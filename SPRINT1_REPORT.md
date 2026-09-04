# SPRINT1_REPORT.md

**Stage**: Sprint 1 implementation complete.
**Scope**: minimum Core to run Scenarios A (single AP) and B (two saturated
contenders on one channel) with real CSMA/CA + packet PHY.

---

## 1. Implemented

```
wifi_simulator/
├── core/
│   ├── rng.py                 seeded RNG (single numpy.random.Generator)
│   ├── event_loop.py          discrete-event engine, ns resolution, priority queue
│   ├── channel_state.py       per-channel active-TX accounting, simultaneous-start collision marker
│   └── simulator.py           top-level driver: topology, traffic, slot scheduler
├── mac/
│   ├── timing.py              IEEE 802.11 timing constants (5 GHz OFDM, 20 MHz)
│   │                          SLOT=9us, SIFS=16us, DIFS=34us, ACK=20us
│   ├── backoff.py             CW_r = min((CW_min+1)*2^r - 1, CW_max), chi-square verified
│   └── mac.py                 per-(AP, link) CSMA/CA state machine
│                              IDLE / DIFS_WAIT / BACKOFF / TX / ACK_WAIT
│                              with proper freeze/resume (frozen_counter)
├── phy/
│   ├── path_loss.py           freq_loss + alpha*log10(d) + cached correlated shadowing
│   ├── sinr.py                LINEAR-DOMAIN power sum (no dBm arithmetic)
│   │                          dbm_to_w / w_to_dbm / sum_powers_linear_w / compute_sinr_db
│   ├── mcs.py                 HE-SU 20 MHz MCS 0..11 + Ideal MCS Selection
│   └── airtime.py             Approximate Packet Airtime = preamble + payload_us
├── network/
│   ├── queue.py               per-(AP, link) FIFO with packet identities
│   └── traffic.py             Poisson arrivals (Sprint 1 only; CBR/on-off in later sprints)
├── metrics/
│   ├── collector.py           throughput, latency (mean/p50/p95), collision/retry/drop counters
│   └── events.py              append-only event trace (CCA, BACKOFF, TX_START, TX_END,
│                              COLLISION, RETRY, ACK, DROP)
├── scenarios/
│   ├── scenario_a.py          1 AP / 1 STA, single channel, saturated
│   └── scenario_b.py          2 AP / 2 STA, same channel, both saturated
└── tests/
    ├── test_primitives.py     11 sanity tests for primitive correctness
    ├── test_freeze_resume.py  5 CSMA/CCA behavior tests
    └── test_sprint1.py        gate: runs all tests + Scenarios A/B
```

## 2. Not implemented (per Sprint 1 prohibitions)

| Mechanism | Sprint |
|-----------|--------|
| MLO (`features/mlo.py`) | 3 (Feature Pack) |
| OFDMA, MU-MIMO, Block ACK, A-MPDU/A-MSDU | on-demand |
| Spatial Reuse, OBSS_PD, BSS Coloring | on-demand |
| EDCA / QoS AC | on-demand |
| 320 MHz channels, channel puncturing | on-demand |
| Mobility | on-demand |
| TCP/IP, ns-3 integration | out of scope |
| Complex YAML framework | deferred (Python dict only) |
| Plugin / registry / factory architecture | deliberately not built |
| `decision_interval` time scale + Controller API | Sprint 2 |
| Legacy Adapter (`controllers/legacy_adapter.py`) | Sprint 2 |
| Multi-BSS topology (≥ 5 APs / overlapping channels) | Sprint 2 |
| Real interferer traffic + on-off/CBR traffic models | Sprint 2 |
| Capture effect (simultaneous TX at different power) | on-demand |
| RTS/CTS, Block ACK | on-demand |
| Rate adaptation (vs Ideal MCS) | on-demand |
| Full MCS tables (HT, VHT, EHT) | Sprint 2+ |
| Analytical correctness tests (Bianchi) | Sprint 2 |

## 3. Scenario A: 1 transmitter, no competitor

- Setup: 1 AP at (0, 0), 1 STA at (10, 0), MCS 11 (143.4 Mbps),
  2304-byte packets, 5 sec run.
- **PASS** (see `/tmp/sprint1` gate output):

  ```
  throughput       : 66.96 Mbps
  success packets  : 18164
  collisions       : 0
  retries          : 0
  drops            : 0
  latency p95      : 4.6 ms (queue builds because lambda >> capacity; expected)
  ```

  Event trace confirms `CCA → BACKOFF → TX_START → TX_END → ACK` sequence with
  no contention. Theoretical saturation throughput for MCS 11 at this SINR
  is ~61 Mbps; measured 67 Mbps (within ±15% of theoretical, per S9).

## 4. Scenario B: 2 saturated contenders, same channel

- Setup: AP0 at (0,0)→STA0 at (10,0), AP1 at (50,0)→STA1 at (60,0); both
  MCS 11, both saturated, 5 sec run.
