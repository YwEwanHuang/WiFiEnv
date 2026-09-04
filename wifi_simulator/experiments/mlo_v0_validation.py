"""MLO Feature Pack v0 — validation runner.

Runs M1 (STR, formal v0) and the experimental `single_radio` demo
plus additional checks:
  * per-link throughput / latency / queue / arrivals / drop
  * simultaneous-TX detection across MLD links (STR expected > 0,
    single_radio expected = 0)
  * full packet conservation: arrivals == success + drop + queued +
    inflight (closed-form, not inequality)
  * seeded reproducibility across runs
  * fixed-steering smoke test (round-robin sanity)

This script is the single source of numbers cited in MLO_V0_REPORT.md.
"""
from __future__ import annotations

import json

from wifi_simulator.core.simulator import ApStation, Simulator
from wifi_simulator.features.mlo import MldConfig


def _make_sim(steering: str, mode: str, seed: int = 2024) -> Simulator:
    return Simulator(
        seed=seed,
        duration_s=5.0,
        aps=[
            ApStation(0, 10, (0.0, 0.0), (10.0, 0.0), 0, 0,
                      tx_power_dbm=18.0, lambda_pps=100000.0,
                      size_bytes=2304),
            ApStation(0, 11, (0.0, 0.0), (10.0, 0.0), 1, 1,
                      tx_power_dbm=18.0, lambda_pps=100000.0,
                      size_bytes=2304),
        ],
        mld_configs=[
            MldConfig(mld_id=0, ap_id=0, link_ids=[0, 1],
                      mode=mode, steering=steering,
                      fixed_link_id=0 if steering == "fixed" else None),
        ],
    )


def _per_link_tx_starts(sim: Simulator) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {0: [], 1: []}
    for line in sim.trace.lines():
        if "TX_START" not in line:
            continue
        parts = line.split()
        t_ns = int(parts[0])
        for tok in parts:
            if tok.startswith("link="):
                lid = int(tok.split("=")[1])
                if lid in out:
                    out[lid].append(t_ns)
                break
    return out


def _count_simultaneous_tx(starts_per_link: dict[int, list[int]],
                            airtime_ns: int) -> int:
    """Count pairs of TX_STARTs (across the two links) whose airtime
    windows overlap in wall-clock time."""
    a = starts_per_link[0]
    b = starts_per_link[1]
    a.sort()
    b.sort()
    ia = ib = 0
    overlap = 0
    while ia < len(a) and ib < len(b):
        ta = a[ia]
        tb = b[ib]
        if ta + airtime_ns <= tb:
            ia += 1
        elif tb + airtime_ns <= ta:
            ib += 1
        else:
            overlap += 1
            if ta + airtime_ns <= tb + airtime_ns:
                ia += 1
            else:
                ib += 1
    return overlap


def _conservation_report(sim: Simulator) -> dict:
    """Full conservation: arrivals = success + drop + queued + inflight.

    `inflight` counts MACs whose `current_packet` is non-None (TX/ACK_WAIT
    in flight at sim end). Those packets are also still in their queue
    — `queued` therefore already includes them; we report both for
    clarity but the closed-form identity is `arrivals == success + drop +
    queued` (since inflight ⊂ queued).
    """
    arrivals = sum(q.arrival_count for q in sim.queues)
    success = sim.metrics.total_success_count()
    drop = sim.metrics.total_drop_count()
    queued = sum(len(q) for q in sim.queues)
    inflight = sum(1 for m in sim.macs if m.current_packet is not None)
    closed = success + drop + queued
    return {
        "arrivals": arrivals,
        "success": success,
        "drop": drop,
        "queued_at_end": queued,
        "inflight": inflight,
        "closed_total": closed,
        "conservation_holds": arrivals == closed,
        "gap": arrivals - closed,
    }


def _run_mlo(steering: str, mode: str, seed: int = 2024,
              duration_s: float = 5.0) -> dict:
    sim = _make_sim(steering=steering, mode=mode, seed=seed)
    res = sim.run()
    # Approximate airtime for overlap detection. 2304-byte packet at the
    # saturation MCS rate (~86 Mbps MCS7) yields ~250 us; use 260 us.
    airtime_ns = 260_000
    tx_starts = _per_link_tx_starts(sim)
    simultaneous = _count_simultaneous_tx(tx_starts, airtime_ns)
    cons = _conservation_report(sim)
    return {
        "summary": res,
        "per_link": res["per_link"],
        "tx_starts_count": {lid: len(tx_starts[lid]) for lid in tx_starts},
        "simultaneous_tx_pairs": simultaneous,
        "queue_len_at_end": {q.link_id: len(q) for q in sim.queues},
        "queue_arrival_count": {q.link_id: q.arrival_count for q in sim.queues},
        "conservation": cons,
        "duration_s": duration_s,
        "seed": seed,
    }


