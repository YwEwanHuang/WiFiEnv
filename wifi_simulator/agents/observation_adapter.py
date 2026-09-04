"""Map Research Env metrics → Legacy L1 / L2 / L3 state format.

Legacy L1 state size: 1 + n_channels (Queue + per-channel interference dBm magnitude)
Legacy L2 state size: n_channels * 2 (interference + selected-channel mask)
Legacy L3 state size: 2 per agent (Tx power + interference on that channel)

Research delta metrics contain: per-link success/collision/retry/drop/queue_len.

For L1: we need queue_len[target_ap] + last_I_per_channel[ap].
We approximate "last interference on channel" as the collision count observed
in the last epoch — a proxy for cross-traffic on that channel.

For L3 per channel c: state = [tx_power_dbm, interference_proxy].
Interference proxy = collision_count_delta (higher collisions → more interferers).
"""
from __future__ import annotations

import numpy as np
from typing import Optional

# Legacy interference values are stored in dBm (e.g., -60 dBm).
# We need a mapping from collision count → approximate interference dBm.
# Strategy: map 0 collisions → quiet (I ≈ 0), more collisions → I ≈ −70 dBm.
# This is a heuristic; the agent learns to react to the relative pattern.
_COLLISION_TO_I_DBM = {
    0: -100.0,   # no collisions → channel is clear
    1: -75.0,
    2: -68.0,
    3: -63.0,
    4: -59.0,
    5: -56.0,
}


def _collisions_to_I(collisions: int) -> float:
    """Map collision count in epoch to approximate interference dBm."""
    if collisions <= 0:
        return -100.0
    keys = sorted(_COLLISION_TO_I_DBM.keys())
    for k in keys:
        if collisions <= k:
            return _COLLISION_TO_I_DBM[k]
    return _COLLISION_TO_I_DBM[keys[-1]]


class ObservationAdapter:
    """Adapt Research Env observations to legacy LearningAgent input.

    The legacy LearningAgent has 3 layers:
        L1: 1 + n_channels  →  queue + per-channel interference
        L2: n_channels * 2  →  interference + selected-channel mask
        L3: dict[channel] → [tx_power, interference] (per channel agent)

    Usage:
        adapter = ObservationAdapter(n_channels=3, target_ap=0)
        l1_state = adapter.l1_state(delta_metrics, tx_power_dbm_per_channel)
        l2_state = adapter.l2_state(delta_metrics, l1_action_channels)
        l3_state = adapter.l3_state(delta_metrics, l1_action_channels,
                                     current_cca_dbm_per_channel)
    """

    def __init__(self, n_channels: int, target_ap: int,
                 max_q_len: int = 16000, init_q_len: int = 8000) -> None:
        self.n_channels = n_channels
        self.target_ap = target_ap
        self.max_q_len = max_q_len
        self.init_q_len = init_q_len
        self.l1_state_size = 1 + n_channels
        self.l2_state_size = n_channels * 2
        self.l3_state_size = 2  # per-agent: [tx_power, interference]

    def l1_state(self, delta: dict, tx_power_per_channel: dict[int, float],
                 link_id: int) -> np.ndarray:
        """L1 state: normalized queue length + per-channel interference magnitude.

        delta: one epoch's delta metrics from Simulator.run_for()
        tx_power_per_channel: {channel: tx_power_dbm} — for collision proxy
        link_id: maps to ap_id (Sprint 3: link_id == ap_id)
        ap_id = link_id
        """
        ap_id = link_id
        q_len = delta.get("queue_len", {}).get(ap_id, self.init_q_len)
        q_norm = min(q_len, self.max_q_len) * 100.0 / self.max_q_len
        per_link = delta.get("delta", {}).get("per_link", {})
        l1_data = [q_norm]
        for ch in range(self.n_channels):
            col = 0
            # All APs on the same channel share collision signal.
            # Use system-wide collisions as interference proxy.
            sys_col = per_link.get(ap_id, {}).get("collision", 0)
            col = sys_col
            I = abs(_collisions_to_I(col))
            l1_data.append(I)
        return np.array(l1_data).reshape(1, -1)

    def l2_state(self, delta: dict,
                 selected_channels: list[int]) -> np.ndarray:
        """L2 state: interference on each channel + selected-channel binary mask.

        selected_channels: list of channel ids chosen by L1 action.
        """
        per_link = delta.get("delta", {}).get("per_link", {})
        ap_id = self.target_ap
        col = per_link.get(ap_id, {}).get("collision", 0)
        I = abs(_collisions_to_I(col))
        ch_interference = [I] * self.n_channels
        # Binary mask for selected channels.
        mask = [1.0 if c in selected_channels else 0.0
                for c in range(self.n_channels)]
        return np.array(ch_interference + mask).reshape(1, -1)

    def l3_state(self, delta: dict, selected_channels: list[int],
                 tx_power_per_channel: dict[int, float],
                 cca_per_channel: dict[int, float]) -> dict[int, np.ndarray]:
        """L3 state: per-channel agent state dict.

        Returns {channel: np.array([tx_power, interference])}.
        Channels not in selected_channels return None (agent doesn't act).
        """
        per_link = delta.get("delta", {}).get("per_link", {})
        ap_id = self.target_ap
        col = per_link.get(ap_id, {}).get("collision", 0)
        I = abs(_collisions_to_I(col))
        result = {}
        for ch in selected_channels:
            tx = tx_power_per_channel.get(ch, 0.0)
            result[ch] = np.array([tx, I]).reshape(1, -1)
        return result