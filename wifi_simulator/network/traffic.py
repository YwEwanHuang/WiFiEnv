"""Traffic generators.

Sprint 1 ships Poisson arrivals only. CBR / on-off / trace-driven are
documented in RESEARCH_ENV_DESIGN.md §8.2 and arrive in later sprints.
"""
from __future__ import annotations

import math
from typing import Callable

from wifi_simulator.core.event_loop import EventLoop
from wifi_simulator.core.rng import Rng
from wifi_simulator.network.queue import PacketQueue


class PoissonTraffic:
    """Poisson packet arrivals scheduled as PACKET_ARRIVAL events on the loop."""

    def __init__(
        self,
        ap_id: int,
        link_id: int,
        dst: int,
        lambda_pps: float,        # packets per second
        size_bytes: int,
        queue: PacketQueue,
        rng: Rng,
        loop: EventLoop,
        on_arrival: Callable[[int], None],   # called with now_ns
    ) -> None:
        self.ap_id = ap_id
        self.link_id = link_id
        self.dst = dst
        self.lambda_pps = lambda_pps
        self.size_bytes = size_bytes
        self.queue = queue
        self.rng = rng
        self.loop = loop
        self.on_arrival = on_arrival
        self._enabled: bool = False

    def start_traffic(self, now_ns: int) -> None:
        self._enabled = True
        self._schedule_next_arrival(now_ns)

    def stop(self) -> None:
        self._enabled = False

    def _schedule_next_arrival(self, now_ns: int) -> None:
        if not self._enabled:
            return
        # inter-arrival ~ Exponential(mean = 1/lambda)
        if self.lambda_pps <= 0:
            # No traffic
            return
        delta_s = self.rng.exponential(1.0 / self.lambda_pps)
        delta_ns = max(1, int(round(delta_s * 1e9)))
        next_time_ns = now_ns + delta_ns

        def _arrival() -> None:
            self._fire_arrival()
        self.loop.schedule(next_time_ns, "PACKET_ARRIVAL", _arrival)

    def _fire_arrival(self) -> None:
        now = self.loop.now_ns
        p = self.queue.enqueue(self.ap_id, self.dst, self.size_bytes, now)
        self.on_arrival(now)
        self._schedule_next_arrival(now)