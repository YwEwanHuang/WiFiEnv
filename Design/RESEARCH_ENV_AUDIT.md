# RESEARCH_ENV_AUDIT.md

**Stage**: Design (Design Convergence pass, consistent with
`MVP_AND_FEATURE_BACKLOG.md`, `RESEARCH_ENV_DESIGN.md`, `VALIDATION_PLAN.md`).
**Scope**: Audit of the *legacy* `Project_3` Wi-Fi environment and identification of
abstractions that materially change the conclusions of Wi-Fi MAC/PHY algorithms.
**Source of truth**: code under `/Users/yiwei/Desktop/Project_3/` (`env.py`, `baseEnv.py`,
`LearningAgent.py`, `Exp_*.py`, `agent/`, `config/`, `simulation plan.docx`).

---

## 1. Legacy environment — what it actually does

### 1.1 One RL step ≡ one "super-slot"

`env.py`:

```python
self.timeSlotDuration = 4500e-6   # 4.5 ms
self.mbps2n_packet = (1e6/8) * self.timeSlotDuration / self.packetSize
```

Per step:

1. `l1_state(ap)` generates new packet arrivals and adds them to the integer queue.
2. Agents pick (channel-set, power-distribution, CCA thresholds).
3. `channelCCAResult(cca)` runs an instantaneous CCA per (target-AP, channel):
   interference from non-target APs is summed in dB, then compared against `cca`.
4. For each AP whose channel clears CCA, `reward()` evaluates Shannon capacity
   `BW * log2(1+SINR) / 1e6` Mbps on each channel and converts to
   `dataRate * mbps2n_packet` packets, draining the queue by that amount.

### 1.2 Three-layer hierarchical controller

| Layer | Alg | State | Action |
|------:|-----|-------|--------|
| L1 | DQN | queue + per-channel interference magnitude | pick a channel subset (powerset of n_channels) |
| L2 | DDPG | per-channel interference + selected channels | Dirichlet-style power distribution over chosen channels |
| L3 | DQN (one agent per channel) | tx power on the channel + last interference | CCA threshold in dBm |

### 1.3 Multi-AP / Multi-BSS

- `n_AP` is set from `config.txt` (4 APs in `Normal`, 10 in `Apartment`).
- `used_channel` is a static dict; APs other than `targetAPs` are hard-assigned.
- All non-target APs always transmit at `pt_max` in `channelCCAResult`
  (`self.rx_power(i_ap, ap, self.pt_max)`), regardless of any traffic Markov chain
  in `I_ap_tfc_dict` (which is built but never consulted on the critical path).
- `gen_sta_position` places 4 fixed STAs around each AP.

### 1.4 PHY model

- `path_loss_matrix[i, j]` = `freq_loss + 10*alpha*log10(d) + n_walls*5` (dB).
  `alpha = 3.5`, `freq_loss` for 5 GHz, +5 dB/wall.
- `rx_power(src, dst, pt, hassdeff=True)` returns `pt - PL - N(0, sdeff_sigma)`.
  Sigma defaults to 3.
- `env_noise_density = 5e-17` W/Hz → noise floor ≈ −90 dBm on a 20 MHz channel.
- `thr_with_SINR`: Shannon capacity only. No MCS table, no PER, no airtime.

### 1.5 Apartment extension

- Same env, with explicit wall geometry; wall count is fed into path loss.
- Used for `Exp_1_trainAgents_IEEEScenario`.

### 1.6 Traffic & queue

- `binomial`, `poisson`, or trace-driven (`trace_nextPackets`).
- Queue is a per-AP int counter; if `Queue >= maxQLen`, episode is reset.
- No packet-level identity, no latency.

---

## 2. Where the legacy code diverges from the prompt

| Prompt assumption | What the code actually does |
|-------------------|-----------------------------|
| "one RL step ≈ one Wi-Fi slot" | one step ≈ a 4.5 ms **super-slot** that compresses ~500 IEEE 802.11 slots (slot time = 9 µs). CSMA inside the step is replaced by one binary CCA outcome per (AP, channel). |
| "interferer traffic" | interferers are modelled as **always transmitting at `pt_max`** on their assigned channel; the `MarkovChain` in `I_ap_tfc_dict` is never read by the simulation path. |
| "Shannon" — implied interim use | still in production as the *only* throughput model — no MCS/PER yet. |
| "per-channel power control" | L2 emits a power *distribution* over chosen channels; the new simulator must expose per-link granularity on `set_tx_power`, not a flat per-AP scalar. |

These divergences are recorded here as part of the audit; the new design
(`RESEARCH_ENV_DESIGN.md`) treats them as primary targets to fix.

---

## 3. Abstractions that materially change algorithm conclusions

Each row answers: *if a paper relies on the legacy env, does this abstraction flip the
qualitative ranking of algorithms?* "Yes" ⇒ must be in Core. "Partial" ⇒ defer to
on-demand. "No" ⇒ keep it cheap.

