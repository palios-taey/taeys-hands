#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = REPO_ROOT / "docs" / "MANUAL_CONSULT_WALKTHROUGH.md"
ENDPOINT = "http://127.0.0.1:8767/v1/chat/completions"
PLATFORM_LABELS = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "gemini": "Gemini",
    "grok": "Grok",
    "perplexity": "Perplexity",
}
IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Invoke one frozen manual-chat-ui worker turn without freeform instructions.",
    )
    phases = parser.add_subparsers(dest="phase", required=True)

    send = phases.add_parser("send", help="Attach two frozen bundles, paste, and send once.")
    _add_common(send)
    send.add_argument("--bundle-a", required=True)
    send.add_argument("--bundle-b", required=True)
    send.add_argument("--prompt-file", required=True)

    extract = phases.add_parser(
        "extract",
        help="Extract once after the completion monitor reports COMPLETE.",
    )
    _add_common(extract)
    extract.add_argument("--monitor-id", required=True)
    extract.add_argument("--response-file", required=True)
    extract.add_argument("--prepare-only", action="store_true")
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORM_LABELS))
    parser.add_argument("--display", required=True)
    parser.add_argument("--seat-id", required=True)
    parser.add_argument("--artifact-root", required=True)


def _absolute_input(raw: str, name: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{name} must be an absolute path")
    path = path.resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"{name} must be a non-empty regular file: {path}")
    return path


def _artifact_root(raw: str, *, allow_existing: bool) -> Path:
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise RuntimeError("artifact root must be an absolute path")
    if root.exists():
        if allow_existing and root.is_dir():
            return root.resolve(strict=True)
        raise RuntimeError(f"artifact root already exists; refusing retry: {root}")
    parent = root.parent.resolve(strict=True)
    root = parent / root.name
    return root


def _identity(raw: str, name: str) -> str:
    if not IDENTITY_RE.fullmatch(raw):
        raise RuntimeError(f"{name} must match {IDENTITY_RE.pattern}")
    return raw


def _request_text(content: str, max_tokens: int) -> str:
    encoded_content = json.dumps(content, ensure_ascii=False)
    return (
        "{\n"
        '  "model": "taey",\n'
        '  "stream": false,\n'
        f'  "max_tokens": {max_tokens},\n'
        '  "chat_template_kwargs": {"enable_thinking": false},\n'
        '  "messages": [\n'
        '    {\n'
        '      "role": "user",\n'
        f'      "content": {encoded_content}\n'
        '    }\n'
        '  ]\n'
        '}\n'
    )


def _ensure_request(path: Path, text: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"request path contains different bytes: {path}")
        return
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
    path.chmod(0o600)


def _send_content(
    platform: str,
    display: str,
    bundle_a: Path,
    bundle_b: Path,
    prompt_file: Path,
) -> str:
    return (
        f"Read {RUNBOOK}. Execute the {PLATFORM_LABELS[platform]} send phase only "
        f"on {display} with BUNDLE_A={bundle_a}, BUNDLE_B={bundle_b}, and "
        f"PROMPT_FILE={prompt_file}. Use drive_chat only and follow the runbook "
        "exactly. Stop after the section 6 send receipt or the first mismatch. "
        "Do not extract, retry, or recover in this turn."
    )


def _extract_content(
    monitor_id: str,
    platform: str,
    display: str,
    response_file: Path,
) -> str:
    return (
        f"Read {RUNBOOK}. The completion monitor reported COMPLETE for "
        f"monitor_id={monitor_id} on {PLATFORM_LABELS[platform]} {display}. Execute section 7 "
        f"extraction only in this new turn. RESPONSE_FILE={response_file}. Use "
        "drive_chat only for the UI sequence and follow the runbook exactly. Do "
        "not navigate, attach, paste, send, retry, or recover. Stop after a "
        "verified non-empty response-file receipt or the first mismatch."
    )


