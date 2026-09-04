"""Multi-BSS scenario: legacy Project_3 'Normal' (4 APs, 3 channels).

Mirrors `config/config.txt`:
    AP positions: (50, 50), (30, 50), (70, 50), (50, 70)
    targetAPs   : [0]  (AP0 is the controller; AP1-3 are interferers)
    n_channels  : 3
    used_channel:
        AP0 -> [0, 1, 2]  (target can pick any; default = channel 0)
        AP1 -> [0]         (interferer on channel 0)
        AP2 -> [1]         (interferer on channel 1)
        AP3 -> [2]         (interferer on channel 2)
    arr_mean   : 500 (binomial)
    timeslot   : 4500e-6 s = 4.5 ms
    pt_max     : 20 dBm
    seed       : 6

STAs: 4 per AP at (±2, 0), (0, ±2) offsets (legacy `gen_sta_position`).

In Sprint 2, each AP has ONE MacStation + ONE STA (we keep the basic
multi-BSS shape but collapse STAs to 1 per AP for simplicity; full 4-STAs-
per-AP support is on-demand per paper). The interferer APs are full
MacStations running CSMA/CA, so they do NOT transmit at pt_max always-on
(this is the third Sprint 1 abstraction fix).
"""
from __future__ import annotations

from wifi_simulator.core.simulator import ApStation, Simulator


# AP positions from config.txt
AP_POS = [(50.0, 50.0), (30.0, 50.0), (70.0, 50.0), (50.0, 70.0)]


def sta_pos_for_ap(ap_pos: tuple[float, float]) -> list[tuple[float, float]]:
    """Mirrors legacy `gen_sta_position` (Sprint 2: 4 STAs per AP)."""
    x, y = ap_pos
    return [(x - 2.0, y), (x, y - 2.0), (x, y + 2.0), (x + 2.0, y)]


def make_aps(lambda_pps: float = 500.0, target_channel: int = 0) -> list[ApStation]:
    """Build the 4-AP Normal scenario.

    Each AP has ONE AP->STA link (collapsed; Sprint 2 minimum). The
    interferer APs (1, 2, 3) are assigned to channels 0, 1, 2 respectively
    (matching legacy `used_channel`). The target AP (AP0) starts on
    `target_channel`.
    """
    aps = []
    # AP0 (target) — start on `target_channel`
    aps.append(ApStation(
        ap_id=0, sta_id=10,
        pos_ap=AP_POS[0], pos_sta=sta_pos_for_ap(AP_POS[0])[0],
        link_id=0, channel_id=target_channel,
        tx_power_dbm=20.0, lambda_pps=lambda_pps, size_bytes=2304,
    ))
    # AP1 (interferer) on channel 0
    aps.append(ApStation(
        ap_id=1, sta_id=11,
        pos_ap=AP_POS[1], pos_sta=sta_pos_for_ap(AP_POS[1])[0],
        link_id=1, channel_id=0,
        tx_power_dbm=20.0, lambda_pps=lambda_pps, size_bytes=2304,
    ))
    # AP2 (interferer) on channel 1
    aps.append(ApStation(
        ap_id=2, sta_id=12,
        pos_ap=AP_POS[2], pos_sta=sta_pos_for_ap(AP_POS[2])[0],
        link_id=2, channel_id=1,
        tx_power_dbm=20.0, lambda_pps=lambda_pps, size_bytes=2304,
    ))
    # AP3 (interferer) on channel 2
    aps.append(ApStation(
        ap_id=3, sta_id=13,
        pos_ap=AP_POS[3], pos_sta=sta_pos_for_ap(AP_POS[3])[0],
        link_id=3, channel_id=2,
        tx_power_dbm=20.0, lambda_pps=lambda_pps, size_bytes=2304,
    ))
    return aps


def run(duration_s: float = 4.5, seed: int = 6, lambda_pps: float = 500.0,
        target_channel: int = 0) -> dict:
    """Run the 4-AP Normal scenario with the new env.

    Default target channel is 0 (matches legacy `used_channel` for AP0 is
    free / N). For comparison with legacy, the target channel is fixed
    across the run (no decision_interval loop yet).
    """
    sim = Simulator(
        seed=seed,
        duration_s=duration_s,
        aps=make_aps(lambda_pps=lambda_pps, target_channel=target_channel),
    )
    return sim.run()