def _reproducibility_check() -> dict:
    out = {}
    for steering in ("round_robin",):
        for mode in ("STR", "single_radio"):
            r1 = _run_mlo(steering=steering, mode=mode, seed=2024)
            r2 = _run_mlo(steering=steering, mode=mode, seed=2024)
            same = (r1["summary"]["total_success_packets"]
                    == r2["summary"]["total_success_packets"]
                    and r1["summary"]["total_throughput_bps"]
                    == r2["summary"]["total_throughput_bps"]
                    and r1["conservation"]["arrivals"]
                    == r2["conservation"]["arrivals"])
            out[f"{steering}-{mode}"] = same
    return out


def _frozen_core_conservation(name: str, seed: int, duration_s: float = 5.0) -> dict:
    """Run a Frozen Core scenario and return full conservation."""
    if name == "A":
        from wifi_simulator.scenarios.scenario_a import run as run_a
        # scenario_a.run is for the module-level invocation; we need a
        # Simulator instance to access queues. Reproduce the same setup.
        sim = Simulator(
            seed=seed, duration_s=duration_s,
            aps=[ApStation(0, 10, (0.0, 0.0), (10.0, 0.0), 0, 0,
                           tx_power_dbm=18.0, lambda_pps=100000.0,
                           size_bytes=2304)],
        )
        sim.run()
    elif name == "B":
        sim = Simulator(
            seed=seed, duration_s=duration_s,
            aps=[
                ApStation(0, 10, (0.0, 0.0), (10.0, 0.0), 0, 0,
                          tx_power_dbm=18.0, lambda_pps=100000.0,
                          size_bytes=2304),
                ApStation(1, 11, (50.0, 0.0), (60.0, 0.0), 1, 0,
                          tx_power_dbm=18.0, lambda_pps=100000.0,
                          size_bytes=2304),
            ],
        )
        sim.run()
    elif name == "C":
        from wifi_simulator.scenarios.scenario_c import make_aps
        sim = Simulator(
            seed=seed, duration_s=duration_s,
            aps=make_aps(lambda_pps=100000.0),
            noise_dbm=-95.0, retry_limit=6,
        )
        sim.run()
    else:
        raise ValueError(name)
    return _conservation_report(sim)


