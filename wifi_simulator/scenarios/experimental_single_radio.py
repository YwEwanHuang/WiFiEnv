"""EXPERIMENTAL — NOT PART OF MLO v0 FORMAL CAPABILITY.

This scenario is a documentation/demo of the `single_radio`
(mutual-exclusion) mode that ships alongside MLO v0. It is NOT a
faithful model of IEEE 802.11be NSTR link-pair behaviour and must
NOT be cited as NSTR in research output.

Setup (same topology as M1, two-link MLD on orthogonal channels):

    - 1 MLD (ap_id=0) with 2 links on orthogonal channels (ch0, ch1).
    - Saturated Poisson traffic at the MLD level.
    - `single_radio` mode: when any link is non-IDLE, peer link's MAC
      is not woken by `MldTraffic`. This is the abstract single-radio
      constraint — NOT IEEE NSTR.

Observed behaviour:

    - In saturation, one link captures the MLD's radio; the peer's
      queue grows monotonically and is starved (zero TX_START events
      on the starved link).
    - Aggregate throughput is bounded by single-link saturation.
    - This mode is included as a baseline for future IEEE-NSTR work.

For the formal MLO v0 capability, see `m1_two_link_str.py` (STR).
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
                lambda_pps=100000.0,
                size_bytes=2304,
            ),
            ApStation(
                ap_id=0, sta_id=11,
                pos_ap=(0.0, 0.0), pos_sta=(10.0, 0.0),
                link_id=1, channel_id=1,
                tx_power_dbm=18.0,
                lambda_pps=100000.0,
                size_bytes=2304,
            ),
        ],
        mld_configs=[
            MldConfig(
                mld_id=0,
                ap_id=0,
                link_ids=[0, 1],
                mode="single_radio",  # experimental
                steering="round_robin",
            ),
        ],
    )
    return sim.run()


if __name__ == "__main__":
    summary = run()
    print(json.dumps(summary, indent=2, default=float))