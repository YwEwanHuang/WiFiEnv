"""Scripted / fixed-parameter Controller.

Run a Wi-Fi scenario without any RL agent — the simulator is driven by a
fixed configuration (channel, Tx power, CCA per epoch).

Usage:
    from wifi_simulator.controllers.scripted import ScriptedRunner

    runner = ScriptedRunner(
        sim=sim,
        decision_interval_ns=4_500_000,   # 4.5 ms per decision step
    )
    # Fixed channel per AP (AP0 → channel 0, AP1 → channel 0, ...)
    runner.set_ap_channel({0: 0, 1: 0, 2: 1, 3: 2})
    # Fixed Tx power per (AP, channel) in dBm
    runner.set_ap_channel_power({0: {0: 20.0}, 1: {0: 20.0}, 2: {1: 20.0}, 3: {2: 20.0}})
    # Fixed CCA per AP in dBm
    runner.set_ap_cca({0: -82.0, 1: -82.0, 2: -82.0, 3: -82.0})

    results = runner.run()   # runs until sim duration, returns per-epoch list

    for epoch in results:
        print(epoch["throughput_mbps"], epoch["queue_len"])

Each epoch returns:
    throughput_mbps, collisions, retries, drops,
    latency_mean_us, latency_p95_us, queue_len, epoch_index
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EpochResult:
    epoch_index: int
    interval_s: float
    now_ns: int
    # per-link throughput from delta
    throughput_mbps: float
    collisions: int
    retries: int
    drops: int
    latency_mean_us: float
    latency_p95_us: float
    queue_len: dict[int, int]


class ScriptedRunner:
    """Fixed-parameter simulator driver.

    The runner owns no RL state. It just:
      1. Applies the registered channel / power / CCA settings.
      2. Calls sim.run_for(decision_interval_ns).
      3. Yields delta metrics.
    """

    def __init__(
        self,
        sim,                          # wifi_simulator.core.simulator.Simulator
        decision_interval_ns: int = 4_500_000,
    ) -> None:
        self.sim = sim
        self.ctrl = sim._controller  if hasattr(sim, '_controller') else None  # noqa: E501
        # Fallback: use Controller if available
        if self.ctrl is None:
            from wifi_simulator.controllers.controller import Controller
            self.ctrl = Controller(sim)

        self.decision_interval_ns = decision_interval_ns
        self._ap_channel: dict[int, int] = {}   # ap_id → channel_id
        self._ap_channel_power: dict[int, dict[int, float]] = {}  # ap_id → {ch → dbm}
        self._ap_cca: dict[int, float] = {}     # ap_id → cca_dbm

    # ---- configuration ---------------------------------------------------

    def set_ap_channel(self, mapping: dict[int, int]) -> None:
        """Map: ap_id → channel_id to activate for this AP's link(s).

        Only relevant when an AP has multiple links (one per channel).
        """
        self._ap_channel = dict(mapping)

    def set_ap_channel_power(self, mapping: dict[int, dict[int, float]]) -> None:
        """Map: ap_id → {channel_id → tx_power_dbm}."""
        self._ap_channel_power = {k: dict(v) for k, v in mapping.items()}

    def set_ap_cca(self, mapping: dict[int, float]) -> None:
        """Map: ap_id → cca_threshold_dbm."""
        self._ap_cca = dict(mapping)

    # ---- apply settings ---------------------------------------------------

    def _apply_settings(self) -> None:
        """Write current channel / power / CCA to all MACs."""
        ctrl = self.ctrl
        # CCA per AP
        for ap_id, cca_dbm in self._ap_cca.items():
            ctrl.set_cca_for_ap(ap_id, cca_dbm)
        # Channel + power per (AP, channel)
        for ap_id, ch_power in self._ap_channel_power.items():
            for channel_id, power_dbm in ch_power.items():
                ctrl.set_tx_power_for_ap_channel(ap_id, channel_id, power_dbm)

    # ---- run --------------------------------------------------------------

    def run(self) -> list[EpochResult]:
        """Run until simulator duration is reached.

        Returns one EpochResult per decision_interval.
        """
        results: list[EpochResult] = []
        epoch_index = 0

        while self.sim.loop.now_ns < int(self.sim.duration_s * 1e9):
            # Apply settings before the epoch
            self._apply_settings()
            # Advance simulation
            delta = self.sim.run_for(self.decision_interval_ns)
            per_link = delta.get("delta", {}).get("per_link", {})
            interval_s = delta.get("interval_s", self.decision_interval_ns * 1e-9)

            # Aggregate across all links for simplicity
            total_success = sum(lm.get("success", 0) for lm in per_link.values())
            total_bytes  = sum(lm.get("success_bytes", 0) for lm in per_link.values())
            total_col    = sum(lm.get("collision", 0) for lm in per_link.values())
            total_retry  = sum(lm.get("retry", 0) for lm in per_link.values())
            total_drop   = sum(lm.get("drop", 0) for lm in per_link.values())
            tp_mbps = total_bytes * 8 / interval_s / 1e6 if interval_s > 0 else 0.0

            delta_metrics = delta.get("delta", {})
            results.append(EpochResult(
                epoch_index=epoch_index,
                interval_s=interval_s,
                now_ns=delta.get("now_ns", 0),
                throughput_mbps=tp_mbps,
                collisions=total_col,
                retries=total_retry,
                drops=total_drop,
                latency_mean_us=delta_metrics.get("latency_mean_us", 0.0),
                latency_p95_us=delta_metrics.get("latency_p95_us", 0.0),
                queue_len=dict(delta.get("queue_len", {})),
            ))
            epoch_index += 1

        return results

    def run_summary(self) -> dict:
        """Run and return a one-shot summary (no per-epoch breakdown)."""
        epochs = self.run()
        if not epochs:
            return {}
        total_bytes = sum(
            e.throughput_mbps * e.interval_s * 1e6 / 8 for e in epochs
        )
        total_s = sum(e.interval_s for e in epochs)
        total_coll = sum(e.collisions for e in epochs)
        total_retry = sum(e.retries for e in epochs)
        total_drop = sum(e.drops for e in epochs)
        return {
            "total_throughput_mbps": total_bytes * 8 / total_s / 1e6 if total_s > 0 else 0,
            "total_packets": sum(
                e.throughput_mbps * e.interval_s * 1e6 / (2304 * 8)
                for e in epochs
            ),
            "total_collisions": total_coll,
            "total_retries": total_retry,
            "total_drops": total_drop,
            "epochs": len(epochs),
            "last_epoch": {
                "latency_mean_us": epochs[-1].latency_mean_us,
                "latency_p95_us": epochs[-1].latency_p95_us,
                "queue_len": epochs[-1].queue_len,
            },
        }