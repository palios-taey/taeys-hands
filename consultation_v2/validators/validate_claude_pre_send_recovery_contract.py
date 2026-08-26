#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.yaml_contract import load_platform_yaml  # noqa: E402
from scripts import run_manual_chat_worker as worker  # noqa: E402


SOURCE_IDENTITY = "taey-revenue-ui-recovery-parallel10-20260826-claude"
RECOVERY_SEAT = "taey-claude-memory-recovery-20260826a"


def _receipt() -> str:
    return "\n".join((
        "CLAUDE PRE-SEND RECOVERY RECEIPT",
        "platform: claude",
        "display: :3",
        f"source_terminal_identity: {SOURCE_IDENTITY}",
        "exception_key: memory_review",
        f"classification_revision_1: {'a' * 64}",
        f"classification_revision_2: {'b' * 64}",
        "clicked_element: claude_memory_not_now",
        "click_count: 1",
        "navigation_postcondition_elements: input, model_selector, toggle_menu",
        "stable_cycles: 2",
        f"post_recovery_revision_1: {'c' * 64}",
        f"post_recovery_revision_2: {'d' * 64}",
        "interstitial_absent: true",
        "attached: false",
        "pasted: false",
        "sent: false",
        "recovered: true",
    ))


def _fake_invoke(*, root: Path, **_kwargs):
    request = root / "request.json"
    headers = root / "response.headers"
    response = root / "worker_response.json"
    request.write_text("{}\n", encoding="utf-8")
    headers.write_text("HTTP/1.1 200 OK\n", encoding="utf-8")
    response.write_text("{}\n", encoding="utf-8")
    return request, headers, response, _receipt()


def _run_main(arguments: list[str]) -> dict:
    output = StringIO()
    with (
        patch.object(sys, "argv", [str(worker.__file__), *arguments]),
        patch.object(worker, "_invoke", _fake_invoke),
        patch.object(worker, "_release_extract_lease", return_value="released"),
        redirect_stdout(output),
    ):
        assert worker.main() == 0
    return json.loads(output.getvalue())


def main() -> int:
    cfg = load_platform_yaml("claude")
    element_map = cfg["tree"]["element_map"]
    assert element_map["claude_memory_review_dialog"] == {
        "name": "Review updates to Claude’s memory",
        "role": "dialog",
        "scope": "pre_send.exception",
    }
    assert element_map["claude_memory_not_now"] == {
        "name": "Not now",
        "role": "push button",
        "scope": "pre_send.exception",
    }
    spec = worker._claude_pre_send_recovery_spec("memory_review")
    assert spec["detect"] == (
        "claude_memory_review_dialog",
        "claude_memory_not_now",
    )
    assert spec["navigation_controls"] == (
        "input",
        "model_selector",
        "toggle_menu",
    )
    assert spec["element"] == "claude_memory_not_now"
    assert spec["stable_cycles"] == 2
    assert spec["max_samples"] == 48
    content = worker._claude_pre_send_recovery_content(
        ":3",
        "memory_review",
        SOURCE_IDENTITY,
    )
    assert content.count("click element=claude_memory_not_now exactly once") == 1
    assert "Do not attach, paste, send, extract, navigate" in content
    assert "Require 2 consecutive matching samples" in content
    assert SOURCE_IDENTITY in content

    parser = worker.build_parser()
    parsed = parser.parse_args([
        "recover-claude-pre-send",
        "--display", ":3",
        "--seat-id", RECOVERY_SEAT,
        "--artifact-root", "/private/new-artifact-root",
        "--exception-key", "memory_review",
        "--source-terminal-identity", SOURCE_IDENTITY,
    ])
    assert parsed.platform == "claude"
    assert parsed.phase == "recover-claude-pre-send"

    with tempfile.TemporaryDirectory() as temporary:
        result = _run_main([
            "recover-claude-pre-send",
            "--display", ":3",
            "--seat-id", RECOVERY_SEAT,
            "--artifact-root", str(Path(temporary) / "recovery"),
            "--exception-key", "memory_review",
            "--source-terminal-identity", SOURCE_IDENTITY,
        ])
    assert result["ok"] is True
    assert result["phase"] == "recover-claude-pre-send"
    assert result["source_terminal_identity"] == SOURCE_IDENTITY
    assert result["exception_key"] == "memory_review"
    assert result["lease_release"] == "released"

    with tempfile.TemporaryDirectory() as temporary:
        try:
            _run_main([
                "recover-claude-pre-send",
                "--display", ":3",
                "--seat-id", SOURCE_IDENTITY,
                "--artifact-root", str(Path(temporary) / "same-identity"),
                "--exception-key", "memory_review",
                "--source-terminal-identity", SOURCE_IDENTITY,
            ])
        except RuntimeError as exc:
            assert str(exc) == "Claude pre-send recovery requires a new seat identity"
        else:
            raise AssertionError("same terminal source identity was not refused")

    print(json.dumps({
        "exception": "memory_review",
        "recovery_element": "claude_memory_not_now",
        "same_identity_refused": True,
        "stable_cycles": 2,
        "status": "PASS",
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
