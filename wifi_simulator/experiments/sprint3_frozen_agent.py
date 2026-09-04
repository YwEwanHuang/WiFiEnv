"""Sprint 3: Frozen Legacy Agent Comparison.

Goal: plug the same trained legacy agent into both environments and compare
performance and ranking.

Pipeline per env:
    Frozen Legacy Agent (DQN_DQN_DQN, DQN_DDPG_DQN, DQN_DDPG_DDPG)
    → ObservationAdapter → l1/l2/l3 states
    → Agent chooses actions
    → LegacyAdapter → Controller → Research Env
    → RewardAdapter → reward
    → repeat

Run:
    python -m wifi_simulator.experiments.sprint3_frozen_agent
"""
from __future__ import annotations

# ---- PATH SETUP ----
# When run as `python -m wifi_simulator.experiments.sprint3_frozen_agent`
# from WiFiEnv/, sys.path[0] is the cwd. We want:
#   [0] WiFiEnv root  → wifi_simulator.* resolves to THIS repo
#   [1] LEGACY_ROOT   → Project_3 modules resolve correctly
#
# legacy_compat must be imported BEFORE any Project_3/Keras code runs.
import sys as _sys
import os as _os

_WIFIENV_ROOT = _os.path.dirname(
    _os.path.dirname(_os.path.abspath(__file__))
)  # WiFiEnv/ (parent of wifi_simulator/)

if _WIFIENV_ROOT not in _sys.path or _sys.path[0] != _WIFIENV_ROOT:
    if _WIFIENV_ROOT in _sys.path:
        _sys.path.remove(_WIFIENV_ROOT)
    _sys.path.insert(0, _WIFIENV_ROOT)

_LEGACY_ROOT_STR = _os.environ.get(
    "LEGACY_PROJECT3_ROOT",
    _os.path.expanduser("~/Desktop/Project_3"),
)
if _LEGACY_ROOT_STR not in _sys.path:
    _sys.path.append(_LEGACY_ROOT_STR)

# Load shim before any Project_3 imports.
import legacy_compat

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# Default settings.
TARGET_AP = 0
PT_MAX_DBM = 20.0
CCA_DBM = -82.0
DECISION_INTERVAL_NS = int(4.5e-3 * 1e9)   # 4.5 ms
LEGACY_ARR_MEAN = 500.0
TIMESLOT_S = 4.5e-3
LAMBDA_PPS = LEGACY_ARR_MEAN / TIMESLOT_S   # 111,111 pps
MAX_QLEN = 16000
INIT_QLEN = 8000
N_CHANNELS = 3
N_STEPS_LEGACY = 1000  # legacy steps per episode
DURATION_S = 4.7       # research env total duration (slightly > 1000*4.5ms = 4.5s)

# Model paths (relative to Project_3/Models/).
MODELS = {
    "DQN_DQN_DQN": "Models/DQN_DQN_DQN",
    "DQN_DDPG_DQN": "Models/DQN_DDPG_DQN",
    "DQN_DDPG_DDPG": "Models/DQN_DDPG_DDPG",
}
SEEDS = [6, 7, 8, 9, 10]

LEGACY_ROOT = _os.environ.get(
    "LEGACY_PROJECT3_ROOT",
    _os.path.expanduser("~/Desktop/Project_3"),
)


# ===========================================================================
# Legacy reference: frozen agent in legacy env
# ===========================================================================

