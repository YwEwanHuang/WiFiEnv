# RESEARCH_ENV_DESIGN.md

**Stage**: Design (Design Convergence pass, ready for Sprint 1).
**Audience**: a research-grade Wi-Fi simulator for Project_3, intended for fast
Python iteration on DRL/MARL algorithms with realistic CSMA/CA + packet-level PHY.
It is **not** an ns-3 clone and not a full IEEE 802.11 stack.

---

## 1. Goals and non-goals

### Goals

- Discrete-event simulation with slot-accurate Wi-Fi timing
  (`SLOT_TIME` / `SIFS` / `DIFS` / `EIFS` / backoff / ACK / retry).
- Packet-level PHY: path loss + correlated shadowing + interference + noise +
  SINR (linear-domain summation) + Ideal MCS Selection + simplified PER +
  Approximate Packet Airtime.
- Multi-BSS, overlapping channel reuse, hidden-node phenomena.
- **Two distinct time scales**:
  - MAC/PHY simulation time: `SLOT_TIME = 9 us`, event time = ns.
  - Algorithm decision epoch: `decision_interval` (configurable, default 4.5 ms
    for Legacy compatibility). RL algorithms do **not** run per-slot.
- Per-link granularity on Controller actions: channel, Tx power, CCA threshold,
  each controllable at `(link_id)` or `(ap, channel)` resolution.
- Optional MLO via a separate Feature Pack — Core remains unaware of MLO.
- Thin Legacy Adapter that maps the existing 3-layer hierarchical DQN/DDPG
  agent to the new Controller API.

### Non-goals (default)

- Full IEEE 802.11be/11bn feature set; OFDMA, multi-RU, MU-MIMO, 320 MHz,
  puncturing, BSS Coloring, OBSS_PD, Spatial Reuse, EMLSR — all on-demand
  only.
- Waveform-level PHY, full rate adaptation, A-MPDU/A-MSDU, Block ACK.
- WPA/WPA3, association / authentication, mobility, beacons, full management plane.
- TCP/IP, EDCA (initial version), regulatory domain.

These are added **per paper**, not up front.

---

## 2. High-level architecture

```
wifi_simulator/
    core/                  discrete-event engine + topology + config
        event_loop.py
        topology.py
        config.py
        rng.py
    mac/                   CSMA/CA + per-link MAC state machines
        mac.py              per (AP, link) state: idle / cca / backoff / tx / ack / retry
        backoff.py
        timing.py           IEEE timing constants, sourced and versioned
        interference.py     per-channel busy/idle accounting
    phy/                   packet-level PHY abstraction
        channel.py          path loss + correlated shadowing
        sinr.py             per-receiver interference + noise (linear-domain sum)
        mcs.py              MCS table + Ideal MCS Selection
        per.py              PER from SINR; success / fail decision
        airtime.py          Approximate Packet Airtime
    network/
        queue.py            per-AP / per-link queue with packet identities
        traffic.py          Poisson / CBR / on-off / trace-driven
    features/              Feature Packs — Core remains unaware of any feature
        mlo.py              MLD model: links, steering, STR / NSTR  (FEATURE PACK)
    controllers/           algorithm-agnostic Controller API
        controller.py       the only thing the algorithm sees
        legacy_adapter.py   wraps Controller for L1/L2/L3 hierarchical agent
    metrics/
        collector.py        throughput / latency / collision / retry / loss / utilization
        events.py           event trace (CCA, BACKOFF, TX, COLLISION, ACK, RETRY)
    scenarios/
        scenario.py         declarative scenario files
    tests/                  sanity / analytical / legacy-compare
```

The architecture is deliberately flat: no plugin framework, no factory, no
registry. Each module is a small class or function file. Adding a feature means
dropping a new file into `features/` (or extending an existing one) — no Core
change required.

### 2.1 Core vs Feature Pack

```
Core Wi-Fi Simulator (C1..C10)
        +
optional Feature Pack (MLO, SR, OFDMA, …)
```

