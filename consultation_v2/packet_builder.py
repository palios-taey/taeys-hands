from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence


IDENTITY_BY_PLATFORM = {
    "chatgpt": "IDENTITY_HORIZON.md",
    "claude": "IDENTITY_GAIA.md",
    "gemini": "IDENTITY_COSMOS.md",
    "grok": "IDENTITY_LOGOS.md",
    "perplexity": "IDENTITY_CLARITY.md",
}
KERNEL_LOGICAL = "FAMILY_KERNEL.md"
SPOTLIGHT_LOGICAL = "SPOTLIGHT_STANDARD_FOR_INTEGRITY.md"

PROMPTING_LINT = Path("/usr/local/bin/prompting-lint")
SCHEMA_VERSION = 2

REQUIRED_DOSSIER_HEADINGS = (
    "Ground truth",
    "Problem statement",
    "Constraints",
    "Objective",
)
QUESTION_LINE = re.compile(
    r"^(?:[-*+]\s+|\d+[.)]\s+)?(?:\[[^\]\r\n]+\]\s*)*"
    r"(?:(?:given|for|under|within|using|from|assuming|based on)\b[^?\r\n]*,\s*)?"
    r"(?:what|why|how|when|where|which|who|whom|whose|is|are|am|do|does|did|"
    r"can|could|should|would|will|may|might|must|has|have|had)[ \t]+[^?\r\n]+\?\s*$",
    flags=re.IGNORECASE,
)

FORBIDDEN_PROMPT_TERMS = (
    "filesystem",
    "file system",
    "absolute path",
    "file path",
    " path ",
    " paths",
    "sha-256",
    "sha256",
    "hash",
    " byte ",
    " bytes",
    "byte count",
    "byte size",
    "file size",
    "git state",
    "git status",
    "git commit",
    "git branch",
    "git diff",
    "git revision",
    "git tree",
    "commit sha",
    "working tree",
    "ui state",
    "ui measurement",
    "ui metrics",
    "ui latency",
    "ui timing",
    "measure ui",
    "measure the ui",
    "at-spi tree",
    "at-spi state",
    "accessibility tree state",
    "tree revision",
    "display state",
    "screen state",
)

OPERATOR_LOCAL_PATH = re.compile(
    rb"(?<![A-Za-z0-9:/])/(?:dev|etc|home|media|mnt|opt|proc|root|run|srv|sys|tmp|usr|var|workspace)(?:/|\b)"
)

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
        "prompting_lint",
        "quarantined_roots",
        "request_id",
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
    dossier_sections: tuple[str, ...]
    prompt: bytes
    prompting_lint: dict[str, Any]
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


def _require_exact_keys(
    value: Mapping[str, Any], keys: frozenset[str], context: str
) -> None:
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise PacketBuildError(
            f"{context} fields differ: missing={missing}, extra={extra}"
        )


def _require_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise PacketBuildError(f"{context} must be a non-empty string")
    return value


def _require_int(value: Any, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PacketBuildError(f"{context} must be a non-negative integer")
    return value


def _require_commit(value: Any, context: str) -> str:
    commit = _require_text(value, context)
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise PacketBuildError(f"{context} must be a full lowercase Git commit SHA")
    return commit


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
    allowed = frozenset({"locator", "bytes", "sha256", "public_commit", "verdict"})
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
    if "public_commit" in binding:
        public_commit = _require_commit(
            binding["public_commit"], f"{context}.public_commit"
        )
        record["public_commit"] = public_commit
        record.update(_git_observation(path, public_commit, data))
    if "verdict" in binding:
        record["verdict"] = _require_text(binding["verdict"], f"{context}.verdict")
    return record


def _git_observation(
    path: Path,
    expected_commit: str,
    expected_data: bytes,
) -> dict[str, str]:
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
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", str(relative)],
        check=False,  # lint-allow: untracked sources are rejected from the inspected returncode below
        capture_output=True,
        text=True,
    )
    if tracked_run.returncode != 0:
        raise PacketBuildError(f"expected Git-tracked source is not tracked: {path}")
    blob_run = subprocess.run(
        ["git", "-C", str(root), "show", f"{expected_commit}:{relative.as_posix()}"],
        check=False,  # lint-allow: nonzero is translated to a blob-specific PacketBuildError below
        capture_output=True,
    )
    if blob_run.returncode != 0:
        error = blob_run.stderr.decode("utf-8", errors="replace").strip()
        raise PacketBuildError(f"cannot read expected Git blob for {path}: {error}")
    if blob_run.stdout != expected_data:
        raise PacketBuildError(
            f"Git-tracked source bytes differ from {expected_commit}:{relative.as_posix()}"
        )
    return {
        "checkout_root": str(root),
        "observed_commit": observed_commit,
        "commit_blob_sha256": _sha256(blob_run.stdout),
    }


def _source_bytes(source: Mapping[str, Any], context: str) -> SourceBytes:
    required = {
        "authorized",
        "bytes",
        "git_tracked",
        "locator",
        "logical",
        "section",
        "sha256",
    }
    git_tracked = source.get("git_tracked")
    if git_tracked is True:
        required.add("expected_commit")
    _require_exact_keys(source, frozenset(required), context)
    if source.get("authorized") is not True:
        raise PacketBuildError(
            f"{context} is not explicitly authorized for transmission"
        )
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
        expected_commit = _require_commit(
            source["expected_commit"], f"{context}.expected_commit"
        )
        record["public_commit"] = expected_commit
        record.update(_git_observation(path, expected_commit, data))
    elif git_tracked is not False:
        raise PacketBuildError(f"{context}.git_tracked must be boolean")
    return SourceBytes(record=record, data=data)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _rejected_input_roots(spec: Mapping[str, Any]) -> tuple[Path, ...]:
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
    return rejected_roots


def _assert_not_rejected_input(
    path: Path, rejected_roots: Sequence[Path], context: str
) -> None:
    for root in rejected_roots:
        if _inside(path, root):
            raise PacketBuildError(
                f"{context} resolves inside rejected candidate root {root}"
            )


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


def _render_manifest(
    task_sources: Sequence[SourceBytes], excluded_stale: Sequence[str]
) -> bytes:
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


def _render_generated_manifest_segment(
    task_sources: Sequence[SourceBytes], excluded_stale: Sequence[str]
) -> tuple[bytes, bytes]:
    manifest = _render_manifest(task_sources, excluded_stale)
    segment = b"".join(
        (
            b"## GENERATED ATTACHED PROVENANCE MANIFEST\n\n# generated_attached_provenance_manifest.json\n",
            manifest,
            b"\n",
        )
    )
    return manifest, segment


