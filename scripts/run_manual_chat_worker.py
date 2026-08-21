#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.yaml_contract import load_platform_yaml


ENDPOINT = "http://127.0.0.1:8767/v1/chat/completions"
PLATFORM_LABELS = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "gemini": "Gemini",
    "grok": "Grok",
    "perplexity": "Perplexity",
}
IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Invoke one frozen manual-chat-ui worker turn without freeform instructions.",
    )
    phases = parser.add_subparsers(dest="phase", required=True)

    send = phases.add_parser("send", help="Attach two frozen bundles, paste, and send once.")
    _add_common(send)
    send.add_argument("--bundle-a", required=True)
    send.add_argument("--bundle-b", required=True)
    send.add_argument("--prompt-file", required=True)

    recover = phases.add_parser(
        "recover",
        help="Execute one YAML-authorized post-send recovery action.",
    )
    _add_common(recover)
    recover.add_argument("--exception-key", required=True)
    recover.add_argument("--source-response-json", required=True)

    extract = phases.add_parser(
        "extract",
        help="Extract once after the completion monitor reports COMPLETE.",
    )
    _add_common(extract)
    extract.add_argument("--monitor-id", required=True)
    extract.add_argument("--response-file", required=True)
    extract.add_argument("--prepare-only", action="store_true")
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORM_LABELS))
    parser.add_argument("--display", required=True)
    parser.add_argument("--seat-id", required=True)
    parser.add_argument("--artifact-root", required=True)


def _absolute_input(raw: str, name: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{name} must be an absolute path")
    path = path.resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"{name} must be a non-empty regular file: {path}")
    return path


def _artifact_root(raw: str, *, allow_existing: bool) -> Path:
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise RuntimeError("artifact root must be an absolute path")
    if root.exists():
        if allow_existing and root.is_dir():
            return root.resolve(strict=True)
        raise RuntimeError(f"artifact root already exists; refusing retry: {root}")
    parent = root.parent.resolve(strict=True)
    root = parent / root.name
    return root


def _identity(raw: str, name: str) -> str:
    if not IDENTITY_RE.fullmatch(raw):
        raise RuntimeError(f"{name} must match {IDENTITY_RE.pattern}")
    return raw


def _request_text(content: str, max_tokens: int) -> str:
    encoded_content = json.dumps(content, ensure_ascii=False)
    return (
        "{\n"
        '  "model": "taey",\n'
        '  "stream": false,\n'
        f'  "max_tokens": {max_tokens},\n'
        '  "chat_template_kwargs": {"enable_thinking": false},\n'
        '  "messages": [\n'
        '    {\n'
        '      "role": "user",\n'
        f'      "content": {encoded_content}\n'
        '    }\n'
        '  ]\n'
        '}\n'
    )


def _ensure_request(path: Path, text: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"request path contains different bytes: {path}")
        return
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
    path.chmod(0o600)


def _post_send_exceptions(platform: str) -> dict[str, dict[str, object]]:
    cfg = load_platform_yaml(platform)
    workflow = cfg.get("workflow")
    element_map = (cfg.get("tree") or {}).get("element_map")
    if not isinstance(workflow, dict) or not isinstance(element_map, dict):
        raise RuntimeError(f"{platform} YAML has no valid workflow or element_map")
    post_send = workflow.get("post_send") or {}
    if not isinstance(post_send, dict):
        raise RuntimeError(f"{platform} workflow.post_send must be a mapping")
    exceptions = post_send.get("exceptions") or {}
    if not isinstance(exceptions, dict):
        raise RuntimeError(f"{platform} workflow.post_send.exceptions must be a mapping")
    normalized: dict[str, dict[str, object]] = {}
    for exception_key, raw_spec in exceptions.items():
        if not isinstance(exception_key, str) or not IDENTITY_RE.fullmatch(exception_key):
            raise RuntimeError(f"{platform} has an invalid post-send exception key")
        if not isinstance(raw_spec, dict):
            raise RuntimeError(f"{platform} post-send exception {exception_key} must be a mapping")
        detect = raw_spec.get("detect")
        if (
            not isinstance(detect, list)
            or not detect
            or not all(isinstance(value, str) and value in element_map for value in detect)
        ):
            raise RuntimeError(
                f"{platform} post-send exception {exception_key} has invalid detect elements"
            )
        normalized[exception_key] = dict(raw_spec)
    return normalized


def _post_send_confirmation_content(platform: str) -> str:
    exceptions = _post_send_exceptions(platform)
    if exceptions:
        rendered = "; ".join(
            f"{key} requires exactly one each of {', '.join(spec['detect'])}"
            for key, spec in exceptions.items()
        )
    else:
        rendered = "no mapped post-send exception is currently configured for this platform"
    return (
        "POST-SEND CONFIRMATION: inspect the first fresh base observation already required by "
        "the send step. If the mapped Stop control is present exactly once, require monitor "
        "registration. If Stop is absent, do not mutate: call observe scope=base exactly once "
        "more. If Stop is then present exactly once, require monitor registration. If Stop is "
        f"still absent, classify only these exact YAML-owned exception sets: {rendered}. If one "
        "complete set is present, return a POST-SEND EXCEPTION REPORT naming the exception key, "
        "both fresh observation revisions, current URL, and matched elements. If no complete set "
        "is present, return an UNMAPPED POST-SEND STATE report with both revisions and current "
        "mapped elements. Stop the turn after either report. Do not infer completion from the URL, "
        "Copy, Regenerate, Retry, or any response text. Do not click any recovery control in the "
        "send turn.\n"
    )


def _monitor_stop_keys(platform: str) -> tuple[str, ...]:
    workflow = load_platform_yaml(platform).get("workflow") or {}
    monitor = workflow.get("monitor") or {}
    if not isinstance(monitor, dict):
        raise RuntimeError(f"{platform} workflow.monitor must be a mapping")
    raw_keys = monitor.get("stop_keys")
    if raw_keys is None:
        raw_key = monitor.get("stop_key") or "stop_button"
        raw_keys = [raw_key]
    if (
        not isinstance(raw_keys, list)
        or not raw_keys
        or not all(isinstance(value, str) and value for value in raw_keys)
    ):
        raise RuntimeError(f"{platform} workflow.monitor has invalid Stop keys")
    return tuple(raw_keys)