The Core must run channel-selection / power-allocation / CCA / MARL
experiments without any feature pack. Feature Packs are isolated modules
under `features/`. MLO is a Feature Pack; Core contains no MLO awareness.

---

## 3. Discrete-event engine

### 3.1 Event types

```
class EventKind(enum.Enum):
    SLOT_BOUNDARY
    CCA_CHECK
    BACKOFF_TICK
    TX_START
    TX_END
    ACK_TIMEOUT
    ACK_RX
    PACKET_ARRIVAL
    QUEUE_UPDATE
    STATS_SAMPLE
    DECISION_EPOCH_END    # controller step boundary
```

### 3.2 Event loop

```python
pq = PriorityQueue()          # (time_ns, seq, event)
while pq and clock < t_end:
    t, _, ev = pq.pop()
    clock = t
    ev.handler()
```

All events carry a `time_ns`. The simulator never advances time by hand; it only
runs the next event.

### 3.3 Two time scales (MAC/PHY vs Algorithm decision)

**MAC/PHY time** runs at ns / 9 µs slot granularity:

- `SLOT_TIME = 9 us` (5 GHz OFDM, configurable).
- All CSMA/CA events (`CCA_CHECK`, `BACKOFF_TICK`, `TX_START`, `TX_END`,
  `ACK_TIMEOUT`) fire in this scale.

**Algorithm decision time** runs at `decision_interval` granularity (e.g.
4.5 ms default):

```
Controller.step(action)
    ↓
Simulator.run_for(decision_interval)        # real MAC/PHY events
    ↓
Metrics.aggregate()
    ↓
Observation = collector.snapshot()
    ↓
Controller.step(next action)
```

A `DECISION_EPOCH_END` event fires at every `decision_interval` boundary;
the Controller is invoked once per epoch, not per slot. RL algorithms
**must not** be called per Wi-Fi slot. This is non-negotiable for research
velocity and for paper realism.

```python
# legacy 4.5 ms starting point, but configurable:
controller = Controller(decision_interval_ns=4_500_000)
```

`decision_interval` is exposed as a config knob so the same scenario can be
run with different epoch lengths without changing code.

### 3.4 RNG

A single `numpy.random.Generator` per simulation, seeded once. Every stochastic
call (backoff draw, shadowing, packet arrival) reads from it. Reproducibility is
mandatory for research.

---

## 4. Topology and devices

### 4.1 Topology

```python
@dataclass
class Device:
    id: int
    role: Literal["AP", "STA", "MLD"]
    pos: Tuple[float, float]
    tx_power_dbm: float
    cca_default_dbm: float

@dataclass
class Link:
    id: int
    ap_id: int
    sta_id: int
    channel_id: int
    channel_width_mhz: int

@dataclass
class Topology:
    devices: list[Device]
    links: list[Link]
    bs_color: dict[int, int] = field(default_factory=dict)
```

`MLD` is a specialisation of `Device` that owns multiple `Link`s (one per
radio). **MLD is owned by `features/mlo.py` only**; Core `topology.py` knows
nothing about MLO.

### 4.2 Channel

Channels are orthogonal in the default config (`channel_width_mhz = 20`,
`non_overlap = True`). Puncturing / partial overlap / 320 MHz are on-demand
features layered as a `ChannelMask` and only enabled when a scenario requests
them. Until then, a `Channel` is `(channel_id, center_freq_mhz, width_mhz)`.

---

## 5. PHY

### 5.1 Path loss + shadowing (correlated)

```
PL(d) = freq_loss + 10 * alpha * log10(d) + n_walls * wall_loss + shadowing_dB
```

- `alpha`, `freq_loss`, `wall_loss` are config constants.
- `shadowing_dB` is **drawn once per (tx, rx) pair at topology build**, then cached.
  This is the key fix for legacy abstraction #5 in `RESEARCH_ENV_AUDIT.md`.

A `SpatialShadowField` (decorator) can layer spatially correlated shadowing via a
Gaussian random field; this is *on-demand* for Spatial Reuse research, not Core.