def _render_bundle_a(
    request_id: str,
    display_name: str,
    kernel: SourceBytes,
    identity: SourceBytes,
    spotlight: SourceBytes,
) -> bytes:
    return b"".join(
        (
            f"# {request_id} {display_name} Bundle A - Governance\n\n## FAMILY KERNEL\n\n# {kernel.record['logical']}\n\n<!-- BEGIN-VERBATIM: {kernel.record['logical']} -->\n".encode(),
            kernel.data,
            b"\n<!-- END-VERBATIM -->\n",
            f"\n## IDENTITY\n\n# {identity.record['logical']}\n\n<!-- BEGIN-VERBATIM: {identity.record['logical']} -->\n".encode(),
            identity.data,
            b"\n<!-- END-VERBATIM -->\n",
            f"\n## SPOTLIGHT STANDARD FOR INTEGRITY\n\n# {spotlight.record['logical']}\n\n<!-- BEGIN-VERBATIM: {spotlight.record['logical']} -->\n".encode(),
            spotlight.data,
            b"\n<!-- END-VERBATIM -->\n",
        )
    )


def _validate_bundle_a_verbatim_markers(
    bundle_a: bytes, logicals: Sequence[str], context: str
) -> tuple[str, ...]:
    cursor = 0
    end_marker = b"<!-- END-VERBATIM -->"
    for logical in logicals:
        begin_marker = f"<!-- BEGIN-VERBATIM: {logical} -->".encode()
        if bundle_a.count(begin_marker) != 1:
            raise PacketBuildError(
                f"{context} must contain one BEGIN-VERBATIM marker for {logical}"
            )
        begin_index = bundle_a.find(begin_marker, cursor)
        if begin_index < 0:
            raise PacketBuildError(
                f"{context} has out-of-order VERBATIM markers for {logical}"
            )
        end_index = bundle_a.find(end_marker, begin_index + len(begin_marker))
        if end_index < 0:
            raise PacketBuildError(
                f"{context} has no END-VERBATIM marker for {logical}"
            )
        cursor = end_index + len(end_marker)
    if bundle_a.count(end_marker) != len(logicals):
        raise PacketBuildError(f"{context} has an unexpected VERBATIM marker count")
    return tuple(logicals)


def _validate_governance_logicals(
    platform: str,
    kernel: SourceBytes,
    identity: SourceBytes,
    spotlight: SourceBytes,
    context: str,
) -> tuple[str, ...]:
    expected = (
        KERNEL_LOGICAL,
        IDENTITY_BY_PLATFORM[platform],
        SPOTLIGHT_LOGICAL,
    )
    observed = (
        kernel.record["logical"],
        identity.record["logical"],
        spotlight.record["logical"],
    )
    if observed != expected:
        raise PacketBuildError(
            f"{context} governance logicals differ: expected {expected!r}, observed {observed!r}"
        )
    return expected


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


def _expected_blob(
    data: bytes, expected: Mapping[str, Any], context: str
) -> dict[str, Any]:
    _require_exact_keys(expected, frozenset({"bytes", "sha256"}), context)
    expected_bytes = _require_int(expected["bytes"], f"{context}.bytes")
    expected_sha = _require_text(expected["sha256"], f"{context}.sha256")
    observed_sha = _sha256(data)
    if len(data) != expected_bytes or observed_sha != expected_sha:
        raise PacketBuildError(
            f"{context} mismatch: expected {expected_bytes}/{expected_sha}, observed {len(data)}/{observed_sha}"
        )
    return {"bytes": len(data), "sha256": observed_sha}


def _validate_source_inclusion(
    bundle: bytes, sources: Sequence[SourceBytes], context: str
) -> None:
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


def _authored_markdown_lines(text: str) -> tuple[tuple[int, int, str], ...]:
    authored: list[tuple[int, int, str]] = []
    fence_character: str | None = None
    fence_length = 0
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        indent_columns = 0
        for character in line:
            if character == " ":
                indent_columns += 1
            elif character == "\t":
                indent_columns += 4 - (indent_columns % 4)
            else:
                break
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence_character is None and fence is not None:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
        elif fence_character is not None:
            closing = re.fullmatch(
                rf" {{0,3}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*",
                line,
            )
            if closing is not None:
                fence_character = None
                fence_length = 0
        elif indent_columns < 4:
            authored.append((offset, offset + len(raw_line), line))
        offset += len(raw_line)
    return tuple(authored)


def _validate_task_dossier(source: SourceBytes) -> tuple[str, ...]:
    try:
        text = source.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PacketBuildError("corrected request packet is not UTF-8") from exc
    if "<" in text:
        raise PacketBuildError(
            "corrected request packet must not contain raw HTML or angle-bracket syntax"
        )
    markdown_offset = 0
    front_matter = re.match(r"\A---[ \t]*\r?\n", text)
    if front_matter is not None:
        closing = re.search(
            r"^---[ \t]*\r?$",
            text[front_matter.end() :],
            flags=re.MULTILINE,
        )
        if closing is None:
            raise PacketBuildError("corrected request packet front matter is unclosed")
        markdown_offset = front_matter.end() + closing.end()
    authored_lines = tuple(
        (start + markdown_offset, end + markdown_offset, line)
        for start, end, line in _authored_markdown_lines(text[markdown_offset:])
    )
    matches = [
        (start, end, match.group(1).strip())
        for start, end, line in authored_lines
        if (match := re.fullmatch(r"## ([^\r\n]+)\s*", line)) is not None
    ]
    headings = [heading for _, _, heading in matches]
    if headings != list(REQUIRED_DOSSIER_HEADINGS):
        raise PacketBuildError(
            "corrected request packet must contain exactly these dossier headings "
            f"in order: {list(REQUIRED_DOSSIER_HEADINGS)!r}; observed {headings!r}"
        )
    for index, required in enumerate(REQUIRED_DOSSIER_HEADINGS):
        body_start = matches[index][1]
        body_end = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            raise PacketBuildError(
                f"corrected request packet section {required!r} must be non-empty"
            )
        if required == "Problem statement" and not any(
            QUESTION_LINE.fullmatch(line.strip())
            for start, _, line in authored_lines
            if body_start <= start < body_end
        ):
            raise PacketBuildError(
                "corrected request packet Problem statement must contain a question-shaped line"
            )
    return REQUIRED_DOSSIER_HEADINGS


def _run_prompting_lint(source: SourceBytes) -> dict[str, Any]:
    executable_data = _read_regular_file(PROMPTING_LINT, "canonical prompting-lint")
    result = subprocess.run(
        [str(PROMPTING_LINT), "/dev/stdin"],
        input=source.data,
        check=False,  # lint-allow: the exact lint exit and output are validated and receipted below
        capture_output=True,
    )
    try:
        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PacketBuildError(
            "canonical prompting-lint emitted non-UTF-8 output"
        ) from exc
    if result.returncode != 0:
        detail = stderr.strip() or stdout.strip()
        raise PacketBuildError(
            f"canonical prompting-lint rejected {source.record['logical']}: {detail}"
        )
    if not stdout.startswith("LINT PASS: /dev/stdin\n") or stderr:
        raise PacketBuildError("canonical prompting-lint success receipt is malformed")
    return {
        "executable": str(PROMPTING_LINT),
        "executable_bytes": len(executable_data),
        "executable_sha256": _sha256(executable_data),
        "input_logical": source.record["logical"],
        "input_bytes": len(source.data),
        "input_sha256": _sha256(source.data),
        "exit_code": result.returncode,
        "stdout": stdout,
        "stdout_bytes": len(result.stdout),
        "stdout_sha256": _sha256(result.stdout),
        "stderr": stderr,
        "stderr_bytes": len(result.stderr),
        "stderr_sha256": _sha256(result.stderr),
        "result": "PASS",
    }


