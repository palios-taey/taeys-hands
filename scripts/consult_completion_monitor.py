#!/usr/bin/env python3
"""Standalone consult completion monitor (one process per display).

This is the EXISTING monitor detection wired into a runner that does not depend
on the (banned) engine. It reuses, unchanged:
  * the per-platform ``CompletionDetector`` (stop-seen-then-gone state machine),
  * the ``stop_button`` element from that platform's YAML (exact match),
  * ``taey-notify`` for the notification.

The archived ``monitor_daemon.py`` was one-shot and engine-launched (it hung at
construction standalone), so it could not simply be re-run; this runner supplies
the always-on poll loop the engine used to provide.

Watches ONE display's stop button every few seconds. On a seen->gone transition
(a generation finishing) it notifies Taey that the consult on that display is
complete, then resets to catch the next generation. Passive: it only reads the
tree and notifies — it never drives, never takes the display lock.

Usage: consult_completion_monitor.py <display-number>   e.g. 2
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time

REPO = "/home/mira/taeys-hands"
sys.path.insert(0, REPO)

# Standard Mira consult display -> platform map (primary + second set).
DISPLAY_PLATFORM = {
    "2": "chatgpt", "3": "claude", "4": "gemini", "5": "grok", "6": "perplexity",
    "21": "claude", "22": "gemini", "23": "grok", "24": "perplexity",
}
POLL_SECONDS = 3.0


def resolve_bus(display: str) -> str:
    r = subprocess.run(["xprop", "-display", display, "-root", "AT_SPI_BUS"],
                       capture_output=True, text=True)
    out = (r.stdout or "").strip()
    return out.split('= "', 1)[1].rstrip('"') if '= "' in out else ""


def load_detector(platform: str):
    mod = importlib.import_module(f"consultation_v2.platforms.{platform}.monitor")
    for name in dir(mod):
        if name.endswith("CompletionDetector"):
            return getattr(mod, name)
    raise RuntimeError(f"no CompletionDetector in {platform} monitor module")


def stop_button_present(platform: str) -> bool:
    from consultation_v2.snapshot import build_snapshot
    tup = build_snapshot(platform)
    snap = next(e for e in tup if hasattr(e, "mapped"))
    return bool(snap.mapped.get("stop_button"))


def notify_taey(message: str) -> None:
    subprocess.run(["taey-notify", "--type", "status", "--from", "consult-monitor",
                    "--", "taey", message], capture_output=True, text=True)


def new_detector(Detector):
    # 2-cycle debounce (deep-mode setting) so a single flickered stop-absent scan
    # never false-completes; the monitor does not know the per-consult mode.
    try:
        return Detector(mode="deep_research")
    except TypeError:
        return Detector()


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        log("usage: consult_completion_monitor.py <display-number>")
        return 2
    n = sys.argv[1].lstrip(":")
    display = f":{n}"
    platform = DISPLAY_PLATFORM.get(n)
    if not platform:
        log(f"[consult-monitor {display}] no platform mapped; refusing")
        return 2

    os.environ["DISPLAY"] = display
    os.environ["AT_SPI_BUS_ADDRESS"] = resolve_bus(display)
    Detector = load_detector(platform)
    det = new_detector(Detector)
    log(f"[consult-monitor {display} {platform}] started; watching stop_button every {POLL_SECONDS:.0f}s")

    while True:
        try:
            present = stop_button_present(platform)
            verdict = det.observe(present)
            if verdict == "complete":
                notify_taey(f"consult on {display} ({platform}) COMPLETE — stop button "
                            f"disappeared. Response ready to harvest.")
                log(f"[consult-monitor {display}] COMPLETE -> notified taey")
                det = new_detector(Detector)  # rearm for the next generation
        except Exception as e:  # firefox restart / empty tree / bus change — keep watching
            log(f"[consult-monitor {display}] scan_error {type(e).__name__}: {str(e)[:100]}")
            os.environ["AT_SPI_BUS_ADDRESS"] = resolve_bus(display)  # bus rotates on restart
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
