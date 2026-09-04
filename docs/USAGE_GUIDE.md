# USAGE GUIDE — Research Wi-Fi Environment v1.0

This is the main reference for researchers and agents who want to **run,
modify, or extend** the Wi-Fi simulation environment.

> Audience: someone who has never seen the codebase. After reading this
> file you should be able to (a) run every shipped scenario, (b) build a
> new experiment from scratch, (c) drive a scenario with `ScriptedRunner`,
> (d) understand exactly what every metric means, and (e) know the rules
> for extending the environment without breaking the v1.0 freeze.

Source-of-truth reminder: when this guide disagrees with the code, the
**code wins** (the Core is frozen; only this guide should be corrected).

---

## 1. Library mental model

```
Scenario ─┐
          │ (defines aps[], seed, duration, optional mld_configs[])
          ▼
     Simulator ─── discrete-event loop, single seeded RNG, metrics
          │
          ├─ MacStation[]      per-link CSMA/CA state machine
          ├─ PacketQueue[]     per-(AP, link) FIFO
          ├─ PoissonTraffic[]  arrival generators  (or MldTraffic for MLD links)
          ├─ ChannelStateRegistry  per-channel busy-TX accounting
          ├─ PathLossModel     freq_loss + alpha*log10(d) + cached shadowing
          ├─ EventTrace        CCA / BACKOFF / TX / COLLISION / ACK / ...
          └─ MetricsCollector  success / fail / retry / drop / latency

Controller  ── per-link setters (channel, Tx power, CCA)
ScriptedRunner ── runs Simulator in fixed decision_interval epochs
                  and returns per-epoch delta metrics
```

You build a `Simulator` from a list of `ApStation` specs. The simulator
owns everything else. A `Controller` or `ScriptedRunner` is an **outer
driver** that reads state from and writes state to the simulator —
never the other way around.

---

## 2. Running an existing scenario

All shipped scenarios expose `run(duration_s, seed) -> dict`. The dict
keys are documented in §7.

### 2.1 Scenario A — single AP, saturated

**Purpose**: theoretical-throughput sanity check. No collisions.

```bash
python -m wifi_simulator.scenarios.scenario_a
```

- Topology: AP0 at `(0, 0)`, STA0 at `(10, 0)`, single channel 0
- Traffic: `lambda_pps = 100_000` (saturated; queue never empties)
- Expected: `collision == 0`, `retry == 0`, `drop == 0`
- Use case: baseline MAC throughput ≈ 65 Mbps (HE MCS 8–9 ideal)

### 2.2 Scenario B — same-channel contention

**Purpose**: two saturated contenders; verify collisions + retries.

```bash
python -m wifi_simulator.scenarios.scenario_b
```

- Topology: two AP/STA pairs on the same channel 0
- Traffic: both `lambda_pps = 100_000`
- Expected: `collision > 0`, `retry > 0`, fairness within ±25 %
- Use case: Bianchi-like DCF behaviour, collision / retry accounting

### 2.3 Scenario C — multi-BSS

**Purpose**: 4 APs, 3 channels, realistic interferer traffic.

```bash
python -m wifi_simulator.scenarios.scenario_c
```

- AP0: one link per channel (ch0, ch1, ch2)
- AP1: ch0 interferer
- AP2: ch1 interferer
- AP3: ch2 interferer
- All saturated (`lambda_pps = 100_000`)
- Use case: channel-reuse, cross-channel coupling, multi-BSS experiments

Programmatic API:

```python
from wifi_simulator.scenarios.scenario_c import run
result = run(duration_s=5.0, seed=6)
print(result["summary"])       # aggregate throughput/latency
print(result["per_link"])      # per-link breakdown
print(result["conservation"])  # success + drop ≤ arrivals check
```

### 2.4 M1 STR — two-link MLO

**Purpose**: formal MLO v0 capability — two-link MLD with STR.

```bash
python -m wifi_simulator.scenarios.m1_two_link_str
```

