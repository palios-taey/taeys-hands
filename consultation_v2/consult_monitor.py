"""Passive Redis liveness reaper for registered consultations.

This monitor sees only consultations that successfully wrote an active-session
record. A consultation that dies before registration is invisible here and must
be handled on the registration side. This module never imports or touches a
display, UI driver, browser, consultation engine, or completion extractor.
"""

from __future__ import annotations

import sys

_MODULES_BEFORE_IMPORTS = frozenset(sys.modules)

import argparse
import json
import math
import os
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

import redis
from redis.exceptions import WatchError


DEFAULT_TIMEOUT = 7200.0
MODEL_REQUEST_TIMEOUT = 5400.0
GRACE = 300.0
NOTIFY_WINDOW = 6 * 60 * 60.0
SCAN_COUNT = 100
SESSION_SET_PATTERN = "taey:*:active_session_ids"

HEALTHY = "healthy/in-flight"
LIVE_STALL = "live-stall/orphan"
ANCIENT_LEAK = "ancient-leak"

_FORBIDDEN_MODULE_PREFIXES = (
    "consultation_v2.atspi",
    "consultation_v2.input",
    "consultation_v2.interact",
    "consultation_v2.orchestrator",
    "consultation_v2.platforms",
    "consultation_v2.runtime",
    "gi.repository.Atspi",
)


def _assert_import_boundary() -> None:
    introduced = set(sys.modules).difference(_MODULES_BEFORE_IMPORTS)
    violations = sorted(
        name
        for name in introduced
        if name.endswith(".driver")
        or any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in _FORBIDDEN_MODULE_PREFIXES
        )
    )
    if violations:
        raise RuntimeError(
            "consult monitor crossed its passive import boundary: "
            + ", ".join(violations)
        )


_assert_import_boundary()


@dataclass(slots=True)
class Finding:
    set_key: str
    session_key: str
    node: str
    raw_record: str | None = field(repr=False)
    record: dict[str, Any] = field(repr=False)
    age_seconds: float | None
    timeout_seconds: float
    verdict: str
    reason: str
    outcome: str = ""

    @property
    def platform(self) -> str:
        return str(self.record.get("platform") or "unknown")

    @property
    def requester(self) -> str:
        return str(self.record.get("requester") or "unknown")

    @property
    def url(self) -> str:
        return str(self.record.get("url") or "unknown")


@dataclass(slots=True)
class ScanReport:
    findings: list[Finding]
    set_count: int
    cleaned: int = 0
    skipped_changed: int = 0
    notifications: int = 0


def _redis_client() -> redis.Redis:
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    client = redis.Redis(
        host=host,
        port=port,
        decode_responses=True,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )
    client.ping()
    return client


def _parse_timestamp(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if moment.tzinfo is None or moment.utcoffset() is None:
            return None
        parsed = moment.timestamp()
    return parsed if math.isfinite(parsed) else None


def _started_timestamp(record: Mapping[str, Any]) -> float | None:
    started_ts = _parse_timestamp(record.get("started_ts"))
    if started_ts is not None:
        return started_ts
    return _parse_timestamp(record.get("started"))


def _heartbeat(record: Mapping[str, Any]) -> tuple[str, float | None] | None:
    for field_name in ("last_seen", "heartbeat"):
        if field_name in record:
            return field_name, _parse_timestamp(record.get(field_name))
    return None


def _record_timeout(record: Mapping[str, Any]) -> float | None:
    raw_timeout = record.get("timeout") or DEFAULT_TIMEOUT
    if isinstance(raw_timeout, bool):
        return None
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timeout) or timeout <= 0:
        return None
    return timeout


def _node_from_set_key(set_key: str) -> str:
    prefix = "taey:"
    suffix = ":active_session_ids"
    if set_key.startswith(prefix) and set_key.endswith(suffix):
        return set_key[len(prefix) : -len(suffix)]
    return set_key


def _malformed_finding(
    set_key: str,
    session_key: str,
    raw_record: str | None,
    record: dict[str, Any],
    reason: str,
) -> Finding:
    return Finding(
        set_key=set_key,
        session_key=session_key,
        node=_node_from_set_key(set_key),
        raw_record=raw_record,
        record=record,
        age_seconds=None,
        timeout_seconds=DEFAULT_TIMEOUT,
        verdict=ANCIENT_LEAK,
        reason=reason,
    )