### 5.2 SINR (linear-domain summation — no dBm arithmetic)

At each `TX_END` event for a packet from `tx` to `rx` on channel `c`,
compute SINR as follows. **All powers must be converted to linear (W) before
summation.** Direct addition in dBm is prohibited.

Definition:

```
SINR_dB = 10 * log10( P_signal_W / ( P_interf_W + P_noise_W ) )
```

— **denominator is interference + noise only**. The signal power is **not**
added to the denominator.

Step-by-step:

```
P_signal_W = 10^((P_signal_dBm - 30) / 10)

# Interferers are all other transmitters on channel c whose TX overlaps this packet.
# Each interferer's received power at rx is converted to linear and summed.
P_interf_W = sum_{tx' != tx, tx' on c, tx' active during packet} 10^((P_tx'_rx_dBm - 30) / 10)

# Noise:
P_noise_W = kT * BW_Hz * NF_linear
# (default nf_dB = 9  →  nf_linear = 10^(9/10))

# SINR:
SINR_dB = 10 * log10( P_signal_W / ( P_interf_W + P_noise_W ) )
```

Sanity reference (interference-only aggregation, no desired signal):

```
Two equal interferers at -60 dBm each:
    sum_W = 2 * 10^((-60 - 30) / 10) = 2e-9  W
    sum_dBm = 10 * log10(2e-9) + 30 ≈ -56.99 dBm
```

**The code MUST convert to linear first, sum, then convert back to dB only
for the final SINR. This rule applies to all interference aggregation in
the simulator, including CCA energy aggregation.** Waveform-level PHY is
explicitly out of scope.

### 5.3 Ideal MCS Selection

`mcs.py` ships a static table mapping `[min_sinr, max_sinr) → (mcs_index, data_rate_mbps)`
for each PHY mode (legacy, HT, VHT, HE, EHT). At TX_START, the MAC picks the
**highest MCS** whose `min_sinr ≤ SINR_estimate_dB`. This is the **Ideal MCS
Selection** allowed for the Core.

Rates are documented in code with `source: str` fields. In Sprint 1 only a
single PHY mode + a few MCS entries are required.

### 5.4 PER and Approximate Packet Airtime

- `per.py`: lookup PER from `(mcs, sinr)` table; default is step-function
  `PER = 0 if SINR > mcs_threshold + margin else 1`. A stochastic draw
  `U(0,1) < PER` decides packet outcome.
- `airtime.py`: **Approximate Packet Airtime** —

  ```
  airtime_us = preamble_us + (payload_bits / (mcs_rate_mbps * 1e6)) * 1e6
  ```

  This is **not** a precise IEEE 802.11 airtime calculation. The model
  ignores:

  - OFDM symbol rounding,
  - SERVICE field bits,
  - TAIL bits,
  - padding,
  - HE / EHT PPDU details.

  Symbol rounding can be added later if it does not significantly increase
  complexity, but is **not required** for Sprint 1. The principle is:

  > A simplified airtime model is acceptable; the documentation must state
  > exactly what it computes.

  In Sprint 1, `Approximate Packet Airtime = preamble_us + payload_us`, with
  preamble and per-MCS rate from the MCS table.

---

## 6. MAC (CSMA/CA, per link)

### 6.1 State machine

```
            ┌──────────┐  arrival (queue non-empty)
            │   IDLE   │ <──────────────────────────────┐
            └────┬─────┘                                │
                 │  channel idle for DIFS               │
                 ▼                                      │
            ┌──────────┐  channel busy                  │
            │  BACKOFF │ ─────────────────────────────► │
            └────┬─────┘  resume after busy              │
                 │  counter = 0                         │
                 ▼                                      │
            ┌──────────┐                                │
            │   TX     │ ──────── TX_END ──► success/fail│
            └────┬─────┘                                │
                 │ fail                                 │
                 ▼                                      │
            ┌──────────┐  retry ≤ retry_limit            │
            │  RETRY   │ ─────────────────────────────► │
            └──────────┘  drop (packet loss)             │
                 │                                      │
                 ▼                                      │
              DROPPED                                   │
                                                      (re-arm)
```

