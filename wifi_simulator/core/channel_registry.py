"""Per-channel TX state registry.

For multi-BSS scenarios, each channel needs its own active-TX accounting.
ChannelStateRegistry maps channel_id -> ChannelState.

For a single-channel scenario, register a single channel (default id=0).
"""
from __future__ import annotations

from dataclasses import dataclass

from wifi_simulator.core.channel_state import ActiveTx, ChannelState


class ChannelStateRegistry:
    def __init__(self) -> None:
        self._by_channel: dict[int, ChannelState] = {}

    def register(self, channel_id: int) -> ChannelState:
        cs = self._by_channel.get(channel_id)
        if cs is None:
            cs = ChannelState(channel_id=channel_id)
            self._by_channel[channel_id] = cs
        return cs

    def get(self, channel_id: int) -> ChannelState:
        return self._by_channel[channel_id]

    def all_channels(self) -> list[int]:
        return list(self._by_channel.keys())
