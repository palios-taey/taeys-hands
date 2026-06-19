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
    max, heavy}) use TWO stop-gone debounce scans; all other modes use one.
  * There is deliberately NO rendered-content freeze heuristic. Thinking/browse
    phases can keep text static while the stop button remains present. The stop
    button is the only completion oracle; a genuinely stuck run is bounded by the
    caller's overall timeout.

This is a per-monitor state machine driven by repeated ``observe()`` calls; the
caller (a driver's ``monitor_generation``) feeds it one fresh snapshot per poll
tick and stops when ``observe()`` returns a terminal verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Set

# Modes that get one extra stop-gone debounce scan before completion. Mirrors
# monitor/central.py::_detect_completion's required_stop_cycles==2 set.
DEEP_MODES: Set[str] = {
    "deep_research",
    "deep_think",
    "pro_extended",
    "extended_thinking",
    "max",
    "heavy",
}

# Verdicts returned by CompletionDetector.observe().
PENDING = "pending"          # still generating / waiting for stop transition
COMPLETE = "complete"        # stop seen then gone for required cycles


@dataclass
class CompletionDetector:
    """Stateful stop-transition completion detector.

    Construct once per generation, then call :meth:`observe` with a fresh
    snapshot each poll tick. ``mode`` selects the required stop-gone cycle count
    (deep modes need two).
    """

    mode: str = ""
    required_stop_cycles: int = field(init=False)
    ever_seen_stop: bool = field(default=False, init=False)
    stop_was_visible: bool = field(default=False, init=False)
    stop_cycles: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        normalized = (self.mode or "").strip().lower()
        self.required_stop_cycles = 2 if normalized in DEEP_MODES else 1

    def observe(self, stop_present: bool) -> str:
        """Advance the state machine by one poll tick.

        Args:
            stop_present: whether the stop button is in the CURRENT fresh scan.

        Returns PENDING or COMPLETE.
        """
        if stop_present:
            self.ever_seen_stop = True
            self.stop_was_visible = True
            # Stop is visible, so generation is active and the consecutive
            # absent-scan debounce counter resets.
            self.stop_cycles = 0
            return PENDING

        # Stop button absent on this scan.
        #
        # Completion = the stop button was SEEN (ever_seen_stop) and is now GONE,
        # DEBOUNCED across ``required_stop_cycles`` consecutive absent scans
        # (deep modes use 2, others 1). This is the present->gone transition of
        # 100_TIMES §1 ("stop-absent -> wait -> re-scan fresh tree -> complete
        # only if STILL absent"), generalised to N consecutive absent scans for
        # conservative AT-SPI refresh debounce on long-running modes.
        if not self.ever_seen_stop:
            # Never seen the stop button yet — cannot complete. NO content
            # fallback (100_TIMES §1: stop never appeared -> STOP and RAISE).
            return PENDING

        self.stop_was_visible = False
        self.stop_cycles += 1
        if self.stop_cycles >= self.required_stop_cycles:
            return COMPLETE
        return PENDING