### 6.2 CSMA/CA logic

Per (AP, link) at every `SLOT_BOUNDARY`:

1. If queue empty → IDLE.
2. Else if channel is **idle** (energy below CCA threshold for the slot)
   for `DIFS` (or `AIFS[AC]`) consecutive slots → BACKOFF.
3. Else → stay IDLE, freeze backoff counter.
4. In BACKOFF: draw `BO ∈ [0, CW]` where
   `CW_r = min((CW_min + 1) * 2^r − 1, CW_max)`,
   with `r` = retry counter. **See §6.4 for the exact formula.**
5. Counter reaches 0 → TX_START.
6. TX_START schedules TX_END at `now + airtime_us`.
7. TX_END triggers PER check; on success schedule ACK RX; on fail schedule retry.
8. ACK RX: success → next packet; ACK timeout → collision / failure → retry.

### 6.3 DIFS / AIFS / SIFS / EIFS / slot time

Default constants in `mac/timing.py` (5 GHz OFDM, 20 MHz):

| Symbol | Value (ns) | Source |
|--------|-----------:|--------|
| `SLOT_TIME`      |    9_000 | IEEE 802.11-2016 §10.3.3 |
| `SIFS`           |   16_000 | IEEE 802.11-2016 §10.3.3 |
| `DIFS`           |   34_000 | `SIFS + 2*SLOT` |
| `EIFS`           |   88_000 | `SIFS + DIFS + ACK_airtime @ 6 Mbps` |
| `AIFS[AC_BE]`    |   34_000 | = DIFS for legacy compatibility |
| `PHY_RX_START_DELAY` | 25_000 | §10.3.5.7 |

A `Notes:` block in the same file records the source and any assumption.

### 6.4 Backoff (corrected CW formula)

The standard IEEE 802.11 contention window is **not** a power-of-two multiple
of `CW_min`. The exact legacy-compatible expression is:

```
r = retry counter,   r ≥ 0
CW_min = 15,  CW_max = 1023     (configurable)
CW_r   = min((CW_min + 1) * (2 ** r) - 1,  CW_max)
       = min(16 * 2^r - 1,        CW_max)
```

This yields:

```
r=0 → CW=15    (uniform [0..15])
r=1 → CW=31
r=2 → CW=63
r=3 → CW=127
r=4 → CW=255
r=5 → CW=511
r=6 → CW=1023   (saturated)
```

`BO = UniformInt(0, CW_r)` is drawn once when entering BACKOFF; the counter
decrements on every idle slot, freezes on busy, and resumes from the frozen
value once the channel goes idle again after DIFS.

`r > retry_limit` → packet dropped, queue head popped, retry counter reset.

**Anti-pattern (DO NOT USE)**: `CW = CW_min * 2 ** r` — this gives `15, 30,
60, 120, …`, which is not the standard and not legacy-compatible.

### 6.5 Interferer model

**Critical fix for legacy abstraction #4.** Interferers run the *same* MAC.
They do not transmit continuously. Interferer traffic is driven by
`network/traffic.py` feeding their queues, and their CSMA/CA produces real
bursts. This single change is what makes OBSS / SR / channel-selection
conclusions trustworthy.

### 6.6 CCA

Per-device CCA threshold, in dBm. Default `−82 dBm` (legacy default). Energy
above CCA for one slot → channel considered busy for that slot.

The CCA threshold is a controllable knob: `controller.set_cca(channel, dbm)`.
There is no OBSS_PD / SR-relative CCA adjustment in Core — see feature packs.

---

## 7. Multi-Link Operation (MLO) — NOT in Core

MLO is a **Feature Pack**, not part of Core. Core contains no MLO behaviour;
only minimal extension hooks (per-link MAC, per-link queue, per-link CCA in
`core/topology.py`) may exist. All MLO behaviour lives in `features/mlo.py`.

