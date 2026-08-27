#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PRIVATE_ROOT_ENV = "TAEY_REVENUE_UI_PRIVATE_ROOT"
APPROVAL_SOURCE_ENV = "TAEY_LINKEDIN_COMMENT_APPROVAL_SOURCE"
SOURCE_SCHEMA = "taey_linkedin_private_comment_approval_v1"
TRANSACTION_SCHEMA = "taey_revenue_ui_private_comment_v1"
RECEIPT_VERSION = "linkedin_gate_signoff_v1"
RECEIPT_KIND = "feed_comment"
RESULT_SCHEMA = "taey_linkedin_comment_materialization_result_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DISPLAY_RE = re.compile(r"^:[1-9][0-9]*$")
_SEAT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_TRACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_ACTION_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_GATE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SOURCE_FIELDS = frozenset(
    {
        "schema",
        "operation",
        "platform",
        "display",
        "seat_id",
        "event_id",
        "correlation_id",
        "action_id",
        "selected_activity",
        "selected_post_body_sha256",
        "source_artifact_sha256",
        "like_authorized",
        "expected_author_name",
        "text",
        "gates",
    }
)


class MaterializationRefused(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _strict_object(raw_bytes: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _token: (_ for _ in ()).throw(ValueError("constant")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise MaterializationRefused("approval_source_invalid") from None
    if not isinstance(value, dict):
        raise MaterializationRefused("approval_source_invalid")
    return value


def _environment_path(name: str) -> Path:
    value = os.environ.get(name, "")
    if not value:
        raise MaterializationRefused("environment_invalid")
    return Path(value)


def _seat_id(value: str) -> str:
    if not _SEAT_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("seat identity is invalid")
    return value


def _trace_id(value: str) -> str:
    if not _TRACE_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("trace identity is invalid")
    return value


def _sha256(value: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("digest must be lowercase SHA-256")
    return value


def _private_root() -> Path:
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        validate_external_private_root,
    )

    try:
        return validate_external_private_root(
            _environment_path(PRIVATE_ROOT_ENV), REPO_ROOT
        )
    except (LinkedInJobsContractError, MaterializationRefused, OSError, ValueError):
        raise MaterializationRefused("private_root_invalid") from None


def _derived_paths(
    private_root: Path, seat_id: str, correlation_id: str
) -> dict[str, Path]:
    paths = {
        "transaction_root": private_root / "transactions",
        "transaction_parent": private_root / "transactions" / seat_id,
        "transaction": private_root
        / "transactions"
        / seat_id
        / f"{correlation_id}.json",
        "receipt_root": private_root / "gate-receipts",
        "receipt_parent": private_root / "gate-receipts" / seat_id,
        "receipt": private_root / "gate-receipts" / seat_id / f"{correlation_id}.json",
    }
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        validate_path_beneath_private_root,
    )

    try:
        for label, path in paths.items():
            validate_path_beneath_private_root(path, private_root, label)
    except (LinkedInJobsContractError, OSError, ValueError):
        raise MaterializationRefused("topology_invalid") from None
    return paths


def _validate_private_directory(path: Path) -> None:
    try:
        metadata = os.lstat(path)
    except OSError:
        raise MaterializationRefused("topology_invalid") from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.geteuid()
    ):
        raise MaterializationRefused("topology_invalid")


def _sync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_or_validate_directory(path: Path) -> None:
    if os.path.lexists(path):
        _validate_private_directory(path)
        return
    try:
        os.mkdir(path, 0o700)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _sync_directory(path.parent)
        _validate_private_directory(path)
    except (FileExistsError, OSError):
        raise MaterializationRefused("topology_invalid") from None


def _validate_author(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise MaterializationRefused("approval_source_invalid")
    return value


def _validate_text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > 1024 * 1024
    ):
        raise MaterializationRefused("approval_source_invalid")
    return value


def _validate_gates(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        raise MaterializationRefused("approval_source_invalid")
    gates: list[dict[str, Any]] = []
    names: set[str] = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"gate", "passed", "ev"}:
            raise MaterializationRefused("approval_source_invalid")
        name = row.get("gate")
        evidence = row.get("ev")
        if (
            not isinstance(name, str)
            or not _GATE_RE.fullmatch(name)
            or name in names
            or row.get("passed") is not True
            or not isinstance(evidence, dict)
        ):
            raise MaterializationRefused("approval_source_invalid")
        names.add(name)
        gates.append({"ev": evidence, "gate": name, "passed": True})
    if "cannot_lie" not in names:
        raise MaterializationRefused("approval_source_invalid")
    return gates


def _read_source(
    private_root: Path,
    seat_id: str,
    event_id: str,
    correlation_id: str,
) -> dict[str, Any]:
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        read_owned_private_bytes,
        validate_path_beneath_private_root,
    )

    try:
        source_path = validate_path_beneath_private_root(
            _environment_path(APPROVAL_SOURCE_ENV),
            private_root,
            "approval source",
        )
        parents: list[Path] = []
        current = source_path.parent
        while current != private_root:
            parents.append(current)
            current = current.parent
        for parent in reversed(parents):
            _validate_private_directory(parent)
        raw_bytes = read_owned_private_bytes(source_path, "approval source")
        if len(raw_bytes) > 4 * 1024 * 1024:
            raise MaterializationRefused("approval_source_invalid")
        source = _strict_object(raw_bytes)
    except MaterializationRefused:
        raise
    except (LinkedInJobsContractError, OSError, ValueError):
        raise MaterializationRefused("approval_source_invalid") from None
    if set(source) != _SOURCE_FIELDS:
        raise MaterializationRefused("approval_source_invalid")
    fixed = {
        "schema": SOURCE_SCHEMA,
        "operation": "comment",
        "platform": "linkedin",
        "seat_id": seat_id,
        "event_id": event_id,
        "correlation_id": correlation_id,
    }
    if any(source.get(key) != value for key, value in fixed.items()):
        raise MaterializationRefused("approval_source_invalid")
    display = source.get("display")
    action_id = source.get("action_id")
    activity = source.get("selected_activity")
    if (
        not isinstance(display, str)
        or not _DISPLAY_RE.fullmatch(display)
        or not isinstance(action_id, str)
        or not _ACTION_RE.fullmatch(action_id)
        or not isinstance(activity, str)
        or not activity.isdigit()
        or any(
            not isinstance(source.get(field), str)
            or not _SHA256_RE.fullmatch(source[field])
            for field in ("selected_post_body_sha256", "source_artifact_sha256")
        )
        or not isinstance(source.get("like_authorized"), bool)
    ):
        raise MaterializationRefused("approval_source_invalid")
    return {
        **source,
        "expected_author_name": _validate_author(source.get("expected_author_name")),
        "text": _validate_text(source.get("text")),
        "gates": _validate_gates(source.get("gates")),
    }


