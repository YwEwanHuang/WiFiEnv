# MVP_AND_FEATURE_BACKLOG.md

**Stage**: Design (Design Convergence pass, ready for Sprint 1).
**Method**: every mechanism is graded against the prompt's "Research-first"
checklist (§1 of the master prompt):

> A mechanism belongs in MVP iff at least one of:
> 1. it changes the algorithm's *observation*,
> 2. it changes the algorithm's *action space*,
> 3. it materially changes *throughput / latency / collision / queue*,
> 4. it changes the *relative ranking* of algorithms,
> 5. it is the *paper topic itself*.

Otherwise it is on-demand.

After the Design Convergence pass, MVP is split into two layers:

- **Core Research Fidelity MVP** — only mechanisms whose deletion directly
  flips wireless algorithm conclusions. These run **independently** of
  research infrastructure.
- **Research Infrastructure** — engineering scaffolding (RNG, config, traces,
  adapter, scenarios) without which the core cannot be used by a researcher.
  These do **not** count as wireless fidelity.

MLO is **removed from Core** and becomes an optional **Feature Pack**.

---

## 1. Core Research Fidelity MVP

The bar to enter this list:

> If we delete the mechanism, does any *current* Project_3 paper
> (channel selection / power allocation / CCA tuning / MARL) risk getting
> the **wrong relative conclusion**?

If yes → Core. If no → Research Infrastructure or on-demand.

| # | Mechanism | Why it survives the bar |
|--:|-----------|------------------------|
| C1 | **Discrete-event timing** (ns resolution, slot-accurate `SLOT_TIME`, `SIFS`, `DIFS`, `EIFS`) | Without slot timing there is no real CSMA/CA; throughput/collision/latency collapse into the legacy "super-slot". Flips every contention-aware conclusion. |
| C2 | **CSMA/CA per (AP, link)**: DIFS / AIFS / busy-sensing / freeze+resume backoff / TX / ACK / retry | The single biggest legacy distortion. Backoff pressure and DIFS cost change which algorithm wins channel selection and CCA tuning. |
| C3 | **Collision / ACK / retry model**: TX overlap detected, retry up to `retry_limit`, drop after exhaustion; ACK timeout treated as collision | Without this, throughput is silently wrong; retry count and collision count are the primary metrics for RA / CCA tuning. |
| C4 | **Packet-level PHY**: path loss + **cached per-link (link-persistent) shadowing** + per-receiver interference + noise + SINR (linear-domain summation — see `RESEARCH_ENV_DESIGN.md` §5.2) | Per-call shadowing is a documented legacy bug that destroys link correlation. Drawing shadowing once per (tx, rx) pair and reusing it is the cheapest way to make SINR stable across packets. (Note: this is *not* spatial correlation; spatial Gaussian random field is on-demand per paper, see §D `SpatialShadowField`.) |
| C5 | **Ideal MCS Selection + simplified PER + Approximate Packet Airtime** | Replaces Shannon. Throughput formula becomes `bytes / airtime`. Latency becomes meaningful. Trade-off between rate and reliability is now real. |
| C6 | **Per-packet queue** with packet identities (enq / success times) | Latency is the headline metric for QoS / MLO / SR papers. Legacy env has only an integer counter. |
| C7 | **Realistic interferer traffic**: interferers run the *same* CSMA/CA, driven by their own queues, never always-on | Always-on interferers is the second biggest legacy distortion. Without this, OBSS / SR / channel-selection experiments do not transfer. |
| C8 | **Multi-BSS support**: ≥ 5 APs, overlapping channel reuse, hidden-node phenomena | Most Project_3 experiments act on multi-AP; single-AP is a degenerate case. |
| C9 | **Algorithm Controller** with **per-link** granularity for channel / Tx power / CCA threshold; **decision_interval** time scale decoupled from MAC/PHY slot | `set_tx_power(link_id, dbm)`, `set_cca(channel, dbm)`, `select_channel(ap, ch)` — not just `set_tx_power(ap, dbm)`. Controller is called once per `decision_interval`, not per slot. |
| C10 | **Minimum research metrics**: throughput (per-link / per-AP / total), latency (mean + p95), collision / drop count, retry count, queue length | Every paper needs these. *p99 latency* and *per-MCS histograms* are research infrastructure (B3 below) and not Core. |

**Total Core item count: 10.** This is the *Minimum Sufficient Fidelity*
target. The Core can run channel-selection / power-allocation / CCA / MARL
experiments on its own. It must run independently of MLO.

### 1.1 What is NOT in Core (and why)

- **MLO** — important research topic, but Core does not need MLO to support
  channel selection / power allocation / CCA / MARL. MLO is a **Feature Pack**
  (see §3 below) layered on top of Core. Core contains no MLO behaviour; only minimal extension hooks (per-link MAC, per-link queue, per-link CCA) may exist.