def _run_legacy_agent_impl(model_name: str, seed: int) -> dict:
    """Core implementation. Must be called from within LEGACY_ROOT."""
    import h5py
    from env import genEnvClass
    from LearningAgent import LearningAgent

    Env = genEnvClass(env_type="Normal")
    env = Env(seed=seed, arr_mean=LEGACY_ARR_MEAN, reset_qlen=True)

    model_path = _os.path.join(LEGACY_ROOT, MODELS[model_name])
    learn_alg = model_name.split("_")
    l1_alg, l2_alg, l3_alg = learn_alg

    (state_sizes, action_sizes, l1_actions, l2_actions,
     l3_actions, n_agents) = env.get_state_action_info()

    # The env reports state_sizes[2]=4 but the L3 models were trained with
    # state_size=1. Inspect the saved weights to override.
    try:
        l3_weight_path = _os.path.join(
            model_path, "Layer_3", "DQN_agent_0", "weights.h5"
        )
        with h5py.File(l3_weight_path, "r") as f:
            shapes: dict[str, tuple] = {}
            def collect(name, obj):
                if hasattr(obj, "shape"):
                    shapes[name] = obj.shape
            f.visititems(collect)
            kernels = sorted([k for k in shapes if "kernel" in k])
            l3_true_state_size = shapes[kernels[0]][0]
        state_sizes = list(state_sizes)
        state_sizes[2] = l3_true_state_size
        print(f"  [L3 state_size override: {4} → {l3_true_state_size}")
    except Exception:
        pass  # keep env's state_sizes

    action_boundary = [
        [None, None],
        [0, env.pt_dec],
        [l3_actions[0], l3_actions[-1]],
    ]
    action_size_per_layer = [
        action_sizes[0],
        action_sizes[1],  # dict for DQN, list for DDPG
        action_sizes[2],
    ]
    if l2_alg == "DDPG":
        action_size_per_layer[1] = list(range(1, n_agents + 1))
    if l3_alg == "DDPG":
        action_size_per_layer[2] = 1

    agent = LearningAgent(
        state_size_per_layer=state_sizes,
        action_size_per_layer=action_size_per_layer,
        action_boundary=action_boundary,
        learn_alg_per_layer=learn_alg,
        n_agents=n_agents,
        model_path=model_path,
    )
    agent.predictMode()

    selected_channels = {TARGET_AP: []}
    tpc = {TARGET_AP: {c: 0.0 for c in range(N_CHANNELS)}}
    cca = {TARGET_AP: {c: None for c in range(N_CHANNELS)}}

    step_rewards, step_throughput, step_queue = [], [], []
    for _ in range(N_STEPS_LEGACY):
        l1s = env.l1_state(TARGET_AP)
        l1a_idx = agent.l1_action(l1s)
        l1a = l1_actions[l1a_idx]
        selected_channels[TARGET_AP] = l1a

        l2s = env.l2_state(TARGET_AP, l1a)
        temp_l2a = agent.l2_action(l2s)
        if l2_alg != "DDPG":
            n_c, raw_action = temp_l2a
            l2a = l2_actions[n_c][raw_action]
        else:
            n_c, raw_action, env_action = temp_l2a
            l2a = env_action[0]

        for i in range(len(l1a)):
            tpc[TARGET_AP][l1a[i]] = l2a[i]

        l3s = env.l3_state(TARGET_AP, tpc[TARGET_AP])
        # NOTE: env.l3_state returns 2D states [tx_power, interference] but
        # the saved L3 models expect state_size=1. The assert fails at (1,2).
        # We catch the exception and use default CCA = -82 dBm for all channels.
        try:
            l3a_temp = agent.l3_action(l3s)
            l3a = {}
            if l3_alg != "DDPG":
                for k in l3a_temp:
                    l3a[k] = l3_actions[l3a_temp[k]] if l3a_temp[k] is not None else None
            else:
                for k in l3a_temp:
                    l3a[k] = l3a_temp[k][1] if l3a_temp[k] is not None else None
        except AssertionError:
            l3a = {}
        cca[TARGET_AP] = l3a if l3a else {c: l3_actions[0] for c in range(N_CHANNELS)}

        if n_c == N_CHANNELS:
            for q in range(N_CHANNELS):
                if cca[TARGET_AP].get(q) is None:
                    cca[TARGET_AP][q] = -82.0
        else:
            for q in range(N_CHANNELS):
                if q not in cca[TARGET_AP] or cca[TARGET_AP][q] is None:
                    cca[TARGET_AP][q] = -82.0

        (n_packets, cca_results, noPacket2Tran,
         Reward, Reward_per_channel) = env.reward(cca, tpc, selected_channels)

        dataRate = 0.0
        for c in cca_results.get(TARGET_AP, {}):
            if cca_results[TARGET_AP][c]:
                ch_dr = Reward_per_channel.get(TARGET_AP, {}).get(c, -50.0)
                if ch_dr != -50:
                    dataRate += max(ch_dr, 0)
        step_throughput.append(dataRate)
        step_rewards.append(Reward.get(TARGET_AP, 0.0))
        step_queue.append(env.Queue[TARGET_AP])

        if _ % 10 == 0:
            env.updateRx()

    total_drained = sum(step_throughput) * TIMESLOT_S * 1e3
    return {
        "seed": seed,
        "model": model_name,
        "throughput_mbps": statistics.mean(step_throughput),
        "reward": statistics.mean(step_rewards),
        "queue_len_mean": statistics.mean(step_queue),
        "queue_len_final": step_queue[-1],
        "total_drained_packets": total_drained,
    }