- 1 MLD (ap_id=0) with two links on orthogonal channels (ch0, ch1)
- MLD-level saturated Poisson arrival, **steering = round_robin**
- Links run **independent CSMA/CA** on each channel (no peer busy override)
- Expected: aggregate throughput ≈ sum of two single-link saturations

> **Single-radio ≠ IEEE NSTR.** The demo `experimental_single_radio`
> (`wifi_simulator/scenarios/experimental_single_radio.py`) ships
> alongside but is explicitly **not** a faithful model of IEEE 802.11be
> NSTR. Do not cite as NSTR in research output. See §9.

---

## 3. Creating a new experiment

The recommended workflow: **copy the closest existing scenario and modify
the minimum number of parameters**. Do not build complex objects from
scratch unless you need topology that none of the shipped scenarios has.

### 3.1 Minimal workflow

```
1. define topology   → list of ApStation (ap_id, sta_id, pos_ap, pos_sta)
2. define traffic    → lambda_pps per ApStation; size_bytes
3. set channel       → channel_id per ApStation
4. set Tx power      → tx_power_dbm per ApStation
5. choose seed       → int; same seed + config = same output
6. create Simulator  → Simulator(seed, duration_s, aps, ...)
7. run               → result = sim.run()
8. read metrics      → result['total_throughput_bps'], result['per_link'], ...
```

### 3.2 Minimal runnable example

```python
from wifi_simulator.core.simulator import ApStation, Simulator

sim = Simulator(
    seed=42,
    duration_s=2.0,
    noise_dbm=-95.0,        # thermal-noise floor (default -95)
    retry_limit=6,          # short retry limit (default 6)
    aps=[
        ApStation(
            ap_id=0, sta_id=10,
            pos_ap=(0.0, 0.0), pos_sta=(10.0, 0.0),
            link_id=0, channel_id=0,
            tx_power_dbm=18.0,
            lambda_pps=100_000.0,
            size_bytes=2304,
        ),
        ApStation(
            ap_id=1, sta_id=11,
            pos_ap=(50.0, 0.0), pos_sta=(60.0, 0.0),
            link_id=1, channel_id=1,        # orthogonal channel → no co-channel interference
            tx_power_dbm=15.0,
            lambda_pps=100_000.0,
            size_bytes=2304,
        ),
    ],
)
result = sim.run()
print(result["total_throughput_bps"] / 1e6, "Mbps")
print(result["per_link"])
```

### 3.3 Parameter cheat-sheet (for `ApStation`)

| Field | Type | Meaning | Default |
|---|---|---|---:|
| `ap_id` | int | AP identifier | required |
| `sta_id` | int | STA identifier | required |
| `pos_ap`, `pos_sta` | `(x, y)` meters | positions for path loss | required |
| `link_id` | int | unique per (AP, channel) | required |
| `channel_id` | int | 0..N-1 | required |
| `tx_power_dbm` | dBm | per-link transmit power | 18.0 |
| `lambda_pps` | packets/sec | Poisson arrival rate | 100.0 |
| `size_bytes` | bytes | payload size | 2304 |
| `cca_threshold_dbm` | dBm | per-link CCA threshold | -82.0 |

`Simulator` itself accepts `seed`, `duration_s`, `aps`, `noise_dbm`,
`retry_limit`, `cca_threshold_dbm` (default for all links), and
`mld_configs` (empty for non-MLD runs).

### 3.4 Prefilling the queue

If you want steady-state saturation **immediately** (no warm-up), prefill:

```python
result = sim.run(prefill_packets=200)  # enqueue 200 packets/AP at t=0
```

For most research questions, leaving the default (queue fills from
Poisson arrivals) is fine — the first ~1 s is the warm-up.

---

## 4. Scripted control (per-epoch driving)

`ScriptedRunner` drives the simulator in fixed `decision_interval`
epochs, applying a fixed channel / Tx power / CCA configuration each
epoch, and returns per-epoch delta metrics.

