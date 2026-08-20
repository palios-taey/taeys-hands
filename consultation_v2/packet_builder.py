from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Any, Mapping, Sequence


IDENTITY_BY_PLATFORM = {
    "chatgpt": "IDENTITY_HORIZON.md",
    "claude": "IDENTITY_GAIA.md",
    "gemini": "IDENTITY_COSMOS.md",
    "grok": "IDENTITY_LOGOS.md",
    "perplexity": "IDENTITY_CLARITY.md",
}

PROHIBITED_ACTIONS = (
    "attachment_staging",
    "display_mutation",
    "profile_mutation",
    "restart",
    "send",
    "signing",
    "taey_task_creation",
    "training",
    "ui_operation",
)

TOP_LEVEL_SPEC_KEYS = frozenset(
    {
        "builder",
        "canonical_task_id",
        "excluded_stale",
        "expected",
        "fresh_neutrality",
        "governance",
        "locator_ruling",
        "negative_receipts",
        "output_root",
        "packet_contract",
        "rejected_input_roots",
        "request_id",
        "schema_version",
        "superseded_task_id",
        "task_sources",
        "worker_spec",
    }
)

RECEIPT_KEYS = frozenset(
    {
        "actions",
        "attachments",
        "build_spec",
        "builder",
        "canonical_task_id",
        "checks",
        "destination",
        "files",
        "fresh_neutrality",
        "generated_manifest",
        "governance_sources",
        "locator_ruling",
        "negative_controls",
        "packet_contract",
        "prompt",
        "quarantined_roots",
        "root",
        "schema_version",
        "send_task",
        "sources",
        "superseded_task_id",
        "worker_spec",
    }
)


class PacketBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceBytes:
    record: dict[str, Any]
    data: bytes


@dataclass(frozen=True)
class DestinationBytes:
    platform: str
    display_name: str
    identity: SourceBytes
    bundle_a_basename: str
    bundle_a: bytes
    prompt_basename: str
    receipt_basename: str
    send_task_id: str
    expected_absolute_paths: tuple[str, ...]


@dataclass(frozen=True)
class PreparedBuild:
    spec_path: Path
    spec: dict[str, Any]
    build_spec_record: dict[str, Any]
    output_root: Path
    kernel: SourceBytes
    spotlight: SourceBytes
    destinations: tuple[DestinationBytes, ...]
    task_sources: tuple[SourceBytes, ...]
    generated_manifest_record: dict[str, Any]
    generated_manifest: bytes
    bundle_b_basename_by_platform: dict[str, str]
    bundle_b: bytes
    prompt: bytes
    packet_contract: dict[str, Any]
    fresh_neutrality: dict[str, Any]
    worker_spec: dict[str, dict[str, Any]]
    builder_record: dict[str, Any]
    rejected_roots: tuple[Path, ...]
    negative_controls: tuple[dict[str, Any], ...]


