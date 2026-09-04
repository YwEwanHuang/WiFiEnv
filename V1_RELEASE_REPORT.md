# Research Wi-Fi Environment — v1.0 Release Report

**Date**: 2026-09-04
**Status**: ✅ **v1.0 — COMPLETE / FROZEN**

This document is the single deliverable that closes the v1.0 release.
After this freeze, the Core is no longer modified for hypothetical
future needs; new mechanisms are added only as Feature Packs driven by
explicit paper requirements.

---

## 1. Final regression

| Check | Result |
|-------|--------|
| 11 primitive sanity tests (`S1`–`S15` incl. `S7` + `S7b`) | **PASS** |
| 5 CSMA / CCA tests (`S8`–`S12`) | **PASS** |
| Scenario A validation (no collisions, theoretical throughput) | **PASS** |
| Scenario B validation (fairness, collisions, retries) | **PASS** |
| Scenario C multi-BSS (conservation holds) | **PASS** |
| MLO v0 M1 STR (formal capability) | **PASS** |
| `single_radio` demo (experimental baseline) | **PASS** |
| Reproducibility (Scenario A, B, C, M1 STR — same seed → identical) | **PASS** |
| Closed-form packet conservation (`gap = 0`) | **PASS** |
| Per-channel utilization reported | **PASS** |

All previously passing tests continue to pass. No regressions.

---

## 2. v1.0 capability boundary

### 2.1 Core (frozen)

| # | Mechanism |
|--:|-----------|
| C1 | Discrete-event timing (ns / 9 µs slot resolution) |
| C2 | CSMA/CA: DIFS / backoff / freeze+resume / TX / ACK / retry |
| C3 | Collision / ACK / retry / drop after `retry_limit` |
| C4 | Packet-level PHY (cached per-link shadowing, linear-domain interference) |
| C5 | Ideal MCS Selection + simplified PER + Approximate Packet Airtime |
| C6 | Per-packet queue with packet identities |
| C7 | Realistic interferer traffic (CSMA/CA, never always-on) |
| C8 | Multi-BSS, ≥ 5 APs, overlapping channel reuse |
| C9 | Per-link Controller (channel / Tx power / CCA at `link_id` granularity) |
| C10 | Research metrics (throughput, latency mean/p50/p95, queue, collision, retry, drop, per-channel utilization) |

The Core can run channel-selection / power-allocation / CCA / MARL
experiments on its own with no Feature Pack loaded.

### 2.2 MLO v0 (shipped Feature Pack)

```
two-link MLD
+ independent per-link CSMA/CA
+ fixed / round-robin steering
+ STR
```

This is the **complete and final** MLO v0 contract. Anything not listed
is not in v0 (see §3).

### 2.3 What v1.0 explicitly does NOT include

These are deferred to future paper-driven Feature Packs:

* IEEE 802.11be NSTR (link-pair NAV, restricted TWT, channel-access sharing)
* EMLSR / link switching latency
* OFDMA / multi-RU / MU-MIMO
* 320 MHz / channel puncturing
* BSS Coloring / OBSS_PD / Spatial Reuse
* EDCA / QoS AC
* Block ACK / A-MPDU / A-MSDU
* Mobility
* TCP / IP stack
* 802.11bn / UHR
* Capture effect (SINR-based)
* Spatial-correlated shadowing (Gaussian random field)
* Rate adaptation (MiniRate / full RA)
* Association / authentication / WPA
* Beacon / scan / management plane
* RL Agent integration
* ns-3 integration
* Visualization / dashboard / CLI framework

---

## 3. Known simplifications / limitations

These are by-design simplifications accepted for v1.0; none are bugs.

| # | Item | Impact | When to revisit |
|--:|------|--------|-----------------|
| 1 | ACK is instantaneous (no scheduled ACK TX) | Slightly optimistic on per-packet airtime | Block-ACK paper |
| 2 | One STA per AP | No intra-BSS STA contention | Multi-STA scheduling paper |
| 3 | PER is binary (0 or 1) | No soft-PER near MCS threshold | Rate-adaptation paper |
| 4 | Shadowing static per run | No time-varying channel | Mobility / fast-fading paper |
| 5 | Poisson arrivals only | No bursty / on-off / trace traffic | Traffic-model paper |
| 6 | No capture effect | Stronger simultaneous TX never wins over weaker | Capture paper |
| 7 | `single_radio` demo mode starves one link under saturation | Abstract single-radio gate, NOT IEEE NSTR | IEEE NSTR paper |
| 8 | No spatial correlation of shadowing | Per-link shadowing only, not spatial field | Spatial-reuse paper |
| 9 | No mobility | Static positions | Mobility paper |
| 10 | No rate adaptation | Ideal MCS only | Rate-adaptation paper |

Each item has a "When to revisit" trigger that names the paper topic
that would justify extending the Core. Until that paper, the Core stays
frozen.

---

## 4. How to run

All commands are runnable without RL. Outputs include throughput,
latency (mean / p50 / p95), queue, collision, retry, drop,
per-channel utilization, and per-link metrics.