def _validate_bundle_b_content(
    bundle_b: bytes,
    governance_sources: Sequence[SourceBytes],
) -> None:
    for source in governance_sources:
        if source.data in bundle_b:
            raise PacketBuildError(
                f"Bundle B duplicates governance source {source.record['logical']}"
            )
    match = OPERATOR_LOCAL_PATH.search(bundle_b)
    if match is not None:
        value = match.group(0).decode("utf-8", errors="replace")
        raise PacketBuildError(
            f"Bundle B contains operator-local absolute path prefix {value!r}"
        )


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
    expected_commit = _require_commit(binding["commit"], "builder.commit")
    module_data = _read_regular_file(module_path, "builder module")
    expected_sha = _require_text(binding["module_sha256"], "builder.module_sha256")
    if _sha256(module_data) != expected_sha:
        raise PacketBuildError("builder module hash mismatch")
    git_observation = _git_observation(module_path, expected_commit, module_data)
    return {
        "repo_root": str(repo_root),
        "commit": expected_commit,
        "module": module,
        "module_sha256": _sha256(module_data),
        **git_observation,
    }


def _validate_prompt(text: Any, expected: Mapping[str, Any]) -> bytes:
    prompt = _require_text(text, "prompt.text")
    read_instruction = "Read both attached files fully before answering. "
    follow_instruction = " Follow the governance, evidence, acceptance, and stop conditions in the attachments."
    stop_instruction = (
        " If either attachment is unavailable or incomplete, state that and stop."
    )
    if "\n" in prompt or "\r" in prompt:
        raise PacketBuildError("prompt must be one brief line")
    if not prompt.startswith(read_instruction):
        raise PacketBuildError(
            "prompt does not begin with the contract read-both instruction"
        )
    required_suffix = follow_instruction + stop_instruction
    if not prompt.endswith(required_suffix):
        raise PacketBuildError(
            "prompt does not end with the contract governance and stop instructions"
        )
    core = prompt[len(read_instruction) : -len(required_suffix)]
    if core.count(" Deliver ") != 1:
        raise PacketBuildError(
            "prompt must state one concise request followed by one named deliverable"
        )
    request, deliverable = core.split(" Deliver ", 1)
    if not request.strip() or not request.endswith("."):
        raise PacketBuildError("prompt concise request must be one complete sentence")
    if not deliverable.strip() or not deliverable.endswith("."):
        raise PacketBuildError("prompt named deliverable must be one complete sentence")
    folded = prompt.casefold()
    forbidden = [term for term in FORBIDDEN_PROMPT_TERMS if term in folded]
    if forbidden:
        raise PacketBuildError(
            f"prompt requests builder- or UI-derived claims: {forbidden}"
        )
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
            files.append(
                {
                    "path": relative,
                    "type": "regular",
                    "bytes": len(data),
                    "sha256": _sha256(data),
                }
            )
        elif stat.S_ISDIR(metadata.st_mode):
            files.append({"path": relative, "type": "directory"})
        elif stat.S_ISLNK(metadata.st_mode):
            files.append(
                {"path": relative, "type": "symlink", "target": os.readlink(path)}
            )
        else:
            files.append(
                {
                    "path": relative,
                    "type": "other",
                    "mode": _mode_text(metadata.st_mode),
                }
            )
    return {"root": root_record, "files": files}