def _recovery_content(
    platform: str,
    display: str,
    exception_key: str,
    source_response_sha256: str,
) -> str:
    exceptions = _post_send_exceptions(platform)
    spec = exceptions.get(exception_key)
    if spec is None:
        raise RuntimeError(f"{platform} has no mapped post-send exception {exception_key}")
    recovery = spec.get("recovery")
    if not isinstance(recovery, dict):
        raise RuntimeError(f"{platform} exception {exception_key} has no recovery mapping")
    action = recovery.get("action")
    element = recovery.get("element")
    max_attempts = recovery.get("max_attempts")
    success_element = recovery.get("success_element")
    url_prefix = recovery.get("url_prefix")
    if action != "click" or max_attempts != 1:
        raise RuntimeError(
            f"{platform} exception {exception_key} recovery must be one exact click"
        )
    if not isinstance(element, str) or element not in spec["detect"]:
        raise RuntimeError(f"{platform} exception {exception_key} has invalid recovery element")
    if success_element not in _monitor_stop_keys(platform):
        raise RuntimeError(f"{platform} exception {exception_key} has invalid success element")
    if not isinstance(url_prefix, str) or not url_prefix.startswith("https://"):
        raise RuntimeError(f"{platform} exception {exception_key} has invalid URL prefix")
    detect = ", ".join(str(value) for value in spec["detect"])
    stop_keys = ", ".join(_monitor_stop_keys(platform))
    return (
        f"Execute one frozen {PLATFORM_LABELS[platform]} post-send recovery transaction on "
        f"{display}. Source evidence SHA-256 is {source_response_sha256}. Use drive_chat only. "
        "Do not read any file, runbook, or YAML. Do not navigate, attach, paste, send, extract, "
        "or operate any control except the one exact recovery control below.\n"
        f"1. observe scope=base; require current_url to begin exactly {url_prefix}. If any mapped "
        f"Stop key ({stop_keys}) is present exactly once, require monitor registration and return "
        "a recovery receipt without clicking. Otherwise require exactly one each of the mapped "
        f"exception elements {detect}.\n"
        "2. observe scope=base exactly once more without mutation. Apply the same Stop check. If "
        "Stop remains absent, require the same complete exception set. Any missing, duplicate, or "
        "different state is an UNMAPPED POST-SEND STATE and ends this turn without mutation.\n"
        f"3. click element={element} exactly once. This is the only recovery mutation authorized. "
        "Observe scope=base exactly once. If Stop is present exactly once, require monitor "
        "registration and return a receipt containing platform/display, URL, exception key, source "
        "evidence SHA-256, clicked element, mapped Stop key, and monitor_id.\n"
        "4. If Stop is absent after the click, do not mutate: observe scope=base exactly once more. "
        "If Stop is now present exactly once, require monitor registration and return the same "
        "receipt. If the mapped exception persists, return a POST-SEND EXCEPTION REPORT. Otherwise "
        "return an UNMAPPED POST-SEND STATE report. Then stop all UI calls. Never click the recovery "
        "control twice.\n"
        "At the first refusal, failed postcondition, missing, renamed, duplicated, ambiguous, or "
        "unsupported element or action, return the first-mismatch stop report and stop."
    )


