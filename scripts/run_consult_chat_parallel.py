#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
LANE_WORKER = REPO_ROOT / "scripts" / "run_consult_chat_worker.py"
READINESS = REPO_ROOT / "scripts" / "display_readiness_check.py"
LANES = {
    "chatgpt": ":2",
    "claude": ":3",
    "gemini": ":4",
    "grok": ":5",
    "perplexity": ":6",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch one frozen five-lane consult_chat campaign concurrently.",
    )
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--packet-stem", required=True)
    parser.add_argument("--packet-root", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--frozen-spec", required=True)
    parser.add_argument("--hands-sha", required=True)
    parser.add_argument("--presence-sha", required=True)
    return parser


def _absolute_directory(raw: str, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise RuntimeError(f"{label} must be a directory: {resolved}")
    return resolved


def _absolute_file(raw: str, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise RuntimeError(f"{label} must be a non-empty file: {resolved}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + (
        f".{time.time_ns() % 1_000_000_000:09d}Z"
    )


def _redis_lines(*arguments: str) -> list[str]:
    result = subprocess.run(
        ["redis-cli", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"redis-cli {' '.join(arguments)} failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


def _preflight(root: Path, packet_root: Path, packet_stem: str) -> dict[str, object]:
    active_turns = _redis_lines("ZCARD", "taey:soma:active_turns")
    if active_turns != ["0"]:
        raise RuntimeError(f"active-turn preflight failed: {active_turns}")
    display_leases = _redis_lines("--scan", "--pattern", "taey:plan_active:*")
    if display_leases:
        raise RuntimeError(f"display-lease preflight failed: {display_leases}")
    worker_scan = subprocess.run(
        ["pgrep", "-af", "run_consult_chat_worker.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    if worker_scan.returncode not in {0, 1}:
        raise RuntimeError(f"worker process preflight failed: {worker_scan.stderr.strip()}")
    orphan_workers = [
        line
        for line in worker_scan.stdout.splitlines()
        if "run_consult_chat_parallel.py" not in line
    ]
    if orphan_workers:
        raise RuntimeError(f"orphan-worker preflight failed: {orphan_workers}")
    if root.exists():
        raise RuntimeError(f"artifact_root already exists; refusing retry: {root}")
    root.parent.resolve(strict=True)

    readiness: dict[str, str] = {}
    inputs: dict[str, dict[str, str]] = {}
    for platform in LANES:
        lane_inputs: dict[str, str] = {}
        for suffix, label in (
            ("bundle-a.md", "bundle_a"),
            ("bundle-b.md", "bundle_b"),
            ("prompt.txt", "prompt_file"),
        ):
            path = packet_root / f"{packet_stem}-{platform}-{suffix}"
            resolved = _absolute_file(str(path), f"{platform} {label}")
            lane_inputs[label] = str(resolved)
        inputs[platform] = lane_inputs
        result = subprocess.run(
            [sys.executable, str(READINESS), platform],
            check=False,
            capture_output=True,
            text=True,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0 or "ready=True" not in output:
            raise RuntimeError(f"{platform} readiness failed: {output}")
        readiness[platform] = output
    return {
        "active_turns": 0,
        "display_leases": [],
        "orphan_workers": [],
        "readiness": readiness,
        "inputs": inputs,
    }


def _terminal_state() -> dict[str, object]:
    active_turns = _redis_lines("ZCARD", "taey:soma:active_turns")
    display_leases = _redis_lines("--scan", "--pattern", "taey:plan_active:*")
    worker_scan = subprocess.run(
        ["pgrep", "-af", "run_consult_chat_worker.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    orphan_workers = [
        line
        for line in worker_scan.stdout.splitlines()
        if "run_consult_chat_parallel.py" not in line
    ]
    return {
        "active_turns": int(active_turns[0]) if len(active_turns) == 1 else None,
        "display_leases": display_leases,
        "orphan_workers": orphan_workers,
    }


def _lane_receipt(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def main() -> int:
    args = _parser().parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,149}", args.campaign_id):
        raise RuntimeError("campaign_id must be a valid 1-150 character identity")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", args.packet_stem):
        raise RuntimeError("packet_stem must be a valid direct filename stem")
    for label, value in (("hands_sha", args.hands_sha), ("presence_sha", args.presence_sha)):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise RuntimeError(f"{label} must be a lowercase 40-hex commit SHA")
    packet_root = _absolute_directory(args.packet_root, "packet_root")
    frozen_spec = _absolute_file(args.frozen_spec, "frozen_spec")
    root = Path(args.artifact_root).expanduser()
    if not root.is_absolute():
        raise RuntimeError("artifact_root must be an absolute path")
    root = root.parent.resolve(strict=True) / root.name
    preflight = _preflight(root, packet_root, args.packet_stem)
    root.mkdir(mode=0o700)
    log_root = root / "launcher_logs"
    log_root.mkdir(mode=0o700)

    processes: dict[str, subprocess.Popen[bytes]] = {}
    handles: dict[str, tuple[object, object]] = {}
    started_by_platform: dict[str, int] = {}
    launches: list[dict[str, object]] = []
    lane_inputs = preflight["inputs"]
    assert isinstance(lane_inputs, dict)
    for platform, display in LANES.items():
        inputs = lane_inputs[platform]
        assert isinstance(inputs, dict)
        stdout_handle = (log_root / f"{platform}.stdout").open("xb")
        stderr_handle = (log_root / f"{platform}.stderr").open("xb")
        command = [
            sys.executable,
            str(LANE_WORKER),
            "--display",
            display,
            "--seat-id",
            f"{args.campaign_id}-{platform}",
            "--artifact-root",
            str(root / platform),
            "--prompt-file",
            str(inputs["prompt_file"]),
            "--bundle-a",
            str(inputs["bundle_a"]),
            "--bundle-b",
            str(inputs["bundle_b"]),
        ]
        started_ns = time.monotonic_ns()
        process = subprocess.Popen(command, stdout=stdout_handle, stderr=stderr_handle)
        processes[platform] = process
        handles[platform] = (stdout_handle, stderr_handle)
        started_by_platform[platform] = started_ns
        launches.append(
            {
                "platform": platform,
                "display": display,
                "seat_id": f"{args.campaign_id}-{platform}",
                "pid": process.pid,
                "started_utc": _utc_now(),
                "started_monotonic_ns": started_ns,
            }
        )

    results: dict[str, dict[str, object]] = {}
    while len(results) < len(processes):
        for platform, process in processes.items():
            if platform in results:
                continue
            exit_code = process.poll()
            if exit_code is None:
                continue
            for handle in handles[platform]:
                handle.close()
            stdout_path = log_root / f"{platform}.stdout"
            stderr_path = log_root / f"{platform}.stderr"
            completed_ns = time.monotonic_ns()
            terminal_receipt = _lane_receipt(stdout_path)
            results[platform] = {
                "exit_code": exit_code,
                "completed_utc": _utc_now(),
                "completed_monotonic_ns": completed_ns,
                "elapsed_ms": (
                    completed_ns - started_by_platform[platform]
                ) / 1_000_000,
                "stdout": str(stdout_path),
                "stdout_sha256": _sha256(stdout_path),
                "stderr": str(stderr_path),
                "stderr_sha256": _sha256(stderr_path),
                "terminal_receipt": terminal_receipt,
            }
        time.sleep(0.5)

    starts = [int(item["started_monotonic_ns"]) for item in launches]
    final_state = _terminal_state()
    clean_release = (
        final_state["active_turns"] == 0
        and final_state["display_leases"] == []
        and final_state["orphan_workers"] == []
    )
    summary = {
        "campaign_id": args.campaign_id,
        "hands_baseline_sha": args.hands_sha,
        "presence_baseline_sha": args.presence_sha,
        "frozen_spec": str(frozen_spec),
        "frozen_spec_sha256": _sha256(frozen_spec),
        "preflight": preflight,
        "launch_spread_ms": (max(starts) - min(starts)) / 1_000_000,
        "launches": launches,
        "results": results,
        "final_state": final_state,
        "clean_release": clean_release,
    }
    summary_path = root / "batch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lane_success = all(
        item["exit_code"] == 0
        and isinstance(item["terminal_receipt"], dict)
        and item["terminal_receipt"].get("ok") is True
        for item in results.values()
    )
    return 0 if lane_success and clean_release else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(1)