def run_legacy_agent(model_name: str, seed: int) -> dict:
    """Run the frozen legacy agent in the legacy Project_3 env.

    Returns per-step metrics averaged over N_STEPS_LEGACY.

    The legacy env reads config.txt from a relative path, so we must
    execute inside LEGACY_ROOT.
    """
    import contextlib
    if LEGACY_ROOT not in _sys.path:
        _sys.path.insert(0, LEGACY_ROOT)
    with contextlib.chdir(LEGACY_ROOT):
        return _run_legacy_agent_impl(model_name, seed)


# ===========================================================================
# Research: frozen agent in Research Env
# ===========================================================================

def run_research_agent(model_name: str, seed: int) -> dict:
    """Run the frozen legacy agent in the Research Env.

    Pipeline:
        ResearchEnvWrapper → ObservationAdapter → l1/l2/l3 states
        → legacy FrozenAgent chooses actions
        → LegacyAdapter → Controller → Simulator
        → RewardAdapter → reward
    """
    from wifi_simulator.agents.frozen_agent import FrozenAgent
    from wifi_simulator.agents.observation_adapter import ObservationAdapter
    from wifi_simulator.agents.reward_adapter import RewardAdapter
    from wifi_simulator.scenarios.normal_4ap import make_aps

    model_path = _os.path.join(LEGACY_ROOT, MODELS[model_name])
    learn_alg = model_name.split("_")
    l1_alg, l2_alg, l3_alg = learn_alg

    # Build frozen agent (infers state/action sizes from legacy env).
    agent = FrozenAgent(
        model_path=model_path,
        n_channels=N_CHANNELS,
        target_ap=TARGET_AP,
        pt_max_dbm=PT_MAX_DBM,
    )

    # Build observation and reward adapters.
    obs_adapter = ObservationAdapter(
        n_channels=N_CHANNELS,
        target_ap=TARGET_AP,
        max_q_len=MAX_QLEN,
        init_q_len=INIT_QLEN,
    )
    reward_adapter = RewardAdapter(target_ap=TARGET_AP)

    # Build Research Env.
    from wifi_simulator.core.simulator import Simulator
    from wifi_simulator.controllers.controller import Controller

    aps = make_aps(lambda_pps=LAMBDA_PPS, target_channel=0)
    sim = Simulator(
        seed=seed,
        duration_s=DURATION_S,
        aps=aps,
        noise_dbm=-95.0,
        retry_limit=6,
    )
    controller = Controller(sim)

    # Apply default policy at startup.
    for ch in range(N_CHANNELS):
        controller.set_tx_power_for_ap_channel(TARGET_AP, ch, -100.0)
    controller.set_tx_power_for_ap_channel(TARGET_AP, 0, PT_MAX_DBM)
    for ch in range(N_CHANNELS):
        controller.set_cca_for_ap(TARGET_AP, CCA_DBM)

    # Prime: run first epoch to get initial observation.
    delta = sim.run_for(DECISION_INTERVAL_NS)

    selected_channels = [0]
    tx_power = {0: 1.0}
    cca_map = {c: CCA_DBM for c in range(N_CHANNELS)}

    step_rewards, step_throughput, step_queue = [], [], []
    step_collisions, step_retries, step_drops = [], [], []
    step_lat_mean, step_lat_p95 = [], []
    total_steps = 0

    while total_steps < 1005:  # 1000 epochs + safety margin
        total_steps += 1
        try:
            # Build L1/L2/L3 states.
            link_id = TARGET_AP
            l1s = obs_adapter.l1_state(delta, tx_power, link_id)
            l2s = obs_adapter.l2_state(delta, selected_channels)
            l3s = obs_adapter.l3_state(delta, selected_channels,
                                        tx_power, cca_map)

            # Agent actions.
            l1a_idx = agent.l1_action(l1s)
            l1a = agent.l1_action_to_channels(l1a_idx)
            l2a = agent.l2_action(l2s)
            power_dict = agent.l2_action_to_power_dict(l2a, l1a)
            l3a = agent.l3_action(l3s)
            cca_dict = agent.l3_action_to_cca_dict(l3a, l1a)

            # Apply via controller.
            for ch, cca_val in cca_dict.items():
                controller.set_cca_for_ap(TARGET_AP, cca_val)
                cca_map[ch] = cca_val

            for ch in range(N_CHANNELS):
                p = power_dict.get(ch, 0.0)
                if p <= 0.0:
                    tx_dbm = -100.0
                else:
                    tx_dbm = PT_MAX_DBM + 10.0 * math.log10(p)
                controller.set_tx_power_for_ap_channel(TARGET_AP, ch, tx_dbm)
                tx_power[ch] = p

            selected_channels = l1a
            delta = sim.run_for(DECISION_INTERVAL_NS)

            # Reward.
            rr = reward_adapter.compute(delta)
            step_rewards.append(rr.reward)
            step_throughput.append(rr.throughput_mbps)
            step_queue.append(rr.queue_len)
            step_collisions.append(rr.collisions)
            step_retries.append(rr.retries)
            step_drops.append(rr.drops)
            step_lat_mean.append(rr.latency_mean_us)
            step_lat_p95.append(rr.latency_p95_us)

            # Done check.
            if rr.queue_len >= MAX_QLEN:
                break
            if sim.loop.now_ns >= int(DURATION_S * 1e9):
                break
        except Exception as e:
            import traceback
            _sys.stderr.write(f'STEP EXCEPTION at step {total_steps}: {e}\n')
            _sys.stderr.write(traceback.format_exc())
            _sys.stderr.write(f'step_rewards len={len(step_rewards)}\n')
            _sys.stderr.flush()
            break

    return {
        "seed": seed,
        "model": model_name,
        "total_steps": total_steps,
        "throughput_mbps": statistics.mean(step_throughput),
        "throughput_mbps_std": statistics.stdev(step_throughput)
                              if len(step_throughput) > 1 else 0.0,
        "reward": statistics.mean(step_rewards),
        "queue_len_mean": statistics.mean(step_queue),
        "queue_len_final": step_queue[-1] if step_queue else 0,
        "collisions_mean": statistics.mean(step_collisions) if step_collisions else 0.0,
        "retries_mean": statistics.mean(step_retries) if step_retries else 0.0,
        "drops_mean": statistics.mean(step_drops) if step_drops else 0.0,
        "latency_mean_us": statistics.mean(step_lat_mean) if step_lat_mean else 0.0,
        "latency_p95_us": statistics.mean(step_lat_p95) if step_lat_p95 else 0.0,
    }