def _send_content(
    platform: str,
    display: str,
    bundle_a: Path,
    bundle_b: Path,
    prompt_file: Path,
) -> str:
    post_send = _post_send_confirmation_content(platform)
    if platform == "claude":
        return (
            f"Execute one frozen Claude send transaction on {display}. Use drive_chat only. "
            "Do not read any file, runbook, or YAML. Use a ref or snapshot revision only from "
            "the immediately preceding fresh observation. Execute exactly this sequence, with "
            "one fresh observation after every mutation:\n"
            "1. navigate to https://claude.ai/new; observe scope=base; require current_url to "
            "be the Claude fresh URL, a populated Claude tree, exactly one input, exactly one "
            "toggle_menu, and exactly one model_selector whose exact name is Model: Opus 5 Extra. "
            "Require zero remove_attachment controls, no stop_button, and none of these mapped "
            "exception elements: send_blocked_previous_message, send_blocked_previous_message_curly, "
            "network_connection_alert, send_blocked_caution_banner, claude_capacity_alert, "
            "claude_capacity_alert_pro, claude_session_limit_alert, claude_hit_limit_alert, "
            "claude_not_working_alert, or claude_chat_length_limit_alert. Record this post-navigation "
            "fresh URL. If this exact base proof is absent, stop without opening the model or effort "
            "menu.\n"
            f"2. Attach Bundle A from {bundle_a}: key ctrl+u from the current fresh base observation; "
            "observe scope=base; require the same Claude fresh URL, zero remove_attachment controls, "
            "model_selector still named Model: Opus 5 Extra, and no mapped exception; focus_dialog "
            "using that fresh observation "
            "and require focused=true with matched_title equal to one of File Upload, Open File, Open, "
            "Choose File, or Select File; observe; require exactly one active "
            "dialog_root and one enabled chooser_widget; key ctrl+l using the fresh native-dialog "
            "revision; observe; require exactly one focused editable "
            "location_entry; key ctrl+a using the fresh native-dialog revision; observe; "
            "require location_entry still focused; "
            f"type exactly {bundle_a} using the fresh native-dialog revision; observe; "
            f"require location_entry text exactly {bundle_a}; key Return using "
            "the fresh native-dialog revision; observe scope=base; require exactly one mapped "
            "remove_attachment control and at least one fresh snapshot node whose role is push button, "
            "list item, or heading and whose name matches Bundle A by the Claude driver rule: exact "
            "absolute path or basename, first token, comma prefix, or one ellipsis with matching prefix "
            "and suffix. Require zero Bundle B matches, model_selector still named Model: Opus 5 Extra, "
            "and no mapped exception.\n"
            f"3. Attach Bundle B from {bundle_b}: key ctrl+u from the current fresh base observation; "
            "observe scope=base; require exactly one mapped remove_attachment control, model_selector "
            "still named Model: Opus 5 Extra, and no mapped exception; focus_dialog using that fresh observation "
            "and require focused=true with matched_title equal to one of File Upload, Open File, Open, "
            "Choose File, or Select File; observe; require exactly one active "
            "dialog_root and one enabled chooser_widget; key ctrl+l using the fresh native-dialog "
            "revision; observe; require exactly one focused editable "
            "location_entry; key ctrl+a using the fresh native-dialog revision; observe; "
            "require location_entry still focused; "
            f"type exactly {bundle_b} using the fresh native-dialog revision; observe; "
            f"require location_entry text exactly {bundle_b}; key Return using "
            "the fresh native-dialog revision; observe scope=base; require exactly two mapped "
            "remove_attachment controls, at least one filename-bearing snapshot node matching Bundle A, "
            "and at least one filename-bearing snapshot node matching Bundle B under the same Claude "
            "driver rule. Require no third remove_attachment control, model_selector still named "
            "Model: Opus 5 Extra, and no mapped exception.\n"
            "4. click the fresh input ref; observe scope=base; require the same exact two "
            "remove_attachment controls and Bundle A plus Bundle B filename proofs; paste "
            f"text_file={prompt_file} exactly once; observe scope=base; require the same two "
            "attachment-count and filename proofs, exactly one enabled send_button named Send message, "
            "model_selector still named Model: Opus 5 Extra, and no mapped exception. Do not require a "
            "composer character count or type-text fallback.\n"
            "5. click the fresh send_button ref exactly once; observe scope=base exactly once; require "
            "current_url to differ from the recorded post-navigation fresh URL and to contain /chat/; "
            "then follow the post-send confirmation below. On a Stop-proven observation, require no "
            "mapped exception and return a receipt containing platform/display, final URL, "
            "the Model: Opus 5 Extra proof, Bundle A one-count proof, Bundle B two-count proof, the "
            "mapped Stop key, and monitor_id. Then stop all UI calls.\n"
            f"{post_send}"
            "At the first missing, renamed, duplicated, ambiguous, or unsupported element; unsupported "
            "action or scope; refusal; failed postcondition; or unexpected state, return the "
            "first-mismatch stop report and stop. Do not retry, recover, press Escape, "
            "extract, poll, click Continue, or send a second time."
        )
    if platform == "gemini":
        bundle_a_stem = bundle_a.stem
        bundle_b_stem = bundle_b.stem
        return (
            f"Execute one frozen Gemini send transaction on {display}. Use drive_chat only. "
            "Do not read any file, runbook, or YAML. For click or focus, pass only the exact "
            "element key mapped as a singleton by the immediately preceding fresh observation; "
            "do not copy or pass an opaque ref. Execute exactly this sequence, with "
            "one fresh observation after every mutation:\n"
            "1. navigate to https://gemini.google.com/u/1/app?pageId=none; observe scope=base; "
            "require a populated Gemini tree and exactly one each of input, mode_picker, "
            "tools_button, upload_menu, and new_chat. Require send_button, stop_button, and "
            "copy_button absent. Record this post-navigation fresh URL.\n"
            "2. Require mode_picker name exactly Open mode picker, currently Pro Extended. If it "
            "is not exact: click element=mode_picker; observe scope=menu_snapshot; require "
            "mode_extended match_count 1 with name exactly Extended thinking Complex problem "
            "solving; click element=mode_extended; observe scope=base; require mode_picker "
            "name exactly Open mode picker, currently Pro Extended. Do not touch the model menu.\n"
            f"3. Attach Bundle A from {bundle_a}: focus element=upload_menu; observe "
            "scope=base; require upload_menu match_count 1 with state focused; key space; observe "
            "scope=menu_snapshot; require "
            "scope_expected_elements to contain upload_files_item and require upload_files_item "
            "match_count 1 with name exactly Upload files. Documents, data, code files; click "
            "element=upload_files_item; observe; "
            "focus_dialog using the fresh observation and require focused=true with matched_title "
            "equal to one of File Upload, Open File, Open, Choose File, or Select File; observe; key "
            "ctrl+l using the fresh native-dialog revision; observe; require exactly one focused "
            "editable location_entry; key ctrl+a using the fresh native-dialog revision; observe; "
            f"type exactly {bundle_a} using the fresh native-dialog revision; observe; require "
            f"location_entry text exactly {bundle_a}; key Return using the fresh native-dialog "
            "revision; observe scope=base; over fresh unknown nodes whose role is section, count each "
            "node once when its name, description, or text contains a filename stem. Require exactly "
            f"one node containing Bundle A stem {bundle_a_stem} and zero nodes containing Bundle B "
            f"stem {bundle_b_stem}. Require mode_picker still named Open mode picker, currently Pro "
            "Extended.\n"
            f"4. Attach Bundle B from {bundle_b}: focus element=upload_menu; observe "
            "scope=base; require upload_menu match_count 1 with state focused; key space; observe "
            "scope=menu_snapshot; require "
            "scope_expected_elements to contain upload_files_item and require upload_files_item "
            "match_count 1 with name exactly Upload files. Documents, data, code files; click "
            "element=upload_files_item; observe; "
            "focus_dialog using the fresh observation and require focused=true with matched_title "
            "equal to one of File Upload, Open File, Open, Choose File, or Select File; observe; key "
            "ctrl+l using the fresh native-dialog revision; observe; require exactly one focused "
            "editable location_entry; key ctrl+a using the fresh native-dialog revision; observe; "
            f"type exactly {bundle_b} using the fresh native-dialog revision; observe; require "
            f"location_entry text exactly {bundle_b}; key Return using the fresh native-dialog "
            "revision; observe scope=base; over fresh unknown nodes whose role is section, count each "
            "node once when its name, description, or text contains a filename stem. Require exactly "
            f"one node containing Bundle A stem {bundle_a_stem} and exactly one node containing Bundle "
            f"B stem {bundle_b_stem}. Require mode_picker still named Open mode picker, currently Pro "
            "Extended.\n"
            "5. click element=input; observe scope=base; paste "
            f"text_file={prompt_file} exactly once; observe scope=base; require exactly one enabled "
            "send_button named Send message. Require at least one fresh section node whose name, "
            f"description, or text contains Bundle A stem {bundle_a_stem} and at least one containing "
            f"Bundle B stem {bundle_b_stem}; do not require exact post-paste stem counts.\n"
            "6. focus element=send_button; observe scope=base; key space; observe scope=base "
            "exactly once; require current_url on "
            "gemini.google.com matching /app/<id> or /u/<digit>/app/<id> and do not require a URL "
            "change; then follow the post-send confirmation below. On a Stop-proven observation, "
            "return a receipt containing platform/display, final URL, "
            "the Pro Extended proof, the one-then-two stem proof, the mapped Stop key, and monitor_id. "
            "Then stop all UI calls.\n"
            f"{post_send}"
            "At the first missing, renamed, duplicated, ambiguous, or unsupported element; unsupported "
            "action or scope; refusal; failed postcondition; or unexpected state, return the "
            "first-mismatch stop report and stop. Do not retry, recover, press Escape, extract, poll, "
            "click Continue, or send a second time."
        )
    if platform == "grok":
        return (
            f"Execute one frozen Grok send transaction on {display}. Use drive_chat only. "
            "Do not read any file, runbook, or YAML. For click, focus, or operate, pass only "
            "the exact element key mapped as a singleton by the immediately preceding fresh "
            "observation; do not copy or pass an opaque ref. Execute exactly this sequence, "
            "with one fresh observation after every mutation:\n"
            "1. navigate to https://grok.com/; observe scope=base; require current_url exactly "
            "https://grok.com/, a populated Grok tree, and exactly one each of input named Ask "
            "Grok anything, model_selector named Model select, attach_trigger named Attach, and "
            "new_chat named New Chat. Require uploaded_file_chip, remove_attachment, send_button, "
            "stop_button, and copy_button absent. Record this post-navigation fresh URL.\n"
            "2. operate element=model_selector and require performed_primitive="
            "focus_and_key_open; observe scope=app_root_snapshot; require model_heavy match_count "
            "1 with name exactly Heavy Team of Experts · Grok 4.5; click element=model_heavy; "
            "observe scope=base; require exactly one each of input named Ask Grok anything, "
            "model_selector named Model select, and attach_trigger named Attach.\n"
            f"3. Attach Bundle A from {bundle_a}: focus element=attach_trigger; observe scope=base; "
            "require attach_trigger match_count 1 with state focused; key space; observe "
            "scope=menu_snapshot; require upload_files_item match_count 1 with name exactly Upload "
            "a file; click element=upload_files_item; observe; focus_dialog using the fresh "
            "observation and require focused=true with matched_title equal to one of File Upload, "
            "Open File, Open, Choose File, or Select File; observe; key ctrl+l; observe; require "
            "exactly one focused editable location_entry; key ctrl+a; observe; type exactly "
            f"{bundle_a}; observe; require location_entry text exactly {bundle_a}; key Return; observe "
            "scope=base; require uploaded_file_chip match_count 1 with name exactly Open attachment "
            "Remove this attachment and remove_attachment match_count 1 with name exactly Remove "
            "this attachment. Require stop_button absent.\n"
            f"4. Attach Bundle B from {bundle_b}: focus element=attach_trigger; observe scope=base; "
            "require attach_trigger match_count 1 with state focused and uploaded_file_chip plus "
            "remove_attachment match_count 1; key space; observe scope=menu_snapshot; require "
            "upload_files_item match_count 1 with name exactly Upload a file; click "
            "element=upload_files_item; observe; focus_dialog using the fresh observation and "
            "require focused=true with matched_title equal to one of File Upload, Open File, Open, "
            "Choose File, or Select File; observe; key ctrl+l; observe; require exactly one focused "
            "editable location_entry; key ctrl+a; observe; type exactly "
            f"{bundle_b}; observe; require location_entry text exactly {bundle_b}; key Return; observe "
            "scope=base; require uploaded_file_chip match_count 2 with both names exactly Open "
            "attachment Remove this attachment and remove_attachment match_count 2 with both names "
            "exactly Remove this attachment. Require no third attachment chip or remove control.\n"
            "5. click element=input; observe scope=base; require the same exact two attachment chips "
            "and two remove controls; paste "
            f"text_file={prompt_file} exactly once; observe scope=base; require the same two "
            "attachment-count proofs and exactly one enabled send_button named Submit.\n"
            "6. click element=send_button exactly once; observe scope=base exactly once; require "
            "current_url to differ from the recorded fresh URL and match "
            "https://grok.com/c/<non-empty-id>; then follow the post-send confirmation below. On a "
            "Stop-proven observation, return a receipt containing "
            "platform/display, final URL, the exact Heavy click proof, the one-then-two attachment "
            "proof, the mapped Stop key, and monitor_id. Then stop all UI calls.\n"
            f"{post_send}"
            "At the first missing, renamed, duplicated, ambiguous, or unsupported element; "
            "unsupported action or scope; refusal; failed postcondition; or unexpected state, "
            "return the first-mismatch stop report and stop. Do not retry, recover, take any "
            "additional close action, extract, poll, click Regenerate, or send a second time."
        )
    if platform == "perplexity":
        bundle_a_name = bundle_a.name
        bundle_b_name = bundle_b.name
        return (
            f"Execute one frozen Perplexity send transaction on {display}. Use drive_chat only. "
            "Do not read any file, runbook, or YAML. For click, focus, or operate, pass only "
            "the exact element key mapped as a singleton by the immediately preceding fresh "
            "observation; do not copy or pass an opaque ref. Execute exactly this sequence, "
            "with one fresh observation after every mutation:\n"
            "1. navigate to https://www.perplexity.ai/; observe scope=base; require current_url "
            "exactly https://www.perplexity.ai/, a populated Perplexity tree, and exactly one each "
            "of input as an editable entry, attach_trigger named Add files or tools, and "
            "model_selector named Model. Require exactly one of search_mode_trigger named Search "
            "with state pressed or deep_research_toggle named Deep research with state pressed. "
            "Require submit_button, stop_button, copy_button, and download_button absent. Record "
            "this post-navigation fresh URL.\n"
            "2. operate element=model_selector and require performed_primitive=focus_and_key_open; "
            "observe scope=menu_snapshot; require model_best match_count 1 with name exactly Best "
            "Selects the best available model; click element=model_best exactly once, whether or not "
            "its current state is checked; observe scope=base; require exactly one input and "
            "attach_trigger and exactly one of the two pressed mode controls from step 1. Record the "
            "exact model_best click as the Best selection proof.\n"
            "3. If deep_research_toggle is already present exactly once with name Deep research and "
            "state pressed, record that proof and do not mutate the mode. Otherwise require "
            "search_mode_trigger present exactly once with name Search and state pressed; operate "
            "element=search_mode_trigger and require performed_primitive=focus_and_key_open; observe "
            "scope=menu_snapshot; require deep_research match_count 1 with name exactly Deep "
            "research; click element=deep_research exactly once; observe scope=base; require "
            "deep_research_toggle match_count 1 with name exactly Deep research and state pressed.\n"
            f"4. Attach Bundle A from {bundle_a}: focus element=attach_trigger; observe scope=base; "
            "require attach_trigger match_count 1 with state focused; key space; observe "
            "scope=menu_snapshot; require "
            "upload_files_item match_count 1 with name exactly Upload files or images; click "
            "element=upload_files_item; observe; focus_dialog using the fresh observation and "
            "require focused=true with matched_title equal to one of File Upload, Open File, Open, "
            "Choose File, or Select File; observe; require exactly one active dialog_root and one "
            "enabled chooser_widget; key ctrl+l; observe; require exactly one focused editable "
            "location_entry; key ctrl+a; observe; require location_entry still focused; type exactly "
            f"{bundle_a}; observe; require location_entry text exactly {bundle_a}; key Return; "
            "observe scope=base; over fresh nodes whose role is push button, section, link, or "
            f"heading, require at least one filename proof matching Bundle A basename {bundle_a_name} "
            f"and zero matching Bundle B basename {bundle_b_name}. Require deep_research_toggle "
            "still present exactly once with state pressed and stop_button absent.\n"
            f"5. Attach Bundle B from {bundle_b}: focus element=attach_trigger; observe scope=base; "
            "require attach_trigger match_count 1 with state focused; key space; observe "
            "scope=menu_snapshot; require "
            "upload_files_item match_count 1 with name exactly Upload files or images; click "
            "element=upload_files_item; observe; focus_dialog using the fresh observation and "
            "require focused=true with matched_title equal to one of File Upload, Open File, Open, "
            "Choose File, or Select File; observe; require exactly one active dialog_root and one "
            "enabled chooser_widget; key ctrl+l; observe; require exactly one focused editable "
            "location_entry; key ctrl+a; observe; require location_entry still focused; type exactly "
            f"{bundle_b}; observe; require location_entry text exactly {bundle_b}; key Return; "
            "observe scope=base; over fresh nodes whose role is push button, section, link, or "
            f"heading, require at least one filename proof matching Bundle A basename {bundle_a_name} "
            f"and at least one matching Bundle B basename {bundle_b_name}. Require exactly two "
            "distinct attachment basenames, deep_research_toggle still present exactly once with "
            "state pressed, and stop_button absent.\n"
            "6. click element=input; observe scope=base; require the same two distinct attachment "
            "basename proofs and deep_research_toggle pressed; paste "
            f"text_file={prompt_file} exactly once; observe scope=base; require the same attachment "
            "and Deep research proofs and exactly one enabled submit_button named Submit.\n"
            "7. click element=submit_button exactly once; observe scope=base exactly once; require "
            "current_url to differ from the recorded fresh URL and begin "
            "https://www.perplexity.ai/search/; then follow the post-send confirmation below. On a "
            "Stop-proven observation, return a receipt containing platform/display, final URL, the "
            "exact Best click proof, the Deep research pressed proof, both distinct attachment basename "
            "proofs, the mapped Stop key, and monitor_id. Then stop all UI calls.\n"
            f"{post_send}"
            "For attachment filename proofs, apply the YAML rule exactly: inspect name, description, "
            "or text on the allowed roles; accept the exact absolute path or basename, the basename "
            "as the first space-delimited token, or one ellipsis with matching prefix and suffix. "
            "At the first missing, renamed, duplicated, ambiguous, or unsupported element; unsupported "
            "action or scope; refusal; failed postcondition; or unexpected state, return the "
            "first-mismatch stop report and stop. Do not retry, recover, press Escape, extract, poll, "
            "or send a second time."
        )
    if platform != "chatgpt":
        raise RuntimeError(f"{platform} has no qualified frozen action sequence")
    return (
        f"Execute one frozen ChatGPT send transaction on {display}. Use drive_chat only. "
        "Do not read any file, runbook, or YAML. Use a ref only from the immediately preceding "
        "fresh observation. Execute exactly this sequence, with one fresh observation after every "
        "mutation:\n"
        "1. navigate to https://chatgpt.com/; observe scope=base; require a populated ChatGPT tree, "
        "one mapped composer, no auth/capacity exception, no running response, and record the fresh URL.\n"
        "2. Require model_selector name Pro. If it is not Pro: click the fresh model_selector ref; "
        "observe scope=app_root_snapshot; click the fresh model_pro ref; observe scope=base; require "
        "model_selector name Pro.\n"
        f"3. Attach Bundle A from {bundle_a} using the current fresh base observation: operate the "
        "fresh attach_trigger ref and require performed_primitive=focus_and_key_open; observe "
        "scope=app_root_snapshot; "
        "operate the fresh tool_upload ref and require performed_primitive=key:ctrl+u; observe; "
        "focus_dialog and require title File Upload; observe; key ctrl+l; observe; key ctrl+a; "
        f"observe; type exactly {bundle_a}; observe; key Return; observe scope=base; require exactly "
        "one mapped attachment chip and one remove control.\n"
        f"4. Attach Bundle B from {bundle_b}: operate the fresh attach_trigger ref and require "
        "performed_primitive=focus_and_key_open; observe scope=app_root_snapshot; operate the fresh "
        "tool_upload ref and require performed_primitive=key:ctrl+u; observe; focus_dialog and "
        "require title File Upload; observe; key ctrl+l; observe; key ctrl+a; observe; type exactly "
        f"{bundle_b}; observe; key Return; observe scope=base; require exactly two mapped attachment "
        "chips and two remove controls.\n"
        "5. click the fresh input_chat_with_chatgpt ref, or input_ask_anything only if that is the "
        f"single mapped composer; observe scope=base; paste text_file={prompt_file}; observe scope=base; "
        "require exactly two attachment chips and one enabled send_button.\n"
        "6. key Return exactly once; observe scope=base exactly once; require the URL changed from the "
        "fresh URL, then follow the post-send confirmation below. On a Stop-proven observation, return "
        "a receipt containing platform/display, final URL, Pro proof, both "
        "attachment proofs, the mapped Stop key, and monitor_id. Then stop all UI calls.\n"
        f"{post_send}"
        "At the first missing element, refusal, failed postcondition, or unexpected state, return the "
        "first-mismatch stop report and stop. Do not retry, recover, extract, poll, press Escape, or send "
        "a second time."
    )


