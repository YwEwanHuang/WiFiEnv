"""Per-channel busy/idle accounting and TX overlap detection.

A ChannelState tracks active transmissions on a single channel. It answers:

- is_busy(now_ns): True if any TX is currently active on this channel
- overlapping_tx(now_ns, window_start, window_end): list of (ap_id, [start,end])
  pairs whose airtime overlaps the given window. Used to detect collisions
  after TX_END.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActiveTx:
    ap_id: int
    link_id: int
    packet_id: int
    start_ns: int
    end_ns: int
    tx_power_dbm: float
    # Set at commit_slot if multiple MACs started TX simultaneously in the
    # same slot. All such TXs are pre-marked as collided.
    collided: bool = False


class ChannelState:
    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id
        self._active: list[ActiveTx] = []
        # Cumulative busy ns of completed TXs (used for utilization).
        self._busy_ns_total: int = 0

    def start_tx(self, ap_id: int, link_id: int, packet_id: int,
                 start_ns: int, end_ns: int, tx_power_dbm: float) -> None:
        self._active.append(ActiveTx(ap_id, link_id, packet_id,
                                     start_ns, end_ns, tx_power_dbm))

    def mark_collisions_at_slot(self, slot_start_ns: int) -> None:
        """Mark all active TXs that started in this slot boundary as collided.

        Called by the simulator after commit_slot has registered all new TXs
        for this slot. Any pair of TXs that started simultaneously in the same
        slot is a collision; both must report FAIL_COLLISION. We pre-mark
        them so that whichever TX_END fires first can pull its own TX without
        erasing the collision evidence for the peer.
        """
        same_slot = [at for at in self._active if at.start_ns == slot_start_ns]
        if len(same_slot) > 1:
            for at in same_slot:
                at.collided = True

    def finish_tx(self, ap_id: int, packet_id: int) -> ActiveTx | None:
        for i, at in enumerate(self._active):
            if at.ap_id == ap_id and at.packet_id == packet_id:
                # Accumulate this TX's busy duration before removing.
                self._busy_ns_total += max(0, at.end_ns - at.start_ns)
                return self._active.pop(i)
        return None

    def is_busy(self, now_ns: int, exclude_ap: int | None = None) -> bool:
        """Legacy helper (kept for compatibility). True if any TX covers now_ns."""
        for at in self._active:
            if exclude_ap is not None and at.ap_id == exclude_ap:
                continue
            if at.start_ns <= now_ns < at.end_ns:
                return True
        return False

    def is_busy_at(self, now_ns: int, exclude_ap: int | None = None) -> bool:
        """Busy at the START of a slot — only counts TXs that started STRICTLY
        before now_ns. Used during slot-boundary processing so that TXs starting
        in the current slot don't count as already-on for other MACs.
        """
        for at in self._active:
            if exclude_ap is not None and at.ap_id == exclude_ap:
                continue
            if at.start_ns < now_ns and at.end_ns > now_ns:
                return True
        return False

    def active_rx_powers_dbm(self, now_ns: int, rx_pos: tuple[float, float],
                             exclude_ap: int) -> list[float]:
        """Return received-power dBm at rx for all currently-active TXs.

        Used to compute aggregate interference at a receiver. Distance-based
        path loss is applied via PathLossModel in the simulator; this method
        just exposes the *Tx* state.
        """
        raise NotImplementedError("Use Simulator.active_rx_powers_dbm() instead.")

    def overlapping_others(self, this_ap: int, this_link: int,
                         window_start: int, window_end: int) -> list[ActiveTx]:
        """Other (ap, link) TXs whose [start, end] overlaps the given window."""
        out = []
        for at in self._active:
            if at.ap_id == this_ap and at.link_id == this_link:
                continue
            if at.end_ns <= window_start or at.start_ns >= window_end:
                continue
            out.append(at)
        return out

    def prune_before(self, t_ns: int) -> None:
        """Drop TXs that ended before t_ns to keep the active list short."""
        self._active = [at for at in self._active if at.end_ns >= t_ns]

    def utilization(self, sim_duration_ns: int, now_ns: int | None = None) -> float:
        """Channel utilization in [0, 1]: fraction of sim time the channel
        was busy with TXs. `now_ns` is the simulation clock used to
        account for any TX still in flight at sim end."""
        if sim_duration_ns <= 0:
            return 0.0
        busy = self._busy_ns_total
        if now_ns is not None:
            for at in self._active:
                busy += max(0, now_ns - at.start_ns)
        return busy / sim_duration_ns