"""Discrete-event loop. All times in nanoseconds.

Events are scheduled with schedule(); the loop pops the earliest one, calls its
handler, and repeats until the queue empties or until the wall-clock budget
runs out.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Callable


@dataclass(order=True)
class Event:
    time_ns: int
    seq: int = field(compare=True)
    kind: str = field(compare=False)
    handler: Callable[[], None] = field(compare=False)


class EventLoop:
    def __init__(self) -> None:
        self._pq: list[Event] = []
        self._seq: int = 0
        self.now_ns: int = 0

    def schedule(self, time_ns: int, kind: str, handler: Callable[[], None]) -> None:
        if time_ns < self.now_ns:
            raise ValueError(
                f"schedule in past: now={self.now_ns} scheduled={time_ns} kind={kind}"
            )
        heapq.heappush(self._pq, Event(time_ns, self._seq, kind, handler))
        self._seq += 1

    def schedule_after(self, delta_ns: int, kind: str, handler: Callable[[], None]) -> None:
        self.schedule(self.now_ns + delta_ns, kind, handler)

    @property
    def has_events(self) -> bool:
        return bool(self._pq)

    def clear(self) -> None:
        """Clear all pending events and reset the clock."""
        self._pq.clear()
        self._seq = 0
        self.now_ns = 0

    def pop(self) -> Event:
        ev = heapq.heappop(self._pq)
        self.now_ns = ev.time_ns
        return ev

    def run_until_empty(self) -> None:
        while self._pq:
            self.pop().handler()

    def run_until(self, t_end_ns: int) -> None:
        while self._pq and self._pq[0].time_ns <= t_end_ns:
            self.pop().handler()
        if self._pq:
            self.now_ns = t_end_ns  # advance clock so future schedules are valid