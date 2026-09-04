"""Research Env wrapper with legacy step/reset interface.

This wrapper lets the frozen legacy LearningAgent interact with the
Research Env through the same interface it was trained with:

    env = ResearchEnvWrapper(seed=..., ...)
    obs = env.reset()                 # same as legacy env.reset()
    for step in range(max_steps):
        l1_state = env.l1_state()     # matches legacy env.l1_state(ap)
        l2_state = env.l2_state()     # matches legacy env.l2_state(ap, channels)
        l3_states = env.l3_state()    # matches legacy env.l3_state(ap, power_dist)
        action = agent.choose_action(obs)
        obs, reward, done, info = env.step(action)  # compatible with agent.store()

The wrapper:
1. Owns the Simulator + Controller + ObservationAdapter + RewardAdapter.
2. Tracks current action (channel/power/CCA) state.
3. Exposes l1_state / l2_state / l3_state at each step.
4. Applies actions through the Controller.

decision_interval = 4.5 ms (matching legacy timeslot_length).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from wifi_simulator.agents.frozen_agent import FrozenAgent
from wifi_simulator.agents.observation_adapter import ObservationAdapter
from wifi_simulator.agents.reward_adapter import RewardAdapter
from wifi_simulator.controllers.controller import Controller
from wifi_simulator.core.simulator import Simulator


# Default settings matching legacy config.txt.
TARGET_AP = 0
PT_MAX_DBM = 20.0
CCA_DBM = -82.0
DECISION_INTERVAL_S = 4.5e-3           # 4.5 ms
DECISION_INTERVAL_NS = int(DECISION_INTERVAL_S * 1e9)
LEGACY_ARR_MEAN = 500.0
TIMESLOT_S = 4.5e-3
LAMBDA_PPS = LEGACY_ARR_MEAN / TIMESLOT_S  # 111,111 pps
MAX_QLEN = 16000
INIT_QLEN = 8000
N_CHANNELS = 3
N_STEPS_LEGACY = 1000  # for legacy reference run


@dataclass
class StepResult:
    """Result of one step(). Mirrors gym-style but with legacy fields."""
    # Compatibility with legacy agent store interface.
    l1_state: np.ndarray
    l2_state: np.ndarray
    l3_states: dict[int, np.ndarray]
    # Reward components (legacy-format).
    reward: float
    reward_result: "RewardAdapter"  # type annotation hack
    # Done flag.
    done: bool
    # Info dict for metrics.
    info: dict = field(default_factory=dict)
    # Current actions (for next step's L2/L3 states).
    selected_channels: list[int] = field(default_factory=list)
    tx_power_per_channel: dict[int, float] = field(default_factory=dict)
    cca_per_channel: dict[int, float] = field(default_factory=dict)


class ResearchEnvWrapper:
    """Wrap Research Simulator as a legacy-style step/reset env.

    Usage with frozen legacy agent:
        wrapper = ResearchEnvWrapper(seed=6, duration_s=4.5, ...)
        agent = FrozenAgent(model_path=..., n_channels=3, target_ap=0)

        obs = wrapper.reset()
        for step in range(max_steps):
            l1 = wrapper.l1_state()
            l2 = wrapper.l2_state()
            l3 = wrapper.l3_state()
            # agent chooses actions...
            l1a_idx = agent.l1_action(l1)
            selected_ch = agent.l1_action_to_channels(l1a_idx)
            l2a = agent.l2_action(l2)
            power_dict = agent.l2_action_to_power_dict(l2a, selected_ch)
            l3a = agent.l3_action(l3)
            cca_dict = agent.l3_action_to_cca_dict(l3a, selected_ch)
            result = wrapper.step(l1a_idx, l2a, selected_ch, power_dict, cca_dict)
            # result.l1_state, result.l2_state are for next step
    """

    def __init__(
        self,
        seed: int,
        duration_s: float = 4.5,
        target_ap: int = TARGET_AP,
        pt_max_dbm: float = PT_MAX_DBM,
        cca_dbm: float = CCA_DBM,
        n_channels: int = N_CHANNELS,
        lambda_pps: float = LAMBDA_PPS,
        max_q_len: int = MAX_QLEN,
        init_q_len: int = INIT_QLEN,
        decision_interval_ns: int = DECISION_INTERVAL_NS,
        legacy_arr_mean: float = LEGACY_ARR_MEAN,
        # Scenario: function or None for default normal_4ap.
        scenario_factory=None,
    ) -> None:
        self.seed = seed
        self.duration_s = duration_s
        self.target_ap = target_ap
        self.pt_max_dbm = pt_max_dbm
        self.cca_dbm = cca_dbm
        self.n_channels = n_channels
        self.decision_interval_ns = decision_interval_ns
        self.max_q_len = max_q_len
        self.init_q_len = init_q_len
        self.legacy_arr_mean = legacy_arr_mean

        # Build scenario APs.
        if scenario_factory is not None:
            aps = scenario_factory(
                lambda_pps=lambda_pps, target_channel=0
            )
        else:
            from wifi_simulator.scenarios.normal_4ap import make_aps
            aps = make_aps(lambda_pps=lambda_pps, target_channel=0)

        # Simulator owns everything.
        self.sim = Simulator(
            seed=seed,
            duration_s=duration_s,
            aps=aps,
            noise_dbm=-95.0,
            retry_limit=6,
        )
        self.controller = Controller(self.sim)
        self.obs_adapter = ObservationAdapter(
            n_channels=n_channels,
            target_ap=target_ap,
            max_q_len=max_q_len,
            init_q_len=init_q_len,
        )
        self.reward_adapter = RewardAdapter(
            target_ap=target_ap,
        )

        # Current action state (for L2/L3 state computation).
        self._selected_channels: list[int] = []
        self._tx_power_per_channel: dict[int, float] = {}
        self._cca_per_channel: dict[int, float] = {
            c: cca_dbm for c in range(n_channels)
        }

        # Track episode state.
        self._done = False
        self._steps = 0

        # Default policy applied at reset.
        self._apply_default_policy()

    def reset(self) -> dict:
        """Reset environment. Returns initial observation dict."""
        self.sim.reset()
        self._done = False
        self._steps = 0
        self._apply_default_policy()

        # Prime with one run_for() call so metrics are populated.
        self._delta = self.sim.run_for(self.decision_interval_ns)
        return self._build_obs()

    def _apply_default_policy(self) -> None:
        """Apply the legacy default policy: AP0 on channel 0 at full power."""
        # Mute all channels first.
        for ch in range(self.n_channels):
            self.controller.set_tx_power_for_ap_channel(
                self.target_ap, ch, -100.0
            )
            self.controller.set_cca_for_ap(self.target_ap, self.cca_dbm)
        # Enable channel 0 at full power.
        self.controller.set_tx_power_for_ap_channel(
            self.target_ap, 0, self.pt_max_dbm
        )
        self._selected_channels = [0]
        self._tx_power_per_channel = {0: 1.0}
        self._cca_per_channel = {c: self.cca_dbm for c in range(self.n_channels)}

    def step(
        self,
        l1_action_index: int,
        l2_action_result,
        selected_channels: list[int],
        tx_power_per_channel: dict[int, float],
        cca_per_channel: dict[int, float],
    ) -> StepResult:
        """Apply one agent action triple, run one decision_interval.

        Returns StepResult with L1/L2/L3 states (for next step),
        reward, done flag, and info.
        """
        if self._done:
            return self._make_done_result()

        # 1. Apply actions via Controller.
        self._selected_channels = selected_channels
        self._tx_power_per_channel = tx_power_per_channel
        self._cca_per_channel = cca_per_channel

        # Apply CCA: all selected channels get their CCA.
        for ch, cca in cca_per_channel.items():
            self.controller.set_cca_for_ap(self.target_ap, cca)

        # Apply Tx power per channel.
        for ch in range(self.n_channels):
            p = tx_power_per_channel.get(ch, 0.0)
            if p <= 0.0:
                tx_dbm = -100.0
            else:
                import math
                tx_dbm = self.pt_max_dbm + 10.0 * math.log10(p)
            self.controller.set_tx_power_for_ap_channel(
                self.target_ap, ch, tx_dbm
            )

        # 2. Run one decision interval.
        self._delta = self.sim.run_for(self.decision_interval_ns)

        # 3. Compute reward.
        reward_result = self.reward_adapter.compute(self._delta)
        reward = reward_result.reward

        # 4. Check done condition (legacy: queue overflow or max steps).
        q_len = reward_result.queue_len
        self._done = q_len >= self.max_q_len
        self._steps += 1

        # 5. Build observation for next step.
        obs = self._build_obs()

        return StepResult(
            l1_state=obs["l1_state"],
            l2_state=obs["l2_state"],
            l3_states=obs["l3_states"],
            reward=reward,
            reward_result=reward_result,
            done=self._done,
            info={
                "throughput_mbps": reward_result.throughput_mbps,
                "queue_len": q_len,
                "collisions": reward_result.collisions,
                "retries": reward_result.retries,
                "drops": reward_result.drops,
                "latency_mean_us": reward_result.latency_mean_us,
                "latency_p95_us": reward_result.latency_p95_us,
                "steps": self._steps,
                "selected_channels": list(selected_channels),
            },
            selected_channels=selected_channels,
            tx_power_per_channel=tx_power_per_channel,
            cca_per_channel=cca_per_channel,
        )

    def _build_obs(self) -> dict:
        """Build L1/L2/L3 states from current delta and action state."""
        link_id = self.target_ap  # Sprint 3: link_id == ap_id
        l1 = self.obs_adapter.l1_state(
            self._delta, self._tx_power_per_channel, link_id
        )
        l2 = self.obs_adapter.l2_state(self._delta, self._selected_channels)
        l3 = self.obs_adapter.l3_state(
            self._delta, self._selected_channels,
            self._tx_power_per_channel, self._cca_per_channel
        )
        return {
            "l1_state": l1,
            "l2_state": l2,
            "l3_states": l3,
        }

    def l1_state(self) -> np.ndarray:
        """L1 state (for external use without step())."""
        return self._build_obs()["l1_state"]

    def l2_state(self) -> np.ndarray:
        """L2 state (for external use without step())."""
        return self._build_obs()["l2_state"]

    def l3_state(self) -> dict[int, np.ndarray]:
        """L3 states (for external use without step())."""
        return self._build_obs()["l3_states"]

    def _make_done_result(self) -> StepResult:
        """Return a zeroed result when episode is done."""
        return StepResult(
            l1_state=np.zeros((1, self.obs_adapter.l1_state_size)),
            l2_state=np.zeros((1, self.obs_adapter.l2_state_size)),
            l3_states={},
            reward=0.0,
            reward_result=None,  # type: ignore
            done=True,
            info={"done_reason": "overflow_or_max_steps"},
        )

    def apply_actions(
        self,
        selected_channels: list[int],
        tx_power_per_channel: dict[int, float],
        cca_per_channel: dict[int, float],
    ) -> None:
        """Apply actions without running the simulator (for the first step
        before the first run_for() call)."""
        self._selected_channels = selected_channels
        self._tx_power_per_channel = tx_power_per_channel
        self._cca_per_channel = cca_per_channel

        import math
        for ch, cca in cca_per_channel.items():
            self.controller.set_cca_for_ap(self.target_ap, cca)
        for ch in range(self.n_channels):
            p = tx_power_per_channel.get(ch, 0.0)
            if p <= 0.0:
                tx_dbm = -100.0
            else:
                tx_dbm = self.pt_max_dbm + 10.0 * math.log10(p)
            self.controller.set_tx_power_for_ap_channel(
                self.target_ap, ch, tx_dbm
            )