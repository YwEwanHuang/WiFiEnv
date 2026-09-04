"""Legacy Project_3 L1/L2/L3 hierarchical action adapter.

The legacy Project_3 env exposes:
  - L1: pick a channel subset (powerset of n_channels).
  - L2: Dirichlet power distribution over the selected channels.
  - L3: per-channel CCA threshold (dBm).

The new env exposes per-link Tx power and per-channel CCA. This adapter
translates (l1_subset, l2_power_dist_decimal, l3_cca_dict) into the new
Controller's API.

For Sprint 2 minimum, the adapter is invoked at startup only (no
decision_interval loop yet). The adapter:
  1. For each channel c in l1_subset: set the target AP's Tx power on c to
     pt_max * l2_power_dist[c] (in dBm-equivalent).
  2. For each channel c: set the CCA threshold to l3_cca_dict[c].
  3. Non-target APs (interferers) keep their default settings from
     `ApStation`.

Power mapping: legacy uses decimal power (e.g., 0.6 = 60 % of pt_max).
We map decimal p to dBm via `pt_max + 10*log10(p)` so that the actual
radiated power is the correct fraction. If p == 0 the channel is silent
(the legacy semantics: 0 power means "do not transmit on this channel").
"""
from __future__ import annotations

import math
from typing import Optional

from wifi_simulator.controllers.controller import Controller
from wifi_simulator.core.simulator import Simulator


class LegacyAdapter:
    """Wrap a Simulator as if it were a legacy Project_3 env.

    Use:
        sim = Simulator(...)
        adapter = LegacyAdapter(sim, target_ap=0, pt_max_dbm=20.0)
        adapter.apply_actions(l1_subset=[0], l2_power={0: 1.0}, l3_cca={0: -82.0, 1: -82.0, 2: -82.0})
        sim.run()

    The adapter does NOT start a decision_interval loop. It applies the
    actions once at startup. For an RL loop wrapping this adapter, the
    caller invokes `apply_actions(...)` and `controller.get_observation(...)`
    at each decision epoch.
    """

    def __init__(self, sim: Simulator, target_ap: int, pt_max_dbm: float = 20.0) -> None:
        self.sim = sim
        self.controller = Controller(sim)
        self.target_ap = target_ap
        self.pt_max_dbm = pt_max_dbm

    def apply_actions(
        self,
        l1_subset: list[int],
        l2_power: dict[int, float],
        l3_cca: dict[int, float],
    ) -> None:
        """Apply one (L1, L2, L3) action triple.

        l1_subset: list of channel ids the target AP should consider.
        l2_power: {channel_id: decimal in [0, 1]} summing to 1 over l1_subset.
                  A channel with power=0 is muted (no Tx).
        l3_cca: {channel_id: cca_threshold_dbm}.
        """
        # Per-channel CCA on the target AP only. Non-target APs keep their
        # own per-AP CCA.
        for ch, cca_dbm in l3_cca.items():
            self.controller.set_cca_for_ap(self.target_ap, cca_dbm)

        # Tx power on the target AP for each selected channel.
        for ch in l1_subset:
            p_dec = l2_power.get(ch, 0.0)
            if p_dec <= 0.0:
                # Legacy semantics: 0 power = "do not transmit on this
                # channel". Set tx power to a very low value so the AP
                # never starts a TX (effectively muted). We use -100 dBm
                # which is below any realistic CCA threshold.
                tx_dbm = -100.0
            else:
                # p_dec is a linear fraction of pt_max. Convert to dB
                # offset from pt_max so that radiated power = pt_max * p_dec.
                tx_dbm = self.pt_max_dbm + 10.0 * math.log10(p_dec)
            self.controller.set_tx_power_for_ap_channel(
                ap_id=self.target_ap, channel_id=ch, dbm=tx_dbm
            )

    def no_op(self) -> None:
        """Equivalent to legacy L1=empty, L2=zero, L3=all-default."""
        for mac in self.sim.macs:
            if mac.ap_id == self.target_ap:
                self.controller.set_tx_power_for_ap_channel(
                    ap_id=self.target_ap, channel_id=mac.channel_id, dbm=-100.0
                )

    def default_policy(self, channel: int = 0) -> None:
        """A simple default: target AP uses `channel` at full power, default
        CCA. Non-target APs keep their default settings.

        This is the minimum policy that lets both envs run on identical
        configuration for a side-by-side comparison.
        """
        # Mute all target AP links first.
        self.no_op()
        # Then enable the chosen channel at full power.
        self.controller.set_tx_power_for_ap_channel(
            ap_id=self.target_ap, channel_id=channel, dbm=self.pt_max_dbm
        )