- **OFDMA, MU-MIMO, SR, OBSS_PD, EDCA, Block ACK, A-MPDU/A-MSDU, 320 MHz,
  puncturing, mobility, TCP, EMLSR** — all on-demand. None of these change
  the relative ranking of *current* Project_3 algorithms.

---

## 2. Research Infrastructure (scaffolding, not fidelity)

These ship in v0 because without them the Core cannot be used as a research
simulator. They are **not** wireless fidelity — removing one of them does
not change algorithm rankings.

| # | Item | Why in v0 |
|--:|------|-----------|
| B1 | **Seeded RNG** (single `numpy.random.Generator` per simulation, deterministic) | Reproducibility. Without it, no paper can be defended. |
| B2 | **Deterministic event log**: every event carries `time_ns` and is recorded in order | Without this, debugging CSMA/CA is intractable. Not a fidelity issue — an engineering issue. |
| B3 | **Event trace file** (CCA / BACKOFF / TX_START / TX_END / COLLISION / ACK / RETRY / DROP) | Same reasoning as B2. |
| B4 | **Config loader**: Python dict or YAML, validated at startup | Without it, scenario reproduction breaks. |
| B5 | **Scenario definition files** (`scenarios/*.py`) — `single_ap_saturated`, `two_ap_same_channel`, `four_ap_grid`, `mld_two_link` | These are the *inputs* to a paper; not fidelity. |
| B6 | **Legacy Adapter** (`wifi_simulator/controllers/legacy_adapter.py`) | Required for Chapter 12 side-by-side experiments. Maps L1/L2/L3 hierarchical actions to the per-link Controller API. |
| B7 | **Validation scripts** (sanity + analytical + Legacy-vs-Research + optional ns-3 spot check) | Correctness is checked at validation time, not in the runtime. |
| B8 | **IEEE timing constants with source citations** in `mac/timing.py` | Without citations, the simulator's constants cannot be defended in a paper. |
| B9 | **`p99` latency / per-MCS histogram / time-series queue length** | Useful, but not in the *minimum* metrics set; on-demand per paper. |

