"""Scenario B: 2 saturated contenders, same channel.

Setup:
    - 2 AP / STA pairs, both on channel 0.
    - AP0 -> STA0, AP1 -> STA1.
    - Both APs saturated.

Expected behavior:
    - CCA / BACKOFF / TX / ACK / COLLISION / RETRY events fire.
    - Collisions happen when backoff counters tie.
    - Per-AP throughput is comparable (within ±25%).
    - Aggregate throughput is strictly lower than single-AP saturated
      throughput from Scenario A.
    - Collision / retry counts are non-zero.
"""
from __future__ import annotations

from wifi_simulator.core.simulator import ApStation, Simulator


def run(duration_s: float = 5.0, seed: int = 2024) -> dict:
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
                lambda_pps=1000.0,
                size_bytes=2304,
            ),
            ApStation(
                ap_id=1,
                sta_id=11,
                pos_ap=(50.0, 0.0),    # far from AP0's STA (avoid capture)
                pos_sta=(60.0, 0.0),
                link_id=1,
                channel_id=0,
                tx_power_dbm=18.0,
                lambda_pps=1000.0,
                size_bytes=2304,
            ),
        ],
    )
    return sim.run()


if __name__ == "__main__":
    import json
    summary = run()
    print(json.dumps(summary, indent=2, default=float))