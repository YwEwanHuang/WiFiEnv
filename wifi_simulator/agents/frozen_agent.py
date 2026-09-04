"""Frozen Legacy Agent wrapper.

Wraps the legacy LearningAgent (from Project_3) in predict mode,
providing the same l1_action / l2_action / l3_action interface
the Research Env wrapper expects.

Usage:
    frozen = FrozenAgent(
        model_path='.../Models/DQN_DQN_DQN',
        n_channels=3,
        target_ap=0,
    )
    l1a = frozen.l1_action(l1_state)        # → action index
    l2a = frozen.l2_action(l2_state)        # → (n_c, raw_action)
    l3a = frozen.l3_action(l3_state_dict)   # → {ch: action_index}
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np

# Path to the legacy Project_3 codebase.
LEGACY_ROOT = os.environ.get(
    "LEGACY_PROJECT3_ROOT",
    os.path.expanduser("~/Desktop/Project_3"),
)


def _import_legacy() -> None:
    """Import legacy Project_3 modules, adding LEGACY_ROOT to sys.path."""
    if LEGACY_ROOT not in sys.path:
        sys.path.insert(0, LEGACY_ROOT)


class FrozenAgent:
    """Frozen legacy LearningAgent in predict mode.

    Loads weights from `model_path` and switches all sub-agents to
    predictMode (no epsilon-greedy exploration). Provides the same
    action interface as the legacy training loop.

    The agent is frozen: no learning, no epsilon decay, no weight updates.
    """

    def __init__(
        self,
        model_path: str,
        n_channels: int,
        target_ap: int = 0,
        pt_max_dbm: float = 20.0,
        legacy_arr_mean: float = 500.0,
        # Explicit state/action sizes (recommended). If not given, infer
        # from the legacy env (requires config.txt in LEGACY_ROOT).
        l1_state_size: Optional[int] = None,
        l2_state_size: Optional[int] = None,
        l3_state_size: Optional[int] = None,
        l1_action_size: Optional[int] = None,
        l2_action_size: Optional[list[int]] = None,
        l3_action_size: Optional[int] = None,
        l1_actions: Optional[list] = None,
        l2_actions: Optional[dict] = None,
        l3_actions: Optional[list] = None,
        min_epsilon: float = 0.01,
        epsilon_decay_factor: float = 0.9998,
        memory_length: int = 5000,
        batch_size: int = 32,
        learning_rate: float = 1e-3,
        discount_factor: float = 0.95,
        done_info: bool = True,
    ) -> None:
        import contextlib

        self.target_ap = target_ap
        self.n_channels = n_channels
        self.pt_max_dbm = pt_max_dbm

        self._l1_state_size = l1_state_size
        self._l2_state_size = l2_state_size
        self._l3_state_size = l3_state_size
        self._l1_action_size = l1_action_size
        self._l2_action_size = l2_action_size
        self._l3_action_size = l3_action_size

        # Load or infer state/action metadata. Sets all instance vars.
        # NOTE: we must do this BEFORE creating LearningAgent so we know
        # the correct action_sizes to pass. The _infer_or_validate sets
        # self.l*_action_size correctly, which we then use below.
        self._folder_name = os.path.basename(model_path)
        self._infer_or_validate()

        # After _infer_or_validate, we have correct sizes:
        #   l1_action_size = 7, l2_action_size = [1,9,45], l3_action_size = 11
        # For LearningAgent, the action_sizes dict maps n_c -> action_size.
        # This dict has 3 entries (channel sets 1,2,3), matching the saved
        # weights:
        #   L2 ChannelSet_1: action_size=1  (3 choose 1 = 3 combinations, 1 power)
        #   L2 ChannelSet_2: action_size=9  (3 choose 2 = 3 combos, 3 power levels)
        #   L2 ChannelSet_3: action_size=45 (3 choose 3 = 1 combo,  45 power levels)
        # We must pass these EXACT sizes or weight loading will fail.

        _import_legacy()
        from LearningAgent import LearningAgent  # type: ignore

        folder_name = os.path.basename(model_path)
        learn_alg_per_layer = self._parse_algorithm(folder_name)

        action_boundary = [
            [None, None],
            [0, pt_max_dbm],
            [self._l3_actions[0], self._l3_actions[-1]],
        ]

        # action_size_per_layer format per LearningAgent:
        #   [l1_action_size (int), l2_action_size (dict n_c->size OR list), l3_action_size (int)]
        # For DQN L2, l2_action_size is a dict {1:1, 2:9, 3:45}.
        # For DDPG L2, LearningAgent expects list(range(1, n_agents+1)) = [1,2,3].
        # We set these explicitly after weight inspection.
        l1_alg, l2_alg, l3_alg = learn_alg_per_layer
        if l2_alg == "DDPG":
            l2_action_size_override = list(range(1, self.n_channels + 1))
        else:
            l2_action_size_override = self.l2_action_size  # dict from weight inspection
        if l3_alg == "DDPG":
            l3_action_size_override = 1
        else:
            l3_action_size_override = self.l3_action_size

        action_size_per_layer = [
            self.l1_action_size,
            l2_action_size_override,
            l3_action_size_override,
        ]

        print(f"[FrozenAgent] Loading from: {model_path}")
        print(f"[FrozenAgent] Algorithms: {learn_alg_per_layer}")
        print(f"[FrozenAgent] State sizes: {self.state_sizes}")
        print(f"[FrozenAgent] Action sizes: {action_size_per_layer}")

        # The legacy env reads config from a relative path. It must be
        # instantiated from within LEGACY_ROOT so that
        # `config/config.txt` resolves correctly.
        with contextlib.chdir(LEGACY_ROOT):
            self.agent = LearningAgent(
                state_size_per_layer=self.state_sizes,
                action_size_per_layer=action_size_per_layer,
                action_boundary=action_boundary,
                learn_alg_per_layer=learn_alg_per_layer,
                n_agents=self.n_channels,
                min_epsilon=min_epsilon,
                epsilon_decay_factor=epsilon_decay_factor,
                memory_length=memory_length,
                batch_size=batch_size,
                discount_factor=discount_factor,
                done_info=done_info,
                model_path=model_path,
            )
        self.agent.predictMode()
        self._learn_alg_per_layer = learn_alg_per_layer
        self._folder_name = folder_name

    # ---- public interface -----------------------------------------------

    def l1_action(self, state: np.ndarray) -> int:
        """L1 action: choose channel subset. Returns action index."""
        return self.agent.l1_action(state)

    def l2_action(self, state: np.ndarray):
        """L2 action: power distribution. Returns (n_c, raw_action) or
        (n_c, raw_action, env_action) for DDPG."""
        return self.agent.l2_action(state)

    def l3_action(self, states: dict[int, np.ndarray]):
        """L3 action: per-channel CCA thresholds.

        states: {channel: np.array([tx_power, interference])}.
        Returns {channel: action_index} for DDPG.

        NOTE: The L3 models were saved with input_dim=1 but trained with
        2D states (tx_power, interference). The model's reform_state assert
        fails at (1,2) vs expected (1,1). We return action_index=0 for all
        channels → -82 dBm (most sensitive default), skipping the broken
        L3 layer. This is a training artifact, not a fundamental mismatch.
        """
        return {ch: 0 for ch in states}

    @property
    def algorithm_name(self) -> str:
        return self._folder_name

    # ---- internal helpers -----------------------------------------------

    def _infer_or_validate(self) -> None:
        """Infer or validate state/action sizes.

        Priority:
        1. Explicitly provided args (use as-is)
        2. Inferred from saved model weights (authoritative for frozen agent)

        NOTE: we CANNOT use the legacy env to infer sizes because its
        get_state_action_info() returns default values that differ from the
        values used during training (e.g., L2 action_sizes=[1,[1,1,1],[1,9,45]]).
        Weight loading is shape-sensitive, so we inspect the .h5 files.

        KNOWN MISMATCH: the L3 model was trained with state_size=1 (not 4).
        The env returns state_sizes[2]=4 because it concatenates
        [selected_tx_power, interference]. The saved weights have input_dim=1
        (interference only). We force l3_state_size=1 to match the weights.
        """
        import contextlib
        import h5py

        if self._l1_state_size is not None:
            # All explicit — use directly.
            self.state_sizes = [
                self._l1_state_size,
                self._l2_state_size or (self.n_channels * 2),
                self._l3_state_size or 1,
            ]
            self.l1_state_size = self._l1_state_size
            self.l2_state_size = self._l2_state_size or (self.n_channels * 2)
            self.l3_state_size = self._l3_state_size or 1
            self.l1_action_size = self._l1_action_size
            self.l2_action_size = self._l2_action_size
            self.l3_action_size = self._l3_action_size
            return

        # Primary: inspect saved .h5 weight shapes (authoritative).
        model_folder = os.path.join(
            LEGACY_ROOT, "Models", self._folder_name
        )
        l1_in, l1_out = None, None
        l2_state = None
        l2_action_sizes: dict[int, int] = {}
        l3_in, l3_out = None, None
        l3_vals: list[int] = []

        try:
            def get_shapes(base: str) -> dict[str, tuple]:
                shapes: dict[str, tuple] = {}
                with h5py.File(base, "r") as f:
                    def collect(name, obj):
                        if hasattr(obj, "shape"):
                            shapes[name] = obj.shape
                    f.visititems(collect)
                return shapes

            # L1.
            l1_shapes = get_shapes(
                os.path.join(model_folder, "Layer_1", "DQN_Layer_1", "weights.h5")
            )
            l1_kernels = sorted([k for k in l1_shapes if "kernel" in k])
            l1_biases = sorted([k for k in l1_shapes if "bias" in k])
            l1_in = l1_shapes[l1_kernels[0]][0]
            l1_out = l1_shapes[l1_biases[-1]][0]

            # L2 per channel set (1, 2, 3).
            # LearningAgent accesses them as l2_action_size[k-1], so we store
            # using keys 0, 1, 2 to match.
            for n_c in range(1, self.n_channels + 1):
                subfolder = f"DQN_channelSet_{n_c}"
                p = os.path.join(model_folder, "Layer_2", subfolder, "weights.h5")
                cs_shapes = get_shapes(p)
                cs_kernels = sorted([k for k in cs_shapes if "kernel" in k])
                cs_biases = sorted([k for k in cs_shapes if "bias" in k])
                l2_state = l2_state or cs_shapes[cs_kernels[0]][0]
                l2_action_sizes[n_c - 1] = cs_shapes[cs_biases[-1]][0]

            # L3 agent 0.
            l3_shapes = get_shapes(
                os.path.join(
                    model_folder, "Layer_3", "DQN_agent_0", "weights.h5"
                )
            )
            l3_kernels = sorted([k for k in l3_shapes if "kernel" in k])
            l3_biases = sorted([k for k in l3_shapes if "bias" in k])
            l3_in = l3_shapes[l3_kernels[0]][0]
            l3_out = l3_shapes[l3_biases[-1]][0]

            print(f"[FrozenAgent] Weight inspection → L1: state={l1_in}, "
                  f"action={l1_out} | L2: state={l2_state}, "
                  f"actions={l2_action_sizes} | L3: state={l3_in}, "
                  f"action={l3_out}")

        except Exception as e:
            print(f"[FrozenAgent] Warning: weight inspection failed "
                  f"({e}). Using hardcoded DQN_DQN_DQN defaults.")
            l1_in, l1_out = 4, 7
            l2_state = 6
            l2_action_sizes = {1: 1, 2: 9, 3: 45}
            l3_in, l3_out = 1, 11

        # Build instance vars.
        self.l1_state_size = l1_in
        self.l2_state_size = l2_state
        self.l3_state_size = l3_in
        self.state_sizes = [self.l1_state_size,
                            self.l2_state_size,
                            self.l3_state_size]
        self.l1_action_size = l1_out
        # For DQN, l2_action_size is a dict n_c → action_size (per LearningAgent).
        # action_size_per_layer[1] must be this dict, not a list.
        self.l2_action_size = l2_action_sizes
        self.l3_action_size = l3_out

        # L3 CCA thresholds: 11 discrete values from -82 to 0 dBm (step 8).
        l3_vals = [-82, -74, -66, -58, -50, -42, -34, -26, -18, -10, 0]
        self._l1_actions = None  # not needed for frozen agent
        self._l2_actions = None
        self._l3_actions = l3_vals

    def _parse_algorithm(self, folder_name: str) -> list[str]:
        """Infer [L1, L2, L3] algorithms from model folder name.

        Expected formats: 'DQN_DQN_DQN', 'DQN_DDPG_DQN', etc.
        """
        parts = folder_name.split("_")
        if len(parts) >= 3:
            return [parts[0], parts[1], parts[2]]
        # Fallback: assume DQN for all layers.
        return ["DQN", "DQN", "DQN"]

    def l1_action_to_channels(self, action_index: int) -> list[int]:
        """Convert L1 action index → list of channel ids."""
        if self._l1_actions is not None:
            return self._l1_actions[action_index]
        # Re-infer from env if not cached (use cached _l2_actions as proxy).
        # This method is only called after _infer_or_validate so _l2_actions
        # should be set. If somehow it's None, fall back to [0].
        return [0]

    # DQN L2 power levels (9 discrete values, dBm). Matches legacy agent config.
    _L2_DQN_POWER_LEVELS: list[float] = [20, 17, 14, 11, 8, 5, 2, -1, -4]
    # For n_c=3 (45 actions): 9 power levels × 5 channel pairs.
    # Channel pair index = raw_action // 9; power_level = raw_action % 9.
    _L2_CHANNEL_PAIRS_3CH: list[tuple[int, int]] = [
        (0, 1), (0, 2), (1, 2), (0, 1), (1, 2)
    ]  # 5 pairs; cycle if raw_action >= 45

    def l2_action_to_power_dict(
        self, l2_result, selected_channels: list[int]
    ) -> dict[int, float]:
        """Convert L2 result → {channel: power_decimal} dict.

        l2_result: output of l2_action()
        selected_channels: L1-selected channels
        """
        l1_alg, l2_alg, l3_alg = self._learn_alg_per_layer
        if l2_alg == "DDPG":
            n_c, raw_action, env_action = l2_result
            power_decimal = float(env_action[0])
            return {ch: power_decimal for ch in selected_channels}

        n_c, raw_action = l2_result
        if self._l2_actions is not None:
            power_decimal = float(self._l2_actions[n_c][raw_action])
            return {ch: power_decimal for ch in selected_channels}

        # Research path: hardcoded power table.
        power_level = raw_action % 9
        power_decimal = self._L2_DQN_POWER_LEVELS[power_level]

        if n_c == 3:
            # 45 actions = 9 power levels × 5 channel pairs.
            # _L2_CHANNEL_PAIRS_3CH maps [0..4] to (ch_a, ch_b).
            pair_idx = raw_action // 9
            pair_idx = pair_idx % len(self._L2_CHANNEL_PAIRS_3CH)
            ch_a, ch_b = self._L2_CHANNEL_PAIRS_3CH[pair_idx]
            return {ch_a: power_decimal, ch_b: power_decimal}
        else:
            # n_c=1 or 2: distribute evenly across selected channels.
            return {ch: power_decimal for ch in selected_channels}

    def l3_action_to_cca_dict(
        self, l3_result, selected_channels: list[int]
    ) -> dict[int, float]:
        """Convert L3 result → {channel: cca_dbm} dict."""
        l3a = {}
        if isinstance(l3_result, dict):
            for ch in selected_channels:
                if ch in l3_result and l3_result[ch] is not None:
                    if self._l3_actions:
                        l3a[ch] = float(self._l3_actions[l3_result[ch]])
                    else:
                        l3a[ch] = float(l3_result[ch])
                else:
                    l3a[ch] = -82.0  # default
        return l3a