def _normalized_text_sha256(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text.strip()).encode("utf-8")).hexdigest()


def _artifacts(
    source: dict[str, Any], receipt_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    from consultation_v2.linkedin_jobs_contract import canonical_json_bytes, sha256_hex

    text = source["text"]
    normalized_text_sha256 = _normalized_text_sha256(text)
    receipt = {
        "action_id": source["action_id"],
        "claims_traced": True,
        "content_hash": normalized_text_sha256,
        "failing_gate": None,
        "gates": source["gates"],
        "kind": RECEIPT_KIND,
        "packet_kind": "comment",
        "receipt_path": str(receipt_path),
        "receipt_version": RECEIPT_VERSION,
        "source_activity_id": source["selected_activity"],
        "source_artifact_sha256": source["source_artifact_sha256"],
        "text_hash": normalized_text_sha256,
        "verdict": "signoff",
    }
    receipt_sha256 = sha256_hex(canonical_json_bytes(receipt))
    transaction = {
        "action_id": source["action_id"],
        "correlation_id": source["correlation_id"],
        "display": source["display"],
        "event_id": source["event_id"],
        "expected_author_name": source["expected_author_name"],
        "gate_receipt_kind": RECEIPT_KIND,
        "gate_receipt_path": str(receipt_path),
        "gate_receipt_sha256": receipt_sha256,
        "gate_receipt_version": RECEIPT_VERSION,
        "like_authorized": source["like_authorized"],
        "operation": "comment",
        "platform": "linkedin",
        "schema": TRANSACTION_SCHEMA,
        "seat_id": source["seat_id"],
        "selected_activity": source["selected_activity"],
        "selected_post_body_sha256": source["selected_post_body_sha256"],
        "source_artifact_sha256": source["source_artifact_sha256"],
        "text": text,
        "text_sha256": sha256_hex(text.encode("utf-8")),
    }
    return receipt, transaction


def _validate_artifacts(
    paths: dict[str, Path],
    source: dict[str, Any],
    expected_receipt_sha256: str,
    expected_transaction_sha256: str,
) -> tuple[str, str]:
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        canonical_json_bytes,
        read_owned_private_bytes,
        sha256_hex,
    )

    receipt, transaction = _artifacts(source, paths["receipt"])
    try:
        _validate_private_directory(paths["receipt_root"])
        _validate_private_directory(paths["receipt_parent"])
        _validate_private_directory(paths["transaction_root"])
        _validate_private_directory(paths["transaction_parent"])
        receipt_bytes = read_owned_private_bytes(paths["receipt"], "gate receipt")
        transaction_bytes = read_owned_private_bytes(
            paths["transaction"], "transaction"
        )
    except (LinkedInJobsContractError, OSError):
        raise MaterializationRefused("topology_invalid") from None
    receipt_sha256 = sha256_hex(receipt_bytes)
    transaction_sha256 = sha256_hex(transaction_bytes)
    if receipt_bytes != canonical_json_bytes(receipt):
        raise MaterializationRefused("gate_receipt_invalid")
    if transaction_bytes != canonical_json_bytes(transaction):
        raise MaterializationRefused("transaction_invalid")
    if (
        receipt_sha256 != expected_receipt_sha256
        or transaction_sha256 != expected_transaction_sha256
    ):
        raise MaterializationRefused("digest_mismatch")
    return receipt_sha256, transaction_sha256