### 7.1 MLO Feature Pack scope

```
@dataclass
class MLD:
    mld_id: int
    ap_id: int
    sta_id: int
    links: list[Link]     # 1..4 links, each on its own channel
    steering_policy: str  # "always_str", "nstr", "manual"
```

Each link has its own MAC state machine, queue, and CCA. The MLD has a
per-packet "current link" assignment written by
`controller.select_link(packet)`.

- **STR (Simultaneous TX/RX)**: links can be TX and RX at the same time; no
  cross-link coupling. Default policy.
- **NSTR (Non-STR)**: while any link is transmitting, all other links
  suspend RX for the duration. Cross-link coupling is implemented as a
  single shared "self-interference" mask.
- `controller.select_link(packet) → link_id`. Default = round-robin over
  idle links.

### 7.2 MLO is deferred from Sprint 1

The first Core release (Sprint 1) ships **without** MLO. MLO Feature Pack is
scheduled for Sprint 3 or later. This is intentional — Core must support
channel-selection / power / CCA / MARL research without MLO.

EMLSR / link switching latency / restricted TWT — **not in MLO v0**; on-demand
per paper.

---

## 8. Queue, traffic, and metrics

### 8.1 Queue

Per (AP, link) FIFO with packet identities. Each packet carries:

```
packet_id, src, dst, link_id, size_bytes, enq_time_ns,
first_tx_time_ns, tx_count, outcome
```

`outcome ∈ {SUCCESS, FAIL_PHY, FAIL_COLLISION, FAIL_NO_ACK, DROP_RETRY_LIMIT}`.

Latency = `success_time_ns − enq_time_ns`.

### 8.2 Traffic models

- **Poisson**: arrival rate λ in pkts/s, sampled per device.
- **CBR**: fixed inter-arrival.
- **On/Off**: Markov on-off with configurable duty cycle.
- **Trace-driven**: list of `(time_ns, n_packets)` loaded from CSV.

Each AP / link has a `TrafficConfig`; multiple APs can use different traces.

### 8.3 Metrics

`metrics/collector.py` records:

- Per-AP throughput, per-link throughput, total throughput.
- Mean / p50 / p95 latency. *(p99 is research infrastructure, not Core.)*
- Queue length time series.
- Collision count, retry count, packet loss count, drop-after-retry-limit count.
- Channel utilization per channel.
- Per-MCS throughput distribution.

`metrics/events.py` writes a per-event trace (CCA, BACKOFF, TX, COLLISION,
ACK, RETRY, DROP) into a file for offline analysis. This is the **single**
debugging instrument; no telemetry framework.

---

## 9. Controller API

The simulator exposes **one** control surface; nothing else is mutable from
outside.

### 9.1 Per-link granularity

The current Project_3 L2 controller acts on **per-channel power distribution**
across multiple selected channels. A flat
`set_tx_power(ap, dbm)` would lose that resolution. The minimum API is:

```python
class Controller:
    # channel selection (per AP)
    def select_channel(self, ap: int, ch: int) -> None: ...

    # per-link Tx power (the unit Project_3 L2 actually controls)
    def set_tx_power(self, link_id: int, dbm: float) -> None: ...
    # or equivalently, by (ap, channel) tuple, for a BSS without MLO:
    # def set_tx_power(self, ap: int, channel: int, dbm: float) -> None: ...

    # per-channel CCA threshold
    def set_cca(self, ap: int, ch: int, dbm: float) -> None: ...

    # MLO Feature Pack surface (no-op if MLO not loaded)
    def select_link(self, mld: int, packet_id: int, link_id: int) -> None: ...
    def set_steering_policy(self, mld: int, policy: str) -> None: ...

    def get_observation(self, ap: int) -> dict:
        """
        Returns a flat dict:
            queue_len, per_link_throughput, per_channel_interference,
            per_channel_idle_busy_ratio, per_link_backoff_counter,
            per_link_mcs, last_latency_p95, ...
        """
```