The architecture split between Core and Research Infrastructure is enforced
only at the **naming** and **ablation** level: Core items are not optional,
Research Infrastructure items can be replaced (e.g., B6 — Legacy Adapter —
can be deleted without affecting Core's correctness).

---

## 3. Feature Packs (Core + optional)

A feature pack is a self-contained module that adds one research capability
on top of Core. Core must remain runnable with **no feature pack loaded**.

### 3.1 MLO Feature Pack (`features/mlo.py`)

```
Core Wi-Fi Simulator
        +
optional research feature
```

For example:

```
Core
+ MLO              (link selection, traffic steering, STR / NSTR)

Core
+ Spatial Reuse    (SR parameter, relative CCA tables)

Core
+ OFDMA            (RU scheduler, MU TX)
```

MLO is the first Feature Pack to be designed but **not** the first to be
implemented.

**MLO Feature Pack scope (v0, on demand):**

- MLD with N = 1..4 links.
- Per-link channel, per-link MAC, per-link queue, per-link CCA.
- Basic link selection: `controller.select_link(mld, packet) -> link_id`.
- Basic traffic steering: round-robin or learned policy.
- **STR** (Simultaneous TX/RX) — links operate independently.
- **NSTR** (Non-STR) — one TX blocks all other RX.
- Default steering policy = round-robin over idle links.

**MLO Feature Pack scope (NOT in v0, deferred):**

- EMLSR / restricted TWT.
- Advanced MLO synchronization and link-switching latency.
- Full 802.11be MLO feature set.

If the existing Core architecture already exposes per-link MAC + per-link
queue + per-link CCA (it does — C9 above), then MLO slots in as a thin
adapter layer in `features/mlo.py` without any Core change. No Core file is
modified to support MLO.

### 3.2 Other Feature Packs (deferred)

| Pack | Trigger paper |
|------|---------------|
| Spatial Reuse | SR parameter paper |
| OFDMA / MU-MIMO | OFDMA scheduler paper |
| OBSS_PD / BSS Coloring | OBSS_PD paper |
| 802.11bn / UHR | 802.11bn paper |
| EDCA / QoS | QoS paper |

---

## 4. On-demand feature backlog

These mechanisms are **explicitly deferred** until a paper needs them.

| # | Feature | Required interface in Core | Comment |
|--:|---------|---------------------------|---------|
| F1 | OFDMA / RU allocation | `Slot.scheduler: Optional[Scheduler]` field | Default = no-op. |
| F2 | multi-RU | RU aggregation API (read-only) | Built on F1. |
| F3 | MU-MIMO | `Slot.users: list[User]` | Built on F1. |
| F4 | 320 MHz channels | `ChannelMask` data type | Placeholder in Core. |
| F5 | Channel puncturing | `ChannelMask` | Same placeholder. |
| F6 | BSS Coloring | `Device.bs_color: int` field | One-line config. |
| F7 | OBSS_PD | CCA adjustment based on `bs_color` | Built on F6. |
| F8 | Spatial Reuse | `Controller.set_sr_param` | CCA threshold boost. |
| F9 | EMLSR / link switching latency | `Link.switching_us` field | Per-link config. |
| F10 | 802.11bn / UHR features | `PhyMode` enum extension | MCS rows + preamble updates. |
| F11 | EDCA / QoS AC | `AIFS[AC]` table, per-AC queue | `mac/timing.py` already enumerates AIFS; needs per-AC MAC. |
| F12 | Block ACK, A-MPDU/A-MSDU | TX aggregator object | Sits in MAC TX_START path. |
| F13 | Mobility | `Device.pos(time_ns)` callable | Topology hooks. |
| F14 | Rate adaptation (MiniRate / full RA) | `RateController` between MAC and PHY | Default = Ideal MCS. |
| F15 | SR / 11bn relative CCA tables | adds rows to CCA table | One-file edit. |
| F16 | TCP/IP stack integration | Not in scope | Use external ns-3 if needed. |
| F17 | Association / authentication / WPA | Not in scope |  |
| F18 | Beacon / scan / management plane | Not in scope |  |

Adding a feature typically edits one or two files and never touches
`core/`, `mac/`, `phy/`.

---

## 5. Ablation check (§16 of the prompt)

For each Core item: *"if we delete it, does it materially affect a current
paper's conclusion?"*

| Core # | Deleted? | Consequence | Verdict |
|-------:|----------|-------------|:-------:|
| C1 (discrete-event timing) | yes | Reverts to legacy 4.5 ms super-slot → every contention-aware conclusion flips. | **keep** |
| C2 (CSMA/CA) | yes | Same as C1; the single biggest fix. | **keep** |
| C3 (collision / ACK / retry) | yes | Throughput silently drops or inflates; retry / collision metrics vanish. | **keep** |
| C4 (packet-level PHY) | yes | Per-call shadowing → uncorrelated noise; any MCS / RA / fast-fading paper loses its signal. | **keep** |
| C5 (Ideal MCS + airtime) | yes | Reverts to Shannon. Latency / reliability trade-off vanishes. | **keep** |
| C6 (per-packet queue) | yes | Latency metric gone. | **keep** |
| C7 (real interferer duty cycle) | yes | Always-on interferers → OBSS / SR / channel-selection conclusions do not transfer. | **keep** |
| C8 (multi-BSS) | yes | Limits studies to 1 AP. | **keep** |
| C9 (per-link Controller + decision_interval) | yes | L2 power distribution has no meaning; CCA threshold has no per-channel resolution. | **keep** |
| C10 (minimum metrics) | yes | Cannot publish throughput / latency numbers. | **keep** |

**Net result**: every Core item survives ablation.

Research Infrastructure items (B1–B9) all survive a separate engineering
ablation: removing B6 (Legacy Adapter) only kills side-by-side Legacy-vs-
Research experiments, not Core; removing B7 (validation scripts) only kills
publication readiness, not Core; etc.

---

## 6. Implementation Sprint mapping

| Sprint | Scope |
|--------|-------|
| **Sprint 1** | Core MVP subset: C1 (event loop) + C3 (collision / ACK / retry) + C6 (queue) + C5 (basic airtime) + C4 (basic path loss / SINR) + C2 (CSMA/CA: DIFS / backoff / freeze / TX / ACK / retry) + C10 (throughput + latency + collision / retry metrics) + research infrastructure B1 (seeded RNG), B2 (deterministic event log), B3 (event trace), B4 (config loader) minimum. **Single AP / STA pair, one channel**. No controller yet. See Sprint 1 report for validation. |
| **Sprint 2** | Multi-BSS + realistic interferers (C7, C8) + Controller with per-link granularity (C9) + decision_interval. Legacy Adapter (B6). First Legacy-vs-Research experiment. |
| **Sprint 3+** | MLO Feature Pack (per §3.1). Other Feature Packs on demand. |

---

## 7. STOP

This document is the **Minimum Sufficient Fidelity** contract for Sprint 1
(Core items only — no MLO, no per-link Controller granularity yet, no
decision_interval). Sprint 1 builds the smallest Core that can run
single-AP and two-AP contention. Sprint 2 widens it.