- **PASS**:

  ```
  aggregate throughput : 73.48 Mbps
  AP0 success          : 10050 packets
  AP1 success          : 9884 packets   (fairness 0.9% — well within ±25%)
  AP0 collisions       : 1110
  AP1 collisions       : 1110
  total retries        : 2220
  drops                : 0
  ```

  Event trace confirms `COLLISION` events fire when two MACs hit BO=0 in
  the same slot boundary, and both MACs report `FAIL_COLLISION` (the
  simultaneous-start marker in `ChannelState.mark_collisions_at_slot` is
  the load-bearing fix).

  **Note on aggregate > single-AP saturation** (73.5 vs 67 Mbps): this is
  consistent with the Bianchi DCF model, where saturation throughput for
  small n (n=2..3) can be similar to or slightly above n=1 due to BO
  amortization. The relevant signal is collisions > 0 and retries > 0;
  aggregate is bounded by Bianchi asymptote as n grows.

## 5. Sanity / unit test results (Sprint 1 §A.1 subset)

| Test | Status |
|------|:------:|
| S1 timing constants match citations | **PASS** |
| S2 path_loss.d_1m | **PASS** |
| S3 path_loss.shadowed (cached) | **PASS** |
| S4 queue.enq_deq (FIFO + latency) | **PASS** |
| S5 mcs.ideal_select (highest MCS) | **PASS** |
| S6 airtime.payload_only = preamble + 8*size_bytes / rate | **PASS** |
| S7 backoff.draw (uniform [0,CW]) | **PASS** (Chi-square < 37.7) |
| S7b backoff.formula values (15, 31, 63, 127, 255, 511, 1023) | **PASS** |
| S8 backoff.freeze_resume | **PASS** |
| S9 csma.single_sat throughput ±15% of theoretical | **PASS** (64.8 vs 61 Mbps) |
| S10 csma.two_ap_same_channel (fairness + collisions + retry + freeze/resume + finite agg) | **PASS** |
| S11 retry.exhaustion (drop after retry_limit) | **PASS** |
| S12 cca.energy (busy when TX active) | **PASS** |
| S13 sinr.linear_sum: (a) two −60 dBm interferers → −56.99 dBm, (b) signal −60 dBm + interferers + noise → ~−3.01 dB | **PASS** |
| S14 event_loop.no_negative_time | **PASS** |
| S15 rng.reproducibility (same seed → same trace) | **PASS** |

Run with: `python -m wifi_simulator.tests.test_sprint1`.

## 6. Phase 0 Hotfix (DIFS + SINR + S10/S13 + capture-effect removal + doc cleanup)

Applied after Sprint 1 sign-off. No architecture change.

### 6.1 DIFS timing fix

- **Before.** `MacStation` used `difs_remaining_slots = DIFS_NS // SLOT_TIME_NS = 3`,
  counting down per slot. With `DIFS_NS = 34_000` and `SLOT_TIME_NS = 9_000`,
  this gives 3 × 9 us = **27 us** of DIFS — not 34 us. Throughput was
  ~10% over Bianchi theoretical as a result.
- **After.** `MacStation` stores `difs_end_ns = now + DIFS_NS` and transitions
  out of DIFS_WAIT on the first slot boundary where `now_ns >= difs_end_ns`.
  No new scheduler abstraction. DIFS wait is now in the range [34, 43] us
  depending on slot alignment — no more floor-rounding shortcut.
- **Throughput before vs after** (5 sec run, saturated):
  - Scenario A: **66.96 → 64.83 Mbps** (−3.2 %; closer to theoretical ~61 Mbps).
  - Scenario B: **73.48 → 70.94 Mbps** (−3.5 %; still in [40, 100] Mbps sanity range).

### 6.2 SINR formula correction (doc only — code was already correct)

- **Doc bug.** `RESEARCH_ENV_DESIGN.md` §5.2 wrote
  `P_total_W = P_signal_W + P_interf_W + P_noise_W; SINR = signal / P_total_W`
  (denominator included the signal power — wrong).
- **Fix.** Doc now states `SINR_dB = 10·log10( P_signal_W / (P_interf_W + P_noise_W) )`,
  matching the code in `wifi_simulator/phy/sinr.py` (which was already correct
  throughout Sprint 1).

### 6.3 S13 retest

Old assertion: "two −60 dBm interferers ⇒ SINR ≈ −57 dB" (undefined desired
signal). New: two-sub-assertion test:
- (a) two equal −60 dBm interferers aggregate to **−56.99 dBm**
  (= 10·log10(2·10⁻⁶)).
- (b) given a separate desired signal at −60 dBm and noise at −95 dBm,
  SINR = 10·log10(10⁻⁹ / (2·10⁻⁹ + 3.16·10⁻¹³)) ≈ **−3.01 dB**.

### 6.4 S10 retest

Removed the "aggregate must be strictly lower than single-AP" pass criterion
(Bianchi DCF: total throughput can peak at small n). S10 now asserts:
- per-AP throughput comparable (within ±25 %);
- collisions > 0;
- retries > 0;
- at least one BACKOFF event in the trace (proves BO path is wired);
- aggregate finite and in [40, 100] Mbps sanity range.