def _assert_no_writers(root: Path) -> None:
    result = subprocess.run(
        ["lsof", "+D", str(root)],
        check=False,  # lint-allow: only documented lsof 0/1 statuses are accepted below
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise PacketBuildError(
            f"lsof failed for rejected root {root}: {result.stderr.strip()}"
        )
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
        expected_error = _require_text(
            value["expected_error"], f"{context}.expected_error"
        )
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
    if spec["schema_version"] != SCHEMA_VERSION:
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

    rejected_roots = _rejected_input_roots(spec)
    for root in rejected_roots:
        if _inside(output_root, root) or _inside(root, output_root):
            raise PacketBuildError("output root overlaps a rejected candidate root")

    builder_record = _verify_builder(spec["builder"])
    packet_contract = _binding_record(spec["packet_contract"], "packet_contract")
    fresh_neutrality = _binding_record(spec["fresh_neutrality"], "fresh_neutrality")
    if fresh_neutrality.get("verdict") != "PASS":
        raise PacketBuildError("fresh neutrality must bind a PASS verdict")

    worker_spec_value = spec["worker_spec"]
    if (
        not isinstance(worker_spec_value, dict)
        or "r3_correction" not in worker_spec_value
    ):
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
    packet_sources = [
        source
        for source in task_sources
        if source.record["logical"] == f"packet_{request_id.rsplit('-', 1)[-1]}.md"
    ]
    if len(packet_sources) != 1:
        raise PacketBuildError(
            "task sources must contain the corrected request packet exactly once"
        )
    packet_source = packet_sources[0]
    dossier_sections = _validate_task_dossier(packet_source)
    prompting_lint = _run_prompting_lint(packet_source)

    for source in (kernel, spotlight, *task_sources):
        _assert_not_rejected_input(
            Path(source.record["locator"]), rejected_roots, source.record["logical"]
        )
    for record in (packet_contract, fresh_neutrality, *worker_spec.values()):
        _assert_not_rejected_input(
            Path(record["locator"]), rejected_roots, "provenance input"
        )

    excluded = spec["excluded_stale"]
    if (
        not isinstance(excluded, list)
        or not excluded
        or not all(isinstance(item, str) and item for item in excluded)
    ):
        raise PacketBuildError("excluded_stale must be a non-empty string array")
    generated_manifest_json, generated_manifest = _render_generated_manifest_segment(
        task_sources,
        excluded,
    )
    expected = spec["expected"]
    if not isinstance(expected, dict):
        raise PacketBuildError("expected must be an object")
    _require_exact_keys(
        expected, frozenset({"bundle_b", "generated_manifest", "prompt"}), "expected"
    )
    manifest_record = {
        "logical": "generated_attached_provenance_manifest.json",
        **_expected_blob(
            generated_manifest,
            expected["generated_manifest"],
            "expected.generated_manifest",
        ),
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
        raise PacketBuildError(
            "Bundle B does not contain the generated manifest exactly once"
        )
    _validate_bundle_b_content(bundle_b, (kernel, spotlight))

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
    prompt_expected_hash = {
        key: expected["prompt"][key]
        for key in ("bytes", "sha256")
        if key in expected["prompt"]
    }
    if frozenset(expected["prompt"]) != frozenset({"bytes", "sha256", "text"}):
        raise PacketBuildError("expected.prompt fields differ")
    prompt = _validate_prompt(prompt_text_value, prompt_expected_hash)

    destination_values = governance["destinations"]
    if not isinstance(destination_values, list) or not destination_values:
        raise PacketBuildError(
            "governance.destinations must contain at least one destination"
        )
    if len(destination_values) > len(IDENTITY_BY_PLATFORM):
        raise PacketBuildError(
            "governance.destinations exceeds the five mapped Family platforms"
        )
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
        governance_logicals = _validate_governance_logicals(
            platform, kernel, identity, spotlight, context
        )
        _assert_not_rejected_input(
            Path(identity.record["locator"]), rejected_roots, identity.record["logical"]
        )
        _validate_bundle_b_content(bundle_b, (identity,))
        display_name = _require_text(
            destination["display_name"], f"{context}.display_name"
        )
        bundle_a = _render_bundle_a(
            request_id, display_name, kernel, identity, spotlight
        )
        _validate_bundle_a_verbatim_markers(
            bundle_a,
            governance_logicals,
            f"{platform} Bundle A",
        )
        expected_bundle_a = destination["expected_bundle_a"]
        if not isinstance(expected_bundle_a, dict):
            raise PacketBuildError(f"{context}.expected_bundle_a must be an object")
        _expected_blob(bundle_a, expected_bundle_a, f"{context}.expected_bundle_a")
        _validate_source_inclusion(
            bundle_a, (kernel, identity, spotlight), f"{platform} Bundle A"
        )
        absolute_paths = destination["expected_bundle_a_absolute_paths"]
        if not isinstance(absolute_paths, list):
            raise PacketBuildError(
                f"{context}.expected_bundle_a_absolute_paths must be an array"
            )
        expected_paths = tuple(
            _require_text(value, f"{context}.expected_bundle_a_absolute_paths")
            for value in absolute_paths
        )
        if len(set(expected_paths)) != len(expected_paths):
            raise PacketBuildError(
                f"{context}.expected_bundle_a_absolute_paths contains duplicates"
            )
        observed_paths = tuple(
            path for path in expected_paths if bundle_a.count(path.encode()) == 1
        )
        if observed_paths != expected_paths or bundle_a.count(b"/home/") != len(
            expected_paths
        ):
            raise PacketBuildError(f"{platform} Bundle A absolute-path scope differs")
        send_task = destination["send_task"]
        if not isinstance(send_task, dict):
            raise PacketBuildError(f"{context}.send_task must be an object")
        _require_exact_keys(
            send_task,
            frozenset({"corrected_packet_path", "forbidden_roots", "task_id"}),
            f"{context}.send_task",
        )
        send_task_id = _require_text(
            send_task["task_id"], f"{context}.send_task.task_id"
        )
        corrected_path = _absolute_path(
            send_task["corrected_packet_path"],
            f"{context}.send_task.corrected_packet_path",
        )
        if corrected_path != Path(packet_sources[0].record["locator"]):
            raise PacketBuildError(
                f"{context}.send_task does not bind the corrected packet"
            )
        forbidden_roots = send_task["forbidden_roots"]
        if not isinstance(forbidden_roots, list) or not forbidden_roots:
            raise PacketBuildError(
                f"{context}.send_task.forbidden_roots must be non-empty"
            )
        for forbidden_index, forbidden_value in enumerate(forbidden_roots):
            forbidden = _absolute_path(
                forbidden_value,
                f"{context}.send_task.forbidden_roots[{forbidden_index}]",
            )
            if _inside(output_root, forbidden):
                raise PacketBuildError(
                    f"output root overlaps forbidden ambiguous send root {forbidden}"
                )
        bundle_a_basename = _validate_basename(
            destination["bundle_a_basename"], f"{context}.bundle_a_basename"
        )
        bundle_b_basename = _validate_basename(
            destination["bundle_b_basename"], f"{context}.bundle_b_basename"
        )
        prompt_basename = _validate_basename(
            destination["prompt_basename"], f"{context}.prompt_basename"
        )
        receipt_basename = _validate_basename(
            destination["receipt_basename"], f"{context}.receipt_basename"
        )
        expected_prefix = f"{request_id}-{platform}-"
        if not all(
            name.startswith(expected_prefix)
            for name in (
                bundle_a_basename,
                bundle_b_basename,
                prompt_basename,
                receipt_basename,
            )
        ):
            raise PacketBuildError(
                f"{context} basenames do not bind request and platform"
            )
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
    expected_basename_count = 4 * len(destinations)
    if (
        len(
            {
                name
                for destination in destinations
                for name in (
                    destination.bundle_a_basename,
                    bundle_b_basename_by_platform[destination.platform],
                    destination.prompt_basename,
                    destination.receipt_basename,
                )
            }
        )
        != expected_basename_count
    ):
        raise PacketBuildError(
            "each destination must produce four unique packet basenames"
        )
    for destination in destinations:
        for other_identity in identity_sources:
            count = destination.bundle_a.count(other_identity.data)
            expected_count = 1 if other_identity is destination.identity else 0
            if count != expected_count:
                raise PacketBuildError(
                    f"{destination.platform} Bundle A identity isolation failed"
                )

    negative_controls = _validate_negative_receipts(spec["negative_receipts"])
    return PreparedBuild(
        spec_path=spec_path,
        spec=spec,
        build_spec_record={
            "locator": str(spec_path),
            "bytes": len(spec_data),
            "sha256": _sha256(spec_data),
        },
        output_root=output_root,
        kernel=kernel,
        spotlight=spotlight,
        destinations=tuple(destinations),
        task_sources=task_sources,
        generated_manifest_record=manifest_record,
        generated_manifest=generated_manifest,
        bundle_b_basename_by_platform=bundle_b_basename_by_platform,
        bundle_b=bundle_b,
        dossier_sections=dossier_sections,
        prompt=prompt,
        prompting_lint=prompting_lint,
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


def _close_descriptor(descriptor: int, context: str) -> None:
    active_error = sys.exception()
    try:
        os.close(descriptor)
    except OSError as exc:
        if active_error is None:
            raise
        active_error.add_note(f"{context} descriptor close also failed: {exc}")


def _open_exclusive_at(
    directory_descriptor: int, basename: str, display_path: Path
) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(basename, flags, 0o600, dir_fd=directory_descriptor)
    try:
        metadata = os.fstat(descriptor)
    except BaseException:
        _close_descriptor(descriptor, "exclusive output")
        raise
    try:
        if not stat.S_ISREG(metadata.st_mode):
            raise PacketBuildError(f"exclusive output is not regular: {display_path}")
        if metadata.st_uid != os.geteuid() or _mode_text(metadata.st_mode) != "0600":
            raise PacketBuildError(
                f"exclusive output owner/mode mismatch: {display_path}"
            )
    except BaseException:
        try:
            _remove_exact_entry(
                directory_descriptor,
                basename,
                metadata,
                "invalid exclusive output",
            )
        finally:
            _close_descriptor(descriptor, "invalid exclusive output")
        raise
    return descriptor


def _read_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _require_directory_identity(path: Path, expected: os.stat_result) -> None:
    observed = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(observed.st_mode) or not _same_inode(observed, expected):
        raise PacketBuildError(f"frozen spec output parent identity changed: {path}")


def _remove_exact_entry(
    directory_descriptor: int,
    basename: str,
    expected: os.stat_result,
    context: str,
) -> None:
    try:
        observed = os.stat(
            basename,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if not _same_inode(observed, expected):
        raise PacketBuildError(f"{context} identity changed before cleanup")
    os.unlink(basename, dir_fd=directory_descriptor)
    os.fsync(directory_descriptor)


def _temporary_spec_entry(directory_descriptor: int) -> tuple[int, str]:
    for _ in range(16):
        basename = f".consultation-packet-freeze-{secrets.token_hex(16)}.json"
        try:
            descriptor = _open_exclusive_at(
                directory_descriptor,
                basename,
                Path(basename),
            )
        except FileExistsError:
            continue
        return descriptor, basename
    raise PacketBuildError("cannot allocate an exclusive temporary frozen spec")


def _freeze_builder_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    _require_exact_keys(
        binding,
        frozenset({"commit", "module", "module_sha256", "repo_root"}),
        "draft builder",
    )
    if binding["commit"] is not None or binding["module_sha256"] is not None:
        raise PacketBuildError(
            "draft builder commit and module_sha256 must both be null"
        )
    repo_root = _absolute_path(binding["repo_root"], "draft builder.repo_root")
    module = _require_text(binding["module"], "draft builder.module")
    module_path = repo_root / module
    if module_path.resolve() != Path(__file__).resolve():
        raise PacketBuildError(
            "draft builder.module does not identify the executing module"
        )
    module_data = _read_regular_file(module_path, "draft builder module")
    commit_run = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = _require_commit(commit_run.stdout.strip(), "draft builder observed commit")
    observation = _git_observation(module_path, commit, module_data)
    if Path(observation["checkout_root"]) != repo_root:
        raise PacketBuildError("draft builder.repo_root is not the Git checkout root")
    return {
        "commit": commit,
        "module": module,
        "module_sha256": _sha256(module_data),
        "repo_root": str(repo_root),
    }


def _freeze_dossier_source(
    spec: Mapping[str, Any], source_path: Path
) -> tuple[SourceBytes, tuple[SourceBytes, ...]]:
    request_id = _require_text(spec.get("request_id"), "request_id")
    expected_logical = f"packet_{request_id.rsplit('-', 1)[-1]}.md"
    task_values = spec.get("task_sources")
    if not isinstance(task_values, list) or not task_values:
        raise PacketBuildError("task_sources must be a non-empty array")
    packet_indexes = [
        index
        for index, value in enumerate(task_values)
        if isinstance(value, dict) and value.get("logical") == expected_logical
    ]
    if len(packet_indexes) != 1:
        raise PacketBuildError(
            "draft task sources must contain the corrected request packet exactly once"
        )
    packet_index = packet_indexes[0]
    packet_value = task_values[packet_index]
    if not isinstance(packet_value, dict):
        raise PacketBuildError("draft corrected request packet must be an object")
    packet_keys = {
        "authorized",
        "bytes",
        "git_tracked",
        "locator",
        "logical",
        "section",
        "sha256",
    }
    if packet_value.get("git_tracked") is True:
        packet_keys.add("expected_commit")
    _require_exact_keys(
        packet_value,
        frozenset(packet_keys),
        "draft corrected request packet",
    )
    if (
        _absolute_path(
            packet_value.get("locator"), "draft corrected request packet locator"
        )
        != source_path
    ):
        raise PacketBuildError(
            "--source does not identify the draft corrected request packet"
        )
    if source_path.suffix.casefold() != ".md":
        raise PacketBuildError("--source must identify one Markdown file")
    if packet_value.get("bytes") is not None or packet_value.get("sha256") is not None:
        raise PacketBuildError(
            "draft corrected request packet bytes and sha256 must both be null"
        )
    source_data = _read_regular_file(source_path, "draft corrected request packet")
    packet_value["bytes"] = len(source_data)
    packet_value["sha256"] = _sha256(source_data)
    task_sources = tuple(
        _source_bytes(value, f"task_sources[{index}]")
        for index, value in enumerate(task_values)
        if isinstance(value, dict)
    )
    if len(task_sources) != len(task_values):
        raise PacketBuildError("each task source must be an object")
    return task_sources[packet_index], task_sources


def _freeze_expected_outputs(
    spec: dict[str, Any], source_path: Path
) -> tuple[bytes, bytes, bytes, list[dict[str, Any]]]:
    packet_source, task_sources = _freeze_dossier_source(spec, source_path)
    _validate_task_dossier(packet_source)
    _run_prompting_lint(packet_source)

    expected = spec.get("expected")
    if not isinstance(expected, dict):
        raise PacketBuildError("draft expected must be an object")
    _require_exact_keys(
        expected,
        frozenset({"bundle_b", "generated_manifest", "prompt"}),
        "draft expected",
    )
    if expected["bundle_b"] is not None or expected["generated_manifest"] is not None:
        raise PacketBuildError(
            "draft bundle_b and generated_manifest expectations must both be null"
        )
    prompt_expected = expected["prompt"]
    if not isinstance(prompt_expected, dict):
        raise PacketBuildError("draft expected.prompt must be an object")
    _require_exact_keys(
        prompt_expected,
        frozenset({"bytes", "sha256", "text"}),
        "draft expected.prompt",
    )
    if prompt_expected["bytes"] is not None or prompt_expected["sha256"] is not None:
        raise PacketBuildError("draft prompt bytes and sha256 must both be null")
    prompt_text = _require_text(prompt_expected["text"], "draft expected.prompt.text")
    prompt_data = prompt_text.encode("utf-8")
    prompt = _validate_prompt(
        prompt_text,
        {"bytes": len(prompt_data), "sha256": _sha256(prompt_data)},
    )

    excluded = spec.get("excluded_stale")
    if (
        not isinstance(excluded, list)
        or not excluded
        or not all(isinstance(item, str) and item for item in excluded)
    ):
        raise PacketBuildError("excluded_stale must be a non-empty string array")
    _, generated_manifest = _render_generated_manifest_segment(task_sources, excluded)
    request_id = _require_text(spec.get("request_id"), "request_id")
    bundle_b = _render_bundle_b(
        request_id,
        task_sources,
        generated_manifest,
    )

    governance = spec.get("governance")
    if not isinstance(governance, dict):
        raise PacketBuildError("governance must be an object")
    _require_exact_keys(
        governance,
        frozenset({"destinations", "kernel", "spotlight"}),
        "governance",
    )
    kernel = _source_bytes(governance["kernel"], "governance.kernel")
    spotlight = _source_bytes(governance["spotlight"], "governance.spotlight")
    destination_values = governance["destinations"]
    if not isinstance(destination_values, list) or not destination_values:
        raise PacketBuildError(
            "governance.destinations must contain at least one destination"
        )
    destination_expectations: list[dict[str, Any]] = []
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
        if destination.get("expected_bundle_a") is not None:
            raise PacketBuildError(f"{context}.expected_bundle_a must be null")
        platform = _require_text(destination.get("platform"), f"{context}.platform")
        if platform not in IDENTITY_BY_PLATFORM:
            raise PacketBuildError(f"unsupported destination platform {platform}")
        identity = _source_bytes(destination.get("identity"), f"{context}.identity")
        if identity.record["logical"] != IDENTITY_BY_PLATFORM[platform]:
            raise PacketBuildError(f"{context} has wrong identity mapping")
        governance_logicals = _validate_governance_logicals(
            platform, kernel, identity, spotlight, context
        )
        display_name = _require_text(
            destination.get("display_name"), f"{context}.display_name"
        )
        bundle_a = _render_bundle_a(
            request_id,
            display_name,
            kernel,
            identity,
            spotlight,
        )
        _validate_bundle_a_verbatim_markers(
            bundle_a,
            governance_logicals,
            f"{platform} Bundle A",
        )
        frozen_expectation = {
            "bytes": len(bundle_a),
            "sha256": _sha256(bundle_a),
        }
        destination["expected_bundle_a"] = frozen_expectation
        destination_expectations.append(
            {"platform": platform, "bundle_a": frozen_expectation}
        )

    expected["bundle_b"] = {
        "bytes": len(bundle_b),
        "sha256": _sha256(bundle_b),
    }
    expected["generated_manifest"] = {
        "bytes": len(generated_manifest),
        "sha256": _sha256(generated_manifest),
    }
    expected["prompt"] = {
        "bytes": len(prompt),
        "sha256": _sha256(prompt),
        "text": prompt.decode("utf-8"),
    }
    return bundle_b, generated_manifest, prompt, destination_expectations


def _validate_frozen_spec_bytes(
    data: bytes,
    output_path: Path,
    directory_descriptor: int,
    directory_identity: os.stat_result,
) -> None:
    descriptor, temporary_basename = _temporary_spec_entry(directory_descriptor)
    temporary_identity = os.fstat(descriptor)
    temporary_path = output_path.parent / temporary_basename
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
        _require_directory_identity(output_path.parent, directory_identity)
        _prepare_build(temporary_path)
    finally:
        try:
            _remove_exact_entry(
                directory_descriptor,
                temporary_basename,
                temporary_identity,
                "temporary frozen spec",
            )
        finally:
            _close_descriptor(descriptor, "temporary frozen spec")


def _write_frozen_spec_output(
    data: bytes,
    output_path: Path,
    directory_descriptor: int,
    directory_identity: os.stat_result,
) -> None:
    descriptor = _open_exclusive_at(
        directory_descriptor,
        output_path.name,
        output_path,
    )
    output_identity = os.fstat(descriptor)
    completed = False
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
        if _read_descriptor(descriptor) != data:
            raise PacketBuildError("frozen build spec final reread mismatch")
        observed = os.stat(
            output_path.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if not _same_inode(observed, output_identity):
            raise PacketBuildError("frozen build spec identity changed after write")
        os.fsync(directory_descriptor)
        _require_directory_identity(output_path.parent, directory_identity)
        completed = True
    finally:
        try:
            if not completed:
                _remove_exact_entry(
                    directory_descriptor,
                    output_path.name,
                    output_identity,
                    "incomplete frozen spec output",
                )
        finally:
            _close_descriptor(descriptor, "frozen spec output")


def freeze_consultation_spec(
    draft_spec_path: str | Path,
    source_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    draft_path = _absolute_path(str(draft_spec_path), "draft spec path")
    source = _absolute_path(str(source_path), "source path")
    output = _absolute_path(str(output_path), "frozen spec output path")
    if len({draft_path, source, output}) != 3:
        raise PacketBuildError("draft spec, source, and frozen output must differ")
    if output.exists() or output.is_symlink():
        raise PacketBuildError(f"frozen spec output already exists: {output}")
    _assert_no_symlink_components(output, include_leaf=False)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    directory_descriptor = os.open(output.parent, directory_flags)
    try:
        directory_identity = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(directory_identity.st_mode)
            or directory_identity.st_uid != os.geteuid()
        ):
            raise PacketBuildError(
                "effective user does not own frozen spec output parent"
            )
        _require_directory_identity(output.parent, directory_identity)

        draft_data = _read_regular_file(draft_path, "draft build spec")
        spec = _strict_json(draft_data, "draft build spec")
        _require_exact_keys(spec, TOP_LEVEL_SPEC_KEYS, "draft build spec")
        if spec.get("schema_version") != SCHEMA_VERSION:
            raise PacketBuildError("unsupported draft build spec schema_version")
        _assert_not_rejected_input(
            output,
            _rejected_input_roots(spec),
            "frozen spec output",
        )
        builder = spec.get("builder")
        if not isinstance(builder, dict):
            raise PacketBuildError("draft builder must be an object")
        spec["builder"] = _freeze_builder_binding(builder)
        bundle_b, generated_manifest, prompt, destinations = _freeze_expected_outputs(
            spec, source
        )
        frozen_data = _json_bytes(spec)
        _validate_frozen_spec_bytes(
            frozen_data,
            output,
            directory_descriptor,
            directory_identity,
        )
        _write_frozen_spec_output(
            frozen_data,
            output,
            directory_descriptor,
            directory_identity,
        )
    finally:
        os.close(directory_descriptor)
    return {
        "status": "spec_frozen",
        "draft_spec": str(draft_path),
        "source": str(source),
        "frozen_spec": {
            "path": str(output),
            "bytes": len(frozen_data),
            "sha256": _sha256(frozen_data),
        },
        "expectations": {
            "bundle_b": {"bytes": len(bundle_b), "sha256": _sha256(bundle_b)},
            "generated_manifest": {
                "bytes": len(generated_manifest),
                "sha256": _sha256(generated_manifest),
            },
            "prompt": {"bytes": len(prompt), "sha256": _sha256(prompt)},
            "destinations": destinations,
        },
        "ui_actions": False,
    }


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
        source
        for source in prepared.task_sources
        if source.record["logical"].startswith("packet_")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": prepared.spec["request_id"],
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
        "prompting_lint": prepared.prompting_lint,
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
            "bundle_a_verbatim_sources": [
                prepared.kernel.record["logical"],
                destination.identity.record["logical"],
                prepared.spotlight.record["logical"],
            ],
            "bundle_b_exact_once_count": len(prepared.task_sources),
            "bundle_b_required_dossier_sections": list(prepared.dossier_sections),
            "deterministic_order": True,
            "destination_identity_isolation": True,
            "governance_absent_from_bundle_b": True,
            "attached_manifest_task_source_count": len(prepared.task_sources),
            "attached_manifest_self_record_count": 1,
            "bundle_b_cross_destination_cmp": True,
            "prompt_cross_destination_cmp": True,
            "exactly_two_attachment_designation_per_destination": True,
            "immutable_source_content_absolute_paths": list(
                destination.expected_absolute_paths
            ),
            "immutable_source_content_path_hits": {
                "bundle_a": len(destination.expected_absolute_paths),
                "bundle_b": 0,
            },
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


def _validate_prompting_lint_receipt(
    value: Any,
    packet_source: Mapping[str, Any],
) -> None:
    if not isinstance(value, dict):
        raise PacketBuildError("receipt prompting_lint must be an object")
    _require_exact_keys(
        value,
        frozenset(
            {
                "executable",
                "executable_bytes",
                "executable_sha256",
                "exit_code",
                "input_bytes",
                "input_logical",
                "input_sha256",
                "result",
                "stderr",
                "stderr_bytes",
                "stderr_sha256",
                "stdout",
                "stdout_bytes",
                "stdout_sha256",
            }
        ),
        "receipt prompting_lint",
    )
    if value["executable"] != str(PROMPTING_LINT):
        raise PacketBuildError("receipt prompting_lint executable is not canonical")
    if value["exit_code"] != 0 or value["result"] != "PASS":
        raise PacketBuildError("receipt prompting_lint does not record a PASS exit")
    if value["input_logical"] != packet_source.get("logical"):
        raise PacketBuildError("receipt prompting_lint input logical name is unbound")
    if value["input_bytes"] != packet_source.get("bytes"):
        raise PacketBuildError("receipt prompting_lint input byte count is unbound")
    if value["input_sha256"] != packet_source.get("sha256"):
        raise PacketBuildError("receipt prompting_lint input digest is unbound")
    stdout = _require_text(value["stdout"], "receipt prompting_lint stdout").encode(
        "utf-8"
    )
    stderr_value = value["stderr"]
    if not isinstance(stderr_value, str):
        raise PacketBuildError("receipt prompting_lint stderr must be text")
    stderr = stderr_value.encode("utf-8")
    if not stdout.startswith(b"LINT PASS: /dev/stdin\n") or stderr:
        raise PacketBuildError("receipt prompting_lint output is not a canonical PASS")
    for label, data in (("stdout", stdout), ("stderr", stderr)):
        if value[f"{label}_bytes"] != len(data) or value[f"{label}_sha256"] != _sha256(
            data
        ):
            raise PacketBuildError(f"receipt prompting_lint {label} binding mismatch")
    executable_sha = _require_text(
        value["executable_sha256"],
        "receipt prompting_lint executable_sha256",
    )
    if re.fullmatch(r"[0-9a-f]{64}", executable_sha) is None:
        raise PacketBuildError("receipt prompting_lint executable digest is malformed")
    _require_int(value["executable_bytes"], "receipt prompting_lint executable_bytes")


def validate_consultation_bundle_receipt(receipt_path: str | Path) -> dict[str, Any]:
    path = _absolute_path(str(receipt_path), "receipt path")
    receipt = _strict_json(_read_regular_file(path, "receipt"), "receipt")
    root = receipt.get("root")
    if not isinstance(root, dict):
        raise PacketBuildError(
            "receipt root must be an object derived from os.stat(actual_root)"
        )
    _require_exact_keys(
        root,
        frozenset({"mode", "owner_gid", "owner_uid", "path", "type"}),
        "receipt.root",
    )
    if root["path"] != str(path.parent) or root["type"] != "directory":
        raise PacketBuildError(
            "receipt root.path must equal dirname(abspath(receipt_path))"
        )
    observed_root = _observed_path_record(path.parent, "directory")
    if root != observed_root:
        raise PacketBuildError(
            "receipt root metadata does not match os.stat(actual_root)"
        )
    _require_exact_keys(receipt, RECEIPT_KEYS, "receipt")
    if receipt["schema_version"] != SCHEMA_VERSION:
        raise PacketBuildError("receipt schema_version is unsupported")
    request_id = _require_text(receipt["request_id"], "receipt request_id")
    destination = _require_text(receipt["destination"], "receipt destination")
    if destination not in IDENTITY_BY_PLATFORM:
        raise PacketBuildError("receipt destination is unsupported")
    expected_prefix = f"{request_id}-{destination}-"
    if not path.name.startswith(expected_prefix):
        raise PacketBuildError(
            "receipt basename is not bound to request_id and destination"
        )
    if "files_inventory" in receipt or "no_abs_in_attachments" in receipt:
        raise PacketBuildError("receipt contains superseded provenance fields")
    worker_spec = receipt["worker_spec"]
    if not isinstance(worker_spec, dict) or "r3_correction" not in worker_spec:
        raise PacketBuildError("receipt must preserve worker_spec.r3_correction")
    files = receipt["files"]
    if (
        not isinstance(files, list)
        or len(files) < 4
        or len(files) > 4 * len(IDENTITY_BY_PLATFORM)
        or len(files) % 4 != 0
    ):
        raise PacketBuildError(
            "receipt files must contain four generated files per destination"
        )
    if len({item.get("basename") for item in files if isinstance(item, dict)}) != len(
        files
    ):
        raise PacketBuildError("receipt files basenames must be unique")
    expected_basenames = sorted(item["basename"] for item in files)
    with os.scandir(path.parent) as entries:
        live_basenames = sorted(entry.name for entry in entries)
    if live_basenames != expected_basenames:
        raise PacketBuildError(
            "live output directory entries differ from the receipt's exact file inventory"
        )
    observed_files: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            raise PacketBuildError("receipt file entry must be an object")
        _require_exact_keys(
            item,
            frozenset({"basename", "mode", "owner_gid", "owner_uid", "type"}),
            "receipt file",
        )
        basename = _validate_basename(item["basename"], "receipt file basename")
        observed_files.append(_observed_path_record(path.parent / basename, "regular"))
    if files != observed_files:
        raise PacketBuildError("receipt file inventory differs from live output root")
    if receipt["checks"].get("generated_regular_file_count") != len(files):
        raise PacketBuildError(
            "receipt generated_regular_file_count must equal the live file count"
        )
    if any(receipt["actions"].get(key) is not False for key in PROHIBITED_ACTIONS):
        raise PacketBuildError("receipt prohibited action fields must all be false")
    attachments = receipt["attachments"]
    if not isinstance(attachments, dict) or frozenset(attachments) != frozenset(
        {"a", "b"}
    ):
        raise PacketBuildError("receipt must designate exactly Bundle A and Bundle B")
    attachment_data: dict[str, bytes] = {}
    for label, attachment in attachments.items():
        if not isinstance(attachment, dict):
            raise PacketBuildError(f"attachment {label} must be an object")
        _require_exact_keys(
            attachment,
            frozenset({"basename", "bytes", "sha256"}),
            f"attachment {label}",
        )
        attachment_path = path.parent / _validate_basename(
            attachment["basename"], f"attachment {label} basename"
        )
        if not attachment_path.name.startswith(expected_prefix):
            raise PacketBuildError(
                f"attachment {label} basename is not bound to request_id and destination"
            )
        data = _read_regular_file(attachment_path, f"attachment {label}")
        if len(data) != attachment["bytes"] or _sha256(data) != attachment["sha256"]:
            raise PacketBuildError(f"attachment {label} content address mismatch")
        attachment_data[label] = data
    governance_sources = receipt["governance_sources"]
    if (
        not isinstance(governance_sources, list)
        or len(governance_sources) != 3
        or not all(isinstance(source, dict) for source in governance_sources)
    ):
        raise PacketBuildError("receipt governance sources must contain three records")
    governance_logicals = [source.get("logical") for source in governance_sources]
    expected_governance_logicals = [
        KERNEL_LOGICAL,
        IDENTITY_BY_PLATFORM[destination],
        SPOTLIGHT_LOGICAL,
    ]
    if governance_logicals != expected_governance_logicals:
        raise PacketBuildError("receipt governance source identities are incorrect")
    checks = receipt["checks"]
    if not isinstance(checks, dict):
        raise PacketBuildError("receipt checks must be an object")
    if checks.get("bundle_a_verbatim_sources") != governance_logicals:
        raise PacketBuildError("receipt Bundle A VERBATIM source evidence is incomplete")
    _validate_bundle_a_verbatim_markers(
        attachment_data["a"], governance_logicals, "receipt Bundle A"
    )
    prompt = receipt["prompt"]
    if not isinstance(prompt, dict):
        raise PacketBuildError("receipt prompt must be an object")
    _require_exact_keys(
        prompt, frozenset({"basename", "bytes", "sha256", "text"}), "receipt prompt"
    )
    prompt_path = path.parent / _validate_basename(
        prompt["basename"], "receipt prompt basename"
    )
    if not prompt_path.name.startswith(expected_prefix):
        raise PacketBuildError(
            "receipt prompt basename is not bound to request_id and destination"
        )
    prompt_data = _read_regular_file(prompt_path, "receipt prompt")
    if (
        prompt_data != prompt["text"].encode()
        or len(prompt_data) != prompt["bytes"]
        or _sha256(prompt_data) != prompt["sha256"]
    ):
        raise PacketBuildError("receipt prompt binding mismatch")
    send_task = receipt["send_task"]
    if not isinstance(send_task, dict):
        raise PacketBuildError("receipt send_task must be an object")
    _require_exact_keys(
        send_task,
        frozenset(
            {
                "attachment_paths",
                "corrected_packet_path",
                "prompt_path",
                "status",
                "task_id",
            }
        ),
        "receipt send_task",
    )
    expected_attachment_paths = [
        str(path.parent / attachments[label]["basename"]) for label in ("a", "b")
    ]
    if send_task["attachment_paths"] != expected_attachment_paths:
        raise PacketBuildError(
            "receipt send_task attachment paths are not the actual r5 files"
        )
    if send_task["prompt_path"] != str(prompt_path):
        raise PacketBuildError(
            "receipt send_task prompt path is not the actual r5 prompt"
        )
    corrected_packet = _absolute_path(
        send_task["corrected_packet_path"], "receipt corrected packet"
    )
    packet_records = [
        source
        for source in receipt["sources"]
        if source.get("logical", "").startswith("packet_")
    ]
    if len(packet_records) != 1 or packet_records[0].get("locator") != str(
        corrected_packet
    ):
        raise PacketBuildError(
            "receipt send_task does not bind the corrected packet source"
        )
    _validate_prompting_lint_receipt(receipt["prompting_lint"], packet_records[0])
    if receipt["checks"].get("bundle_b_required_dossier_sections") != list(
        REQUIRED_DOSSIER_HEADINGS
    ):
        raise PacketBuildError(
            "receipt required dossier section evidence is incomplete"
        )
    quarantine = receipt["quarantined_roots"]
    if (
        not isinstance(quarantine, dict)
        or quarantine.get("unchanged") is not True
        or quarantine.get("before") != quarantine.get("after")
    ):
        raise PacketBuildError(
            "receipt rejected-root before/after evidence is not unchanged"
        )
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
        content_by_basename[
            prepared.bundle_b_basename_by_platform[destination.platform]
        ] = prepared.bundle_b
        content_by_basename[destination.prompt_basename] = prepared.prompt
        content_by_basename[destination.receipt_basename] = b""
    descriptors: dict[str, int] = {}
    try:
        for basename in sorted(content_by_basename):
            path = prepared.output_root / basename
            descriptors[basename] = _open_exclusive(path)
            file_paths.append(path)
        files = [_observed_path_record(path, "regular") for path in sorted(file_paths)]
        expected_file_count = 4 * len(prepared.destinations)
        if len(files) != expected_file_count:
            raise PacketBuildError(
                "construction did not create four regular files per destination"
            )
        expected_basenames = sorted(content_by_basename)
        with os.scandir(prepared.output_root) as entries:
            live_basenames = sorted(entry.name for entry in entries)
        if live_basenames != expected_basenames:
            raise PacketBuildError(
                "live output directory entries differ from the exact intended basenames"
            )

        for basename, data in content_by_basename.items():
            if data:
                _write_all(descriptors[basename], data)
                os.fsync(descriptors[basename])
        for destination in prepared.destinations:
            reread = {
                destination.bundle_a_basename: destination.bundle_a,
                prepared.bundle_b_basename_by_platform[
                    destination.platform
                ]: prepared.bundle_b,
                destination.prompt_basename: prepared.prompt,
            }
            for basename, expected_data in reread.items():
                observed_data = _read_regular_file(
                    prepared.output_root / basename, f"final reread {basename}"
                )
                if observed_data != expected_data:
                    raise PacketBuildError(f"final reread mismatch for {basename}")

        quarantine_after = {
            str(root): _snapshot_root(root) for root in prepared.rejected_roots
        }
        if quarantine_before != quarantine_after:
            raise PacketBuildError(
                "a rejected candidate root changed during construction"
            )

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
                raise PacketBuildError(
                    "derived receipt root differs from actual target"
                )
            receipt_bytes = _json_bytes(receipt)
            _write_all(descriptors[destination.receipt_basename], receipt_bytes)
            os.fsync(descriptors[destination.receipt_basename])
        directory_descriptor = os.open(
            prepared.output_root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        )
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
        result_files.append(
            {"path": str(path), "bytes": len(data), "sha256": _sha256(data)}
        )
    for destination in prepared.destinations:
        validate_consultation_bundle_receipt(
            prepared.output_root / destination.receipt_basename
        )
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
        "bundle_b": {
            "bytes": len(prepared.bundle_b),
            "sha256": _sha256(prepared.bundle_b),
        },
        "dossier_sections": list(prepared.dossier_sections),
        "generated_manifest": prepared.generated_manifest_record,
        "prompt": {"bytes": len(prepared.prompt), "sha256": _sha256(prepared.prompt)},
        "prompting_lint": prepared.prompting_lint,
        "destinations": [
            {
                "platform": destination.platform,
                "bundle_a": {
                    "bytes": len(destination.bundle_a),
                    "sha256": _sha256(destination.bundle_a),
                },
                "send_task_id": destination.send_task_id,
            }
            for destination in prepared.destinations
        ],
        "negative_controls": list(prepared.negative_controls),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build PACKET_CONTRACT two-attachment consultation sets."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "build"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--spec", required=True)
    freeze_parser = subparsers.add_parser("freeze-spec")
    freeze_parser.add_argument("--draft-spec", required=True)
    freeze_parser.add_argument("--source", required=True)
    freeze_parser.add_argument("--output", required=True)
    receipt_parser = subparsers.add_parser("validate-receipt")
    receipt_parser.add_argument("receipt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "freeze-spec":
            result = freeze_consultation_spec(
                args.draft_spec,
                args.source,
                args.output,
            )
        elif args.command == "preflight":
            result = preflight_consultation_bundles(args.spec)
        elif args.command == "build":
            result = build_consultation_bundles(args.spec)
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
