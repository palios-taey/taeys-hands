"""Shared completion detector for consultation_v2 drivers.

SINGLE SOURCE OF TRUTH for "the response is done". Mirrors
``monitor/central.py::_detect_completion`` (the canonical detector) so the
in-process driver poll and the out-of-process central monitor agree on the
exact same stop-transition semantics:

  * ``ever_seen_stop`` is sticky — completion is only ever declared AFTER the
    stop button has been observed at least once. A scan that never sees the
    stop button can never "complete" (no content-guess fallback — 100_TIMES
    §1: "If the stop button never appears -> STOP and RAISE").
  * Completion = stop button present -> gone TRANSITION (debounced): a single
    stop-absent scan after ever_seen is not enough; it must stay absent for
    ``required_stop_cycles`` consecutive scans.
  * Deep modes ({deep_research, deep_think, pro_extended, extended_thinking,
    heavy}) require TWO stop-gone cycles (the spinner can briefly drop the stop
    button mid-run); all other modes require one.
  * Hang detection: while the stop button is still present but the rendered
    content count has not changed for ``HANG_TICKS`` ticks, the generation is
    SUSPECTED HUNG. We never auto-complete on a hang (that would false-complete
    a frozen run) — the caller decides whether to keep waiting or surface it.

This is a per-monitor state machine driven by repeated ``observe()`` calls; the
caller (a driver's ``monitor_generation``) feeds it one fresh snapshot per poll
tick and stops when ``observe()`` returns a terminal verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set

# Modes that briefly drop the stop button mid-run (multi-phase / heavy
# reasoning), so a single stop-gone scan is not trusted as completion. Mirrors
# monitor/central.py::_detect_completion's required_stop_cycles==2 set.
DEEP_MODES: Set[str] = {
    "deep_research",
    "deep_think",
    "pro_extended",
    "extended_thinking",
    "heavy",
}

# Number of consecutive ticks the rendered content count may stay frozen while
# the stop button is still present before the run is SUSPECTED hung. Mirrors
# monitor/central.py::HANG_TICKS.
HANG_TICKS = 30

# Verdicts returned by CompletionDetector.observe().
PENDING = "pending"          # still generating / waiting for stop transition
COMPLETE = "complete"        # stop seen then gone for required cycles
HANG_SUSPECTED = "hang"      # stop present + content frozen >= HANG_TICKS


@dataclass
class CompletionDetector:
    """Stateful stop-transition completion detector.

    Construct once per generation, then call :meth:`observe` with a fresh
    snapshot each poll tick. ``mode`` selects the required stop-gone cycle count
    (deep modes need two). ``stop_key`` / ``content_count`` let the caller
    decouple from a specific Snapshot type — it passes the booleans/ints it
    already has.
    """

    mode: str = ""
    required_stop_cycles: int = field(init=False)
    ever_seen_stop: bool = field(default=False, init=False)
    stop_was_visible: bool = field(default=False, init=False)
    stop_cycles: int = field(default=0, init=False)
    last_content_count: Optional[int] = field(default=None, init=False)
    frozen_ticks: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        normalized = (self.mode or "").strip().lower()
        self.required_stop_cycles = 2 if normalized in DEEP_MODES else 1

    def observe(self, stop_present: bool, content_count: Optional[int] = None) -> str:
        """Advance the state machine by one poll tick.

        Args:
            stop_present: whether the stop button is in the CURRENT fresh scan.
            content_count: optional rendered-element count for hang detection.
                When omitted, hang detection is disabled (stop-only mode).

        Returns one of PENDING / COMPLETE / HANG_SUSPECTED.
        """
        if stop_present:
            self.ever_seen_stop = True
            self.stop_was_visible = True
            # Stop is back (or still) visible — generation is active, so reset
            # the consecutive-absent debounce counter. A transient mid-run drop
            # followed by a re-show can therefore never combine with a later
            # real drop to false-complete a deep run.
            self.stop_cycles = 0
            # Hang detection: content frozen while stop still showing.
            if content_count is not None and content_count == self.last_content_count:
                self.frozen_ticks += 1
            else:
                self.frozen_ticks = 0
            self.last_content_count = content_count
            if (
                content_count is not None
                and self.frozen_ticks >= HANG_TICKS
            ):
                return HANG_SUSPECTED
            return PENDING

        # Stop button absent on this scan.
        #
        # Completion = the stop button was SEEN (ever_seen_stop) and is now GONE,
        # DEBOUNCED across ``required_stop_cycles`` consecutive absent scans
        # (deep modes need 2, others 1). This is the present->gone transition of
        # 100_TIMES §1 ("stop-absent -> wait -> re-scan fresh tree -> complete
        # only if STILL absent"), generalised to N consecutive absent scans for
        # the multi-phase deep modes whose spinner can briefly drop the stop
        # button between phases.
        #
        # NOTE vs monitor/central.py: central's literal Redis state machine only
        # advances its cycle counter on a scan that immediately follows a
        # stop-VISIBLE scan, so its 2-cycle gate relies on the deep-mode UI
        # re-showing the stop button between phases. The in-process driver poll
        # is faster (1s vs central's 2s) and can sample two consecutive
        # absent-scans through a brief re-show, so we debounce on consecutive
        # absent scans instead — same INTENT (a single transient stop-drop never
        # completes a deep run), without depending on catching the re-show.
        if not self.ever_seen_stop:
            # Never seen the stop button yet — cannot complete. NO content
            # fallback (100_TIMES §1: stop never appeared -> STOP and RAISE).
            return PENDING

        self.stop_was_visible = False
        self.stop_cycles += 1
        if self.stop_cycles >= self.required_stop_cycles:
            return COMPLETE
        return PENDING
