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


SOURCE_IDENTITY = "grok-r5-r2-p306-s23-1"
RECOVERY_SEAT = "grok-r5-r2-p306-s23-1-bot-recovery-1"
PRE_COUNTS = {
    "grok_bot_dialog": 1,
    "grok_bot_dismiss": 1,
    "grok_bot_get": 1,
    "uploaded_file_chip": 0,
    "remove_attachment": 0,
    "send_button": 0,
    "stop_button": 0,
}
PRE_STATES = {
    "grok_bot_dialog": ["showing", "focusable", "enabled"],
    "grok_bot_dismiss": ["showing", "focusable", "enabled"],
    "grok_bot_get": ["showing", "focusable", "enabled"],
}
POST_COUNTS = {
    "input": 1,
    "attach_trigger": 1,
    "model_selector": 1,
    "new_chat": 1,
    "grok_bot_dialog": 0,
    "grok_bot_dismiss": 0,
    "grok_bot_get": 0,
    "uploaded_file_chip": 0,
    "remove_attachment": 0,
    "send_button": 0,
    "stop_button": 0,
}
MODEL_SOURCE_IDENTITY = "grok-r5-r2-s23-2"
MODEL_RECOVERY_SEAT = "grok-r5-r2-s23-2-model-menu-recovery-1"
MODEL_PRE_COUNTS = {
    "model_auto": 1,
    "model_fast": 1,
    "model_expert": 1,
    "model_heavy": 1,
    "grok_bot_dialog": 0,
    "grok_bot_dismiss": 0,
    "grok_bot_get": 0,
    "uploaded_file_chip": 0,
    "remove_attachment": 0,
    "send_button": 0,
    "stop_button": 0,
    "copy_button": 0,
}
MODEL_PRE_STATES = {
    key: ["showing", "focusable", "enabled"]
    for key in ("model_auto", "model_fast", "model_expert", "model_heavy")
}
MODEL_POST_COUNTS = {
    "input": 1,
    "attach_trigger": 1,
    "model_selector": 1,
    "new_chat": 1,
    "model_auto": 0,
    "model_fast": 0,
    "model_expert": 0,
    "model_heavy": 0,
    "grok_bot_dialog": 0,
    "grok_bot_dismiss": 0,
    "grok_bot_get": 0,
    "uploaded_file_chip": 0,
    "remove_attachment": 0,
    "send_button": 0,
    "stop_button": 0,
    "copy_button": 0,
}


def _receipt(*, bad_pre_count: bool = False) -> str:
    pre_counts = dict(PRE_COUNTS)
    if bad_pre_count:
        pre_counts["grok_bot_get"] = 0
    compact_pre = json.dumps(pre_counts, separators=(",", ":"))
    compact_post = json.dumps(POST_COUNTS, separators=(",", ":"))
    return "\n".join((
        "GROK PRE-SEND RECOVERY RECEIPT",
        "platform: grok",
        "display: :23",
        f"source_terminal_identity: {SOURCE_IDENTITY}",
        "exception_key: meet_grok_bot",
        "classification_scope: base",
        f"classification_revision_1: {'a' * 64}",
        f"classification_revision_2: {'b' * 64}",
        f"pre_recovery_counts_1: {compact_pre}",
        f"pre_recovery_counts_2: {json.dumps(PRE_COUNTS, separators=(',', ':'))}",
        f"pre_recovery_states_1: {json.dumps(PRE_STATES, separators=(',', ':'))}",
        f"pre_recovery_states_2: {json.dumps(PRE_STATES, separators=(',', ':'))}",
        "clicked_element: grok_bot_dismiss",
        "click_count: 1",
        "performed_primitive: click",
        "postcondition_scope: base",
        "postcondition_elements: input, attach_trigger, model_selector, new_chat",
        "stable_cycles: 2",
        f"post_recovery_revision_1: {'c' * 64}",
        f"post_recovery_revision_2: {'d' * 64}",
        f"post_recovery_counts_1: {compact_post}",
        f"post_recovery_counts_2: {compact_post}",
        "interstitial_absent: true",
        "observe_count: 4",
        "navigation_count: 0",
        "attachment_count: 0",
        "paste_count: 0",
        "send_count: 0",
        "selected_model: false",
        "sent: false",
        "recovered: true",
    ))


