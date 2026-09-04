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

        self.loop.run_until(self._duration_ns)

        for t in self.traffics:
            t.stop()

        return self.metrics.summary(self._duration_ns)

    def _on_slot_boundary(self) -> None:
        """Two-phase slot boundary.

        Phase 1: for each channel, snapshot its busy state, then ask each MAC
                 on that channel to PLAN its slot action.
        Phase 2: commit any pending TX starts.
        """
        now_ns = self.loop.now_ns
        # Group MACs by channel for the busy snapshot.
        busy_per_mac: dict[int, bool] = {}
        for m in self.macs:
            cs = self.channel_registry.get(m.channel_id)
            busy_per_mac[m.ap_id] = cs.is_busy_at(now_ns, exclude_ap=m.ap_id)
        for m in self.macs:
            m.plan_slot(now_ns, busy_per_mac[m.ap_id])
        for m in self.macs:
            m.commit_slot(now_ns)
        # Mark simultaneous-start collisions per channel.
        for ch_id in self.channel_registry.all_channels():
            self.channel_registry.get(ch_id).mark_collisions_at_slot(now_ns)
        self.loop.schedule(now_ns + SLOT_TIME_NS, "SLOT_BOUNDARY",
                           self._on_slot_boundary)


def _euclid(p: tuple[float, float], q: tuple[float, float]) -> float:
    return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2)