def _topology_sha256(
    source: dict[str, Any],
    receipt_sha256: str,
    transaction_sha256: str,
) -> str:
    from consultation_v2.linkedin_jobs_contract import canonical_json_bytes, sha256_hex

    return sha256_hex(
        canonical_json_bytes(
            {
                "correlation_id": source["correlation_id"],
                "directory_mode": "0700",
                "event_id": source["event_id"],
                "gate_receipt_mode": "0400",
                "gate_receipt_sha256": receipt_sha256,
                "schema": "taey_linkedin_comment_private_topology_v1",
                "seat_id": source["seat_id"],
                "transaction_mode": "0400",
                "transaction_sha256": transaction_sha256,
            }
        )
    )


def _result(
    state: str,
    source: dict[str, Any],
    receipt_sha256: str,
    transaction_sha256: str,
) -> dict[str, str]:
    return {
        "correlation_id": source["correlation_id"],
        "event_id": source["event_id"],
        "gate_receipt_sha256": receipt_sha256,
        "schema": RESULT_SCHEMA,
        "seat_id": source["seat_id"],
        "state": state,
        "topology_sha256": _topology_sha256(source, receipt_sha256, transaction_sha256),
        "transaction_sha256": transaction_sha256,
    }


def _prepare(paths: dict[str, Path], source: dict[str, Any]) -> dict[str, str]:
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        canonical_json_bytes,
        sha256_hex,
        write_new_private_json,
    )

    if os.path.lexists(paths["receipt"]) or os.path.lexists(paths["transaction"]):
        raise MaterializationRefused("identity_spent")
    for name in (
        "receipt_root",
        "receipt_parent",
        "transaction_root",
        "transaction_parent",
    ):
        _create_or_validate_directory(paths[name])
    receipt, transaction = _artifacts(source, paths["receipt"])
    receipt_sha256 = sha256_hex(canonical_json_bytes(receipt))
    transaction_sha256 = sha256_hex(canonical_json_bytes(transaction))
    try:
        receipt_bytes = write_new_private_json(paths["receipt"], receipt)
        if sha256_hex(receipt_bytes) != receipt_sha256:
            raise MaterializationRefused("gate_receipt_invalid")
        transaction_bytes = write_new_private_json(paths["transaction"], transaction)
        if sha256_hex(transaction_bytes) != transaction_sha256:
            raise MaterializationRefused("transaction_invalid")
    except MaterializationRefused:
        raise
    except (FileExistsError, LinkedInJobsContractError, OSError):
        raise MaterializationRefused("artifact_write_refused") from None
    _validate_artifacts(paths, source, receipt_sha256, transaction_sha256)
    return _result("prepared", source, receipt_sha256, transaction_sha256)


def _preflight(
    paths: dict[str, Path],
    source: dict[str, Any],
    expected_receipt_sha256: str,
    expected_transaction_sha256: str,
) -> dict[str, str]:
    receipt_sha256, transaction_sha256 = _validate_artifacts(
        paths,
        source,
        expected_receipt_sha256,
        expected_transaction_sha256,
    )
    return _result("ready", source, receipt_sha256, transaction_sha256)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize one immutable private LinkedIn comment approval.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "preflight"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--seat-id", required=True, type=_seat_id)
        subparser.add_argument("--event-id", required=True, type=_trace_id)
        subparser.add_argument("--correlation-id", required=True, type=_trace_id)
        if command == "preflight":
            subparser.add_argument(
                "--expected-gate-receipt-sha256", required=True, type=_sha256
            )
            subparser.add_argument(
                "--expected-transaction-sha256", required=True, type=_sha256
            )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        private_root = _private_root()
        paths = _derived_paths(private_root, args.seat_id, args.correlation_id)
        source = _read_source(
            private_root,
            args.seat_id,
            args.event_id,
            args.correlation_id,
        )
        if args.command == "prepare":
            result = _prepare(paths, source)
        else:
            result = _preflight(
                paths,
                source,
                args.expected_gate_receipt_sha256,
                args.expected_transaction_sha256,
            )
    except MaterializationRefused as exc:
        failure_code = exc.code
    except Exception:
        failure_code = "internal_refused"
    else:
        sys.stdout.buffer.write(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
        return 0
    refusal = {
        "correlation_id": args.correlation_id,
        "event_id": args.event_id,
        "failure_code": failure_code,
        "schema": RESULT_SCHEMA,
        "seat_id": args.seat_id,
        "state": "refused",
    }
    sys.stderr.buffer.write(
        json.dumps(refusal, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