```python
from wifi_simulator.core.simulator import ApStation, Simulator
from wifi_simulator.controllers.scripted import ScriptedRunner

sim = Simulator(
    seed=42, duration_s=1.0,
    aps=[
        ApStation(0, 10, (0,0), (10,0), 0, 0, 18.0, 100_000.0, 2304),
        ApStation(1, 11, (50,0),(60,0), 1, 0, 18.0, 100_000.0, 2304),
    ],
)

runner = ScriptedRunner(sim, decision_interval_ns=450_000_000)   # 450 ms
runner.set_ap_channel_power({0: {0: 18.0}, 1: {0: 15.0}})        # AP0=18dBm, AP1=15dBm on ch0
runner.set_ap_cca({0: -82.0, 1: -82.0})                          # CCA per AP

epochs = runner.run()     # list of EpochResult, one per decision_interval
for e in epochs:
    print(e.epoch_index, e.throughput_mbps, e.collisions, e.queue_len)
```

`EpochResult` fields (dataclass):

`epoch_index`, `interval_s`, `now_ns`, `throughput_mbps`,
`collisions`, `retries`, `drops`, `latency_mean_us`,
`latency_p95_us`, `queue_len` (dict keyed by `ap_id`).

`ScriptedRunner` API:

| Method | Meaning |
|---|---|
| `set_ap_channel(mapping)` | `ap_id → channel_id` (active channel for AP's links) |
| `set_ap_channel_power(mapping)` | `ap_id → {channel_id → tx_power_dbm}` |
| `set_ap_cca(mapping)` | `ap_id → cca_threshold_dbm` |
| `run() -> list[EpochResult]` | Run until sim duration, yield per-epoch |
| `run_summary() -> dict` | One-shot aggregate over all epochs |

> **`decision_interval` is not a Wi-Fi slot.** The MAC / PHY run on the
> internal 9 µs slot. The controller only updates parameters at
> decision-epoch boundaries. This is the abstraction an RL agent would
> observe / act on. A typical value: 4.5 ms (legacy Normal config).

For finer-grained programmatic control (e.g. an RL loop that updates
parameters between epochs), use the lower-level `Controller`:

```python
from wifi_simulator.controllers.controller import Controller

ctrl = Controller(sim)
ctrl.set_tx_power(link_id=0, dbm=15.0)               # per-link
ctrl.set_cca(channel_id=0, dbm=-75.0)                # per-channel (all MACs on ch)
ctrl.set_cca_for_ap(ap_id=0, dbm=-78.0)             # per-AP
ctrl.set_tx_power_for_ap_channel(ap_id=0, channel_id=0, dbm=18.0)
obs = ctrl.get_observation(ap_id=0)                 # flat dict for an agent
```

`get_observation(ap_id)` returns `ap_id`, `link_id`, `channel_id`,
`tx_power_dbm`, `cca_threshold_dbm`, `queue_len`, `retry_count`,
`backoff_counter`, `tx_attempts`, `success_count`, `collision_count`.

---

## 5. Traffic

**Only Poisson arrivals are implemented** in v1.0. CBR / on-off /
trace-driven are deferred.

Per-`ApStation`:

- `lambda_pps` — packets / second (mean Poisson arrival rate)
- `size_bytes` — fixed payload size per packet (default 2304)

Internally each `ApStation` is given a `PoissonTraffic` whose inter-arrival
is `exponential(1 / lambda_pps)` drawn from the simulator's seeded RNG.
When `lambda_pps <= 0` the source is silent (used internally for MLD-
owned links; see §9).

> **Saturated regime**: set `lambda_pps = 100_000` or higher; the queue
> never empties, which exposes steady-state MAC behaviour. This is the
> default in every shipped scenario.

---

## 6. PHY / MAC parameters

These are the parameters researchers actually tune. Internal constants
(SLOT_TIME, SIFS, DIFS, EIFS, CW_MIN, CW_MAX) are intentionally **not**
in this list — they're frozen.

| Parameter | Where | Unit | Notes |
|---|---|---|---|
| `channel_id` | `ApStation` | int | 0..N-1; channels are independent (no cross-channel interference) |
| `tx_power_dbm` | `ApStation` | dBm | per-link; affects received power at all STAs |
| `cca_threshold_dbm` | `ApStation` / `Simulator` | dBm | per-link default; can be set globally on `Simulator` |
| `noise_dbm` | `Simulator` | dBm | thermal noise floor (default -95) |
| Path-loss model | `PathLossModel` | — | `freq_loss + alpha * log10(d) + shadowing`. Shadowing is cached per link, **not** spatially correlated (see §12). |
| MCS selection | `phy/mcs.py` | — | **Ideal** MCS Selection by default; no rate adaptation (see §12) |
| Packet airtime | `phy/airtime.py` | µs | preamble + payload_us |
| `size_bytes` | `ApStation` | bytes | payload (MAC SDU + header in v1) |
| `retry_limit` | `Simulator` | int | short retry limit (default 6) |
| `duration_s` | `Simulator` | seconds | total simulated time |
| `seed` | `Simulator` | int | single source of stochasticity |
| `decision_interval_ns` | `ScriptedRunner` | ns | epoch length for scripted / RL driving |

For full per-link / per-epoch control of Tx power, CCA, and channel,
drive the simulator via `Controller` or `ScriptedRunner` (§4).

---

## 7. Metrics

`Simulator.run()` returns a dict with the following keys. **Field
names are the actual code output — do not rename them.**

| Field | Type | Unit | Definition |
|---|---|---|---|
| `duration_s` | float | seconds | sim duration actually run |
| `total_throughput_bps` | float | bits / sec | **Goodput** of successfully delivered payload bytes / sim duration. **Not** airtime; collisions and PHY failures do not count. |
| `total_success_packets` | int | count | packets that reached success |
| `total_drop_packets` | int | count | packets dropped after `retry_limit` |
| `latency_mean_us` | float | µs | mean of `(success_time_ns - enqueue_time_ns) / 1000` |
| `latency_p50_us` | float | µs | median latency |
| `latency_p95_us` | float | µs | 95th-percentile latency (index `min(n-1, int(0.95 * n))`) |
| `per_link` | dict | — | per-link breakdown keyed by `link_id` |
| `channel_utilization` | dict | `[0, 1]` | per-channel busy fraction keyed by `channel_id` |

`per_link[link_id]`:

| Key | Unit | Meaning |
|---|---|---|
| `success` | count | successful deliveries on this link |
| `success_bytes` | bytes | total payload bytes delivered |
| `collision` | count | TX attempts lost to collision |
| `fail_phy` | count | TX attempts lost to PHY failure (SINR / PER) |
| `fail_no_ack` | count | TX attempts with no ACK |
| `retry` | count | retries scheduled (any failure cause) |
| `drop` | count | drops after `retry_limit` |
| `tx_attempts` | count | total TX attempts |
| `throughput_bps` | bits / sec | per-link goodput |

> **Throughput is goodput**, not airtime. A packet that collides,
> fails PHY, or never gets ACK contributes **zero** to throughput,
> even though it consumed airtime. This is the load-bearing metric
> definition for research; do not substitute PHY-rate × active-time.

`channel_utilization[channel_id]` is the fraction of sim time the
channel was busy with active TX (excluding CCA detection outside TX).

---

## 8. Reproducible experiment pattern

Recommended template for a research sweep:

```python
import json
from wifi_simulator.core.simulator import ApStation, Simulator

def run_once(seed: int, duration_s: float = 5.0) -> dict:
    sim = Simulator(
        seed=seed,
        duration_s=duration_s,
        aps=[
            ApStation(0, 10, (0,0), (10,0), 0, 0, 18.0, 100_000.0, 2304),
            ApStation(1, 11, (50,0),(60,0), 1, 0, 18.0, 100_000.0, 2304),
        ],
    )
    return sim.run()

# --- sweep -----------------------------------------------------------------
seeds = [2024, 2025, 2026, 2027, 2028]
results = [run_once(s) for s in seeds]

# Save raw per-seed results
for s, r in zip(seeds, results):
    with open(f"raw_seed_{s}.json", "w") as f:
        json.dump(r, f, indent=2, default=float)

# Aggregate (your choice of summary statistic)
import statistics
tps = [r["total_throughput_bps"] / 1e6 for r in results]
print(f"throughput mean={statistics.mean(tps):.2f} Mbps "
      f"std={statistics.stdev(tps):.2f} Mbps (n={len(seeds)} seeds)")
```

Rules of thumb:

- **Always** fix `seed`. Same scenario + seed + config = bit-identical
  output, including utilization.
- **Always** save raw per-seed results before aggregating. Don't
  overwrite.
- Use **≥ 5 seeds** for any throughput / latency number you cite.
- For paper-grade runs, save the full `result` dict (not just the
  headline metric) so future analysis can recompute.

---

## 9. MLO v0 (Feature Pack)

MLO v0 is the **complete and final** v0 contract shipped alongside
Frozen Core. Anything not listed below is not in v0.

Supported:

- **two-link MLD** — one `MldConfig` covers exactly two `link_ids`
- **independent per-link CSMA/CA** — each link runs its own MAC state
  machine on its own channel
- **fixed / round-robin steering** — per-packet dispatch policy
- **STR mode** — links transmit simultaneously; no peer-busy override

```python
from wifi_simulator.core.simulator import ApStation, Simulator
from wifi_simulator.features.mlo import MldConfig

sim = Simulator(
    seed=2024, duration_s=5.0,
    aps=[
        ApStation(0, 10, (0,0), (10,0), 0, 0, 18.0, 100_000.0, 2304),
        ApStation(0, 11, (0,0), (10,0), 1, 1, 18.0, 100_000.0, 2304),
    ],
    mld_configs=[
        MldConfig(
            mld_id=0,
            ap_id=0,
            link_ids=[0, 1],
            mode="STR",                # formal v0
            steering="round_robin",    # or "fixed"
            fixed_link_id=None,        # required only when steering == "fixed"
        ),
    ],
)
result = sim.run()
```

**Mode semantics**:

- `"STR"` — wake the destination MAC on every arrival; links are
  fully independent on their own channels.
- `"single_radio"` — wake the destination MAC only if no peer link
  is active. **Experimental**. Starves one link under saturation.
  **Not** a faithful model of IEEE 802.11be NSTR.

> `single_radio` ≠ IEEE NSTR. Real IEEE 802.11be NSTR semantics
> (link-pair sharing, NAV across links, restricted TWT) are not
> implemented. Do not cite `single_radio` runs as NSTR in research
> output. See `MLO_V0_REPORT.md` for the formal contract.

When MLD-owned links are configured, the simulator **automatically**
zeros each `ApStation.lambda_pps` and replaces per-link
`PoissonTraffic` with one `MldTraffic` per MLD. You should still pass
a non-zero `lambda_pps` on the **first** link of the MLD's `ApStation`
list — that is the MLD-level arrival rate.

---

## 10. Validation (what to run before claiming results)

After **any** Core change — which should not happen unless fixing a
correctness bug (§11) — or after merging a Feature Pack, run:

```bash
python -m wifi_simulator.tests.test_primitives         # 11 primitive sanity tests
python -m wifi_simulator.tests.test_freeze_resume      # 5 CSMA / CCA tests
python -m wifi_simulator.tests.test_sprint1            # integration: A + B end-to-end
python -m wifi_simulator.experiments.mlo_v0_validation # MLO v0 + conservation
```

All four must pass. For end-to-end smoke:

```bash
python -m wifi_simulator.scenarios.scenario_a
python -m wifi_simulator.scenarios.scenario_b
python -m wifi_simulator.scenarios.scenario_c
python -m wifi_simulator.scenarios.m1_two_link_str
```

The MLO v0 validation also checks **closed-form packet conservation**
(`arrivals == success + drop + queued`, `gap = 0`) for A, B, C, and M1.

> **Frozen Core modifications or new Feature Pack merges are blocked
> until regression passes.** Do not relax this for convenience.

---

## 11. How to extend

### 11.1 Modifying Core

**Don't.** The Core is frozen at v1.0. Modifications are accepted only
when fixing a correctness bug that distorts research results. New
mechanisms for hypothetical future work do **not** justify Core edits.

If you believe a Core change is unavoidable:

1. Write a failing test that demonstrates the bug.
2. Show that **no** Feature Pack path can solve it.
3. Get explicit approval.
4. Run §10 regression. All must pass without numeric regression on the
   v1.0 baseline numbers in `V1_RELEASE_REPORT.md` §5.

### 11.2 Adding a new research mechanism

Use a **Feature Pack** — a self-contained module under
`wifi_simulator/features/` that adds new behaviour via composition,
without modifying Core files. Pattern:

```
explicit paper requirement
    ↓
minimum sufficient implementation
    ↓
regression validation against §10
```

Examples that would land as Feature Packs (none of these exist yet):

- **OFDMA / MU-MIMO** — multi-RU scheduling
- **SR / OBSS_PD** — BSS Coloring + per-BSS CCA offset
- **EDCA** — per-AC backoff parameters
- **IEEE NSTR** — link-pair NAV, restricted TWT

Each Feature Pack ships its own validation script under
`wifi_simulator/experiments/` and its own report (e.g. `MLO_V0_REPORT.md`).

Do **not** build speculative abstractions ("a future-OFDMA-friendly MAC
interface") before a paper requires it.

---

## 12. Known limitations

Each is a by-design simplification accepted for v1.0; none are bugs.
Each names the paper topic that would justify revisiting it.

| # | Item | Impact | Revisit when |
|--:|---|---|---|
| 1 | ACK is instantaneous (no scheduled ACK TX) | slightly optimistic on per-packet airtime | Block-ACK paper |
| 2 | One STA per AP | no intra-BSS STA contention | Multi-STA scheduling paper |
| 3 | PER is binary (0 or 1) | no soft-PER near MCS threshold | Rate-adaptation paper |
| 4 | Shadowing static per run | no time-varying channel | Mobility / fast-fading paper |
| 5 | Poisson arrivals only | no bursty / on-off / trace traffic | Traffic-model paper |
| 6 | No capture effect | stronger simultaneous TX never wins | Capture paper |
| 7 | `single_radio` demo mode starves one link under saturation | abstract single-radio gate, **not** IEEE NSTR | IEEE NSTR paper |
| 8 | No spatial correlation of shadowing | per-link shadowing only, not spatial field | Spatial-reuse paper |
| 9 | No mobility | static positions | Mobility paper |
| 10 | No rate adaptation | Ideal MCS only | Rate-adaptation paper |

Also explicitly **not** included in v1.0 (deferred to Feature Packs
with no committed timeline): 320 MHz / puncturing, Block ACK / A-MPDU /
A-MSDU, EMLSR, 802.11bn, TCP / IP stack, beacon / scan / management
plane, RL agent, ns-3 integration, visualization / CLI framework.

> **What you can study with v1.0 as-is**: channel selection (centralised
> or per-AP), Tx power control, CCA tuning, multi-BSS interference
> coupling, MLO STR (two-link MLD), Bianchi-style fairness, retry /
> drop dynamics under saturation, conservative evaluation of MARL
> algorithms against scripted baselines.
>
> **What you cannot study yet without a Feature Pack**: OFDMA, MU-MIMO,
> spatial reuse, NSTR, EDCA, mobility, capture, multi-STA per AP,
> rate adaptation, realistic non-Poisson traffic.