# WiFiEnv — Research-Grade Wi-Fi Environment

A research-grade Wi-Fi simulator intended for fast Python iteration on
DRL/MARL algorithms with realistic CSMA/CA + packet-level PHY.

It is **not** an ns-3 clone and not a full IEEE 802.11 stack. Its goal
is to fix the abstractions in the legacy Project_3 environment that
most distort algorithm conclusions, while keeping the implementation
small enough to read end-to-end.

## Design philosophy

> Research fidelity > protocol completeness.
> Experiment velocity > software architecture completeness.
> Minimum sufficient fidelity > engineering realism.
> Paper-driven feature development > roadmap-driven feature development.

The simulator was developed across three stages:

1. **Sprint 1** — minimum Core: event loop, CSMA/CA, packet-level PHY,
   1 AP/STA, 2-AP contention. See `SPRINT1_REPORT.md`.
2. **Sprint 2** — multi-BSS, multi-channel, per-link Controller, Legacy
   Adapter. See `SPRINT2_REPORT.md`.
3. **Sprint 2.5** — Experiment Comparability Gate. Legacy-vs-Research
   comparison made metric-comparable; mechanism ablation identifies
   dominant divergence. See `SPRINT2_REPORT.md` §"Experiment Comparability
   Gate".

## Repository layout

```
WiFiEnv/
├── Design/                    design documents (audit, design, backlog, validation)
├── SPRINT1_REPORT.md          Sprint 1 implementation + Phase 0 hotfix
├── SPRINT2_REPORT.md          Sprint 2 + 2.5 implementation, experiment, gate
└── wifi_simulator/
    ├── core/                  event loop, RNG, channel state, simulator
    │   ├── event_loop.py      discrete-event engine (ns resolution)
    │   ├── rng.py             single seeded numpy Generator
    │   ├── channel_state.py   per-channel active-TX accounting
    │   ├── channel_registry.py  multi-BSS channel registry
    │   └── simulator.py       top-level driver
    ├── mac/                   CSMA/CA + per-link state machine
    │   ├── timing.py          IEEE 802.11-2016 §10.3.3 constants
    │   ├── backoff.py         CW_r = min((CW_min+1)*2^r - 1, CW_max)
    │   └── mac.py             DIFS / backoff / freeze+resume / TX / ACK / retry
    ├── phy/                   packet-level PHY abstraction
    │   ├── path_loss.py       freq_loss + alpha*log10(d) + cached per-link shadowing
    │   ├── sinr.py            LINEAR-DOMAIN interference sum (no dBm arithmetic)
    │   ├── mcs.py             HE-SU 20 MHz MCS 0..11 + Ideal MCS Selection
    │   └── airtime.py         Approximate Packet Airtime = preamble + payload_us
    ├── network/
    │   ├── queue.py           per-(AP, link) FIFO with packet identities
    │   └── traffic.py         Poisson arrivals
    ├── metrics/
    │   ├── collector.py       throughput, latency, collision, retry, drop
    │   └── events.py          event trace (CCA, BACKOFF, TX, COLLISION, ACK, …)
    ├── controllers/
    │   ├── controller.py      per-link / per-channel API
    │   └── legacy_adapter.py  L1/L2/L3 → Controller mapping
    ├── scenarios/             scenario_a (1 AP), scenario_b (2 AP), normal_4ap
    ├── experiments/           legacy_vs_research_normal vertical slice
    └── tests/                 sanity + CSMA/CCA + Sprint 1 gate
```

## Quick start

```bash
cd WiFiEnv
python -m wifi_simulator.tests.test_sprint1        # 16 sanity + CSMA tests
python -m wifi_simulator.scenarios.scenario_a        # single-AP saturated
python -m wifi_simulator.scenarios.scenario_b        # 2-AP contention
python -m wifi_simulator.scenarios.normal_4ap       # legacy Normal scenario mirror
```

## Running the Legacy-vs-Research experiment

The experiment in `wifi_simulator/experiments/legacy_vs_research_normal.py`
compares the legacy Project_3 env with the new env on the same scenario.
It needs the legacy Project_3 code at a known path:

```bash
export LEGACY_PROJECT3_ROOT=/path/to/legacy/Project_3   # contains env.py
python -m wifi_simulator.experiments.legacy_vs_research_normal
```

If `LEGACY_PROJECT3_ROOT` is not set, the default is
`/Users/yiwei/Desktop/Project_3`. The legacy code is **not** part of
this repository; it lives separately in the user's legacy Project_3
checkout.

The experiment runs three conditions × 5 seeds:
- **E0** — legacy Project_3 (always-on interferers, Shannon capacity)
- **E1** — research core (CSMA/CA + packet airtime + Ideal MCS)
- **E2** — research + always-on interferers (mechanism ablation)

See `SPRINT2_REPORT.md` §"Experiment Comparability Gate" for the full
result and the metric-definition caveat.

## Design documents

| Document | What |
|---|---|
| `Design/RESEARCH_ENV_AUDIT.md` | Audit of legacy Project_3 abstractions that distort algorithm conclusions |
| `Design/RESEARCH_ENV_DESIGN.md` | Sprint 1+2 design: time scales, two-phase slot processing, Controller API, MLO as Feature Pack |
| `Design/MVP_AND_FEATURE_BACKLOG.md` | Core 10 + Research Infrastructure 9 + Feature Packs |
| `Design/VALIDATION_PLAN.md` | Correctness validation (A) + Scientific Robustness (B) + Optional PHY Enhancement (D) |

## What is NOT in this repository

The legacy Project_3 environment code (`env.py`, `baseEnv.py`,
`Exp_*.py`, `agent/`, `Models/`, `Results/`, `Figures/`, etc.) is
intentionally **not** included. The new env supersedes it for new
research; the legacy code remains in the user's separate `Project_3/`
checkout for side-by-side experiments.

## Status

* **Sprint 1 Core**: 16/16 sanity + CSMA tests pass.
* **Sprint 2 multi-BSS + Controller + Legacy Adapter**: working.
* **Sprint 2.5 Comparability Gate**: passed (5 seeds, 3 conditions,
  AP0 headline, mechanism ablation identifies duty cycle as dominant
  factor, metric-definition mismatch documented).
* **Sprint 3 / MLO / OFDMA / SR / OBSS_PD / capture effect / EDCA /
  Block ACK / aggregation / 320 MHz / puncturing / mobility / TCP /
  ns-3**: not implemented, on-demand per paper.
