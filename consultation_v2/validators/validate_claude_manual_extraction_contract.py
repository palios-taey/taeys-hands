#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.platforms.claude.downloaded_artifact import (
    ClaudeArtifactDownloadError,
    ClaudeDownloadScope,
    materialize_claude_download,
    snapshot_claude_downloads,
    write_download_receipt,
)
from consultation_v2.yaml_contract import get_extraction
from consultation_v2.types import ElementRef, Snapshot
import scripts.run_manual_chat_worker as worker
from scripts.run_manual_chat_worker import (
    _classify_claude_extraction_snapshot,
    _claude_extraction_mode,
    _create_request,
    _extract_content,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _scope(root: Path) -> ClaudeDownloadScope:
    profile = root / "profile"
    downloads = root / "Downloads"
    profile.mkdir()
    downloads.mkdir()
    preferences = profile / "prefs.js"
    preferences.write_text("// isolated validator profile\n", encoding="utf-8")
    return ClaudeDownloadScope(
        display=":3",
        firefox_pid=1234,
        process_start_ticks=5678,
        profile_path=profile,
        preferences_path=preferences,
        download_preferences_sha256="a" * 64,
        directory=downloads,
        directory_source="profile_pref_default_downloads",
    )


def _receipt(mode: str) -> str:
    artifact = mode == "downloaded_file"
    lines = [
        f"extraction_mode={mode}",
        f"classification_revision={'b' * 64}",
        f"generated_artifact_controls_section_count={int(artifact)}",
        f"generated_artifact_view_button_count={int(artifact)}",
        f"generated_artifact_download_button_count={int(artifact)}",
        f"artifact_download_click_count={int(artifact)}",
        "artifact_view_click_count=0",
        "artifact_copy_click_count=0",
        "generic_artifact_click_count=0",
        f"assistant_copy_click_count={int(not artifact)}",
        f"clipboard_read_count={int(not artifact)}",
        f"post_download_observe_count={int(artifact)}",
    ]
    if artifact:
        lines.append(f"post_download_revision={'c' * 64}")
    return "\n".join(lines) + "\n"


def _artifact_snapshot(counts: tuple[int, int, int]) -> Snapshot:
    mapped: dict[str, list[ElementRef]] = {}
    for key, count in zip(worker.CLAUDE_ARTIFACT_CONTROL_KEYS, counts, strict=True):
        mapped[key] = [
            ElementRef(
                key=key,
                name=f"{key}-{index}",
                role="push button",
                x=10 + index,
                y=20 + index,
                states=["enabled", "showing"],
            )
            for index in range(count)
        ]
    return Snapshot(
        platform="claude",
        url="https://claude.ai/chat/contract",
        mapped=mapped,
        raw_count=sum(counts),
    )


def _expect_download_error(action, expected: str) -> None:
    try:
        action()
    except ClaudeArtifactDownloadError as exc:
        _require(expected in str(exc), f"unexpected download refusal: {exc}")
    else:
        raise AssertionError(f"Claude download did not refuse {expected}")


def main() -> int:
    assistant = get_extraction("claude", "assistant_text")
    downloaded = get_extraction("claude", "downloaded_file")
    _require(assistant is not None, "Claude assistant_text extraction is missing")
    _require(downloaded is not None, "Claude downloaded_file extraction is missing")
    _require(
        tuple(
            (step.action, step.element, step.select, step.validation)
            for step in assistant.steps
        )
        == (
            ("scroll_to_bottom", "message_actions_button", "last", None),
            ("hover", "message_actions_button", "last", None),
            ("copy_element", "copy_button", "last", None),
            ("read_clipboard", None, "last", None),
        ),
        "Claude assistant_text extraction drifted",
    )
    _require(
        tuple(
            (step.action, step.element, step.select, step.validation)
            for step in downloaded.steps
        )
        == (("download", "generated_artifact_download_button", "last", None),),
        "Claude downloaded_file extraction must contain one exact download action",
    )

    assistant_card = _extract_content(
        "monitor-contract",
        "claude",
        ":3",
        Path("/frozen/response.txt"),
        claude_extraction_mode="assistant_text",
        claude_launcher_revision="a" * 64,
    )
    download_card = _extract_content(
        "monitor-contract",
        "claude",
        ":3",
        Path("/frozen/response.txt"),
        claude_extraction_mode="downloaded_file",
        claude_launcher_revision="a" * 64,
    )
    _require(
        "extraction_mode=assistant_text" in assistant_card
        and "exactly 0 generated_artifact_controls_section" in assistant_card
        and "action=read_clipboard" in assistant_card
        and "element=generated_artifact_download_button exactly once"
        not in assistant_card,
        "Claude assistant card is not one exact branch",
    )
    _require(
        "extraction_mode=downloaded_file" in download_card
        and "exactly 1 generated_artifact_controls_section" in download_card
        and download_card.count(
            "action=click, element=generated_artifact_download_button exactly once"
        )
        == 1
        and "Do not click generated_artifact_view_button" in download_card
        and "action=read_clipboard" not in download_card
        and "make a second Download or Copy attempt" in download_card,
        "Claude artifact branch lost one-click or no-fallback authority",
    )
    _require(
        "classify-to-execute drift" in assistant_card
        and "classify-to-execute drift" in download_card,
        "Claude extraction cards do not stop on launcher/worker drift",
    )

    assistant_snapshot = _artifact_snapshot((0, 0, 0))
    downloaded_snapshot = _artifact_snapshot((1, 1, 1))
    _require(
        _classify_claude_extraction_snapshot(assistant_snapshot)[0]
        == "assistant_text"
        and _classify_claude_extraction_snapshot(downloaded_snapshot)[0]
        == "downloaded_file",
        "canonical Claude snapshot classifier rejected exact branches",
    )
    try:
        _classify_claude_extraction_snapshot(_artifact_snapshot((1, 0, 1)))
    except RuntimeError:
        pass
    else:
        raise AssertionError("canonical Claude snapshot classifier accepted a partial trio")

    with (
        patch.object(worker, "_bind_claude_observation_display"),
        patch.object(
            worker,
            "_build_canonical_claude_snapshot",
            return_value=assistant_snapshot,
        ),
        patch.object(
            worker,
            "resolve_claude_download_scope",
            side_effect=AssertionError("assistant branch resolved download scope"),
        ),
        patch.object(
            worker,
            "snapshot_claude_downloads",
            side_effect=AssertionError("assistant branch captured download manifest"),
        ),
    ):
        prepared_mode, _revision, _counts, prepared_downloads = (
            worker._prepare_claude_extraction(":3")
        )
    _require(
        prepared_mode == "assistant_text" and prepared_downloads is None,
        "Claude assistant preflight acquired a download dependency",
    )

    with tempfile.TemporaryDirectory() as raw_root:
        request_path = Path(raw_root) / "request.json"
        _create_request(request_path, "frozen\n")
        try:
            _create_request(request_path, "frozen\n")
        except RuntimeError:
            pass
        else:
            raise AssertionError("Claude final request creation accepted a retry")

    _require(
        _claude_extraction_mode(_receipt("assistant_text")) == "assistant_text"
        and _claude_extraction_mode(_receipt("downloaded_file"))
        == "downloaded_file",
        "Claude extraction receipt classifier rejected valid branch cardinality",
    )
    invalid_receipt = _receipt("downloaded_file").replace(
        "artifact_download_click_count=1",
        "artifact_download_click_count=2",
    )
    try:
        _claude_extraction_mode(invalid_receipt)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Claude extraction receipt accepted two Download clicks")
    try:
        _claude_extraction_mode(_receipt("downloaded_file"), "assistant_text")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Claude extraction receipt crossed the launcher branch")

    with tempfile.TemporaryDirectory() as raw_root:
        artifact_root = Path(raw_root) / "prepared"
        response_file = artifact_root / "response.txt"
        environment = os.environ.copy()
        environment.pop("DISPLAY", None)
        environment.pop("AT_SPI_BUS_ADDRESS", None)
        prepared = subprocess.run(
            [
                sys.executable,
                "-P",
                str(REPO_ROOT / "scripts" / "run_manual_chat_worker.py"),
                "extract",
                "--platform",
                "claude",
                "--display",
                ":3",
                "--seat-id",
                "contract-seat",
                "--artifact-root",
                str(artifact_root),
                "--monitor-id",
                "contract-monitor",
                "--response-file",
                str(response_file),
                "--prepare-only",
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # lint-allow: validator asserts the prepare-only exit and stderr
        )
        _require(
            prepared.returncode == 0,
            f"Claude prepare-only failed without display state: {prepared.stderr}",
        )
        prepared_result = json.loads(prepared.stdout)
        _require(
            prepared_result["request_json"] == str(artifact_root / "request.json")
            and not (artifact_root / "request.json").exists()
            and (artifact_root / ".prepared").is_file(),
            "Claude prepare-only created the final request or lost its handoff marker",
        )

    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        scope = _scope(root)
        (scope.directory / "existing.txt").write_text("before", encoding="utf-8")
        before = snapshot_claude_downloads(scope)
        payload = b"# Exact generated artifact\n\nSix headings preserved.\n"
        (scope.directory / "artifact.md").write_bytes(payload)
        destination = root / "response.txt"
        receipt = materialize_claude_download(
            before,
            destination,
            timeout=1.0,
            interval=0.01,
            scope_resolver=lambda _display: scope,
        )
        _require(
            destination.read_bytes() == payload
            and destination.stat().st_mode & 0o777 == 0o600
            and receipt["source"]["sha256"] == hashlib.sha256(payload).hexdigest()
            and receipt["destination"]["path"] == str(destination),
            "Claude download materialization changed bytes, mode, or provenance",
        )
        receipt_path = root / "download_receipt.json"
        write_download_receipt(receipt_path, receipt)
        _require(
            receipt_path.is_file()
            and receipt_path.stat().st_mode & 0o777 == 0o600
            and receipt_path.stat().st_size > 0,
            "Claude download receipt is not an exclusive private artifact",
        )

    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        scope = _scope(root)
        before = snapshot_claude_downloads(scope)
        (scope.directory / "one.md").write_text("one", encoding="utf-8")
        (scope.directory / "two.md").write_text("two", encoding="utf-8")
        _expect_download_error(
            lambda: materialize_claude_download(
                before,
                root / "response.txt",
                timeout=0.1,
                interval=0.01,
                scope_resolver=lambda _display: scope,
            ),
            "multiple complete",
        )

    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        scope = _scope(root)
        before = snapshot_claude_downloads(scope)
        (scope.directory / "artifact.part").write_text("partial", encoding="utf-8")
        _expect_download_error(
            lambda: materialize_claude_download(
                before,
                root / "response.txt",
                timeout=0.05,
                interval=0.01,
                scope_resolver=lambda _display: scope,
            ),
            "no unique stable",
        )

    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        scope = _scope(root)
        target = root / "target.md"
        target.write_text("linked", encoding="utf-8")
        before = snapshot_claude_downloads(scope)
        (scope.directory / "artifact.md").symlink_to(target)
        _expect_download_error(
            lambda: materialize_claude_download(
                before,
                root / "response.txt",
                timeout=0.1,
                interval=0.01,
                scope_resolver=lambda _display: scope,
            ),
            "changed ambiguously",
        )

    print("claude manual extraction contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
