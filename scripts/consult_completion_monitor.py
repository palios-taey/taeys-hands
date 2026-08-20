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
(a generation finishing) it notifies Taey and the requester recorded on the
active consultation, then resets to catch the next generation. Passive: it only
reads the tree and coordination record and notifies — it never drives.

Usage: consult_completion_monitor.py <display-number>   e.g. 2
"""
from __future__ import annotations

import importlib
import json
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
    # The stop control is named per-platform: ChatGPT maps stop_streaming_button /
    # stop_answering_button, others map stop_button. Read the platform's declared
    # workflow.monitor.stop_keys (fallback stop_button) instead of hardcoding one key,
    # or ChatGPT completion is never detected.
    from consultation_v2.snapshot import build_snapshot
    from consultation_v2.yaml_contract import load_platform_yaml
    cfg = load_platform_yaml(platform)
    stop_keys = (((cfg.get("workflow") or {}).get("monitor") or {}).get("stop_keys")
                 or ["stop_button"])
    tup = build_snapshot(platform)
    snap = next(e for e in tup if hasattr(e, "mapped"))
    return any(snap.mapped.get(k) for k in stop_keys)


def active_completion_routes(platform: str, display: str) -> list[dict[str, str]]:
    from storage.redis_pool import get_client

    client = get_client()
    routes: list[dict[str, str]] = []
    for set_key in client.scan_iter(match="taey:*:active_session_ids"):
        for session_key in client.smembers(set_key):
            raw = client.get(session_key)
            if not raw:
                continue
            record = json.loads(raw)
            if not isinstance(record, dict) or record.get("platform") != platform:
                continue
            registered_display = str(record.get("display") or "")
            if registered_display != display:
                continue
            routes.append({
                "monitor_id": str(record.get("monitor_id") or ""),
                "requester": str(record.get("requester") or ""),
                "url": str(record.get("url") or ""),
            })
    if len(routes) > 1:
        monitor_ids = sorted(route["monitor_id"] for route in routes)
        raise RuntimeError(
            f"multiple active consultations claim {display}: {monitor_ids}"
        )
    return routes


def notify_taey(message: str, platform: str, display: str) -> tuple[list[str], list[str]]:
    targets = {"taey"}
    targets.update(
        target.strip()
        for target in os.environ.get("CONSULT_MONITOR_NOTIFY", "").split(",")
        if target.strip()
    )
    route_error = ""
    routes: list[dict[str, str]] = []
    try:
        routes = active_completion_routes(platform, display)
    except Exception as exc:
        route_error = f"active-session route lookup failed: {type(exc).__name__}: {exc}"
    targets.update(
        route["requester"]
        for route in routes
        if route["requester"] and route["requester"] != "unknown"
    )

    monitor_ids = sorted({route["monitor_id"] for route in routes if route["monitor_id"]})
    routed_message = message
    if monitor_ids:
        routed_message += f" monitor_ids={','.join(monitor_ids)}"
    if route_error:
        routed_message += f" ROUTE_ERROR={route_error}"

    failures: list[str] = []
    for target in sorted(targets):
        try:
            completed = subprocess.run(
                ["taey-notify", "--type", "status", "--from", "consult-monitor",
                 "--", target, routed_message],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            failures.append(f"{target}:exception:{type(exc).__name__}:{exc}")
            continue
        if completed.returncode != 0:
            failures.append(
                f"{target}:{completed.returncode}:"
                f"{(completed.stderr or completed.stdout).strip()[:160]}"
            )
    return sorted(targets), failures


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
                try:
                    targets, failures = notify_taey(
                        f"consult on {display} ({platform}) COMPLETE — stop button "
                        f"disappeared. Response ready to harvest.",
                        platform,
                        display,
                    )
                    log(
                        f"[consult-monitor {display}] COMPLETE -> notified "
                        f"{','.join(targets)} failures={failures or 'none'}"
                    )
                finally:
                    det = new_detector(Detector)
        except Exception as e:  # firefox restart / empty tree / bus change — keep watching
            log(f"[consult-monitor {display}] scan_error {type(e).__name__}: {str(e)[:100]}")
            os.environ["AT_SPI_BUS_ADDRESS"] = resolve_bus(display)  # bus rotates on restart
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