def _model_menu_receipt(*, bad_state: bool = False, selected_model: bool = True) -> str:
    pre_states = dict(MODEL_PRE_STATES)
    if bad_state:
        pre_states["model_heavy"] = ["showing", "enabled"]
    compact_pre = json.dumps(MODEL_PRE_COUNTS, separators=(",", ":"))
    compact_states = json.dumps(pre_states, separators=(",", ":"))
    compact_post = json.dumps(MODEL_POST_COUNTS, separators=(",", ":"))
    return "\n".join((
        "GROK PRE-SEND RECOVERY RECEIPT",
        "platform: grok",
        "display: :23",
        f"source_terminal_identity: {MODEL_SOURCE_IDENTITY}",
        "exception_key: model_menu_open",
        "classification_scope: base",
        f"classification_revision_1: {'1' * 64}",
        f"classification_revision_2: {'2' * 64}",
        f"pre_recovery_counts_1: {compact_pre}",
        f"pre_recovery_counts_2: {compact_pre}",
        f"pre_recovery_states_1: {compact_states}",
        f"pre_recovery_states_2: {json.dumps(MODEL_PRE_STATES, separators=(',', ':'))}",
        "clicked_element: model_heavy",
        "click_count: 1",
        "performed_primitive: click",
        "postcondition_scope: base",
        "postcondition_elements: input, attach_trigger, model_selector, new_chat",
        "stable_cycles: 2",
        f"post_recovery_revision_1: {'3' * 64}",
        f"post_recovery_revision_2: {'4' * 64}",
        f"post_recovery_counts_1: {compact_post}",
        f"post_recovery_counts_2: {compact_post}",
        "model_menu_absent: true",
        "observe_count: 4",
        "navigation_count: 0",
        "attachment_count: 0",
        "paste_count: 0",
        "send_count: 0",
        f"selected_model: {str(selected_model).lower()}",
        "sent: false",
        "recovered: true",
    ))


def _fake_invoke(*, root: Path, receipt: str | None = None, **_kwargs):
    request = root / "request.json"
    headers = root / "response.headers"
    response = root / "worker_response.json"
    request.write_text("{}\n", encoding="utf-8")
    headers.write_text("HTTP/1.1 200 OK\n", encoding="utf-8")
    response.write_text("{}\n", encoding="utf-8")
    return request, headers, response, receipt or _receipt()


def _run_main(arguments: list[str], *, receipt: str | None = None) -> dict:
    output = StringIO()

    def invoke(**kwargs):
        return _fake_invoke(receipt=receipt, **kwargs)

    with (
        patch.object(sys, "argv", [str(worker.__file__), *arguments]),
        patch.object(worker, "_invoke", invoke),
        patch.object(worker, "_release_extract_lease", return_value="released"),
        redirect_stdout(output),
    ):
        assert worker.main() == 0
    return json.loads(output.getvalue())


def _arguments(artifact_root: Path, seat_id: str = RECOVERY_SEAT) -> list[str]:
    return [
        "recover-grok-pre-send",
        "--display", ":23",
        "--seat-id", seat_id,
        "--artifact-root", str(artifact_root),
        "--exception-key", "meet_grok_bot",
        "--source-terminal-identity", SOURCE_IDENTITY,
    ]


def _model_arguments(
    artifact_root: Path,
    seat_id: str = MODEL_RECOVERY_SEAT,
) -> list[str]:
    return [
        "recover-grok-pre-send",
        "--display", ":23",
        "--seat-id", seat_id,
        "--artifact-root", str(artifact_root),
        "--exception-key", "model_menu_open",
        "--source-terminal-identity", MODEL_SOURCE_IDENTITY,
    ]


