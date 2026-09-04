"""Sanity / unit tests for Sprint 1 primitives.

Run with:
    cd Project_3 && python -m wifi_simulator.tests.test_primitives
or:
    cd Project_3 && python -m pytest wifi_simulator/tests/test_primitives.py
"""
from __future__ import annotations

import math
import sys

import numpy as np

from wifi_simulator.core.rng import Rng
from wifi_simulator.mac.timing import (
    ACK_AIRTIME_US,
    CW_MAX,
    CW_MIN,
    DIFS_NS,
    EIFS_NS,
    SIFS_NS,
    SLOT_TIME_NS,
    contention_window,
)
from wifi_simulator.mac.backoff import draw_backoff
from wifi_simulator.network.queue import Packet, PacketQueue
from wifi_simulator.phy.airtime import approximate_packet_airtime_us
from wifi_simulator.phy.mcs import HE_SU_20MHZ_MCS_TABLE, basic_rate_entry, ideal_select
from wifi_simulator.phy.path_loss import PathLossModel
from wifi_simulator.phy.sinr import (
    compute_sinr_db,
    dbm_to_w,
    sum_powers_linear_w,
    thermal_noise_w,
    w_to_dbm,
)


def test_timing_constants():
    # S1: timing constants match citations
    assert SLOT_TIME_NS == 9_000
    assert SIFS_NS == 16_000
    assert DIFS_NS == 34_000
    # EIFS = SIFS + DIFS + ACK_at_6Mbps (~36us rounded)
    assert EIFS_NS > DIFS_NS
    assert ACK_AIRTIME_US == 20
    print("S1 timing constants: PASS")


def test_path_loss_d1m():
    # S2: at d=1m, path loss = freq_loss + shadowing (alpha*log10(1) = 0)
    rng = Rng(42)
    pl = PathLossModel(rng, freq_loss_db=40.0, alpha=3.5, shadowing_sigma_db=0.0)
    pl_val = pl.path_loss_db(tx=0, rx=1, distance_m=1.0)
    assert math.isclose(pl_val, 40.0, abs_tol=1e-6)
    print("S2 path_loss.d_1m: PASS")


def test_path_loss_correlated_shadowing():
    # S3: shadowing drawn once per (tx,rx) and reused
    rng = Rng(42)
    pl = PathLossModel(rng, shadowing_sigma_db=3.0)
    pl_a = pl.path_loss_db(0, 1, 10.0)
    pl_b = pl.path_loss_db(0, 1, 10.0)
    assert pl_a == pl_b, "Shadowing should be cached per pair"
    # Different pair should (likely) get different shadowing
    pl_c = pl.path_loss_db(1, 0, 10.0)
    assert pl.is_cached(0, 1) and pl.is_cached(1, 0)
    print("S3 path_loss.shadowed: PASS")


def test_queue_enq_deq():
    # S4: FIFO order + latency formula
    q = PacketQueue(ap_id=0, link_id=0)
    p1 = q.enqueue(0, 1, 100, 1000)
    p2 = q.enqueue(0, 1, 200, 2000)
    assert len(q) == 2
    assert q.peek().packet_id == 0
    head = q.pop()
    assert head.packet_id == 0
    assert head.enq_time_ns == 1000
    head.success_time_ns = 5500
    assert head.latency_ns == 4500
    q.pop()
    assert q.is_empty
    print("S4 queue.enq_deq: PASS")


def test_mcs_ideal_select():
    # S5: ideal_select returns highest MCS whose min_sinr <= sinr
    # Very low SINR: should return mcs 0 (or lowest)
    e = ideal_select(sinr_db=-50.0)
    assert e.mcs_index == 0
    # Very high SINR: should return highest MCS
    e = ideal_select(sinr_db=40.0)
    assert e.mcs_index == HE_SU_20MHZ_MCS_TABLE[-1].mcs_index
    # Mid SINR
    e = ideal_select(sinr_db=15.0)
    # Should pick the highest MCS whose threshold <= 15
    chosen = max((m for m in HE_SU_20MHZ_MCS_TABLE if m.min_sinr_db <= 15.0),
                 key=lambda m: m.min_sinr_db)
    assert e.mcs_index == chosen.mcs_index
    print("S5 mcs.ideal_select: PASS")


def test_airtime_payload_only():
    # S6: airtime = preamble + size_bits / rate_mbps
    # size_bits = 8 * size_bytes
    airtime = approximate_packet_airtime_us(size_bytes=100, rate_mbps=10.0, preamble_us=20)
    # payload_us = 8*100 / 10 = 80 us; airtime = 20 + 80 = 100 us
    assert math.isclose(airtime, 100.0, abs_tol=1e-6)
    # Confirm NOT 8 * size_bits (which would be 800 / 10 = 80 → airtime = 100, same)
    # Try a case that distinguishes: size_bytes=1000, rate=100 Mbps
    airtime2 = approximate_packet_airtime_us(size_bytes=1000, rate_mbps=100.0, preamble_us=20)
    # 8*1000/100 = 80 us → 100 us
    # If we'd used 8*size_bits, it'd be 8*8000/100 = 640 us → 660 us
    assert math.isclose(airtime2, 100.0, abs_tol=1e-6)
    print("S6 airtime.payload_only: PASS")


