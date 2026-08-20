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
            if (
                record.get("phase") != "awaiting_completion"
                or record.get("stop_proven") is not True
            ):
                continue
            routes.append({
                "monitor_id": str(record.get("monitor_id") or ""),
                "requester": str(record.get("requester") or ""),
                "actor_seat_id": str(record.get("actor_seat_id") or ""),
                "url": str(record.get("url") or ""),
                "session_key": str(session_key),
                "set_key": str(set_key),
            })
    if len(routes) > 1:
        monitor_ids = sorted(route["monitor_id"] for route in routes)
        raise RuntimeError(
            f"multiple active consultations claim {display}: {monitor_ids}"
        )
    return routes


def refresh_route(route: dict[str, str]) -> bool:
    from storage.redis_pool import get_client

    client = get_client()
    raw = client.get(route["session_key"])
    if not raw:
        return False
    record = json.loads(raw)
    if (
        not isinstance(record, dict)
        or record.get("phase") != "awaiting_completion"
        or record.get("stop_proven") is not True
        or str(record.get("monitor_id") or "") != route["monitor_id"]
    ):
        return False
    record["last_seen"] = time.time()
    record["last_action"] = "completion_monitor_read"
    timeout = int(record.get("timeout") or 10800)
    client.set(route["session_key"], json.dumps(record), ex=timeout)
    return True


def finish_route(
    route: dict[str, str],
    *,
    notification_failures: list[str],
) -> bool:
    from storage.redis_pool import get_client

    client = get_client()
    raw = client.get(route["session_key"])
    if not raw:
        return False
    record = json.loads(raw)
    if (
        not isinstance(record, dict)
        or str(record.get("monitor_id") or "") != route["monitor_id"]
        or record.get("phase") != "awaiting_completion"
    ):
        return False
    if notification_failures:
        record["phase"] = "notification_failed"
        record["notification_failures"] = notification_failures
        record["last_seen"] = time.time()
        timeout = int(record.get("timeout") or 10800)
        client.set(route["session_key"], json.dumps(record), ex=timeout)
        return False
    pipe = client.pipeline()
    pipe.srem(route["set_key"], route["session_key"])
    pipe.delete(route["session_key"])
    pipe.execute()
    return True


def notify_taey(message: str, route: dict[str, str]) -> tuple[list[str], list[str]]:
    targets = {"taey"}
    targets.update(
        target.strip()
        for target in os.environ.get("CONSULT_MONITOR_NOTIFY", "").split(",")
        if target.strip()
    )
    requester = route["requester"]
    if requester and requester != "unknown":
        targets.add(requester)
    routed_message = message
    if route["monitor_id"]:
        routed_message += f" monitor_id={route['monitor_id']}"
    if route.get("actor_seat_id"):
        routed_message += (
            f" extraction_executor={route['actor_seat_id']} — delegate extraction to "
            "that callable worker seat; Main Taey must not drive the display"
        )

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
    det = None
    active_monitor_id = ""
    log(
        f"[consult-monitor {display} {platform}] started; idle until a "
        "Stop-proven manual consultation is registered"
    )

    while True:
        try:
            routes = active_completion_routes(platform, display)
            if not routes:
                det = None
                active_monitor_id = ""
                time.sleep(POLL_SECONDS)
                continue
            route = routes[0]
            if route["monitor_id"] != active_monitor_id:
                det = new_detector(Detector)
                det.observe(True)
                active_monitor_id = route["monitor_id"]
                log(
                    f"[consult-monitor {display}] activated for "
                    f"{active_monitor_id}"
                )
            present = stop_button_present(platform)
            if not refresh_route(route):
                det = None
                active_monitor_id = ""
                time.sleep(POLL_SECONDS)
                continue
            assert det is not None
            verdict = det.observe(present)
            if verdict == "complete":
                try:
                    targets, failures = notify_taey(
                        f"consult on {display} ({platform}) COMPLETE — stop button "
                        f"disappeared. Response ready to harvest.",
                        route,
                    )
                    removed = finish_route(
                        route,
                        notification_failures=failures,
                    )
                    log(
                        f"[consult-monitor {display}] COMPLETE -> notified "
                        f"{','.join(targets)} failures={failures or 'none'} "
                        f"route_removed={removed}"
                    )
                finally:
                    det = None
                    active_monitor_id = ""
        except Exception as e:  # firefox restart / empty tree / bus change — keep watching
            log(f"[consult-monitor {display}] scan_error {type(e).__name__}: {str(e)[:100]}")
            os.environ["AT_SPI_BUS_ADDRESS"] = resolve_bus(display)  # bus rotates on restart
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
