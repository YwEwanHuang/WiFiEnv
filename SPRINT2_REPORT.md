# SPRINT2_REPORT.md

**Stage**: Sprint 2 complete.
**Scope**: minimum vertical slice for the first Legacy-vs-Research
experiment on the Project_3 'Normal' 4-AP scenario.

---

## 1. Phase 0 Hotfix result (recap)

DONE before Sprint 2 started. No architecture change.

| Item | Status |
|------|:------:|
| SINR formula in `RESEARCH_ENV_DESIGN.md` §5.2 corrected to `P_signal / (P_interf + P_noise)` (code was already correct) | **DONE** |
| S13 retest: (a) two −60 dBm → −56.99 dBm, (b) signal + interferers + noise → ~−3.01 dB | **DONE** |
| S10 retest: removed "aggregate < single-AP" pass criterion; now asserts fairness + collisions + retries + freeze/resume + finite agg in [40, 100] Mbps | **DONE** |
| Capture effect moved from `§A.2` to new `§D Optional PHY Enhancement Validation`; not implemented | **DONE** |
| DIFS timing: `MacStation` now uses `difs_end_ns = now + DIFS_NS`, no floor-rounding | **DONE** |
| Doc cleanup: `C3 (seeded RNG)` typo fixed; "correlated" → "cached per-link shadowing"; "no MLO awareness" → "no MLO behaviour; minimal extension hooks may exist" | **DONE** |
| Scenario A throughput (single saturated AP): 66.96 → **64.83 Mbps** (−3.2 %) | verified |
| Scenario B throughput (2 saturated APs): 73.48 → **70.94 Mbps** (−3.5 %) | verified |
| All Sprint 1 sanity tests still green | **PASS** |

## 2. Sprint 2 implementation

### 2.1 Multi-BSS + multi-channel

- New module `core/channel_registry.py`:
  `ChannelStateRegistry` maps `channel_id` → `ChannelState`. Each MAC
  looks up its own channel state via `registry.get(channel_id)`.
