"""Sprint 2.5: Experiment Comparability Gate.

Goal: make the Legacy-vs-Research comparison metrically comparable, then
run a 3-condition mechanism ablation across 5 seeds to identify *which*
mechanism causes the throughput divergence.

Three experiment conditions:

    E0 — Legacy Project_3 (always-on interferers, Shannon capacity)
    E1 — Research Core (CSMA/CA everywhere, packet airtime, Ideal MCS)
    E2 — Research + always-on interferers (CSMA/CA OFF for AP1-3, they
          transmit as fast as they have packets, mimicking legacy's
          always-on interference)

The headline metric is **target AP0 throughput** (Mbps, over 4.5 s).
Legacy "throughput" is Shannon-equivalent drained packets; Research
throughput is actual delivered packets. These are different metrics
and the comparison is reported **side-by-side, not as a single ratio**.

AP1, AP2, AP3 throughput are reported as **contextual** only — they
are not part of the headline AP0 comparison because legacy does not
measure them.

Topology:
    4 APs at (50,50), (30,50), (70,50), (50,70)         [from config.txt]
    1 STA per AP at AP_pos + (-2, 0)                    [Sprint 2.5 choice;
                                                         legacy has 4 STAs
                                                         per AP but only
                                                         uses 1 randomly
                                                         picked per step]
    AP0 (target) on channel 0
    AP1 interferer on channel 0
    AP2 interferer on channel 1
    AP3 interferer on channel 2

Run: `python -m wifi_simulator.experiments.legacy_vs_research_normal`
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from dataclasses import dataclass
from typing import Optional

# MacState is used inside _patch_always_on's nested functions, which
# don't see the imports of `run_research_always_on`. Import at module
# scope so the closure can find it.
from wifi_simulator.mac.mac import MacState  # noqa: F401

# Default policy used for E0 and E1.
TARGET_CHANNEL = 0
PT_MAX_DBM = 20.0
CCA_DBM = -82.0
LEGACY_ARR_MEAN = 500.0   # packets per 4.5 ms slot
TIMESLOT_S = 4.5e-3
LEGACY_SEEDS = [6, 7, 8, 9, 10]
DURATION_S = 4.5
N_STEPS_LEGACY = 1000


# ===========================================================================
# E0 — Legacy Project_3
# ===========================================================================

def run_legacy(seed: int) -> dict:
    """Run legacy Project_3 env for N steps. Returns per-step drained
    packet counts per AP, plus the final queue state.

    What "delivered packets" means here:
        `packtDelivered = dataRate * mbps2n_packet` in legacy `reward()`,
        where `dataRate` is Shannon capacity summed over channels where
        CCA passed. This is the **legacy abstract metric**: it is the
        number of packets that *would have been* drained from the queue
        given the channel's Shannon capacity. It is NOT a count of
        actually-transmitted packets. **Only AP0 (target) is measured.**
        Non-target AP queues are never drained (they serve only as
        always-on interference sources at pt_max).
    """
    LEGACY_ROOT = os.environ.get(
        "LEGACY_PROJECT3_ROOT", "/Users/yiwei/Desktop/Project_3"
    )
    if LEGACY_ROOT not in sys.path:
        sys.path.insert(0, LEGACY_ROOT)
    try:
        from env import genEnvClass  # type: ignore
    except ImportError as e:
        raise ImportError(
            f"Cannot import legacy Project_3 env from {LEGACY_ROOT}. "
            f"Set LEGACY_PROJECT3_ROOT environment variable to the path "
            f"containing env.py and baseEnv.py. Original error: {e}"
        )

    Env = genEnvClass(env_type="Normal")
    env = Env(seed=seed, arr_mean=LEGACY_ARR_MEAN)

    target_ap = 0
    selected_channels = {target_ap: [TARGET_CHANNEL]}
    tpc = {target_ap: {c: 0.0 for c in range(env.n_channels)}}
    tpc[target_ap][TARGET_CHANNEL] = 1.0
    cca = {target_ap: {c: CCA_DBM for c in range(env.n_channels)}}

    ap0_packets_per_step: list[float] = []
    for _ in range(N_STEPS_LEGACY):
        n_packets, _, _, _, _ = env.reward(cca, tpc, selected_channels)
        # n_packets is {ap: drained_packets} for targetAPs only.
        ap0_packets_per_step.append(float(n_packets.get(target_ap, 0.0)))

    total_packets = sum(ap0_packets_per_step)
    return {
        "seed": seed,
        "ap0_packets_total": total_packets,
        "ap0_packets_per_step_avg": total_packets / N_STEPS_LEGACY,
        "ap0_throughput_mbps": total_packets * 2304 * 8 / (DURATION_S * 1e6),
        "metric_definition": "legacy: Shannon-equivalent drained packets, AP0 only",
        "final_queue": dict(env.Queue),
    }


# ===========================================================================
# E1 — Research Core (full CSMA/CA, packet airtime, Ideal MCS)
# ===========================================================================

def run_research(seed: int) -> dict:
    """Run the research env with full CSMA/CA for all APs.

    Returns per-link and aggregate throughput for all 4 APs.
    """
    lambda_pps = LEGACY_ARR_MEAN / TIMESLOT_S  # 111,111 pps
    from wifi_simulator.core.simulator import Simulator
    from wifi_simulator.controllers.legacy_adapter import LegacyAdapter
    from wifi_simulator.scenarios.normal_4ap import make_aps

    sim = Simulator(
        seed=seed,
        duration_s=DURATION_S,
        aps=make_aps(lambda_pps=lambda_pps, target_channel=TARGET_CHANNEL),
    )
    adapter = LegacyAdapter(sim, target_ap=0, pt_max_dbm=PT_MAX_DBM)
    adapter.default_policy(channel=TARGET_CHANNEL)
    metrics = sim.run()
    return _format_research(metrics, seed, label="E1")


# ===========================================================================
# E2 — Research + always-on interferers
# ===========================================================================

def run_research_always_on(seed: int) -> dict:
    """Run the research env with AP1-3 patched to skip DIFS/BACKOFF
    (always-on interferer behaviour, matching legacy's pt_max interference
    model as closely as possible).

    Mechanism: AP1-3's MacStation.plan_slot and MacStation._handle_failure
    are monkey-patched at runtime. The patch:
      - in plan_slot, if queue is non-empty and not currently TXing,
        immediately set pending_tx_start = True (skip DIFS/BACKOFF).
      - in _handle_failure, retry immediately without DIFS.

    With lambda_pps=111,111 the queue is always non-empty, so AP1-3 are
    in TX essentially 100% of the time (only a slot-time gap between
    successive TXs). This approximates legacy's always-on interference
    model.
    """
    lambda_pps = LEGACY_ARR_MEAN / TIMESLOT_S
    from wifi_simulator.core.simulator import Simulator
    from wifi_simulator.controllers.legacy_adapter import LegacyAdapter
    from wifi_simulator.scenarios.normal_4ap import make_aps

    sim = Simulator(
        seed=seed,
        duration_s=DURATION_S,
        aps=make_aps(lambda_pps=lambda_pps, target_channel=TARGET_CHANNEL),
    )
    # Patch AP1, AP2, AP3 (interferers) to always-on.
    for mac in sim.macs:
        if mac.ap_id != 0:
            _patch_always_on(mac)
    adapter = LegacyAdapter(sim, target_ap=0, pt_max_dbm=PT_MAX_DBM)
    adapter.default_policy(channel=TARGET_CHANNEL)
    metrics = sim.run()
    return _format_research(metrics, seed, label="E2")


def _patch_always_on(mac) -> None:
    """Runtime monkey-patch: skip DIFS_WAIT and BACKOFF for one MAC.

    This is an experimental override for the ablation only. It is NOT a
    new architecture feature; it lives in this experiment file.
    """
    def plan_slot(now_ns, channel_busy_at_slot_start):
        # If currently TXing or waiting for ACK, don't interrupt.
        if mac.state in (MacState.TX, MacState.ACK_WAIT):
            return
        # If queue is non-empty, go straight to TX.
        if not mac.queue.is_empty:
            mac.pending_tx_start = True
        # Note: the actual TX is registered in commit_slot (called by the
        # simulator's two-phase slot handler) only if pending_tx_start.
    mac.plan_slot = plan_slot

    def _handle_failure(now_ns):
        if mac.current_packet is None:
            mac.state = MacState.IDLE
            return
        mac.retry_count += 1
        if mac.retry_count > mac.retry_limit:
            p = mac.queue.pop()
            p.outcome = "DROP_RETRY_LIMIT"
            mac.metrics.record_drop(p)
            mac.retry_count = 0
            mac.current_packet = None
            mac.state = MacState.IDLE
            return
        mac.current_packet = None
        # Skip _begin_difs_wait; next plan_slot will pick this up.
        mac.state = MacState.IDLE
    mac._handle_failure = _handle_failure


# ===========================================================================
# Output formatting
# ===========================================================================

def _format_research(metrics: dict, seed: int, label: str) -> dict:
    """Pick out the per-link numbers we need for the comparability table.

    A link may be missing from `per_link` if the MAC never managed a TX
    attempt (e.g., AP0 completely jammed by always-on interferers in E2).
    We treat missing entries as zero.
    """
    per_link = metrics["per_link"]

    def _link(ap_id: int) -> dict:
        return per_link.get(ap_id, {
            "success": 0, "collision": 0, "fail_phy": 0,
            "fail_no_ack": 0, "retry": 0, "drop": 0,
            "tx_attempts": 0, "throughput_bps": 0.0,
        })

    ap0 = _link(0)
    ap1 = _link(1)
    ap2 = _link(2)
    ap3 = _link(3)
    return {
        "label": label,
        "seed": seed,
        "metric_definition": (
            "research: actual transmitted packets (post-PER, post-collision)"
        ),
        "ap0_success": ap0["success"],
        "ap0_throughput_mbps": ap0["success"] * 2304 * 8 / (DURATION_S * 1e6),
        "ap0_collisions": ap0["collision"],
        "ap0_retries": ap0["retry"],
        "ap0_drops": ap0["drop"],
        "ap1_success": ap1["success"],
        "ap1_throughput_mbps": ap1["success"] * 2304 * 8 / (DURATION_S * 1e6),
        "ap1_collisions": ap1["collision"],
        "ap2_success": ap2["success"],
        "ap2_throughput_mbps": ap2["success"] * 2304 * 8 / (DURATION_S * 1e6),
        "ap2_collisions": ap2["collision"],
        "ap3_success": ap3["success"],
        "ap3_throughput_mbps": ap3["success"] * 2304 * 8 / (DURATION_S * 1e6),
        "ap3_collisions": ap3["collision"],
        "system_throughput_mbps": (
            (ap0["success"] + ap1["success"] + ap2["success"] + ap3["success"])
            * 2304 * 8 / (DURATION_S * 1e6)
        ),
        "system_collisions": ap0["collision"] + ap1["collision"]
            + ap2["collision"] + ap3["collision"],
    }


# ===========================================================================
# Cross-seed aggregation
# ===========================================================================

def _agg(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": statistics.mean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def run_all_seeds(seeds: list[int]) -> dict:
    """Run E0, E1, E2 for all seeds; return aggregated comparison."""
    e0, e1, e2 = [], [], []
    for seed in seeds:
        print(f"  seed={seed}...", end=" ", flush=True)
        e0.append(run_legacy(seed))
        print("E0 done,", end=" ", flush=True)
        e1.append(run_research(seed))
        print("E1 done,", end=" ", flush=True)
        e2.append(run_research_always_on(seed))
        print("E2 done.")
    return {"E0": e0, "E1": e1, "E2": e2}


def summarize(results: dict) -> dict:
    e0 = results["E0"]
    e1 = results["E1"]
    e2 = results["E2"]
    return {
        "E0 (legacy)": {
            "metric": e0[0]["metric_definition"],
            "ap0_throughput_mbps": _agg([r["ap0_throughput_mbps"] for r in e0]),
            "ap0_packets_total": _agg([r["ap0_packets_total"] for r in e0]),
        },
        "E1 (research core)": {
            "metric": e1[0]["metric_definition"],
            "ap0_throughput_mbps": _agg([r["ap0_throughput_mbps"] for r in e1]),
            "ap0_collisions": _agg([r["ap0_collisions"] for r in e1]),
            "ap0_retries": _agg([r["ap0_retries"] for r in e1]),
            "ap0_drops": _agg([r["ap0_drops"] for r in e1]),
            "ap1_throughput_mbps": _agg([r["ap1_throughput_mbps"] for r in e1]),
            "ap2_throughput_mbps": _agg([r["ap2_throughput_mbps"] for r in e1]),
            "ap3_throughput_mbps": _agg([r["ap3_throughput_mbps"] for r in e1]),
            "system_throughput_mbps": _agg(
                [r["system_throughput_mbps"] for r in e1]
            ),
            "system_collisions": _agg([r["system_collisions"] for r in e1]),
        },
        "E2 (research + always-on interferers)": {
            "metric": e2[0]["metric_definition"],
            "ap0_throughput_mbps": _agg([r["ap0_throughput_mbps"] for r in e2]),
            "ap0_collisions": _agg([r["ap0_collisions"] for r in e2]),
            "ap0_retries": _agg([r["ap0_retries"] for r in e2]),
            "ap0_drops": _agg([r["ap0_drops"] for r in e2]),
            "ap1_throughput_mbps": _agg([r["ap1_throughput_mbps"] for r in e2]),
            "ap2_throughput_mbps": _agg([r["ap2_throughput_mbps"] for r in e2]),
            "ap3_throughput_mbps": _agg([r["ap3_throughput_mbps"] for r in e2]),
            "system_throughput_mbps": _agg(
                [r["system_throughput_mbps"] for r in e2]
            ),
            "system_collisions": _agg([r["system_collisions"] for r in e2]),
        },
    }


def print_table(summary: dict) -> None:
    print()
    print("AP0 throughput (Mbps), 5 seeds, mean ± std, min .. max")
    print("-" * 70)
    for cond, body in summary.items():
        ap0 = body["ap0_throughput_mbps"]
        print(f"  {cond:<42s}  "
              f"{ap0['mean']:6.2f} ± {ap0['std']:5.2f}  "
              f"[{ap0['min']:6.2f}, {ap0['max']:6.2f}]")
    print()
    print("Per-link throughput (E1 vs E2), Mbps, mean")
    print("-" * 70)
    print(f"  {'link':<6s}  {'E1 (research core)':>20s}  {'E2 (always-on)':>20s}")
    for ap in [1, 2, 3]:
        e1 = summary["E1 (research core)"][f"ap{ap}_throughput_mbps"]["mean"]
        e2 = summary["E2 (research + always-on interferers)"][f"ap{ap}_throughput_mbps"]["mean"]
        print(f"  AP{ap:<3d}  {e1:>20.2f}  {e2:>20.2f}")
    print()
    print("Collision counts (research conditions), system total, mean")
    print("-" * 70)
    e1_coll = summary["E1 (research core)"]["system_collisions"]["mean"]
    e2_coll = summary["E2 (research + always-on interferers)"]["system_collisions"]["mean"]
    print(f"  E1 system collisions: {e1_coll:.1f}")
    print(f"  E2 system collisions: {e2_coll:.1f}")


# ===========================================================================
# Main
# ===========================================================================

def main() -> int:
    print("=" * 72)
    print("Sprint 2.5 — Experiment Comparability Gate")
    print("=" * 72)
    print(f"Seeds: {LEGACY_SEEDS}")
    print(f"Duration: {DURATION_S} s ({N_STEPS_LEGACY} legacy time slots)")
    print(f"Topology: 4 APs, 3 channels, target AP0 on channel {TARGET_CHANNEL}")
    print(f"Traffic: lambda_pps = {LEGACY_ARR_MEAN / TIMESLOT_S:.0f} pps per AP")
    print()
    print("Metric definitions (per-AP):")
    print("  E0: legacy `n_packets[AP0]` = Shannon-equivalent drained packets.")
    print("      (NOT actually-transmitted packets. AP1-3 not measured.)")
    print("  E1, E2: research `per_link[ap].success` = actually-transmitted")
    print("      packets post-PER, post-collision.")
    print()
    print("Running 3 conditions × 5 seeds = 15 runs...")
    print()
    results = run_all_seeds(LEGACY_SEEDS)
    summary = summarize(results)
    print_table(summary)
    print()
    print("Per-seed raw results:")
    for cond in ("E0", "E1", "E2"):
        print(f"  {cond}:")
        for r in results[cond]:
            ap0_mbps = r.get("ap0_throughput_mbps", 0.0)
            label = r.get("label", "")
            seed = r["seed"]
            print(f"    seed={seed}: AP0 = {ap0_mbps:6.2f} Mbps  ({label})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
