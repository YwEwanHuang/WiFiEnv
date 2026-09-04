"""Run all Sprint 1 validation tests and Scenarios A/B.

This is the Sprint 1 gate. Prints a one-page summary.
"""
from __future__ import annotations

import json
import sys

from wifi_simulator.scenarios.scenario_a import run as run_a
from wifi_simulator.scenarios.scenario_b import run as run_b


def main() -> int:
    print("=" * 72)
    print("Sprint 1 validation: primitives")
    print("=" * 72)
    from wifi_simulator.tests.test_primitives import (
        test_timing_constants,
        test_path_loss_d1m,
        test_path_loss_correlated_shadowing,
        test_queue_enq_deq,
        test_mcs_ideal_select,
        test_airtime_payload_only,
        test_backoff_draw,
        test_backoff_formula_values,
        test_sinr_linear_sum,
        test_event_loop_no_negative_time,
        test_rng_reproducibility,
    )
    test_timing_constants()
    test_path_loss_d1m()
    test_path_loss_correlated_shadowing()
    test_queue_enq_deq()
    test_mcs_ideal_select()
    test_airtime_payload_only()
    test_backoff_draw()
    test_backoff_formula_values()
    test_sinr_linear_sum()
    test_event_loop_no_negative_time()
    test_rng_reproducibility()

    print()
    print("=" * 72)
    print("Sprint 1 validation: CSMA/CCA")
    print("=" * 72)
    from wifi_simulator.tests.test_freeze_resume import (
        test_freeze_resume_deterministic,
        test_retry_exhaustion,
        test_scenario_a_no_contention,
        test_scenario_b_two_ap_same_channel,
        test_cca_energy,
    )
    test_freeze_resume_deterministic()
    test_retry_exhaustion()
    test_scenario_a_no_contention()
    test_scenario_b_two_ap_same_channel()
    test_cca_energy()

    print()
    print("=" * 72)
    print("Scenario A: 1 transmitter, no competitor (5 sec, saturated)")
    print("=" * 72)
    s_a = run_a(duration_s=5.0)
    print(json.dumps(s_a, indent=2, default=float))

    print()
    print("=" * 72)
    print("Scenario B: 2 saturated contenders, same channel (5 sec)")
    print("=" * 72)
    s_b = run_b(duration_s=5.0)
    print(json.dumps(s_b, indent=2, default=float))

    print()
    print("=" * 72)
    print("Sprint 1 summary")
    print("=" * 72)
    print(f"Scenario A throughput: {s_a['total_throughput_bps']/1e6:.2f} Mbps, "
          f"success={s_a['total_success_packets']}, "
          f"collision={s_a['per_link'][0]['collision']}, "
          f"retry={s_a['per_link'][0]['retry']}, "
          f"drop={s_a['total_drop_packets']}")
    s_b_ap0 = s_b['per_link'][0]
    s_b_ap1 = s_b['per_link'][1]
    print(f"Scenario B throughput: {s_b['total_throughput_bps']/1e6:.2f} Mbps, "
          f"AP0 success={s_b_ap0['success']}, "
          f"AP1 success={s_b_ap1['success']}, "
          f"AP0 collisions={s_b_ap0['collision']}, "
          f"AP1 collisions={s_b_ap1['collision']}, "
          f"total retries={s_b_ap0['retry']+s_b_ap1['retry']}")

    # Final pass/fail
    ok_a = (s_a['per_link'][0]['collision'] == 0
            and s_a['per_link'][0]['retry'] == 0
            and s_a['total_drop_packets'] == 0)
    ok_b = (s_b_ap0['collision'] > 0 and s_b_ap1['collision'] > 0
            and s_b_ap0['retry'] > 0 and s_b_ap1['retry'] > 0)
    print()
    print(f"Scenario A: {'PASS' if ok_a else 'FAIL'} (no collisions expected)")
    print(f"Scenario B: {'PASS' if ok_b else 'FAIL'} (collisions + retries expected)")
    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    sys.exit(main())