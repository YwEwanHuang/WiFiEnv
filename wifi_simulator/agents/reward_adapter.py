"""Map Research Env delta metrics → Legacy reward format.

Legacy reward formula (from env.py `reward()`):
    Reward[ap] = eta_1 * dataRate - eta_2 * Queue[ap]

Where:
    dataRate = sum over channels where CCA passed:
        Shannon(p_signal, p_interference) in Mbps
    Queue[ap] = current queue length (not delta)

Research env provides:
    delta.success: packets delivered this epoch
    delta.queue_len: current queue length per AP
    delta.collision / retry / drop: counts this epoch

We approximate "dataRate" from Research as:
    throughput_mbps = success_packets * packet_size * 8 / epoch_s

The key difference from legacy is that Research's throughput is *actual*
transmitted packets (post-PER, post-collision), not Shannon capacity.

The adapter exposes the Research reward side-by-side with a throughput-only
variant for transparency. Both can be used as the RL reward signal.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RewardResult:
    reward: float          # RL reward for this epoch
    reward_components: dict  # detailed breakdown
    throughput_mbps: float   # actual throughput this epoch
    queue_len: int           # queue length at epoch end
    collisions: int          # collisions this epoch
    retries: int             # retries this epoch
    drops: int               # drops this epoch
    latency_mean_us: float   # mean latency this epoch
    latency_p95_us: float    # p95 latency this epoch


# Default eta values from legacy env.py (overridable).
DEFAULT_ETA_1 = 1.0
DEFAULT_ETA_2 = 0.01
PACKET_SIZE_BYTES = 2304


class RewardAdapter:
    """Compute legacy-format reward from Research Env delta metrics.

    Legacy reward = eta_1 * throughput_mbps - eta_2 * queue_len

    For comparison, also exposes "throughput-only" and "per-link" variants.
    """

    def __init__(self, target_ap: int,
                 eta_1: float = DEFAULT_ETA_1,
                 eta_2: float = DEFAULT_ETA_2,
                 packet_size: int = PACKET_SIZE_BYTES) -> None:
        self.target_ap = target_ap
        self.eta_1 = eta_1
        self.eta_2 = eta_2
        self.packet_size = packet_size

    def compute(self, delta: dict) -> RewardResult:
        """Compute reward from one epoch's delta metrics.

        delta: from Simulator.run_for()
        """
        per_link = delta.get("delta", {}).get("per_link", {})
        interval_s = delta.get("interval_s", 4.5e-3)

        # Get target AP metrics.
        lp = per_link.get(self.target_ap, {})
        success = lp.get("success", 0)
        collisions = lp.get("collision", 0)
        retries = lp.get("retry", 0)
        drops = lp.get("drop", 0)
        throughput_mbps = lp.get("throughput_mbps", 0.0)

        queue_len = delta.get("queue_len", {}).get(self.target_ap, 0)

        # Legacy-format reward.
        reward = self.eta_1 * throughput_mbps - self.eta_2 * queue_len

        return RewardResult(
            reward=reward,
            reward_components={
                "eta_1": self.eta_1,
                "eta_2": self.eta_2,
                "throughput_mbps": throughput_mbps,
                "queue_len": queue_len,
                "success_packets": success,
            },
            throughput_mbps=throughput_mbps,
            queue_len=queue_len,
            collisions=collisions,
            retries=retries,
            drops=drops,
            latency_mean_us=delta.get("delta", {}).get("latency_mean_us", 0.0),
            latency_p95_us=delta.get("delta", {}).get("latency_p95_us", 0.0),
        )