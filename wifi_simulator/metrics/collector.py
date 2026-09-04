"""Metrics collector: throughput, latency, collision/retry/drop counters."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from wifi_simulator.network.queue import Packet


@dataclass
class LinkMetrics:
    success_count: int = 0
    success_bytes: int = 0
    collision_count: int = 0
    fail_phy_count: int = 0
    fail_no_ack_count: int = 0
    retry_count: int = 0
    drop_count: int = 0
    tx_attempt_count: int = 0
    latencies_ns: list[int] = field(default_factory=list)


class MetricsCollector:
    def __init__(self) -> None:
        self._per_link: dict[int, LinkMetrics] = {}

    def _lm(self, link_id: int) -> LinkMetrics:
        if link_id not in self._per_link:
            self._per_link[link_id] = LinkMetrics()
        return self._per_link[link_id]

    def record_tx_attempt(self, link_id: int) -> None:
        self._lm(link_id).tx_attempt_count += 1

    def record_success(self, p: Packet) -> None:
        lm = self._lm(p.link_id)
        lm.success_count += 1
        lm.success_bytes += p.size_bytes
        if p.success_time_ns is not None:
            lm.latencies_ns.append(p.latency_ns)

    def record_collision(self, link_id: int) -> None:
        self._lm(link_id).collision_count += 1

    def record_fail_phy(self, link_id: int) -> None:
        self._lm(link_id).fail_phy_count += 1

    def record_fail_no_ack(self, link_id: int) -> None:
        self._lm(link_id).fail_no_ack_count += 1

    def record_retry(self, link_id: int) -> None:
        self._lm(link_id).retry_count += 1

    def record_drop(self, p: Packet) -> None:
        self._lm(p.link_id).drop_count += 1

    def total_success_bytes(self) -> int:
        return sum(lm.success_bytes for lm in self._per_link.values())

    def total_success_count(self) -> int:
        return sum(lm.success_count for lm in self._per_link.values())

    def total_drop_count(self) -> int:
        return sum(lm.drop_count for lm in self._per_link.values())

    def all_latencies_ns(self) -> Iterable[int]:
        for lm in self._per_link.values():
            yield from lm.latencies_ns

    def link_throughput_bps(self, link_id: int, duration_ns: int) -> float:
        if duration_ns <= 0:
            return 0.0
        return self._lm(link_id).success_bytes * 8 / (duration_ns * 1e-9)

    def summary(self, duration_ns: int) -> dict:
        all_lat = sorted(self.all_latencies_ns())
        n = len(all_lat)
        total_bytes = self.total_success_bytes()
        total_drops = self.total_drop_count()
        duration_s = duration_ns * 1e-9 if duration_ns > 0 else 1.0
        per_link = {}
        for lid, lm in self._per_link.items():
            per_link[lid] = {
                "success": lm.success_count,
                "success_bytes": lm.success_bytes,
                "collision": lm.collision_count,
                "fail_phy": lm.fail_phy_count,
                "fail_no_ack": lm.fail_no_ack_count,
                "retry": lm.retry_count,
                "drop": lm.drop_count,
                "tx_attempts": lm.tx_attempt_count,
                "throughput_bps": lm.success_bytes * 8 / duration_s,
            }
        return {
            "duration_s": duration_s,
            "total_throughput_bps": total_bytes * 8 / duration_s,
            "total_success_packets": self.total_success_count(),
            "total_drop_packets": total_drops,
            "latency_mean_us": (sum(all_lat) / n / 1000.0) if n else 0.0,
            "latency_p50_us": (all_lat[n // 2] / 1000.0) if n else 0.0,
            "latency_p95_us": (all_lat[min(n - 1, int(n * 0.95))] / 1000.0) if n else 0.0,
            "per_link": per_link,
        }