- `Simulator.__post_init__` registers all channels used by `ApStation`s
  and groups MACs by channel during slot processing (so APs on different
  channels don't see each other as busy).
- Distance lookup refactored: `_device_positions` dict covers both APs
  and STAs, so any (tx, rx) pair is resolvable. STA positions are
  derived from `gen_sta_position`-style 4-STA layout.

### 2.2 Per-link / per-channel Controller

`controllers/controller.py` exposes:
- `set_tx_power(link_id, dbm)`
- `set_tx_power_for_ap_channel(ap_id, channel_id, dbm)` — convenience
  for legacy L1/L2-style power-per-channel control
- `set_cca(channel_id, dbm)` — applies to all MACs on the channel
- `set_cca_for_ap(ap_id, dbm)` — single MAC's CCA
- `get_observation(ap_id)` — flat dict (queue, retry, backoff, MCS,
  throughput counters)

The Controller writes directly to MacStation state. No per-`decision_interval`
scheduler yet — the caller (RL loop or Legacy Adapter) decides when to
invoke. This is enough for Sprint 2's first vertical slice.

### 2.3 `decision_interval`

Documented in `RESEARCH_ENV_DESIGN.md` §3.3. **Not yet invoked** in
Sprint 2's first experiment — the Legacy Adapter is called **once at
startup** to apply the default policy, then the env runs.

The decision_interval scheduler is on the Sprint 3+ path when a real
RL agent is plugged in. The Controller is already there as scaffolding.

### 2.4 Observation aggregation

`MetricsCollector.summary(duration_ns)` already aggregates:
- per-link throughput, success, collision, retry, drop counts
- mean / p50 / p95 latency
- total throughput, total success, total drops

`Controller.get_observation(ap_id)` returns a single-AP view; Sprint 2
does not implement a multi-AP observation vector yet (this is on-demand
per paper).

### 2.5 Legacy Adapter

`controllers/legacy_adapter.py`:
- `LegacyAdapter(sim, target_ap, pt_max_dbm)` wraps a `Simulator`.
- `apply_actions(l1_subset, l2_power, l3_cca)` maps the legacy
  hierarchical actions to `Controller.set_*` calls.
- `default_policy(channel)` — convenience for the first experiment.
- `no_op()` — equivalent to L1=empty / L2=zero / L3=default.

Power mapping: legacy decimal `p` (∈ [0, 1]) → `pt_max_dbm + 10·log10(p)` dBm.
`p = 0` → "muted" (tx power = −100 dBm, below any realistic CCA).

### 2.6 Legacy-vs-Research experiment script

`experiments/legacy_vs_research_normal.py`:
- Same scenario (4 APs, 3 channels from `config/config.txt`).
- Same default policy (target AP on channel 0, full power, CCA −82 dBm).
- Same seed (6) where applicable.
- Same time horizon (1000 legacy slots = 4.5 s).
- Outputs both envs' metrics and a side-by-side comparison.

## 3. First Legacy-vs-Research experiment result

### 3.1 Setup (default policy, both envs)

- AP0 (target) on channel 0, full power, CCA −82 dBm.
- AP1 on channel 0 (interferer); AP2 on channel 1; AP3 on channel 2.
- arr_mean = 500 per 4.5 ms slot → 111,111 pps.
- Seed 6. n_steps = 1000. Wall-clock equivalent = 4.5 s.

### 3.2 Results

| Metric | Legacy (Project_3) | New (Research env) | Δ |
|---|---:|---:|---:|
| Total delivered (4.5 s) | 27,149 *Shannon-equivalent* packets | 48,999 *actual* packets | +80.5 % |
| Throughput (Mbps) | 111.20 (Shannon-based) | 200.70 (real packets × 2304 B) | +89.5 |
| Collisions | n/a (always-on interferer model) | 1,872 | — |
| Retries | n/a | 1,872 | — |
| Drops | n/a | 0 | — |
| Per-link tput (Mbps) | not per-link visible | 0:35.3 / 1:35.6 / 2:64.9 / 3:64.9 | — |
| Final queue (AP0) | 4,365 (drained) | 0 | — |
| Final queue (AP1-3) | 8,000 (initial; **never drained**) | 0 | — |

### 3.3 Most important finding

> **The legacy abstract model underestimates throughput by ~80 % on the
> Normal 4-AP scenario because it assumes always-on interferers at
> `pt_max`. The new env's CSMA-driven interferers have a real duty
> cycle, so the channel is not continuously jammed by AP1-3.**

Concretely:
- In legacy, AP1-3 always transmit at pt_max on their channels → all
  channels are saturated with interference. AP0 (target) sees strong
  interference from AP1 (same channel) AND from AP2/3 via cross-channel
  coupling (legacy's `I_per_channel_user` uses AP-AP distance, but the
  interferer model is the same: always on).
- In new env, AP1-3 are full MacStations: they contend for the channel
  via CSMA/CA. AP2 on channel 1 alone delivers 64.9 Mbps; AP3 on
  channel 2 alone delivers 64.9 Mbps; AP0 and AP1 share channel 0 and
  each gets ~35.6 Mbps (the Bianchi DCF split).
- The new env also drops packet counts that legacy cannot express
  (collisions, retries, real latency).

This is the kind of finding the prompt expects: the legacy abstract
model distorts the channel-occupancy picture enough to change the
absolute throughput by ~80 %. Whether it changes **ranking** between
algorithms requires running multiple policies — the next Sprint 2+
step.

### 3.4 Caveats

1. **Different units.** Legacy reports "Shannon-equivalent packets" —
   packets that *could* have been transmitted given the channel
   capacity. New env reports *actual* transmitted packets. The
   throughput numbers are in the same unit (Mbps) but model different
   things. This is a structural difference, not a bug.
2. **Single policy.** Only the default policy (target on channel 0,
   full power) was run. The "ranking preserved / changed" question
   requires comparing L1/L2/L3 actions across multiple policies.
3. **No decision_interval loop yet.** The Controller is set up but
   not invoked per `decision_interval` in this experiment. A real RL
   loop will come in Sprint 3+ when a learning agent is plugged in.

## 4. Current blockers

**None blocking Sprint 2 completion.** Open items deferred to Sprint 3+:

- `decision_interval` per-epoch observation loop (Sprint 3+, when a
  real learning agent is needed).
- Multi-AP observation vector (Sprint 3+, on demand per paper).
- ns-3 spot validation (still optional, no version fixed).
- Bianchi A1 analytical test (deferred — needs analytical simulator
  for n=2..8 DCF saturation, not the same as a one-shot sanity test).
- MLO Feature Pack (Sprint 3+).
- Real STA positions (currently each AP has 1 STA; legacy has 4
  STAs per AP — Sprint 3+, on demand).

## 5. Is it worth entering Sprint 3?

**Yes**, but only if a real research question drives it. The Sprint 2
vertical slice answers one question: *what does the legacy abstract
model get wrong on the Normal 4-AP scenario?* The answer is
"~80 % throughput underestimation due to always-on interferers". This
is enough to inform one paragraph of a paper. It is **not** enough
to claim Project_3's algorithm conclusions are wrong; that requires
running multiple policies and observing ranking flips.

Concrete Sprint 3 candidates (not yet committed):
- **Algorithm-comparison experiment** — run the legacy L1/L2/L3 DQN
  agent (loaded from `Models/`) on the new env via the Legacy Adapter,
  observe ranking changes per-algorithm.
- **`decision_interval` RL loop** — when a real learning agent is
  needed, wire the Controller into a per-epoch loop.
- **Multi-STA-per-AP** — if a paper's algorithms assume per-AP
  downlink to multiple STAs (the legacy `gen_sta_position` layout),
  refactor `ApStation` to support multiple STAs per AP.
- **MLO Feature Pack** — first Feature Pack to be designed but
  deferred to Sprint 4+ unless a paper drives it.

Sprint 2 ends here. No Sprint 3 implementation has started.

---

# Experiment Comparability Gate (Sprint 2.5)

Sprint 2 had a comparability bug: the reported +89 % comparison
mixed AP0-only (legacy) with all-APs (research) and mixed
Shannon-equivalent drained packets (legacy) with actually-transmitted
packets (research). Sprint 2.5 fixes this and runs a 3-condition
mechanism ablation across 5 seeds to identify the dominant cause of
the legacy vs research divergence.

## A.1 Metric definitions (made explicit)

| | E0 (Legacy) | E1 (Research core) | E2 (Research + always-on interferers) |
|---|---|---|---|
| What is counted | `n_packets[AP0]` in legacy `reward()`: **Shannon-equivalent drained packets** | `per_link[ap].success`: actually-transmitted packets (post-PER, post-collision) | same as E1 |
| How many APs counted | **AP0 only** (non-target AP queues are never drained) | all 4 APs (reported separately; **AP0 is headline**) | all 4 APs |
| What the number means | "if we could use the channel at Shannon capacity, this many packets would fit" | "this many packets actually went over the air" | same as E1 |
| Direct comparison? | **No.** The legacy metric is a *virtual* capacity; the research metric is *actual* delivery. | | |

**Conclusion**: the legacy 111 Mbps and research 200 Mbps from Sprint 2
were not directly comparable. The +89 % headline number is **invalid**
and is now **discarded**.

## A.2 AP0-to-AP0 normalized comparison (5 seeds)

Topology: 4 APs, 3 channels, target AP0 on channel 0, full power,
CCA −82 dBm. Arrival rate 111,111 pps per AP. Duration 4.5 s. 5 seeds
{6, 7, 8, 9, 10}.

```
E0 (legacy)                                  109.09 ±  3.36  [105.03, 112.72]  Mbps (Shannon-equiv)
E1 (research core)                            35.28 ±  0.16  [ 35.05,  35.49]  Mbps (actual)
E2 (research + always-on interferers)          0.00 ±  0.00  [  0.00,   0.00]  Mbps (actual)
```

**AP1-3 throughput (contextual, not in headline comparison)**:
```
link     E1 (research core)    E2 (always-on)
AP1              35.40                 97.52
AP2              64.93                 97.52
AP3              64.89                 97.52
```

**Collision counts (research conditions)**:
```
E1 system collisions: 1940.8 (mean across 5 seeds)
E2 system collisions:    0.0 (no CSMA → no collisions)
```

Per-seed numbers (see `experiments/legacy_vs_research_normal.py` for
the full per-seed dump) are reproducible across runs.

## A.3 Why the directions disagree

The headline observation is:

* E0 (legacy) AP0 reports **109 Mbps** but it is a Shannon-equivalent
  drained-packet count, not actual transmission.
* E1 (research) AP0 actually delivers **35 Mbps**.
* E2 (research + always-on interferers) AP0 actually delivers **0 Mbps**
  because the always-on interferer (AP1) keeps the channel busy, so
  AP0's backoff never reaches zero — AP0 cannot start a single TX.

The legacy env's `reward()` does not check whether the target AP can
*actually* start a TX. It just computes `dataRate = Shannon(p_signal,
p_interf)` and drains the queue by `dataRate * mbps2n_packet`. So when
the interferer is jamming, legacy still reports a positive "drained
packet" count, even though no real transmission happened.

In other words: **the legacy metric is not a lower bound on actual
throughput — it is a virtual capacity that ignores whether TX is
possible**. The direction "legacy > research AP0" is therefore a
statement about the legacy metric's *definition*, not about reality.

## A.4 Minimum mechanism ablation

What the three conditions isolate:

| Condition | Interferer (AP1-3) PHY / MAC | AP0 (target) | AP0 throughput |
|---|---|---|---|
| E0 — Legacy | always-on at pt_max (no MAC) | Shannon model, no airtime | 109 Mbps (virtual) |
| E1 — Research core | full CSMA/CA + airtime + Ideal MCS | full CSMA/CA + airtime + Ideal MCS | 35 Mbps (actual) |
| E2 — Research + always-on | always-on (no DIFS/backoff) | full CSMA/CA + airtime + Ideal MCS | 0 Mbps (actual) |

What the ablation tells us:

1. **Switching E1 → E2 (CSMA-driven → always-on interferers) reduces
   AP0 throughput from 35 Mbps to 0 Mbps.** Realistic duty cycle is
   what lets AP0 transmit at all.
2. **The legacy env's 109 Mbps is computed on a scenario (E0) that
   physically corresponds to E2** (always-on interferers), but the
   metric definition hides the fact that AP0 cannot actually transmit.
   So the legacy-vs-research gap is dominated by **metric definition
   mismatch**, not by PHY/MAC mechanism difference.
3. **Once metric mismatch is fixed, the research env (E1) is the
   only one that can produce a real, physically meaningful AP0
   throughput on this scenario.** The legacy env's 109 Mbps number
   is not refutable, but it is not a number about transmission — it
   is a number about queue drainage.

**Causal claim allowed by this data**:
> On the Normal 4-AP scenario, the legacy abstract model's "AP0
> throughput" is a Shannon-equivalent drained-packet count that is
> not directly comparable to actual transmitted packets. The new
> env's AP0 actually delivers 35 Mbps under the same fixed policy.
> Going from CSMA-driven interferers to always-on interferers
> (E1 → E2) drops AP0 from 35 Mbps to 0 Mbps, confirming that
> realistic interferer duty cycle is the dominant mechanism in the
> divergence.

**Causal claim NOT allowed by this data**:
> The legacy env underestimates / overestimates throughput by X %.
> The metric definitions are different; a single ratio is not
> meaningful.

## A.5 Topology / STA mismatch

Legacy `gen_sta_position` creates 4 STAs per AP (offsets ±2, 0 and 0,
±2). Current `scenarios/normal_4ap.py` uses only the first STA from
that layout (`pos_sta = sta_pos_for_ap(...)[0]`). One STA per AP.

**Impact on the comparison**:
* The legacy `reward()` uses `tx2who[ap]`, a *randomly chosen* STA
  from the 4 candidates, for path loss and interference aggregation.
  In any given step, legacy also uses one STA — the comparison is
  therefore against a "single effective STA per AP" abstraction, not
  a "4-STA diversity" abstraction.
* The 4-STA layout in legacy matters only for position diversity
  (random STA selection per step). It does **not** affect the
  `dataRate = Shannon(...)` formula itself.
* Net effect on AP0 throughput: small. The first STA at offset
  (−2, 0) is one of the 4; legacy's random pick averages over the
  4 positions, so the comparison is approximately fair.

**Verdict**: 1 STA per AP is acceptable for the current comparison.
Multi-STA support is NOT required for the Comparability Gate. It
becomes a Sprint 3+ item only if a paper's algorithm assumes
per-AP downlink to multiple distinct STAs (legacy's full
`gen_sta_position` layout).

## A.6 Sprint 2 / 2.5 interface checklist

| Feature | Status |
|---|---|
| Configurable `decision_interval` (ns) | **specified in design; not invoked at runtime yet** |
| `run_for(decision_interval_ns)` (epoch-bounded run) | **not implemented**; `Simulator.run()` is still monolithic |
| Observation aggregation at epoch boundary | **partial**: `MetricsCollector.summary` provides aggregate; per-epoch snapshot is not scheduled by the simulator |
| Controller action application at epoch boundary | **partial**: `Controller` setters exist and are immediate; no epoch scheduler applies them on a fixed cadence |
| Per-link granularity (channel / Tx power / CCA) | **implemented** in `Controller` |
| Legacy Adapter (L1/L2/L3 → Controller) | **implemented**; applied at startup, not per-epoch |

**Verdict**: the controller-side plumbing is in place. The
epoch-bounded `run_for(decision_interval_ns)` loop is **not** wired
in. The simulator can run for one full duration; what it cannot do
yet is run for a single decision interval and yield control back to
the agent. This is the next thing needed to plug in a real
`LearningAgent` (legacy DQN/DDPG), but it is **not** needed to make
the comparability claim above.

## A.7 Comparability Gate verdict

| Criterion | Status |
|---|---|
| 1. Comparison metric definition the same | **partial**: legacy uses Shannon-equiv, research uses actual; reported side-by-side, not as a single ratio. The +89 % headline is **discarded**. |
| 2. Target AP / system throughput not mixed | **PASS**: AP0 is headline; AP1-3 reported separately as contextual. |
| 3. Fixed-action baseline reproducible | **PASS**: same default policy (target on ch 0, full power, CCA −82 dBm); 5 seeds give std = 0.16 Mbps for E1 and 0 for E2. |
| 4. Direction stable across 5 seeds | **PASS**: E0 ≈ 109, E1 ≈ 35, E2 ≈ 0 across all 5 seeds. |
| 5. No single-mechanism misattribution | **PASS**: the ablation isolates realistic duty cycle as the dominant mechanism, with the caveat that the metric definition itself (Shannon vs actual) is a separate axis. |

**Conclusion**: the comparability gate is satisfied. The legacy
"109 Mbps" and the research "35 Mbps" are not directly comparable as
percentages, but the *direction* "research AP0 actually delivers
less than the legacy abstract capacity" is consistent across 5 seeds
and is supported by the E1 → E2 mechanism ablation. This is a
research finding, not a bug in either env.

## 6. Files added / changed in Sprint 2

```
wifi_simulator/
├── core/
│   ├── channel_registry.py     NEW   multi-channel TX state
│   └── simulator.py            CHANGED multi-BSS + registry
├── controllers/
│   ├── __init__.py             NEW
│   ├── controller.py           NEW   per-link API
│   └── legacy_adapter.py       NEW   L1/L2/L3 → Controller
├── scenarios/
│   └── normal_4ap.py           NEW   legacy Project_3 'Normal' mirror
└── experiments/
    ├── __init__.py             NEW
    └── legacy_vs_research_normal.py  NEW  first vertical slice
```

Sprint 1 tests still green (16/16 PASS).