def _strict_json(raw: bytes, context: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PacketBuildError(f"{context} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                PacketBuildError(f"{context} contains non-JSON constant {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketBuildError(f"{context} is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PacketBuildError(f"{context} must be a JSON object")
    return value


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_exact_keys(value: Mapping[str, Any], keys: frozenset[str], context: str) -> None:
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise PacketBuildError(f"{context} fields differ: missing={missing}, extra={extra}")


def _require_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise PacketBuildError(f"{context} must be a non-empty string")
    return value


def _require_int(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PacketBuildError(f"{context} must be a non-negative integer")
    return value


def _absolute_path(value: Any, context: str) -> Path:
    text = _require_text(value, context)
    path = Path(text)
    if not path.is_absolute() or str(path) != os.path.abspath(text):
        raise PacketBuildError(f"{context} must be a normalized absolute path")
    return path


def _mode_text(mode: int) -> str:
    return f"{stat.S_IMODE(mode):04o}"


def _observed_path_record(path: Path, expected_type: str) -> dict[str, Any]:
    metadata = os.stat(path, follow_symlinks=False)
    if expected_type == "directory" and not stat.S_ISDIR(metadata.st_mode):
        raise PacketBuildError(f"{path} is not a directory")
    if expected_type == "regular" and not stat.S_ISREG(metadata.st_mode):
        raise PacketBuildError(f"{path} is not a regular file")
    return {
        "path" if expected_type == "directory" else "basename": (
            str(path) if expected_type == "directory" else path.name
        ),
        "type": expected_type,
        "owner_uid": metadata.st_uid,
        "owner_gid": metadata.st_gid,
        "mode": _mode_text(metadata.st_mode),
    }


def _assert_no_symlink_components(path: Path, *, include_leaf: bool) -> None:
    current = Path(path.anchor)
    parts = path.parts[1:] if path.is_absolute() else path.parts
    limit = len(parts) if include_leaf else max(0, len(parts) - 1)
    for part in parts[:limit]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise PacketBuildError(f"symlink path component is forbidden: {current}")


def _read_regular_file(path: Path, context: str) -> bytes:
    _assert_no_symlink_components(path, include_leaf=True)
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PacketBuildError(f"cannot open {context} at {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PacketBuildError(f"{context} is not a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
    finally:
        os.close(descriptor)
    if not data:
        raise PacketBuildError(f"{context} is empty: {path}")
    return data


def _binding_record(binding: Mapping[str, Any], context: str) -> dict[str, Any]:
    allowed = frozenset({"locator", "bytes", "sha256", "public_commit", "verdict", "prompting_lint"})
    unknown = frozenset(binding) - allowed
    if unknown:
        raise PacketBuildError(f"{context} has unknown fields: {sorted(unknown)}")
    path = _absolute_path(binding.get("locator"), f"{context}.locator")
    data = _read_regular_file(path, context)
    expected_bytes = _require_int(binding.get("bytes"), f"{context}.bytes")
    expected_sha = _require_text(binding.get("sha256"), f"{context}.sha256")
    if len(data) != expected_bytes or _sha256(data) != expected_sha:
        raise PacketBuildError(f"{context} content address mismatch at {path}")
    record: dict[str, Any] = {
        "locator": str(path),
        "bytes": len(data),
        "sha256": _sha256(data),
    }
    for key in ("public_commit", "verdict", "prompting_lint"):
        if key in binding:
            record[key] = _require_text(binding[key], f"{context}.{key}")
    return record


def _git_observation(path: Path, expected_commit: str) -> dict[str, str]:
    root_run = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        check=False,  # lint-allow: nonzero is translated to a path-specific PacketBuildError below
        capture_output=True,
        text=True,
    )
    if root_run.returncode != 0:
        raise PacketBuildError(f"Git-tracked source has no checkout: {path}")
    root = Path(root_run.stdout.strip())
    commit_run = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    observed_commit = commit_run.stdout.strip()
    if observed_commit != expected_commit:
        raise PacketBuildError(
            f"Git checkout mismatch for {path}: expected {expected_commit}, observed {observed_commit}"
        )
    relative = path.relative_to(root)
    tracked_run = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", str(relative)],
        check=False,  # lint-allow: untracked sources are rejected from the inspected returncode below
        capture_output=True,
        text=True,
    )
    if tracked_run.returncode != 0:
        raise PacketBuildError(f"expected Git-tracked source is not tracked: {path}")
    return {"checkout_root": str(root), "observed_commit": observed_commit}


def _source_bytes(source: Mapping[str, Any], context: str) -> SourceBytes:
    required = {"authorized", "bytes", "git_tracked", "locator", "logical", "section", "sha256"}
    git_tracked = source.get("git_tracked")
    if git_tracked is True:
        required.add("expected_commit")
    _require_exact_keys(source, frozenset(required), context)
    if source.get("authorized") is not True:
        raise PacketBuildError(f"{context} is not explicitly authorized for transmission")
    path = _absolute_path(source["locator"], f"{context}.locator")
    logical = _require_text(source["logical"], f"{context}.logical")
    section = _require_text(source["section"], f"{context}.section")
    data = _read_regular_file(path, context)
    expected_bytes = _require_int(source["bytes"], f"{context}.bytes")
    expected_sha = _require_text(source["sha256"], f"{context}.sha256")
    if len(data) != expected_bytes or _sha256(data) != expected_sha:
        raise PacketBuildError(f"{context} content address mismatch at {path}")
    record: dict[str, Any] = {
        "logical": logical,
        "locator": str(path),
        "bytes": len(data),
        "sha256": _sha256(data),
        "git_tracked": bool(git_tracked),
        "authorized": True,
        "section": section,
    }
    if git_tracked is True:
        expected_commit = _require_text(source["expected_commit"], f"{context}.expected_commit")
        record["public_commit"] = expected_commit
        record.update(_git_observation(path, expected_commit))
    elif git_tracked is not False:
        raise PacketBuildError(f"{context}.git_tracked must be boolean")
    return SourceBytes(record=record, data=data)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _assert_not_rejected_input(path: Path, rejected_roots: Sequence[Path], context: str) -> None:
    for root in rejected_roots:
        if _inside(path, root):
            raise PacketBuildError(f"{context} resolves inside rejected candidate root {root}")


def _validate_generated_bundle_metadata(
    request_id: str,
    task_sources: Sequence[SourceBytes],
    manifest: Mapping[str, Any],
) -> None:
    generated_fields: dict[str, Any] = {
        "request_id": request_id,
        "source_headers": [
            {
                "logical": source.record["logical"],
                "section": source.record["section"],
            }
            for source in task_sources
        ],
        "manifest": manifest,
    }

    def reject_operator_paths(value: Any, context: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                reject_operator_paths(item, f"{context}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                reject_operator_paths(item, f"{context}[{index}]")
        elif isinstance(value, str) and "/home/" in value:
            raise PacketBuildError(
                f"Bundle B generated metadata contains an operator-local absolute path at {context}"
            )

    reject_operator_paths(generated_fields, "bundle_b_generated")


def _render_manifest(task_sources: Sequence[SourceBytes], excluded_stale: Sequence[str]) -> bytes:
    manifest_sources: list[dict[str, Any]] = []
    for source in task_sources:
        record: dict[str, Any] = {
            "bytes": source.record["bytes"],
            "git_tracked": source.record["git_tracked"],
            "logical": source.record["logical"],
        }
        if source.record["git_tracked"]:
            record["public_commit"] = source.record["public_commit"]
        record["sha256"] = source.record["sha256"]
        manifest_sources.append(record)
    manifest = {
        "excluded_stale": list(excluded_stale),
        "generated_attached_provenance_manifest": {
            "logical": "generated_attached_provenance_manifest.json",
            "note": "this file",
        },
        "task_sources": manifest_sources,
    }
    return _json_bytes(manifest)


def _render_bundle_a(
    request_id: str,
    display_name: str,
    kernel: SourceBytes,
    identity: SourceBytes,
    spotlight: SourceBytes,
) -> bytes:
    return b"".join(
        (
            f"# {request_id} {display_name} Bundle A - Governance\n\n## FAMILY KERNEL\n\n# FAMILY_KERNEL.md\n".encode(),
            kernel.data,
            f"\n\n## IDENTITY\n\n# {identity.record['logical']}\n".encode(),
            identity.data,
            b"\n\n## SPOTLIGHT STANDARD FOR INTEGRITY\n\n# SPOTLIGHT_STANDARD_FOR_INTEGRITY.md\n",
            spotlight.data,
            b"\n",
        )
    )


def _render_bundle_b(
    request_id: str,
    task_sources: Sequence[SourceBytes],
    generated_manifest_segment: bytes,
) -> bytes:
    parts: list[bytes] = [f"# {request_id} Bundle B - Task".encode()]
    for source in task_sources:
        parts.append(
            f"\n\n## {source.record['section']}\n\n# {source.record['logical']}\n".encode()
        )
        parts.append(source.data)
    parts.extend((b"\n\n", generated_manifest_segment))
    return b"".join(parts)


def _expected_blob(data: bytes, expected: Mapping[str, Any], context: str) -> dict[str, Any]:
    _require_exact_keys(expected, frozenset({"bytes", "sha256"}), context)
    expected_bytes = _require_int(expected["bytes"], f"{context}.bytes")
    expected_sha = _require_text(expected["sha256"], f"{context}.sha256")
    observed_sha = _sha256(data)
    if len(data) != expected_bytes or observed_sha != expected_sha:
        raise PacketBuildError(
            f"{context} mismatch: expected {expected_bytes}/{expected_sha}, observed {len(data)}/{observed_sha}"
        )
    return {"bytes": len(data), "sha256": observed_sha}


def _validate_source_inclusion(bundle: bytes, sources: Sequence[SourceBytes], context: str) -> None:
    positions: list[int] = []
    for source in sources:
        count = bundle.count(source.data)
        if count != 1:
            raise PacketBuildError(
                f"{context} contains {source.record['logical']} {count} times instead of once"
            )
        positions.append(bundle.index(source.data))
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise PacketBuildError(f"{context} source order is not deterministic")


def _validate_basename(value: Any, context: str) -> str:
    text = _require_text(value, context)
    if Path(text).name != text or text in {".", ".."}:
        raise PacketBuildError(f"{context} must be a basename")
    return text


def _verify_builder(binding: Mapping[str, Any]) -> dict[str, Any]:
    _require_exact_keys(
        binding,
        frozenset({"commit", "module", "module_sha256", "repo_root"}),
        "builder",
    )
    repo_root = _absolute_path(binding["repo_root"], "builder.repo_root")
    module = _require_text(binding["module"], "builder.module")
    module_path = repo_root / module
    if module_path.resolve() != Path(__file__).resolve():
        raise PacketBuildError("builder.module does not identify the executing module")
    expected_commit = _require_text(binding["commit"], "builder.commit")
    commit_run = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    observed_commit = commit_run.stdout.strip()
    if observed_commit != expected_commit:
        raise PacketBuildError(
            f"builder commit mismatch: expected {expected_commit}, observed {observed_commit}"
        )
    module_data = _read_regular_file(module_path, "builder module")
    expected_sha = _require_text(binding["module_sha256"], "builder.module_sha256")
    if _sha256(module_data) != expected_sha:
        raise PacketBuildError("builder module hash mismatch")
    return {
        "repo_root": str(repo_root),
        "commit": observed_commit,
        "module": module,
        "module_sha256": _sha256(module_data),
    }


def _validate_prompt(text: Any, expected: Mapping[str, Any]) -> bytes:
    prompt = _require_text(text, "prompt.text")
    if not prompt.startswith("Read both attached files fully before answering. "):
        raise PacketBuildError("prompt does not begin with the contract read-both instruction")
    if not prompt.endswith(
        "If either attachment is unavailable or incomplete, state that and stop."
    ):
        raise PacketBuildError("prompt does not end with the contract stop instruction")
    prompt_bytes = prompt.encode("utf-8")
    _expected_blob(prompt_bytes, expected, "expected.prompt")
    return prompt_bytes


def _snapshot_root(root: Path) -> dict[str, Any]:
    _assert_no_symlink_components(root, include_leaf=True)
    root_record = _observed_path_record(root, "directory")
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        metadata = os.lstat(path)
        relative = str(path.relative_to(root))
        if stat.S_ISREG(metadata.st_mode):
            data = _read_regular_file(path, f"quarantine file {relative}")
            files.append({"path": relative, "type": "regular", "bytes": len(data), "sha256": _sha256(data)})
        elif stat.S_ISDIR(metadata.st_mode):
            files.append({"path": relative, "type": "directory"})
        elif stat.S_ISLNK(metadata.st_mode):
            files.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
        else:
            files.append({"path": relative, "type": "other", "mode": _mode_text(metadata.st_mode)})
    return {"root": root_record, "files": files}


def _assert_no_writers(root: Path) -> None:
    result = subprocess.run(
        ["lsof", "+D", str(root)],
        check=False,  # lint-allow: only documented lsof 0/1 statuses are accepted below
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise PacketBuildError(f"lsof failed for rejected root {root}: {result.stderr.strip()}")
    if result.stdout.strip():
        raise PacketBuildError(f"rejected root has an open file: {root}")


def _validate_negative_receipts(values: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(values, list) or not values:
        raise PacketBuildError("negative_receipts must be a non-empty array")
    results: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        context = f"negative_receipts[{index}]"
        if not isinstance(value, dict):
            raise PacketBuildError(f"{context} must be an object")
        _require_exact_keys(value, frozenset({"expected_error", "locator"}), context)
        locator = _absolute_path(value["locator"], f"{context}.locator")
        expected_error = _require_text(value["expected_error"], f"{context}.expected_error")
        try:
            validate_consultation_bundle_receipt(locator)
        except PacketBuildError as exc:
            observed_error = str(exc)
            if expected_error not in observed_error:
                raise PacketBuildError(
                    f"{context} rejected for unexpected reason: {observed_error!r}"
                ) from exc
            results.append(
                {
                    "locator": str(locator),
                    "sha256": _sha256(_read_regular_file(locator, context)),
                    "rejected": True,
                    "error": observed_error,
                }
            )
        else:
            raise PacketBuildError(f"{context} was incorrectly accepted")
    return tuple(results)


def _prepare_build(spec_path: Path) -> PreparedBuild:
    spec_path = _absolute_path(str(spec_path), "spec path")
    spec_data = _read_regular_file(spec_path, "build spec")
    spec = _strict_json(spec_data, "build spec")
    _require_exact_keys(spec, TOP_LEVEL_SPEC_KEYS, "build spec")
    if spec["schema_version"] != 1:
        raise PacketBuildError("unsupported build spec schema_version")
    request_id = _require_text(spec["request_id"], "request_id")
    _require_text(spec["canonical_task_id"], "canonical_task_id")
    _require_text(spec["superseded_task_id"], "superseded_task_id")
    output_root = _absolute_path(spec["output_root"], "output_root")
    if output_root.exists() or output_root.is_symlink():
        raise PacketBuildError(f"output root already exists: {output_root}")
    _assert_no_symlink_components(output_root, include_leaf=False)
    parent_record = _observed_path_record(output_root.parent, "directory")
    if parent_record["owner_uid"] != os.geteuid():
        raise PacketBuildError("effective user does not own output parent")

    rejected_values = spec["rejected_input_roots"]
    if not isinstance(rejected_values, list) or not rejected_values:
        raise PacketBuildError("rejected_input_roots must be a non-empty array")
    rejected_roots = tuple(
        _absolute_path(value, f"rejected_input_roots[{index}]")
        for index, value in enumerate(rejected_values)
    )
    if len(set(rejected_roots)) != len(rejected_roots):
        raise PacketBuildError("rejected_input_roots contains duplicates")
    for root in rejected_roots:
        _observed_path_record(root, "directory")
        if _inside(output_root, root) or _inside(root, output_root):
            raise PacketBuildError("output root overlaps a rejected candidate root")

    builder_record = _verify_builder(spec["builder"])
    packet_contract = _binding_record(spec["packet_contract"], "packet_contract")
    fresh_neutrality = _binding_record(spec["fresh_neutrality"], "fresh_neutrality")
    if fresh_neutrality.get("verdict") != "PASS" or fresh_neutrality.get("prompting_lint") != "PASS":
        raise PacketBuildError("fresh neutrality must bind PASS verdict and prompting lint")

    worker_spec_value = spec["worker_spec"]
    if not isinstance(worker_spec_value, dict) or "r3_correction" not in worker_spec_value:
        raise PacketBuildError("worker_spec.r3_correction is required")
    worker_spec: dict[str, dict[str, Any]] = {}
    for key, value in worker_spec_value.items():
        if not isinstance(value, dict):
            raise PacketBuildError(f"worker_spec.{key} must be an object")
        worker_spec[key] = _binding_record(value, f"worker_spec.{key}")

    governance = spec["governance"]
    if not isinstance(governance, dict):
        raise PacketBuildError("governance must be an object")
    _require_exact_keys(
        governance,
        frozenset({"destinations", "kernel", "spotlight"}),
        "governance",
    )
    kernel = _source_bytes(governance["kernel"], "governance.kernel")
    spotlight = _source_bytes(governance["spotlight"], "governance.spotlight")

    task_values = spec["task_sources"]
    if not isinstance(task_values, list) or not task_values:
        raise PacketBuildError("task_sources must be a non-empty array")
    task_sources = tuple(
        _source_bytes(value, f"task_sources[{index}]")
        for index, value in enumerate(task_values)
        if isinstance(value, dict)
    )
    if len(task_sources) != len(task_values):
        raise PacketBuildError("each task source must be an object")
    logicals = [source.record["logical"] for source in task_sources]
    if len(set(logicals)) != len(logicals):
        raise PacketBuildError("task source logical names must be unique")
    packet_sources = [source for source in task_sources if source.record["logical"] == f"packet_{request_id.rsplit('-', 1)[-1]}.md"]
    if len(packet_sources) != 1:
        raise PacketBuildError("task sources must contain the corrected request packet exactly once")

    for source in (kernel, spotlight, *task_sources):
        _assert_not_rejected_input(Path(source.record["locator"]), rejected_roots, source.record["logical"])
    for record in (packet_contract, fresh_neutrality, *worker_spec.values()):
        _assert_not_rejected_input(Path(record["locator"]), rejected_roots, "provenance input")

    excluded = spec["excluded_stale"]
    if not isinstance(excluded, list) or not excluded or not all(isinstance(item, str) and item for item in excluded):
        raise PacketBuildError("excluded_stale must be a non-empty string array")
    generated_manifest_json = _render_manifest(task_sources, excluded)
    generated_manifest = b"".join(
        (
            b"## GENERATED ATTACHED PROVENANCE MANIFEST\n\n# generated_attached_provenance_manifest.json\n",
            generated_manifest_json,
            b"\n",
        )
    )
    expected = spec["expected"]
    if not isinstance(expected, dict):
        raise PacketBuildError("expected must be an object")
    _require_exact_keys(expected, frozenset({"bundle_b", "generated_manifest", "prompt"}), "expected")
    manifest_record = {
        "logical": "generated_attached_provenance_manifest.json",
        **_expected_blob(generated_manifest, expected["generated_manifest"], "expected.generated_manifest"),
    }
    manifest_value = _strict_json(generated_manifest_json, "generated manifest")
    if len(manifest_value.get("task_sources", [])) != len(task_sources):
        raise PacketBuildError("generated manifest task source count mismatch")
    if manifest_value.get("generated_attached_provenance_manifest") != {
        "logical": "generated_attached_provenance_manifest.json",
        "note": "this file",
    }:
        raise PacketBuildError("generated manifest self-record is missing or malformed")
    _validate_generated_bundle_metadata(request_id, task_sources, manifest_value)

    bundle_b = _render_bundle_b(request_id, task_sources, generated_manifest)
    _expected_blob(bundle_b, expected["bundle_b"], "expected.bundle_b")
    _validate_source_inclusion(bundle_b, task_sources, "Bundle B")
    if bundle_b.count(generated_manifest) != 1:
        raise PacketBuildError("Bundle B does not contain the generated manifest exactly once")
    if kernel.data in bundle_b or spotlight.data in bundle_b:
        raise PacketBuildError("Bundle B contains governance source bytes")

    prompt_spec = spec.get("expected", {}).get("prompt")
    if not isinstance(prompt_spec, dict):
        raise PacketBuildError("expected.prompt must be an object")
    prompt_text = spec["governance"].get("destinations")
    if not isinstance(prompt_text, list):
        raise PacketBuildError("governance.destinations must be an array")
    prompt_value = spec.get("builder", {}).get("prompt_text")
    if prompt_value is not None:
        raise PacketBuildError("builder.prompt_text is not a valid field")
    prompt_text_value = expected["prompt"].get("text")
    prompt_expected_hash = {key: expected["prompt"][key] for key in ("bytes", "sha256") if key in expected["prompt"]}
    if frozenset(expected["prompt"]) != frozenset({"bytes", "sha256", "text"}):
        raise PacketBuildError("expected.prompt fields differ")
    prompt = _validate_prompt(prompt_text_value, prompt_expected_hash)

    destination_values = governance["destinations"]
    if not isinstance(destination_values, list) or len(destination_values) != 2:
        raise PacketBuildError("this builder invocation requires exactly two destinations")
    destinations: list[DestinationBytes] = []
    bundle_b_basename_by_platform: dict[str, str] = {}
    identity_sources: list[SourceBytes] = []
    for index, destination in enumerate(destination_values):
        context = f"governance.destinations[{index}]"
        if not isinstance(destination, dict):
            raise PacketBuildError(f"{context} must be an object")
        _require_exact_keys(
            destination,
            frozenset(
                {
                    "bundle_a_basename",
                    "bundle_b_basename",
                    "display_name",
                    "expected_bundle_a",
                    "expected_bundle_a_absolute_paths",
                    "identity",
                    "platform",
                    "prompt_basename",
                    "receipt_basename",
                    "send_task",
                }
            ),
            context,
        )
        platform = _require_text(destination["platform"], f"{context}.platform")
        if platform not in IDENTITY_BY_PLATFORM:
            raise PacketBuildError(f"unsupported destination platform {platform}")
        identity = _source_bytes(destination["identity"], f"{context}.identity")
        if identity.record["logical"] != IDENTITY_BY_PLATFORM[platform]:
            raise PacketBuildError(f"{context} has wrong identity mapping")
        _assert_not_rejected_input(Path(identity.record["locator"]), rejected_roots, identity.record["logical"])
        display_name = _require_text(destination["display_name"], f"{context}.display_name")
        bundle_a = _render_bundle_a(request_id, display_name, kernel, identity, spotlight)
        expected_bundle_a = destination["expected_bundle_a"]
        if not isinstance(expected_bundle_a, dict):
            raise PacketBuildError(f"{context}.expected_bundle_a must be an object")
        _expected_blob(bundle_a, expected_bundle_a, f"{context}.expected_bundle_a")
        _validate_source_inclusion(bundle_a, (kernel, identity, spotlight), f"{platform} Bundle A")
        absolute_paths = destination["expected_bundle_a_absolute_paths"]
        if not isinstance(absolute_paths, list) or len(absolute_paths) != 2:
            raise PacketBuildError(f"{context}.expected_bundle_a_absolute_paths must contain two strings")
        expected_paths = tuple(_require_text(value, f"{context}.expected_bundle_a_absolute_paths") for value in absolute_paths)
        observed_paths = tuple(path for path in expected_paths if bundle_a.count(path.encode()) == 1)
        if observed_paths != expected_paths or bundle_a.count(b"/home/") != 2:
            raise PacketBuildError(f"{platform} Bundle A absolute-path scope differs")
        send_task = destination["send_task"]
        if not isinstance(send_task, dict):
            raise PacketBuildError(f"{context}.send_task must be an object")
        _require_exact_keys(
            send_task,
            frozenset({"corrected_packet_path", "forbidden_roots", "task_id"}),
            f"{context}.send_task",
        )
        send_task_id = _require_text(send_task["task_id"], f"{context}.send_task.task_id")
        corrected_path = _absolute_path(
            send_task["corrected_packet_path"],
            f"{context}.send_task.corrected_packet_path",
        )
        if corrected_path != Path(packet_sources[0].record["locator"]):
            raise PacketBuildError(f"{context}.send_task does not bind the corrected packet")
        forbidden_roots = send_task["forbidden_roots"]
        if not isinstance(forbidden_roots, list) or not forbidden_roots:
            raise PacketBuildError(f"{context}.send_task.forbidden_roots must be non-empty")
        for forbidden_index, forbidden_value in enumerate(forbidden_roots):
            forbidden = _absolute_path(
                forbidden_value,
                f"{context}.send_task.forbidden_roots[{forbidden_index}]",
            )
            if _inside(output_root, forbidden):
                raise PacketBuildError(f"output root overlaps forbidden ambiguous send root {forbidden}")
        bundle_a_basename = _validate_basename(destination["bundle_a_basename"], f"{context}.bundle_a_basename")
        bundle_b_basename = _validate_basename(destination["bundle_b_basename"], f"{context}.bundle_b_basename")
        prompt_basename = _validate_basename(destination["prompt_basename"], f"{context}.prompt_basename")
        receipt_basename = _validate_basename(destination["receipt_basename"], f"{context}.receipt_basename")
        expected_prefix = f"{request_id}-{platform}-"
        if not all(name.startswith(expected_prefix) for name in (bundle_a_basename, bundle_b_basename, prompt_basename, receipt_basename)):
            raise PacketBuildError(f"{context} basenames do not bind request and platform")
        identity_sources.append(identity)
        bundle_b_basename_by_platform[platform] = bundle_b_basename
        destinations.append(
            DestinationBytes(
                platform=platform,
                display_name=display_name,
                identity=identity,
                bundle_a_basename=bundle_a_basename,
                bundle_a=bundle_a,
                prompt_basename=prompt_basename,
                receipt_basename=receipt_basename,
                send_task_id=send_task_id,
                expected_absolute_paths=expected_paths,
            )
        )
    if len({destination.platform for destination in destinations}) != len(destinations):
        raise PacketBuildError("destination platforms must be unique")
    if len({name for destination in destinations for name in (destination.bundle_a_basename, bundle_b_basename_by_platform[destination.platform], destination.prompt_basename, destination.receipt_basename)}) != 8:
        raise PacketBuildError("the two destination sets must produce exactly eight unique basenames")
    for destination in destinations:
        for other_identity in identity_sources:
            count = destination.bundle_a.count(other_identity.data)
            expected_count = 1 if other_identity is destination.identity else 0
            if count != expected_count:
                raise PacketBuildError(f"{destination.platform} Bundle A identity isolation failed")

    negative_controls = _validate_negative_receipts(spec["negative_receipts"])
    return PreparedBuild(
        spec_path=spec_path,
        spec=spec,
        build_spec_record={"locator": str(spec_path), "bytes": len(spec_data), "sha256": _sha256(spec_data)},
        output_root=output_root,
        kernel=kernel,
        spotlight=spotlight,
        destinations=tuple(destinations),
        task_sources=task_sources,
        generated_manifest_record=manifest_record,
        generated_manifest=generated_manifest,
        bundle_b_basename_by_platform=bundle_b_basename_by_platform,
        bundle_b=bundle_b,
        prompt=prompt,
        packet_contract=packet_contract,
        fresh_neutrality=fresh_neutrality,
        worker_spec=worker_spec,
        builder_record=builder_record,
        rejected_roots=rejected_roots,
        negative_controls=negative_controls,
    )


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise PacketBuildError("exclusive output write made no progress")
        view = view[written:]


def _open_exclusive(path: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise PacketBuildError(f"exclusive output is not regular: {path}")
    if metadata.st_uid != os.geteuid() or _mode_text(metadata.st_mode) != "0600":
        raise PacketBuildError(f"exclusive output owner/mode mismatch: {path}")
    return descriptor


def _receipt(
    prepared: PreparedBuild,
    destination: DestinationBytes,
    root_record: dict[str, Any],
    files: list[dict[str, Any]],
    quarantine_before: dict[str, Any],
    quarantine_after: dict[str, Any],
) -> dict[str, Any]:
    root_path = prepared.output_root
    bundle_b_basename = prepared.bundle_b_basename_by_platform[destination.platform]
    packet_source = next(
        source for source in prepared.task_sources if source.record["logical"].startswith("packet_")
    )
    return {
        "schema_version": 1,
        "canonical_task_id": prepared.spec["canonical_task_id"],
        "superseded_task_id": prepared.spec["superseded_task_id"],
        "destination": destination.platform,
        "root": root_record,
        "files": files,
        "builder": prepared.builder_record,
        "build_spec": prepared.build_spec_record,
        "packet_contract": prepared.packet_contract,
        "worker_spec": prepared.worker_spec,
        "fresh_neutrality": prepared.fresh_neutrality,
        "locator_ruling": prepared.spec["locator_ruling"],
        "governance_sources": [
            prepared.kernel.record,
            destination.identity.record,
            prepared.spotlight.record,
        ],
        "sources": [source.record for source in prepared.task_sources],
        "generated_manifest": prepared.generated_manifest_record,
        "attachments": {
            "a": {
                "basename": destination.bundle_a_basename,
                "bytes": len(destination.bundle_a),
                "sha256": _sha256(destination.bundle_a),
            },
            "b": {
                "basename": bundle_b_basename,
                "bytes": len(prepared.bundle_b),
                "sha256": _sha256(prepared.bundle_b),
            },
        },
        "prompt": {
            "basename": destination.prompt_basename,
            "bytes": len(prepared.prompt),
            "sha256": _sha256(prepared.prompt),
            "text": prepared.prompt.decode("utf-8"),
        },
        "send_task": {
            "task_id": destination.send_task_id,
            "status": "pending_r5_control_acceptance",
            "corrected_packet_path": packet_source.record["locator"],
            "attachment_paths": [
                str(root_path / destination.bundle_a_basename),
                str(root_path / bundle_b_basename),
            ],
            "prompt_path": str(root_path / destination.prompt_basename),
        },
        "negative_controls": list(prepared.negative_controls),
        "quarantined_roots": {
            "before": quarantine_before,
            "after": quarantine_after,
            "unchanged": quarantine_before == quarantine_after,
        },
        "checks": {
            "source_size_hash_verification": True,
            "bundle_a_exact_once_count": 3,
            "bundle_b_exact_once_count": len(prepared.task_sources),
            "deterministic_order": True,
            "destination_identity_isolation": True,
            "governance_absent_from_bundle_b": True,
            "attached_manifest_task_source_count": len(prepared.task_sources),
            "attached_manifest_self_record_count": 1,
            "bundle_b_cross_destination_cmp": True,
            "prompt_cross_destination_cmp": True,
            "exactly_two_attachment_designation_per_destination": True,
            "immutable_source_content_absolute_paths": list(destination.expected_absolute_paths),
            "immutable_source_content_path_hits": {"bundle_a": 2, "bundle_b": 0},
            "no_operator_local_abs_in_bundle_b_provenance_and_request": True,
            "generated_regular_file_count": len(files),
            "live_directory_exactly_matches_files": True,
            "symlink_count": 0,
            "independent_final_reread": True,
            "quarantined_roots_unchanged": quarantine_before == quarantine_after,
            "receipt_root_derived_from_actual_target": True,
            "send_task_bound_to_r5_and_corrected_packet": True,
        },
        "actions": {key: False for key in PROHIBITED_ACTIONS},
    }


def validate_consultation_bundle_receipt(receipt_path: str | Path) -> dict[str, Any]:
    path = _absolute_path(str(receipt_path), "receipt path")
    receipt = _strict_json(_read_regular_file(path, "receipt"), "receipt")
    root = receipt.get("root")
    if not isinstance(root, dict):
        raise PacketBuildError("receipt root must be an object derived from os.stat(actual_root)")
    _require_exact_keys(root, frozenset({"mode", "owner_gid", "owner_uid", "path", "type"}), "receipt.root")
    if root["path"] != str(path.parent) or root["type"] != "directory":
        raise PacketBuildError("receipt root.path must equal dirname(abspath(receipt_path))")
    observed_root = _observed_path_record(path.parent, "directory")
    if root != observed_root:
        raise PacketBuildError("receipt root metadata does not match os.stat(actual_root)")
    _require_exact_keys(receipt, RECEIPT_KEYS, "receipt")
    if receipt["schema_version"] != 1:
        raise PacketBuildError("receipt schema_version is unsupported")
    if "files_inventory" in receipt or "no_abs_in_attachments" in receipt:
        raise PacketBuildError("receipt contains superseded provenance fields")
    worker_spec = receipt["worker_spec"]
    if not isinstance(worker_spec, dict) or "r3_correction" not in worker_spec:
        raise PacketBuildError("receipt must preserve worker_spec.r3_correction")
    files = receipt["files"]
    if not isinstance(files, list) or len(files) != 8:
        raise PacketBuildError("receipt files must contain all eight generated files")
    if len({item.get("basename") for item in files if isinstance(item, dict)}) != 8:
        raise PacketBuildError("receipt files basenames must be unique")
    expected_basenames = sorted(item["basename"] for item in files)
    with os.scandir(path.parent) as entries:
        live_basenames = sorted(entry.name for entry in entries)
    if live_basenames != expected_basenames:
        raise PacketBuildError(
            "live output directory entries differ from the receipt's exact eight-file inventory"
        )
    observed_files: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            raise PacketBuildError("receipt file entry must be an object")
        _require_exact_keys(item, frozenset({"basename", "mode", "owner_gid", "owner_uid", "type"}), "receipt file")
        basename = _validate_basename(item["basename"], "receipt file basename")
        observed_files.append(_observed_path_record(path.parent / basename, "regular"))
    if files != observed_files:
        raise PacketBuildError("receipt file inventory differs from live output root")
    if receipt["checks"].get("generated_regular_file_count") != 8:
        raise PacketBuildError("receipt generated_regular_file_count must equal eight")
    if any(receipt["actions"].get(key) is not False for key in PROHIBITED_ACTIONS):
        raise PacketBuildError("receipt prohibited action fields must all be false")
    attachments = receipt["attachments"]
    if not isinstance(attachments, dict) or frozenset(attachments) != frozenset({"a", "b"}):
        raise PacketBuildError("receipt must designate exactly Bundle A and Bundle B")
    for label, attachment in attachments.items():
        if not isinstance(attachment, dict):
            raise PacketBuildError(f"attachment {label} must be an object")
        _require_exact_keys(attachment, frozenset({"basename", "bytes", "sha256"}), f"attachment {label}")
        attachment_path = path.parent / _validate_basename(attachment["basename"], f"attachment {label} basename")
        data = _read_regular_file(attachment_path, f"attachment {label}")
        if len(data) != attachment["bytes"] or _sha256(data) != attachment["sha256"]:
            raise PacketBuildError(f"attachment {label} content address mismatch")
    prompt = receipt["prompt"]
    if not isinstance(prompt, dict):
        raise PacketBuildError("receipt prompt must be an object")
    _require_exact_keys(prompt, frozenset({"basename", "bytes", "sha256", "text"}), "receipt prompt")
    prompt_path = path.parent / _validate_basename(prompt["basename"], "receipt prompt basename")
    prompt_data = _read_regular_file(prompt_path, "receipt prompt")
    if prompt_data != prompt["text"].encode() or len(prompt_data) != prompt["bytes"] or _sha256(prompt_data) != prompt["sha256"]:
        raise PacketBuildError("receipt prompt binding mismatch")
    send_task = receipt["send_task"]
    if not isinstance(send_task, dict):
        raise PacketBuildError("receipt send_task must be an object")
    _require_exact_keys(
        send_task,
        frozenset({"attachment_paths", "corrected_packet_path", "prompt_path", "status", "task_id"}),
        "receipt send_task",
    )
    expected_attachment_paths = [str(path.parent / attachments[label]["basename"]) for label in ("a", "b")]
    if send_task["attachment_paths"] != expected_attachment_paths:
        raise PacketBuildError("receipt send_task attachment paths are not the actual r5 files")
    if send_task["prompt_path"] != str(prompt_path):
        raise PacketBuildError("receipt send_task prompt path is not the actual r5 prompt")
    corrected_packet = _absolute_path(send_task["corrected_packet_path"], "receipt corrected packet")
    packet_records = [source for source in receipt["sources"] if source.get("logical", "").startswith("packet_")]
    if len(packet_records) != 1 or packet_records[0].get("locator") != str(corrected_packet):
        raise PacketBuildError("receipt send_task does not bind the corrected packet source")
    quarantine = receipt["quarantined_roots"]
    if not isinstance(quarantine, dict) or quarantine.get("unchanged") is not True or quarantine.get("before") != quarantine.get("after"):
        raise PacketBuildError("receipt rejected-root before/after evidence is not unchanged")
    return receipt


def build_consultation_bundles(spec_path: str | Path) -> dict[str, Any]:
    prepared = _prepare_build(Path(spec_path))
    quarantine_before: dict[str, Any] = {}
    for root in prepared.rejected_roots:
        _assert_no_writers(root)
        quarantine_before[str(root)] = _snapshot_root(root)

    os.mkdir(prepared.output_root, 0o700)
    root_record = _observed_path_record(prepared.output_root, "directory")
    if root_record["owner_uid"] != os.geteuid() or root_record["mode"] != "0700":
        raise PacketBuildError("new output root owner/mode mismatch")

    file_paths: list[Path] = []
    content_by_basename: dict[str, bytes] = {}
    for destination in prepared.destinations:
        content_by_basename[destination.bundle_a_basename] = destination.bundle_a
        content_by_basename[prepared.bundle_b_basename_by_platform[destination.platform]] = prepared.bundle_b
        content_by_basename[destination.prompt_basename] = prepared.prompt
        content_by_basename[destination.receipt_basename] = b""
    descriptors: dict[str, int] = {}
    try:
        for basename in sorted(content_by_basename):
            path = prepared.output_root / basename
            descriptors[basename] = _open_exclusive(path)
            file_paths.append(path)
        files = [_observed_path_record(path, "regular") for path in sorted(file_paths)]
        if len(files) != 8:
            raise PacketBuildError("construction did not create exactly eight regular files")
        expected_basenames = sorted(content_by_basename)
        with os.scandir(prepared.output_root) as entries:
            live_basenames = sorted(entry.name for entry in entries)
        if live_basenames != expected_basenames:
            raise PacketBuildError(
                "live output directory entries differ from the exact eight intended basenames"
            )

        for basename, data in content_by_basename.items():
            if data:
                _write_all(descriptors[basename], data)
                os.fsync(descriptors[basename])
        for destination in prepared.destinations:
            reread = {
                destination.bundle_a_basename: destination.bundle_a,
                prepared.bundle_b_basename_by_platform[destination.platform]: prepared.bundle_b,
                destination.prompt_basename: prepared.prompt,
            }
            for basename, expected_data in reread.items():
                observed_data = _read_regular_file(prepared.output_root / basename, f"final reread {basename}")
                if observed_data != expected_data:
                    raise PacketBuildError(f"final reread mismatch for {basename}")

        quarantine_after = {str(root): _snapshot_root(root) for root in prepared.rejected_roots}
        if quarantine_before != quarantine_after:
            raise PacketBuildError("a rejected candidate root changed during construction")

        for destination in prepared.destinations:
            receipt = _receipt(
                prepared,
                destination,
                root_record,
                files,
                quarantine_before,
                quarantine_after,
            )
            receipt_path = prepared.output_root / destination.receipt_basename
            if receipt["root"]["path"] != str(receipt_path.parent):
                raise PacketBuildError("derived receipt root differs from actual target")
            receipt_bytes = _json_bytes(receipt)
            _write_all(descriptors[destination.receipt_basename], receipt_bytes)
            os.fsync(descriptors[destination.receipt_basename])
        directory_descriptor = os.open(prepared.output_root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        for descriptor in descriptors.values():
            os.close(descriptor)

    result_files: list[dict[str, Any]] = []
    for path in sorted(file_paths):
        data = _read_regular_file(path, f"production output {path.name}")
        result_files.append({"path": str(path), "bytes": len(data), "sha256": _sha256(data)})
    for destination in prepared.destinations:
        validate_consultation_bundle_receipt(prepared.output_root / destination.receipt_basename)
    return {
        "status": "built",
        "root": root_record,
        "files": result_files,
        "quarantined_roots_unchanged": True,
        "negative_controls": list(prepared.negative_controls),
    }


def preflight_consultation_bundles(spec_path: str | Path) -> dict[str, Any]:
    prepared = _prepare_build(Path(spec_path))
    return {
        "status": "preflight_pass",
        "output_root": str(prepared.output_root),
        "builder": prepared.builder_record,
        "bundle_b": {"bytes": len(prepared.bundle_b), "sha256": _sha256(prepared.bundle_b)},
        "generated_manifest": prepared.generated_manifest_record,
        "prompt": {"bytes": len(prepared.prompt), "sha256": _sha256(prepared.prompt)},
        "destinations": [
            {
                "platform": destination.platform,
                "bundle_a": {"bytes": len(destination.bundle_a), "sha256": _sha256(destination.bundle_a)},
                "send_task_id": destination.send_task_id,
            }
            for destination in prepared.destinations
        ],
        "negative_controls": list(prepared.negative_controls),
    }


VERIFY_RUN_INPUT_SPEC_KEYS = frozenset(
    {
        "authority_source",
        "bundle_a",
        "bundle_b",
        "corrected_packet",
        "output_receipt",
        "prompt",
        "receipt",
        "schema_version",
        "send_task",
    }
)
VERIFY_SEND_TASK_KEYS = frozenset(
    {
        "expected_authority",
        "expected_claimed_worker",
        "expected_status",
        "task_id",
    }
)
AUTHORITY_SOURCE_KINDS = frozenset({"local_snapshot", "orchestrator_readonly_get"})


def _observed_hash_binding(binding: Mapping[str, Any], context: str) -> dict[str, Any]:
    _require_exact_keys(binding, frozenset({"bytes", "path", "sha256"}), context)
    path = _absolute_path(binding["path"], f"{context}.path")
    data = _read_regular_file(path, context)
    expected = _expected_blob(data, {"bytes": binding["bytes"], "sha256": binding["sha256"]}, context)
    expected["path"] = str(path)
    return expected


def _readonly_get_task(locator: str, task_id: str) -> dict[str, Any]:
    if any(token in locator for token in ("?", "#", " ")):
        raise PacketBuildError("orchestrator locator must be a query-free URL")
    if not locator.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise PacketBuildError("orchestrator locator must be a local GET URL")
    if not locator.rstrip("/").endswith("/" + task_id):
        raise PacketBuildError("orchestrator locator does not name the exact send task")
    request = urllib.request.Request(locator, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.getcode() != 200:
                raise PacketBuildError(f"orchestrator GET returned HTTP {response.getcode()}")
            raw = response.read()
    except urllib.error.URLError as exc:
        raise PacketBuildError(f"orchestrator GET failed: {exc}") from exc
    if not raw:
        raise PacketBuildError("orchestrator GET returned an empty body")
    return _strict_json(raw, "orchestrator task")


def _load_authority_snapshot(source: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    _require_exact_keys(source, frozenset({"kind", "locator"}), "authority_source")
    kind = _require_text(source["kind"], "authority_source.kind")
    locator = _require_text(source["locator"], "authority_source.locator")
    if kind not in AUTHORITY_SOURCE_KINDS:
        raise PacketBuildError(
            "authority_source.kind is not a read-only proof source; "
            "verify-run-inputs never starts, dispatches, or sends"
        )
    if kind == "local_snapshot":
        path = _absolute_path(locator, "authority_source.locator")
        return _strict_json(_read_regular_file(path, "authority snapshot"), "authority snapshot")
    return _readonly_get_task(locator, task_id)


def _prove_supervised_claim(snapshot: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    _require_exact_keys(expected, VERIFY_SEND_TASK_KEYS, "send_task")
    task_id = _require_text(expected["task_id"], "send_task.task_id")
    expected_status = _require_text(expected["expected_status"], "send_task.expected_status")
    worker = _require_text(expected["expected_claimed_worker"], "send_task.expected_claimed_worker")
    authority = _require_text(expected["expected_authority"], "send_task.expected_authority")
    if expected_status != "in_progress":
        raise PacketBuildError("send-input gate requires expected_status in_progress")
    if authority != "supervised_taey":
        raise PacketBuildError("send-input gate requires expected_authority supervised_taey")
    snapshot_id = _require_text(snapshot.get("id"), "authority snapshot id")
    snapshot_status = _require_text(snapshot.get("status"), "authority snapshot status")
    dispatched_to = snapshot.get("dispatched_to")
    snapshot_authority = snapshot.get("authority")
    if snapshot_id != task_id:
        raise PacketBuildError("authority snapshot id is not the exact send task")
    if snapshot_status != "in_progress":
        raise PacketBuildError("send task has not started (status is not in_progress)")
    if not isinstance(dispatched_to, str) or not dispatched_to:
        raise PacketBuildError("send task is not claimed (dispatched_to empty)")
    if dispatched_to != worker:
        raise PacketBuildError("send task claimed worker differs from frozen expected worker")
    if snapshot_authority != "supervised_taey":
        raise PacketBuildError("send task is not under supervised Taey authority")
    claim_worker = snapshot.get("dispatch_claim_worker")
    if claim_worker not in (None, worker):
        raise PacketBuildError("dispatch_claim_worker disagrees with dispatched_to")
    return {
        "task_id": task_id,
        "started": True,
        "claimed": True,
        "status": snapshot_status,
        "claimed_worker": dispatched_to,
        "authority": snapshot_authority,
    }


def _cross_check_receipt_hashes(
    receipt_data: bytes,
    hashes: Mapping[str, dict[str, Any]],
    task_id: str,
) -> None:
    receipt = _strict_json(receipt_data, "send-input receipt")
    attachments = receipt.get("attachments")
    if isinstance(attachments, dict):
        for label, key in (("a", "bundle_a"), ("b", "bundle_b")):
            attachment = attachments.get(label)
            if not isinstance(attachment, dict):
                continue
            sha = attachment.get("sha256")
            size = attachment.get("bytes")
            if sha != hashes[key]["sha256"] or size != hashes[key]["bytes"]:
                raise PacketBuildError(f"receipt attachment {label} hash differs from frozen {key}")
    prompt = receipt.get("prompt")
    if isinstance(prompt, dict):
        if prompt.get("sha256") != hashes["prompt"]["sha256"] or prompt.get("bytes") != hashes["prompt"]["bytes"]:
            raise PacketBuildError("receipt prompt hash differs from frozen prompt")
    send_task = receipt.get("send_task")
    if isinstance(send_task, dict) and send_task.get("task_id") not in (None, task_id):
        raise PacketBuildError("receipt send_task.task_id differs from frozen send task")
    packet_records = [
        source
        for source in receipt.get("sources") or []
        if isinstance(source, dict) and str(source.get("logical", "")).startswith("packet_")
    ]
    if packet_records:
        if len(packet_records) != 1:
            raise PacketBuildError("receipt names more than one corrected packet source")
        packet = packet_records[0]
        if packet.get("sha256") != hashes["corrected_packet"]["sha256"]:
            raise PacketBuildError("receipt corrected packet hash differs from frozen packet")
        if packet.get("locator") != hashes["corrected_packet"]["path"]:
            raise PacketBuildError("receipt corrected packet locator differs from frozen packet path")


def verify_run_inputs(spec_path: str | Path) -> dict[str, Any]:
    path = _absolute_path(str(spec_path), "verify-run-inputs spec")
    spec = _strict_json(_read_regular_file(path, "verify-run-inputs spec"), "verify-run-inputs spec")
    _require_exact_keys(spec, VERIFY_RUN_INPUT_SPEC_KEYS, "verify-run-inputs spec")
    if spec["schema_version"] != 1:
        raise PacketBuildError("verify-run-inputs schema_version is unsupported")
    hashes = {
        "bundle_a": _observed_hash_binding(spec["bundle_a"], "bundle_a"),
        "bundle_b": _observed_hash_binding(spec["bundle_b"], "bundle_b"),
        "prompt": _observed_hash_binding(spec["prompt"], "prompt"),
        "corrected_packet": _observed_hash_binding(spec["corrected_packet"], "corrected_packet"),
        "receipt": _observed_hash_binding(spec["receipt"], "receipt"),
    }
    send_task = spec["send_task"]
    if not isinstance(send_task, dict):
        raise PacketBuildError("send_task must be an object")
    task_id = _require_text(send_task.get("task_id"), "send_task.task_id")
    receipt_data = _read_regular_file(Path(hashes["receipt"]["path"]), "receipt")
    _cross_check_receipt_hashes(receipt_data, hashes, task_id)
    snapshot = _load_authority_snapshot(spec["authority_source"], task_id)
    proof = _prove_supervised_claim(snapshot, send_task)
    output_path = _absolute_path(spec["output_receipt"], "output_receipt")
    if output_path.parent == output_path:
        raise PacketBuildError("output_receipt must be a file path")
    receipt = {
        "schema_version": 1,
        "status": "verify_run_inputs_pass",
        "spec": {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(_read_regular_file(path, "verify spec reread"))},
        "hashes": hashes,
        "send_task": proof,
        "authority_source": spec["authority_source"],
        "actions": {key: False for key in PROHIBITED_ACTIONS},
        "checks": {
            "bundle_a_hash": True,
            "bundle_b_hash": True,
            "prompt_hash": True,
            "corrected_packet_hash": True,
            "receipt_hash": True,
            "send_task_started": True,
            "send_task_claimed": True,
            "supervised_taey_authority": True,
            "no_task_create_or_dispatch": True,
            "no_attachment_staging": True,
            "no_ui_or_send": True,
        },
    }
    payload = _json_bytes(receipt)
    descriptor = _open_exclusive(output_path)
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    observed = _read_regular_file(output_path, "verify-run-inputs output receipt")
    if observed != payload:
        raise PacketBuildError("verify-run-inputs output receipt reread mismatch")
    return {
        "status": "verify_run_inputs_pass",
        "receipt": str(output_path),
        "bytes": len(observed),
        "sha256": _sha256(observed),
        "send_task": proof,
        "actions": receipt["actions"],
    }


def _control_hash_binding(path: Path, data: bytes) -> dict[str, Any]:
    return {"path": str(path), "bytes": len(data), "sha256": _sha256(data)}


def _write_control_file(path: Path, data: bytes) -> None:
    descriptor = _open_exclusive(path)
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run_verify_run_inputs_controls() -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    def one_case(name: str, *, expect_pass: bool, mutate: Any) -> None:
        with tempfile.TemporaryDirectory(prefix="packet-verify-run-inputs-") as raw_root:
            root = Path(raw_root)
            bundle_a = b"FAKE-BUNDLE-A\n"
            bundle_b = b"FAKE-BUNDLE-B\n"
            prompt = (
                b"Read both attached files fully before answering. Fake request. "
                b"Deliver fake deliverable. Follow the governance, evidence, "
                b"acceptance, and stop conditions in the attachments. If either "
                b"attachment is unavailable or incomplete, state that and stop."
            )
            packet = b"FAKE-CORRECTED-PACKET\n"
            task_id = "task-fake-send-1"
            worker = "taey"
            bundle_a_path = root / "bundle_a.md"
            bundle_b_path = root / "bundle_b.md"
            prompt_path = root / "prompt.txt"
            packet_path = root / "corrected_packet.md"
            receipt_path = root / "build_receipt.json"
            snapshot_path = root / "authority.json"
            spec_path = root / "verify_spec.json"
            output_path = root / "verify_receipt.json"
            for path, data in (
                (bundle_a_path, bundle_a),
                (bundle_b_path, bundle_b),
                (prompt_path, prompt),
                (packet_path, packet),
            ):
                _write_control_file(path, data)
            build_receipt = {
                "attachments": {
                    "a": {"basename": "bundle_a.md", "bytes": len(bundle_a), "sha256": _sha256(bundle_a)},
                    "b": {"basename": "bundle_b.md", "bytes": len(bundle_b), "sha256": _sha256(bundle_b)},
                },
                "prompt": {
                    "basename": "prompt.txt",
                    "bytes": len(prompt),
                    "sha256": _sha256(prompt),
                    "text": prompt.decode("utf-8"),
                },
                "send_task": {"task_id": task_id},
                "sources": [
                    {
                        "logical": "packet_corrected",
                        "locator": str(packet_path),
                        "bytes": len(packet),
                        "sha256": _sha256(packet),
                    }
                ],
            }
            snapshot = {
                "id": task_id,
                "status": "in_progress",
                "dispatched_to": worker,
                "dispatch_claim_worker": worker,
                "authority": "supervised_taey",
            }
            spec = {
                "schema_version": 1,
                "bundle_a": _control_hash_binding(bundle_a_path, bundle_a),
                "bundle_b": _control_hash_binding(bundle_b_path, bundle_b),
                "prompt": _control_hash_binding(prompt_path, prompt),
                "corrected_packet": _control_hash_binding(packet_path, packet),
                "receipt": {
                    "path": str(receipt_path),
                    "bytes": 0,
                    "sha256": "pending",
                },
                "send_task": {
                    "task_id": task_id,
                    "expected_status": "in_progress",
                    "expected_claimed_worker": worker,
                    "expected_authority": "supervised_taey",
                },
                "authority_source": {"kind": "local_snapshot", "locator": str(snapshot_path)},
                "output_receipt": str(output_path),
            }
            mutate(spec, snapshot, build_receipt)
            receipt_bytes = _json_bytes(build_receipt)
            spec["receipt"] = _control_hash_binding(receipt_path, receipt_bytes)
            if name == "falsified_receipt_hash":
                spec["receipt"]["sha256"] = "0" * 64
            _write_control_file(receipt_path, receipt_bytes)
            _write_control_file(snapshot_path, _json_bytes(snapshot))
            _write_control_file(spec_path, _json_bytes(spec))
            try:
                result = verify_run_inputs(spec_path)
                passed = True
                detail = result["status"]
            except (OSError, PacketBuildError) as exc:
                passed = False
                detail = str(exc)
            ok = passed if expect_pass else not passed
            results.append(
                {
                    "name": name,
                    "expect_pass": expect_pass,
                    "passed": passed,
                    "ok": ok,
                    "detail": detail,
                }
            )

    one_case("positive_started_claimed_hashes", expect_pass=True, mutate=lambda spec, snapshot, receipt: None)

    def mismatch_a(spec: dict[str, Any], snapshot: dict[str, Any], receipt: dict[str, Any]) -> None:
        spec["bundle_a"]["sha256"] = "0" * 64

    def mismatch_b(spec: dict[str, Any], snapshot: dict[str, Any], receipt: dict[str, Any]) -> None:
        spec["bundle_b"]["sha256"] = "0" * 64

    def mismatch_prompt(spec: dict[str, Any], snapshot: dict[str, Any], receipt: dict[str, Any]) -> None:
        spec["prompt"]["sha256"] = "0" * 64

    def mismatch_packet(spec: dict[str, Any], snapshot: dict[str, Any], receipt: dict[str, Any]) -> None:
        spec["corrected_packet"]["sha256"] = "0" * 64

    def not_started(spec: dict[str, Any], snapshot: dict[str, Any], receipt: dict[str, Any]) -> None:
        snapshot["status"] = "pending"

    def not_claimed(spec: dict[str, Any], snapshot: dict[str, Any], receipt: dict[str, Any]) -> None:
        snapshot["dispatched_to"] = ""

    def wrong_task(spec: dict[str, Any], snapshot: dict[str, Any], receipt: dict[str, Any]) -> None:
        snapshot["id"] = "task-other"

    def not_supervised(spec: dict[str, Any], snapshot: dict[str, Any], receipt: dict[str, Any]) -> None:
        snapshot["authority"] = "autonomous_engine"

    def dispatch_kind(spec: dict[str, Any], snapshot: dict[str, Any], receipt: dict[str, Any]) -> None:
        spec["authority_source"]["kind"] = "dispatch"

    one_case("falsified_bundle_a_hash", expect_pass=False, mutate=mismatch_a)
    one_case("falsified_bundle_b_hash", expect_pass=False, mutate=mismatch_b)
    one_case("falsified_prompt_hash", expect_pass=False, mutate=mismatch_prompt)
    one_case("falsified_corrected_packet_hash", expect_pass=False, mutate=mismatch_packet)
    one_case("falsified_receipt_hash", expect_pass=False, mutate=lambda spec, snapshot, receipt: None)
    one_case("falsified_not_started", expect_pass=False, mutate=not_started)
    one_case("falsified_not_claimed", expect_pass=False, mutate=not_claimed)
    one_case("falsified_wrong_task_id", expect_pass=False, mutate=wrong_task)
    one_case("falsified_not_supervised_taey", expect_pass=False, mutate=not_supervised)
    one_case("falsified_dispatch_authority_kind", expect_pass=False, mutate=dispatch_kind)

    failed = [item for item in results if not item["ok"]]
    if failed:
        names = ", ".join(item["name"] for item in failed)
        raise PacketBuildError(f"verify-run-inputs controls failed: {names}")
    return {
        "status": "verify_run_inputs_controls_pass",
        "cases": results,
        "positive": 1,
        "falsified": len(results) - 1,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build PACKET_CONTRACT two-attachment consultation sets.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "build", "verify-run-inputs"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--spec", required=True)
    receipt_parser = subparsers.add_parser("validate-receipt")
    receipt_parser.add_argument("receipt")
    subparsers.add_parser("verify-run-inputs-controls")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight_consultation_bundles(args.spec)
        elif args.command == "build":
            result = build_consultation_bundles(args.spec)
        elif args.command == "verify-run-inputs":
            result = verify_run_inputs(args.spec)
        elif args.command == "verify-run-inputs-controls":
            result = run_verify_run_inputs_controls()
        else:
            receipt = validate_consultation_bundle_receipt(args.receipt)
            result = {
                "status": "receipt_valid",
                "receipt": str(Path(args.receipt).absolute()),
                "destination": receipt["destination"],
            }
    except (OSError, PacketBuildError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
