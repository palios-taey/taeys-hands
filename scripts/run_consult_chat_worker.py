#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ENDPOINT = "http://127.0.0.1:8767/v1/chat/completions"
IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
DISPLAYS = (":2", ":3", ":4", ":5", ":6")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Invoke one frozen one-call consult_chat transaction.",
    )
    parser.add_argument("--display", required=True, choices=DISPLAYS)
    parser.add_argument("--seat-id", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--bundle-a", required=True)
    parser.add_argument("--bundle-b", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    return parser


def _identity(value: str) -> str:
    if not IDENTITY_RE.fullmatch(value):
        raise RuntimeError(f"seat id must match {IDENTITY_RE.pattern}")
    return value


def _input_file(raw: str, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise RuntimeError(f"{label} must be a non-empty regular file: {resolved}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _headers(path: Path) -> dict[str, str]:
    blocks = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n\n")
    blocks = [block for block in blocks if block.startswith("HTTP/")]
    if not blocks:
        raise RuntimeError("worker response has no HTTP header block")
    lines = blocks[-1].splitlines()
    parts = lines[0].split()
    if len(parts) < 2 or parts[1] != "200":
        raise RuntimeError(f"worker returned non-200 status: {lines[0]}")
    result: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip().lower()] = value.strip()
    return result


def _worker_receipt(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
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
        raise RuntimeError("worker response has no terminal receipt")
    return content


def main() -> int:
    args = _parser().parse_args()
    seat_id = _identity(args.seat_id)
    prompt_file = _input_file(args.prompt_file, "prompt_file")
    bundle_a = _input_file(args.bundle_a, "bundle_a")
    bundle_b = _input_file(args.bundle_b, "bundle_b")
    if len({prompt_file, bundle_a, bundle_b}) != 3:
        raise RuntimeError("prompt_file, bundle_a, and bundle_b must be distinct")

    root = Path(args.artifact_root).expanduser()
    if not root.is_absolute():
        raise RuntimeError("artifact_root must be an absolute path")
    if root.exists():
        raise RuntimeError(f"artifact_root already exists; refusing retry: {root}")
    root = root.parent.resolve(strict=True) / root.name
    root.mkdir(mode=0o700)

    output_file = root / "response.txt"
    receipt_file = root / "consultation_receipt.json"
    request_file = root / "request.json"
    response_headers = root / "response.headers"
    worker_response = root / "worker_response.json"
    user_message = json.dumps(
        {
            "display": args.display,
            "prompt_file": str(prompt_file),
            "bundle_a": str(bundle_a),
            "bundle_b": str(bundle_b),
            "output_file": str(output_file),
            "receipt_file": str(receipt_file),
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    request_payload = {
        "model": "taey",
        "stream": False,
        "max_tokens": 2048,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": user_message}],
    }
    request_file.write_text(
        json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    request_file.chmod(0o600)

    identity_material = "\0".join(
        (
            seat_id,
            args.display,
            _sha256(prompt_file),
            _sha256(bundle_a),
            _sha256(bundle_b),
        )
    ).encode("utf-8")
    event_id = f"consult-{hashlib.sha256(identity_material).hexdigest()[:24]}"
    correlation_id = f"{event_id}-1"
    prepared = {
        "artifact_root": str(root),
        "bundle_a_sha256": _sha256(bundle_a),
        "bundle_b_sha256": _sha256(bundle_b),
        "correlation_id": correlation_id,
        "display": args.display,
        "event_id": event_id,
        "prompt_sha256": _sha256(prompt_file),
        "request_file": str(request_file),
        "seat_id": seat_id,
    }
    if args.prepare_only:
        print(json.dumps(prepared, sort_keys=True))
        return 0

    completed = subprocess.run(
        [
            "curl",
            "-sS",
            "--max-time",
            "6500",
            "-D",
            str(response_headers),
            "-o",
            str(worker_response),
            "-H",
            "Content-Type: application/json",
            "-H",
            f"X-Taey-Seat-Id: {seat_id}",
            "-H",
            f"X-Taey-Event-Id: {event_id}",
            "-H",
            f"X-Taey-Correlation-Id: {correlation_id}",
            "-H",
            "X-Taey-Tool-Profile: consult-chat",
            "--data-binary",
            f"@{request_file}",
            ENDPOINT,
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"worker transport failed with curl exit {completed.returncode}; refusing retry"
        )
    observed_headers = _headers(response_headers)
    expected_headers = {
        "x-taey-seat-id": seat_id,
        "x-taey-event-id": event_id,
        "x-taey-correlation-id": correlation_id,
        "x-taey-tool-profile": "consult-chat",
    }
    mismatches = {
        key: {"expected": value, "observed": observed_headers.get(key)}
        for key, value in expected_headers.items()
        if observed_headers.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"worker identity header mismatch: {mismatches}")
    terminal_receipt = _worker_receipt(worker_response)
    if not output_file.is_file() or output_file.stat().st_size == 0:
        raise RuntimeError(f"consult_chat returned without a non-empty response: {terminal_receipt}")
    if not receipt_file.is_file() or receipt_file.stat().st_size == 0:
        raise RuntimeError(f"consult_chat returned without a non-empty receipt: {terminal_receipt}")
    try:
        receipt_payload = json.loads(receipt_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("consultation receipt is not valid JSON") from exc
    if not isinstance(receipt_payload, dict) or receipt_payload.get("ok") is not True:
        raise RuntimeError("consultation receipt does not prove ok=true")

    print(
        json.dumps(
            {
                **prepared,
                "ok": True,
                "response_file": str(output_file),
                "response_bytes": output_file.stat().st_size,
                "response_sha256": _sha256(output_file),
                "receipt_file": str(receipt_file),
                "receipt_bytes": receipt_file.stat().st_size,
                "receipt_sha256": _sha256(receipt_file),
                "worker_response": str(worker_response),
                "worker_response_sha256": _sha256(worker_response),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"STOP: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1)
