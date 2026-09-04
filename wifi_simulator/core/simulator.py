"""Top-level simulator driver.

Sprint 2 scope:
    - Multi-BSS: multiple AP / STA pairs across multiple channels
    - Each AP runs its own MacStation with its own queue and traffic
    - Realistic interferer traffic: interferers also run CSMA/CA
    - Optional Controller with configurable decision_interval
    - ChannelStateRegistry for per-channel active-TX accounting

Not in scope (Sprint 3+): MLO, OFDMA, SR, OBSS_PD, capture effect, etc.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from wifi_simulator.core.channel_registry import ChannelStateRegistry
from wifi_simulator.core.event_loop import EventLoop
from wifi_simulator.core.rng import Rng
from wifi_simulator.features.mlo import MldConfig, MldSteering, MldTraffic
from wifi_simulator.mac.mac import MacStation
from wifi_simulator.mac.timing import SLOT_TIME_NS
from wifi_simulator.metrics.collector import MetricsCollector
from wifi_simulator.metrics.events import EventTrace
from wifi_simulator.network.queue import PacketQueue
from wifi_simulator.network.traffic import PoissonTraffic
from wifi_simulator.phy.path_loss import PathLossModel


@dataclass
class ApStation:
    ap_id: int
    sta_id: int
    pos_ap: tuple[float, float]
    pos_sta: tuple[float, float]
    link_id: int
    channel_id: int
    tx_power_dbm: float = 18.0
    lambda_pps: float = 100.0
    size_bytes: int = 2304
    # Per-link CCA threshold (Sprint 2: per-link, not per-channel).
    cca_threshold_dbm: float = -82.0


@dataclass
class Simulator:
    seed: int
    duration_s: float
    aps: list[ApStation]
    noise_dbm: float = -95.0
    retry_limit: int = 6
    # Default CCA for all APs unless ApStation overrides.
    cca_threshold_dbm: float = -82.0
    # MLO Feature Pack v0 — list of MLD configs. Empty for Frozen Core runs.
    mld_configs: list = field(default_factory=list)

    rng: Rng = field(init=False)
    loop: EventLoop = field(init=False)
    trace: EventTrace = field(init=False)
    metrics: MetricsCollector = field(init=False)
    path_loss: PathLossModel = field(init=False)
    channel_registry: ChannelStateRegistry = field(init=False)
    macs: list[MacStation] = field(init=False)
    queues: list[PacketQueue] = field(init=False)
    traffics: list[PoissonTraffic] = field(init=False)
    _device_positions: dict[int, tuple[float, float]] = field(init=False)
    _duration_ns: int = field(init=False)
    # Incremental epoch tracking: metrics snapshot at epoch start.
    _epoch_start_ns: int = field(init=False, default=0)
    _epoch_start_metrics: dict = field(init=False, default=None)
    # MLO Feature Pack v0 — MLD wiring.
    mld_registry: dict = field(init=False, default_factory=dict)
    _mld_link_set: set = field(init=False, default_factory=set)
    _mld_steerings: dict = field(init=False, default_factory=dict)
    _mld_traffics: list = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.rng = Rng(self.seed)
        self.loop = EventLoop()
        self.trace = EventTrace()
        self.metrics = MetricsCollector()
        self.path_loss = PathLossModel(self.rng)
        self.channel_registry = ChannelStateRegistry()
        self.macs = []
        self.queues = []
        self.traffics = []
        self._device_positions = {}

        # Register each AP/STA position for distance lookup.
        for ap_sta in self.aps:
            self._device_positions[ap_sta.ap_id] = ap_sta.pos_ap
            self._device_positions[ap_sta.sta_id] = ap_sta.pos_sta
            # Pre-register the channel so ChannelState exists before MacStation
            # uses it.
            self.channel_registry.register(ap_sta.channel_id)

        for ap_sta in self.aps:
            queue = PacketQueue(ap_sta.ap_id, ap_sta.link_id)
            self.queues.append(queue)

            mac = MacStation(
                ap_id=ap_sta.ap_id,
                link_id=ap_sta.link_id,
                sta_id=ap_sta.sta_id,
                channel_id=ap_sta.channel_id,
                rng=self.rng,
                event_loop=self.loop,
                queue=queue,
                trace=self.trace,
                metrics=self.metrics,
                channel_state=self.channel_registry,
                path_loss=self.path_loss,
                get_distance_m=self._distance,
                tx_power_dbm=ap_sta.tx_power_dbm,
                cca_threshold_dbm=ap_sta.cca_threshold_dbm,
                noise_dbm=self.noise_dbm,
                retry_limit=self.retry_limit,
            )
            self.macs.append(mac)

            def make_on_arrival(m: MacStation):
                def _on_arrival(now_ns: int) -> None:
                    m.on_packet_arrival(now_ns)
                return _on_arrival

            traffic = PoissonTraffic(
                ap_id=ap_sta.ap_id,
                link_id=ap_sta.link_id,
                dst=ap_sta.sta_id,
                lambda_pps=ap_sta.lambda_pps,
                size_bytes=ap_sta.size_bytes,
                queue=queue,
                rng=self.rng,
                loop=self.loop,
                on_arrival=make_on_arrival(mac),
            )
            self.traffics.append(traffic)

        # ---- MLO Feature Pack v0 wiring --------------------------
        # 1. Register MLD configs and tag MACs with mld_id / mld_mode.
        self.mld_registry = {c.mld_id: c for c in self.mld_configs}
        self._mld_link_set = set()
        for cfg in self.mld_configs:
            for lid in cfg.link_ids:
                if lid not in self._mld_link_set:
                    self._mld_link_set.add(lid)
        for cfg in self.mld_configs:
            for m in self.macs:
                if m.link_id in cfg.link_ids:
                    m.mld_id = cfg.mld_id
                    m.mld_mode = cfg.mode

        # 2. Zero per-link PoissonTraffic for MLD-owned links — arrivals
        #    are driven by MldTraffic below.
        for ap_sta, traffic in zip(self.aps, self.traffics):
            if ap_sta.link_id in self._mld_link_set:
                traffic.lambda_pps = 0.0

        # 3. Build one MldTraffic per MLD; it steers packets into the
        #    MLD's per-link queues and triggers each link's MAC.
        self._mld_steerings = {
            cfg.mld_id: MldSteering(cfg) for cfg in self.mld_configs
        }
        self._mld_traffics = []
        queue_by_link = {q.link_id: q for q in self.queues}
        mac_by_link = {m.link_id: m for m in self.macs}
        for cfg in self.mld_configs:
            # Use the first listed link's ApStation as the basis for
            # lambda_pps / size_bytes / dst. Per-link queues/MACs are
            # looked up by link_id regardless of aps list order.
            base_link_id = cfg.link_ids[0]
            base_ap_sta = next(
                a for a in self.aps if a.link_id == base_link_id
            )
            link_queues = {lid: queue_by_link[lid] for lid in cfg.link_ids}
            link_macs = {lid: mac_by_link[lid] for lid in cfg.link_ids}
            mt = MldTraffic(
                ap_id=cfg.ap_id,
                mld_id=cfg.mld_id,
                link_queues=link_queues,
                link_macs=link_macs,
                sta_id=base_ap_sta.sta_id,
                lambda_pps=base_ap_sta.lambda_pps,
                size_bytes=base_ap_sta.size_bytes,
                steering=self._mld_steerings[cfg.mld_id],
                rng=self.rng,
                loop=self.loop,
            )
            self._mld_traffics.append(mt)

    def _distance(self, a: int, b: int) -> float:
        pa = self._device_positions.get(a, (0.0, 0.0))
        pb = self._device_positions.get(b, (0.0, 0.0))
        return _euclid(pa, pb)

    # ---- run ---------------------------------------------------------

    def run(self, prefill_packets: int = 0, disable_traffic: bool = False) -> dict:
        """Run the simulation.

        prefill_packets: if > 0, enqueue this many packets per AP at t=0
            (so the queue starts saturated). Useful for measuring steady-state
            saturation throughput without waiting for the queue to fill.
        disable_traffic: if True, do not start traffic generators (use with
            prefill).
        """
        self._duration_ns = int(self.duration_s * 1e9)

        if prefill_packets > 0:
            for q, m in zip(self.queues, self.macs):
                for _ in range(prefill_packets):
                    p = q.enqueue(q.ap_id, q.ap_id + 10, 2304, 0)
                m.on_packet_arrival(0)

        self.loop.schedule(0, "SLOT_BOUNDARY", self._on_slot_boundary)

        if not disable_traffic:
            for t in self.traffics:
                t.start_traffic(0)
            for t in self._mld_traffics:
                t.start_traffic(0)

        self.loop.run_until(self._duration_ns)

        for t in self.traffics:
            t.stop()

        summary = self.metrics.summary(self._duration_ns)
        summary["channel_utilization"] = self.channel_utilization()
        return summary

    def channel_utilization(self) -> dict[int, float]:
        """Per-channel utilization in [0, 1] at the current sim time.

        Utilization is the fraction of sim time the channel was busy with
        active transmissions (excluding CCA detection outside TX).
        """
        out: dict[int, float] = {}
        now_ns = self.loop.now_ns
        for ch_id in self.channel_registry.all_channels():
            cs = self.channel_registry.get(ch_id)
            out[ch_id] = cs.utilization(self._duration_ns, now_ns)
        return out

    # ---- run_for (epoch-bounded) ---------------------------------------------

    def run_for(self, decision_interval_ns: int) -> dict:
        """Run for one decision_interval (epoch).

        Returns delta metrics (throughput / collision / retry / drop / latency)
        accrued during this epoch, plus current queue lengths per link.

        The first call to run_for() starts traffic generators if not already
        running. Subsequent calls continue from where the previous one ended.
        Use reset() to restart from scratch.
        """
        target_ns = self._epoch_start_ns + decision_interval_ns
        if target_ns <= self.loop.now_ns:
            # Zero-length epoch — return zeros.
            return self._delta_metrics({}, decision_interval_ns)

        # Take a metrics snapshot before running.
        before = self._snapshot()

        if self._epoch_start_ns == 0:
            # First epoch — schedule slot boundary if not already scheduled.
            # Only schedule once; the slot handler re-schedules itself.
            self.loop.schedule(0, "SLOT_BOUNDARY", self._on_slot_boundary)
            for t in self.traffics:
                t.start_traffic(0)
            for t in self._mld_traffics:
                t.start_traffic(0)

        self.loop.run_until(target_ns)

        self._epoch_start_ns = target_ns
        after = self._snapshot()
        self._epoch_start_metrics = after

        return self._delta_metrics(before, decision_interval_ns, before)

    def reset(self) -> None:
        """Reset all state: event loop, metrics, queues, MACs, traffic.

        After reset(), run_for() starts fresh (traffic generators stopped
        until the first run_for() call).
        """
        self.loop.clear()
        self.metrics = MetricsCollector()
        for q in self.queues:
            q.clear()
        for m in self.macs:
            m.reset()
        for s in self._mld_steerings.values():
            s.reset()
        self._epoch_start_ns = 0
        self._epoch_start_metrics = None

    def _snapshot(self) -> dict:
        """Take a snapshot of current metrics and queue state."""
        metrics = self.metrics.summary(self.loop.now_ns)
        queue_snapshot = {}
        for m in self.macs:
            queue_snapshot[m.ap_id] = len(m.queue)
        return {"metrics": metrics, "queue_len": queue_snapshot,
                "now_ns": self.loop.now_ns}

    def _delta_metrics(self, before: dict,
                       interval_ns: int,
                       epoch_start: dict | None = None) -> dict:
        """Compute delta metrics between two snapshots."""
        if not before or "metrics" not in before:
            # No 'before' snapshot — return current metrics as-is (epoch 0).
            cur = self.metrics.summary(interval_ns)
            queue_snapshot = {m.ap_id: len(m.queue) for m in self.macs}
            interval_s = interval_ns * 1e-9 if interval_ns > 0 else 0.0
            return {"delta": cur, "queue_len": queue_snapshot,
                    "now_ns": self.loop.now_ns, "interval_s": interval_s}
        b_metrics = before["metrics"]
        a_metrics = self.metrics.summary(self.loop.now_ns)
        interval_s = interval_ns * 1e-9

        # Delta per link.
        delta_link = {}
        for lid in set(list(b_metrics["per_link"]) +
                      list(a_metrics["per_link"])):
            b = b_metrics["per_link"].get(lid, {})
            a = a_metrics["per_link"].get(lid, {})
            delta_link[lid] = {
                "success": a.get("success", 0) - b.get("success", 0),
                "collision": a.get("collision", 0) - b.get("collision", 0),
                "fail_phy": a.get("fail_phy", 0) - b.get("fail_phy", 0),
                "fail_no_ack": a.get("fail_no_ack", 0) -
                                b.get("fail_no_ack", 0),
                "retry": a.get("retry", 0) - b.get("retry", 0),
                "drop": a.get("drop", 0) - b.get("drop", 0),
                "tx_attempts": a.get("tx_attempts", 0) -
                                b.get("tx_attempts", 0),
            }
            # Absolute bytes sent in this epoch.
            delta_link[lid]["success_bytes"] = (
                a.get("success_bytes", 0) - b.get("success_bytes", 0)
                if "success_bytes" in a else 0
            )
            delta_link[lid]["throughput_mbps"] = (
                delta_link[lid]["success_bytes"] * 8 / interval_s / 1e6
                if interval_s > 0 else 0.0
            )

        # Delta latency: approximate from current snapshot (not delta-aware).
        # Use current latencies as a proxy; true epoch-latency needs per-epoch
        # packet tracking which is on-demand.
        return {
            "delta": {
                "per_link": delta_link,
                "total_success":
                    a_metrics["total_success_packets"] -
                    b_metrics["total_success_packets"],
                "total_drops":
                    a_metrics["total_drop_packets"] -
                    b_metrics["total_drop_packets"],
                "latency_mean_us": a_metrics.get("latency_mean_us", 0.0),
                "latency_p95_us": a_metrics.get("latency_p95_us", 0.0),
            },
            "queue_len": {m.ap_id: len(m.queue) for m in self.macs},
            "now_ns": self.loop.now_ns,
            "interval_s": interval_s,
        }

    def _on_slot_boundary(self) -> None:
        """Two-phase slot boundary.

        Phase 1: for each channel, snapshot its busy state, then ask each MAC
                 on that channel to PLAN its slot action.
        Phase 2: commit any pending TX starts.

        MLO Feature Pack v0 — NSTR: the single-radio invariant is enforced
        at the MldTraffic arrival layer (only one link of an NSTR MLD is
        woken from IDLE at a time). Once a link is awake, its MAC runs
        independent CSMA/CA on its own channel — no peer-state busy
        override is needed here, and applying one would cause self-deadlock
        (a MAC in DIFS_WAIT would block itself).
        """
        now_ns = self.loop.now_ns
        # Per-link channel busy. Keyed by link_id (not ap_id) because
        # multi-link APs/MLDs share an ap_id across distinct channels; the
        # earlier ap_id-keyed dict silently overwrote per-channel state.
        busy_by_link: dict[int, bool] = {}
        for m in self.macs:
            cs = self.channel_registry.get(m.channel_id)
            busy_by_link[m.link_id] = cs.is_busy_at(
                now_ns, exclude_ap=m.ap_id
            )

        for m in self.macs:
            m.plan_slot(now_ns, busy_by_link[m.link_id])
        for m in self.macs:
            m.commit_slot(now_ns)
        # Mark simultaneous-start collisions per channel.
        for ch_id in self.channel_registry.all_channels():
            self.channel_registry.get(ch_id).mark_collisions_at_slot(now_ns)
        self.loop.schedule(now_ns + SLOT_TIME_NS, "SLOT_BOUNDARY",
                           self._on_slot_boundary)


def _euclid(p: tuple[float, float], q: tuple[float, float]) -> float:
    return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2)