def _classify(
    set_key: str,
    session_key: str,
    raw_record: str | None,
    now: float,
) -> Finding:
    if raw_record is None:
        return _malformed_finding(
            set_key, session_key, raw_record, {}, "missing-session-record"
        )
    try:
        decoded = json.loads(raw_record)
    except (json.JSONDecodeError, TypeError):
        return _malformed_finding(
            set_key, session_key, raw_record, {}, "malformed-json"
        )
    if not isinstance(decoded, dict):
        return _malformed_finding(
            set_key, session_key, raw_record, {}, "non-object-json"
        )

    heartbeat = _heartbeat(decoded)
    if heartbeat is not None:
        heartbeat_field, heartbeat_ts = heartbeat
        if heartbeat_ts is None:
            return _malformed_finding(
                set_key,
                session_key,
                raw_record,
                decoded,
                f"invalid-{heartbeat_field}",
            )
        age = now - heartbeat_ts
        threshold = MODEL_REQUEST_TIMEOUT + GRACE
        if age <= threshold:
            verdict = HEALTHY
        elif age <= NOTIFY_WINDOW:
            verdict = LIVE_STALL
        else:
            verdict = ANCIENT_LEAK
        return Finding(
            set_key=set_key,
            session_key=session_key,
            node=_node_from_set_key(set_key),
            raw_record=raw_record,
            record=decoded,
            age_seconds=age,
            timeout_seconds=threshold,
            verdict=verdict,
            reason=f"{heartbeat_field}-age",
        )

    started_ts = _started_timestamp(decoded)
    if started_ts is None:
        return _malformed_finding(
            set_key, session_key, raw_record, decoded, "invalid-or-missing-started"
        )
    timeout = _record_timeout(decoded)
    if timeout is None:
        return _malformed_finding(
            set_key, session_key, raw_record, decoded, "invalid-timeout"
        )

    # Revisit clock-skew handling before running this reader across hosts.
    age = now - started_ts
    if age <= timeout + GRACE:
        verdict = HEALTHY
    elif age <= NOTIFY_WINDOW:
        verdict = LIVE_STALL
    else:
        verdict = ANCIENT_LEAK
    return Finding(
        set_key=set_key,
        session_key=session_key,
        node=_node_from_set_key(set_key),
        raw_record=raw_record,
        record=decoded,
        age_seconds=age,
        timeout_seconds=timeout,
        verdict=verdict,
        reason="started-age",
    )


def _scan_findings(client: redis.Redis, now: float) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    set_count = 0
    for set_key in client.scan_iter(match=SESSION_SET_PATTERN, count=SCAN_COUNT):
        set_count += 1
        for session_key in client.sscan_iter(set_key, count=SCAN_COUNT):
            raw_record = client.get(session_key)
            findings.append(
                _classify(set_key, session_key, raw_record, now)
            )
    findings.sort(key=lambda finding: (finding.node, finding.session_key))
    return findings, set_count


def _clean_if_unchanged(client: redis.Redis, finding: Finding) -> bool:
    try:
        with client.pipeline() as transaction:
            transaction.watch(finding.session_key)
            current_record = transaction.get(finding.session_key)
            if current_record != finding.raw_record:
                transaction.unwatch()
                return False
            transaction.multi()
            transaction.srem(finding.set_key, finding.session_key)
            transaction.delete(finding.session_key)
            transaction.execute()
            return True
    except WatchError:
        return False


def _notification_targets(requester: str) -> list[str]:
    normalized = requester.strip()
    targets = ["taey"]
    if normalized.lower() not in {"", "unknown", "none", "null", "taey"}:
        targets.append(normalized)
    return targets


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    return f"{hours}h{minutes:02d}m{remaining_seconds:02d}s"


