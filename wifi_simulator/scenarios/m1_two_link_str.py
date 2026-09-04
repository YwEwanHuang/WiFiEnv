"""M1 — Two-link STR (Simultaneous TX/RX) scenario.

Setup:
    - 1 MLD (ap_id=0) with 2 links on orthogonal channels (ch0, ch1).
    - 1 STA per link, both co-located at the AP.
    - Saturated Poisson traffic at the MLD level (steering dispatches to
      per-link queues).
    - STR mode: links run their CSMA/CA independently on each channel.
      The MLD does NOT enforce any peer-state busy override, so each
      link contends freely on its own channel.

Validation targets:
    - Both links actually transmit (no starvation).
    - Simultaneous TX: at some slot boundaries, both links start TX in
      the same slot on different channels. Aggregate throughput
      approaches the sum of two single-link saturations.
    - Per-link throughput / latency / queue are normal for a saturated
      independent CSMA/CA link.
    - Packet conservation holds (success + drops <= arrivals).
    - Seeded reproducibility: same seed gives identical numbers.
"""
from __future__ import annotations

import json

from wifi_simulator.core.simulator import ApStation, Simulator
from wifi_simulator.features.mlo import MldConfig


def run(duration_s: float = 5.0, seed: int = 2024) -> dict:
    sim = Simulator(
        seed=seed,
        duration_s=duration_s,
        aps=[
            ApStation(
                ap_id=0, sta_id=10,
                pos_ap=(0.0, 0.0), pos_sta=(10.0, 0.0),
                link_id=0, channel_id=0,
                tx_power_dbm=18.0,
                lambda_pps=100000.0,   # MLD-level saturation
                size_bytes=2304,
            ),
            ApStation(
                ap_id=0, sta_id=11,
                pos_ap=(0.0, 0.0), pos_sta=(10.0, 0.0),
                link_id=1, channel_id=1,
                tx_power_dbm=18.0,
                lambda_pps=100000.0,   # MLD-level saturation
                size_bytes=2304,
            ),
        ],
        mld_configs=[
            MldConfig(
                mld_id=0,
                ap_id=0,
                link_ids=[0, 1],
                mode="STR",
                steering="round_robin",
            ),
        ],
    )
    return sim.run()


if __name__ == "__main__":
    summary = run()
    print(json.dumps(summary, indent=2, default=float))