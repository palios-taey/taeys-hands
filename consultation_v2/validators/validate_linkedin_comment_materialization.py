#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMAND = REPO_ROOT / "scripts/prepare_linkedin_comment.py"
SCHEMA = (
    REPO_ROOT / "consultation_v2/platforms/linkedin/comment-approval-source.schema.json"
)
SEAT = "linkedin-comment-validator"
EVENT = "linkedin-comment-event-001"
CORRELATION = "linkedin-comment-correlation-001"
ACTION = "linkedin-comment-action-001"
ACTIVITY = "1234567890123456789"
AUTHOR = "Private Author Sentinel"
TEXT = "Exact private comment sentinel.\n"
PRIVATE_EVIDENCE = "Private gate evidence sentinel"
BODY_SHA256 = "b" * 64
SOURCE_SHA256 = "c" * 64
RESULT_SCHEMA = "taey_linkedin_comment_materialization_result_v1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def write_private_file(path: Path, raw_bytes: bytes, mode: int = 0o400) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        pending = memoryview(raw_bytes)
        while pending:
            written = os.write(descriptor, pending)
            assert written > 0
            pending = pending[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def approval(**changes: Any) -> dict[str, Any]:
    value = {
        "schema": "taey_linkedin_private_comment_approval_v1",
        "operation": "comment",
        "platform": "linkedin",
        "display": ":18",
        "seat_id": SEAT,
        "event_id": EVENT,
        "correlation_id": CORRELATION,
        "action_id": ACTION,
        "selected_activity": ACTIVITY,
        "selected_post_body_sha256": BODY_SHA256,
        "source_artifact_sha256": SOURCE_SHA256,
        "like_authorized": True,
        "expected_author_name": AUTHOR,
        "text": TEXT,
        "gates": [
            {
                "gate": "cannot_lie",
                "passed": True,
                "ev": {"evidence": PRIVATE_EVIDENCE},
            },
            {
                "gate": "stance",
                "passed": True,
                "ev": {"status": "synthetic-pass"},
            },
        ],
    }
    value.update(changes)
    return value


def fixture(
    case_root: Path,
    *,
    value: dict[str, Any] | None = None,
    raw_bytes: bytes | None = None,
    source_mode: int = 0o400,
) -> tuple[Path, Path, dict[str, Any]]:
    private_root = case_root / "private"
    private_root.mkdir(mode=0o700, parents=True)
    os.chmod(private_root, 0o700)
    source_value = value if value is not None else approval()
    source = private_root / "approvals" / "comment.json"
    write_private_file(
        source,
        canonical_bytes(source_value) if raw_bytes is None else raw_bytes,
        source_mode,
    )
    return private_root, source, source_value


def invoke(
    command: str,
    private_root: Path,
    source: Path,
    *,
    receipt_sha256: str | None = None,
    transaction_sha256: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["TAEY_REVENUE_UI_PRIVATE_ROOT"] = str(private_root)
    environment["TAEY_LINKEDIN_COMMENT_APPROVAL_SOURCE"] = str(source)
    arguments = [
        sys.executable,
        str(COMMAND),
        command,
        "--seat-id",
        SEAT,
        "--event-id",
        EVENT,
        "--correlation-id",
        CORRELATION,
    ]
    if command == "preflight":
        assert receipt_sha256 is not None and transaction_sha256 is not None
        arguments.extend(
            [
                "--expected-gate-receipt-sha256",
                receipt_sha256,
                "--expected-transaction-sha256",
                transaction_sha256,
            ]
        )
    assert str(private_root) not in arguments and str(source) not in arguments
    result = subprocess.run(
        arguments,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,  # lint-allow: adversarial validator asserts exact refusal status and payload
    )
    for private_value in (
        AUTHOR,
        TEXT.strip(),
        PRIVATE_EVIDENCE,
        str(private_root),
        str(source),
    ):
        assert private_value not in result.stdout
        assert private_value not in result.stderr
    return result


def receipt_path(private_root: Path) -> Path:
    return private_root / "gate-receipts" / SEAT / f"{CORRELATION}.json"


def transaction_path(private_root: Path) -> Path:
    return private_root / "transactions" / SEAT / f"{CORRELATION}.json"


def require_refusal(result: subprocess.CompletedProcess[str], code: str) -> None:
    assert result.returncode == 2, (
        code,
        result.returncode,
        result.stdout,
        result.stderr,
    )
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "correlation_id": CORRELATION,
        "event_id": EVENT,
        "failure_code": code,
        "schema": RESULT_SCHEMA,
        "seat_id": SEAT,
        "state": "refused",
    }


def expected_artifacts(
    private_root: Path, value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_hash = hashlib.sha256(
        " ".join(value["text"].strip().split()).encode()
    ).hexdigest()
    path = receipt_path(private_root)
    receipt = {
        "action_id": ACTION,
        "claims_traced": True,
        "content_hash": normalized_hash,
        "failing_gate": None,
        "gates": value["gates"],
        "kind": "feed_comment",
        "packet_kind": "comment",
        "receipt_path": str(path),
        "receipt_version": "linkedin_gate_signoff_v1",
        "source_activity_id": ACTIVITY,
        "source_artifact_sha256": SOURCE_SHA256,
        "text_hash": normalized_hash,
        "verdict": "signoff",
    }
    receipt_sha256 = hashlib.sha256(canonical_bytes(receipt)).hexdigest()
    transaction = {
        "action_id": ACTION,
        "correlation_id": CORRELATION,
        "display": ":18",
        "event_id": EVENT,
        "expected_author_name": AUTHOR,
        "gate_receipt_kind": "feed_comment",
        "gate_receipt_path": str(path),
        "gate_receipt_sha256": receipt_sha256,
        "gate_receipt_version": "linkedin_gate_signoff_v1",
        "like_authorized": True,
        "operation": "comment",
        "platform": "linkedin",
        "schema": "taey_revenue_ui_private_comment_v1",
        "seat_id": SEAT,
        "selected_activity": ACTIVITY,
        "selected_post_body_sha256": BODY_SHA256,
        "source_artifact_sha256": SOURCE_SHA256,
        "text": TEXT,
        "text_sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
    }
    return receipt, transaction


def validate_happy_path(case_root: Path) -> None:
    root, source, value = fixture(
        case_root,
        raw_bytes=(
            json.dumps(approval(), indent=2, ensure_ascii=False) + "\n"
        ).encode(),
    )
    prepared = invoke("prepare", root, source)
    assert prepared.returncode == 0, (prepared.stdout, prepared.stderr)
    result = json.loads(prepared.stdout)
    assert set(result) == {
        "correlation_id",
        "event_id",
        "gate_receipt_sha256",
        "schema",
        "seat_id",
        "state",
        "topology_sha256",
        "transaction_sha256",
    }
    assert result["schema"] == RESULT_SCHEMA and result["state"] == "prepared"
    assert result["seat_id"] == SEAT and result["event_id"] == EVENT
    assert result["correlation_id"] == CORRELATION
    expected_receipt, expected_transaction = expected_artifacts(root, value)
    actual_receipt_bytes = receipt_path(root).read_bytes()
    actual_transaction_bytes = transaction_path(root).read_bytes()
    assert actual_receipt_bytes == canonical_bytes(expected_receipt)
    assert actual_transaction_bytes == canonical_bytes(expected_transaction)
    assert (
        hashlib.sha256(actual_receipt_bytes).hexdigest()
        == result["gate_receipt_sha256"]
    )
    assert (
        hashlib.sha256(actual_transaction_bytes).hexdigest()
        == result["transaction_sha256"]
    )
    for path in (receipt_path(root), transaction_path(root)):
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        assert path.stat().st_uid == os.geteuid()
    for path in (
        root / "gate-receipts",
        root / "gate-receipts" / SEAT,
        root / "transactions",
        root / "transactions" / SEAT,
    ):
        assert path.is_dir() and stat.S_IMODE(path.stat().st_mode) == 0o700
        assert path.stat().st_uid == os.geteuid()
    assert expected_transaction["gate_receipt_sha256"] == result["gate_receipt_sha256"]
    assert expected_receipt["receipt_path"] == expected_transaction["gate_receipt_path"]
    assert expected_receipt["text_hash"] == expected_receipt["content_hash"]
    ready = invoke(
        "preflight",
        root,
        source,
        receipt_sha256=result["gate_receipt_sha256"],
        transaction_sha256=result["transaction_sha256"],
    )
    assert ready.returncode == 0, (ready.stdout, ready.stderr)
    ready_result = json.loads(ready.stdout)
    assert ready_result == {**result, "state": "ready"}


def validate_source_refusals(base: Path) -> int:
    valid = approval()
    cases: list[tuple[str, dict[str, Any] | None, bytes | None, int]] = [
        ("extra-field", {**valid, "unexpected": True}, None, 0o400),
        ("wrong-schema", {**valid, "schema": "wrong"}, None, 0o400),
        ("wrong-operation", {**valid, "operation": "post"}, None, 0o400),
        ("wrong-platform", {**valid, "platform": "x"}, None, 0o400),
        ("wrong-display", {**valid, "display": ":0"}, None, 0o400),
        ("wrong-seat", {**valid, "seat_id": "other"}, None, 0o400),
        ("wrong-event", {**valid, "event_id": "other"}, None, 0o400),
        ("wrong-correlation", {**valid, "correlation_id": "other"}, None, 0o400),
        ("bad-action", {**valid, "action_id": "spaces are invalid"}, None, 0o400),
        ("bad-activity", {**valid, "selected_activity": "activity-1"}, None, 0o400),
        (
            "bad-body-hash",
            {**valid, "selected_post_body_sha256": "B" * 64},
            None,
            0o400,
        ),
        ("bad-source-hash", {**valid, "source_artifact_sha256": "short"}, None, 0o400),
        ("bad-like", {**valid, "like_authorized": 1}, None, 0o400),
        ("empty-author", {**valid, "expected_author_name": ""}, None, 0o400),
        ("spaced-author", {**valid, "expected_author_name": f" {AUTHOR}"}, None, 0o400),
        (
            "control-author",
            {**valid, "expected_author_name": "Private\nAuthor"},
            None,
            0o400,
        ),
        ("empty-text", {**valid, "text": ""}, None, 0o400),
        ("nul-text", {**valid, "text": "bad\x00text"}, None, 0o400),
        ("no-gates", {**valid, "gates": []}, None, 0o400),
        (
            "failed-gate",
            {**valid, "gates": [{"gate": "cannot_lie", "passed": False, "ev": {}}]},
            None,
            0o400,
        ),
        (
            "bad-gate-name",
            {**valid, "gates": [{"gate": "Cannot Lie", "passed": True, "ev": {}}]},
            None,
            0o400,
        ),
        (
            "bad-gate-evidence",
            {**valid, "gates": [{"gate": "cannot_lie", "passed": True, "ev": "yes"}]},
            None,
            0o400,
        ),
        (
            "extra-gate-field",
            {
                **valid,
                "gates": [
                    {"gate": "cannot_lie", "passed": True, "ev": {}, "extra": True}
                ],
            },
            None,
            0o400,
        ),
        (
            "duplicate-gate",
            {**valid, "gates": [valid["gates"][0], valid["gates"][0]]},
            None,
            0o400,
        ),
        ("missing-cannot-lie", {**valid, "gates": [valid["gates"][1]]}, None, 0o400),
        ("wrong-mode", valid, None, 0o600),
        ("non-object", None, b"[]", 0o400),
    ]
    for field in tuple(valid):
        cases.append(
            (
                f"missing-{field}",
                {key: item for key, item in valid.items() if key != field},
                None,
                0o400,
            )
        )
    duplicate_raw = canonical_bytes(valid).replace(
        b'"action_id":"linkedin-comment-action-001"',
        b'"action_id":"linkedin-comment-action-001","action_id":"duplicate"',
    )
    cases.append(("duplicate-field", None, duplicate_raw, 0o400))
    nan_raw = canonical_bytes(valid).replace(
        b'"like_authorized":true', b'"like_authorized":NaN'
    )
    cases.append(("nan", None, nan_raw, 0o400))
    for name, value, raw_bytes, mode in cases:
        root, source, _ = fixture(
            base / name,
            value=value,
            raw_bytes=raw_bytes,
            source_mode=mode,
        )
        require_refusal(invoke("prepare", root, source), "approval_source_invalid")
    return len(cases)


def validate_topology_refusals(base: Path) -> int:
    root, source, _ = fixture(base / "wrong-root-mode")
    os.chmod(root, 0o755)
    require_refusal(invoke("prepare", root, source), "private_root_invalid")

    root, source, _ = fixture(base / "wrong-source-parent-mode")
    os.chmod(source.parent, 0o755)
    require_refusal(invoke("prepare", root, source), "topology_invalid")

    root, source, _ = fixture(base / "symlink-source")
    target = source.with_name("target.json")
    source.rename(target)
    source.symlink_to(target)
    require_refusal(invoke("prepare", root, source), "approval_source_invalid")

    root, source, _ = fixture(base / "existing-receipt")
    write_private_file(receipt_path(root), b"{}")
    require_refusal(invoke("prepare", root, source), "identity_spent")

    root, source, _ = fixture(base / "existing-transaction")
    write_private_file(transaction_path(root), b"{}")
    require_refusal(invoke("prepare", root, source), "identity_spent")

    root, source, _ = fixture(base / "wrong-output-parent-mode")
    (root / "gate-receipts" / SEAT).mkdir(mode=0o700, parents=True)
    os.chmod(root / "gate-receipts" / SEAT, 0o755)
    require_refusal(invoke("prepare", root, source), "topology_invalid")
    return 6


def validate_preflight_refusals(base: Path) -> int:
    root, source, _ = fixture(base / "digest")
    prepared = invoke("prepare", root, source)
    assert prepared.returncode == 0
    result = json.loads(prepared.stdout)
    wrong = "0" * 64 if result["transaction_sha256"] != "0" * 64 else "1" * 64
    require_refusal(
        invoke(
            "preflight",
            root,
            source,
            receipt_sha256=result["gate_receipt_sha256"],
            transaction_sha256=wrong,
        ),
        "digest_mismatch",
    )

    root, source, _ = fixture(base / "changed-source")
    prepared = invoke("prepare", root, source)
    assert prepared.returncode == 0
    result = json.loads(prepared.stdout)
    os.chmod(source, 0o600)
    source.write_bytes(canonical_bytes(approval(text="Changed private text.")))
    os.chmod(source, 0o400)
    require_refusal(
        invoke(
            "preflight",
            root,
            source,
            receipt_sha256=result["gate_receipt_sha256"],
            transaction_sha256=result["transaction_sha256"],
        ),
        "gate_receipt_invalid",
    )
    return 2


def validate_public_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(approval())
    assert (
        schema["properties"]["schema"]["const"]
        == "taey_linkedin_private_comment_approval_v1"
    )
    gate_items = schema["properties"]["gates"]["items"]
    assert gate_items["additionalProperties"] is False
    assert set(gate_items["required"]) == {"gate", "passed", "ev"}
    assert gate_items["properties"]["passed"]["const"] is True


def validate_static_boundary() -> None:
    source = COMMAND.read_text(encoding="utf-8")
    normalized_source = " ".join(source.split())
    assert (
        '"transaction": private_root / "transactions" / seat_id / f"{correlation_id}.json"'
        in normalized_source
    )
    assert (
        '"receipt": private_root / "gate-receipts" / seat_id / f"{correlation_id}.json"'
        in normalized_source
    )
    assert source.index(
        'write_new_private_json(paths["receipt"], receipt)'
    ) < source.index('write_new_private_json(paths["transaction"], transaction)')
    assert "stat.S_IMODE(metadata.st_mode) != 0o700" in source
    assert "write_new_private_json" in source
    assert "build_snapshot" not in source
    assert "click" not in source
    result_source = source.split("def _result(", 1)[1].split("def _prepare(", 1)[0]
    for private_field in ("text", "expected_author_name", "receipt_path"):
        assert private_field not in result_source


def main() -> int:
    validate_public_schema()
    validate_static_boundary()
    with tempfile.TemporaryDirectory(
        prefix="linkedin-comment-materialization-validator-"
    ) as raw:
        base = Path(raw)
        validate_happy_path(base / "happy")
        source_cases = validate_source_refusals(base / "sources")
        topology_cases = validate_topology_refusals(base / "topology")
        preflight_cases = validate_preflight_refusals(base / "preflight")
    print(
        json.dumps(
            {
                "adversarial_cases": source_cases + topology_cases + preflight_cases,
                "emitted_modes": ["0400", "0400"],
                "private_values_on_argv_or_results": False,
                "profile": "linkedin-comment-materialization",
                "status": "PASS",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
