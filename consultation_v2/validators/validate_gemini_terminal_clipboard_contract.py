#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_manual_chat_worker import (  # noqa: E402
    _gemini_terminal_clipboard_only_content,
    _validate_gemini_terminal_clipboard_only_capture,
    _validate_gemini_terminal_clipboard_only_receipt,
    _validate_gemini_terminal_clipboard_source,
    build_parser,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    display = ":4"
    source_seat = "source-gemini-terminal-seat"
    source_turn = "0123456789abcdef0123456789abcdef"
    source_event = "send-source-gemini-terminal"
    new_seat = "fresh-gemini-clipboard-seat"
    terminal_sha_argument = "0" * 64
    copy_sha_argument = "1" * 64
    args = build_parser().parse_args([
        "extract-gemini-terminal-clipboard",
        "--display", display,
        "--seat-id", new_seat,
        "--artifact-root", "/tmp/gemini-terminal-clipboard-artifacts",
        "--source-terminal-receipt", "/tmp/source-terminal.md",
        "--source-terminal-receipt-sha256", terminal_sha_argument,
        "--source-copy-result-json", "/tmp/source-copy-result.json",
        "--source-copy-result-json-sha256", copy_sha_argument,
        "--response-file", "/tmp/gemini-terminal-clipboard-artifacts/response.txt",
    ])
    _require(args.platform == "gemini", "clipboard-only phase lost Gemini binding")
    _require(
        args.source_terminal_receipt_sha256 == terminal_sha_argument
        and args.source_copy_result_json_sha256 == copy_sha_argument,
        "clipboard-only phase lost source hashes",
    )

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        call_dir = (
            root / "drive_chat_captures" / "taey-worker" / source_seat
            / source_event / source_turn / "0051-source-copy"
        )
        call_dir.mkdir(parents=True)
        source_request = call_dir / "request.json"
        _write_json(source_request, {
            "arguments": {
                "action": "click",
                "display": display,
                "element": "copy_button",
            },
            "event_id": source_event,
            "proxy_namespace": "taey-worker",
            "schema": "taey.drive_chat.exchange.v1",
            "seat_id": source_seat,
            "tool_round": 51,
            "turn_id": source_turn,
        })
        source_inner = {
            "ok": True,
            "platform": "gemini",
            "action": "click",
            "display": display,
            "result": {
                "performed": True,
                "performed_primitive": "click",
                "element": {
                    "element": "copy_button",
                    "name": "Copy",
                    "role": "push button",
                },
            },
            "error": None,
            "ui_sequence": {"state": "mutation_complete"},
        }
        source_result = call_dir / "result.json"
        _write_json(source_result, {
            "event_id": source_event,
            "proxy_namespace": "taey-worker",
            "result": json.dumps(source_inner, sort_keys=True),
            "returned": True,
            "schema": "taey.drive_chat.exchange.v1",
            "seat_id": source_seat,
            "tool_ok": True,
            "tool_round": 51,
            "turn_id": source_turn,
        })
        copy_sha = _sha256(source_result)
        terminal_receipt = root / "TERMINAL-FIRST-MISMATCH.md"
        terminal_receipt.write_text(
            "\n".join([
                "# Gemini terminal",
                f"- seat_id: `{source_seat}`",
                f"- turn_id: `{source_turn}`",
                f"- event_id: `{source_event}`",
                f"- display: `{display}`",
                "- terminal_result: `supervisor first-error halt`",
                "- captured_drive_chat_calls: `51`",
                f"- round_51_request_sha256: `{_sha256(source_request)}`",
                f"- round_51_result_sha256: `{copy_sha}`",
                "- second_unauthorized_call: round `51`, `click copy_button`, performed `true`",
                "- start_research_call_count: `0`",
                "- read_clipboard_call_count: `0`",
                "- further_calls_after_round_51: `0`",
                "This identity is spent and must never be retried or recovered.",
                "",
            ]),
            encoding="utf-8",
        )
        terminal_sha = _sha256(terminal_receipt)
        source = _validate_gemini_terminal_clipboard_source(
            terminal_receipt,
            terminal_sha,
            source_result,
            copy_sha,
            display,
            new_seat,
        )
        _require(
            source["clipboard_source_certainty"] == "captured_proven"
            and source["provider_output_proven"] is True,
            "clean global capture history did not prove the clipboard source",
        )
        response_file = root / "artifacts" / "response.txt"
        response_file.parent.mkdir()
        response_file.write_text("preserved Gemini response\n", encoding="utf-8")
        content = _gemini_terminal_clipboard_only_content(
            display,
            response_file,
            source,
        )
        _require(
            content.count("action=read_clipboard") == 1,
            "clipboard-only card does not authorize exactly one read",
        )
        _require(
            "must not touch the UI" in content
            and "Do not retry" in content
            and "ui_mutation_count=0" in content,
            "clipboard-only card lost its no-mutation boundary",
        )

        fresh_event = "extract-gemini-terminal-clipboard-fixture"
        fresh_turn = "fedcba9876543210fedcba9876543210"
        fresh_call = (
            root / "drive_chat_captures" / "taey-worker" / new_seat
            / fresh_event / fresh_turn / "0001-clipboard-read"
        )
        fresh_call.mkdir(parents=True)
        _write_json(fresh_call / "request.json", {
            "arguments": {
                "action": "read_clipboard",
                "display": display,
                "output_file": str(response_file),
            },
            "event_id": fresh_event,
            "seat_id": new_seat,
            "tool_round": 1,
        })
        fresh_inner = {
            "ok": True,
            "platform": "gemini",
            "action": "read_clipboard",
            "display": display,
            "result": {
                "output_file": str(response_file),
                "bytes": response_file.stat().st_size,
                "sha256": _sha256(response_file),
            },
        }
        _write_json(fresh_call / "result.json", {
            "result": json.dumps(fresh_inner, sort_keys=True),
            "seat_id": new_seat,
            "event_id": fresh_event,
            "tool_round": 1,
            "tool_ok": True,
        })
        _validate_gemini_terminal_clipboard_only_capture(
            new_seat,
            fresh_event,
            display,
            response_file,
            source,
        )
        receipt = (
            "Gemini terminal clipboard-only receipt\n"
            "platform=gemini\n"
            f"display={display}\n"
            f"source_terminal_receipt_sha256={terminal_sha}\n"
            f"source_copy_result_json_sha256={copy_sha}\n"
            f"source_seat_id={source_seat}\n"
            "source_copy_tool_round=51\n"
            "clipboard_source_certainty=captured_proven\n"
            "provider_output_proven=true\n"
            "clipboard_read_count=1\n"
            "observe_count=0\n"
            "scroll_count=0\n"
            "click_count=0\n"
            "key_count=0\n"
            "navigation_count=0\n"
            "ui_mutation_count=0\n"
            "other_tool_call_count=0\n"
            f"output_file={response_file}\n"
            f"byte_count={response_file.stat().st_size}\n"
            f"response_sha256={_sha256(response_file)}\n"
        )
        _validate_gemini_terminal_clipboard_only_receipt(
            receipt,
            display,
            response_file,
            source,
        )

        later_call = call_dir.parent / "0052-later-clipboard"
        later_call.mkdir()
        _write_json(later_call / "request.json", {
            "arguments": {
                "action": "click",
                "display": display,
                "element": "copy_button",
            },
            "seat_id": source_seat,
            "turn_id": source_turn,
            "event_id": source_event,
            "tool_round": 52,
        })
        uncertain_source = _validate_gemini_terminal_clipboard_source(
            terminal_receipt,
            terminal_sha,
            source_result,
            copy_sha,
            display,
            new_seat,
        )
        _require(
            uncertain_source["clipboard_source_certainty"] == "uncertain"
            and uncertain_source["provider_output_proven"] is False
            and str(later_call / "request.json")
            in uncertain_source["later_clipboard_affecting_records"],
            "later global Copy event did not downgrade provider provenance",
        )

    print("gemini terminal clipboard-only contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
