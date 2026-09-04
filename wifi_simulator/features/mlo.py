"""MLO Feature Pack v0 — minimal multi-link device (MLD) capability.

Formal v0 capability (this file's contract):

    * two-link MLD
    * each link runs independent CSMA/CA (STR)
    * per-packet steering: `fixed` or `round_robin`
    * STR mode

Experimental simplified mode shipped alongside v0 for documentation:

    * `single_radio` (mutual exclusion) — when any link of the MLD is
      non-IDLE, peer link's MAC is not woken by MldTraffic. This is NOT
      a faithful model of IEEE 802.11be NSTR link-pair behaviour; it
      captures the abstract single-radio constraint and causes
      starvation of the peer link under saturation. Do NOT cite as
      NSTR in research output. Real NSTR semantics (link-pair sharing,
      NAV across links, restricted TWT, etc.) are deferred.

Out of scope (deferred per project plan):
EMLSR, link switching latency, restricted TWT, advanced MLO sync,
multi-link aggregation, OFDMA / MU-MIMO, 320 MHz, puncturing, SR / OBSS_PD,
EDCA, Block ACK / A-MPDU, mobility, 802.11bn, capture, ns-3 realism.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from wifi_simulator.core.event_loop import EventLoop
from wifi_simulator.core.rng import Rng
from wifi_simulator.network.queue import PacketQueue


@dataclass
class MldConfig:
    """MLD configuration. One MLD = one AP owning `link_ids` of that AP."""

    mld_id: int
    ap_id: int
    link_ids: list[int]
    mode: str = "STR"             # "STR" (formal v0) or "single_radio" (experimental)
    steering: str = "round_robin"  # "fixed" or "round_robin"
    fixed_link_id: Optional[int] = None  # required when steering == "fixed"


class MldSteering:
    """Decide which link of an MLD receives the next packet.

    Pure policy. Holds no sim state. Reset by `reset()` between episodes
    to keep round-robin deterministic across runs with the same seed.
    """

    def __init__(self, cfg: MldConfig) -> None:
        self.cfg = cfg
        self._rr_idx: int = 0

    def pick(self) -> int:
        if self.cfg.steering == "fixed":
            if self.cfg.fixed_link_id is None:
                raise ValueError("fixed_link_id required for fixed steering")
            return self.cfg.fixed_link_id
        if self.cfg.steering == "round_robin":
            if not self.cfg.link_ids:
                raise ValueError("MldConfig.link_ids must be non-empty")
            lid = self.cfg.link_ids[self._rr_idx % len(self.cfg.link_ids)]
            self._rr_idx += 1
            return lid
        raise ValueError(f"unknown MldConfig.steering: {self.cfg.steering}")

    def reset(self) -> None:
        """Reset round-robin counter (deterministic replay across runs)."""
        self._rr_idx = 0


class MldTraffic:
    """Poisson arrivals at the MLD level; steering dispatches each packet
    to a per-link queue and triggers that link's MAC `on_packet_arrival`.

    This replaces the per-link `PoissonTraffic` generators for MLD-owned
    links. Per-link traffics for those links are zeroed in
    `Simulator.__post_init__` so they emit no arrivals.

    Mode behaviour:

    * `"STR"` (formal v0): always wake the destination MAC. Links run
      fully independent CSMA/CA on each channel.
    * `"single_radio"` (experimental demo only): only wake the
      destination MAC if no peer link is currently active. Otherwise
      queue the packet and skip the wake — captures the abstract
      single-radio constraint but causes starvation in saturation.
    """

    def __init__(
        self,
        ap_id: int,
        mld_id: int,
        link_queues: dict[int, PacketQueue],
        link_macs: dict,
        sta_id: int,
        lambda_pps: float,
        size_bytes: int,
        steering: MldSteering,
        rng: Rng,
        loop: EventLoop,
    ) -> None:
        self.ap_id = ap_id
        self.mld_id = mld_id
        self.link_queues = link_queues
        self.link_macs = link_macs
        self.sta_id = sta_id
        self.lambda_pps = lambda_pps
        self.size_bytes = size_bytes
        self.steering = steering
        self.rng = rng
        self.loop = loop
        self._enabled: bool = False

    def start_traffic(self, now_ns: int) -> None:
        self._enabled = True
        self._schedule_next_arrival(now_ns)

    def stop(self) -> None:
        self._enabled = False

    def _schedule_next_arrival(self, now_ns: int) -> None:
        if not self._enabled or self.lambda_pps <= 0:
            return
        # Exponential inter-arrival in seconds; convert to ns.
        delta_s = self.rng.exponential(1.0 / self.lambda_pps)
        delta_ns = max(1, int(round(delta_s * 1e9)))
        next_time_ns = now_ns + delta_ns

        def _arrival() -> None:
            self._fire_arrival()
        self.loop.schedule(next_time_ns, "PACKET_ARRIVAL", _arrival)

    def _fire_arrival(self) -> None:
        now = self.loop.now_ns
        lid = self.steering.pick()
        q = self.link_queues[lid]
        q.enqueue(self.ap_id, self.sta_id, self.size_bytes, now)
        mac = self.link_macs[lid]
        # `single_radio` gate (experimental simplified mode — NOT IEEE NSTR):
        # Only wake the destination MAC when no peer link is active.
        # STR mode skips the gate — links run independently.
        if self.steering.cfg.mode == "single_radio":
            any_peer_active = any(
                m.is_active()
                for lid2, m in self.link_macs.items()
                if lid2 != lid
            )
            if any_peer_active:
                self._schedule_next_arrival(now)
                return
        mac.on_packet_arrival(now)
        self._schedule_next_arrival(now)