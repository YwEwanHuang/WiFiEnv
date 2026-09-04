# VALIDATION_PLAN.md

**Stage**: Design (Design Convergence pass, ready for Sprint 1).

The plan is split into two **independent** parts:

- **A. Simulator Correctness Validation** — does the simulator faithfully
  implement its own model? Pass / fail.
- **B. Legacy-vs-Research Scientific Robustness Experiment** — do Project_3
  algorithm conclusions derived under the legacy abstract Wi-Fi model still
  hold under CSMA/CA + packet PHY? This is a **scientific result**, not a
  simulator verdict.

ns-3 validation is a third, **optional** external reference used only when
needed for publication credibility.

---

## A. Simulator Correctness Validation

The only correctness question is:

> Does the simulator behave the way its own model definition says it does?

Correctness is a property of the *implementation*. It does **not** say
whether the model is the right model for a given study — that is a
research judgment, made per paper.

Correctness validation has three layers, each with explicit pass/fail:

1. **Sanity / unit tests** — every primitive does what its docstring says.
2. **Analytical tests** — known-form Wi-Fi results match within tolerance.
3. **Deterministic reproducibility** — same seed produces identical traces.

### A.1 Sanity / unit tests (`wifi_simulator/tests/`)

One assertion per primitive, then move on. No fixtures, no per-function
suites. The list is intentionally small.

| # | Test | What it asserts | Pass criterion |
|--:|------|-----------------|----------------|
| S1 | `timing.constants` | `SLOT`, `SIFS`, `DIFS`, `EIFS` match the values listed in `mac/timing.py` source citations | numeric equality |
| S2 | `path_loss.d_1m` | path loss at d=1m equals `freq_loss` for the chosen carrier | exact |
| S3 | `path_loss.shadowed` | shadowing is drawn once per (tx, rx) and reused — same pair returns same value on second call | exact |
| S4 | `queue.enq_deq` | FIFO order preserved; latency = `success_time_ns − enq_time_ns` | exact |
| S5 | `mcs.ideal_select` | given SINR, returns highest MCS whose threshold ≤ SINR; never exceeds table max | exact |
| S6 | `airtime.payload_only` | `airtime_us = preamble_us + (size_bits) / rate_mbps`, where `size_bits = 8 * size_bytes` (NOT `8 * size_bits`) | exact |
| S7 | `backoff.draw` | `BO` uniform in `[0, CW]`; CW follows `min((CW_min+1)*2^r - 1, CW_max)` and saturates at `CW_max` | statistical (10k samples, Chi-square on uniform) |
| S8 | `backoff.freeze_resume` | busy slot freezes counter; idle slot decrements; resume after busy starts from frozen value | exact (deterministic seed) |
| S9 | `csma.single_sat` | one saturated AP, no interferer → throughput is bounded by `1 / (DIFS + E[BO]·slot + T_data + SIFS + ACK)` (theoretical MAC throughput), latency bounded by 1 retry | ±15 % vs hand-computed airtime |
| S10 | `csma.two_ap_same_channel` | two saturated APs on same channel → **fairness** + **collision/retry trend** + **freeze/resume triggered** + **aggregate finite & physically plausible** — NOT `each = ½ · PHY capacity`; n=1 vs n>1 aggregate direction is left to Bianchi analytical (A1), not asserted here | qualitative (see §A.1.1) |
| S11 | `retry.exhaustion` | packet dropped after `retry_limit` failures | exact |
| S12 | `cca.energy` | signal above CCA threshold for ≥1 slot marks channel busy | exact |
| S13 | `sinr.linear_sum` | interference aggregated in linear domain, NOT dBm: (a) two equal −60 dBm interferers → aggregate interference power ≈ **−56.99 dBm** (10·log10(2·10⁻⁶) = −56.99); (b) given a separate desired signal power, SINR = 10·log10(signal_W / (interf_W + noise_W)) matches hand calculation | exact (two sub-assertions) |
| S14 | `event_loop.no_negative_time` | every event has `time_ns ≥ 0` and `time_ns ≥ clock` | exact |
| S15 | `rng.reproducibility` | same seed, same scenario, same algorithm → identical event trace | exact |