```bash
# Core scenarios
python -m wifi_simulator.scenarios.scenario_a           # 1 AP, 1 STA, saturated
python -m wifi_simulator.scenarios.scenario_b           # 2 APs, same channel, saturated
python -m wifi_simulator.scenarios.scenario_c           # 4 APs, 3 channels, multi-BSS

# MLO v0
python -m wifi_simulator.scenarios.m1_two_link_str      # 1 MLD, 2 links, STR (formal v0)
python -m wifi_simulator.scenarios.experimental_single_radio   # experimental baseline, NOT IEEE NSTR

# Validation
python -m wifi_simulator.tests.test_primitives          # 11 primitive sanity tests
python -m wifi_simulator.tests.test_freeze_resume       # 5 CSMA / CCA tests
python -m wifi_simulator.tests.test_sprint1             # integration: primitive + CSMA + A + B
python -m wifi_simulator.experiments.mlo_v0_validation  # full MLO v0 validation incl. conservation

# Programmatic
python -c "from wifi_simulator.scenarios.scenario_a import run; print(run(5.0, 2024))"
```

Each scenario's `run()` returns a dict including `total_throughput_bps`,
`total_success_packets`, `total_drop_packets`, `latency_mean_us`,
`latency_p50_us`, `latency_p95_us`, `per_link`, and `channel_utilization`.

---

## 5. Final baseline (seed, 5 s, frozen numbers)

These are the canonical numbers to cite in any v1.0 paper using this
environment. They are reproducible with the exact seed below.

| Scenario | Seed | Aggregate throughput | Success | Drops | Collisions | Channel utilization |
|----------|-----:|---------------------:|--------:|------:|-----------:|---------------------|
| **A** (1 AP, 1 STA, saturated) | 2024 | **64.83 Mbps** | 17,587 | 0 | 0 | ch0 = 0.579 |
| **B** (2 APs, same ch, saturated) | 2024 | **70.94 Mbps** | 19,244 | 0 | 2,062 (1,031/AP) | ch0 = 0.701 |
| **C** (4 APs, 3 ch, multi-BSS) | 6 | **207.84 Mbps** | 56,381 | 0 | varies per link¹ | ch0 = 0.701, ch1 = 0.713, ch2 = 0.723 |
| **M1 STR** (2-link MLD, orthogonal ch, saturated) | 2024 | **129.75 Mbps** | 35,197 | 0 | 0 per link | ch0 = 0.579, ch1 = 0.579 |
| `single_radio` (experimental, NOT IEEE NSTR) | 2024 | 64.83 Mbps | 17,587 (only link 0) | 0 | 0 | ch0 = 0.579, ch1 = 0 (idle) |

¹ Scenario C per-link: link 0 35.63 / 1.0k collisions, link 1 33.19 / 0.97k, link 2 31.96 / 0.92k, link 3 35.40 / 1.0k, link 4 36.35 / 0.97k, link 5 35.31 / 0.92k. Co-channel pairs share Bianchi n=2 fairness.

### 5.1 Closed-form packet conservation (`arrivals = success + drop + queued`)

| Scenario | Arrivals | success + drop + queued | gap |
|---|---:|---:|---:|
| A | 499,711 | 499,711 | **0** |
| B | 999,900 | 999,900 | **0** |
| C | 3,003,605 | 3,003,605 | **0** |
| M1 STR | 499,724 | 499,724 | **0** |
| `single_radio` demo | 499,711 | 499,711 | **0** |

### 5.2 Wall-clock (5 s sim on a single thread)

| Scenario | Wall time |
|----------|----------:|
| A | ~2.0 s |
| B | ~3.7 s |
| C | ~11.4 s |
| M1 STR | ~2.7 s |
| `single_radio` | ~3.8 s |

---

## 6. v1.0 freeze checklist

| # | Criterion | Status |
|---|-----------|--------|
| 1 | All Core scenarios (A/B/C) run independently with sensible metrics | ✅ |
| 2 | No RL agent required for any shipped scenario | ✅ |
| 3 | Per-link + aggregate throughput / latency / queue / collision / retry / drop / utilization reported | ✅ |
| 4 | Multi-BSS with realistic interferer traffic | ✅ |
| 5 | Scripted channel / Tx power / CCA control (`ScriptedRunner`) | ✅ |
| 6 | All existing sanity + CSMA / CCA tests pass | ✅ |
| 7 | Deterministic reproducibility (same seed → identical numbers incl. utilization) | ✅ |
| 8 | Closed-form packet conservation (`gap = 0`) | ✅ |
| 9 | No known correctness bug that distorts results | ✅ |
| 10 | MLO v0 STR delivers two-link concurrent TX with closed-form conservation | ✅ |
| 11 | Experimental `single_radio` mode marked NOT IEEE NSTR | ✅ |
| 12 | v1.0 capability boundary and "not in v1.0" list documented | ✅ |
| 13 | Documentation cross-consistency across Design / MVP / Validation / MVP-Report / MLO-Report / V1-Report | ✅ |

---

## 7. Conclusion

**✅ v1.0 freeze conditions are met.**

The Research Wi-Fi Environment v1.0 is **COMPLETE and FROZEN** as of
2026-09-04.

* **Core**: discrete-event CSMA/CA simulator with packet-level PHY,
  multi-BSS, per-link Controller, ScriptedRunner, closed-form
  conservation, and per-channel utilization reporting.
* **MLO v0**: two-link MLD with independent per-link CSMA/CA, fixed /
  round-robin steering, STR. The experimental `single_radio` baseline
  ships alongside but is explicitly NOT IEEE NSTR.
* **Deferral rule**: any new mechanism enters only as a Feature Pack,
  triggered by an explicit paper requirement. The Core is no longer
  modified for hypothetical future needs.
* **Reproducibility**: every baseline number in §5 is bit-for-bit
  reproducible with the listed seed.

After this freeze, no new Sprint is opened and no Feature Pack is
implemented without a paper-driven requirement.