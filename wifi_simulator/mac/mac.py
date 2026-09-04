"""Per-(AP, link) CSMA/CA state machine.

This is the heart of the simulator. States:

    IDLE         queue empty, waiting for packet
    DIFS_WAIT    waiting DIFS slots after channel went idle
                 (either before initial backoff OR after busy freeze)
    BACKOFF      decrementing backoff counter
    TX           transmitting (TX_END scheduled)
    ACK_WAIT     ACK expected at TX_END + SIFS (Sprint 1: ACK instantaneous)

Freeze/resume (IEEE 802.11 §10.3.4):
- BACKOFF + busy slot -> counter frozen, transition to DIFS_WAIT
- After busy ends + DIFS elapses -> resume frozen counter (no redraw)
- If counter reaches 0 during a backoff slot, immediately start TX.

Critical race-condition rule: when multiple MACs reach BO=0 in the same slot
boundary, they MUST start TX in the same slot and COLLIDE. The slot boundary
handler is responsible for snapshotting the channel's busy state BEFORE
processing any MAC, and registering new TXs AFTER all MACs have decided.

Each MacStation owns:
    - queue: PacketQueue
    - state, backoff_counter, retry_count, frozen_counter
    - current_packet (the head packet in flight)
    - tx_power_dbm (configurable)
    - cca_threshold_dbm (configurable)
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Callable, Optional

from wifi_simulator.core.rng import Rng
from wifi_simulator.mac.backoff import draw_backoff
from wifi_simulator.mac.timing import (
    CW_MAX,
    CW_MIN,
    DIFS_NS,
    RETRY_LIMIT,
    SIFS_NS,
    SLOT_TIME_NS,
)
from wifi_simulator.metrics.collector import MetricsCollector
from wifi_simulator.metrics.events import EventTrace
from wifi_simulator.network.queue import Packet, PacketQueue
from wifi_simulator.phy.airtime import approximate_packet_airtime_us
from wifi_simulator.phy.mcs import McsEntry, ideal_select
from wifi_simulator.phy.sinr import compute_sinr_db

if TYPE_CHECKING:
    from wifi_simulator.core.channel_registry import ChannelStateRegistry
    from wifi_simulator.core.channel_state import ChannelState
    from wifi_simulator.core.event_loop import EventLoop
    from wifi_simulator.phy.path_loss import PathLossModel


class MacState(Enum):
    IDLE = "IDLE"
    DIFS_WAIT = "DIFS_WAIT"
    BACKOFF = "BACKOFF"
    TX = "TX"
    ACK_WAIT = "ACK_WAIT"


class MacStation:
    """Per-(AP, link) CSMA/CA station."""

    def __init__(
        self,
        ap_id: int,
        link_id: int,
        sta_id: int,
        channel_id: int,
        rng: Rng,
        event_loop: "EventLoop",
        queue: PacketQueue,
        trace: EventTrace,
        metrics: MetricsCollector,
        channel_state: "ChannelState | ChannelStateRegistry",
        path_loss: "PathLossModel",
        get_distance_m: Callable[[int, int], float],
        tx_power_dbm: float = 18.0,
        cca_threshold_dbm: float = -82.0,
        noise_dbm: float = -95.0,
        retry_limit: int = RETRY_LIMIT,
        cw_min: int = CW_MIN,
        cw_max: int = CW_MAX,
        # MLO Feature Pack v0 — None for non-MLD MACs.
        mld_id: Optional[int] = None,
        mld_mode: str = "STR",
    ) -> None:
        self.ap_id = ap_id
        self.link_id = link_id
        self.sta_id = sta_id
        self.channel_id = channel_id
        self.rng = rng
        self.loop = event_loop
        self.queue = queue
        self.trace = trace
        self.metrics = metrics
        self.mld_id = mld_id
        self.mld_mode = mld_mode
        # ChannelStateRegistry (multi-BSS) or single ChannelState (Sprint 1).
        # MacStation always accesses its channel via `self.channel_state` so
        # the rest of the code is unchanged.
        if hasattr(channel_state, "get"):
            self.channel_state = channel_state.get(channel_id)
            self._registry = channel_state
        else:
            self.channel_state = channel_state
            self._registry = None
        self.path_loss = path_loss
        self.get_distance_m = get_distance_m
        self.tx_power_dbm = tx_power_dbm
        self.cca_threshold_dbm = cca_threshold_dbm
        self.noise_dbm = noise_dbm
        self.retry_limit = retry_limit
        self.cw_min = cw_min
        self.cw_max = cw_max

        self.state: MacState = MacState.IDLE
        self.backoff_counter: int = 0
        self.retry_count: int = 0
        # Frozen counter during busy period; None means no frozen counter.
        self.frozen_counter: Optional[int] = None
        # Wall-clock ns at which DIFS_WAIT completes (relative to which
        # we compare `now_ns >= difs_end_ns`). Initialized to 0; only valid
        # while state == DIFS_WAIT. Set when DIFS_WAIT starts or is reset.
        self.difs_end_ns: int = 0
        self.current_packet: Optional[Packet] = None
        self.current_mcs: Optional[McsEntry] = None
        self.current_tx_start_ns: int = 0
        self.current_tx_end_ns: int = 0
        # Pending TX start request from the slot planner.
        self.pending_tx_start: bool = False

    def reset(self) -> None:
        """Reset MAC state for a new episode (queue already cleared)."""
        self.state = MacState.IDLE
        self.backoff_counter = 0
        self.retry_count = 0
        self.frozen_counter = None
        self.difs_end_ns = 0
        self.current_packet = None
        self.current_mcs = None
        self.current_tx_start_ns = 0
        self.current_tx_end_ns = 0
        self.pending_tx_start = False

    # ---- MLO (Feature Pack v0) ---------------------------------------

    def is_active(self) -> bool:
        """True iff the MAC is currently using the radio (any non-IDLE state).

        Consulted by `MldTraffic` to decide whether to wake a peer MAC
        in `single_radio` / mutual-exclusion mode (the experimental
        simplified mode shipped with MLO v0 — see `MldConfig.mode`). STR
        MLDs do not consult this.
        """
        return self.state != MacState.IDLE

    # ---- packet arrival ------------------------------------------------

    def on_packet_arrival(self, now_ns: int) -> None:
        """Called when a packet is appended to this queue."""
        if self.state == MacState.IDLE:
            self._begin_difs_wait(now_ns)

    # ---- slot boundary (two-phase) ---------------------------------

    def plan_slot(self, now_ns: int, channel_busy_at_slot_start: bool) -> None:
        """Phase 1 of slot boundary: decide what to do, but do NOT start it.

        The simulator calls this for each MAC with the same
        `channel_busy_at_slot_start` value (the channel state at the START of
        the slot, BEFORE any MAC has started a new transmission). If this MAC
        wants to start a TX, it sets `self.pending_tx_start = True`.
        """
        if self.queue.is_empty and self.state in (MacState.IDLE, MacState.DIFS_WAIT):
            if self.state != MacState.IDLE:
                self.frozen_counter = None
                self.state = MacState.IDLE
            return
        if self.state in (MacState.TX, MacState.ACK_WAIT):
            return

        busy = channel_busy_at_slot_start

        if self.state == MacState.DIFS_WAIT:
            if busy:
                # Channel went busy during DIFS_WAIT; restart DIFS countdown
                self.difs_end_ns = now_ns + DIFS_NS
            elif now_ns >= self.difs_end_ns:
                # DIFS elapsed on an idle slot -> transition out
                if self.frozen_counter is not None and self.frozen_counter > 0:
                    self.backoff_counter = self.frozen_counter
                    self.frozen_counter = None
                    self.state = MacState.BACKOFF
                else:
                    self.frozen_counter = None
                    self._draw_backoff_and_begin(now_ns)

        elif self.state == MacState.BACKOFF:
            if busy:
                self.frozen_counter = self.backoff_counter
                self.state = MacState.DIFS_WAIT
                self.difs_end_ns = now_ns + DIFS_NS
            else:
                self.backoff_counter -= 1
                if self.backoff_counter <= 0:
                    self.frozen_counter = None
                    self.pending_tx_start = True

        # Emit CCA event for debugging
        self.trace.emit(now_ns, "CCA", ap_id=self.ap_id, link_id=self.link_id,
                        busy=busy)

    def commit_slot(self, now_ns: int) -> None:
        """Phase 2 of slot boundary: actually start the TX if pending."""
        if self.pending_tx_start:
            self.pending_tx_start = False
            self._start_tx(now_ns)

    # ---- TX end ----------------------------------------------------

    def on_tx_end(self, now_ns: int) -> None:
        """Evaluate TX outcome: collision / PER / failure."""
        if self.state != MacState.TX or self.current_packet is None:
            return

        my_tx = self.channel_state.finish_tx(self.ap_id, self.current_packet.packet_id)
        if my_tx is None:
            self.current_packet = None
            self.state = MacState.IDLE
            self._maybe_continue(now_ns)
            return

        # If this TX was pre-marked as collided at TX_START (because a peer
        # MAC started TX in the same slot), it is a collision regardless of
        # whether the peer TX is still in the active list. This handles the
        # case where one peer's TX_END fires first and removes its TX record.
        if my_tx.collided:
            self.current_packet.outcome = "FAIL_COLLISION"
            self.metrics.record_collision(self.link_id)
            self.trace.emit(now_ns, "COLLISION",
                            ap_id=self.ap_id, link_id=self.link_id,
                            packet_id=self.current_packet.packet_id,
                            reason="simultaneous_start")
            self._handle_failure(now_ns)
            return

        overlapping = self.channel_state.overlapping_others(
            self.ap_id, self.link_id,
            my_tx.start_ns, my_tx.end_ns,
        )

        d = self.get_distance_m(self.ap_id, self.sta_id)
        pl_db = self.path_loss.path_loss_db(self.ap_id, self.sta_id, d)
        signal_dbm = my_tx.tx_power_dbm - pl_db

        interf_dbm: list[float] = []
        for ot in overlapping:
            od = self.get_distance_m(ot.ap_id, self.sta_id)
            opl = self.path_loss.path_loss_db(ot.ap_id, self.sta_id, od)
            interf_dbm.append(ot.tx_power_dbm - opl)

        if overlapping:
            self.current_packet.outcome = "FAIL_COLLISION"
            self.metrics.record_collision(self.link_id)
            self.trace.emit(now_ns, "COLLISION",
                            ap_id=self.ap_id, link_id=self.link_id,
                            packet_id=self.current_packet.packet_id,
                            interferers=len(overlapping))
            self._handle_failure(now_ns)
            return

        sinr_db = compute_sinr_db(signal_dbm, interf_dbm, self.noise_dbm)
        mcs = ideal_select(sinr_db)
        per = 0.0 if sinr_db >= mcs.min_sinr_db else 1.0
        if per > 0:
            self.current_packet.outcome = "FAIL_PHY"
            self.metrics.record_fail_phy(self.link_id)
            self.trace.emit(now_ns, "TX_END",
                            ap_id=self.ap_id, link_id=self.link_id,
                            packet_id=self.current_packet.packet_id,
                            success=False, reason="PER")
            self._handle_failure(now_ns)
            return

        ack_time_ns = now_ns + SIFS_NS
        self.current_mcs = mcs
        self.state = MacState.ACK_WAIT
        def _on_ack() -> None:
            self._on_ack_success()
        self.loop.schedule(ack_time_ns, "ACK", _on_ack)

    # ---- internal helpers ---------------------------------------

    def _begin_difs_wait(self, now_ns: int) -> None:
        if self.queue.is_empty:
            self.state = MacState.IDLE
            self.frozen_counter = None
            return
        self.state = MacState.DIFS_WAIT
        # DIFS = 34 us (SIFS + 2*slot, 802.11-2016 §10.3.3). Stored as a
        # wall-clock target ns; not floor-rounded to whole slots. The
        # transition out of DIFS_WAIT happens on the first slot boundary at
        # or after `difs_end_ns` that observes an idle channel.
        self.difs_end_ns = now_ns + DIFS_NS
        self.frozen_counter = None

    def _draw_backoff_and_begin(self, now_ns: int) -> None:
        bo = draw_backoff(self.rng, self.retry_count, self.cw_min, self.cw_max)
        self.backoff_counter = bo
        self.state = MacState.BACKOFF
        self.frozen_counter = None
        self.trace.emit(now_ns, "BACKOFF",
                        ap_id=self.ap_id, link_id=self.link_id,
                        counter=bo, retry=self.retry_count)

    def _start_tx(self, now_ns: int) -> None:
        if self.queue.is_empty:
            self.state = MacState.IDLE
            return
        p = self.queue.peek()
        assert p is not None

        d = self.get_distance_m(self.ap_id, self.sta_id)
        pl_db = self.path_loss.path_loss_db(self.ap_id, self.sta_id, d)
        signal_dbm = self.tx_power_dbm - pl_db
        interf_dbm: list[float] = []
        sinr_db = compute_sinr_db(signal_dbm, interf_dbm, self.noise_dbm)
        mcs = ideal_select(sinr_db)

        airtime_us = approximate_packet_airtime_us(
            size_bytes=p.size_bytes,
            rate_mbps=mcs.rate_mbps,
            preamble_us=mcs.preamble_us,
        )
        airtime_ns = int(round(airtime_us * 1000))
        tx_end_ns = now_ns + airtime_ns

        self.current_packet = p
        self.current_mcs = mcs
        self.current_tx_start_ns = now_ns
        self.current_tx_end_ns = tx_end_ns
        self.state = MacState.TX

        self.channel_state.start_tx(
            self.ap_id, self.link_id, p.packet_id,
            now_ns, tx_end_ns, self.tx_power_dbm,
        )
        p.first_tx_time_ns = p.first_tx_time_ns or now_ns
        p.tx_count += 1
        self.metrics.record_tx_attempt(self.link_id)

        self.trace.emit(now_ns, "TX_START",
                        ap_id=self.ap_id, link_id=self.link_id,
                        packet_id=p.packet_id, size_bytes=p.size_bytes,
                        mcs=mcs.mcs_index, airtime_us=airtime_us)

        def _tx_end() -> None:
            self.on_tx_end(tx_end_ns)
        self.loop.schedule(tx_end_ns, "TX_END", _tx_end)

    def _handle_failure(self, now_ns: int) -> None:
        """Common path for collision / PER failure."""
        if self.current_packet is None:
            self.state = MacState.IDLE
            return
        self.retry_count += 1
        if self.retry_count > self.retry_limit:
            p = self.queue.pop()
            p.outcome = "DROP_RETRY_LIMIT"
            self.metrics.record_drop(p)
            self.trace.emit(now_ns, "DROP",
                            ap_id=self.ap_id, link_id=self.link_id,
                            packet_id=p.packet_id,
                            tx_attempts=p.tx_count)
            self.retry_count = 0
            self.current_packet = None
            self.state = MacState.IDLE
            self._maybe_continue(now_ns)
            return

        # Retry: re-arm DIFS+backoff
        self.metrics.record_retry(self.link_id)
        self.current_packet = None
        self.trace.emit(now_ns, "RETRY",
                        ap_id=self.ap_id, link_id=self.link_id,
                        retry=self.retry_count)
        self._begin_difs_wait(now_ns)

    def _on_ack_success(self) -> None:
        if self.state != MacState.ACK_WAIT or self.current_packet is None:
            return
        p = self.queue.pop()
        p.outcome = "SUCCESS"
        p.success_time_ns = self.loop.now_ns
        self.metrics.record_success(p)
        self.trace.emit(self.loop.now_ns, "ACK",
                        ap_id=self.ap_id, link_id=self.link_id,
                        packet_id=p.packet_id, success=True)
        self.retry_count = 0
        self.current_packet = None
        self.state = MacState.IDLE
        self._maybe_continue(self.loop.now_ns)

    def _maybe_continue(self, now_ns: int) -> None:
        if not self.queue.is_empty:
            self._begin_difs_wait(now_ns)