def main() -> None:
    print("=" * 72)
    print("MLO Feature Pack v0 — validation")
    print("=" * 72)

    # ---- M1: round-robin STR (FORMAL v0) ----
    print()
    print("-" * 72)
    print("M1 — Two-link STR (round-robin steering) [formal v0]")
    print("-" * 72)
    m1 = _run_mlo(steering="round_robin", mode="STR")
    s1 = m1["summary"]
    print(f"  aggregate throughput : {s1['total_throughput_bps']/1e6:.2f} Mbps")
    print(f"  total success packets: {s1['total_success_packets']}")
    print(f"  total drops          : {s1['total_drop_packets']}")
    for lid, lm in sorted(m1["per_link"].items()):
        print(f"  link {lid}: {lm['throughput_bps']/1e6:.2f} Mbps, "
              f"succ={lm['success']}, coll={lm['collision']}, "
              f"drop={lm['drop']}, retry={lm['retry']}")
    print(f"  TX_START count       : {m1['tx_starts_count']}")
    print(f"  simultaneous TX pairs: {m1['simultaneous_tx_pairs']}")
    print(f"  arrivals per link    : {m1['queue_arrival_count']}")
    print(f"  queue at end         : {m1['queue_len_at_end']}")
    print(f"  latency mean/p95 us  : {s1['latency_mean_us']:.0f} / "
          f"{s1['latency_p95_us']:.0f}")
    c1 = m1["conservation"]
    print(f"  conservation: arrivals={c1['arrivals']}, "
          f"success+drop+queued={c1['closed_total']}, "
          f"gap={c1['gap']}, holds={c1['conservation_holds']}")

    # ---- Experimental: single_radio demo ----
    print()
    print("-" * 72)
    print("Experimental — two-link single_radio (NOT IEEE NSTR)")
    print("-" * 72)
    sr = _run_mlo(steering="round_robin", mode="single_radio")
    sr_s = sr["summary"]
    print(f"  aggregate throughput : {sr_s['total_throughput_bps']/1e6:.2f} Mbps")
    print(f"  total success packets: {sr_s['total_success_packets']}")
    print(f"  total drops          : {sr_s['total_drop_packets']}")
    for lid, lm in sorted(sr["per_link"].items()):
        print(f"  link {lid}: {lm['throughput_bps']/1e6:.2f} Mbps, "
              f"succ={lm['success']}, coll={lm['collision']}, "
              f"drop={lm['drop']}, retry={lm['retry']}")
    print(f"  TX_START count       : {sr['tx_starts_count']}")
    print(f"  simultaneous TX pairs: {sr['simultaneous_tx_pairs']}")
    print(f"  queue at end         : {sr['queue_len_at_end']}")
    csr = sr["conservation"]
    print(f"  conservation: arrivals={csr['arrivals']}, "
          f"success+drop+queued={csr['closed_total']}, "
          f"gap={csr['gap']}, holds={csr['conservation_holds']}")

    # ---- Smoke: fixed steering STR ----
    print()
    print("-" * 72)
    print("Fixed-steering STR (smoke)")
    print("-" * 72)
    fx = _run_mlo(steering="fixed", mode="STR")
    print(f"  aggregate throughput : {fx['summary']['total_throughput_bps']/1e6:.2f} Mbps")
    for lid, lm in sorted(fx["per_link"].items()):
        print(f"  link {lid}: {lm['throughput_bps']/1e6:.2f} Mbps, "
              f"succ={lm['success']}, coll={lm['collision']}")

    # ---- Reproducibility ----
    print()
    print("-" * 72)
    print("Reproducibility (same seed → identical)")
    print("-" * 72)
    rep = _reproducibility_check()
    for k, v in rep.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")

    # ---- Frozen Core full conservation ----
    print()
    print("-" * 72)
    print("Frozen Core — full packet conservation")
    print("-" * 72)
    for label, name, seed in (("A", "A", 2024), ("B", "B", 2024), ("C", "C", 6)):
        c = _frozen_core_conservation(name, seed)
        print(f"  Scenario {label}: arrivals={c['arrivals']}, "
              f"success+drop+queued={c['closed_total']}, "
              f"gap={c['gap']}, holds={c['conservation_holds']}")

    # ---- Save JSON for the report ----
    out = {
        "m1_str": {
            "aggregate_mbps": m1["summary"]["total_throughput_bps"] / 1e6,
            "success": m1["summary"]["total_success_packets"],
            "drops": m1["summary"]["total_drop_packets"],
            "per_link": m1["per_link"],
            "tx_starts": m1["tx_starts_count"],
            "simultaneous_tx_pairs": m1["simultaneous_tx_pairs"],
            "queue_at_end": m1["queue_len_at_end"],
            "queue_arrivals": m1["queue_arrival_count"],
            "latency_mean_us": m1["summary"]["latency_mean_us"],
            "latency_p95_us": m1["summary"]["latency_p95_us"],
            "conservation": m1["conservation"],
        },
        "experimental_single_radio": {
            "aggregate_mbps": sr["summary"]["total_throughput_bps"] / 1e6,
            "success": sr["summary"]["total_success_packets"],
            "drops": sr["summary"]["total_drop_packets"],
            "per_link": sr["per_link"],
            "tx_starts": sr["tx_starts_count"],
            "simultaneous_tx_pairs": sr["simultaneous_tx_pairs"],
            "queue_at_end": sr["queue_len_at_end"],
            "conservation": sr["conservation"],
        },
        "fixed_steering_str_smoke": {
            "aggregate_mbps": fx["summary"]["total_throughput_bps"] / 1e6,
            "per_link": fx["per_link"],
        },
        "reproducibility": rep,
        "frozen_core_conservation": {
            label: _frozen_core_conservation(name, seed)
            for label, name, seed in (("A", "A", 2024), ("B", "B", 2024), ("C", "C", 6))
        },
    }
    with open("/Users/yiwei/Desktop/WiFiEnv/wifi_simulator/experiments/mlo_v0_validation.json", "w") as f:
        json.dump(out, f, indent=2, default=float)
    print()
    print("Saved: mlo_v0_validation.json")


if __name__ == "__main__":
    main()