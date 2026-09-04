"""Approximate Packet Airtime.

This is NOT a precise IEEE 802.11 airtime calculation. The model:

    airtime_us = preamble_us + (size_bits / rate_mbps) * 1e6 / 1e6
                  = preamble_us + size_bits / rate_mbps

Ignored (deliberately; this is "Approximate", not "Exact"):

    - OFDM symbol rounding
    - SERVICE field bits
    - TAIL bits
    - padding
    - HE / EHT PPDU details
    - L-SIG, RL-SIG, HE-SIG-A/B/C overhead
    - GI / NGI specifics

Symbol rounding can be added later if it doesn't significantly increase
complexity. The principle: a simplified model is acceptable; the documentation
must state exactly what it computes. See RESEARCH_ENV_DESIGN.md §5.4.

Inputs:
        size_bytes: payload size in bytes (MAC SDU + MAC header, no FCS in this
                    approximate model)
        rate_mbps: data rate in Mbps
        preamble_us: preamble duration in microseconds

Output: airtime in microseconds (float).
"""
from __future__ import annotations


def approximate_packet_airtime_us(size_bytes: int, rate_mbps: float, preamble_us: int) -> float:
    if size_bytes < 0:
        raise ValueError(f"size_bytes must be >= 0, got {size_bytes}")
    if rate_mbps <= 0:
        raise ValueError(f"rate_mbps must be > 0, got {rate_mbps}")
    size_bits = 8 * size_bytes
    payload_us = size_bits / rate_mbps  # bits / (Mbps) = bits / (1e6 bits/s) = us
    return float(preamble_us + payload_us)