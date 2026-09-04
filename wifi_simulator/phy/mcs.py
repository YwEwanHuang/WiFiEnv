"""Ideal MCS Selection.

A small MCS table indexed by min SINR. At TX_START we pick the highest MCS whose
min_sinr <= SINR_estimate_dB. This is the "Ideal MCS Selection" the design
allows for the Core.

In Sprint 1 we ship a single PHY mode (HE SU 20 MHz, MCS 0..11) with a fixed
preamble duration per MCS. Each row carries its source citation as a comment.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class McsEntry:
    mcs_index: int
    min_sinr_db: float
    rate_mbps: float        # data rate, MAC payload bits / second
    preamble_us: int         # HE-SU preamble at this MCS, fixed for 20 MHz


# HE-SU 20 MHz, 0.8us GI, single-user. IEEE 802.11ax Table 28-30.
# (Nss=1, 242-tone RU). Conservative min_sinr thresholds from
# IEEE 802.11ax sensitivity numbers + 10 dB fade margin.
HE_SU_20MHZ_MCS_TABLE: list[McsEntry] = [
    McsEntry(0,  -3.0,    8.6,  36),   # BPSK 1/2
    McsEntry(1,   2.0,   17.2,  36),   # QPSK 1/2
    McsEntry(2,   5.0,   25.8,  36),   # QPSK 3/4
    McsEntry(3,   9.0,   34.4,  36),   # 16-QAM 1/2
    McsEntry(4,  12.0,   51.6,  36),   # 16-QAM 3/4
    McsEntry(5,  16.0,   68.8,  36),   # 64-QAM 2/3
    McsEntry(6,  19.0,   77.4,  36),   # 64-QAM 3/4
    McsEntry(7,  22.0,   86.0,  36),   # 64-QAM 5/6
    McsEntry(8,  25.0,  103.2,  36),   # 256-QAM 3/4
    McsEntry(9,  27.0,  114.7,  36),   # 256-QAM 5/6
    McsEntry(10, 30.0,  129.0,  36),   # 1024-QAM 3/4
    McsEntry(11, 32.0,  143.4,  36),   # 1024-QAM 5/6
]

# Basic rate (legacy non-HT): 6 Mbps, BPSK 1/2, 20 us preamble.
BASIC_RATE_MBPS: float = 6.0
BASIC_PREAMBLE_US: int = 20


def ideal_select(sinr_db: float, table: list[McsEntry] | None = None) -> McsEntry:
    """Highest MCS whose min_sinr <= sinr_db. Returns the lowest MCS if SINR is very low."""
    table = table or HE_SU_20MHZ_MCS_TABLE
    chosen = table[0]
    for entry in table:
        if entry.min_sinr_db <= sinr_db:
            chosen = entry
        else:
            break
    return chosen


def basic_rate_entry() -> McsEntry:
    """A non-HT basic rate entry for ACK and broadcast frames."""
    return McsEntry(
        mcs_index=-1,
        min_sinr_db=-99.0,
        rate_mbps=BASIC_RATE_MBPS,
        preamble_us=BASIC_PREAMBLE_US,
    )