# WiFiEnv — Research Wi-Fi Environment

A research-grade Wi-Fi **discrete-event simulation environment** for fast
Python iteration on **channel selection, Tx power control, CCA tuning,
multi-BSS, and MLO (STR)** algorithms. Written for researchers who need
realistic CSMA/CA + packet-level PHY without ns-3.

> **Not** an ns-3 clone. **Not** a full IEEE 802.11 stack.
> **Core is frozen at v1.0** — see `V1_RELEASE_REPORT.md` for the
> canonical baseline numbers and the freeze checklist.

---

## Current capability (v1.0)

What's in the box **today**:

- Discrete-event timing (ns / 9 µs slot)
- CSMA/CA: DIFS / backoff / freeze+resume / TX / ACK / retry
- Collision, ACK failure, retry, drop-after-`retry_limit`
- Packet-level PHY with cached per-link shadowing (linear-domain SINR)
- Ideal MCS Selection + simplified PER + approximate packet airtime
- Per-(AP, link) FIFO queue with packet identities
- Realistic interferer traffic (interferers also run CSMA/CA, never always-on)
- Multi-BSS, multi-channel (≥ 4 APs across ≥ 3 channels)
- Per-link Controller (channel / Tx power / CCA at `link_id` granularity)
- `ScriptedRunner` for fixed-parameter per-epoch driving (no RL required)
- Metrics: throughput, latency mean/p50/p95, queue, collision, retry,
  drop, **per-channel utilization**, per-link breakdown
- Deterministic reproducibility (same scenario + seed + config → bit-identical)
- **MLO v0 Feature Pack**: two-link MLD, independent per-link CSMA/CA,
  fixed / round-robin steering, STR mode

What's **explicitly out of scope** (deferred to paper-driven Feature Packs):

| Deferred | Reason |
|---|---|
| IEEE 802.11be NSTR / EMLSR | Future MLO paper |
| OFDMA / MU-MIMO / 320 MHz / puncturing | OFDMA paper |
| BSS Coloring / OBSS_PD / Spatial Reuse (SR) | SR paper |
| EDCA / QoS AC / Block ACK / A-MPDU / A-MSDU | QoS paper |
| Capture effect / spatial-correlated shadowing | Capture paper |
| Mobility / TCP / IP stack | Mobility paper |
| 802.11bn (UHR) / rate adaptation / management plane | Not requested |
| RL agent / Gymnasium wrapper / ns-3 integration | Out of env scope |

The Core is **not** modified for hypothetical future needs; new mechanisms
arrive only as Feature Packs triggered by an explicit paper requirement.

---

## Quick start

```bash
# Core scenarios (Core v1.0)
python -m wifi_simulator.scenarios.scenario_a          # 1 AP, 1 STA, saturated
python -m wifi_simulator.scenarios.scenario_b          # 2 APs, same channel, saturated
python -m wifi_simulator.scenarios.scenario_c          # 4 APs, 3 channels, multi-BSS

# MLO v0 Feature Pack
python -m wifi_simulator.scenarios.m1_two_link_str     # 1 MLD, 2 links, STR (formal v0)

# Regression tests
python -m wifi_simulator.tests.test_primitives         # 11 primitive sanity tests
python -m wifi_simulator.tests.test_freeze_resume      # 5 CSMA / CCA tests
python -m wifi_simulator.tests.test_sprint1            # integration: A + B end-to-end
python -m wifi_simulator.experiments.mlo_v0_validation # MLO v0 + packet conservation
```

All commands run without RL and print a JSON summary.

---

## Minimal Python example

```python
from wifi_simulator.core.simulator import ApStation, Simulator

sim = Simulator(
    seed=2024,                       # deterministic
    duration_s=5.0,                  # simulation duration (seconds)
    aps=[
        ApStation(
            ap_id=0, sta_id=10,
            pos_ap=(0.0, 0.0),        # AP position (x, y) in meters
            pos_sta=(10.0, 0.0),      # STA position (x, y) in meters
            link_id=0, channel_id=0,  # one link on channel 0
            tx_power_dbm=18.0,        # transmit power
            lambda_pps=100000.0,      # Poisson arrival rate (packets/sec)
            size_bytes=2304,          # payload size per packet
        ),
    ],
)
result = sim.run()

print(f"throughput  = {result['total_throughput_bps']/1e6:.2f} Mbps")
print(f"success     = {result['total_success_packets']}")
print(f"drops       = {result['total_drop_packets']}")
print(f"latency p95 = {result['latency_p95_us']:.1f} µs")
print(f"utilization = {result['channel_utilization']}")
print(f"per_link    = {result['per_link']}")
```

`result` is a `dict` with the keys below.

---

## Metrics (return fields)

Top-level (`Simulator.run()` returns):

| Field | Unit | Meaning |
|---|---|---|
| `total_throughput_bps` | bits / s | Sum of successful payload bits / sim duration. **Goodput**, not airtime. |
| `total_success_packets` | count | Packets delivered successfully |
| `total_drop_packets` | count | Packets dropped after `retry_limit` |
| `latency_mean_us` | µs | Mean enqueue→success latency |
| `latency_p50_us` | µs | Median latency |
| `latency_p95_us` | µs | 95th-percentile latency |
| `per_link` | dict | Per-link breakdown keyed by `link_id` |
| `channel_utilization` | dict | Per-channel busy fraction keyed by `channel_id`, in `[0, 1]` |

Per-link (`result["per_link"][link_id]`):

`success`, `success_bytes`, `collision`, `fail_phy`, `fail_no_ack`,
`retry`, `drop`, `tx_attempts`, `throughput_bps`.

---

## Reproducibility

> Same scenario + same seed + same config → **bit-identical** output,
> including per-channel utilization and per-link latency percentiles.

Seed is the only randomness source (single `numpy.random.Generator` per
`Simulator`). All stochastic draws — backoff counters, shadowing,
Poisson inter-arrivals — flow through that one generator.

The V1 baseline numbers are reproducible with:

| Scenario | Seed | Throughput |
|---|---:|---:|
| A | 2024 | 64.83 Mbps |
| B | 2024 | 70.94 Mbps |
| C | 6 | 207.84 Mbps |
| M1 STR | 2024 | 129.75 Mbps |

See `V1_RELEASE_REPORT.md` §5 for the full table.

---

## Documentation

| File | What |
|---|---|
| `docs/USAGE_GUIDE.md` | **Start here.** Library mental model, how to run each scenario, how to build a new experiment, scripted control, traffic / PHY / MAC parameters, metrics, reproducible experiment template, MLO v0, validation commands, extension rules, known limitations. |
| `V1_RELEASE_REPORT.md` | Canonical baseline numbers (seed, 5 s), freeze checklist, v1.0 capability boundary, known simplifications table, wall-clock numbers. |

Other files in the repo (sprint reports, design docs, MVP report) are
historical and **not needed** by new users.