def _identity_headers(headers_path: Path) -> dict[str, str]:
    blocks = headers_path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n\n")
    blocks = [block for block in blocks if block.startswith("HTTP/")]
    if not blocks:
        raise RuntimeError("worker response has no HTTP header block")
    lines = blocks[-1].splitlines()
    parts = lines[0].split()
    if len(parts) < 2 or parts[1] != "200":
        raise RuntimeError(f"worker returned non-200 status: {lines[0]}")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def _worker_receipt(response_path: Path) -> tuple[dict[str, object], str]:
    try:
        payload = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("worker response is not valid JSON") from exc
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or len(choices) != 1:
        raise RuntimeError("worker response must contain exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        raise RuntimeError("worker response did not finish with stop")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("worker response has no receipt text")
    return payload, content


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _invoke(
    *,
    root: Path,
    request_text: str,
    seat_id: str,
    event_id: str,
    correlation_id: str,
) -> tuple[Path, Path, Path, str]:
    request_path = root / "request.json"
    headers_path = root / "response.headers"
    response_path = root / "worker_response.json"
    _ensure_request(request_path, request_text)
    completed = subprocess.run(
        [
            "curl",
            "-sS",
            "--max-time",
            "3600",
            "-D",
            str(headers_path),
            "-o",
            str(response_path),
            "-H",
            "Content-Type: application/json",
            "-H",
            f"X-Taey-Seat-Id: {seat_id}",
            "-H",
            f"X-Taey-Event-Id: {event_id}",
            "-H",
            f"X-Taey-Correlation-Id: {correlation_id}",
            "-H",
            "X-Taey-Tool-Profile: manual-chat-ui",
            "--data-binary",
            f"@{request_path}",
            ENDPOINT,
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"worker transport failed with curl exit {completed.returncode}; refusing retry"
        )
    headers = _identity_headers(headers_path)
    expected_headers = {
        "x-taey-seat-id": seat_id,
        "x-taey-event-id": event_id,
        "x-taey-correlation-id": correlation_id,
        "x-taey-tool-profile": "manual-chat-ui",
    }
    mismatches = {
        key: {"expected": value, "observed": headers.get(key)}
        for key, value in expected_headers.items()
        if headers.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"worker identity header mismatch: {mismatches}")
    _payload, receipt = _worker_receipt(response_path)
    return request_path, headers_path, response_path, receipt


def _is_worker_stop_report(receipt: str) -> bool:
    lowered = receipt.lower()
    return all(
        field in lowered
        for field in (
            "platform/display:",
            "expected postcondition:",
            "observed postcondition:",
            "classification:",
        )
    )


def _release_extract_lease(display: str, seat_id: str) -> str:
    host = os.environ.get("REDIS_HOST") or os.environ.get("TAEY_REDIS_HOST") or "127.0.0.1"
    port = os.environ.get("REDIS_PORT") or os.environ.get("TAEY_REDIS_PORT") or "6379"
    key = f"taey:plan_active:{display}"
    fetched = subprocess.run(
        ["redis-cli", "-h", host, "-p", port, "--raw", "GET", key],
        check=False,
        capture_output=True,
        text=True,
    )
    if fetched.returncode != 0:
        raise RuntimeError("could not read the extraction display lease")
    raw = fetched.stdout.rstrip("\n")
    if not raw:
        return "absent"
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("extraction display lease is malformed") from exc
    if not isinstance(record, dict) or record.get("seat_id") != seat_id:
        raise RuntimeError("extraction display lease belongs to another seat")
    removed = subprocess.run(
        [
            "redis-cli",
            "-h",
            host,
            "-p",
            port,
            "--raw",
            "EVAL",
            "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end",
            "1",
            key,
            raw,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if removed.returncode != 0:
        raise RuntimeError("could not compare-delete the extraction display lease")
    if removed.stdout.strip() != "1":
        raise RuntimeError("extraction display lease changed before compare-delete")
    return "released"


def main() -> int:
    args = build_parser().parse_args()
    seat_id = _identity(args.seat_id, "seat id")
    artifact_root_preexisted = Path(args.artifact_root).expanduser().exists()
    root = _artifact_root(
        args.artifact_root,
        allow_existing=args.phase == "extract",
    )

    if args.phase == "send":
        bundle_a = _absolute_input(args.bundle_a, "bundle A")
        bundle_b = _absolute_input(args.bundle_b, "bundle B")
        prompt_file = _absolute_input(args.prompt_file, "prompt file")
        content = _send_content(
            args.platform,
            args.display,
            bundle_a,
            bundle_b,
            prompt_file,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0{args.platform}\0{args.display}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"send-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 8192)
    else:
        monitor_id = _identity(args.monitor_id, "monitor id")
        response_file = Path(args.response_file).expanduser()
        if not response_file.is_absolute():
            raise RuntimeError("response file must be an absolute path")
        response_file = response_file.parent.resolve(strict=False) / response_file.name
        if response_file != root / "response.txt":
            raise RuntimeError("response file must be ARTIFACT_ROOT/response.txt")
        if response_file.exists():
            raise RuntimeError(f"response file already exists; refusing retry: {response_file}")
        content = _extract_content(
            monitor_id,
            args.platform,
            args.display,
            response_file,
        )
        digest = hashlib.sha256(monitor_id.encode("utf-8")).hexdigest()
        event_id = f"extract-{digest[:24]}"
        request_text = _request_text(content, 4096)

    correlation_id = f"{event_id}-1"
    if not root.exists():
        root.mkdir(mode=0o700)
    prepared_marker = root / ".prepared"
    if args.phase == "extract":
        _ensure_request(root / "request.json", request_text)
        if args.prepare_only:
            for output in (root / "response.headers", root / "worker_response.json", response_file):
                if output.exists():
                    raise RuntimeError(f"extraction output already exists: {output}")
            if prepared_marker.exists():
                if prepared_marker.read_text(encoding="utf-8") != event_id + "\n":
                    raise RuntimeError("prepared extraction handoff identity mismatch")
            else:
                if artifact_root_preexisted:
                    raise RuntimeError("prepared extraction handoff was already consumed")
                with prepared_marker.open("x", encoding="utf-8") as handle:
                    handle.write(event_id + "\n")
                prepared_marker.chmod(0o600)
            print(json.dumps({
                "artifact_root": str(root),
                "event_id": event_id,
                "request_json": str(root / "request.json"),
                "response_file": str(response_file),
            }, sort_keys=True))
            return 0
        if not prepared_marker.is_file():
            raise RuntimeError("extraction handoff is not prepared or was already consumed")
        if prepared_marker.read_text(encoding="utf-8") != event_id + "\n":
            raise RuntimeError("extraction handoff identity mismatch")
        for output in (root / "response.headers", root / "worker_response.json", response_file):
            if output.exists():
                raise RuntimeError(f"extraction output already exists; refusing retry: {output}")
        prepared_marker.unlink()
    lease_release = None
    primary_error = None
    try:
        request_path, headers_path, response_path, receipt = _invoke(
            root=root,
            request_text=request_text,
            seat_id=seat_id,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        if _is_worker_stop_report(receipt):
            raise RuntimeError("worker returned the walkthrough stop report")
        if args.phase == "send" and "monitor_id" not in receipt:
            raise RuntimeError("send response has no monitor_id")
        if response_file is not None:
            if not response_file.is_file() or response_file.stat().st_size == 0:
                raise RuntimeError("extraction did not create a non-empty response file")
    except RuntimeError as exc:
        primary_error = exc
    finally:
        if args.phase == "extract":
            try:
                lease_release = _release_extract_lease(args.display, seat_id)
            except RuntimeError as cleanup_error:
                if primary_error is None:
                    primary_error = cleanup_error
                else:
                    primary_error = RuntimeError(
                        f"{primary_error}; extraction lease cleanup failed: {cleanup_error}"
                    )
    if primary_error is not None:
        raise primary_error
    result: dict[str, object] = {
        "ok": True,
        "phase": args.phase,
        "platform": args.platform,
        "display": args.display,
        "seat_id": seat_id,
        "event_id": event_id,
        "correlation_id": correlation_id,
        "request_json": str(request_path),
        "request_sha256": _sha256(request_path),
        "response_headers": str(headers_path),
        "response_json": str(response_path),
        "response_json_sha256": _sha256(response_path),
    }
    if response_file is not None:
        result.update({
            "response_file": str(response_file),
            "response_bytes": response_file.stat().st_size,
            "response_sha256": _sha256(response_file),
            "lease_release": lease_release,
        })
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(1)
