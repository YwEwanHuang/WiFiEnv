"""Per-(AP, link) FIFO queue with packet identities.

Each packet carries:
    packet_id       unique within the simulation
    src, dst        device ids
    link_id         the link it is queued on
    size_bytes      payload bytes (MAC SDU + MAC header in Sprint 1)
    enq_time_ns     time the packet entered the queue
    first_tx_time_ns time of first transmission attempt (None until first TX)
    tx_count        number of transmission attempts
    outcome         None / "SUCCESS" / "FAIL_PHY" / "FAIL_COLLISION" /
                    "FAIL_NO_ACK" / "DROP_RETRY_LIMIT"
    success_time_ns time of successful delivery
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional


@dataclass
class Packet:
    packet_id: int
    src: int
    dst: int
    link_id: int
    size_bytes: int
    enq_time_ns: int
    first_tx_time_ns: Optional[int] = None
    tx_count: int = 0
    outcome: Optional[str] = None
    success_time_ns: Optional[int] = None

    @property
    def latency_ns(self) -> int:
        if self.success_time_ns is None:
            return 0
        return self.success_time_ns - self.enq_time_ns


class PacketQueue:
    """FIFO queue for a single (ap, link)."""

    def __init__(self, ap_id: int, link_id: int) -> None:
        self.ap_id = ap_id
        self.link_id = link_id
        self._q: Deque[Packet] = deque()
        self.next_id: int = 0

    def enqueue(self, src: int, dst: int, size_bytes: int, now_ns: int) -> Packet:
        pid = self.next_id
        self.next_id += 1
        p = Packet(
            packet_id=pid,
            src=src,
            dst=dst,
            link_id=self.link_id,
            size_bytes=size_bytes,
            enq_time_ns=now_ns,
        )
        self._q.append(p)
        return p

    def peek(self) -> Optional[Packet]:
        return self._q[0] if self._q else None

    def pop(self) -> Packet:
        return self._q.popleft()

    def __len__(self) -> int:
        return len(self._q)

    @property
    def is_empty(self) -> bool:
        return not self._q