| # | Abstraction | Effect on algorithms | Severity |
|--:|-------------|----------------------|:--------:|
| 1 | **No CSMA/CA**: 1-step super-slot, no DIFS/AIFS/backoff/retry/ACK | Under real Wi-Fi, contention, collisions, and idle slots dominate throughput. Algorithms that look great under "binary CCA" can collapse under backoff pressure, and vice versa. Affects: channel selection, CCA tuning, OBSS, MARL convergence. | **Yes — Core (C2)** |
| 2 | **No packet airtime / no MCS table / Shannon capacity only** | Hides the entire rate-vs-reliability trade-off (MCS 0..11, HE/EHT MCS 0..13). Tx-power and CCA choices change which MCS is reachable; legacy env evaluates a continuous curve and makes these choices look near-free. | **Yes — Core (C5)** |
| 3 | **No retry / no collision detection** | Collisions are silent packet loss. Real backoff/retry, RTS/CTS, and Block ACK (research-deferred) all change throughput + latency. | **Yes — Core (C3)** |
| 4 | **Interferers always transmit at full `pt_max`** | Distorts OBSS dynamics: legacy env over-estimates interference and removes duty-cycle. OBSS_PD, SR, channel selection conclusions will not transfer. | **Yes — Core (C7)** |
| 5 | **Per-call shadowing draw (`sdeff()`)** | A receiver-side shadowing value drawn fresh on every `rx_power` call is per-call noise, not a spatial process. It destroys link correlation. The same link sees uncorrelated noise across packets → blocks any meaningful fast-fading / rate-adaptation study. | **Yes — Core (C4)** |
| 6 | **No packet-level events → no latency / jitter** | Latency is the headline metric for QoS / MLO papers; legacy env cannot produce it. | **Yes — Core (C6)** |
| 7 | **No multi-link / MLO** | MLO is a research topic; it is **NOT in Core** but in the **MLO Feature Pack** (`features/mlo.py`). See `MVP_AND_FEATURE_BACKLOG.md` §3.1. | Feature Pack |
| 8 | **Channels are independent / no bonding / no overlap** | OK for current channel-selection studies; will need a width/abstraction layer for 802.11be. | Partial — on-demand |
| 9 | **Single target AP / other APs hard-coded** | Limits MARL studies that need symmetric agents. | Partial — on-demand |
| 10 | **Three-layer hierarchical controller with non-Markovian storage** | State is collapsed per step; reward is delayed and discounted in `Exp_1`. Defer for now — keep it. | No |
| 11 | **Packet size = 2304 B hard-coded** | Acceptable for first cut; one knob later. | No |
| 12 | **No mobility, no association, no security** | Out of scope for current research. | No |
| 13 | **No EDCA / QoS** | Adequate for best-effort research; defer. | No |
| 14 | **Shannon vs real MCS gap is paper-topic dependent** | If the paper is "rate adaptation", Shannon is unacceptable. If the paper is "channel selection in multi-AP" with fixed MCS, Shannon is acceptable but MCS is still preferable. → use **Ideal MCS Selection** in Core. | Partial — Core (C5) |

---

## 4. Inferred research questions (what the Core must answer)

From `simulation plan.docx`, `Exp_*.py`, the Model/Results folders, and the prompt's
list of features, the active research questions are:

1. **Channel selection** under multi-BSS interference — does the algorithm still pick
   good channels when CSMA, MCS, and retry are real?
2. **Transmit power allocation** with **CCA threshold tuning** (L3 in legacy) — how
   does the trade-off change with airtime + collisions + MCS?
3. **MARL / multi-agent** convergence on (1) and (2).
4. **Multi-BSS overlapping** with N_AP = 5–20, N_STA = 50–200.
5. **MLO** (link selection, traffic steering, basic STR/NSTR) — **Feature Pack**.
6. **Comparison vs ns-3** for a small set of "headline" scenarios — **optional**.

These are the *fidelity* targets for Core; everything else is on-demand.

---

## 5. What stays in legacy, untouched

- `LearningAgent.py`, `agent/NN_agent.py`, `agent/DDPG.py`, `agent/DuelingDQN.py`.
- All `Exp_*.py` (they drive legacy env).
- All `Models/`, `Results/`, `Figures/`, `past_fig/`.
- `MAenv/` (third-party PettingZoo-style multiagent utilities, not used in current
  Exp scripts; keep untouched).
- `Utility/` (MarkovChain, tools, OUActionNoise).

A new environment lives at `wifi_simulator/` and is consumed by **new** scripts.
A thin **Legacy Adapter** at
`wifi_simulator/controllers/legacy_adapter.py` translates the
hierarchical L1/L2/L3 action interface into the new Controller interface for
side-by-side comparison experiments (Chapter 12 of the prompt). The
Legacy Adapter is **deferred to Sprint 2** — Sprint 1 builds Core first.

---

## 6. Audit summary for the Core design

The legacy env is a **single-step Bernoulli Wi-Fi slot simulator with Shannon capacity**
and always-on interferers. The four mechanisms that *most* distort conclusions and
must be in the Core are:

1. Discrete-event time + slot-accurate CSMA/CA (DIFS/AIFS + backoff + ACK + retry).
2. Per-packet PHY (path loss + *correlated* shadowing + interference + noise +
   SINR + MCS + PER + airtime), with **linear-domain interference summation** —
   no dBm arithmetic.
3. Realistic interferer duty cycle (interferers also run CSMA/CA).
4. Per-link queueing with packet identities so latency is measurable.

Everything beyond these four is on-demand; see `MVP_AND_FEATURE_BACKLOG.md`.

### 6.1 Cross-document consistency

The Core items in `MVP_AND_FEATURE_BACKLOG.md` (`C1`..`C10`) are the
implementation contract for `RESEARCH_ENV_DESIGN.md`. The validation
contract for those items is in `VALIDATION_PLAN.md` §A. The MLO Feature
Pack is documented in `MVP_AND_FEATURE_BACKLOG.md` §3.1 and
`RESEARCH_ENV_DESIGN.md` §7; MLO is **not** part of Core and is **not**
validated in §A. The Legacy Adapter is documented in
`RESEARCH_ENV_DESIGN.md` §9.2 and is **deferred to Sprint 2**.

ns-3 is treated as **optional external validation** in `VALIDATION_PLAN.md`
§C; no ns-3 version is fixed at design time, and **no ns-3 framework is
built for Sprint 1**. The Sprint 1 implementation does not block on ns-3.