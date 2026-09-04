"""IEEE 802.11 timing constants (5 GHz OFDM, 20 MHz).

Values cited from IEEE 802.11-2016 §10.3.3 and §17.4.4.4 unless noted.

All values in nanoseconds (int) for fast integer arithmetic.

Notes:
- We do NOT differentiate 2.4 GHz vs 5 GHz in MVP; SLOT_TIME=9us is the OFDM slot
  for both. 2.4 GHz DSSS has a longer slot (20 us) — out of scope here.
- EIFS uses the legacy 6 Mbps ACK airtime baseline; this matches §10.3.3.
- PHY_RX_START_DELAY is the receiver turnaround; not used in Sprint 1 but kept
  for the timing constants contract.
"""
from __future__ import annotations


# --- 802.11 basic timing (ns) ---------------------------------------------

SLOT_TIME_NS: int = 9_000               # 9 us.  IEEE 802.11-2016 §10.3.3 (OFDM)
SIFS_NS: int = 16_000                   # 16 us. IEEE 802.11-2016 §10.3.3
DIFS_NS: int = SIFS_NS + 2 * SLOT_TIME_NS   # 34 us. Defined as SIFS + 2*slot.
EIFS_NS: int = SIFS_NS + DIFS_NS + (4 + 6) * 8 * 1_000_000 // 6_000_000  # ≈ 88 us
# ACK = 14 byte * 8 / 6e6 ≈ 18.7 us; use 20 us rounded
ACK_AIRTIME_US: int = 20                # 14-byte ACK at 6 Mbps + preamble (Sprint 1 fixed)
PREQ_ACK_TIMEOUT_NS: int = SIFS_NS + ACK_AIRTIME_US * 1_000   # SIFS + ACK duration

PHY_RX_START_DELAY_NS: int = 25_000    # 25 us.  IEEE 802.11-2016 §10.3.5.7


# --- 802.11 backoff (slot units) ------------------------------------------

CW_MIN: int = 15
CW_MAX: int = 1023
RETRY_LIMIT: int = 6                    # short retry limit (legacy-compatible)


def contention_window(retry: int, cw_min: int = CW_MIN, cw_max: int = CW_MAX) -> int:
    """Standard 802.11 contention window after `retry` collisions/failures.

    CW_r = min((CW_min + 1) * 2**r - 1, CW_max)

    Yields:
        r=0 → 15, r=1 → 31, r=2 → 63, r=3 → 127, r=4 → 255, r=5 → 511, r=7+ → 1023

    This is the IEEE 802.11-2016 §10.3.3 expression. Do NOT replace with
    `CW_min * 2**r` (that gives 15, 30, 60, 120, ... which is wrong).
    """
    if retry < 0:
        raise ValueError(f"retry must be >= 0, got {retry}")
    cw = (cw_min + 1) * (1 << retry) - 1
    return min(cw, cw_max)