def _notify_status(finding: Finding) -> int:
    started = str(finding.record.get("started") or "unknown")
    message = (
        "Consult status: registered consult appears stalled/orphaned; "
        f"platform={finding.platform} url={finding.url} started={started} "
        f"elapsed={_format_duration(finding.age_seconds)}. "
        "The monitor removed only its stale Redis registration. Taey retains "
        "the supervised by-hand decision on whether any follow-up is needed."
    )
    targets = _notification_targets(finding.requester)
    for target in targets:
        subprocess.run(
            ["taey-notify", "--type", "status", "--", target, message],
            check=True,
            capture_output=True,
            text=True,
        )
    return len(targets)


def scan_and_reap(
    client: redis.Redis | None = None,
    *,
    dry_run: bool = True,
    now: float | None = None,
) -> ScanReport:
    active_client = client or _redis_client()
    observed_at = time.time() if now is None else now
    findings, set_count = _scan_findings(active_client, observed_at)
    report = ScanReport(findings=findings, set_count=set_count)

    for finding in findings:
        if finding.verdict == HEALTHY:
            finding.outcome = "leave"
            continue
        if dry_run:
            if finding.verdict == LIVE_STALL:
                targets = ",".join(_notification_targets(finding.requester))
                finding.outcome = f"would-status:{targets}+clean"
            else:
                finding.outcome = "would-clean:silent"
            continue
        if not _clean_if_unchanged(active_client, finding):
            finding.outcome = "skip:changed-or-gone"
            report.skipped_changed += 1
            continue
        report.cleaned += 1
        if finding.verdict == LIVE_STALL:
            report.notifications += _notify_status(finding)
            finding.outcome = "cleaned+status"
        else:
            finding.outcome = "cleaned:silent"
    return report


def _cell(value: Any) -> str:
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _print_report(report: ScanReport, *, dry_run: bool) -> None:
    print("key\tnode\tplatform\trequester\tage\ttimeout\tverdict\taction")
    for finding in report.findings:
        age = (
            "unknown"
            if finding.age_seconds is None
            else str(max(0, int(finding.age_seconds)))
        )
        row = (
            finding.session_key,
            finding.node,
            finding.platform,
            finding.requester,
            age,
            int(finding.timeout_seconds),
            finding.verdict,
            finding.outcome,
        )
        print("\t".join(_cell(value) for value in row))

    totals = Counter(finding.verdict for finding in report.findings)
    print(
        "TOTAL "
        f"mode={'dry-run' if dry_run else 'apply'} "
        f"sets={report.set_count} sessions={len(report.findings)} "
        f"healthy={totals[HEALTHY]} live_stall={totals[LIVE_STALL]} "
        f"ancient_leak={totals[ANCIENT_LEAK]} cleaned={report.cleaned} "
        f"skipped_changed={report.skipped_changed} "
        f"notifications={report.notifications}"
    )

    per_node: dict[str, Counter[str]] = defaultdict(Counter)
    for finding in report.findings:
        per_node[finding.node][finding.verdict] += 1
    print("PER_NODE node\ttotal\thealthy\tlive_stall\tancient_leak")
    for node in sorted(per_node):
        counts = per_node[node]
        print(
            "\t".join(
                (
                    _cell(node),
                    str(sum(counts.values())),
                    str(counts[HEALTHY]),
                    str(counts[LIVE_STALL]),
                    str(counts[ANCIENT_LEAK]),
                )
            )
        )

    stale_sample = [
        finding for finding in report.findings if finding.verdict != HEALTHY
    ][:5]
    print(f"SAMPLE count={len(stale_sample)}")
    for finding in stale_sample:
        print(
            f"{_cell(finding.session_key)}\t{finding.verdict}\t{finding.outcome}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Passively classify and optionally reap registered consult stalls."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--dry-run",
        action="store_true",
        help="classify only (default; no notifications or Redis writes)",
    )
    action.add_argument(
        "--apply",
        action="store_true",
        help="status-notify live stalls and clean exact stale registrations",
    )
    cadence = parser.add_mutually_exclusive_group()
    cadence.add_argument("--once", action="store_true", help="run one pass (default)")
    cadence.add_argument("--loop", action="store_true", help="poll until interrupted")
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="seconds between --loop passes (default: 60)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    dry_run = not args.apply
    client = _redis_client()
    while True:
        report = scan_and_reap(client, dry_run=dry_run)
        _print_report(report, dry_run=dry_run)
        if not args.loop:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
