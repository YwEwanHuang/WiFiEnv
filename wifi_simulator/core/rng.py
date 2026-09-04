"""Seeded RNG. One Generator per run; everything stochastic reads from it."""
from __future__ import annotations

import numpy as np


class Rng:
    """Thin wrapper around numpy.random.Generator with the calls the simulator needs."""

    def __init__(self, seed: int) -> None:
        self._g = np.random.default_rng(seed)

    def uniform_int(self, low: int, high_inclusive: int) -> int:
        """Uniform integer in [low, high_inclusive]. high_inclusive < low raises."""
        if high_inclusive < low:
            raise ValueError(f"uniform_int: high<low ({high_inclusive}<{low})")
        return int(self._g.integers(low, high_inclusive + 1))

    def uniform(self) -> float:
        """Uniform in [0, 1)."""
        return float(self._g.random())

    def exponential(self, mean: float) -> float:
        """Exponential with given mean (seconds)."""
        return float(self._g.exponential(mean))

    def normal(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        return float(self._g.normal(mu, sigma))