def _extract_content(
    monitor_id: str,
    platform: str,
    display: str,
    response_file: Path,
) -> str:
    if platform == "claude":
        return (
            f"The completion monitor reported COMPLETE for monitor_id={monitor_id}. Execute one frozen "
            f"Claude extraction transaction on {display} with drive_chat only. Do not read any file, "
            "runbook, or YAML. Use a ref or snapshot revision only from the immediately preceding fresh "
            "observation. Execute exactly this sequence:\n"
            "1. observe scope=base; require current_url to contain /chat/, require continue_button "
            "to be absent, and require none of these mapped exception elements: "
            "send_blocked_previous_message, send_blocked_previous_message_curly, network_connection_alert, "
            "send_blocked_caution_banner, claude_capacity_alert, claude_capacity_alert_pro, "
            "claude_session_limit_alert, claude_hit_limit_alert, claude_not_working_alert, or "
            "claude_chat_length_limit_alert.\n"
            "2. key ctrl+End; observe scope=base; require the same "
            "/chat/ URL condition, continue_button absent, no mapped exception, at least "
            "one mapped copy_button, and exactly one fresh copy_button ref marked by the YAML last_by_y "
            "selection.\n"
            "3. click that YAML-selected last-by-y fresh copy_button ref; observe scope=base; require the "
            "same /chat/ URL condition, continue_button absent, and no mapped exception.\n"
            f"4. read_clipboard with output_file={response_file}. Require that drive_chat created a new "
            "non-empty response file and return its byte count and SHA-256. Then stop all UI calls.\n"
            "At the first missing or ambiguous element, refusal, failed postcondition, or unexpected "
            "state, return the first-mismatch stop report and stop. Do not navigate, attach, paste, send, "
            "retry, recover, poll, click Continue, or make a second Copy attempt."
        )
    if platform == "gemini":
        return (
            f"The completion monitor reported COMPLETE for monitor_id={monitor_id}. Execute one "
            f"frozen Gemini extraction transaction on {display} with drive_chat only. Do not read "
            "any file, runbook, or YAML. Use a ref or snapshot revision only from the immediately "
            "preceding fresh observation. Execute exactly this sequence:\n"
            "1. observe scope=base; require current_url on gemini.google.com matching /app/<id> or "
            "/u/<digit>/app/<id>, and require "
            "deep_think_interim_ack_placeholder absent.\n"
            "2. key ctrl+End; observe scope=base; require the "
            "same URL condition, deep_think_interim_ack_placeholder absent, at least "
            "one mapped copy_button, and exactly one fresh copy_button ref marked by the YAML "
            "last_by_y selection.\n"
            "3. click that YAML-selected last-by-y fresh copy_button ref; observe scope=base; require "
            "the same URL condition and deep_think_interim_ack_placeholder absent.\n"
            f"4. read_clipboard with output_file={response_file}. Require that drive_chat created a "
            "new non-empty response file and return its byte count and SHA-256. Then stop all UI "
            "calls.\n"
            "At the first missing or ambiguous element, refusal, failed postcondition, or unexpected "
            "state, return the first-mismatch stop report and stop. Do not navigate, attach, paste, "
            "send, retry, recover, poll, use share_export or copy_content_item, or make a second Copy "
            "attempt."
        )
    if platform == "grok":
        return (
            f"The completion monitor reported COMPLETE for monitor_id={monitor_id}. Execute one "
            f"frozen Grok extraction transaction on {display} with drive_chat only. Do not read "
            "any file, runbook, or YAML. Use an element or snapshot revision only from the "
            "immediately preceding fresh observation. Execute exactly this sequence:\n"
            "1. observe scope=base; require current_url to match "
            "https://grok.com/c/<non-empty-id>.\n"
            "2. key ctrl+End; observe scope=base; require the same URL condition, at least one "
            "mapped copy_button named Copy response, and exactly one fresh "
            "copy_button target marked by the YAML last_by_y selection.\n"
            "3. click element=copy_button; observe scope=base; require the same URL condition.\n"
            f"4. read_clipboard with output_file={response_file}. Require that drive_chat created "
            "a new non-empty response file and return its byte count and SHA-256. Then stop all UI "
            "calls.\n"
            "At the first missing or ambiguous element, refusal, failed postcondition, or unexpected "
            "state, return the first-mismatch stop report and stop. Do not navigate, attach, paste, "
            "send, retry, recover, poll, click Regenerate, or make a second Copy attempt."
        )
    if platform == "perplexity":
        return (
            f"The completion monitor reported COMPLETE for monitor_id={monitor_id}. Execute one "
            f"frozen Perplexity extraction transaction on {display} with drive_chat only. Do not "
            "read any file, runbook, or YAML. For click, pass only the exact element key mapped as "
            "a singleton by the immediately preceding fresh observation; do not copy or pass an "
            "opaque ref. Execute exactly this sequence:\n"
            "1. observe scope=base; require current_url to begin "
            "https://www.perplexity.ai/search/ and require stop_button absent.\n"
            "2. key ctrl+End; observe scope=base; require the same URL condition, stop_button absent, "
            "at least one mapped download_button named Download, at least one mapped more_actions "
            "named More actions, and exactly one mapped copy_contents_button named Copy contents.\n"
            "3. click element=copy_contents_button; observe scope=base; require the same URL condition and "
            "stop_button absent.\n"
            f"4. read_clipboard with output_file={response_file}. Require that drive_chat created a "
            "new non-empty response file and return its byte count and SHA-256. Then stop all UI "
            "calls.\n"
            "At the first missing or ambiguous element, refusal, failed postcondition, or unexpected "
            "state, return the first-mismatch stop report and stop. Do not navigate, attach, paste, "
            "send, retry, recover, poll, open Download, or make a second Copy attempt."
        )
    if platform != "chatgpt":
        raise RuntimeError(f"{platform} has no qualified frozen extraction sequence")
    return (
        f"The completion monitor reported COMPLETE for monitor_id={monitor_id}. Execute one frozen "
        f"ChatGPT extraction transaction on {display} with drive_chat only. Do not read any file, "
        "runbook, or YAML. Execute exactly: observe scope=base; key ctrl+End; observe scope=base; "
        "click the last-by-y fresh copy_button ref; observe scope=base; read_clipboard with "
        f"output_file={response_file}. Require that drive_chat created a new non-empty response file "
        "and return its byte count and SHA-256. Then stop all UI calls. At the first missing element, "
        "refusal, failed postcondition, or unexpected state, return the first-mismatch stop report and "
        "stop. Do not navigate, attach, paste, send, retry, recover, or poll."
    )


