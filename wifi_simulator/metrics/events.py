"""Event trace: append-only log of CSMA/CA events.

This is the SINGLE debugging instrument for Sprint 1. No telemetry framework.

Each event has:
    time_ns, kind, ap_id, link_id, **kwargs

Kinds:
    CCA           slot boundary CCA result (channel, busy)
    BACKOFF       new backoff counter drawn (counter)
    TX_START      packet started transmission (packet_id, size_bytes, mcs)
    TX_END        packet finished transmission (packet_id, success)
    COLLISION     TX_END found overlapping TXs on same channel
    ACK           ACK expected (packet_id, success)
    RETRY         packet going to retry (packet_id, retry_count)
    DROP          packet dropped after retry limit (packet_id)
"""
from __future__ import annotations

from typing import IO, Any


class EventTrace:
    def __init__(self, sink: IO[str] | None = None) -> None:
        self._sink = sink
        self._buf: list[str] = []

    def emit(self, time_ns: int, kind: str, ap_id: int = -1, link_id: int = -1, **kw: Any) -> None:
        extras = " ".join(f"{k}={v}" for k, v in kw.items())
        line = f"{time_ns:>12d} {kind:<10s} ap={ap_id} link={link_id} {extras}".rstrip()
        self._buf.append(line)
        if self._sink is not None:
            self._sink.write(line + "\n")

    def lines(self) -> list[str]:
        return list(self._buf)