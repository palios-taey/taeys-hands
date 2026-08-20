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
(a generation finishing) it prepares a frozen extraction handoff, notifies Taey,
and sends status-only notices to the other recorded targets. It reads the tree
and coordination record and writes only the handoff artifacts; it never drives.

Usage: consult_completion_monitor.py <display-number>   e.g. 2
"""
from __future__ import annotations

import importlib
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)

# Standard Mira consult display -> platform map (primary + second set).
DISPLAY_PLATFORM = {
    "2": "chatgpt", "3": "claude", "4": "gemini", "5": "grok", "6": "perplexity",
    "21": "claude", "22": "gemini", "23": "grok", "24": "perplexity",
}
POLL_SECONDS = 3.0
NOTIFICATION_RETRY_SECONDS = float(
    os.environ.get("CONSULT_MONITOR_NOTIFICATION_RETRY_SECONDS", "30")
)
NOTIFICATION_MAX_ATTEMPTS = int(
    os.environ.get("CONSULT_MONITOR_NOTIFICATION_MAX_ATTEMPTS", "20")
)


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


def active_completion_routes(platform: str, display: str) -> list[dict[str, object]]:
    from storage.redis_pool import get_client

    client = get_client()
    routes: list[dict[str, object]] = []
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
            phase = str(record.get("phase") or "")
            if phase not in {"awaiting_completion", "notification_failed"}:
                continue
            if record.get("stop_proven") is not True:
                continue
            if (
                phase == "notification_failed"
                and float(record.get("next_notification_retry_at") or 0.0)
                > time.time()
            ):
                continue
            routes.append({
                "monitor_id": str(record.get("monitor_id") or ""),
                "requester": str(record.get("requester") or ""),
                "actor_seat_id": str(record.get("actor_seat_id") or ""),
                "phase": phase,
                "platform": platform,
                "display": display,
                "url": str(record.get("url") or ""),
                "notified_targets": [
                    str(target)
                    for target in (record.get("notified_targets") or [])
                    if str(target)
                ],
                "session_key": str(session_key),
                "set_key": str(set_key),
            })
    if len(routes) > 1:
        monitor_ids = sorted(route["monitor_id"] for route in routes)
        raise RuntimeError(
            f"multiple active consultations claim {display}: {monitor_ids}"
        )
    return routes


def refresh_route(route: dict[str, object]) -> bool:
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
    route: dict[str, object],
    *,
    notification_failures: list[str],
    notified_targets: list[str],
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
        or record.get("phase") not in {
            "awaiting_completion",
            "notification_failed",
        }
    ):
        return False
    if notification_failures:
        now = time.time()
        delivered_targets = sorted({
            str(target)
            for target in (
                list(record.get("notified_targets") or [])
                + notified_targets
            )
            if str(target)
        })
        if "taey" in delivered_targets:
            pipe = client.pipeline()
            pipe.srem(route["set_key"], route["session_key"])
            pipe.delete(route["session_key"])
            pipe.execute()
            return True
        attempts = int(record.get("notification_attempts") or 0) + 1
        timeout = int(record.get("timeout") or 10800)
        try:
            started_ts = float(
                record.get("started_ts")
                or record.get("last_seen")
                or now
            )
            deadline = float(
                record.get("notification_deadline_at")
                or started_ts + timeout
            )
        except (TypeError, ValueError):
            deadline = now + timeout
        remaining = max(1, int(deadline - now))
        record["phase"] = "notification_failed"
        record["notification_failures"] = notification_failures
        record["notified_targets"] = delivered_targets
        record["notification_attempts"] = attempts
        record["notification_deadline_at"] = deadline
        record["next_notification_retry_at"] = (
            now + NOTIFICATION_RETRY_SECONDS
        )
        record["last_seen"] = now
        if attempts >= NOTIFICATION_MAX_ATTEMPTS or deadline <= now:
            record["phase"] = "notification_abandoned"
            record["last_action"] = "notification_retry_exhausted"
            pipe = client.pipeline()
            pipe.set(
                route["session_key"],
                json.dumps(record),
                ex=remaining,
            )
            pipe.srem(route["set_key"], route["session_key"])
            pipe.execute()
            return True
        client.set(route["session_key"], json.dumps(record), ex=remaining)
        return False
    pipe = client.pipeline()
    pipe.srem(route["set_key"], route["session_key"])
    pipe.delete(route["session_key"])
    pipe.execute()
    return True


def _prepare_extraction_handoff(route: dict[str, object]) -> dict[str, str]:
    monitor_id = str(route.get("monitor_id") or "")
    actor_seat_id = str(route.get("actor_seat_id") or "")
    platform = str(route.get("platform") or "")
    display = str(route.get("display") or "")
    if not all((monitor_id, actor_seat_id, platform, display)):
        raise RuntimeError("completion route lacks extraction identity")
    monitor_slug = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        monitor_id,
    ).strip("_")
    if not monitor_slug:
        raise RuntimeError("completion route has no safe monitor identifier")
    response_root = Path(
        os.environ.get(
            "TAEY_CONSULT_RESPONSE_ROOT",
            str(Path.home() / "taey_runs" / "consultations"),
        )
    ).expanduser()
    artifact_root = response_root / monitor_slug
    artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    response_file = artifact_root / "response.txt"
    response_headers = artifact_root / "response.headers"
    response_json = artifact_root / "worker_response.json"
    request_json = artifact_root / "request.json"
    preexisting_outputs = [
        str(path)
        for path in (response_file, response_headers, response_json)
        if path.exists()
    ]
    if preexisting_outputs:
        raise RuntimeError(
            f"extraction output path already exists: {preexisting_outputs}"
        )
    identity_digest = hashlib.sha256(monitor_id.encode("utf-8")).hexdigest()
    event_id = f"extract-{identity_digest[:24]}"
    correlation_id = f"{event_id}-1"
    runbook = Path(REPO) / "docs" / "MANUAL_CONSULT_WALKTHROUGH.md"
    content = (
        f"Read {runbook}. The completion monitor reported COMPLETE for "
        f"monitor_id={monitor_id} on {platform} {display}. Execute section 7 "
        f"extraction only in this new turn. RESPONSE_FILE={response_file}. "
        "Use drive_chat only for the UI sequence and follow the runbook exactly. "
        "Do not navigate, attach, paste, send, retry, or recover. Stop after a "
        "verified non-empty response-file receipt or the first mismatch."
    )
    request_payload = {
        "model": "taey",
        "stream": False,
        "max_tokens": 4096,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": content}],
    }
    request_text = json.dumps(
        request_payload,
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    if request_json.exists():
        if request_json.read_text(encoding="utf-8") != request_text:
            raise RuntimeError(
                f"extraction request path contains different bytes: {request_json}"
            )
    else:
        with request_json.open("x", encoding="utf-8") as handle:
            handle.write(request_text)
        request_json.chmod(0o600)
    command = " ".join([
        "curl -sS --max-time 3600",
        f"-D {shlex.quote(str(response_headers))}",
        f"-o {shlex.quote(str(response_json))}",
        "-H 'Content-Type: application/json'",
        f"-H {shlex.quote(f'X-Taey-Seat-Id: {actor_seat_id}')}",
        f"-H {shlex.quote(f'X-Taey-Event-Id: {event_id}')}",
        f"-H {shlex.quote(f'X-Taey-Correlation-Id: {correlation_id}')}",
        "-H 'X-Taey-Tool-Profile: manual-chat-ui'",
        f"--data-binary @{shlex.quote(str(request_json))}",
        "http://127.0.0.1:8767/v1/chat/completions",
    ])
    return {
        "runbook": str(runbook),
        "response_file": str(response_file),
        "response_headers": str(response_headers),
        "response_json": str(response_json),
        "request_json": str(request_json),
        "event_id": event_id,
        "correlation_id": correlation_id,
        "command": command,
    }


def notify_taey(
    message: str,
    route: dict[str, object],
) -> tuple[list[str], list[str], list[str]]:
    targets = {"taey"}
    targets.update(
        target.strip()
        for target in os.environ.get("CONSULT_MONITOR_NOTIFY", "").split(",")
        if target.strip()
    )
    requester = str(route["requester"])
    if requester and requester != "unknown":
        targets.add(requester)
    routed_message = message
    if route["monitor_id"]:
        routed_message += f" monitor_id={route['monitor_id']}"

    already_notified = {
        str(target)
        for target in (route.get("notified_targets") or [])
        if str(target)
    }
    notified_targets: list[str] = []
    failures: list[str] = []
    for target in sorted(targets - already_notified):
        target_message = routed_message
        if target == "taey":
            try:
                handoff = _prepare_extraction_handoff(route)
            except (OSError, RuntimeError) as exc:
                failures.append(
                    f"taey:handoff:{type(exc).__name__}:{str(exc)[:160]}"
                )
                continue
            target_message += (
                f" extraction_executor={route['actor_seat_id']}"
                f" response_file={handoff['response_file']}"
                f" extraction_request_json={handoff['request_json']}"
                f" extraction_response_headers={handoff['response_headers']}"
                f" extraction_response_json={handoff['response_json']}"
                f" extraction_event_id={handoff['event_id']}"
                f" extraction_correlation_id={handoff['correlation_id']}. "
                "Main Taey: use run_command, not send_message; do not drive the "
                f"display. Run exactly: {handoff['command']}"
            )
        else:
            target_message += (
                " status_only=true extraction_owner=taey. Do not invoke a worker "
                "and do not drive the display."
            )
        try:
            completed = subprocess.run(
                ["taey-notify", "--type", "status", "--from", "consult-monitor",
                 "--", target, target_message],
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
            continue
        notified_targets.append(target)
    return sorted(targets), notified_targets, failures


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
            if route["phase"] == "notification_failed":
                targets, notified_targets, failures = notify_taey(
                    f"consult on {display} ({platform}) COMPLETE — stop button "
                    f"disappeared. Response ready to harvest.",
                    route,
                )
                removed = finish_route(
                    route,
                    notification_failures=failures,
                    notified_targets=notified_targets,
                )
                log(
                    f"[consult-monitor {display}] NOTIFICATION RETRY -> "
                    f"{','.join(targets)} failures={failures or 'none'} "
                    f"route_removed={removed}"
                )
                det = None
                active_monitor_id = ""
                time.sleep(POLL_SECONDS)
                continue
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
                    targets, notified_targets, failures = notify_taey(
                        f"consult on {display} ({platform}) COMPLETE — stop button "
                        f"disappeared. Response ready to harvest.",
                        route,
                    )
                    removed = finish_route(
                        route,
                        notification_failures=failures,
                        notified_targets=notified_targets,
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