# ===========================================================================
# Aggregation
# ===========================================================================

def agg(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": statistics.mean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


@dataclass
class ModelResult:
    model: str
    legacy: list[dict] = field(default_factory=list)
    research: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        l_through = agg([r["throughput_mbps"] for r in self.legacy])
        r_through = agg([r["throughput_mbps"] for r in self.research])
        l_reward = agg([r["reward"] for r in self.legacy])
        r_reward = agg([r["reward"] for r in self.research])
        l_queue = agg([r["queue_len_mean"] for r in self.legacy])
        r_queue = agg([r["queue_len_mean"] for r in self.research])
        r_coll = agg([r["collisions_mean"] for r in self.research])
        r_retry = agg([r["retries_mean"] for r in self.research])
        r_drop = agg([r["drops_mean"] for r in self.research])
        r_lat_mean = agg([r["latency_mean_us"] for r in self.research])
        r_lat_p95 = agg([r["latency_p95_us"] for r in self.research])
        return {
            "model": self.model,
            "legacy": {
                "throughput_mbps": l_through,
                "reward": l_reward,
                "queue_len_mean": l_queue,
            },
            "research": {
                "throughput_mbps": r_through,
                "reward": r_reward,
                "queue_len_mean": r_queue,
                "collisions_mean": r_coll,
                "retries_mean": r_retry,
                "drops_mean": r_drop,
                "latency_mean_us": r_lat_mean,
                "latency_p95_us": r_lat_p95,
            },
        }


# ===========================================================================
# Main
# ===========================================================================

def main() -> int:
    print("=" * 72)
    print("Sprint 3 — Frozen Legacy Agent Comparison")
    print("=" * 72)
    print(f"LEGACY_ROOT: {LEGACY_ROOT}")
    print(f"Seeds: {SEEDS}")
    print(f"Models: {list(MODELS.keys())}")
    print(f"decision_interval: {DECISION_INTERVAL_NS / 1e6:.4f} ms")
    print(f"Traffic: lambda={LAMBDA_PPS:.0f} pps, arr_mean={LEGACY_ARR_MEAN}")
    print()

    results: dict[str, ModelResult] = {}

    for model_name in MODELS:
        print(f"\n{'=' * 60}")
        print(f"  Model: {model_name}")
        print(f"{'=' * 60}")
        mr = ModelResult(model=model_name)
        for seed in SEEDS:
            print(f"\n  seed={seed}...", end=" ", flush=True)

            # Legacy.
            try:
                lr = run_legacy_agent(model_name, seed)
                mr.legacy.append(lr)
                print(f"legacy done  ", end="", flush=True)
            except Exception as e:
                print(f"LEGACY ERROR: {e}", flush=True)
                continue

            # Research.
            try:
                rr = run_research_agent(model_name, seed)
                mr.research.append(rr)
                print(f"research done  ", end="", flush=True)
            except Exception as e:
                print(f"RESEARCH ERROR: {e}", flush=True)
                import traceback
                traceback.print_exc()
                continue

            # Per-seed summary.
            lt = lr["throughput_mbps"]
            rt = rr["throughput_mbps"]
            print(f"\n    legacy: {lt:.2f} Mbps, "
                  f"research: {rt:.2f} Mbps, "
                  f"ratio: {rt/lt if lt > 0 else 0:.2f}")

        results[model_name] = mr

    # Print final comparison table.
    print("\n" + "=" * 72)
    print("RESULTS SUMMARY")
    print("=" * 72)

    print("\nThroughput (Mbps), mean ± std, [min, max] — 5 seeds")
    print("-" * 70)
    print(f"  {'Model':<20s}  {'Legacy':>22s}  {'Research':>22s}")
    for model_name, mr in results.items():
        ls = mr.summary()["legacy"]["throughput_mbps"]
        rs = mr.summary()["research"]["throughput_mbps"]
        print(f"  {model_name:<20s}  "
              f"{ls['mean']:6.2f} ± {ls['std']:5.2f}  "
              f"[{ls['min']:5.2f}, {ls['max']:5.2f}]"
              f"  |  "
              f"{rs['mean']:6.2f} ± {rs['std']:5.2f}  "
              f"[{rs['min']:5.2f}, {rs['max']:5.2f}]")

    print("\nResearch-only metrics (mean ± std)")
    print("-" * 70)
    print(f"  {'Model':<20s}  "
          f"{'Collisions/epoch':>16s}  {'Retries/epoch':>13s}  "
          f"{'Drops/epoch':>11s}  {'Lat_mean(us)':>12s}  {'Lat_p95(us)':>11s}")
    for model_name, mr in results.items():
        rs = mr.summary()["research"]
        print(f"  {model_name:<20s}  "
              f"{rs['collisions_mean']['mean']:6.2f}±{rs['collisions_mean']['std']:5.2f}  "
              f"{rs['retries_mean']['mean']:5.2f}±{rs['retries_mean']['std']:4.2f}  "
              f"{rs['drops_mean']['mean']:4.2f}±{rs['drops_mean']['std']:3.2f}  "
              f"{rs['latency_mean_us']['mean']:6.1f}±{rs['latency_mean_us']['std']:5.1f}  "
              f"{rs['latency_p95_us']['mean']:5.1f}±{rs['latency_p95_us']['std']:4.1f}")

    # Ranking.
    print("\nRanking (by throughput Mbps, research env)")
    print("-" * 70)
    research_ranking = sorted(
        results.items(),
        key=lambda x: x[1].summary()["research"]["throughput_mbps"]["mean"],
        reverse=True,
    )
    legacy_ranking = sorted(
        results.items(),
        key=lambda x: x[1].summary()["legacy"]["throughput_mbps"]["mean"],
        reverse=True,
    )
    print("  Legacy ranking:")
    for rank, (model_name, _) in enumerate(legacy_ranking, 1):
        t = results[model_name].summary()["legacy"]["throughput_mbps"]["mean"]
        print(f"    {rank}. {model_name}: {t:.2f} Mbps")
    print("  Research ranking:")
    for rank, (model_name, _) in enumerate(research_ranking, 1):
        t = results[model_name].summary()["research"]["throughput_mbps"]["mean"]
        print(f"    {rank}. {model_name}: {t:.2f} Mbps")

    rank_flip = (
        [m for m, _ in legacy_ranking] !=
        [m for m, _ in research_ranking]
    )
    print(f"\n  Ranking flip: {'YES' if rank_flip else 'No change'}")

    # Check if research metrics show agent can actually transmit.
    print("\nResearch throughput check (is agent transmitting?):")
    for model_name, mr in results.items():
        rts = [r["throughput_mbps"] for r in mr.research]
        if not rts:
            continue
        mean_t = statistics.mean(rts)
        if mean_t < 0.1:
            print(f"  {model_name}: {mean_t:.4f} Mbps — agent may not be "
                  "starting any TX. Check observation mapping or agent policy.")
        else:
            print(f"  {model_name}: {mean_t:.2f} Mbps — OK")

    # Save raw results.
    import json
    raw = {
        model_name: {
            "legacy": mr.legacy,
            "research": mr.research,
            "summary": mr.summary(),
        }
        for model_name, mr in results.items()
    }
    out_path = _os.path.join(
        _os.path.dirname(__file__), "sprint3_results_raw.json"
    )
    with open(out_path, "w") as f:
        json.dump(raw, f, indent=2, default=str)
    print(f"\nRaw results saved to: {out_path}")
    return 0


if __name__ == "__main__":
    _sys.exit(main())