def _identity_headers(headers_path: Path) -> dict[str, str]:
    blocks = headers_path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n\n")
    blocks = [block for block in blocks if block.startswith("HTTP/")]
    if not blocks:
        raise RuntimeError("worker response has no HTTP header block")
    lines = blocks[-1].splitlines()
    parts = lines[0].split()
    if len(parts) < 2 or parts[1] != "200":
        raise RuntimeError(f"worker returned non-200 status: {lines[0]}")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def _worker_receipt(response_path: Path) -> tuple[dict[str, object], str]:
    try:
        payload = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("worker response is not valid JSON") from exc
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or len(choices) != 1:
        raise RuntimeError("worker response must contain exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        raise RuntimeError("worker response did not finish with stop")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("worker response has no receipt text")
    return payload, content


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _invoke(
    *,
    root: Path,
    request_text: str,
    seat_id: str,
    event_id: str,
    correlation_id: str,
) -> tuple[Path, Path, Path, str]:
    request_path = root / "request.json"
    headers_path = root / "response.headers"
    response_path = root / "worker_response.json"
    _ensure_request(request_path, request_text)
    completed = subprocess.run(
        [
            "curl",
            "-sS",
            "--max-time",
            "3600",
            "-D",
            str(headers_path),
            "-o",
            str(response_path),
            "-H",
            "Content-Type: application/json",
            "-H",
            f"X-Taey-Seat-Id: {seat_id}",
            "-H",
            f"X-Taey-Event-Id: {event_id}",
            "-H",
            f"X-Taey-Correlation-Id: {correlation_id}",
            "-H",
            "X-Taey-Tool-Profile: manual-chat-ui",
            "--data-binary",
            f"@{request_path}",
            ENDPOINT,
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"worker transport failed with curl exit {completed.returncode}; refusing retry"
        )
    headers = _identity_headers(headers_path)
    expected_headers = {
        "x-taey-seat-id": seat_id,
        "x-taey-event-id": event_id,
        "x-taey-correlation-id": correlation_id,
        "x-taey-tool-profile": "manual-chat-ui",
    }
    mismatches = {
        key: {"expected": value, "observed": headers.get(key)}
        for key, value in expected_headers.items()
        if headers.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"worker identity header mismatch: {mismatches}")
    _payload, receipt = _worker_receipt(response_path)
    return request_path, headers_path, response_path, receipt


def _is_worker_stop_report(receipt: str) -> bool:
    lowered = receipt.lower()
    for line in receipt.splitlines():
        if not line.strip():
            continue
        headline = line.strip(" \t#*_`").lower()
        normalized_headline = re.sub(r"[^a-z0-9]+", " ", headline).strip()
        if normalized_headline.startswith((
            "stop report",
            "first mismatch stop report",
            "stop first mismatch report",
            "post send exception report",
            "unmapped post send state",
        )):
            return True
    return all(
        field in lowered
        for field in (
            "platform/display:",
            "expected postcondition:",
            "observed postcondition:",
            "classification:",
        )
    )


def _release_extract_lease(display: str, seat_id: str) -> str:
    host = os.environ.get("REDIS_HOST") or os.environ.get("TAEY_REDIS_HOST") or "127.0.0.1"
    port = os.environ.get("REDIS_PORT") or os.environ.get("TAEY_REDIS_PORT") or "6379"
    key = f"taey:plan_active:{display}"
    fetched = subprocess.run(
        ["redis-cli", "-h", host, "-p", port, "--raw", "GET", key],
        check=False,
        capture_output=True,
        text=True,
    )
    if fetched.returncode != 0:
        raise RuntimeError("could not read the extraction display lease")
    raw = fetched.stdout.rstrip("\n")
    if not raw:
        return "absent"
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("extraction display lease is malformed") from exc
    if not isinstance(record, dict) or record.get("seat_id") != seat_id:
        raise RuntimeError("extraction display lease belongs to another seat")
    removed = subprocess.run(
        [
            "redis-cli",
            "-h",
            host,
            "-p",
            port,
            "--raw",
            "EVAL",
            "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end",
            "1",
            key,
            raw,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if removed.returncode != 0:
        raise RuntimeError("could not compare-delete the extraction display lease")
    if removed.stdout.strip() != "1":
        raise RuntimeError("extraction display lease changed before compare-delete")
    return "released"


def main() -> int:
    args = build_parser().parse_args()
    seat_id = _identity(args.seat_id, "seat id")
    artifact_root_preexisted = Path(args.artifact_root).expanduser().exists()
    root = _artifact_root(
        args.artifact_root,
        allow_existing=args.phase == "extract",
    )

    source_response = None
    source_response_sha256 = None
    exception_key = None
    if args.phase == "send":
        bundle_a = _absolute_input(args.bundle_a, "bundle A")
        bundle_b = _absolute_input(args.bundle_b, "bundle B")
        prompt_file = _absolute_input(args.prompt_file, "prompt file")
        content = _send_content(
            args.platform,
            args.display,
            bundle_a,
            bundle_b,
            prompt_file,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0{args.platform}\0{args.display}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"send-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 8192)
    elif args.phase == "recover":
        exception_key = _identity(args.exception_key, "exception key")
        source_response = _absolute_input(args.source_response_json, "source response JSON")
        _source_payload, source_receipt = _worker_receipt(source_response)
        if not _is_worker_stop_report(source_receipt):
            raise RuntimeError("source response is not a terminal worker report")
        source_response_sha256 = _sha256(source_response)
        content = _recovery_content(
            args.platform,
            args.display,
            exception_key,
            source_response_sha256,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0{args.platform}\0{args.display}\0{exception_key}\0"
            f"{source_response_sha256}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"recover-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 4096)
    else:
        monitor_id = _identity(args.monitor_id, "monitor id")
        response_file = Path(args.response_file).expanduser()
        if not response_file.is_absolute():
            raise RuntimeError("response file must be an absolute path")
        response_file = response_file.parent.resolve(strict=False) / response_file.name
        if response_file != root / "response.txt":
            raise RuntimeError("response file must be ARTIFACT_ROOT/response.txt")
        if response_file.exists():
            raise RuntimeError(f"response file already exists; refusing retry: {response_file}")
        content = _extract_content(
            monitor_id,
            args.platform,
            args.display,
            response_file,
        )
        digest = hashlib.sha256(monitor_id.encode("utf-8")).hexdigest()
        event_id = f"extract-{digest[:24]}"
        request_text = _request_text(content, 4096)

    correlation_id = f"{event_id}-1"
    if not root.exists():
        root.mkdir(mode=0o700)
    prepared_marker = root / ".prepared"
    if args.phase == "extract":
        _ensure_request(root / "request.json", request_text)
        if args.prepare_only:
            for output in (root / "response.headers", root / "worker_response.json", response_file):
                if output.exists():
                    raise RuntimeError(f"extraction output already exists: {output}")
            if prepared_marker.exists():
                if prepared_marker.read_text(encoding="utf-8") != event_id + "\n":
                    raise RuntimeError("prepared extraction handoff identity mismatch")
            else:
                if artifact_root_preexisted:
                    raise RuntimeError("prepared extraction handoff was already consumed")
                with prepared_marker.open("x", encoding="utf-8") as handle:
                    handle.write(event_id + "\n")
                prepared_marker.chmod(0o600)
            print(json.dumps({
                "artifact_root": str(root),
                "event_id": event_id,
                "request_json": str(root / "request.json"),
                "response_file": str(response_file),
            }, sort_keys=True))
            return 0
        if not prepared_marker.is_file():
            raise RuntimeError("extraction handoff is not prepared or was already consumed")
        if prepared_marker.read_text(encoding="utf-8") != event_id + "\n":
            raise RuntimeError("extraction handoff identity mismatch")
        for output in (root / "response.headers", root / "worker_response.json", response_file):
            if output.exists():
                raise RuntimeError(f"extraction output already exists; refusing retry: {output}")
        prepared_marker.unlink()
    lease_release = None
    primary_error = None
    mutation_stop_report = False
    try:
        request_path, headers_path, response_path, receipt = _invoke(
            root=root,
            request_text=request_text,
            seat_id=seat_id,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        if (
            source_response is not None
            and _sha256(source_response) != source_response_sha256
        ):
            raise RuntimeError("source response changed during recovery")
        if _is_worker_stop_report(receipt):
            mutation_stop_report = args.phase in {"send", "recover"}
            raise RuntimeError(f"worker returned a terminal {args.phase} report")
        if args.phase in {"send", "recover"} and not re.search(
            r"(?im)\bmonitor_id\b[*`\"' \t|]*(?::|=|`|\|)[*`\"' \t|]*(?!(?:none|null)\b)"
            r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}",
            receipt,
        ):
            raise RuntimeError(f"{args.phase} response has no registered monitor_id")
        if response_file is not None:
            if not response_file.is_file() or response_file.stat().st_size == 0:
                raise RuntimeError("extraction did not create a non-empty response file")
    except RuntimeError as exc:
        primary_error = exc
    finally:
        if args.phase == "extract" or mutation_stop_report:
            try:
                lease_release = _release_extract_lease(args.display, seat_id)
            except RuntimeError as cleanup_error:
                if primary_error is None:
                    primary_error = cleanup_error
                else:
                    primary_error = RuntimeError(
                        f"{primary_error}; extraction lease cleanup failed: {cleanup_error}"
                    )
    if primary_error is not None:
        raise primary_error
    result: dict[str, object] = {
        "ok": True,
        "phase": args.phase,
        "platform": args.platform,
        "display": args.display,
        "seat_id": seat_id,
        "event_id": event_id,
        "correlation_id": correlation_id,
        "request_json": str(request_path),
        "request_sha256": _sha256(request_path),
        "response_headers": str(headers_path),
        "response_json": str(response_path),
        "response_json_sha256": _sha256(response_path),
    }
    if response_file is not None:
        result.update({
            "response_file": str(response_file),
            "response_bytes": response_file.stat().st_size,
            "response_sha256": _sha256(response_file),
            "lease_release": lease_release,
        })
    if source_response is not None:
        result.update({
            "exception_key": exception_key,
            "source_response_json": str(source_response),
            "source_response_json_sha256": source_response_sha256,
        })
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(1)