def main() -> int:
    cfg = load_platform_yaml("grok")
    element_map = cfg["tree"]["element_map"]
    assert element_map["grok_bot_dialog"] == {
        "name": "Meet Grok Bot",
        "role": "dialog",
        "scope": "pre_send.exception",
    }
    assert element_map["grok_bot_dismiss"] == {
        "name": "Dismiss",
        "role": "push button",
        "scope": "pre_send.exception",
    }
    assert element_map["grok_bot_get"] == {
        "name": "Get Grok Bot",
        "role": "push button",
        "scope": "pre_send.exception",
    }
    spec = worker._grok_pre_send_recovery_spec("meet_grok_bot")
    assert spec["exact_url"] == "https://grok.com/"
    assert spec["detect"] == (
        "grok_bot_dialog",
        "grok_bot_dismiss",
        "grok_bot_get",
    )
    assert spec["element"] == "grok_bot_dismiss"
    assert spec["exact_singletons"] == (
        "input",
        "attach_trigger",
        "model_selector",
        "new_chat",
    )
    assert spec["stable_cycles"] == 2
    assert spec["max_samples"] == 48
    content = worker._grok_pre_send_recovery_content(
        ":23",
        "meet_grok_bot",
        SOURCE_IDENTITY,
    )
    assert content.count("click element=grok_bot_dismiss exactly once") == 1
    assert "Do not navigate, attach, paste, send" in content
    assert "current_url exactly https://grok.com/" in content
    assert "Require 2 consecutive matching samples" in content
    assert SOURCE_IDENTITY in content

    model_spec = worker._grok_pre_send_recovery_spec("model_menu_open")
    assert model_spec["detect_scope"] == "base"
    assert model_spec["detect"] == (
        "model_auto",
        "model_fast",
        "model_expert",
        "model_heavy",
    )
    assert model_spec["blocked_state_absent"] == (
        "grok_bot_dialog",
        "grok_bot_dismiss",
        "grok_bot_get",
        "uploaded_file_chip",
        "remove_attachment",
        "send_button",
        "stop_button",
        "copy_button",
    )
    assert model_spec["element"] == "model_heavy"
    assert model_spec["selected_model"] is True
    assert model_spec["absence_receipt_field"] == "model_menu_absent"
    assert model_spec["exact_singletons"] == (
        "input",
        "attach_trigger",
        "model_selector",
        "new_chat",
    )
    model_content = worker._grok_pre_send_recovery_content(
        ":23",
        "model_menu_open",
        MODEL_SOURCE_IDENTITY,
    )
    assert model_content.count("click element=model_heavy exactly once") == 1
    assert "observe scope=base exactly once" in model_content
    assert "select any model except model_heavy" in model_content
    assert "Do not navigate, attach, paste, send" in model_content
    assert "navigation_count=0" in model_content
    assert "attachment_count=0" in model_content
    assert "paste_count=0" in model_content
    assert "send_count=0" in model_content
    assert "selected_model=true" in model_content
    assert MODEL_SOURCE_IDENTITY in model_content

    parser = worker.build_parser()
    parsed = parser.parse_args(_arguments(Path("/private/new-artifact-root")))
    assert parsed.platform == "grok"
    assert parsed.phase == "recover-grok-pre-send"

    with tempfile.TemporaryDirectory() as temporary:
        result = _run_main(_arguments(Path(temporary) / "recovery"))
    assert result["ok"] is True
    assert result["phase"] == "recover-grok-pre-send"
    assert result["source_terminal_identity"] == SOURCE_IDENTITY
    assert result["exception_key"] == "meet_grok_bot"
    assert result["lease_release"] == "released"

    with tempfile.TemporaryDirectory() as temporary:
        try:
            _run_main(_arguments(Path(temporary) / "same-identity", SOURCE_IDENTITY))
        except RuntimeError as exc:
            assert str(exc) == "Grok pre-send recovery requires a new seat identity"
        else:
            raise AssertionError("same terminal source identity was not refused")

    with tempfile.TemporaryDirectory() as temporary:
        try:
            _run_main(
                _arguments(Path(temporary) / "bad-count"),
                receipt=_receipt(bad_pre_count=True),
            )
        except RuntimeError as exc:
            assert str(exc) == (
                "Grok pre-send recovery response has invalid pre_recovery_counts_1"
            )
        else:
            raise AssertionError("invalid exact count receipt was not refused")

    with tempfile.TemporaryDirectory() as temporary:
        result = _run_main(
            _model_arguments(Path(temporary) / "model-menu-recovery"),
            receipt=_model_menu_receipt(),
        )
    assert result["ok"] is True
    assert result["phase"] == "recover-grok-pre-send"
    assert result["source_terminal_identity"] == MODEL_SOURCE_IDENTITY
    assert result["exception_key"] == "model_menu_open"
    assert result["lease_release"] == "released"

    with tempfile.TemporaryDirectory() as temporary:
        try:
            _run_main(
                _model_arguments(
                    Path(temporary) / "same-model-identity",
                    MODEL_SOURCE_IDENTITY,
                ),
                receipt=_model_menu_receipt(),
            )
        except RuntimeError as exc:
            assert str(exc) == "Grok pre-send recovery requires a new seat identity"
        else:
            raise AssertionError("same model-menu source identity was not refused")

    with tempfile.TemporaryDirectory() as temporary:
        try:
            _run_main(
                _model_arguments(Path(temporary) / "bad-model-state"),
                receipt=_model_menu_receipt(bad_state=True),
            )
        except RuntimeError as exc:
            assert str(exc) == (
                "Grok pre-send recovery response has invalid pre_recovery_states_1"
            )
        else:
            raise AssertionError("invalid exact model state receipt was not refused")

    with tempfile.TemporaryDirectory() as temporary:
        try:
            _run_main(
                _model_arguments(Path(temporary) / "bad-selected-model"),
                receipt=_model_menu_receipt(selected_model=False),
            )
        except RuntimeError as exc:
            assert "selected_model" in str(exc)
        else:
            raise AssertionError("false model-selection receipt was not refused")

    print(json.dumps({
        "exception": "meet_grok_bot",
        "recovery_element": "grok_bot_dismiss",
        "same_identity_refused": True,
        "invalid_count_refused": True,
        "model_menu_open": "model_heavy",
        "model_state_mismatch_refused": True,
        "selected_model_mismatch_refused": True,
        "stable_cycles": 2,
        "status": "PASS",
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
