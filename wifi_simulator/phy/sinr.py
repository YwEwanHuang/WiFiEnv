"""SINR aggregation in the LINEAR power domain.

Legacy bug: legacy `channelCCAResult` adds interferer powers in dBm directly
(e.g., -60 dBm + -60 dBm -> "more negative dBm"). That is mathematically
incorrect.

Rule (enforced everywhere in the simulator):
  1. Convert each received power from dBm to linear (Watts).
  2. Sum interference in linear domain.
  3. Add noise in linear domain.
  4. Compute SINR_dB = 10 * log10(signal_W / (interference_W + noise_W)).
"""
from __future__ import annotations

import math
from typing import Iterable


def dbm_to_w(dbm: float) -> float:
    return 10 ** ((dbm - 30.0) / 10.0)


def w_to_dbm(w: float) -> float:
    if w <= 0:
        return -300.0
    return 10.0 * math.log10(w) + 30.0


def sum_powers_linear_w(dbm_list: Iterable[float]) -> float:
    """Sum powers in linear (W) domain. Returns linear W (not dBm)."""
    total_w = 0.0
    for dbm in dbm_list:
        total_w += dbm_to_w(dbm)
    return total_w


def thermal_noise_w(bw_hz: float, noise_figure_db: float = 9.0) -> float:
    """kT * BW * nf, where kT = -174 dBm/Hz at room temperature. Returns W."""
    kT_dbm_per_hz = -174.0
    bw_noise_dbm = kT_dbm_per_hz + 10.0 * math.log10(bw_hz)
    noise_dbm = bw_noise_dbm + noise_figure_db
    return dbm_to_w(noise_dbm)


def compute_sinr_db(
    signal_dbm: float,
    interferers_dbm: Iterable[float],
    noise_dbm: float,
) -> float:
    """Compute SINR in dB. Linear-domain sum of interferers + noise."""
    interf_w = sum_powers_linear_w(interferers_dbm)
    noise_w = dbm_to_w(noise_dbm)
    signal_w = dbm_to_w(signal_dbm)
    total_interf_plus_noise_w = interf_w + noise_w
    if signal_w <= 0:
        return -300.0
    sinr_linear = signal_w / total_interf_plus_noise_w
    if sinr_linear <= 0:
        return -300.0
    return 10.0 * math.log10(sinr_linear)