**Layer pass criterion**: all sanity tests green (15 conceptual slots
S1–S15; in code, S7 is split into `S7` and `S7b` for statistical and
formula-check coverage — see `wifi_simulator/tests/test_primitives.py`).
The numbering and pass criteria in §A.1 below remain authoritative.

#### A.1.1 Two-saturated-AP test — what to actually check (S10)

`each throughput = 0.5 × PHY capacity` is **wrong** because under real
CSMA/CA:

- DIFS, backoff, SIFS, ACK, preamble overhead consume airtime.
- Aggregate throughput is in the same order of magnitude as single-AP
  saturated throughput (Bianchi DCF: total throughput can peak at small n
  due to BO amortization, so aggregate may be similar to or slightly
  above single-AP saturation).
- Fairness between two equal APs is high, but jitter and exact split depend
  on seed.

S10 must verify, qualitatively:

1. Each AP's throughput is **comparable** (within ±25 %).
2. Collision / retry counts are **non-zero** (proves CSMA/CA contention is
   actually exercised).
3. Freeze/resume is **actually triggered** in the event trace — i.e., at
   least one BO counter is frozen mid-count and then resumed after busy
   ends + DIFS (proves the slot-boundary CCA / freeze / DIFS path is
   wired correctly, not just the TX path).
4. Aggregate throughput is **finite and physically plausible** (in the
   50–90 Mbps range for the standard scenario; this is a sanity bound,
   not a Bianchi comparison).

**S10 does NOT assert that aggregate is below single-AP saturation.** The
n=1 vs n>1 relationship is a property of Bianchi DCF and is judged
analytically in A1, not as a sanity-test pass criterion.

#### A.1.2 Saturated throughput test (S9) — what to compare against

`throughput ≈ PHY capacity` is **wrong** because DIFS / backoff / preamble /
ACK still take airtime even with one saturated AP and no interferer.

S9 must compare against:

- The theoretical MAC saturation throughput for a single DCF node:
  `S = T_data / (T_data + DIFS + E[BO]·slot + SIFS + ACK)`
  (with `E[BO] = CW_min / 2 = 7.5` slots for r=0).
- A hand-computed airtime calculation: `(payload_bits + preamble_bits) / mcs_rate_mbps`.

#### A.1.3 Bianchi-style test — what `n` means

When the simulator says "Bianchi n", `n` is the **number of saturated
contention nodes**. A scenario where only the AP transmits saturated
downlink and the STA only returns ACK is **not** two saturated Bianchi
contenders — it is one saturated AP contending with one nearly-silent STA.
This must be respected when interpreting A1/A2 results.

### A.2 Analytical tests

Known-form results. 5 % – 20 % tolerance is typical; tighter is suspicious.

| # | Test | Reference | Tolerance |
|--:|------|-----------|:---------:|
| A1 | Saturation throughput, n saturated DCF nodes (no STAs-only-ACK, see §A.1.3) | Bianchi 1998 IEEE 802.11 DCF saturation throughput, n=2..8 | ±15 % |
| A2 | Poisson arrival, light load, 1 AP, no interferer | `λ · 2304 · 8 / 1e6` Mbps for small λ | ±10 % |
| A3 | CSMA/CA airtime, retry p | `p^r · (1−p)` retry distribution; expected airtime = `T_e + Σ p^r · T_r` | ±15 % |
| A5 | Shannon throughput upper bound at high SINR | for `SINR > 30 dB`, throughput ≤ `BW · log2(1+SINR)` | exact upper bound |
| A6 | Multi-BSS interference: per-BSS throughput | `R_i ≈ R_sat / (n_active_i + Σ_interferer_factor)` | monotonic in interferer count |

**Layer pass criterion**: all 5 analytical tests pass. A1 is the
load-bearing test — if it fails, the CSMA/CA core is wrong. Capture
effect (formerly A4) is moved to §D Optional PHY Enhancement Validation
and is NOT part of the Core gate.

### A.3 Deterministic reproducibility