The Controller is called **once per `decision_interval`**, not per slot. See
§3.3. Sprint 1 ships a no-op Controller; Sprint 2 introduces the per-link
granularity + decision_interval driven observation.

### 9.2 Legacy Adapter

`controllers/legacy_adapter.py` maps the 3-layer hierarchical DQN/DDPG actions
(L1 channel subset, L2 power distribution, L3 per-channel CCA) to the new
Controller API. The mapping must cover:

- L1 channel selection → `select_channel(ap, ch)` per AP.
- L2 power allocation → `set_tx_power(link_id, dbm)` per link / per-AP.
- L3 CCA threshold → `set_cca(channel, dbm)` per channel.

Existing `LearningAgent` + `Exp_1_trainAgents.py`-style scripts work with a
one-line swap to use `LegacyAdapter` as their `genEnvClass`.

The adapter exists *only* for side-by-side Legacy-vs-Research experiments
(Chapter 12 of the prompt). New code calls the Controller directly. The
adapter is **deferred to Sprint 2** — Sprint 1 builds Core first.

---

## 10. Scenarios and configuration

`scenarios/scenario.py` reads a Python dict (YAML deferred) and instantiates
topology, traffic, controllers, metrics. Default scenarios:

- `single_ap_saturated` (legacy-style baseline, 1 AP, 1 STA, no interferer).
- `two_ap_same_channel` (2 APs saturated, same channel — Bianchi-style
  contention test).
- `four_ap_grid` (legacy `Normal` config: 4 APs, 3 channels) — Sprint 2+.
- `apartment_walls` (legacy `Apartment` config) — Sprint 2+.
- `ring_of_aps` (5–20 APs, regular topology, hidden-node stress test) —
  Sprint 2+.
- `mld_two_link` (1 MLD, 2 links, 2 channels) — MLO Feature Pack, Sprint 3+.

Each scenario is a single Python file under `scenarios/`.

---

## 11. Out-of-scope for Core (recorded for §15 of the prompt)

| Mechanism | Status | Trigger paper |
|-----------|:-----:|---------------|
| OFDMA / RU allocation | Feature Pack | OFDMA scheduler paper |
| multi-RU, MU-MIMO | Feature Pack | multi-user scheduling paper |
| MLO (link selection, STR/NSTR, traffic steering) | Feature Pack (`features/mlo.py`) | MLO paper |
| 320 MHz, channel puncturing | on-demand | puncturing study |
| BSS Coloring, OBSS_PD | Feature Pack | OBSS_PD study |
| Spatial Reuse | Feature Pack | SR parameter paper |
| EMLSR | on-demand | EMLSR mode paper |
| 802.11bn / UHR features | on-demand | 802.11bn paper |
| EDCA / QoS AC | on-demand | QoS paper |
| Block ACK, A-MPDU/A-MSDU | on-demand | aggregation paper |
| Mobility | on-demand | mobility paper |
| Rate adaptation (MiniRate / RA) | on-demand | rate-adaptation paper |

The Core must support the **interfaces** that let these features be added
without re-architecting: e.g., a `ChannelMask` for puncturing, a `MultiUser`
slot for OFDMA, a `SpatialReuse` parameter for SR. See
`MVP_AND_FEATURE_BACKLOG.md` §4.

---

## 12. Cross-references

- Legacy abstractions and their impact: `RESEARCH_ENV_AUDIT.md`.
- Justification for what is in / out of Core: `MVP_AND_FEATURE_BACKLOG.md`.
- How Core is verified: `VALIDATION_PLAN.md`.

---

## 13. STOP

This document is the **design contract** for the Sprint 1 Core. Sprint 1
implements only the Core items C1..C10 with the minimum subset needed to
run Scenario A (single AP, no competitor) and Scenario B (two saturated
contenders, same channel). MLO, per-link Controller granularity, and
`decision_interval` are Sprint 2.