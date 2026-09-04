"""Backoff draw helper.

BO is drawn UniformInt(0, CW_r) where CW_r follows IEEE 802.11-2016 §10.3.3:
    CW_r = min((CW_min + 1) * 2**r - 1, CW_max)
"""
from __future__ import annotations

from wifi_simulator.core.rng import Rng
from wifi_simulator.mac.timing import CW_MAX, CW_MIN, contention_window


def draw_backoff(rng: Rng, retry: int, cw_min: int = CW_MIN, cw_max: int = CW_MAX) -> int:
    """Draw a backoff counter. retry is the current retry count (0 = first attempt)."""
    cw = contention_window(retry, cw_min, cw_max)
    return rng.uniform_int(0, cw)