- Same `seed`, same scenario, same algorithm → identical event trace,
  byte-for-byte. (S15 covers the RNG side; an end-to-end trace-equality test
  on a small scenario is added in Sprint 2.)

**Layer pass criterion**: 100 % byte-equal event trace for a fixed seed
across at least 100 k events.

### A.4 Correctness pass criteria

The simulator is **correct** when:

1. All sanity tests (S1–S15, with S7 covering both statistical and
   formula) pass.
2. All 5 analytical tests (A1, A2, A3, A5, A6) pass at the listed tolerance.
3. Deterministic reproducibility holds.

This is the **only** definition of "the simulator is right". Nothing in
part B affects this. Capture effect and spatial correlation are not part
of Core correctness — see §D.

---

## B. Legacy-vs-Research Scientific Robustness Experiment

This is **not** a simulator correctness test. It is a research experiment
whose outcome is itself a publishable result.

### B.1 The question

> Do Project_3 algorithm conclusions, derived under the legacy abstract
> Wi-Fi model, still hold under a more realistic CSMA/CA + packet PHY?

The legacy abstract model is:

- 4.5 ms super-slot, one-step binary CCA outcome.
- Shannon capacity, no MCS, no airtime, no retry.
- Always-on interferers at `pt_max`.
- Integer queue, no latency.

### B.2 What is NOT a pass criterion

The following are **explicitly forbidden** as pass / fail rules:

- ❌ "Algorithm ranking must match the legacy ranking." A ranking flip is
  itself a publishable finding ("X looked best in abstract model; Y is
  best under realistic contention").
- ❌ "New throughput must be lower than legacy throughput." The new
  environment has real CSMA/CA with real duty cycle; the legacy
  environment has always-on interferers. Depending on configuration, new
  throughput can be **higher or lower** than legacy.
- ❌ "Collision count must be > 0." Correctness (A.4) already proves CSMA/CA
  is wired up; the research experiment reports whatever collision count
  appears and interprets it.

### B.3 What IS reported

For each scenario in §B.4, the experiment outputs:

| Output | Meaning |
|--------|---------|
| `ranking_preserved` | Did the relative order between algorithms match legacy? (`YES` / `NO` / `PARTIAL`) |
| `throughput_delta` | New throughput − legacy throughput, per AP and total |
| `collision_count` | Number of collisions observed |
| `retry_count` | Number of retries observed |
| `latency_p95` | New-env p95 latency (legacy has no latency) |
| `possible_reason` | One-line diagnosis if ranking flipped or throughput changed sign |

All six are *scientific results*, not pass / fail flags.

### B.4 Scenarios

| Scenario | Setup | Reference |
|----------|-------|-----------|
| L-1 | `Exp_1_trainAgents.py` default: 4 APs (Normal), 3 channels, Poisson λ=200, target AP = 0 | `Results/Exp_1_Train/DQN_DQN_DQN.csv` |
| L-2 | `Exp_4_diffChannelNumber.py` n_channels=8 | `Results/Exp_4_diffChannelNumber/` |
| L-3 | `Exp_1_trainAgents_IEEEScenario.py`: 10 APs (Apartment), walls | `Results/Exp_1_Train_IEEEScenario/` |

### B.5 Failure handling

If the experiment shows a *ranking flip* or a *throughput sign reversal*:

1. Record the observation in `tests/legacy_compare/<scenario>.md`.
2. Inspect whether the new env violates §A (correctness) — if so, fix the
   sim first.
3. Otherwise, the finding is reported as **"the legacy abstract model
   distorted the algorithm comparison for this configuration"** in the
   paper text.

### B.6 The headline result

Once §A passes and at least one §B scenario runs end-to-end, write one
`tests/legacy_compare/HEADLINE.md` containing:

- Ranking-preserved / ranking-flipped per algorithm pair.
- Throughput direction per scenario.
- Collision / retry / latency observations.
- A short paragraph explaining which mechanism (CSMA/CA, MCS, retry, real
  interferer duty cycle) likely caused each divergence.

This is a paper section, not a test report.

---

## D. Optional PHY Enhancement Validation

This section is **not** part of the Core correctness gate. It only runs
when a specific paper enables the corresponding feature.

| # | Test | When to run | Reference |
|--:|------|-------------|-----------|
| P1 | Capture effect (SINR-based, linear-domain) | A paper enables capture: two simultaneous TXs at different powers → stronger wins if `P_strong / P_weak > capture_ratio` | ±10 % |
| P2 | Spatial-correlated shadowing | A paper enables `SpatialShadowField`: shadowing follows a Gaussian random field; same-location links see similar shadowing | qualitative |
| P3 | Rate adaptation (MiniRate / full RA) | A paper enables RA: MCS selected by feedback, not Ideal Selection | paper-specific |

These tests are **NOT** required for the Core to ship. They are recorded
here so that the validation contract is complete when a feature pack
extends the Core. **Do not implement capture effect or spatial correlation
just to satisfy validation** — they are on-demand per paper.

---

## C. ns-3 spot validation (optional, external)

ns-3 is the **reference simulator** but **not** a Core blocker. It runs
only if a paper needs external credibility, or if a reviewer specifically
asks for ns-3 comparison.

### C.1 Version policy

- **No specific ns-3 version is fixed at design time.**
- The version will be fixed **only when ns-3 validation actually starts** —
  i.e., when there is a concrete paper or credibility need.
- MLO validation, when it happens, must use an ns-3 version with **explicit,
  documented MLO support** (i.e., a version where the `wifi-mlo` model is
  stable and tested). The exact version is fixed at validation start.
- Do **not** spend design-time building an ns-3 framework now. The Sprint 1
  implementation does **not** include ns-3 integration.

### C.2 Scenarios (sketch only)

When ns-3 validation is later scheduled, it will cover a small set:

| # | Scenario | What to compare |
|--:|----------|-----------------|
| N1 | 1 AP, 1 STA, saturated UDP | per-MCS throughput curve vs Core |
| N2 | 1 AP, 8 STAs, DCF | aggregate saturation throughput |
| N3 | 2 APs, same channel, light UDP | OBSS baseline |
| N4 | 4 APs, 2 channels, mixed traffic | multi-BSS |
| N5 | 1 MLD, 2 links, STR | MLO STR aggregate |

### C.3 Trend-level agreement

- throughput ordering across configurations matches ns-3,
- collision / retry rates within a factor of 2,
- latency p95 within a factor of 3.

We do **not** require event-by-event match.

---

## D. Validation outputs

- `tests/test_results.xml` — pytest output for §A.
- `tests/analytical_plots/*.png` — each A-test with reference curve overlaid.
- `tests/legacy_compare/*.png` + `*.md` — per-scenario §B observation + analysis.
- `tests/ns3_compare/*.png` + `*.md` — per-scenario §C observation (if run).
- `tests/VALIDATION_REPORT.md` — which layer passed; open issues.

---

## E. Pass criteria summary

| Layer | Pass criterion | Status |
|-------|---------------|--------|
| §A.1 Sanity | All 15 tests green | required |
| §A.2 Analytical | All 5 tests within tolerance (A1, A2, A3, A5, A6) | required |
| §A.3 Reproducibility | 100 % byte-equal event trace on same seed | required |
| §B Legacy-vs-Research | Per-scenario observation reported (no pass/fail) | required for paper use |
| §C ns-3 spot check | Trend agreement within listed factors | optional, on demand |
| §D Optional PHY Enhancement | Only when the corresponding feature is enabled | not required for Core |

The Core is **publishable** when §A.1, §A.2, §A.3 all pass. §B is a
research output, not a gate. §C is on demand. §D runs only when a
specific feature (capture, spatial correlation, RA) is enabled for a
paper.

---

## F. STOP

This is the validation contract for Sprint 1. Sprint 1 must satisfy the
§A.1 sanity tests for its scope (event loop, RNG, queue, basic airtime,
basic path loss / SINR, CSMA/CA, throughput + latency + collision / retry
metrics). §A.2, §A.3, §B, and §C are scheduled for later sprints.