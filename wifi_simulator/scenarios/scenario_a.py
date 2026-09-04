"""Scenario A: 1 transmitter, no competitor.

Setup:
    - 1 AP, 1 STA, single channel.
    - AP at (0, 0), STA at (10, 0).
    - AP saturated: lambda_pps set high enough that the queue never empties.

Expected behavior:
    - CCA / BACKOFF / TX / ACK events fire.
    - No collision events.
    - Throughput bounded by `T_data / (T_data + DIFS + E[BO]*slot + SIFS + ACK)`.
"""
from __future__ import annotations

from wifi_simulator.core.simulator import ApStation, Simulator


def run(duration_s: float = 10.0, seed: int = 2024) -> dict:
    sim = Simulator(
        seed=seed,
        duration_s=duration_s,
        aps=[
            ApStation(
                ap_id=0,
                sta_id=10,
                pos_ap=(0.0, 0.0),
                pos_sta=(10.0, 0.0),
                link_id=0,
                channel_id=0,
                tx_power_dbm=18.0,
                lambda_pps=100000.0,   # very high to keep queue saturated
                size_bytes=2304,
            ),
        ],
    )
    return sim.run()


if __name__ == "__main__":
    import json
    summary = run()
    print(json.dumps(summary, indent=2, default=float))