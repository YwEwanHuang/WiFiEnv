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
        if channel_id not in self._by_channel:
            self._by_channel[channel_id] = ChannelState(channel_id=channel_id)
        return self._by_channel[channel_id]

    def get(self, channel_id: int) -> ChannelState:
        return self._by_channel[channel_id]

    def all_channels(self) -> list[int]:
        return list(self._by_channel.keys())
