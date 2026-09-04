"""Algorithm-agnostic Controller API.

The Controller is the **only** surface the algorithm sees. It exposes
controllable parameters (channel, Tx power, CCA threshold) at per-link or
per-channel granularity. The Controller writes to MacStation / ChannelState
state directly.

Usage:

    sim = Simulator(...)
    ctrl = Controller(sim)
    ctrl.set_tx_power(link_id=0, dbm=15.0)
    ctrl.set_cca(channel_id=0, dbm=-75.0)
    obs = ctrl.get_observation(ap_id=0)
    sim.run()

For Sprint 2, the Controller is not yet invoked per `decision_interval`.
It exposes setters that an outer loop (or the Legacy Adapter) can call
before / between runs. Per-interval invocation comes when a real RL agent
is plugged in.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from wifi_simulator.core.simulator import Simulator
    from wifi_simulator.mac.mac import MacStation


class Controller:
    """Per-link / per-channel control surface.

    The Controller owns no scheduler of its own; the caller (RL loop or
    Legacy Adapter) decides when to apply actions. setters take effect
    immediately on the underlying MacStation / ChannelState.
    """

    def __init__(self, sim: "Simulator") -> None:
        self.sim = sim

    # ---- setters -----------------------------------------------------

    def set_tx_power(self, link_id: int, dbm: float) -> None:
        """Set Tx power for a single link (AP+link).

        Equivalent to `set_tx_power_for_ap_channel(ap, channel, dbm)` when
        the link maps to one (ap, channel). Sprint 2: one link per AP.
        """
        for mac in self.sim.macs:
            if mac.link_id == link_id:
                mac.tx_power_dbm = dbm
                return
        raise KeyError(f"link_id {link_id} not found")

    def set_cca(self, channel_id: int, dbm: float) -> None:
        """Set CCA threshold (dBm) for ALL MACs on this channel.

        CCA is a per-receiver concept. In Sprint 2, all MACs on a given
        channel share the same CCA threshold (one global threshold per
        channel). When per-MAC CCA is needed, callers should set it
        directly on the MacStation.
        """
        for mac in self.sim.macs:
            if mac.channel_id == channel_id:
                mac.cca_threshold_dbm = dbm

    def set_cca_for_ap(self, ap_id: int, dbm: float) -> None:
        """Set CCA threshold (dBm) for a single AP's MAC."""
        for mac in self.sim.macs:
            if mac.ap_id == ap_id:
                mac.cca_threshold_dbm = dbm
                return
        raise KeyError(f"ap_id {ap_id} not found")

    def set_tx_power_for_ap_channel(self, ap_id: int, channel_id: int, dbm: float) -> None:
        """Set Tx power for the link of (ap, channel) — convenience for
        L1/L2-style power-per-channel control.
        """
        for mac in self.sim.macs:
            if mac.ap_id == ap_id and mac.channel_id == channel_id:
                mac.tx_power_dbm = dbm
                return
        raise KeyError(f"link for ap={ap_id}, channel={channel_id} not found")

    # ---- observation ------------------------------------------------

    def get_observation(self, ap_id: int) -> dict:
        """Return a flat observation dict for the algorithm.

        The set of keys is deliberately small for Sprint 2 — enough to drive
        the Legacy Adapter and a minimum decision policy.
        """
        mac = self._mac_for_ap(ap_id)
        return {
            "ap_id": ap_id,
            "link_id": mac.link_id,
            "channel_id": mac.channel_id,
            "tx_power_dbm": mac.tx_power_dbm,
            "cca_threshold_dbm": mac.cca_threshold_dbm,
            "queue_len": len(mac.queue),
            "retry_count": mac.retry_count,
            "backoff_counter": mac.backoff_counter,
            "tx_attempts": self.sim.metrics._lm(mac.link_id).tx_attempt_count,
            "success_count": self.sim.metrics._lm(mac.link_id).success_count,
            "collision_count": self.sim.metrics._lm(mac.link_id).collision_count,
        }

    def get_all_observations(self) -> dict[int, dict]:
        return {m.ap_id: self.get_observation(m.ap_id) for m in self.sim.macs}

    def _mac_for_ap(self, ap_id: int) -> "MacStation":
        for m in self.sim.macs:
            if m.ap_id == ap_id:
                return m
        raise KeyError(f"ap_id {ap_id} not found")
