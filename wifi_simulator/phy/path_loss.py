"""Path loss with cached (correlated) shadowing.

Legacy bug: legacy `rx_power` re-draws shadowing on every call -> per-call noise
that destroys link correlation. Here we draw shadowing once per (tx, rx) pair at
topology build and cache the value forever.
"""
from __future__ import annotations

import math
from typing import Tuple

from wifi_simulator.core.rng import Rng


# Defaults - match legacy Project_3 config.
FREQ_LOSS_DB_5GHZ: float = 40.0      # 5 GHz free-space-ish baseline
ALPHA: float = 3.5                   # path loss exponent
WALL_LOSS_DB: float = 5.0
SHADOWING_SIGMA_DB: float = 3.0


class PathLossModel:
    def __init__(
        self,
        rng: Rng,
        freq_loss_db: float = FREQ_LOSS_DB_5GHZ,
        alpha: float = ALPHA,
        wall_loss_db: float = WALL_LOSS_DB,
        shadowing_sigma_db: float = SHADOWING_SIGMA_DB,
    ) -> None:
        self._rng = rng
        self._freq = freq_loss_db
        self._alpha = alpha
        self._wall = wall_loss_db
        self._sigma = shadowing_sigma_db
        self._cache: dict[Tuple[int, int], float] = {}
        self._walls: dict[Tuple[int, int], int] = {}

    def set_wall_count(self, tx: int, rx: int, n_walls: int) -> None:
        """Record wall count for (tx, rx)."""
        self._walls[(tx, rx)] = n_walls

    def path_loss_db(self, tx: int, rx: int, distance_m: float) -> float:
        if distance_m <= 0:
            distance_m = 1e-3
        key = (tx, rx)
        if key not in self._cache:
            shadowing = self._rng.normal(0.0, self._sigma)
            walls = self._walls.get(key, 0)
            pl = (
                self._freq
                + 10.0 * self._alpha * math.log10(distance_m)
                + walls * self._wall
                + shadowing
            )
            self._cache[key] = pl
        return self._cache[key]

    def is_cached(self, tx: int, rx: int) -> bool:
        """Test helper: confirm shadowing is cached (called twice -> same value)."""
        return (tx, rx) in self._cache