def test_backoff_draw():
    # S7: BO uniform in [0, CW]; CW follows (CW_min+1)*2^r - 1
    rng = Rng(123)
    # r=0: CW = 15 → uniform in [0, 15]
    samples = [draw_backoff(rng, retry=0) for _ in range(10000)]
    assert min(samples) == 0
    assert max(samples) == 15
    assert all(0 <= s <= 15 for s in samples)
    # Chi-square check: should be roughly uniform
    counts = [0] * 16
    for s in samples:
        counts[s] += 1
    expected = 10000 / 16
    chi2 = sum((c - expected) ** 2 / expected for c in counts)
    # df = 15, critical value at p=0.001 is ~37.7
    assert chi2 < 37.7, f"Chi-square = {chi2}, distribution not uniform"
    # r=2: CW = 63 → uniform in [0, 63]
    samples2 = [draw_backoff(rng, retry=2) for _ in range(1000)]
    assert min(samples2) == 0
    assert max(samples2) == 63
    # r=10: CW = 1023 (saturated at CW_max)
    samples3 = [draw_backoff(rng, retry=10) for _ in range(5000)]
    assert max(samples3) == CW_MAX, "Retry >= 6 should saturate at CW_max"
    assert all(0 <= s <= CW_MAX for s in samples3)
    # Verify max is reachable with high probability: with 5000 samples over [0,1023],
    # we should see most values; just verify max==CW_MAX (above).
    print("S7 backoff.draw: PASS")


def test_backoff_formula_values():
    # Direct check of contention_window: r=0→15, r=1→31, r=2→63, r=3→127, r=6→1023
    assert contention_window(0) == 15
    assert contention_window(1) == 31
    assert contention_window(2) == 63
    assert contention_window(3) == 127
    assert contention_window(4) == 255
    assert contention_window(5) == 511
    assert contention_window(6) == 1023
    assert contention_window(7) == 1023  # saturated
    print("S7b backoff.formula values: PASS")


def test_sinr_linear_sum():
    # S13: interference aggregated in linear domain, NOT dBm.
    #   (a) two equal -60 dBm interferers -> aggregate interference power
    #       is exactly -56.99 dBm (= 10*log10(2*10^-6)). The dBm-arithmetic
    #       mistake would have given -57 dBm or worse.
    #   (b) given a separate desired signal power, SINR =
    #       10*log10(signal_W / (interf_W + noise_W)) matches hand calc.

    # (a) aggregate interference
    interf_dbm = sum_powers_linear_w([-60.0, -60.0])
    interf_dbm_dbm = 10.0 * math.log10(interf_dbm) + 30.0
    assert math.isclose(interf_dbm_dbm, -56.9897, abs_tol=0.01), \
        f"Two -60 dBm interferers should aggregate to -56.99 dBm, got {interf_dbm_dbm}"

    # (b) SINR with desired signal
    signal = -60.0  # dBm (1 nW)
    noise = -95.0   # dBm (~3.16e-13 W)
    # signal_W = 1e-9; interf_W = 2e-9; noise_W = 3.16e-13
    # SINR = 1e-9 / (2e-9 + 3.16e-13) = 1e-9 / 2.000000316e-9 ≈ 0.5 → -3 dB
    sinr = compute_sinr_db(signal, [-60.0, -60.0], noise)
    assert math.isclose(sinr, -3.0103, abs_tol=0.05), \
        f"Expected ~-3.01 dB (signal = interferers, both -60 dBm), got {sinr}"

    # Just signal + noise (no interferers)
    sinr_clean = compute_sinr_db(signal, [], noise)
    # 1e-9 W vs 3.16e-13 W → ratio ~3162 → 35 dB
    assert sinr_clean > 30.0 and sinr_clean < 40.0, \
        f"Expected ~35 dB but got {sinr_clean}"

    # Linear-domain sanity check
    assert dbm_to_w(0.0) == 1e-3
    assert math.isclose(w_to_dbm(1.0), 30.0, abs_tol=1e-6)  # 1 W = 30 dBm
    # sum of two 0 dBm should be ~3 dBm (double the power)
    two_0dbm_w = sum_powers_linear_w([0.0, 0.0])
    # 2 mW = 0.002 W
    assert math.isclose(two_0dbm_w, 0.002, abs_tol=1e-6)
    print(f"S13 sinr.linear_sum: PASS (interf={interf_dbm_dbm:.4f} dBm, sinr={sinr:.4f} dB)")


def test_event_loop_no_negative_time():
    # S14
    from wifi_simulator.core.event_loop import EventLoop
    el = EventLoop()
    fired = []
    def h():
        fired.append(el.now_ns)
    el.schedule(100, "a", h)
    el.schedule(50, "b", h)
    el.schedule(200, "c", h)
    try:
        el.schedule(-1, "bad", h)
        assert False, "should have raised"
    except ValueError:
        pass
    el.run_until_empty()
    assert fired == [50, 100, 200]
    # Time monotonic
    assert all(t >= 0 for t in fired)
    print("S14 event_loop.no_negative_time: PASS")


def test_rng_reproducibility():
    # S15
    rng1 = Rng(2024)
    rng2 = Rng(2024)
    s1 = [rng1.uniform_int(0, 100) for _ in range(1000)]
    s2 = [rng2.uniform_int(0, 100) for _ in range(1000)]
    assert s1 == s2
    # Different seed → different sequence (almost certainly)
    rng3 = Rng(2025)
    s3 = [rng3.uniform_int(0, 100) for _ in range(100)]
    assert s1[:100] != s3
    print("S15 rng.reproducibility: PASS")


if __name__ == "__main__":
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
    print("\nAll Sprint 1 primitive sanity tests: PASS")