### 6.5 Capture effect removed from Core validation

A4 (capture effect) was moved from `§A.2 Analytical` to a new
`§D Optional PHY Enhancement Validation` section. Capture effect is NOT
implemented in the Core and is on-demand per paper.

### 6.6 Doc cleanup

- `MVP_AND_FEATURE_BACKLOG.md`: Sprint 1 mapping line referenced
  `C3 (seeded RNG)` — fixed to `C3 (collision / ACK / retry)`. Seeded RNG
  is B1 (Research Infrastructure).
- `RESEARCH_ENV_DESIGN.md` and `MVP_AND_FEATURE_BACKLOG.md`: "correlated
  shadowing" → "cached per-link / link-persistent shadowing" (we do not
  implement spatial correlation; only link-persistent cache).
- "Core has no MLO awareness" → "Core contains no MLO behaviour; only
  minimal extension hooks (per-link MAC, per-link queue, per-link CCA) may
  exist" (per-link primitives are still in Core).

### 6.7 Phase 0 validation gate result

- Scenario A (1 saturated transmitter): **PASS** — 64.83 Mbps, 0 collisions.
- Scenario B (2 saturated same-channel contenders): **PASS** — 70.94 Mbps aggregate,
  fairness 2.2 %, 1031+1031 collisions, 2062 retries, freeze/resume triggered.
- No correctness failures. **Ready to enter Sprint 2.**

## 7. Known limitations (Sprint 1 after hotfix)

1. **DIFS alignment overshoot.** DIFS wait is in [34, 43] us depending on
   slot alignment, not exactly 34 us. Within slot-time tolerance;
   acceptable for all current papers. Tighter matching would need
   sub-slot scheduling, deferred to a paper-driven request.

2. **No capture effect.** When two TXs overlap, both fail regardless of
   relative power. Simpler model is fine for Sprint 1. Capture effect is
   on-demand for papers that compare absolute throughput across power
   configurations (§D `P1`).

3. **Simultaneous-start collision detection** depends on
   `mark_collisions_at_slot` at the slot boundary. If two MACs hit BO=0 in
   *different* slot boundaries but their airtimes overlap (e.g., one TX
   starts just as another ends), the collision is detected at TX_END via
   `overlapping_others` — this path was verified by hand-tracing, not by
   an automated test.

4. **Event-loop scheduling overhead.** Each slot boundary schedules the
   next slot at +9 us, so the priority queue holds ~600K future events at
   any moment during a 5 sec run. heapq handles this but adds ~20% to wall
   time vs a tighter scheduler. Acceptable for Sprint 1; optimize in
   Sprint 2 only if DRL training throughput becomes a bottleneck.

5. **No controller** — Controller API and `decision_interval` are Sprint 2.

6. **Path-loss distances** are computed from explicit `pos_ap` / `pos_sta`
   tuples. Interferer signal at a STA uses AP-AP distance (since STA is
   co-located with AP in Sprint 1). This is a Sprint 1 simplification;
   real STA positions are Sprint 2.

## 8. Sprint 2 — minimum proposal

(Only after Sprint 1 is reviewed. Do NOT start until §10 sign-off.)

In order of dependency:

1. **Multi-BSS support** — 5+ APs, overlapping channels, non-co-located STAs.
   Refactor `Simulator._distance` to look up arbitrary (tx, rx) positions.
2. **Real interferer traffic** — interferers are full MacStations running
   CSMA/CA. They do not transmit at `pt_max` continuously. (Already
   structurally supported; just add more APs in scenario.)
3. **Channel selection** — `Controller.select_channel(ap, ch)`.
5. **Per-link / per-channel Tx power** — `Controller.set_tx_power(link_id, dbm)`.
6. **CCA control** — `Controller.set_cca(channel, dbm)`.
7. **`decision_interval`** — RL agent called once per `decision_interval_ns`,
   not per slot. Default 4.5 ms (legacy-compatible).
8. **Legacy Adapter** — `wifi_simulator/controllers/legacy_adapter.py` mapping
   L1/L2/L3 hierarchical actions to the new Controller API.
9. **First Legacy-vs-Research experiment** — `Exp_1`-equivalent scenario
   on new env via Legacy Adapter. Output as scientific result (not pass/fail).

MLO Feature Pack and per-MCS throughput histograms / p99 latency / CCA
energy histograms remain on-demand.

## 9. Decisions required before Sprint 2

None. The Sprint 2 path is fully specified by `RESEARCH_ENV_DESIGN.md`
and `MVP_AND_FEATURE_BACKLOG.md`; no design questions remain for the user
before implementation begins.

If the user wants to ship a paper on Sprint 1 outputs directly (e.g., a
Sprint 1 result on Bianchi or capture effect), the dependencies above can
be re-ordered; otherwise Sprint 2 follows §8.