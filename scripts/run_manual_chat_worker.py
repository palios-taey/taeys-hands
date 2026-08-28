#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.yaml_contract import get_extraction, load_platform_yaml  # noqa: E402
from consultation_v2.platforms.claude.downloaded_artifact import (  # noqa: E402
    CLAUDE_ARTIFACT_CONTROL_KEYS,  # noqa: F401 - compatibility export for validator
    ClaudeArtifactDownloadError,
    ClaudeDownloadSnapshot,
    classify_claude_extraction_snapshot,
    materialize_claude_download,
    resolve_claude_download_scope,
    snapshot_claude_downloads,
    write_download_receipt,
)


ENDPOINT = "http://127.0.0.1:8767/v1/chat/completions"
PLATFORM_LABELS = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "gemini": "Gemini",
    "grok": "Grok",
    "perplexity": "Perplexity",
}
IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
CHATGPT_POWER_INSTANT_DESCRIPTION = (
    "Instant, 1 of 5. Use Left and Right arrow keys to adjust power."
)
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

    recover_claude_pre_send = phases.add_parser(
        "recover-claude-pre-send",
        help="Classify and dismiss one exact Claude pre-send interstitial.",
    )
    recover_claude_pre_send.set_defaults(platform="claude")
    recover_claude_pre_send.add_argument("--display", required=True)
    recover_claude_pre_send.add_argument("--seat-id", required=True)
    recover_claude_pre_send.add_argument("--artifact-root", required=True)
    recover_claude_pre_send.add_argument("--exception-key", required=True)
    recover_claude_pre_send.add_argument("--source-terminal-identity", required=True)

    recover_grok_pre_send = phases.add_parser(
        "recover-grok-pre-send",
        help="Classify and dismiss one exact Grok pre-send interstitial.",
    )
    recover_grok_pre_send.set_defaults(platform="grok")
    recover_grok_pre_send.add_argument("--display", required=True)
    recover_grok_pre_send.add_argument("--seat-id", required=True)
    recover_grok_pre_send.add_argument("--artifact-root", required=True)
    recover_grok_pre_send.add_argument("--exception-key", required=True)
    recover_grok_pre_send.add_argument("--source-terminal-identity", required=True)

    diagnose_chatgpt_model_menu = phases.add_parser(
        "diagnose-chatgpt-model-menu",
        help="Map one ChatGPT advanced-model submenu without selecting or sending.",
    )
    diagnose_chatgpt_model_menu.set_defaults(platform="chatgpt")
    diagnose_chatgpt_model_menu.add_argument("--display", required=True)
    diagnose_chatgpt_model_menu.add_argument("--seat-id", required=True)
    diagnose_chatgpt_model_menu.add_argument("--artifact-root", required=True)

    diagnose_chatgpt_power_right = phases.add_parser(
        "diagnose-chatgpt-power-right",
        help="Press Right once on an already-focused ChatGPT Power row and map the result.",
    )
    diagnose_chatgpt_power_right.set_defaults(platform="chatgpt")
    diagnose_chatgpt_power_right.add_argument("--display", required=True)
    diagnose_chatgpt_power_right.add_argument("--seat-id", required=True)
    diagnose_chatgpt_power_right.add_argument("--artifact-root", required=True)
    diagnose_chatgpt_power_right.add_argument("--pre-selector-name", required=True)
    diagnose_chatgpt_power_right.add_argument("--pre-description", required=True)

    reset_chatgpt_model_menu_compact = phases.add_parser(
        "reset-chatgpt-model-menu-compact",
        help="Reset one already-open ChatGPT advanced model menu to compact state.",
    )
    reset_chatgpt_model_menu_compact.set_defaults(platform="chatgpt")
    reset_chatgpt_model_menu_compact.add_argument("--display", required=True)
    reset_chatgpt_model_menu_compact.add_argument("--seat-id", required=True)
    reset_chatgpt_model_menu_compact.add_argument("--artifact-root", required=True)

    diagnose_perplexity_artifacts = phases.add_parser(
        "diagnose-perplexity-artifacts",
        help="Open one completed Perplexity Artifacts pane and map its contents.",
    )
    diagnose_perplexity_artifacts.set_defaults(platform="perplexity")
    diagnose_perplexity_artifacts.add_argument("--display", required=True)
    diagnose_perplexity_artifacts.add_argument("--seat-id", required=True)
    diagnose_perplexity_artifacts.add_argument("--artifact-root", required=True)
    diagnose_perplexity_artifacts.add_argument(
        "--source-terminal-identity",
        required=True,
    )
    diagnose_perplexity_artifacts.add_argument("--thread-url", required=True)

    diagnose_perplexity_report_card = phases.add_parser(
        "diagnose-perplexity-report-card",
        help="Click one mapped Perplexity report entry and map its resulting surface.",
    )
    diagnose_perplexity_report_card.set_defaults(platform="perplexity")
    diagnose_perplexity_report_card.add_argument("--display", required=True)
    diagnose_perplexity_report_card.add_argument("--seat-id", required=True)
    diagnose_perplexity_report_card.add_argument("--artifact-root", required=True)
    diagnose_perplexity_report_card.add_argument(
        "--source-diagnostic-identity",
        required=True,
    )
    diagnose_perplexity_report_card.add_argument("--thread-url", required=True)

    extract_perplexity_report_card = phases.add_parser(
        "extract-perplexity-report-card",
        help="Open one mapped Perplexity report card, copy it, and materialize it once.",
    )
    extract_perplexity_report_card.set_defaults(platform="perplexity")
    extract_perplexity_report_card.add_argument("--display", required=True)
    extract_perplexity_report_card.add_argument("--seat-id", required=True)
    extract_perplexity_report_card.add_argument("--artifact-root", required=True)
    extract_perplexity_report_card.add_argument(
        "--source-diagnostic-identity",
        required=True,
    )
    extract_perplexity_report_card.add_argument("--thread-url", required=True)
    extract_perplexity_report_card.add_argument("--response-file", required=True)

    extract_perplexity_report_preview = phases.add_parser(
        "extract-perplexity-report-preview",
        help="Extract once from one terminal Perplexity report-preview surface.",
    )
    extract_perplexity_report_preview.set_defaults(platform="perplexity")
    extract_perplexity_report_preview.add_argument("--display", required=True)
    extract_perplexity_report_preview.add_argument("--seat-id", required=True)
    extract_perplexity_report_preview.add_argument("--artifact-root", required=True)
    extract_perplexity_report_preview.add_argument(
        "--source-terminal-response-json", required=True
    )
    extract_perplexity_report_preview.add_argument("--thread-url", required=True)
    extract_perplexity_report_preview.add_argument("--response-file", required=True)

    extract_perplexity_report_open_menu = phases.add_parser(
        "extract-perplexity-report-open-menu",
        help="Continue once from one terminal Perplexity report-preview options menu.",
    )
    extract_perplexity_report_open_menu.set_defaults(platform="perplexity")
    extract_perplexity_report_open_menu.add_argument("--display", required=True)
    extract_perplexity_report_open_menu.add_argument("--seat-id", required=True)
    extract_perplexity_report_open_menu.add_argument("--artifact-root", required=True)
    extract_perplexity_report_open_menu.add_argument(
        "--source-terminal-response-json", required=True
    )
    extract_perplexity_report_open_menu.add_argument("--thread-url", required=True)
    extract_perplexity_report_open_menu.add_argument("--response-file", required=True)

    extract_gemini_terminal_clipboard = phases.add_parser(
        "extract-gemini-terminal-clipboard",
        help="Materialize one already-copied terminal Gemini response without UI mutation.",
    )
    extract_gemini_terminal_clipboard.set_defaults(platform="gemini")
    extract_gemini_terminal_clipboard.add_argument("--display", required=True)
    extract_gemini_terminal_clipboard.add_argument("--seat-id", required=True)
    extract_gemini_terminal_clipboard.add_argument("--artifact-root", required=True)
    extract_gemini_terminal_clipboard.add_argument(
        "--source-terminal-receipt", required=True
    )
    extract_gemini_terminal_clipboard.add_argument(
        "--source-terminal-receipt-sha256", required=True
    )
    extract_gemini_terminal_clipboard.add_argument(
        "--source-copy-result-json", required=True
    )
    extract_gemini_terminal_clipboard.add_argument(
        "--source-copy-result-json-sha256", required=True
    )
    extract_gemini_terminal_clipboard.add_argument("--response-file", required=True)

    extract = phases.add_parser(
        "extract",
        help="Extract once from one explicitly authorized completion basis.",
    )
    _add_common(extract)
    extraction_basis = extract.add_mutually_exclusive_group(required=True)
    extraction_basis.add_argument("--monitor-id")
    extraction_basis.add_argument("--completed-before-stop-source-response-json")
    extract.add_argument("--response-file", required=True)
    extract.add_argument(
        "--output-type",
        choices=("assistant_text", "research_report"),
        default="assistant_text",
    )
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


def _create_request(path: Path, text: str) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise RuntimeError(
            f"request path already exists; refusing retry: {path}"
        ) from exc
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


def _claude_active_model_names() -> tuple[str, ...]:
    workflow = load_platform_yaml("claude").get("workflow") or {}
    selection = workflow.get("selection") or {}
    menus = selection.get("menus") or {}
    if not isinstance(menus, dict):
        raise RuntimeError("claude workflow.selection.menus must be a mapping")
    option_paths = (("model", "opus"), ("mode", "extended_thinking"))
    accepted: tuple[str, ...] | None = None
    for menu_name, option_name in option_paths:
        menu = menus.get(menu_name) or {}
        options = menu.get("options") or {}
        option = options.get(option_name) or {}
        names = option.get("active_trigger_names")
        if (
            not isinstance(names, list)
            or not names
            or not all(
                isinstance(name, str) and name and name == name.strip()
                for name in names
            )
            or len(names) != len(set(names))
        ):
            raise RuntimeError(
                "claude workflow.selection.menus."
                f"{menu_name}.options.{option_name}.active_trigger_names must "
                "be unique exact strings"
            )
        current = tuple(names)
        if accepted is None:
            accepted = current
        elif set(current) != set(accepted):
            raise RuntimeError(
                "claude opus and extended-thinking active trigger names must agree"
            )
    if accepted is None:
        raise RuntimeError("claude active model names were not resolved")
    return accepted


def _claude_pre_send_recovery_spec(exception_key: str) -> dict[str, object]:
    cfg = load_platform_yaml("claude")
    workflow = cfg.get("workflow")
    element_map = (cfg.get("tree") or {}).get("element_map")
    if not isinstance(workflow, dict) or not isinstance(element_map, dict):
        raise RuntimeError("claude YAML has no valid workflow or element_map")
    navigation = workflow.get("navigation")
    pre_send = workflow.get("pre_send")
    monitor = workflow.get("monitor")
    if (
        not isinstance(navigation, dict)
        or not isinstance(pre_send, dict)
        or not isinstance(monitor, dict)
    ):
        raise RuntimeError("claude YAML has no navigation or pre-send contract")
    exceptions = pre_send.get("exceptions")
    if not isinstance(exceptions, dict):
        raise RuntimeError("claude workflow.pre_send.exceptions must be a mapping")
    raw_spec = exceptions.get(exception_key)
    if not isinstance(raw_spec, dict):
        raise RuntimeError(f"claude has no mapped pre-send exception {exception_key}")

    detect = raw_spec.get("detect")
    detect_states = raw_spec.get("detect_states")
    navigation_controls_absent = raw_spec.get("navigation_controls_absent")
    recovery = raw_spec.get("recovery")
    postcondition = navigation.get("postcondition")
    observation = navigation.get("observation")
    if (
        not isinstance(detect, list)
        or len(detect) != 2
        or len(detect) != len(set(detect))
        or not all(isinstance(key, str) and key in element_map for key in detect)
    ):
        raise RuntimeError("claude pre-send exception detect elements are invalid")
    if not isinstance(detect_states, dict) or set(detect_states) != set(detect):
        raise RuntimeError("claude pre-send exception detect states are invalid")
    for key, states in detect_states.items():
        if (
            not isinstance(states, list)
            or not states
            or len(states) != len(set(states))
            or not all(isinstance(state, str) and state for state in states)
        ):
            raise RuntimeError(f"claude pre-send exception states are invalid for {key}")
    if not isinstance(postcondition, dict) or postcondition.get("scope") != "base":
        raise RuntimeError("claude navigation postcondition must use base scope")
    exact_singletons = postcondition.get("exact_singletons")
    if (
        not isinstance(exact_singletons, list)
        or not exact_singletons
        or len(exact_singletons) != len(set(exact_singletons))
        or not all(
            isinstance(key, str) and key in element_map
            for key in exact_singletons
        )
    ):
        raise RuntimeError("claude navigation exact singleton controls are invalid")
    if navigation_controls_absent != exact_singletons:
        raise RuntimeError(
            "claude pre-send blocked state must exclude the navigation singleton controls"
        )
    if not isinstance(observation, dict):
        raise RuntimeError("claude navigation observation contract is missing")
    refresh_policy = observation.get("refresh_policy")
    stable_cycles = observation.get("stable_cycles")
    interval_ms = observation.get("interval_ms")
    timeout_ms = observation.get("timeout_ms")
    if (
        refresh_policy != "invalidate_reacquire"
        or stable_cycles != 2
        or isinstance(interval_ms, bool)
        or not isinstance(interval_ms, int)
        or interval_ms <= 0
        or isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or timeout_ms < interval_ms * stable_cycles
    ):
        raise RuntimeError("claude navigation observation barrier is invalid")
    max_samples = (timeout_ms + interval_ms - 1) // interval_ms
    if not 2 <= max_samples <= 100:
        raise RuntimeError("claude navigation observation sample bound is invalid")

    if not isinstance(recovery, dict):
        raise RuntimeError("claude pre-send exception has no recovery mapping")
    action = recovery.get("action")
    element = recovery.get("element")
    max_attempts = recovery.get("max_attempts")
    url_prefix = recovery.get("url_prefix")
    absent_after_recovery = recovery.get("absent_after_recovery")
    if action != "click" or max_attempts != 1 or element not in detect:
        raise RuntimeError("claude pre-send recovery must be one exact mapped click")
    if url_prefix != "https://claude.ai/new":
        raise RuntimeError("claude pre-send recovery URL prefix is invalid")
    if absent_after_recovery != detect:
        raise RuntimeError("claude pre-send recovery must remove the complete exception set")
    if recovery.get("success_postcondition") != "navigation":
        raise RuntimeError("claude pre-send recovery must reuse the navigation postcondition")
    stop_keys = monitor.get("stop_keys")
    exception_states = monitor.get("exception_states")
    if (
        not isinstance(stop_keys, list)
        or not stop_keys
        or not isinstance(exception_states, list)
    ):
        raise RuntimeError("claude monitor exception contract is invalid")
    forbidden_after_recovery: list[str] = []
    for key in stop_keys:
        if not isinstance(key, str) or key not in element_map:
            raise RuntimeError("claude monitor Stop key is invalid")
        forbidden_after_recovery.append(key)
    for state in exception_states:
        detect_keys = state.get("detect") if isinstance(state, dict) else None
        if not isinstance(detect_keys, list):
            raise RuntimeError("claude monitor exception state is invalid")
        for key in detect_keys:
            if not isinstance(key, str) or key not in element_map:
                raise RuntimeError("claude monitor exception element is invalid")
            if key not in forbidden_after_recovery:
                forbidden_after_recovery.append(key)
    return {
        "detect": tuple(detect),
        "detect_states": {
            key: tuple(states) for key, states in detect_states.items()
        },
        "navigation_controls": tuple(exact_singletons),
        "element": element,
        "url_prefix": url_prefix,
        "absent_after_recovery": tuple(absent_after_recovery),
        "stable_cycles": stable_cycles,
        "max_samples": max_samples,
        "forbidden_after_recovery": tuple(forbidden_after_recovery),
    }


def _grok_pre_send_recovery_spec(exception_key: str) -> dict[str, object]:
    cfg = load_platform_yaml("grok")
    workflow = cfg.get("workflow")
    element_map = (cfg.get("tree") or {}).get("element_map")
    urls = cfg.get("urls")
    if (
        not isinstance(workflow, dict)
        or not isinstance(element_map, dict)
        or not isinstance(urls, dict)
    ):
        raise RuntimeError("grok YAML has no valid workflow, element_map, or urls")
    pre_send = workflow.get("pre_send")
    if not isinstance(pre_send, dict):
        raise RuntimeError("grok YAML has no pre-send contract")
    exceptions = pre_send.get("exceptions")
    if not isinstance(exceptions, dict):
        raise RuntimeError("grok workflow.pre_send.exceptions must be a mapping")
    raw_spec = exceptions.get(exception_key)
    if not isinstance(raw_spec, dict):
        raise RuntimeError(f"grok has no mapped pre-send exception {exception_key}")

    fresh_url = urls.get("fresh")
    exact_url = raw_spec.get("exact_url")
    detect = raw_spec.get("detect")
    detect_states = raw_spec.get("detect_states")
    blocked_state_absent = raw_spec.get("blocked_state_absent")
    recovery = raw_spec.get("recovery")
    if not isinstance(fresh_url, str) or exact_url != fresh_url:
        raise RuntimeError("grok pre-send exception must bind the exact fresh URL")
    if (
        not isinstance(detect, list)
        or len(detect) != 3
        or len(detect) != len(set(detect))
        or not all(isinstance(key, str) and key in element_map for key in detect)
    ):
        raise RuntimeError("grok pre-send exception detect elements are invalid")
    if not isinstance(detect_states, dict) or set(detect_states) != set(detect):
        raise RuntimeError("grok pre-send exception detect states are invalid")
    for key, states in detect_states.items():
        if (
            not isinstance(states, list)
            or not states
            or len(states) != len(set(states))
            or not all(isinstance(state, str) and state for state in states)
        ):
            raise RuntimeError(f"grok pre-send exception states are invalid for {key}")
    if (
        not isinstance(blocked_state_absent, list)
        or not blocked_state_absent
        or len(blocked_state_absent) != len(set(blocked_state_absent))
        or not all(
            isinstance(key, str) and key in element_map
            for key in blocked_state_absent
        )
    ):
        raise RuntimeError("grok pre-send blocked-state absences are invalid")
    if not isinstance(recovery, dict):
        raise RuntimeError("grok pre-send exception has no recovery mapping")
    element = recovery.get("element")
    absent_after_recovery = recovery.get("absent_after_recovery")
    postcondition = recovery.get("postcondition")
    observation = recovery.get("observation")
    if (
        recovery.get("action") != "click"
        or recovery.get("max_attempts") != 1
        or element not in detect
        or element != "grok_bot_dismiss"
    ):
        raise RuntimeError("grok pre-send recovery must click exact Dismiss once")
    if absent_after_recovery != detect:
        raise RuntimeError("grok pre-send recovery must remove the complete exception set")
    if not isinstance(postcondition, dict) or postcondition.get("scope") != "base":
        raise RuntimeError("grok pre-send recovery postcondition must use base scope")
    exact_singletons = postcondition.get("exact_singletons")
    absent = postcondition.get("absent")
    if (
        not isinstance(exact_singletons, list)
        or not exact_singletons
        or len(exact_singletons) != len(set(exact_singletons))
        or not all(
            isinstance(key, str) and key in element_map
            for key in exact_singletons
        )
    ):
        raise RuntimeError("grok post-recovery exact singleton controls are invalid")
    if (
        not isinstance(absent, list)
        or len(absent) != len(set(absent))
        or not all(isinstance(key, str) and key in element_map for key in absent)
        or not set((*detect, *blocked_state_absent)).issubset(absent)
    ):
        raise RuntimeError("grok post-recovery absent controls are invalid")
    if not isinstance(observation, dict):
        raise RuntimeError("grok pre-send recovery observation barrier is missing")
    refresh_policy = observation.get("refresh_policy")
    stable_cycles = observation.get("stable_cycles")
    interval_ms = observation.get("interval_ms")
    timeout_ms = observation.get("timeout_ms")
    if (
        refresh_policy != "invalidate_reacquire"
        or stable_cycles != 2
        or isinstance(interval_ms, bool)
        or not isinstance(interval_ms, int)
        or interval_ms <= 0
        or isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or timeout_ms < interval_ms * stable_cycles
    ):
        raise RuntimeError("grok pre-send recovery observation barrier is invalid")
    max_samples = (timeout_ms + interval_ms - 1) // interval_ms
    if not 2 <= max_samples <= 100:
        raise RuntimeError("grok pre-send recovery sample bound is invalid")
    return {
        "exact_url": exact_url,
        "detect": tuple(detect),
        "detect_states": {
            key: tuple(states) for key, states in detect_states.items()
        },
        "blocked_state_absent": tuple(blocked_state_absent),
        "element": element,
        "exact_singletons": tuple(exact_singletons),
        "absent_after_recovery": tuple(absent),
        "stable_cycles": stable_cycles,
        "max_samples": max_samples,
    }


def _completed_before_stop_state(platform: str) -> dict[str, object] | None:
    cfg = load_platform_yaml(platform)
    workflow = cfg.get("workflow")
    element_map = (cfg.get("tree") or {}).get("element_map")
    if not isinstance(workflow, dict) or not isinstance(element_map, dict):
        raise RuntimeError(f"{platform} YAML has no valid workflow or element_map")
    post_send = workflow.get("post_send") or {}
    if not isinstance(post_send, dict):
        raise RuntimeError(f"{platform} workflow.post_send must be a mapping")
    raw_state = post_send.get("completed_before_stop")
    if raw_state is None:
        return None
    if not isinstance(raw_state, dict):
        raise RuntimeError(
            f"{platform} workflow.post_send.completed_before_stop must be a mapping"
        )
    detect = raw_state.get("detect")
    absent = raw_state.get("absent")
    stable_observations = raw_state.get("stable_observations")
    handoff = raw_state.get("handoff")
    for field_name, values in (("detect", detect), ("absent", absent)):
        if (
            not isinstance(values, list)
            or not values
            or not all(
                isinstance(value, str) and value in element_map
                for value in values
            )
            or len(values) != len(set(values))
        ):
            raise RuntimeError(
                f"{platform} completed-before-Stop {field_name} elements are invalid"
            )
    if set(detect).intersection(absent):
        raise RuntimeError(
            f"{platform} completed-before-Stop detect and absent elements overlap"
        )
    if stable_observations != 2:
        raise RuntimeError(
            f"{platform} completed-before-Stop requires exactly two observations"
        )
    if handoff not in {"inline_extract", "separate_extract"}:
        raise RuntimeError(
            f"{platform} completed-before-Stop requires a qualified handoff"
        )
    return {
        "detect": tuple(detect),
        "absent": tuple(absent),
        "stable_observations": stable_observations,
        "handoff": handoff,
    }


def _post_send_confirmation_content(
    platform: str,
    completed_before_stop_response_file: Path | None = None,
) -> str:
    exceptions = _post_send_exceptions(platform)
    completed_state = _completed_before_stop_state(platform)
    if exceptions:
        rendered = "; ".join(
            f"{key} requires exactly one each of {', '.join(spec['detect'])}"
            for key, spec in exceptions.items()
        )
    else:
        rendered = "no mapped post-send exception is currently configured for this platform"
    base = (
        "POST-SEND CONFIRMATION: inspect the first fresh base observation already required by "
        "the send step. If the mapped Stop control is present exactly once, require monitor "
        "registration. If Stop is absent, do not mutate: call observe scope=base exactly once "
        "more. If Stop is then present exactly once, require monitor registration. If Stop is "
        f"still absent, classify only these exact YAML-owned exception sets: {rendered}. If one "
        "complete set is present, return a POST-SEND EXCEPTION REPORT naming the exception key, "
        "both fresh observation revisions, current URL, and matched elements. "
    )
    if completed_state is None:
        return (
            base
            + "If no complete set is present, return an UNMAPPED POST-SEND STATE report with "
            "both revisions and current mapped elements. Stop the turn after either report. Do "
            "not infer completion from the URL, Copy, Regenerate, Retry, or any response text. "
            "Do not click any recovery control in the send turn.\n"
        )
    handoff = str(completed_state["handoff"])
    if handoff == "inline_extract" and completed_before_stop_response_file is None:
        raise RuntimeError(
            f"{platform} completed-before-Stop requires an extraction output file"
        )
    detect = ", ".join(completed_state["detect"])
    absent = ", ".join(completed_state["absent"])
    completed_state_instruction = (
        base
        + "If no exception set is present, classify the YAML-owned completed-before-Stop state "
        f"only when both fresh observations contain exactly one each of {detect}, contain none "
        f"of {absent}, preserve the same answer-thread URL, and the mapped input is enabled and "
        "editable. Do not inspect or judge response text. If that exact state is absent, "
        "duplicated, or differs between observations, return an UNMAPPED POST-SEND STATE report "
        "with both revisions and current mapped elements, then stop. If the exact state is "
        "present in both observations, completion occurred before Stop could be observed. Do not "
        "register a monitor and do not claim Stop was seen. "
    )
    receipt_fields = (
        "The terminal receipt must include exact machine fields "
        "completion_basis=completed_before_stop, stop_seen=false, monitor_id=none, "
        "send_count=1, observation_revision_1=<first 64-hex revision>, "
        "observation_revision_2=<second 64-hex revision>, thread_url=<exact current URL>, "
        "platform=<platform>, and display=<display>. "
    )
    if handoff == "separate_extract":
        return (
            completed_state_instruction
            + receipt_fields
            + "Return a COMPLETED-BEFORE-STOP SEND RECEIPT with the matched and absent "
            "elements, then stop all UI calls. Extraction requires a separately authorized "
            "turn bound to this receipt. Do not scroll, Copy, Download, or mutate after the "
            "second completion observation. Do not click any recovery control or send again.\n"
        )
    assert completed_before_stop_response_file is not None
    return (
        completed_state_instruction
        + "Continue in this same turn with exactly: "
        + "key ctrl+End; observe scope=base; require the same URL, completed state, and exactly one "
        + "copy_button target selected by the YAML last_by_y rule; click that copy_button; observe "
        + "scope=base; require the same URL and completed state; read_clipboard with "
        + f"output_file={completed_before_stop_response_file}. Require a new non-empty file. Return "
        + "a COMPLETED-BEFORE-STOP SEND RECEIPT containing the matched and absent elements and "
        + receipt_fields
        + f"output_file={completed_before_stop_response_file}, byte_count=<exact integer>, and "
        + "response_sha256=<exact SHA-256>. Then stop "
        + "all UI calls. Do not click any recovery control or send again.\n"
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


def _chatgpt_model_menu_diagnostic_content(display: str) -> str:
    return (
        f"Execute one frozen ChatGPT Power-focus diagnostic transaction on {display}. Use "
        "drive_chat only. Do not navigate, select a model, attach, paste, send, extract, poll, "
        "recover, press Escape, click Show advanced options, click Model or Effort, or send any "
        "Left or Right key. The only authorized mutations are opening model_selector once if it "
        "is not already expanded and focusing model_power once. Use a ref only from the "
        "immediately preceding fresh observation.\n"
        "1. observe scope=base exactly once. Require one populated ChatGPT tree and exactly one "
        "model_selector whose exact name is Instant. Record its states and snapshot revision. If "
        "its states include expanded, do not operate it. Otherwise operate the fresh "
        "model_selector exactly once, require performed_primitive=mapped_pointer_activate, and "
        "perform no other mutation before step 2.\n"
        "2. observe scope=app_root_snapshot exactly once. Require exactly one model_power whose "
        f"exact name is Power, role is menu item, and description is exactly "
        f"{CHATGPT_POWER_INSTANT_DESCRIPTION!r}. Also require exactly one "
        "model_show_advanced_options whose exact name is Show advanced options and role is menu "
        "item. Record the app-root revision, full model_power row, its description, and its fresh "
        "ref.\n"
        "3. focus element=model_power from that exact fresh ref once. Require performed=true and "
        "performed_primitive=focus. This is the only Power action authorized.\n"
        "4. The immediately next drive_chat call must be observe scope=base exactly once. Make no "
        "intervening call. Require exactly one model_power with name Power, role menu item, states "
        f"including showing, focused, and enabled, and description exactly "
        f"{CHATGPT_POWER_INSTANT_DESCRIPTION!r}. Require model_selector still named Instant with "
        "state expanded and model_show_advanced_options still present exactly once. Make no more "
        "drive_chat calls. Return a CHATGPT MODEL MENU DIAGNOSTIC RECEIPT containing "
        "platform/display, pre_focus_selector, pre_focus_app_root_revision, model_power, "
        "model_show_advanced_options, pre_focus_power_description, power_ref_used, focus_result, "
        "post_focus_base_revision, post_focus_power, post_focus_power_description, "
        "power_focused: true, and power_description with the exact live description. End with "
        "selector_open_count: 0 or 1, power_focus_count: 1, advanced_click_count: 0, "
        "right_key_count: 0, and selected_or_sent: false. Then halt.\n"
        "At the first missing, renamed, duplicated, ambiguous, unsupported, or unexpected element, "
        "state, action, scope, or postcondition, return the first-mismatch stop report and halt. Do "
        "not retry or recover."
    )


def _chatgpt_power_right_diagnostic_content(
    display: str,
    pre_selector_name: str,
    pre_description: str,
) -> str:
    return (
        f"Execute one frozen ChatGPT Power Right-arrow discovery transaction on {display}. Use "
        "drive_chat only. Do not navigate, open the selector, focus or click any element, select "
        "through any other control, attach, paste, send, extract, poll, recover, press Escape, or "
        "send any key other than the one exact Right key below. The only authorized mutation is "
        "one drive_chat action=key with key=Right immediately after the fresh precondition "
        "observation.\n"
        "1. observe scope=base exactly once. Require one populated ChatGPT tree, exactly one "
        f"model_selector whose exact name is {pre_selector_name!r}, role is push button, and "
        "states include "
        "expanded, and exactly one model_power whose exact name is Power, role is menu item, "
        "states include showing, focused, and enabled, and description is exactly "
        f"{pre_description!r}. Record the base revision, full selector row, "
        "full Power row, and exact pre-action description. Do not perform any other call before "
        "step 2.\n"
        "2. call drive_chat with action=key and key=Right exactly once. Do not pass element, ref, "
        "or scope. Require the result key is exactly Right and clearmodifiers is true. This is the "
        "only mutation authorized.\n"
        "3. The immediately next drive_chat call must be observe scope=base exactly once. Make no "
        "intervening call. Require exactly one model_power whose exact name is Power, role is menu "
        "item, and states include showing, focused, and enabled. Require its exact description is "
        "nonempty and byte-different from the exact pre-action description. Require exactly one "
        "model_selector whose role is push button and states include expanded; record its complete "
        "post-action row without assuming its name. Make no more drive_chat calls.\n"
        "Return a CHATGPT POWER RIGHT DIAGNOSTIC RECEIPT containing platform/display, "
        "pre_base_revision, pre_selector, pre_power, key_result, post_base_revision, post_power, "
        "and post_selector. Include each of these three unformatted machine lines exactly once, "
        "using JSON double-quoted strings for the complete verbatim values:\n"
        f"pre_selector_name: {json.dumps(pre_selector_name, ensure_ascii=False)}\n"
        f"pre_power_description: {json.dumps(pre_description, ensure_ascii=False)}\n"
        "post_power_description: \"<complete nonempty exact live post-action description>\"\n"
        "All counters count only drive_chat calls issued by this transaction; an already-open or "
        "already-focused state does not increment them. End with precondition_proven: true, "
        "right_key_result_proven: true, key_result_key: \"Right\", "
        "key_result_clearmodifiers: true, power_focused: true, "
        "post_selector_expanded: true, "
        "power_description_nonempty: true, power_description_changed: true, "
        "base_observe_count: 2, right_key_count: 1, power_adjustment_count: 1, "
        "selector_open_count: 0, power_focus_count: 0, click_count: 0, other_key_count: 0, "
        "other_mutation_count: 0, and sent: false. Then halt.\n"
        "At the first missing, renamed, duplicated, ambiguous, unsupported, or unexpected "
        "element, state, action, scope, result, or postcondition, return the first-mismatch stop "
        "report and halt. Do not retry or recover."
    )


def _chatgpt_model_menu_compact_reset_content(display: str) -> str:
    return (
        f"Execute one frozen ChatGPT advanced-to-compact model-menu reset on {display}. Use "
        "drive_chat only. Do not navigate, open the selector, focus Power, click Show advanced "
        "options, click Model or Effort, select a model, attach, paste, send, extract, poll, "
        "recover, press Escape, or send any key. The only authorized mutation is one direct "
        "click on model_show_compact_options using a ref from the immediately preceding fresh "
        "observation.\n"
        "1. observe scope=base exactly once. Require one populated ChatGPT tree and exactly one "
        "model_selector whose exact name is Instant and whose states include expanded. Record "
        "the selector row and base revision. Do not operate it.\n"
        "2. observe scope=app_root_snapshot exactly once. Require exactly one "
        "model_show_compact_options whose exact name is Show compact options and role is menu "
        "item. Record the app-root revision, full row, and fresh ref.\n"
        "3. click element=model_show_compact_options from that exact fresh ref once. Require "
        "performed=true and performed_primitive=click. This is the only mutation authorized.\n"
        "4. The immediately next drive_chat call must be observe scope=app_root_snapshot exactly "
        "once. Make no intervening call. Require exactly one model_power whose exact name is "
        f"Power, role is menu item, and description is exactly "
        f"{CHATGPT_POWER_INSTANT_DESCRIPTION!r}. Require exactly one "
        "model_show_advanced_options whose exact name is Show advanced options and role is menu "
        "item. Require model_show_compact_options absent. Make no more drive_chat calls. Return "
        "a CHATGPT MODEL MENU COMPACT RESET RECEIPT containing platform/display, "
        "pre_click_selector, pre_click_base_revision, pre_click_app_root_revision, "
        "model_show_compact_options, compact_ref_used, click_result, "
        "post_click_app_root_revision, post_click_model_power, post_click_power_description, "
        "post_click_model_show_advanced_options, show_compact_options_absent: true, and "
        "compact_proven: true. End with compact_click_count: 1, selector_open_count: 0, "
        "power_focus_count: 0, advanced_click_count: 0, model_click_count: 0, "
        "effort_click_count: 0, left_key_count: 0, right_key_count: 0, "
        "other_mutation_count: 0, and selected_or_sent: false. Then halt.\n"
        "At the first missing, renamed, duplicated, ambiguous, unsupported, or unexpected "
        "element, state, action, scope, or postcondition, return the first-mismatch stop report "
        "and halt. Do not retry or recover."
    )


def _perplexity_artifacts_diagnostic_content(
    display: str,
    source_terminal_identity: str,
    thread_url: str,
) -> str:
    return (
        f"Execute one frozen Perplexity Artifacts-pane diagnostic transaction on {display}. "
        f"The terminal source identity is {source_terminal_identity}; never invoke or retry "
        "that identity. This turn has a new identity. Use drive_chat only. Do not navigate, "
        "attach, paste, send, Copy, read the clipboard, extract, poll, recover, press a key, "
        "or click any control except artifacts_one_button exactly once.\n"
        "1. observe scope=base exactly once. Require current_url exactly "
        f"{thread_url}, a populated Perplexity tree, stop_button absent, exactly zero "
        "research_report_open, exactly zero artifact_options, exactly one "
        "artifacts_one_button named Artifacts 1 with role push button and states showing, "
        "focusable, and enabled, exactly one copy_button named Copy, exactly one helpful, and "
        "exactly one not_helpful. Record pre_observation_revision and every precondition count. "
        "Any missing, renamed, duplicated, different, or additional report/options state ends "
        "the turn without mutation.\n"
        "2. click element=artifacts_one_button from that exact fresh observation once. Require "
        "performed=true and performed_primitive=click. This is the only mutation authorized.\n"
        "3. The immediately next drive_chat call must be observe scope=base exactly once. Make "
        "no intervening call. Require the same exact current_url, a populated Perplexity tree, "
        "and stop_button absent. Do not require or infer any report, options, Copy contents, or "
        "other pane element; this observation exists to discover them. Record the exact "
        "post_observation_revision and the observed counts for research_report_open, "
        "artifact_options, artifacts_one_button, copy_contents_button, and copy_button. Make no "
        "more drive_chat calls.\n"
        "Return a PERPLEXITY ARTIFACTS PANE DIAGNOSTIC RECEIPT containing separate platform "
        "and display fields, source_terminal_identity, thread_url, pre_observation_revision, "
        "pre_report_open_count, pre_artifact_options_count, pre_artifacts_one_count, "
        "pre_copy_count, pre_helpful_count, pre_not_helpful_count, clicked_element, "
        "click_result, post_observation_revision, post_report_open_count, "
        "post_artifact_options_count, post_artifacts_one_count, post_copy_contents_count, and "
        f"post_copy_count. Use exact values platform=perplexity and display={display}. End with "
        "observe_count: 2, click_count: 1, copied: false, "
        "extracted: false, sent: false, and other_mutation_count: 0. The complete post-action "
        "tree is retained by the private drive_chat exchange capture; do not paraphrase it as "
        "an extraction result. Then halt.\n"
        "At the first missing, renamed, duplicated, ambiguous, unsupported, or unexpected "
        "element, state, action, scope, result, URL, or postcondition, return the first-mismatch "
        "stop report and halt. Do not retry or recover."
    )


def _perplexity_report_card_diagnostic_content(
    display: str,
    source_diagnostic_identity: str,
    thread_url: str,
) -> str:
    return (
        f"Execute one frozen Perplexity report-entry diagnostic transaction on {display}. "
        f"The source diagnostic identity is {source_diagnostic_identity}; never invoke or "
        "retry that identity. This turn has a new identity. Use drive_chat only. Do not "
        "navigate, attach, paste, send, Copy, read the clipboard, extract, retry, recover, "
        "press a key, or click any control except artifact_report_entry exactly once.\n"
        "1. observe scope=base exactly once. Require current_url exactly "
        f"{thread_url}, a populated Perplexity tree, stop_button absent, exactly one "
        "artifacts_pane_toggle named Artifacts with role push button and states showing, "
        "focused, expanded, focusable, and enabled, exactly one artifact_report_entry with "
        "role push button, states showing, focusable, and enabled, and a nonempty dynamic "
        "name, and exactly one artifacts_pane_download named Download with role push button "
        "and states focusable and enabled. Record pre_observation_revision, every exact "
        "precondition count, and the exact pre_report_entry_name. Any missing, renamed, "
        "duplicated, empty-name, different, or additional report-entry state ends the turn "
        "without mutation.\n"
        "2. click element=artifact_report_entry from that exact fresh observation once. "
        "Require performed=true and performed_primitive=click. This is the only mutation "
        "authorized.\n"
        "3. The immediately next drive_chat call must be observe scope=base exactly once. "
        "Make no intervening call. Require a populated Perplexity tree. Do not require or "
        "infer a particular resulting URL, report surface, options menu, Copy control, or "
        "pane state; this observation exists to discover the exact result. Record "
        "post_observation_revision, post_current_url, and the observed counts for stop_button, "
        "artifacts_pane_toggle, artifact_report_entry, artifacts_pane_download, "
        "research_report_open, artifact_options, and copy_contents_button. Make no more "
        "drive_chat calls.\n"
        "Return a PERPLEXITY REPORT CARD DIAGNOSTIC RECEIPT containing platform, display, "
        "source_diagnostic_identity, thread_url, pre_observation_revision, pre_stop_count, "
        "pre_artifacts_pane_toggle_count, pre_artifact_report_entry_count, "
        "pre_artifacts_pane_download_count, pre_report_entry_name, clicked_element, "
        "click_performed, performed_primitive, post_observation_revision, post_current_url, "
        "post_stop_count, post_artifacts_pane_toggle_count, "
        "post_artifact_report_entry_count, post_artifacts_pane_download_count, "
        "post_research_report_open_count, post_artifact_options_count, and "
        f"post_copy_contents_count. Use exact values platform=perplexity and display={display}. "
        "End with observe_count: 2, click_count: 1, copied: false, clipboard_read: false, "
        "extracted: false, sent: false, and other_mutation_count: 0. The complete post-action "
        "tree is retained by the private drive_chat exchange capture; do not paraphrase it as "
        "an extraction result. Then halt.\n"
        "At the first missing, renamed, duplicated, ambiguous, unsupported, or unexpected "
        "element, state, action, scope, result, URL, or postcondition, return the first-mismatch "
        "stop report and halt. Do not retry or recover."
    )


def _perplexity_report_card_extraction_content(
    display: str,
    source_diagnostic_identity: str,
    thread_url: str,
    response_file: Path,
) -> str:
    return (
        f"Execute one frozen Perplexity report-card extraction transaction on {display}. "
        f"The terminal source diagnostic identity is {source_diagnostic_identity}; never invoke "
        "or retry it. This turn has a new identity. Use drive_chat only. For both clicks, pass "
        "only the exact element key; never copy or pass an opaque ref. Do not attach, paste, "
        "send, research, regenerate, retry, recover, poll, press a key, open a menu, download, "
        "or click any control except artifact_report_entry once and copy_contents_button once.\n"
        "1. observe scope=base exactly once. Record initial_observation_revision and "
        "initial_current_url. If and only if initial_current_url differs from "
        f"{thread_url}, navigate exactly once to {thread_url}, then immediately observe "
        "scope=base exactly once and record that fresh revision. Otherwise do not navigate "
        "and do not take a second pre-click observation. No other URL is authorized.\n"
        "2. On the exact thread URL, require a populated Perplexity tree, stop_button absent, "
        "exactly one artifacts_pane_toggle named Artifacts with role push button and states "
        "showing, focused, expanded, focusable, and enabled, exactly one artifact_report_entry "
        "with role push button, states showing, focusable, and enabled, and a nonempty dynamic "
        "name, and exactly one artifacts_pane_download named Download with role push button and "
        "states focusable and enabled. Record this tree as pre_observation_revision and record "
        "all exact counts plus pre_report_entry_name.\n"
        "3. click element=artifact_report_entry exactly once from that fresh observation. "
        "Require performed=true and performed_primitive=click.\n"
        "4. Immediately observe scope=base exactly once with no intervening call. Require a "
        "populated Perplexity tree, stop_button absent, current_url matching exactly one "
        "standalone report URL of the form https://www.perplexity.ai/computer/a/<non-empty-id>, "
        "and exactly one copy_contents_button named Copy contents with role push button and "
        "states showing and enabled. Record report_surface_observation_revision and the exact "
        "report_surface_url.\n"
        "5. click element=copy_contents_button exactly once from that fresh observation. "
        "Require performed=true and performed_primitive=click.\n"
        "6. Immediately observe scope=base exactly once with no intervening call. Require the "
        "same exact report_surface_url, a populated Perplexity tree, stop_button absent, and "
        "exactly one copy_contents_button named Copy contents with role push button and states "
        "showing and enabled.\n"
        f"7. read_clipboard output_file={response_file} exactly once. Require the newly created "
        "file to be nonempty. Compute its exact byte_count and response_sha256. Make no more "
        "drive_chat calls.\n"
        "Return a PERPLEXITY REPORT CARD EXTRACTION RECEIPT containing separate fields for "
        "platform, display, source_diagnostic_identity, thread_url, initial_observation_revision, "
        "initial_current_url, navigation_count, post_navigation_observe_count, "
        "pre_observation_revision, pre_current_url, pre_stop_count, "
        "pre_artifacts_pane_toggle_count, pre_artifact_report_entry_count, "
        "pre_artifacts_pane_download_count, pre_report_entry_name, clicked_report_entry, "
        "report_entry_click_performed, report_entry_performed_primitive, "
        "report_surface_observation_revision, report_surface_url, report_surface_stop_count, "
        "report_surface_copy_contents_count, clicked_copy_contents, copy_click_performed, "
        "copy_performed_primitive, post_copy_observation_revision, post_copy_url, "
        "post_copy_stop_count, post_copy_contents_count, output_file, byte_count, and "
        "response_sha256. End with initial_observe_count: 1, report_entry_click_count: 1, "
        "report_surface_observe_count: 1, report_copy_click_count: 1, "
        "post_copy_observe_count: 1, clipboard_read_count: 1, total_click_count: 2, "
        "other_mutation_count: 0, extracted: true, sent: false, regenerated: false, and "
        "retried: false. Then halt.\n"
        "At the first missing, renamed, duplicated, ambiguous, unsupported, or unexpected "
        "element, state, action, scope, result, URL, file, or postcondition, return the "
        "first-mismatch stop report and halt. Do not retry or recover."
    )


def _perplexity_report_preview_extraction_content(
    display: str,
    source_response_sha256: str,
    preview_url: str,
    response_file: Path,
) -> str:
    return (
        f"Execute one frozen Perplexity report-preview extraction on {display}. This new turn is "
        "authorized only by the terminal first-mismatch response whose exact SHA-256 is "
        f"{source_response_sha256}; never invoke or retry that source identity. Use drive_chat "
        "only and pass element keys only, never opaque refs. Do not navigate, attach, paste, "
        "send, research, regenerate, retry, recover, poll, press a key, expand, close, download, "
        "or scroll.\n"
        f"1. observe scope=base exactly once. Require current_url exactly {preview_url}, a "
        "populated Perplexity tree, stop_button absent, exactly one artifact_options named "
        "Artifact options with role push button and states showing, focusable, enabled, exactly "
        "one close_artifact named Close, exactly one expand_artifact named Expand artifact, and "
        "exactly one report_scroll_pane with role scroll pane and states showing and enabled.\n"
        "2. operate element=artifact_options exactly once. Require performed=true and "
        "performed_primitive=mapped_pointer_activate. Immediately observe scope=base "
        "exactly once. Require current_url unchanged, stop_button absent, and exactly one "
        "artifact_open_new_tab named Open in new tab with role menu item and states showing and enabled.\n"
        "3. click element=artifact_open_new_tab exactly once. Require performed=true and "
        "performed_primitive=click. Immediately observe scope=base exactly once. Require current_url "
        "to match https://www.perplexity.ai/computer/a/<non-empty-id>, stop_button absent, and "
        "exactly one copy_contents_button named Copy contents with role push button and states "
        "showing and enabled.\n"
        "4. click element=copy_contents_button exactly once. Require performed=true and "
        "performed_primitive=click. Immediately observe scope=base exactly once. Require the same "
        "standalone report URL, stop_button absent, and exactly one copy_contents_button named "
        "Copy contents with role push button and states showing and enabled.\n"
        f"5. read_clipboard output_file={response_file} exactly once. Require the new file to be "
        "nonempty and compute exact byte_count and response_sha256. Make no more drive_chat calls.\n"
        "Return a PERPLEXITY REPORT PREVIEW EXTRACTION RECEIPT with separate fields: platform, "
        "display, source_response_json_sha256, preview_url, pre_observation_revision, pre_stop_count, "
        "pre_artifact_options_count, pre_close_artifact_count, pre_expand_artifact_count, "
        "pre_report_scroll_pane_count, options_performed, options_primitive, menu_observation_revision, "
        "menu_stop_count, menu_open_new_tab_count, open_new_tab_performed, open_new_tab_primitive, "
        "standalone_observation_revision, standalone_url, standalone_stop_count, "
        "standalone_copy_contents_count, copy_performed, copy_primitive, post_copy_observation_revision, "
        "post_copy_url, post_copy_stop_count, post_copy_contents_count, output_file, byte_count, and "
        "response_sha256. End with observe_count: 4, operate_count: 1, click_count: 2, "
        "clipboard_read_count: 1, other_mutation_count: 0, extracted: true, sent: false, "
        "regenerated: false, retried: false. Then halt. At first mismatch, return the first-mismatch "
        "stop report and halt without another action."
    )


def _perplexity_report_open_menu_extraction_content(
    display: str,
    source_response_sha256: str,
    source_observation_revision: str,
    preview_url: str,
    response_file: Path,
) -> str:
    return (
        f"Execute one frozen Perplexity already-open report-menu extraction on {display}. This "
        "new turn is authorized only by the terminal first-mismatch response whose exact SHA-256 "
        f"is {source_response_sha256} and whose exact source observation revision is "
        f"{source_observation_revision}; never invoke or retry that source identity. Use "
        "drive_chat only and pass element keys only, never opaque refs. Do not operate "
        "artifact_options. Do not navigate, attach, paste, send, research, regenerate, retry, "
        "recover, poll, press a key, expand, close, download, or scroll.\n"
        f"1. observe scope=base exactly once. Require snapshot revision exactly "
        f"{source_observation_revision}, current_url exactly {preview_url}, a populated Perplexity "
        "tree, stop_button absent, exactly one artifact_options named Artifact options with role "
        "push button and states showing, expanded, focusable, enabled, and exactly one "
        "artifact_open_new_tab named Open in new tab with role menu item and states showing and "
        "enabled. Do not operate the already-expanded artifact_options control.\n"
        "2. click element=artifact_open_new_tab exactly once. Require performed=true and "
        "performed_primitive=click. Immediately observe scope=base exactly once. Require "
        "current_url to match https://www.perplexity.ai/computer/a/<non-empty-id>, stop_button "
        "absent, and exactly one copy_contents_button named Copy contents with role push button "
        "and states showing and enabled.\n"
        "3. click element=copy_contents_button exactly once. Require performed=true and "
        "performed_primitive=click. Immediately observe scope=base exactly once. Require the same "
        "standalone report URL, stop_button absent, and exactly one copy_contents_button named "
        "Copy contents with role push button and states showing and enabled.\n"
        f"4. read_clipboard output_file={response_file} exactly once. Require the new file to be "
        "nonempty and compute exact byte_count and response_sha256. Make no more drive_chat calls.\n"
        "Return a PERPLEXITY REPORT OPEN MENU EXTRACTION RECEIPT with separate fields: platform, "
        "display, source_response_json_sha256, source_observation_revision, preview_url, "
        "pre_observation_revision, pre_stop_count, pre_artifact_options_count, "
        "pre_artifact_options_expanded, pre_open_new_tab_count, open_new_tab_performed, "
        "open_new_tab_primitive, standalone_observation_revision, standalone_url, "
        "standalone_stop_count, standalone_copy_contents_count, copy_performed, copy_primitive, "
        "post_copy_observation_revision, post_copy_url, post_copy_stop_count, "
        "post_copy_contents_count, output_file, byte_count, and response_sha256. End with "
        "observe_count: 3, operate_count: 0, click_count: 2, clipboard_read_count: 1, "
        "other_mutation_count: 0, extracted: true, sent: false, regenerated: false, retried: "
        "false. Then halt. At first mismatch, return the first-mismatch stop report and halt "
        "without another action."
    )


def _claude_pre_send_recovery_content(
    display: str,
    exception_key: str,
    source_terminal_identity: str,
) -> str:
    spec = _claude_pre_send_recovery_spec(exception_key)
    detect = tuple(str(value) for value in spec["detect"])
    detect_states = dict(spec["detect_states"])
    navigation_controls = tuple(str(value) for value in spec["navigation_controls"])
    absent_after_recovery = tuple(
        str(value) for value in spec["absent_after_recovery"]
    )
    forbidden_after_recovery = tuple(
        str(value) for value in spec["forbidden_after_recovery"]
    )
    element = str(spec["element"])
    url_prefix = str(spec["url_prefix"])
    stable_cycles = int(spec["stable_cycles"])
    max_samples = int(spec["max_samples"])
    state_contract = "; ".join(
        f"{key} states include {', '.join(str(state) for state in states)}"
        for key, states in detect_states.items()
    )
    return (
        f"Execute one frozen Claude pre-send exception recovery transaction on {display}. "
        f"The terminal source identity is {source_terminal_identity}; never invoke or retry "
        "that identity. This turn has a new identity. Use drive_chat only. Do not attach, paste, "
        "send, extract, navigate, focus, press a key, operate any menu, or click any control "
        f"except {element} exactly once.\n"
        f"1. observe scope=base exactly once. Require current_url to begin exactly {url_prefix}, "
        f"one populated Claude tree, exactly one each of {', '.join(detect)}, and {state_contract}. "
        f"Require zero of the navigation-ready controls {', '.join(navigation_controls)}. Record "
        "classification_revision_1. Any missing, duplicate, renamed, different, or additional "
        "state is a first mismatch and ends the turn without mutation.\n"
        "2. observe scope=base exactly once more without mutation. Require the same URL, exact "
        "exception elements, states, and absent navigation-ready controls. Record "
        "classification_revision_2 and the fresh recovery-control ref. Any difference ends the "
        "turn without mutation.\n"
        f"3. click element={element} exactly once using only that fresh ref. Require "
        "performed=true. This is the only mutation authorized.\n"
        f"4. Begin the existing YAML-owned navigation observation barrier. Take at most "
        f"{max_samples} fresh base observations. A sample matches only when current_url still "
        f"begins {url_prefix}, the tree is populated, exactly one each of "
        f"{', '.join(navigation_controls)} is mapped, and every element in "
        f"{', '.join((*absent_after_recovery, *forbidden_after_recovery))} is absent. Require "
        f"{stable_cycles} consecutive "
        "matching samples. A nonmatching settling sample authorizes only the next read-only base "
        "observation; it never authorizes another mutation. If the exception remains after the "
        "click, one of the exact forbidden elements appears, an element duplicates or changes, or the "
        "sample bound ends without the stable postcondition, return a FIRST-MISMATCH STOP REPORT "
        "with every observation revision and current mapped elements, then stop.\n"
        "5. After the stable barrier, make no more drive_chat calls. Return a CLAUDE PRE-SEND "
        "RECOVERY RECEIPT containing platform, display, source_terminal_identity, exception_key, "
        "classification_revision_1, classification_revision_2, clicked_element, click_count, "
        "navigation_postcondition_elements, stable_cycles, post_recovery_revision_1, "
        "post_recovery_revision_2, interstitial_absent, attached, pasted, sent, and recovered. "
        f"Use exact values platform=claude, display={display}, "
        f"source_terminal_identity={source_terminal_identity}, exception_key={exception_key}, "
        f"clicked_element={element}, click_count=1, stable_cycles={stable_cycles}, "
        "interstitial_absent=true, attached=false, pasted=false, sent=false, and recovered=true. "
        "The two post-recovery revisions must be the final two matching barrier samples. Then halt."
    )


def _grok_pre_send_recovery_content(
    display: str,
    exception_key: str,
    source_terminal_identity: str,
) -> str:
    spec = _grok_pre_send_recovery_spec(exception_key)
    detect = tuple(str(value) for value in spec["detect"])
    detect_states = dict(spec["detect_states"])
    blocked_state_absent = tuple(
        str(value) for value in spec["blocked_state_absent"]
    )
    exact_singletons = tuple(str(value) for value in spec["exact_singletons"])
    absent_after_recovery = tuple(
        str(value) for value in spec["absent_after_recovery"]
    )
    element = str(spec["element"])
    exact_url = str(spec["exact_url"])
    stable_cycles = int(spec["stable_cycles"])
    max_samples = int(spec["max_samples"])
    state_contract = "; ".join(
        f"{key} states include {', '.join(str(state) for state in states)}"
        for key, states in detect_states.items()
    )
    return (
        f"Execute one frozen Grok pre-send exception recovery transaction on {display}. "
        f"The terminal source identity is {source_terminal_identity}; never invoke or retry "
        "that identity. This turn has a distinct new seat identity. Use drive_chat only and "
        "pass element keys only, never opaque refs. Do not navigate, attach, paste, send, "
        "extract, select a model, open a menu, focus, press a key, scroll, retry, or click any "
        f"control except {element} exactly once.\n"
        f"1. observe scope=base exactly once. Require current_url exactly {exact_url}, one "
        f"populated Grok tree, exactly one each of {', '.join(detect)}, and {state_contract}. "
        f"Require zero each of {', '.join(blocked_state_absent)}. Record "
        "classification_revision_1 and exact pre-recovery match counts. Any missing, duplicate, "
        "renamed, different, or additional mapped interstitial control is a first mismatch and "
        "ends the turn without mutation.\n"
        "2. observe scope=base exactly once more without mutation. Require the same exact URL, "
        "singleton interstitial controls, states, and absent controls. Record "
        "classification_revision_2 and exact pre-recovery match counts. Any difference ends the "
        "turn without mutation.\n"
        f"3. click element={element} exactly once. Require performed=true and "
        "performed_primitive=click. This is the only mutation authorized. Never click "
        "grok_bot_get.\n"
        f"4. Take at most {max_samples} fresh base observations. A sample matches only when "
        f"current_url is exactly {exact_url}, the Grok tree is populated, exactly one each of "
        f"{', '.join(exact_singletons)} is mapped, and every element in "
        f"{', '.join(absent_after_recovery)} is absent. Require {stable_cycles} consecutive "
        "matching samples. A nonmatching settling sample authorizes only the next read-only base "
        "observation; it never authorizes another mutation. If an interstitial remains after the "
        "click, an attachment, Send, or Stop control appears, a required fresh control is missing "
        "or duplicated, the URL changes, or the sample bound ends without the stable "
        "postcondition, return a FIRST-MISMATCH STOP REPORT with every observation revision and "
        "exact match count, then stop.\n"
        "5. After the stable barrier, make no more drive_chat calls. Return a GROK PRE-SEND "
        "RECOVERY RECEIPT containing platform, display, source_terminal_identity, exception_key, "
        "classification_revision_1, classification_revision_2, pre_recovery_counts_1, "
        "pre_recovery_counts_2, clicked_element, click_count, performed_primitive, "
        "postcondition_elements, stable_cycles, post_recovery_revision_1, "
        "post_recovery_revision_2, post_recovery_counts_1, post_recovery_counts_2, "
        "interstitial_absent, observe_count, navigation_count, attachment_count, paste_count, "
        "send_count, selected_model, sent, and recovered. Use exact values platform=grok, "
        f"display={display}, source_terminal_identity={source_terminal_identity}, "
        f"exception_key={exception_key}, clicked_element={element}, click_count=1, "
        f"performed_primitive=click, stable_cycles={stable_cycles}, interstitial_absent=true, "
        "navigation_count=0, attachment_count=0, paste_count=0, send_count=0, "
        "selected_model=false, sent=false, and recovered=true. observe_count must equal two plus "
        "the exact number of post-click barrier samples. The two post-recovery revisions and "
        "count maps must be the final two matching barrier samples. Write each of the four count "
        "maps as one unquoted compact JSON object on its own field-name line, for example "
        "pre_recovery_counts_1: {\"grok_bot_dialog\":1}. Write observe_count on its own "
        "field-name line. Then halt."
    )


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
    completed_before_stop_response_file: Path | None = None,
) -> str:
    post_send = _post_send_confirmation_content(
        platform,
        completed_before_stop_response_file,
    )
    if platform == "claude":
        active_model_names = json.dumps(
            list(_claude_active_model_names()),
            ensure_ascii=False,
        )
        return (
            f"Execute one frozen Claude send transaction on {display}. Use drive_chat only. "
            "Do not read any file, runbook, or YAML. Use a ref or snapshot revision only from "
            "the immediately preceding fresh observation. Execute exactly this sequence, with "
            "one fresh observation after every mutation:\n"
            "1. navigate to https://claude.ai/new; observe scope=base; require current_url to "
            "be the Claude fresh URL, a populated Claude tree, exactly one input, exactly one "
            "toggle_menu, and exactly one model_selector whose exact name is in the "
            f"YAML-derived set {active_model_names}. "
            "Require no stop_button and none of these mapped "
            "exception elements: send_blocked_previous_message, send_blocked_previous_message_curly, "
            "network_connection_alert, send_blocked_caution_banner, claude_capacity_alert, "
            "claude_capacity_alert_pro, claude_session_limit_alert, claude_hit_limit_alert, "
            "claude_not_working_alert, or claude_chat_length_limit_alert. Record this post-navigation "
            "fresh URL. If no remove_attachment controls are present, continue. If one or more "
            "remove_attachment controls are present, record their exact initial count N. Require the "
            "fresh observation to expose exactly one YAML-selected canonical remove_attachment target. "
            "Repeat exactly N times: click element=remove_attachment once from the fresh observation; "
            "observe scope=base; require the remove_attachment count to decrease by exactly one, the same "
            "Claude fresh URL and required controls, no stop_button, and none of the mapped exception "
            "elements above. Before each remaining click require exactly one YAML-selected canonical "
            "remove_attachment target from that fresh observation. After the Nth click require zero "
            "remove_attachment controls, and record that observation as the clean "
            "post-navigation base proof. If the initial state is neither clean nor stale-attachment state, "
            "or any count/postcondition fails, stop without opening the model or effort menu.\n"
            f"2. Attach Bundle A from {bundle_a}: before ctrl+u, require the immediately "
            "preceding fresh base observation to expose key_preconditions.ctrl+u as one exact "
            "lowercase SHA-256 token. If it is absent, focus element=input exactly once from "
            "that fresh observation; observe scope=base exactly once; require the same Claude "
            "fresh URL, zero remove_attachment controls, model_selector exact name still in the "
            f"YAML-derived set {active_model_names}, no stop_button, none of the mapped exception "
            "elements above, and key_preconditions.ctrl+u now present as one exact lowercase "
            "SHA-256 token. If it is still absent, return the first-mismatch stop report and stop. "
            "Then call drive_chat with exactly action=key, "
            f"display={display}, key=ctrl+u; pass no element, ref, scope, or other argument; "
            "observe scope=base; require the same Claude fresh URL, zero remove_attachment controls, "
            "model_selector exact name still in the "
            f"YAML-derived set {active_model_names}, and no mapped exception; focus_dialog "
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
            "and suffix. Require zero Bundle B matches, model_selector exact name still in the "
            f"YAML-derived set {active_model_names}, "
            "and no mapped exception.\n"
            f"3. Attach Bundle B from {bundle_b}: before ctrl+u, require the immediately "
            "preceding fresh base observation to expose key_preconditions.ctrl+u as one exact "
            "lowercase SHA-256 token. If it is absent, focus element=input exactly once from "
            "that fresh observation; observe scope=base exactly once; require the same Claude "
            "fresh URL, exactly one remove_attachment control, the same Bundle A filename proof, "
            "zero Bundle B matches, model_selector exact name still in the "
            f"YAML-derived set {active_model_names}, no stop_button, none of the mapped exception "
            "elements above, and key_preconditions.ctrl+u now present as one exact lowercase "
            "SHA-256 token. If it is still absent, return the first-mismatch stop report and stop. "
            "Then call drive_chat with exactly action=key, "
            f"display={display}, key=ctrl+u; pass no element, ref, scope, or other argument; "
            "observe scope=base; require exactly one mapped remove_attachment control, model_selector "
            "exact name still in the "
            f"YAML-derived set {active_model_names}, and no mapped exception; focus_dialog using that fresh observation "
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
            "driver rule. Require no third remove_attachment control, model_selector exact name still "
            f"in the YAML-derived set {active_model_names}, and no mapped exception.\n"
            "4. focus the fresh input ref; observe scope=base; require input match_count 1 with "
            "state focused, the same exact two remove_attachment controls, and Bundle A plus "
            "Bundle B filename proofs; paste "
            f"text_file={prompt_file} exactly once; observe scope=base; require the same two "
            "attachment-count and filename proofs, exactly one enabled send_button named Send message, "
            "model_selector exact name still in the "
            f"YAML-derived set {active_model_names}, and no mapped exception. Do not require a "
            "composer character count or type-text fallback.\n"
            "5. click the fresh send_button ref exactly once; observe scope=base exactly once; require "
            "current_url to differ from the recorded post-navigation fresh URL and to contain /chat/; "
            "then follow the post-send confirmation below. On a Stop-proven observation, require no "
            "mapped exception and return a receipt containing platform/display, final URL, "
            f"the YAML-derived active-model proof {active_model_names}, Bundle A one-count proof, "
            "Bundle B two-count proof, the "
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
        generic_post_send_heading = "POST-SEND CONFIRMATION: "
        if not post_send.startswith(generic_post_send_heading):
            raise RuntimeError("Gemini research confirmation heading contract drifted")
        research_post_send = (
            "RESEARCH-PHASE POST-START CONFIRMATION: ENTRY REQUIRES "
            "start_research_click_count=1 and a recorded start_research_post_revision. If either "
            "proof is absent, this block is out of scope and must not be evaluated. "
            + post_send.removeprefix(generic_post_send_heading)
        )
        return (
            f"Execute one frozen Gemini send transaction on {display}. Use drive_chat only. "
            "Do not read any file, runbook, or YAML. For click or focus, pass only the exact "
            "element key mapped as a singleton by the immediately preceding fresh observation; "
            "do not copy or pass an opaque ref. Execute exactly this sequence, with "
            "one fresh observation after every mutation:\n"
            "1. navigate to https://gemini.google.com/u/1/app?pageId=none; observe scope=base; "
            "require a populated Gemini tree and exactly one each of input, mode_picker, "
            "tools_button, and upload_menu. Require send_button, stop_button, and "
            "copy_button absent. Record this post-navigation fresh URL.\n"
            "2. Require mode_picker name exactly Open mode picker, currently Pro Extended. If it "
            "is not exact: click element=mode_picker; observe scope=menu_snapshot; require "
            "mode_extended match_count 1 with name exactly Extended thinking Complex problem "
            "solving; click element=mode_extended; observe scope=base; require mode_picker "
            "name exactly Open mode picker, currently Pro Extended. Do not touch the model menu.\n"
            "3. From that fresh base observation, if tool_deselect_deep_research is present "
            "exactly once with name exactly Deselect Deep research, record the Deep Research "
            "active proof and do not open the tools menu. Otherwise require "
            "tool_deselect_deep_research absent; focus element=tools_button; observe scope=base; "
            "require tools_button match_count 1 with name exactly Upload & tools and state focused, "
            "and require mode_picker still named Open mode picker, currently Pro Extended; key space "
            "using that fresh base revision; observe scope=menu_snapshot; require "
            "scope_expected_elements to contain tool_deep_research and require "
            "tool_deep_research match_count 1 with name exactly Deep research; click "
            "element=tool_deep_research exactly once; observe scope=base; require "
            "tool_deselect_deep_research match_count 1 with name exactly Deselect Deep research "
            "and mode_picker name exactly Open mode picker, currently Pro Extended. Record that "
            "fresh observation as the Deep Research active proof.\n"
            f"4. Attach Bundle A from {bundle_a}: focus element=upload_menu; observe "
            "scope=base; require upload_menu match_count 1 with state focused; key space; observe "
            "scope=menu_snapshot; require "
            "scope_expected_elements to contain upload_files_item and require upload_files_item "
            "match_count 1 with name exactly Upload files. Documents, data, code files and state "
            "focused; key Return using the fresh menu_snapshot revision; observe; "
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
            "Extended and tool_deselect_deep_research match_count 1 with name exactly Deselect "
            "Deep research.\n"
            f"5. Attach Bundle B from {bundle_b}: focus element=upload_menu; observe "
            "scope=base; require upload_menu match_count 1 with state focused; key space; observe "
            "scope=menu_snapshot; require "
            "scope_expected_elements to contain upload_files_item and require upload_files_item "
            "match_count 1 with name exactly Upload files. Documents, data, code files and state "
            "focused; key Return using the fresh menu_snapshot revision; observe; "
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
            "Extended and tool_deselect_deep_research match_count 1 with name exactly Deselect "
            "Deep research. Record this first post-B observation as attachment_settle_revision_1 "
            "with Bundle A match_count 1 and Bundle B match_count 1.\n"
            "6. Before any prompt mutation, observe scope=base exactly once more. This must be a "
            "new independent drive_chat observation call; an identical tree hash is allowed when "
            "the stable UI is unchanged. Over fresh unknown nodes whose role is section, count each "
            "node once when its name, description, or text contains a filename stem. Require exactly "
            f"one node containing Bundle A stem {bundle_a_stem} and exactly one node containing Bundle "
            f"B stem {bundle_b_stem}. Require mode_picker still named Open mode picker, currently Pro "
            "Extended, tool_deselect_deep_research match_count 1 with name exactly Deselect Deep "
            "research, and input match_count 1 with state focused. Record this as "
            "attachment_settle_revision_2 with Bundle A match_count 1 and Bundle B match_count 1. "
            "The current Gemini YAML exposes no mapped upload-in-progress, upload-busy, or upload-error "
            "element, so make no inferred upload-state claim beyond these exact mapped proofs.\n"
            "7. From that second fresh attachment-settle observation, require input match_count 1 "
            "with state focused; paste "
            f"text_file={prompt_file} exactly once; observe scope=base; require exactly one enabled "
            "send_button named Send message. Require at least one fresh section node whose name, "
            f"description, or text contains Bundle A stem {bundle_a_stem} and at least one containing "
            f"Bundle B stem {bundle_b_stem}; do not require exact post-paste stem counts. Require "
            "tool_deselect_deep_research match_count 1 with name exactly Deselect Deep research. "
            "Record prompt_paste_observation_revision.\n"
            "8. focus element=send_button; observe scope=base; require send_button match_count 1 "
            "with state focused and tool_deselect_deep_research match_count 1 with name exactly "
            "Deselect Deep research. Record plan_send_pre_revision; key space exactly once; observe "
            "scope=base exactly once; require current_url on gemini.google.com matching /app/<id> or "
            "/u/<digit>/app/<id> and do not require a URL change. Record plan_send_post_revision and "
            "plan_send_count=1. A stop_button during this phase proves only plan generation; it does "
            "not authorize monitor handoff. Immediately after plan_send_post_revision, Step 9 is "
            "the exclusive next phase. Until start_research_click_count=1 and "
            "start_research_post_revision are both recorded, do not evaluate any post-send "
            "exception or completed-before-Stop state; Copy, input, and absence of Stop or Send "
            "are only read-only wait-state evidence.\n"
            "9. Use read-only base observations to wait at most 180 seconds for start_research "
            "match_count 1 with name exactly Start research and state enabled. Every sample must retain "
            "the same answer-thread URL, mode_picker name exactly Open mode picker, currently Pro "
            "Extended, and tool_deselect_deep_research match_count 1 with name exactly Deselect Deep "
            "research. While start_research is absent or is present once but not yet enabled, make no "
            "mutation and take only another fresh base observation. More than one start_research, a "
            "different URL, a missing mode/tool proof, or expiry of 180 seconds is a terminal first "
            "mismatch. Do not treat a plan-phase stop_button as research-phase completion. Record every "
            "sample revision and the final enabled singleton start_research_pre_revision.\n"
            "10. click element=start_research exactly once from that immediately preceding fresh base "
            "observation; observe scope=base exactly once; require the same answer-thread URL and record "
            "start_research_click_count=1 plus start_research_post_revision. Only now follow the "
            "post-send confirmation below for the research-phase mapped Stop. On a Stop-proven "
            "observation, return a receipt containing platform/display, final URL, the Pro Extended "
            "proof, the Deep Research active proof, the exact Bundle A one-count proof, the exact "
            "Bundle B one-count proof in both attachment-settle observations, "
            "attachment_settle_revision_1, attachment_settle_revision_2, "
            "prompt_paste_observation_revision, plan_send_pre_revision, plan_send_post_revision, "
            "plan_send_count=1, start_research_pre_revision, start_research_post_revision, "
            "start_research_click_count=1, research_stop_seen=true, the mapped Stop key, and monitor_id. "
            "If the post-send confirmation instead proves the YAML-owned completed-before-Stop state, "
            "include the same attachment, prompt, plan-send, and Start-research fields in that terminal "
            "success receipt with research_stop_seen=false in addition to its required completion fields. "
            "Then stop all UI calls.\n"
            f"{research_post_send}"
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
            "mapped_pointer_activate; observe scope=app_root_snapshot; require model_heavy match_count "
            "1 with name exactly Heavy Team of Experts · Grok 4.5. If model_heavy states include "
            "checked, key Escape using that fresh app_root_snapshot revision; otherwise click "
            "element=model_heavy using that fresh observation; "
            "observe scope=base; require exactly one each of input named Ask Grok anything, "
            "model_selector named Model select, and attach_trigger named Attach.\n"
            f"3. Attach Bundle A from {bundle_a}: operate element=attach_trigger and require "
            "performed_primitive=mapped_pointer_activate; observe scope=menu_snapshot; require "
            "upload_files_item match_count 1 with name exactly Upload "
            "a file; click element=upload_files_item; observe; focus_dialog using the fresh "
            "observation and require focused=true with matched_title equal to one of File Upload, "
            "Open File, Open, Choose File, or Select File; observe; key ctrl+l; observe; require "
            "exactly one focused editable location_entry; key ctrl+a; observe; type exactly "
            f"{bundle_a}; observe; require location_entry text exactly {bundle_a}; key Return; observe "
            "scope=base; require uploaded_file_chip match_count 1 with name exactly Open attachment "
            "Remove this attachment and remove_attachment match_count 1 with name exactly Remove "
            "this attachment. Require stop_button absent.\n"
            f"4. Attach Bundle B from {bundle_b}: require the current fresh base observation to "
            "contain attach_trigger match_count 1 and uploaded_file_chip plus remove_attachment "
            "match_count 1; operate element=attach_trigger and require performed_primitive="
            "mapped_pointer_activate; observe scope=menu_snapshot; require "
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
            "platform/display, final URL, the exact Heavy selection proof, the one-then-two attachment "
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
            "Selects the best available model. If model_best states include checked, key Escape using "
            "that fresh menu_snapshot revision; otherwise click element=model_best using that fresh "
            "observation; observe scope=base; require exactly one input and "
            "attach_trigger and exactly one of the two pressed mode controls from step 1. Record the "
            "exact checked-or-click branch as the Best selection proof.\n"
            "3. If deep_research_toggle is already present exactly once with name Deep research and "
            "state pressed, record that proof and do not mutate the mode. Otherwise require "
            "search_mode_trigger present exactly once with name Search and state pressed; operate "
            "element=search_mode_trigger and require performed_primitive=focus_and_key_open; observe "
            "scope=menu_snapshot; require deep_research match_count 1 with name exactly Deep "
            "research; click element=deep_research exactly once; observe scope=base; require "
            "deep_research_toggle match_count 1 with name exactly Deep research and state pressed.\n"
            f"4. Attach Bundle A from {bundle_a}: operate element=attach_trigger and require "
            "performed_primitive=mapped_pointer_activate; observe scope=app_root_snapshot; require "
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
            f"5. Attach Bundle B from {bundle_b}: operate element=attach_trigger and require "
            "performed_primitive=mapped_pointer_activate; observe scope=app_root_snapshot; require "
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
            "exact Best selection proof, the Deep research pressed proof, both distinct attachment basename "
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
        "2. Require model_selector name Pro. If it is not Pro: operate element=model_selector and "
        "require performed_primitive=mapped_pointer_activate; observe scope=app_root_snapshot; click "
        "the fresh model_pro ref; observe scope=base; require "
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


def _require_extraction_steps(
    platform: str,
    output_type: str,
    expected: tuple[tuple[str, str | None, str, str | None], ...],
) -> None:
    workflow = get_extraction(platform, output_type)
    if workflow is None:
        raise RuntimeError(f"{platform} YAML has no {output_type} extraction workflow")
    observed = tuple(
        (step.action, step.element, step.select, step.validation)
        for step in workflow.steps
    )
    if observed != expected or workflow.validate_markers:
        raise RuntimeError(
            f"{platform} YAML {output_type} extraction workflow does not match the "
            "qualified production sequence"
        )


def _require_claude_extraction_workflows() -> None:
    _require_extraction_steps(
        "claude",
        "assistant_text",
        (
            ("scroll_to_bottom", "message_actions_button", "last", None),
            ("hover", "message_actions_button", "last", None),
            ("copy_element", "copy_button", "last", None),
            ("read_clipboard", None, "last", None),
        ),
    )
    _require_extraction_steps(
        "claude",
        "downloaded_file",
        (("download", "generated_artifact_download_button", "last", None),),
    )


def _bind_claude_observation_display(display: str) -> None:
    current_display = str(os.environ.get("DISPLAY") or "").strip()
    if current_display and current_display != display:
        raise RuntimeError(
            f"process DISPLAY={current_display!r} does not match Claude display {display!r}"
        )
    bus_path = Path("/tmp") / f"a11y_bus_{display}"
    try:
        descriptor = os.open(
            bus_path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        raise RuntimeError(
            f"could not open Claude AT-SPI bus binding: {bus_path}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(
                "Claude AT-SPI bus binding must be a regular nonsymlink file"
            )
        bus = os.read(descriptor, 4096).decode("utf-8").strip()
        if os.read(descriptor, 1):
            raise RuntimeError("Claude AT-SPI bus binding is unexpectedly large")
    finally:
        os.close(descriptor)
    if not bus:
        raise RuntimeError("Claude AT-SPI bus binding is empty")
    current_bus = str(os.environ.get("AT_SPI_BUS_ADDRESS") or "").strip()
    if current_bus and current_bus != bus:
        raise RuntimeError(
            "process AT_SPI_BUS_ADDRESS does not match the Claude display binding"
        )
    os.environ["DISPLAY"] = display
    os.environ["AT_SPI_BUS_ADDRESS"] = bus


def _build_canonical_claude_snapshot():
    from consultation_v2.snapshot import build_snapshot

    _firefox, _document, snapshot = build_snapshot("claude")
    return snapshot


def _classify_claude_extraction_snapshot(
    snapshot,
) -> tuple[str, str, dict[str, int]]:
    try:
        return classify_claude_extraction_snapshot(snapshot)
    except ClaudeArtifactDownloadError as exc:
        raise RuntimeError(str(exc)) from exc


def _prepare_claude_extraction(
    display: str,
) -> tuple[str, str, dict[str, int], ClaudeDownloadSnapshot | None]:
    _bind_claude_observation_display(display)
    snapshot = _build_canonical_claude_snapshot()
    mode, revision, counts = _classify_claude_extraction_snapshot(snapshot)
    download_before = None
    if mode == "downloaded_file":
        download_before = snapshot_claude_downloads(
            resolve_claude_download_scope(display)
        )
    return mode, revision, counts, download_before


def _extract_content(
    monitor_id: str | None,
    platform: str,
    display: str,
    response_file: Path,
    completed_before_stop_source_sha256: str | None = None,
    claude_extraction_mode: str | None = None,
    claude_launcher_revision: str | None = None,
    output_type: str = "assistant_text",
) -> str:
    if platform == "claude":
        _require_claude_extraction_workflows()
        if claude_extraction_mode not in {"assistant_text", "downloaded_file"}:
            raise RuntimeError(
                "Claude extraction requires one launcher-classified output type"
            )
        if (
            claude_launcher_revision is None
            or re.fullmatch(r"[0-9a-f]{64}", claude_launcher_revision) is None
        ):
            raise RuntimeError(
                "Claude extraction requires a canonical launcher snapshot revision"
            )
        expected_count = "1" if claude_extraction_mode == "downloaded_file" else "0"
        common = (
            f"The completion monitor reported COMPLETE for monitor_id={monitor_id}. The canonical "
            f"Hands launcher snapshot selected extraction_mode={claude_extraction_mode} with "
            f"launcher_snapshot_sha256={claude_launcher_revision}. Execute one frozen Claude "
            f"extraction transaction on {display} with drive_chat only. Do not read any file, "
            "runbook, or YAML. For click, pass only the exact element key mapped by the immediately "
            f"preceding fresh observation; do not copy or pass an opaque ref. Every drive_chat call "
            f"must include display={display}; omission is a terminal card violation.\n"
            f"1. drive_chat display={display}, action=observe, scope=base exactly once; require "
            "current_url to contain /chat/, require continue_button absent, and require none of "
            "these mapped exception elements: send_blocked_previous_message, "
            "send_blocked_previous_message_curly, network_connection_alert, "
            "send_blocked_caution_banner, claude_capacity_alert, claude_capacity_alert_pro, "
            "claude_session_limit_alert, claude_hit_limit_alert, claude_not_working_alert, or "
            "claude_chat_length_limit_alert. In this same fresh observation require exactly "
            f"{expected_count} generated_artifact_controls_section, exactly {expected_count} "
            "generated_artifact_view_button, and exactly "
            f"{expected_count} generated_artifact_download_button. Any different, partial, or "
            "duplicate count is classify-to-execute drift: return a terminal first-mismatch stop "
            "report before mutation.\n"
        )
        if claude_extraction_mode == "downloaded_file":
            branch = (
                f"2. drive_chat display={display}, action=click, "
                "element=generated_artifact_download_button exactly once; then make exactly one "
                f"fresh drive_chat display={display}, action=observe, scope=base. Require the same "
                "/chat/ URL, continue_button absent, and no mapped exception. Stop all UI calls. "
                "Do not click generated_artifact_view_button, any artifact Copy control, or any "
                "generic artifact control. Do not read the clipboard.\n"
            )
        else:
            branch = (
                f"2. drive_chat display={display}, action=key, key=ctrl+End; then drive_chat "
                f"display={display}, action=observe, scope=base; require the same /chat/ URL, "
                "continue_button absent, no mapped exception, and exactly one mapped "
                "message_actions_button owned by the current_response_article. drive_chat "
                f"display={display}, action=hover, element=message_actions_button exactly once; "
                f"drive_chat display={display}, action=observe, scope=base; require the same URL "
                "and exception conditions, at least one mapped copy_button named Copy, and exactly "
                "one fresh copy_button target marked by the YAML last_by_y selection. drive_chat "
                f"display={display}, action=click, element=copy_button exactly once; drive_chat "
                f"display={display}, action=observe, scope=base; require the same URL and exception "
                f"conditions. drive_chat display={display}, action=read_clipboard, "
                f"output_file={response_file}; require a new non-empty response file. Stop all UI "
                "calls.\n"
            )
        receipt = (
            "Only after the exact branch passes, return exactly one Claude extraction receipt "
            "with one line per field in field=value form: extraction_mode; "
            "classification_revision; generated_artifact_controls_section_count; "
            "generated_artifact_view_button_count; generated_artifact_download_button_count; "
            "artifact_download_click_count; artifact_view_click_count; artifact_copy_click_count; "
            "generic_artifact_click_count; assistant_copy_click_count; clipboard_read_count; "
            "post_download_observe_count. classification_revision must be the 64-hex revision of "
            "step 1. downloaded_file must also include post_download_revision as the 64-hex "
            "revision after its one click.\n"
            "At the first missing or ambiguous element, refusal, failed postcondition, or unexpected "
            "state, return a first-mismatch stop report without any success receipt field and stop. "
            "Do not navigate, attach, paste, send, retry, recover, poll, click Continue, make a "
            "second Download or Copy attempt, or cross to the other extraction branch."
        )
        return common + branch + receipt
    if platform == "gemini":
        if completed_before_stop_source_sha256 is None:
            completion_basis = (
                f"The completion monitor reported COMPLETE for monitor_id={monitor_id}. "
            )
            completion_requirements = "and "
            receipt_requirements = ""
        else:
            completion_basis = (
                "This separately authorized Gemini extraction is based on a terminal "
                "completed-before-Stop send receipt with "
                f"source_response_json_sha256={completed_before_stop_source_sha256}. "
                "No completion monitor reported COMPLETE and no observed Stop transition is "
                "claimed. "
            )
            completion_requirements = "require stop_button absent, and "
            receipt_requirements = (
                " Return completion_basis=completed_before_stop and "
                f"source_response_json_sha256={completed_before_stop_source_sha256} in the "
                "receipt."
            )
        if output_type == "research_report":
            _require_extraction_steps(
                "gemini",
                "research_report",
                (
                    ("click", "share_export", "last", None),
                    ("copy_element", "copy_content_item", "last", None),
                    ("read_clipboard", None, "last", "response_complete"),
                ),
            )
            return (
                completion_basis
                + "Execute one frozen Gemini Deep Research report extraction transaction on "
                f"{display} with drive_chat only. Do not read any file, runbook, or YAML. "
                "The signed Deep Research send-phase card registered "
                "output_type=research_report with the completion route. Execute exactly this "
                "YAML-owned sequence, using only an element key from the immediately preceding "
                "fresh observation:\n"
                "1. observe scope=app_root_snapshot; require current_url on gemini.google.com "
                "matching /app/<id> or /u/<digit>/app/<id>, require stop_button absent, require "
                "deep_think_interim_ack_placeholder absent, and require exactly one mapped "
                "share_export named Share & Export with role push button and states showing and "
                "enabled.\n"
                "2. click element=share_export exactly once; observe scope=app_root_snapshot; "
                "require the same URL and terminal conditions and exactly one mapped "
                "copy_content_item named Copy with role menu item and states showing and enabled.\n"
                "3. click element=copy_content_item exactly once; observe "
                "scope=app_root_snapshot; require the same URL and terminal conditions.\n"
                f"4. read_clipboard with output_file={response_file}. Require that drive_chat "
                "created a new response file larger than 89 bytes whose content is not the exact "
                "Gemini completion notice. Then stop all UI calls. Return exactly one field "
                "output_type=research_report and the byte count and SHA-256."
                f"{receipt_requirements}\n"
                "At the first missing or ambiguous element, refusal, failed postcondition, or "
                "unexpected state, return the first-mismatch stop report and stop. Do not navigate, "
                "attach, paste, send, retry, recover, poll, use copy_button, or make a second "
                "Share & Export or Copy attempt."
            )
        if output_type != "assistant_text":
            raise RuntimeError(
                f"Gemini extraction output type is unsupported: {output_type!r}"
            )
        return (
            completion_basis
            + "Execute one "
            f"frozen Gemini extraction transaction on {display} with drive_chat only. Do not read "
            "any file, runbook, or YAML. For click, pass only the exact element key mapped by the "
            "immediately preceding fresh observation; do not copy or pass an opaque ref. Execute "
            "exactly this sequence:\n"
            "1. observe scope=base; require current_url on gemini.google.com matching /app/<id> or "
            f"/u/<digit>/app/<id>, {completion_requirements}require "
            "deep_think_interim_ack_placeholder absent.\n"
            "2. key ctrl+End; observe scope=base; require the "
            "same URL condition, deep_think_interim_ack_placeholder absent, at least "
            "one mapped copy_button, and exactly one fresh copy_button target marked by the YAML "
            "last_by_y selection.\n"
            "3. click element=copy_button; observe scope=base; require "
            "the same URL condition and deep_think_interim_ack_placeholder absent.\n"
            f"4. read_clipboard with output_file={response_file}. Require that drive_chat created a "
            "new non-empty response file and return its byte count and SHA-256. Then stop all UI "
            f"calls.{receipt_requirements}\n"
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
        if completed_before_stop_source_sha256 is None:
            completion_basis = (
                f"The completion monitor reported COMPLETE for monitor_id={monitor_id}. "
            )
            receipt_requirements = ""
        else:
            completion_basis = (
                "This separately authorized Perplexity extraction is based on a terminal "
                "completed-before-Stop send receipt with "
                f"source_response_json_sha256={completed_before_stop_source_sha256}. "
                "No completion monitor reported COMPLETE and no observed Stop transition is "
                "claimed. "
            )
            receipt_requirements = (
                " Return completion_basis=completed_before_stop and "
                f"source_response_json_sha256={completed_before_stop_source_sha256} in the "
                "receipt."
            )
        _require_extraction_steps(
            "perplexity",
            "research_report",
            (
                ("open_panel", "artifact_options", "last", None),
                ("open_panel", "artifact_open_new_tab", "last", None),
                ("copy_element", "copy_contents_button", "last", None),
                ("read_clipboard", None, "last", "response_complete"),
            ),
        )
        return (
            completion_basis
            + "Execute one "
            f"frozen Perplexity extraction transaction on {display} with drive_chat only. Do not "
            "read any file, runbook, or YAML. Pass only an exact element key from the immediately "
            "preceding fresh observation; do not require a singleton when that observation marks "
            "exactly one target with the YAML-owned last_by_y selection. "
            "Do not copy or pass an opaque ref. Execute exactly this sequence:\n"
            "1. observe scope=base; require current_url to begin "
            "https://www.perplexity.ai/search/, require stop_button absent, and require exactly one "
            "mapped research_report_open with a nonempty dynamic name and exactly one mapped "
            "artifact_options named Artifact options.\n"
            "2. operate element=artifact_options exactly once; require "
            "performed_primitive=mapped_pointer_activate; observe scope=base; require the "
            "same answer-thread URL, stop_button absent, and exactly one mapped artifact_open_new_tab "
            "named Open in new tab with role menu item and states showing and enabled.\n"
            "3. click element=artifact_open_new_tab exactly once; observe scope=base; require current_url "
            "to match https://www.perplexity.ai/computer/a/<non-empty-id>, stop_button absent, and exactly "
            "one mapped copy_contents_button named Copy contents with role push button and states showing "
            "and enabled.\n"
            "4. click element=copy_contents_button exactly once; observe scope=base; require the same "
            "/computer/a/<non-empty-id> URL and stop_button absent.\n"
            f"5. read_clipboard with output_file={response_file}. Require that drive_chat created a "
            "new non-empty research report file and return its byte count and SHA-256. Then stop "
            "all UI calls. Only after all five steps pass, return the exact lines "
            "report_options_open_count=1, standalone_report_open_count=1, and report_copy_count=1."
            f"{receipt_requirements}\n"
            "At the first missing or ambiguous element, refusal, failed postcondition, or unexpected "
            "state, return the first-mismatch stop report without any success cardinality field and "
            "stop. Do not navigate, attach, paste, "
            "send, retry, recover, poll, expand or scroll the report, use Download or Markdown, "
            "or make a second "
            "Copy attempt."
        )
    if platform != "chatgpt":
        raise RuntimeError(f"{platform} has no qualified frozen extraction sequence")
    return (
        f"The completion monitor reported COMPLETE for monitor_id={monitor_id}. Execute one frozen "
        f"ChatGPT extraction transaction on {display} with drive_chat only. Do not read any file, "
        "runbook, or YAML. For click, pass only the exact element key mapped by the immediately "
        "preceding fresh observation; do not copy or pass an opaque ref. Execute exactly: observe "
        "scope=base; key ctrl+End; observe scope=base; click element=copy_button; observe scope=base; "
        "read_clipboard with "
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
    request_must_be_new: bool = False,
) -> tuple[Path, Path, Path, str]:
    request_path = root / "request.json"
    headers_path = root / "response.headers"
    response_path = root / "worker_response.json"
    if request_must_be_new:
        _create_request(request_path, request_text)
    else:
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


def _is_completed_before_stop_receipt(receipt: str) -> bool:
    for line in receipt.splitlines():
        if not line.strip():
            continue
        headline = line.strip(" \t#*_`").lower()
        normalized_headline = re.sub(r"[^a-z0-9]+", " ", headline).strip()
        if normalized_headline.startswith("completed before stop send receipt"):
            return True
    return False


def _claude_extraction_mode(
    receipt: str,
    expected_mode: str | None = None,
) -> str:
    def value(field: str) -> str:
        matches = re.findall(
            rf"(?m)^[ \t]*{re.escape(field)}[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$",
            receipt,
        )
        if len(matches) != 1:
            raise RuntimeError(
                f"Claude extraction receipt has {len(matches)} exact {field} fields"
            )
        return matches[0]

    mode = value("extraction_mode")
    if mode not in {"assistant_text", "downloaded_file"}:
        raise RuntimeError("Claude extraction receipt has an invalid extraction_mode")
    if expected_mode is not None and mode != expected_mode:
        raise RuntimeError(
            "Claude extraction receipt crossed the launcher-classified branch"
        )
    classification_revision = value("classification_revision")
    if re.fullmatch(r"[0-9a-f]{64}", classification_revision) is None:
        raise RuntimeError(
            "Claude extraction receipt has an invalid classification_revision"
        )
    expected = {
        "assistant_text": {
            "generated_artifact_controls_section_count": "0",
            "generated_artifact_view_button_count": "0",
            "generated_artifact_download_button_count": "0",
            "artifact_download_click_count": "0",
            "artifact_view_click_count": "0",
            "artifact_copy_click_count": "0",
            "generic_artifact_click_count": "0",
            "assistant_copy_click_count": "1",
            "clipboard_read_count": "1",
            "post_download_observe_count": "0",
        },
        "downloaded_file": {
            "generated_artifact_controls_section_count": "1",
            "generated_artifact_view_button_count": "1",
            "generated_artifact_download_button_count": "1",
            "artifact_download_click_count": "1",
            "artifact_view_click_count": "0",
            "artifact_copy_click_count": "0",
            "generic_artifact_click_count": "0",
            "assistant_copy_click_count": "0",
            "clipboard_read_count": "0",
            "post_download_observe_count": "1",
        },
    }[mode]
    invalid = [
        field
        for field, expected_value in expected.items()
        if value(field) != expected_value
    ]
    if invalid:
        raise RuntimeError(
            f"Claude extraction receipt has invalid branch cardinality: {invalid}"
        )
    post_download_revisions = re.findall(
        r"(?m)^[ \t]*post_download_revision[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$",
        receipt,
    )
    if mode == "downloaded_file":
        if (
            len(post_download_revisions) != 1
            or re.fullmatch(r"[0-9a-f]{64}", post_download_revisions[0]) is None
        ):
            raise RuntimeError(
                "Claude downloaded-file receipt lacks one fresh post-download revision"
            )
    elif post_download_revisions:
        raise RuntimeError(
            "Claude assistant-text receipt contains downloaded-file provenance"
        )
    return mode


def _receipt_field_matches(receipt: str, field: str, expected: str) -> bool:
    separator = r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
    return re.search(
        rf"(?im)\b{re.escape(field)}\b{separator}{re.escape(expected)}"
        rf"(?=$|[\s*`|,;)])",
        receipt,
    ) is not None


def _grok_recovery_count_map(receipt: str, field: str) -> dict[str, int]:
    matches = re.findall(
        rf"(?im)^\s*(?:[-*]\s*)?`?{re.escape(field)}`?\s*[:=]\s*"
        r"`?(\{[^\n`]+\})`?\s*$",
        receipt,
    )
    if len(matches) != 1:
        raise RuntimeError(
            f"Grok pre-send recovery receipt has {len(matches)} exact {field} maps"
        )
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Grok pre-send recovery receipt has invalid JSON in {field}"
        ) from exc
    if (
        not isinstance(value, dict)
        or not all(isinstance(key, str) for key in value)
        or not all(
            isinstance(count, int) and not isinstance(count, bool)
            for count in value.values()
        )
    ):
        raise RuntimeError(
            f"Grok pre-send recovery receipt has invalid counts in {field}"
        )
    return value


def _grok_recovery_observe_count(receipt: str) -> int:
    matches = re.findall(
        r"(?im)^\s*(?:[-*]\s*)?`?observe_count`?\s*[:=]\s*`?([0-9]+)`?\s*$",
        receipt,
    )
    if len(matches) != 1:
        raise RuntimeError(
            "Grok pre-send recovery receipt must have one exact observe_count"
        )
    return int(matches[0])


def _gemini_terminal_receipt_field(receipt: str, field: str) -> str:
    matches = re.findall(
        rf"(?m)^- {re.escape(field)}: `([^`]+)`$",
        receipt,
    )
    if len(matches) != 1:
        raise RuntimeError(
            f"Gemini terminal receipt has {len(matches)} exact {field} fields"
        )
    return matches[0]


def _clipboard_affecting_request(arguments: object) -> bool:
    if not isinstance(arguments, dict):
        return False
    action = arguments.get("action")
    element = arguments.get("element")
    if action in {"click", "operate", "activate"} and isinstance(element, str):
        return "copy" in element.lower()
    key = arguments.get("key")
    return action == "key" and isinstance(key, str) and key.lower() in {
        "ctrl+c",
        "ctrl+insert",
    }


def _clipboard_affecting_result(inner: object) -> bool:
    if not isinstance(inner, dict):
        return False
    action = inner.get("action")
    result = inner.get("result")
    element = result.get("element") if isinstance(result, dict) else None
    element_key = element.get("element") if isinstance(element, dict) else None
    if action in {"click", "operate", "activate"} and isinstance(element_key, str):
        return "copy" in element_key.lower()
    key = result.get("key") if isinstance(result, dict) else None
    return action == "key" and isinstance(key, str) and key.lower() in {
        "ctrl+c",
        "ctrl+insert",
    }


def _validate_gemini_terminal_clipboard_source(
    terminal_receipt: Path,
    expected_terminal_sha256: str,
    copy_result_json: Path,
    expected_copy_result_sha256: str,
    display: str,
    new_seat_id: str,
) -> dict[str, object]:
    for label, value in (
        ("source terminal receipt SHA-256", expected_terminal_sha256),
        ("source Copy result SHA-256", expected_copy_result_sha256),
    ):
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise RuntimeError(f"{label} must be exactly 64 lowercase hex characters")
    if _sha256(terminal_receipt) != expected_terminal_sha256:
        raise RuntimeError("source terminal receipt SHA-256 mismatch")
    if _sha256(copy_result_json) != expected_copy_result_sha256:
        raise RuntimeError("source Copy result SHA-256 mismatch")

    receipt = terminal_receipt.read_text(encoding="utf-8")
    source_seat_id = _identity(
        _gemini_terminal_receipt_field(receipt, "seat_id"),
        "source seat id",
    )
    source_turn_id = _identity(
        _gemini_terminal_receipt_field(receipt, "turn_id"),
        "source turn id",
    )
    source_event_id = _identity(
        _gemini_terminal_receipt_field(receipt, "event_id"),
        "source event id",
    )
    if new_seat_id == source_seat_id:
        raise RuntimeError("terminal clipboard extraction requires a new seat identity")
    expected_receipt_values = {
        "display": display,
        "terminal_result": "supervisor first-error halt",
        "captured_drive_chat_calls": "51",
        "round_51_result_sha256": expected_copy_result_sha256,
        "start_research_call_count": "0",
        "read_clipboard_call_count": "0",
        "further_calls_after_round_51": "0",
    }
    invalid_receipt_values = [
        field
        for field, expected in expected_receipt_values.items()
        if _gemini_terminal_receipt_field(receipt, field) != expected
    ]
    if invalid_receipt_values:
        raise RuntimeError(
            "Gemini terminal receipt has invalid source fields: "
            f"{invalid_receipt_values}"
        )
    if (
        "- second_unauthorized_call: round `51`, `click copy_button`, performed `true`"
        not in receipt
        or "This identity is spent and must never be retried or recovered." not in receipt
    ):
        raise RuntimeError("Gemini terminal receipt lacks the exact terminal Copy evidence")

    try:
        wrapper = json.loads(copy_result_json.read_text(encoding="utf-8"))
        inner = json.loads(wrapper["result"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("source Copy result is not a valid captured exchange") from exc
    if not isinstance(wrapper, dict) or not isinstance(inner, dict):
        raise RuntimeError("source Copy result capture must contain two JSON objects")
    source_round = wrapper.get("tool_round")
    expected_wrapper = {
        "schema": "taey.drive_chat.exchange.v1",
        "proxy_namespace": "taey-worker",
        "seat_id": source_seat_id,
        "turn_id": source_turn_id,
        "event_id": source_event_id,
        "tool_round": 51,
        "tool_ok": True,
        "returned": True,
    }
    invalid_wrapper = [
        field for field, expected in expected_wrapper.items()
        if wrapper.get(field) != expected
    ]
    result = inner.get("result")
    element = result.get("element") if isinstance(result, dict) else None
    ui_sequence = inner.get("ui_sequence")
    if invalid_wrapper or not isinstance(result, dict) or not isinstance(element, dict):
        raise RuntimeError(
            f"source Copy result has invalid capture identity: {invalid_wrapper}"
        )
    if (
        inner.get("ok") is not True
        or inner.get("platform") != "gemini"
        or inner.get("display") != display
        or inner.get("action") != "click"
        or inner.get("error") is not None
        or result.get("performed") is not True
        or result.get("performed_primitive") != "click"
        or element.get("element") != "copy_button"
        or element.get("name") != "Copy"
        or element.get("role") != "push button"
        or not isinstance(ui_sequence, dict)
        or ui_sequence.get("state") != "mutation_complete"
    ):
        raise RuntimeError("source Copy result does not prove one successful Gemini Copy")

    call_dir = copy_result_json.parent
    turn_dir = call_dir.parent
    event_dir = turn_dir.parent
    seat_root = event_dir.parent
    proxy_root = seat_root.parent
    capture_root = proxy_root.parent
    if (
        not call_dir.name.startswith(f"{source_round:04d}-")
        or turn_dir.name != source_turn_id
        or event_dir.name != source_event_id
        or seat_root.name != source_seat_id
        or proxy_root.name != wrapper["proxy_namespace"]
        or capture_root.name != "drive_chat_captures"
    ):
        raise RuntimeError("source Copy result path does not match its capture identity")
    source_request = call_dir / "request.json"
    if not source_request.is_file():
        raise RuntimeError("source Copy capture has no paired request")
    source_request_sha256 = _gemini_terminal_receipt_field(
        receipt, "round_51_request_sha256"
    )
    if _sha256(source_request) != source_request_sha256:
        raise RuntimeError("source Copy request SHA-256 mismatch")
    try:
        request_payload = json.loads(source_request.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("source Copy request is not valid JSON") from exc
    if (
        request_payload.get("seat_id") != source_seat_id
        or request_payload.get("turn_id") != source_turn_id
        or request_payload.get("event_id") != source_event_id
        or request_payload.get("tool_round") != 51
        or request_payload.get("arguments")
        != {"action": "click", "display": display, "element": "copy_button"}
    ):
        raise RuntimeError("source Copy request does not match round 51 exactly")

    copy_completed_ns = copy_result_json.stat().st_mtime_ns
    capture_search_root = capture_root.parent
    capture_roots = {capture_root}
    capture_roots.update(
        path.resolve(strict=True)
        for path in capture_search_root.rglob("drive_chat_captures")
        if path.is_dir()
    )
    later_clipboard_events: list[str] = []
    uncertain_records: list[str] = []
    for scanned_root in sorted(capture_roots):
        for candidate in scanned_root.rglob("request.json"):
            candidate = candidate.resolve(strict=True)
            if candidate == source_request or candidate.stat().st_mtime_ns <= copy_completed_ns:
                continue
            try:
                candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                uncertain_records.append(str(candidate))
                continue
            if _clipboard_affecting_request(candidate_payload.get("arguments")):
                later_clipboard_events.append(str(candidate))
        for candidate in scanned_root.rglob("result.json"):
            candidate = candidate.resolve(strict=True)
            if candidate == copy_result_json or candidate.stat().st_mtime_ns <= copy_completed_ns:
                continue
            try:
                candidate_wrapper = json.loads(candidate.read_text(encoding="utf-8"))
                candidate_inner = json.loads(candidate_wrapper["result"])
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                uncertain_records.append(str(candidate))
                continue
            if _clipboard_affecting_result(candidate_inner):
                later_clipboard_events.append(str(candidate))
    certainty = (
        "captured_proven"
        if not later_clipboard_events and not uncertain_records
        else "uncertain"
    )
    return {
        "source_seat_id": source_seat_id,
        "source_turn_id": source_turn_id,
        "source_event_id": source_event_id,
        "source_copy_tool_round": source_round,
        "source_terminal_receipt_sha256": expected_terminal_sha256,
        "source_copy_result_json_sha256": expected_copy_result_sha256,
        "capture_root": capture_root,
        "proxy_namespace": wrapper["proxy_namespace"],
        "clipboard_source_certainty": certainty,
        "provider_output_proven": certainty == "captured_proven",
        "global_capture_roots_scanned": tuple(
            str(path) for path in sorted(capture_roots)
        ),
        "later_clipboard_affecting_records": tuple(sorted(later_clipboard_events)),
        "uncertain_capture_records": tuple(sorted(uncertain_records)),
    }


def _gemini_terminal_clipboard_only_content(
    display: str,
    response_file: Path,
    source: dict[str, object],
) -> str:
    return (
        f"Execute one source-bound terminal Gemini clipboard materialization on {display}. "
        "The prior terminal turn already performed the one Copy action; this turn must not "
        "touch the UI. Call drive_chat exactly once with "
        f"display={display}, action=read_clipboard, output_file={response_file}. Do not call "
        "observe, scroll_to_bottom, click, focus, activate, hover, operate, key, type, paste, "
        "navigate, focus_dialog, abort, or any other tool or action before or after that one "
        "read_clipboard call. Do not retry if it is refused or empty. The source proof is "
        f"source_terminal_receipt_sha256={source['source_terminal_receipt_sha256']}, "
        f"source_copy_result_json_sha256={source['source_copy_result_json_sha256']}, "
        f"source_seat_id={source['source_seat_id']}, and "
        f"source_copy_tool_round={source['source_copy_tool_round']}. After the one successful "
        "call, return a Gemini terminal clipboard-only receipt with exactly these fields: "
        "platform=gemini; "
        f"display={display}; "
        f"source_terminal_receipt_sha256={source['source_terminal_receipt_sha256']}; "
        f"source_copy_result_json_sha256={source['source_copy_result_json_sha256']}; "
        f"source_seat_id={source['source_seat_id']}; "
        f"source_copy_tool_round={source['source_copy_tool_round']}; "
        f"clipboard_source_certainty={source['clipboard_source_certainty']}; "
        f"provider_output_proven={str(source['provider_output_proven']).lower()}; "
        "clipboard_read_count=1; observe_count=0; scroll_count=0; click_count=0; "
        "key_count=0; navigation_count=0; ui_mutation_count=0; other_tool_call_count=0; "
        f"output_file={response_file}; byte_count=<exact integer>; "
        "response_sha256=<exact 64-hex SHA-256>. Stop immediately."
    )


def _validate_gemini_terminal_clipboard_only_receipt(
    receipt: str,
    display: str,
    response_file: Path,
    source: dict[str, object],
) -> None:
    if "gemini terminal clipboard-only receipt" not in receipt.lower():
        raise RuntimeError("Gemini clipboard-only response has no exact receipt heading")
    expected = {
        "platform": "gemini",
        "display": display,
        "source_terminal_receipt_sha256": str(
            source["source_terminal_receipt_sha256"]
        ),
        "source_copy_result_json_sha256": str(
            source["source_copy_result_json_sha256"]
        ),
        "source_seat_id": str(source["source_seat_id"]),
        "source_copy_tool_round": str(source["source_copy_tool_round"]),
        "clipboard_source_certainty": str(source["clipboard_source_certainty"]),
        "provider_output_proven": str(source["provider_output_proven"]).lower(),
        "clipboard_read_count": "1",
        "observe_count": "0",
        "scroll_count": "0",
        "click_count": "0",
        "key_count": "0",
        "navigation_count": "0",
        "ui_mutation_count": "0",
        "other_tool_call_count": "0",
        "output_file": str(response_file),
        "byte_count": str(response_file.stat().st_size),
        "response_sha256": _sha256(response_file),
    }
    invalid = [
        field for field, value in expected.items()
        if not _receipt_field_matches(receipt, field, value)
    ]
    if invalid:
        raise RuntimeError(
            f"Gemini clipboard-only response has invalid receipt fields: {invalid}"
        )


def _validate_gemini_terminal_clipboard_only_capture(
    seat_id: str,
    event_id: str,
    display: str,
    response_file: Path,
    source: dict[str, object],
) -> None:
    capture_root = source.get("capture_root")
    proxy_namespace = source.get("proxy_namespace")
    if not isinstance(capture_root, Path) or not isinstance(proxy_namespace, str):
        raise RuntimeError("Gemini clipboard-only capture root is invalid")
    seat_root = capture_root / proxy_namespace / seat_id
    requests = sorted(seat_root.rglob("request.json")) if seat_root.is_dir() else []
    results = sorted(seat_root.rglob("result.json")) if seat_root.is_dir() else []
    if len(requests) != 1 or len(results) != 1:
        raise RuntimeError(
            "Gemini clipboard-only turn must capture exactly one request and one result"
        )
    try:
        request = json.loads(requests[0].read_text(encoding="utf-8"))
        wrapper = json.loads(results[0].read_text(encoding="utf-8"))
        inner = json.loads(wrapper["result"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Gemini clipboard-only capture is invalid") from exc
    expected_arguments = {
        "action": "read_clipboard",
        "display": display,
        "output_file": str(response_file),
    }
    result = inner.get("result") if isinstance(inner, dict) else None
    if (
        request.get("seat_id") != seat_id
        or request.get("event_id") != event_id
        or request.get("tool_round") != 1
        or request.get("arguments") != expected_arguments
        or wrapper.get("seat_id") != seat_id
        or wrapper.get("event_id") != event_id
        or wrapper.get("tool_round") != 1
        or wrapper.get("tool_ok") is not True
        or inner.get("ok") is not True
        or inner.get("platform") != "gemini"
        or inner.get("display") != display
        or inner.get("action") != "read-clipboard"
        or not isinstance(result, dict)
        or result.get("output_file") != str(response_file)
        or result.get("bytes") != response_file.stat().st_size
        or result.get("sha256") != _sha256(response_file)
    ):
        raise RuntimeError("Gemini clipboard-only capture does not prove one exact read")


def _validate_perplexity_diagnostic_receipt(
    receipt: str,
    label: str,
    required_fields: tuple[str, ...],
    exact_values: dict[str, str],
    numeric_fields: tuple[str, ...],
) -> None:
    lowered_receipt = receipt.lower()
    missing_fields = [field for field in required_fields if field not in lowered_receipt]
    if missing_fields:
        raise RuntimeError(f"{label} response is missing receipt fields: {missing_fields}")
    invalid_values = [
        field
        for field, expected in exact_values.items()
        if not _receipt_field_matches(receipt, field, expected)
    ]
    if invalid_values:
        raise RuntimeError(f"{label} response has invalid values: {invalid_values}")
    invalid_revisions = [
        field
        for field in ("pre_observation_revision", "post_observation_revision")
        if re.search(
            rf"(?im)\b{field}\b"
            r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*[0-9a-f]{64}\b",
            receipt,
        )
        is None
    ]
    if invalid_revisions:
        raise RuntimeError(f"{label} response has invalid revisions: {invalid_revisions}")
    invalid_counts = [
        field
        for field in numeric_fields
        if re.search(
            rf"(?im)\b{field}\b"
            r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*\d+\b",
            receipt,
        )
        is None
    ]
    if invalid_counts:
        raise RuntimeError(f"{label} response has invalid counts: {invalid_counts}")


def _validate_perplexity_artifacts_diagnostic_receipt(
    receipt: str,
    display: str,
    source_terminal_identity: str,
    thread_url: str,
) -> None:
    required_fields = (
        "perplexity artifacts pane diagnostic receipt",
        "platform",
        "display",
        "source_terminal_identity",
        "thread_url",
        "pre_observation_revision",
        "pre_report_open_count",
        "pre_artifact_options_count",
        "pre_artifacts_one_count",
        "pre_copy_count",
        "pre_helpful_count",
        "pre_not_helpful_count",
        "clicked_element",
        "click_result",
        "post_observation_revision",
        "post_report_open_count",
        "post_artifact_options_count",
        "post_artifacts_one_count",
        "post_copy_contents_count",
        "post_copy_count",
        "observe_count",
        "click_count",
        "copied",
        "extracted",
        "sent",
        "other_mutation_count",
    )
    exact_values = {
        "platform": "perplexity",
        "display": display,
        "source_terminal_identity": source_terminal_identity,
        "thread_url": thread_url,
        "pre_report_open_count": "0",
        "pre_artifact_options_count": "0",
        "pre_artifacts_one_count": "1",
        "pre_copy_count": "1",
        "pre_helpful_count": "1",
        "pre_not_helpful_count": "1",
        "clicked_element": "artifacts_one_button",
        "observe_count": "2",
        "click_count": "1",
        "copied": "false",
        "extracted": "false",
        "sent": "false",
        "other_mutation_count": "0",
    }
    _validate_perplexity_diagnostic_receipt(
        receipt,
        "Perplexity Artifacts diagnostic",
        required_fields,
        exact_values,
        (
            "post_report_open_count",
            "post_artifact_options_count",
            "post_artifacts_one_count",
            "post_copy_contents_count",
            "post_copy_count",
        ),
    )


def _validate_perplexity_report_card_diagnostic_receipt(
    receipt: str,
    display: str,
    source_diagnostic_identity: str,
    thread_url: str,
) -> None:
    required_fields = (
        "perplexity report card diagnostic receipt",
        "platform",
        "display",
        "source_diagnostic_identity",
        "thread_url",
        "pre_observation_revision",
        "pre_stop_count",
        "pre_artifacts_pane_toggle_count",
        "pre_artifact_report_entry_count",
        "pre_artifacts_pane_download_count",
        "pre_report_entry_name",
        "clicked_element",
        "click_performed",
        "performed_primitive",
        "post_observation_revision",
        "post_current_url",
        "post_stop_count",
        "post_artifacts_pane_toggle_count",
        "post_artifact_report_entry_count",
        "post_artifacts_pane_download_count",
        "post_research_report_open_count",
        "post_artifact_options_count",
        "post_copy_contents_count",
        "observe_count",
        "click_count",
        "copied",
        "clipboard_read",
        "extracted",
        "sent",
        "other_mutation_count",
    )
    exact_values = {
        "platform": "perplexity",
        "display": display,
        "source_diagnostic_identity": source_diagnostic_identity,
        "thread_url": thread_url,
        "pre_stop_count": "0",
        "pre_artifacts_pane_toggle_count": "1",
        "pre_artifact_report_entry_count": "1",
        "pre_artifacts_pane_download_count": "1",
        "clicked_element": "artifact_report_entry",
        "click_performed": "true",
        "performed_primitive": "click",
        "observe_count": "2",
        "click_count": "1",
        "copied": "false",
        "clipboard_read": "false",
        "extracted": "false",
        "sent": "false",
        "other_mutation_count": "0",
    }
    _validate_perplexity_diagnostic_receipt(
        receipt,
        "Perplexity report-card diagnostic",
        required_fields,
        exact_values,
        (
            "post_stop_count",
            "post_artifacts_pane_toggle_count",
            "post_artifact_report_entry_count",
            "post_artifacts_pane_download_count",
            "post_research_report_open_count",
            "post_artifact_options_count",
            "post_copy_contents_count",
        ),
    )
    if re.search(
        r"(?im)\bpre_report_entry_name\b"
        r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
        r"(?=[^\r\n]*[A-Za-z0-9])[^\r\n]+",
        receipt,
    ) is None:
        raise RuntimeError(
            "Perplexity report-card diagnostic response has an empty report-entry name"
        )
    if re.search(
        r"(?im)\bpost_current_url\b"
        r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*https://www\.perplexity\.ai/\S+",
        receipt,
    ) is None:
        raise RuntimeError(
            "Perplexity report-card diagnostic response has an invalid post URL"
        )


def _validate_perplexity_report_card_extraction_receipt(
    receipt: str,
    display: str,
    source_diagnostic_identity: str,
    thread_url: str,
    response_file: Path,
) -> None:
    fields = (
        "perplexity report card extraction receipt", "platform", "display",
        "source_diagnostic_identity", "thread_url", "initial_observation_revision",
        "initial_current_url", "navigation_count", "post_navigation_observe_count",
        "pre_observation_revision", "pre_current_url", "pre_stop_count",
        "pre_artifacts_pane_toggle_count", "pre_artifact_report_entry_count",
        "pre_artifacts_pane_download_count", "pre_report_entry_name",
        "clicked_report_entry", "report_entry_click_performed",
        "report_entry_performed_primitive", "report_surface_observation_revision",
        "report_surface_url", "report_surface_stop_count",
        "report_surface_copy_contents_count", "clicked_copy_contents",
        "copy_click_performed", "copy_performed_primitive",
        "post_copy_observation_revision", "post_copy_url", "post_copy_stop_count",
        "post_copy_contents_count", "output_file", "byte_count", "response_sha256",
        "initial_observe_count", "report_entry_click_count",
        "report_surface_observe_count", "report_copy_click_count",
        "post_copy_observe_count", "clipboard_read_count", "total_click_count",
        "other_mutation_count", "extracted", "sent", "regenerated", "retried",
    )
    missing = [field for field in fields if field not in receipt.lower()]
    if missing:
        raise RuntimeError(
            f"Perplexity report-card extraction response is missing fields: {missing}"
        )
    if not response_file.is_file() or response_file.stat().st_size == 0:
        raise RuntimeError("Perplexity report-card extraction file is missing or empty")
    exact = {
        "platform": "perplexity", "display": display,
        "source_diagnostic_identity": source_diagnostic_identity,
        "thread_url": thread_url, "pre_current_url": thread_url,
        "pre_stop_count": "0", "pre_artifacts_pane_toggle_count": "1",
        "pre_artifact_report_entry_count": "1",
        "pre_artifacts_pane_download_count": "1",
        "clicked_report_entry": "artifact_report_entry",
        "report_entry_click_performed": "true",
        "report_entry_performed_primitive": "click",
        "report_surface_stop_count": "0",
        "report_surface_copy_contents_count": "1",
        "clicked_copy_contents": "copy_contents_button",
        "copy_click_performed": "true", "copy_performed_primitive": "click",
        "post_copy_stop_count": "0", "post_copy_contents_count": "1",
        "output_file": str(response_file),
        "byte_count": str(response_file.stat().st_size),
        "response_sha256": _sha256(response_file),
        "initial_observe_count": "1", "report_entry_click_count": "1",
        "report_surface_observe_count": "1", "report_copy_click_count": "1",
        "post_copy_observe_count": "1", "clipboard_read_count": "1",
        "total_click_count": "2", "other_mutation_count": "0",
        "extracted": "true", "sent": "false", "regenerated": "false",
        "retried": "false",
    }
    invalid = [
        field for field, expected in exact.items()
        if not _receipt_field_matches(receipt, field, expected)
    ]
    if invalid:
        raise RuntimeError(
            f"Perplexity report-card extraction response has invalid values: {invalid}"
        )
    revisions = (
        "initial_observation_revision", "pre_observation_revision",
        "report_surface_observation_revision", "post_copy_observation_revision",
    )
    invalid_revisions = [
        field for field in revisions
        if re.search(
            rf"(?im)\b{field}\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*[0-9a-f]{{64}}\b",
            receipt,
        ) is None
    ]
    if invalid_revisions:
        raise RuntimeError(
            f"Perplexity report-card extraction response has invalid revisions: {invalid_revisions}"
        )
    count_pattern = r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*(0|1)\b"
    navigation = re.search(r"(?im)\bnavigation_count\b" + count_pattern, receipt)
    post_navigation = re.search(
        r"(?im)\bpost_navigation_observe_count\b" + count_pattern, receipt
    )
    initial_url = re.search(
        r"(?im)\binitial_current_url\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
        r"(https://www\.perplexity\.ai/\S+)",
        receipt,
    )
    if (
        navigation is None or post_navigation is None or initial_url is None
        or navigation.group(1) != post_navigation.group(1)
        or ((initial_url.group(1) != thread_url) != (navigation.group(1) == "1"))
    ):
        raise RuntimeError("Perplexity report-card extraction navigation proof is invalid")
    report_url_pattern = r"https://www\.perplexity\.ai/computer/a/[A-Za-z0-9_-]+"
    report_url = re.search(
        r"(?im)\breport_surface_url\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
        rf"({report_url_pattern})\b",
        receipt,
    )
    post_copy_url = re.search(
        r"(?im)\bpost_copy_url\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
        rf"({report_url_pattern})\b",
        receipt,
    )
    if (
        report_url is None or post_copy_url is None
        or report_url.group(1) != post_copy_url.group(1)
    ):
        raise RuntimeError("Perplexity report-card extraction report URL is not stable")
    if re.search(
        r"(?im)\bpre_report_entry_name\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
        r"(?=[^\r\n]*[A-Za-z0-9])[^\r\n]+",
        receipt,
    ) is None:
        raise RuntimeError("Perplexity report-card extraction report name is empty")


def _perplexity_report_preview_source_provenance(
    receipt: str, display: str, preview_url: str
) -> bool:
    required = {
        "platform": "perplexity",
        "display": display,
        "report_surface_url": preview_url,
        "report_surface_stop_count": "0",
        "report_surface_copy_contents_count": "0",
        "report_entry_click_count": "1",
        "report_copy_click_count": "0",
        "clipboard_read_count": "0",
        "sent": "false",
        "retried": "false",
    }
    return "first-mismatch stop report" in receipt.lower() and all(
        _receipt_field_matches(receipt, field, value)
        for field, value in required.items()
    )


def _perplexity_report_open_menu_source_provenance(
    receipt: str, display: str, preview_url: str
) -> str | None:
    required = {
        "platform": "perplexity",
        "display": display,
        "current_url": preview_url,
        "pre_stop_count": "0",
        "pre_artifact_options_count": "1",
        "pre_close_artifact_count": "1",
        "pre_expand_artifact_count": "1",
        "pre_report_scroll_pane_count": "1",
        "options_performed": "false",
        "open_new_tab_performed": "false",
        "observe_count": "1",
        "operate_count": "0",
        "click_count": "0",
        "clipboard_read_count": "0",
        "extracted": "false",
        "sent": "false",
        "retried": "false",
    }
    lowered = receipt.lower()
    if (
        "first-mismatch stop report" not in lowered
        or "already shows the artifact-options menu open" not in lowered
        or "mapped element `artifact_open_new_tab`" not in receipt
        or "states: showing, expanded, focusable, enabled" not in lowered
        or any(
            not _receipt_field_matches(receipt, field, value)
            for field, value in required.items()
        )
    ):
        return None
    revision = re.search(
        r"(?im)\bpre_observation_revision\b"
        r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*([0-9a-f]{64})\b",
        receipt,
    )
    return revision.group(1) if revision is not None else None


def _validate_perplexity_report_open_menu_extraction_receipt(
    receipt: str,
    display: str,
    source_sha256: str,
    source_observation_revision: str,
    preview_url: str,
    response_file: Path,
) -> None:
    if not response_file.is_file() or response_file.stat().st_size == 0:
        raise RuntimeError("Perplexity open-menu extraction file is missing or empty")
    exact = {
        "platform": "perplexity",
        "display": display,
        "source_response_json_sha256": source_sha256,
        "source_observation_revision": source_observation_revision,
        "preview_url": preview_url,
        "pre_observation_revision": source_observation_revision,
        "pre_stop_count": "0",
        "pre_artifact_options_count": "1",
        "pre_artifact_options_expanded": "true",
        "pre_open_new_tab_count": "1",
        "open_new_tab_performed": "true",
        "open_new_tab_primitive": "click",
        "standalone_stop_count": "0",
        "standalone_copy_contents_count": "1",
        "copy_performed": "true",
        "copy_primitive": "click",
        "post_copy_stop_count": "0",
        "post_copy_contents_count": "1",
        "output_file": str(response_file),
        "byte_count": str(response_file.stat().st_size),
        "response_sha256": _sha256(response_file),
        "observe_count": "3",
        "operate_count": "0",
        "click_count": "2",
        "clipboard_read_count": "1",
        "other_mutation_count": "0",
        "extracted": "true",
        "sent": "false",
        "regenerated": "false",
        "retried": "false",
    }
    invalid = [
        field
        for field, value in exact.items()
        if not _receipt_field_matches(receipt, field, value)
    ]
    if "perplexity report open menu extraction receipt" not in receipt.lower() or invalid:
        raise RuntimeError(
            f"Perplexity open-menu extraction receipt has invalid fields: {invalid}"
        )
    for field in (
        "standalone_observation_revision",
        "post_copy_observation_revision",
    ):
        if re.search(
            rf"(?im)\b{field}\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*[0-9a-f]{{64}}\b",
            receipt,
        ) is None:
            raise RuntimeError(f"Perplexity open-menu extraction invalid revision: {field}")
    url_pattern = r"https://www\.perplexity\.ai/computer/a/[A-Za-z0-9_-]+"
    standalone_url = re.search(
        r"(?im)\bstandalone_url\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
        rf"({url_pattern})\b",
        receipt,
    )
    post_copy_url = re.search(
        r"(?im)\bpost_copy_url\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
        rf"({url_pattern})\b",
        receipt,
    )
    if (
        standalone_url is None
        or post_copy_url is None
        or post_copy_url.group(1) != standalone_url.group(1)
    ):
        raise RuntimeError("Perplexity open-menu extraction standalone URL is not stable")


def _validate_perplexity_report_preview_extraction_receipt(
    receipt: str,
    display: str,
    source_sha256: str,
    preview_url: str,
    response_file: Path,
) -> None:
    if not response_file.is_file() or response_file.stat().st_size == 0:
        raise RuntimeError("Perplexity preview extraction file is missing or empty")
    exact = {
        "platform": "perplexity", "display": display,
        "source_response_json_sha256": source_sha256, "preview_url": preview_url,
        "pre_stop_count": "0", "pre_artifact_options_count": "1",
        "pre_close_artifact_count": "1", "pre_expand_artifact_count": "1",
        "pre_report_scroll_pane_count": "1", "options_performed": "true",
        "options_primitive": "mapped_pointer_activate", "menu_stop_count": "0",
        "menu_open_new_tab_count": "1", "open_new_tab_performed": "true",
        "open_new_tab_primitive": "click", "standalone_stop_count": "0",
        "standalone_copy_contents_count": "1", "copy_performed": "true",
        "copy_primitive": "click", "post_copy_stop_count": "0",
        "post_copy_contents_count": "1", "output_file": str(response_file),
        "byte_count": str(response_file.stat().st_size),
        "response_sha256": _sha256(response_file), "observe_count": "4",
        "operate_count": "1", "click_count": "2", "clipboard_read_count": "1",
        "other_mutation_count": "0", "extracted": "true", "sent": "false",
        "regenerated": "false", "retried": "false",
    }
    invalid = [
        field for field, value in exact.items()
        if not _receipt_field_matches(receipt, field, value)
    ]
    if "perplexity report preview extraction receipt" not in receipt.lower() or invalid:
        raise RuntimeError(
            f"Perplexity preview extraction receipt has invalid fields: {invalid}"
        )
    for field in (
        "pre_observation_revision", "menu_observation_revision",
        "standalone_observation_revision", "post_copy_observation_revision",
    ):
        if re.search(
            rf"(?im)\b{field}\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*[0-9a-f]{{64}}\b",
            receipt,
        ) is None:
            raise RuntimeError(f"Perplexity preview extraction invalid revision: {field}")
    url_pattern = r"https://www\.perplexity\.ai/computer/a/[A-Za-z0-9_-]+"
    standalone = re.search(
        r"(?im)\bstandalone_url\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
        rf"({url_pattern})\b", receipt,
    )
    post_copy = re.search(
        r"(?im)\bpost_copy_url\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*"
        rf"({url_pattern})\b", receipt,
    )
    if standalone is None or post_copy is None or standalone.group(1) != post_copy.group(1):
        raise RuntimeError("Perplexity preview extraction standalone URL is not stable")


def _completed_before_stop_provenance(
    receipt: str,
    platform: str,
    display: str,
) -> bool:
    required = {
        "completion_basis": "completed_before_stop",
        "stop_seen": "false",
        "monitor_id": "none",
        "send_count": "1",
        "platform": platform,
        "display": display,
    }
    if any(
        not _receipt_field_matches(receipt, field, expected)
        for field, expected in required.items()
    ):
        return False
    for index in (1, 2):
        if re.search(
            rf"(?im)\bobservation_revision_{index}\b"
            r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*[0-9a-f]{64}\b",
            receipt,
        ) is None:
            return False
    thread_url_patterns = {
        "gemini": r"https://gemini\.google\.com/(?:u/\d+/)?app/[A-Za-z0-9_-]+",
        "perplexity": r"https://www\.perplexity\.ai/search/[A-Za-z0-9_-]+",
    }
    pattern = thread_url_patterns.get(platform)
    return pattern is not None and re.search(pattern, receipt) is not None


def _extraction_event_id(
    seat_id: str,
    monitor_id: str | None,
    platform: str,
    display: str,
    source_response_sha256: str | None,
    output_type: str,
) -> str:
    completion_identity = monitor_id or (
        f"completed-before-stop\0{platform}\0{display}\0{source_response_sha256}"
    )
    identity_material = f"{seat_id}\0{completion_identity}"
    if platform == "gemini" and output_type == "research_report":
        identity_material += f"\0{output_type}"
    digest = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()
    return f"extract-{digest[:24]}"


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
        allow_existing=args.phase in {
            "extract", "extract-perplexity-report-card",
            "extract-perplexity-report-preview", "extract-perplexity-report-open-menu",
        },
    )

    source_response = None
    source_response_sha256 = None
    source_terminal_identity = None
    source_diagnostic_identity = None
    exception_key = None
    completed_before_stop_response_file = None
    claude_download_before = None
    claude_download_receipt = None
    extraction_mode = None
    claude_launcher_revision = None
    claude_launcher_counts = None
    perplexity_diagnostic_thread_url = None
    preview_source_response = None
    preview_source_sha256 = None
    preview_source_observation_revision = None
    perplexity_preview_url = None
    gemini_terminal_receipt = None
    gemini_terminal_receipt_sha256 = None
    gemini_copy_result_json = None
    gemini_copy_result_json_sha256 = None
    gemini_clipboard_source = None
    if args.phase == "diagnose-chatgpt-model-menu":
        if args.platform != "chatgpt":
            raise RuntimeError("diagnose-chatgpt-model-menu requires platform chatgpt")
        content = _chatgpt_model_menu_diagnostic_content(args.display)
        digest = hashlib.sha256(
            f"{seat_id}\0{args.platform}\0{args.display}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"diagnose-model-menu-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 4096)
    elif args.phase == "diagnose-chatgpt-power-right":
        if args.platform != "chatgpt":
            raise RuntimeError("diagnose-chatgpt-power-right requires platform chatgpt")
        if args.pre_selector_name == "":
            raise RuntimeError("diagnose-chatgpt-power-right requires a nonempty pre-selector name")
        if args.pre_description == "":
            raise RuntimeError("diagnose-chatgpt-power-right requires a nonempty pre-description")
        content = _chatgpt_power_right_diagnostic_content(
            args.display,
            args.pre_selector_name,
            args.pre_description,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0{args.platform}\0{args.display}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"diagnose-power-right-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 4096)
    elif args.phase == "reset-chatgpt-model-menu-compact":
        if args.platform != "chatgpt":
            raise RuntimeError(
                "reset-chatgpt-model-menu-compact requires platform chatgpt"
            )
        content = _chatgpt_model_menu_compact_reset_content(args.display)
        digest = hashlib.sha256(
            f"{seat_id}\0{args.platform}\0{args.display}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"reset-model-menu-compact-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 4096)
    elif args.phase == "diagnose-perplexity-artifacts":
        if args.platform != "perplexity":
            raise RuntimeError(
                "diagnose-perplexity-artifacts requires platform perplexity"
            )
        if args.display != ":6":
            raise RuntimeError("diagnose-perplexity-artifacts requires display :6")
        source_terminal_identity = _identity(
            args.source_terminal_identity,
            "source terminal identity",
        )
        if seat_id == source_terminal_identity:
            raise RuntimeError(
                "Perplexity Artifacts diagnostic requires a new seat identity"
            )
        perplexity_diagnostic_thread_url = args.thread_url.strip()
        if re.fullmatch(
            r"https://www\.perplexity\.ai/search/[A-Za-z0-9_-]+",
            perplexity_diagnostic_thread_url,
        ) is None:
            raise RuntimeError(
                "diagnose-perplexity-artifacts requires one exact Perplexity thread URL"
            )
        content = _perplexity_artifacts_diagnostic_content(
            args.display,
            source_terminal_identity,
            perplexity_diagnostic_thread_url,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0perplexity\0{args.display}\0{source_terminal_identity}\0"
            f"{perplexity_diagnostic_thread_url}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"diagnose-perplexity-artifacts-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 4096)
    elif args.phase == "diagnose-perplexity-report-card":
        if args.platform != "perplexity":
            raise RuntimeError(
                "diagnose-perplexity-report-card requires platform perplexity"
            )
        if args.display != ":6":
            raise RuntimeError("diagnose-perplexity-report-card requires display :6")
        source_diagnostic_identity = _identity(
            args.source_diagnostic_identity,
            "source diagnostic identity",
        )
        if seat_id == source_diagnostic_identity:
            raise RuntimeError(
                "Perplexity report-card diagnostic requires a new seat identity"
            )
        perplexity_diagnostic_thread_url = args.thread_url.strip()
        if re.fullmatch(
            r"https://www\.perplexity\.ai/search/[A-Za-z0-9_-]+",
            perplexity_diagnostic_thread_url,
        ) is None:
            raise RuntimeError(
                "diagnose-perplexity-report-card requires one exact Perplexity thread URL"
            )
        content = _perplexity_report_card_diagnostic_content(
            args.display,
            source_diagnostic_identity,
            perplexity_diagnostic_thread_url,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0perplexity\0{args.display}\0{source_diagnostic_identity}\0"
            f"{perplexity_diagnostic_thread_url}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"diagnose-perplexity-report-card-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 4096)
    elif args.phase == "extract-perplexity-report-card":
        if args.platform != "perplexity":
            raise RuntimeError(
                "extract-perplexity-report-card requires platform perplexity"
            )
        if args.display != ":6":
            raise RuntimeError("extract-perplexity-report-card requires display :6")
        source_diagnostic_identity = _identity(
            args.source_diagnostic_identity,
            "source diagnostic identity",
        )
        if seat_id == source_diagnostic_identity:
            raise RuntimeError(
                "Perplexity report-card extraction requires a new seat identity"
            )
        perplexity_diagnostic_thread_url = args.thread_url.strip()
        if re.fullmatch(
            r"https://www\.perplexity\.ai/search/[A-Za-z0-9_-]+",
            perplexity_diagnostic_thread_url,
        ) is None:
            raise RuntimeError(
                "extract-perplexity-report-card requires one exact Perplexity thread URL"
            )
        response_file = Path(args.response_file).expanduser()
        if not response_file.is_absolute():
            raise RuntimeError("response file must be an absolute path")
        response_file = response_file.parent.resolve(strict=False) / response_file.name
        if response_file != root / "response.txt":
            raise RuntimeError("response file must be ARTIFACT_ROOT/response.txt")
        execution_outputs = (
            root / "request.json",
            root / "response.headers",
            root / "worker_response.json",
            response_file,
        )
        existing_outputs = [str(path) for path in execution_outputs if path.exists()]
        if existing_outputs:
            raise RuntimeError(
                "Perplexity report-card extraction output already exists; refusing retry: "
                f"{existing_outputs}"
            )
        content = _perplexity_report_card_extraction_content(
            args.display,
            source_diagnostic_identity,
            perplexity_diagnostic_thread_url,
            response_file,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0perplexity\0{args.display}\0{source_diagnostic_identity}\0"
            f"{perplexity_diagnostic_thread_url}\0{response_file}\0{content}".encode(
                "utf-8"
            )
        ).hexdigest()
        event_id = f"extract-perplexity-report-card-{digest[:24]}"
        request_text = _request_text(content, 4096)
    elif args.phase == "extract-perplexity-report-preview":
        if args.platform != "perplexity" or args.display != ":6":
            raise RuntimeError("extract-perplexity-report-preview requires Perplexity on :6")
        perplexity_diagnostic_thread_url = args.thread_url.strip()
        if re.fullmatch(
            r"https://www\.perplexity\.ai/search/[A-Za-z0-9_-]+",
            perplexity_diagnostic_thread_url,
        ) is None:
            raise RuntimeError("preview extraction requires one exact Perplexity thread URL")
        perplexity_preview_url = perplexity_diagnostic_thread_url + "?preview=1"
        preview_source_response = _absolute_input(
            args.source_terminal_response_json, "source terminal response JSON"
        )
        _source_payload, preview_source_receipt = _worker_receipt(preview_source_response)
        if not _is_worker_stop_report(preview_source_receipt) or not (
            _perplexity_report_preview_source_provenance(
                preview_source_receipt, args.display, perplexity_preview_url
            )
        ):
            raise RuntimeError("source response lacks exact terminal preview provenance")
        preview_source_sha256 = _sha256(preview_source_response)
        response_file = Path(args.response_file).expanduser()
        if not response_file.is_absolute():
            raise RuntimeError("response file must be an absolute path")
        response_file = response_file.parent.resolve(strict=False) / response_file.name
        if response_file != root / "response.txt":
            raise RuntimeError("response file must be ARTIFACT_ROOT/response.txt")
        outputs = (
            root / "request.json", root / "response.headers",
            root / "worker_response.json", response_file,
        )
        existing = [str(path) for path in outputs if path.exists()]
        if existing:
            raise RuntimeError(f"preview extraction output exists; refusing retry: {existing}")
        content = _perplexity_report_preview_extraction_content(
            args.display, preview_source_sha256, perplexity_preview_url, response_file
        )
        digest = hashlib.sha256(
            f"{seat_id}\0perplexity\0{args.display}\0{preview_source_sha256}\0"
            f"{perplexity_preview_url}\0{response_file}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"extract-perplexity-report-preview-{digest[:24]}"
        request_text = _request_text(content, 4096)
    elif args.phase == "extract-perplexity-report-open-menu":
        if args.platform != "perplexity" or args.display != ":6":
            raise RuntimeError(
                "extract-perplexity-report-open-menu requires Perplexity on :6"
            )
        perplexity_diagnostic_thread_url = args.thread_url.strip()
        if re.fullmatch(
            r"https://www\.perplexity\.ai/search/[A-Za-z0-9_-]+",
            perplexity_diagnostic_thread_url,
        ) is None:
            raise RuntimeError(
                "open-menu extraction requires one exact Perplexity thread URL"
            )
        perplexity_preview_url = perplexity_diagnostic_thread_url + "?preview=1"
        preview_source_response = _absolute_input(
            args.source_terminal_response_json, "source terminal response JSON"
        )
        _source_payload, preview_source_receipt = _worker_receipt(
            preview_source_response
        )
        preview_source_observation_revision = (
            _perplexity_report_open_menu_source_provenance(
                preview_source_receipt, args.display, perplexity_preview_url
            )
        )
        if (
            not _is_worker_stop_report(preview_source_receipt)
            or preview_source_observation_revision is None
        ):
            raise RuntimeError(
                "source response lacks exact terminal open-menu provenance"
            )
        preview_source_sha256 = _sha256(preview_source_response)
        response_file = Path(args.response_file).expanduser()
        if not response_file.is_absolute():
            raise RuntimeError("response file must be an absolute path")
        response_file = response_file.parent.resolve(strict=False) / response_file.name
        if response_file != root / "response.txt":
            raise RuntimeError("response file must be ARTIFACT_ROOT/response.txt")
        outputs = (
            root / "request.json",
            root / "response.headers",
            root / "worker_response.json",
            response_file,
        )
        existing = [str(path) for path in outputs if path.exists()]
        if existing:
            raise RuntimeError(
                f"open-menu extraction output exists; refusing retry: {existing}"
            )
        content = _perplexity_report_open_menu_extraction_content(
            args.display,
            preview_source_sha256,
            preview_source_observation_revision,
            perplexity_preview_url,
            response_file,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0perplexity\0{args.display}\0{preview_source_sha256}\0"
            f"{preview_source_observation_revision}\0{perplexity_preview_url}\0"
            f"{response_file}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"extract-perplexity-report-open-menu-{digest[:24]}"
        request_text = _request_text(content, 4096)
    elif args.phase == "recover-claude-pre-send":
        exception_key = _identity(args.exception_key, "exception key")
        source_terminal_identity = _identity(
            args.source_terminal_identity,
            "source terminal identity",
        )
        if seat_id == source_terminal_identity:
            raise RuntimeError(
                "Claude pre-send recovery requires a new seat identity"
            )
        content = _claude_pre_send_recovery_content(
            args.display,
            exception_key,
            source_terminal_identity,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0claude\0{args.display}\0{exception_key}\0"
            f"{source_terminal_identity}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"recover-claude-pre-send-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 4096)
    elif args.phase == "recover-grok-pre-send":
        if args.platform != "grok":
            raise RuntimeError("recover-grok-pre-send requires platform grok")
        exception_key = _identity(args.exception_key, "exception key")
        source_terminal_identity = _identity(
            args.source_terminal_identity,
            "source terminal identity",
        )
        if seat_id == source_terminal_identity:
            raise RuntimeError(
                "Grok pre-send recovery requires a new seat identity"
            )
        content = _grok_pre_send_recovery_content(
            args.display,
            exception_key,
            source_terminal_identity,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0grok\0{args.display}\0{exception_key}\0"
            f"{source_terminal_identity}\0{content}".encode("utf-8")
        ).hexdigest()
        event_id = f"recover-grok-pre-send-{digest[:24]}"
        response_file = None
        request_text = _request_text(content, 4096)
    elif args.phase == "extract-gemini-terminal-clipboard":
        if args.platform != "gemini":
            raise RuntimeError(
                "extract-gemini-terminal-clipboard requires platform gemini"
            )
        gemini_terminal_receipt = _absolute_input(
            args.source_terminal_receipt,
            "source terminal receipt",
        )
        gemini_terminal_receipt_sha256 = args.source_terminal_receipt_sha256
        gemini_copy_result_json = _absolute_input(
            args.source_copy_result_json,
            "source Copy result JSON",
        )
        gemini_copy_result_json_sha256 = args.source_copy_result_json_sha256
        response_file = Path(args.response_file).expanduser()
        if not response_file.is_absolute():
            raise RuntimeError("response file must be an absolute path")
        response_file = response_file.parent.resolve(strict=False) / response_file.name
        if response_file != root / "response.txt":
            raise RuntimeError("response file must be ARTIFACT_ROOT/response.txt")
        if response_file.exists():
            raise RuntimeError(
                f"response file already exists; refusing retry: {response_file}"
            )
        gemini_clipboard_source = _validate_gemini_terminal_clipboard_source(
            gemini_terminal_receipt,
            gemini_terminal_receipt_sha256,
            gemini_copy_result_json,
            gemini_copy_result_json_sha256,
            args.display,
            seat_id,
        )
        capture_root = gemini_clipboard_source["capture_root"]
        proxy_namespace = gemini_clipboard_source["proxy_namespace"]
        assert isinstance(capture_root, Path)
        assert isinstance(proxy_namespace, str)
        if (capture_root / proxy_namespace / seat_id).exists():
            raise RuntimeError(
                "terminal clipboard extraction seat already has captured calls; refusing retry"
            )
        content = _gemini_terminal_clipboard_only_content(
            args.display,
            response_file,
            gemini_clipboard_source,
        )
        digest = hashlib.sha256(
            f"{seat_id}\0gemini\0{args.display}\0"
            f"{gemini_terminal_receipt_sha256}\0"
            f"{gemini_copy_result_json_sha256}\0{response_file}\0{content}".encode(
                "utf-8"
            )
        ).hexdigest()
        event_id = f"extract-gemini-terminal-clipboard-{digest[:24]}"
        request_text = _request_text(content, 2048)
    elif args.phase == "send":
        bundle_a = _absolute_input(args.bundle_a, "bundle A")
        bundle_b = _absolute_input(args.bundle_b, "bundle B")
        prompt_file = _absolute_input(args.prompt_file, "prompt file")
        completed_state = _completed_before_stop_state(args.platform)
        if completed_state is not None and completed_state["handoff"] == "inline_extract":
            completed_before_stop_response_file = root / "response.txt"
            if completed_before_stop_response_file.exists():
                raise RuntimeError(
                    "completed-before-Stop response file already exists; refusing send: "
                    f"{completed_before_stop_response_file}"
                )
        content = _send_content(
            args.platform,
            args.display,
            bundle_a,
            bundle_b,
            prompt_file,
            completed_before_stop_response_file,
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
        monitor_id = None
        completed_before_stop_source = args.completed_before_stop_source_response_json
        if completed_before_stop_source is not None:
            completed_state = _completed_before_stop_state(args.platform)
            if completed_state is None:
                raise RuntimeError(
                    "completed-before-Stop extraction is not qualified for this platform"
                )
            source_response = _absolute_input(
                completed_before_stop_source,
                "completed-before-Stop source response JSON",
            )
            _source_payload, source_receipt = _worker_receipt(source_response)
            if (
                not _is_completed_before_stop_receipt(source_receipt)
                or not _completed_before_stop_provenance(
                    source_receipt,
                    args.platform,
                    args.display,
                )
            ):
                raise RuntimeError(
                    "completed-before-Stop source response lacks exact send, two-observation, "
                    "thread, platform, display, or monitor-none evidence"
                )
            source_response_sha256 = _sha256(source_response)
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
        event_id = _extraction_event_id(
            seat_id,
            monitor_id,
            args.platform,
            args.display,
            source_response_sha256,
            args.output_type,
        )
        if args.platform == "claude":
            _require_claude_extraction_workflows()
            request_text = None
        else:
            content = _extract_content(
                monitor_id,
                args.platform,
                args.display,
                response_file,
                source_response_sha256,
                output_type=args.output_type,
            )
            request_text = _request_text(content, 4096)

    correlation_id = f"{event_id}-1"
    if not root.exists():
        root.mkdir(mode=0o700)
    prepared_marker = root / ".prepared"
    if args.phase == "extract":
        request_file = root / "request.json"
        extraction_outputs = [
            root / "response.headers",
            root / "worker_response.json",
            response_file,
        ]
        if args.platform == "claude":
            extraction_outputs.extend((root / "download_receipt.json", request_file))
        else:
            assert request_text is not None
            _ensure_request(request_file, request_text)
        if args.prepare_only:
            for output in extraction_outputs:
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
            prepared_result = {
                "artifact_root": str(root),
                "event_id": event_id,
                "output_type": args.output_type,
                "request_json": str(request_file),
                "response_file": str(response_file),
            }
            if source_response is not None:
                prepared_result.update({
                    "completion_basis": "completed_before_stop",
                    "source_response_json": str(source_response),
                    "source_response_json_sha256": source_response_sha256,
                })
            print(json.dumps(prepared_result, sort_keys=True))
            return 0
        if not prepared_marker.is_file():
            raise RuntimeError("extraction handoff is not prepared or was already consumed")
        if prepared_marker.read_text(encoding="utf-8") != event_id + "\n":
            raise RuntimeError("extraction handoff identity mismatch")
        for output in extraction_outputs:
            if output.exists():
                raise RuntimeError(f"extraction output already exists; refusing retry: {output}")
        prepared_marker.unlink()
    lease_release = None
    primary_error = None
    mutation_stop_report = False
    completed_before_stop = False
    try:
        request_must_be_new = args.phase in {
            "extract-perplexity-report-card", "extract-perplexity-report-preview",
            "extract-perplexity-report-open-menu",
            "extract-gemini-terminal-clipboard",
        }
        if args.phase == "extract" and args.platform == "claude":
            try:
                (
                    extraction_mode,
                    claude_launcher_revision,
                    claude_launcher_counts,
                    claude_download_before,
                ) = _prepare_claude_extraction(args.display)
            except ClaudeArtifactDownloadError as exc:
                raise RuntimeError(str(exc)) from exc
            content = _extract_content(
                monitor_id,
                args.platform,
                args.display,
                response_file,
                source_response_sha256,
                extraction_mode,
                claude_launcher_revision,
            )
            request_text = _request_text(content, 4096)
            request_must_be_new = True
        if request_text is None:
            raise RuntimeError("worker request was not constructed")
        request_path, headers_path, response_path, receipt = _invoke(
            root=root,
            request_text=request_text,
            seat_id=seat_id,
            event_id=event_id,
            correlation_id=correlation_id,
            request_must_be_new=request_must_be_new,
        )
        completed_before_stop = (
            args.phase == "send"
            and _is_completed_before_stop_receipt(receipt)
        )
        if completed_before_stop:
            completed_state = _completed_before_stop_state(args.platform)
            if completed_state is None:
                raise RuntimeError(
                    "completed-before-Stop receipt is not authorized for this platform"
                )
            if not _completed_before_stop_provenance(
                receipt,
                args.platform,
                args.display,
            ):
                raise RuntimeError(
                    "completed-before-Stop send receipt lacks exact terminal provenance"
                )
            if completed_state["handoff"] == "inline_extract":
                if completed_before_stop_response_file is None:
                    raise RuntimeError(
                        "completed-before-Stop inline extraction has no output path"
                    )
                if (
                    not completed_before_stop_response_file.is_file()
                    or completed_before_stop_response_file.stat().st_size == 0
                ):
                    raise RuntimeError(
                        "completed-before-Stop send did not create a non-empty response file"
                    )
                completed_response_sha256 = _sha256(
                    completed_before_stop_response_file
                )
                if (
                    not _receipt_field_matches(
                        receipt,
                        "output_file",
                        str(completed_before_stop_response_file),
                    )
                    or not _receipt_field_matches(
                        receipt,
                        "byte_count",
                        str(completed_before_stop_response_file.stat().st_size),
                    )
                    or not _receipt_field_matches(
                        receipt,
                        "response_sha256",
                        completed_response_sha256,
                    )
                ):
                    raise RuntimeError(
                        "completed-before-Stop send receipt does not match the extracted file"
                    )
        if (
            source_response is not None
            and _sha256(source_response) != source_response_sha256
        ):
            if args.phase == "recover":
                raise RuntimeError("source response changed during recovery")
            raise RuntimeError("source response changed during the extraction turn")
        if (
            preview_source_response is not None
            and _sha256(preview_source_response) != preview_source_sha256
        ):
            raise RuntimeError("preview source response changed during extraction")
        if (
            args.phase == "extract"
            and source_response is not None
            and (
                not _receipt_field_matches(
                    receipt,
                    "completion_basis",
                    "completed_before_stop",
                )
                or not _receipt_field_matches(
                    receipt,
                    "source_response_json_sha256",
                    str(source_response_sha256),
                )
            )
        ):
            raise RuntimeError(
                "completed-before-Stop extraction receipt lacks source provenance"
            )
        if _is_worker_stop_report(receipt):
            mutation_stop_report = args.phase in {
                "send",
                "recover",
                "recover-claude-pre-send",
                "recover-grok-pre-send",
                "diagnose-chatgpt-model-menu",
                "diagnose-chatgpt-power-right",
                "reset-chatgpt-model-menu-compact",
                "diagnose-perplexity-artifacts",
                "diagnose-perplexity-report-card",
                "extract-perplexity-report-card",
                "extract-perplexity-report-preview",
                "extract-perplexity-report-open-menu",
                "extract-gemini-terminal-clipboard",
            }
            raise RuntimeError(f"worker returned a terminal {args.phase} report")
        if (
            args.phase == "extract"
            and args.platform == "gemini"
            and args.output_type == "research_report"
        ):
            if not _receipt_field_matches(receipt, "output_type", args.output_type):
                raise RuntimeError(
                    "Gemini extraction receipt does not match the selected output type"
                )
            assert response_file is not None
            completion_notice = (
                "I've completed your research. Feel free to ask me follow-up "
                "questions or request changes."
            )
            extracted = response_file.read_text(encoding="utf-8").strip()
            if len(extracted.encode("utf-8")) <= 89 or extracted == completion_notice:
                raise RuntimeError(
                    "Gemini research-report extraction returned the completion notice"
                )
        if args.phase == "extract-gemini-terminal-clipboard":
            assert gemini_terminal_receipt is not None
            assert gemini_terminal_receipt_sha256 is not None
            assert gemini_copy_result_json is not None
            assert gemini_copy_result_json_sha256 is not None
            assert gemini_clipboard_source is not None
            assert response_file is not None
            if not response_file.is_file() or response_file.stat().st_size == 0:
                raise RuntimeError(
                    "Gemini terminal clipboard extraction did not create a non-empty file"
                )
            revalidated_source = _validate_gemini_terminal_clipboard_source(
                gemini_terminal_receipt,
                gemini_terminal_receipt_sha256,
                gemini_copy_result_json,
                gemini_copy_result_json_sha256,
                args.display,
                seat_id,
            )
            for field in (
                "source_seat_id",
                "source_turn_id",
                "source_event_id",
                "source_copy_tool_round",
                "source_terminal_receipt_sha256",
                "source_copy_result_json_sha256",
                "clipboard_source_certainty",
                "provider_output_proven",
                "global_capture_roots_scanned",
                "later_clipboard_affecting_records",
                "uncertain_capture_records",
            ):
                if revalidated_source[field] != gemini_clipboard_source[field]:
                    raise RuntimeError(
                        f"Gemini terminal clipboard source changed during extraction: {field}"
                    )
            _validate_gemini_terminal_clipboard_only_capture(
                seat_id,
                event_id,
                args.display,
                response_file,
                gemini_clipboard_source,
            )
            _validate_gemini_terminal_clipboard_only_receipt(
                receipt,
                args.display,
                response_file,
                gemini_clipboard_source,
            )
        if args.phase == "extract" and args.platform == "claude":
            if extraction_mode is None:
                raise RuntimeError("Claude extraction branch was not classified")
            _claude_extraction_mode(receipt, extraction_mode)
            if extraction_mode == "downloaded_file":
                if claude_download_before is None:
                    raise RuntimeError("Claude download manifest was not captured")
                try:
                    if (
                        resolve_claude_download_scope(args.display)
                        != claude_download_before.scope
                    ):
                        raise ClaudeArtifactDownloadError(
                            "Claude Firefox download scope changed during extraction"
                        )
                    claude_download_receipt = materialize_claude_download(
                        claude_download_before,
                        response_file,
                    )
                    write_download_receipt(
                        root / "download_receipt.json",
                        claude_download_receipt,
                    )
                except ClaudeArtifactDownloadError as exc:
                    raise RuntimeError(str(exc)) from exc
            elif claude_download_before is not None:
                raise RuntimeError(
                    "Claude assistant-text extraction captured a download manifest"
                )
        if args.phase == "recover-claude-pre-send":
            assert exception_key is not None
            assert source_terminal_identity is not None
            lowered_receipt = receipt.lower()
            required_receipt_fields = (
                "claude pre-send recovery receipt",
                "platform",
                "display",
                "source_terminal_identity",
                "exception_key",
                "classification_revision_1",
                "classification_revision_2",
                "clicked_element",
                "click_count",
                "navigation_postcondition_elements",
                "stable_cycles",
                "post_recovery_revision_1",
                "post_recovery_revision_2",
                "interstitial_absent",
                "attached",
                "pasted",
                "sent",
                "recovered",
            )
            missing_receipt_fields = [
                field
                for field in required_receipt_fields
                if field not in lowered_receipt
            ]
            if missing_receipt_fields:
                raise RuntimeError(
                    "Claude pre-send recovery response is missing receipt fields: "
                    f"{missing_receipt_fields}"
                )
            exact_receipt_values = {
                "platform": "claude",
                "display": args.display,
                "source_terminal_identity": source_terminal_identity,
                "exception_key": exception_key,
                "clicked_element": "claude_memory_not_now",
                "click_count": "1",
                "stable_cycles": "2",
                "interstitial_absent": "true",
                "attached": "false",
                "pasted": "false",
                "sent": "false",
                "recovered": "true",
            }
            invalid_receipt_values = [
                field
                for field, expected in exact_receipt_values.items()
                if not _receipt_field_matches(receipt, field, expected)
            ]
            if invalid_receipt_values:
                raise RuntimeError(
                    "Claude pre-send recovery response has invalid receipt values: "
                    f"{invalid_receipt_values}"
                )
            revision_fields = (
                "classification_revision_1",
                "classification_revision_2",
                "post_recovery_revision_1",
                "post_recovery_revision_2",
            )
            invalid_revisions = [
                field
                for field in revision_fields
                if re.search(
                    rf"(?im)\b{field}\b"
                    r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*[0-9a-f]{64}\b",
                    receipt,
                )
                is None
            ]
            if invalid_revisions:
                raise RuntimeError(
                    "Claude pre-send recovery response has invalid revisions: "
                    f"{invalid_revisions}"
                )
            navigation_controls = tuple(
                str(value)
                for value in _claude_pre_send_recovery_spec(exception_key)[
                    "navigation_controls"
                ]
            )
            if any(key not in receipt for key in navigation_controls):
                raise RuntimeError(
                    "Claude pre-send recovery response omits navigation controls"
                )
        if args.phase == "recover-grok-pre-send":
            assert exception_key is not None
            assert source_terminal_identity is not None
            spec = _grok_pre_send_recovery_spec(exception_key)
            lowered_receipt = receipt.lower()
            required_receipt_fields = (
                "grok pre-send recovery receipt",
                "platform",
                "display",
                "source_terminal_identity",
                "exception_key",
                "classification_revision_1",
                "classification_revision_2",
                "pre_recovery_counts_1",
                "pre_recovery_counts_2",
                "clicked_element",
                "click_count",
                "performed_primitive",
                "postcondition_elements",
                "stable_cycles",
                "post_recovery_revision_1",
                "post_recovery_revision_2",
                "post_recovery_counts_1",
                "post_recovery_counts_2",
                "interstitial_absent",
                "observe_count",
                "navigation_count",
                "attachment_count",
                "paste_count",
                "send_count",
                "selected_model",
                "sent",
                "recovered",
            )
            missing_receipt_fields = [
                field
                for field in required_receipt_fields
                if field not in lowered_receipt
            ]
            if missing_receipt_fields:
                raise RuntimeError(
                    "Grok pre-send recovery response is missing receipt fields: "
                    f"{missing_receipt_fields}"
                )
            exact_receipt_values = {
                "platform": "grok",
                "display": args.display,
                "source_terminal_identity": source_terminal_identity,
                "exception_key": exception_key,
                "clicked_element": str(spec["element"]),
                "click_count": "1",
                "performed_primitive": "click",
                "stable_cycles": str(spec["stable_cycles"]),
                "interstitial_absent": "true",
                "navigation_count": "0",
                "attachment_count": "0",
                "paste_count": "0",
                "send_count": "0",
                "selected_model": "false",
                "sent": "false",
                "recovered": "true",
            }
            invalid_receipt_values = [
                field
                for field, expected in exact_receipt_values.items()
                if not _receipt_field_matches(receipt, field, expected)
            ]
            if invalid_receipt_values:
                raise RuntimeError(
                    "Grok pre-send recovery response has invalid receipt values: "
                    f"{invalid_receipt_values}"
                )
            revision_fields = (
                "classification_revision_1",
                "classification_revision_2",
                "post_recovery_revision_1",
                "post_recovery_revision_2",
            )
            invalid_revisions = [
                field
                for field in revision_fields
                if re.search(
                    rf"(?im)\b{field}\b"
                    r"[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*[0-9a-f]{64}\b",
                    receipt,
                )
                is None
            ]
            if invalid_revisions:
                raise RuntimeError(
                    "Grok pre-send recovery response has invalid revisions: "
                    f"{invalid_revisions}"
                )
            detect = tuple(str(value) for value in spec["detect"])
            blocked_state_absent = tuple(
                str(value) for value in spec["blocked_state_absent"]
            )
            exact_singletons = tuple(
                str(value) for value in spec["exact_singletons"]
            )
            absent_after_recovery = tuple(
                str(value) for value in spec["absent_after_recovery"]
            )
            expected_pre_counts = {
                **{key: 1 for key in detect},
                **{key: 0 for key in blocked_state_absent},
            }
            expected_post_counts = {
                **{key: 1 for key in exact_singletons},
                **{key: 0 for key in absent_after_recovery},
            }
            for field in ("pre_recovery_counts_1", "pre_recovery_counts_2"):
                if _grok_recovery_count_map(receipt, field) != expected_pre_counts:
                    raise RuntimeError(
                        f"Grok pre-send recovery response has invalid {field}"
                    )
            for field in ("post_recovery_counts_1", "post_recovery_counts_2"):
                if _grok_recovery_count_map(receipt, field) != expected_post_counts:
                    raise RuntimeError(
                        f"Grok pre-send recovery response has invalid {field}"
                    )
            observe_count = _grok_recovery_observe_count(receipt)
            if not 4 <= observe_count <= int(spec["max_samples"]) + 2:
                raise RuntimeError(
                    "Grok pre-send recovery response has invalid observe_count"
                )
            if any(key not in receipt for key in exact_singletons):
                raise RuntimeError(
                    "Grok pre-send recovery response omits postcondition controls"
                )
        if args.phase == "diagnose-chatgpt-model-menu":
            required_receipt_fields = (
                "chatgpt model menu diagnostic receipt",
                "platform/display",
                "pre_focus_selector",
                "pre_focus_app_root_revision",
                "model_power",
                "model_show_advanced_options",
                "pre_focus_power_description",
                "power_ref_used",
                "focus_result",
                "post_focus_base_revision",
                "post_focus_power",
                "post_focus_power_description",
                "power_focused",
                "power_description",
                "selector_open_count",
                "power_focus_count",
                "advanced_click_count",
                "right_key_count",
                "selected_or_sent",
            )
            lowered_receipt = receipt.lower()
            missing_receipt_fields = [
                field for field in required_receipt_fields if field not in lowered_receipt
            ]
            if missing_receipt_fields:
                raise RuntimeError(
                    "diagnostic response is missing required receipt fields: "
                    f"{missing_receipt_fields}"
                )
            diagnostic_value_patterns = {
                "selector_open_count": r"(?im)\bselector_open_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*[01]\b",
                "power_focus_count": r"(?im)\bpower_focus_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*1\b",
                "advanced_click_count": r"(?im)\badvanced_click_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "right_key_count": r"(?im)\bright_key_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "power_focused": r"(?im)\bpower_focused\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "selected_or_sent": r"(?im)\bselected_or_sent\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*false\b",
            }
            invalid_receipt_fields = [
                field
                for field, pattern in diagnostic_value_patterns.items()
                if re.search(pattern, receipt) is None
            ]
            if invalid_receipt_fields:
                raise RuntimeError(
                    "diagnostic response has invalid receipt fields: "
                    f"{invalid_receipt_fields}"
                )
            if CHATGPT_POWER_INSTANT_DESCRIPTION not in receipt:
                raise RuntimeError(
                    "diagnostic response does not preserve the exact live Power description"
                )
        if args.phase == "diagnose-chatgpt-power-right":
            required_receipt_fields = (
                "chatgpt power right diagnostic receipt",
                "platform/display",
                "pre_base_revision",
                "pre_selector",
                "pre_power",
                "pre_selector_name",
                "pre_power_description",
                "key_result",
                "post_base_revision",
                "post_power",
                "post_power_description",
                "post_selector",
                "precondition_proven",
                "right_key_result_proven",
                "key_result_key",
                "key_result_clearmodifiers",
                "power_focused",
                "post_selector_expanded",
                "power_description_nonempty",
                "power_description_changed",
                "base_observe_count",
                "right_key_count",
                "power_adjustment_count",
                "selector_open_count",
                "power_focus_count",
                "click_count",
                "other_key_count",
                "other_mutation_count",
                "sent",
            )
            lowered_receipt = receipt.lower()
            missing_receipt_fields = [
                field for field in required_receipt_fields if field not in lowered_receipt
            ]
            if missing_receipt_fields:
                raise RuntimeError(
                    "Power Right response is missing required receipt fields: "
                    f"{missing_receipt_fields}"
                )
            power_right_value_patterns = {
                "precondition_proven": r"(?im)\bprecondition_proven\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "right_key_result_proven": r"(?im)\bright_key_result_proven\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "key_result_key": r"(?im)\bkey_result_key\b[*`\"' \t|]*(?::|=|\|)[*` \t|]*[\"']Right[\"']",
                "key_result_clearmodifiers": r"(?im)\bkey_result_clearmodifiers\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "power_focused": r"(?im)\bpower_focused\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "post_selector_expanded": r"(?im)\bpost_selector_expanded\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "power_description_nonempty": r"(?im)\bpower_description_nonempty\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "power_description_changed": r"(?im)\bpower_description_changed\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "base_observe_count": r"(?im)\bbase_observe_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*2\b",
                "right_key_count": r"(?im)\bright_key_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*1\b",
                "power_adjustment_count": r"(?im)\bpower_adjustment_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*1\b",
                "selector_open_count": r"(?im)\bselector_open_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "power_focus_count": r"(?im)\bpower_focus_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "click_count": r"(?im)\bclick_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "other_key_count": r"(?im)\bother_key_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "other_mutation_count": r"(?im)\bother_mutation_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "sent": r"(?im)\bsent\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*false\b",
            }
            invalid_receipt_fields = [
                field
                for field, pattern in power_right_value_patterns.items()
                if re.search(pattern, receipt) is None
            ]
            if invalid_receipt_fields:
                raise RuntimeError(
                    "Power Right response has invalid receipt fields: "
                    f"{invalid_receipt_fields}"
                )
            exact_values: dict[str, str] = {}
            for field in (
                "pre_selector_name",
                "pre_power_description",
                "post_power_description",
            ):
                pattern = re.compile(
                    rf"(?m)^{re.escape(field)}: "
                    rf"(?P<value>\"(?:\\.|[^\"\\])*\")\r?$"
                )
                matches = list(pattern.finditer(receipt))
                if len(matches) != 1:
                    raise RuntimeError(
                        f"Power Right response has {len(matches)} exact {field} lines; "
                        "expected exactly one"
                    )
                exact_values[field] = json.loads(matches[0].group("value"))
            if exact_values["pre_selector_name"] != args.pre_selector_name:
                raise RuntimeError(
                    "Power Right response changed the exact pre-action selector name"
                )
            if exact_values["pre_power_description"] != args.pre_description:
                raise RuntimeError(
                    "Power Right response changed the exact pre-action Power description"
                )
            if (
                not exact_values["post_power_description"]
                or exact_values["post_power_description"]
                == exact_values["pre_power_description"]
                or exact_values["post_power_description"]
                == "<complete nonempty exact live post-action description>"
            ):
                raise RuntimeError(
                    "Power Right response does not prove a nonempty changed Power description"
                )
        if args.phase == "reset-chatgpt-model-menu-compact":
            required_receipt_fields = (
                "chatgpt model menu compact reset receipt",
                "platform/display",
                "pre_click_selector",
                "pre_click_base_revision",
                "pre_click_app_root_revision",
                "model_show_compact_options",
                "compact_ref_used",
                "click_result",
                "post_click_app_root_revision",
                "post_click_model_power",
                "post_click_power_description",
                "post_click_model_show_advanced_options",
                "show_compact_options_absent",
                "compact_proven",
                "compact_click_count",
                "selector_open_count",
                "power_focus_count",
                "advanced_click_count",
                "model_click_count",
                "effort_click_count",
                "left_key_count",
                "right_key_count",
                "other_mutation_count",
                "selected_or_sent",
            )
            lowered_receipt = receipt.lower()
            missing_receipt_fields = [
                field for field in required_receipt_fields if field not in lowered_receipt
            ]
            if missing_receipt_fields:
                raise RuntimeError(
                    "compact-reset response is missing required receipt fields: "
                    f"{missing_receipt_fields}"
                )
            compact_value_patterns = {
                "compact_click_count": r"(?im)\bcompact_click_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*1\b",
                "selector_open_count": r"(?im)\bselector_open_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "power_focus_count": r"(?im)\bpower_focus_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "advanced_click_count": r"(?im)\badvanced_click_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "model_click_count": r"(?im)\bmodel_click_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "effort_click_count": r"(?im)\beffort_click_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "left_key_count": r"(?im)\bleft_key_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "right_key_count": r"(?im)\bright_key_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "other_mutation_count": r"(?im)\bother_mutation_count\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*0\b",
                "show_compact_options_absent": r"(?im)\bshow_compact_options_absent\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "compact_proven": r"(?im)\bcompact_proven\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*true\b",
                "selected_or_sent": r"(?im)\bselected_or_sent\b[*`\"' \t|]*(?::|=|\|)[*`\"' \t|]*false\b",
            }
            invalid_receipt_fields = [
                field
                for field, pattern in compact_value_patterns.items()
                if re.search(pattern, receipt) is None
            ]
            if invalid_receipt_fields:
                raise RuntimeError(
                    "compact-reset response has invalid receipt fields: "
                    f"{invalid_receipt_fields}"
                )
            if CHATGPT_POWER_INSTANT_DESCRIPTION not in receipt:
                raise RuntimeError(
                    "compact-reset response does not preserve the exact live Power description"
                )
        if args.phase == "diagnose-perplexity-artifacts":
            assert source_terminal_identity is not None
            assert perplexity_diagnostic_thread_url is not None
            _validate_perplexity_artifacts_diagnostic_receipt(
                receipt,
                args.display,
                source_terminal_identity,
                perplexity_diagnostic_thread_url,
            )
        if args.phase == "diagnose-perplexity-report-card":
            assert source_diagnostic_identity is not None
            assert perplexity_diagnostic_thread_url is not None
            _validate_perplexity_report_card_diagnostic_receipt(
                receipt,
                args.display,
                source_diagnostic_identity,
                perplexity_diagnostic_thread_url,
            )
        if args.phase == "extract-perplexity-report-card":
            assert source_diagnostic_identity is not None
            assert perplexity_diagnostic_thread_url is not None
            assert response_file is not None
            _validate_perplexity_report_card_extraction_receipt(
                receipt,
                args.display,
                source_diagnostic_identity,
                perplexity_diagnostic_thread_url,
                response_file,
            )
        if args.phase == "extract-perplexity-report-preview":
            assert preview_source_sha256 is not None
            assert perplexity_preview_url is not None
            assert response_file is not None
            _validate_perplexity_report_preview_extraction_receipt(
                receipt, args.display, preview_source_sha256,
                perplexity_preview_url, response_file,
            )
        if args.phase == "extract-perplexity-report-open-menu":
            assert preview_source_sha256 is not None
            assert preview_source_observation_revision is not None
            assert perplexity_preview_url is not None
            assert response_file is not None
            _validate_perplexity_report_open_menu_extraction_receipt(
                receipt,
                args.display,
                preview_source_sha256,
                preview_source_observation_revision,
                perplexity_preview_url,
                response_file,
            )
        if (
            args.phase in {"send", "recover"}
            and not completed_before_stop
            and not re.search(
                r"(?im)\bmonitor_id\b[*`\"' \t|]*(?::|=|`|\|)[*`\"' \t|]*"
                r"(?!(?:none|null)\b)[A-Za-z0-9][A-Za-z0-9._:-]{0,199}",
                receipt,
            )
        ):
            raise RuntimeError(f"{args.phase} response has no registered monitor_id")
        if response_file is not None:
            if not response_file.is_file() or response_file.stat().st_size == 0:
                raise RuntimeError("extraction did not create a non-empty response file")
    except RuntimeError as exc:
        primary_error = exc
    finally:
        if args.phase in {
            "extract",
            "recover-claude-pre-send",
            "recover-grok-pre-send",
            "diagnose-chatgpt-model-menu",
            "diagnose-chatgpt-power-right",
            "reset-chatgpt-model-menu-compact",
            "diagnose-perplexity-artifacts",
            "diagnose-perplexity-report-card",
            "extract-perplexity-report-card",
            "extract-perplexity-report-preview",
            "extract-perplexity-report-open-menu",
            "extract-gemini-terminal-clipboard",
        } or mutation_stop_report or completed_before_stop:
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
    if args.phase == "extract":
        result["output_type"] = args.output_type
    if response_file is not None:
        result.update({
            "response_file": str(response_file),
            "response_bytes": response_file.stat().st_size,
            "response_sha256": _sha256(response_file),
            "lease_release": lease_release,
        })
    if extraction_mode is not None:
        result["extraction_mode"] = extraction_mode
    if claude_launcher_revision is not None:
        result.update({
            "launcher_snapshot_sha256": claude_launcher_revision,
            "launcher_artifact_control_counts": claude_launcher_counts,
        })
    if claude_download_receipt is not None:
        download_receipt_path = root / "download_receipt.json"
        result.update({
            "download_receipt": str(download_receipt_path),
            "download_receipt_sha256": _sha256(download_receipt_path),
            "download_source": claude_download_receipt["source"],
        })
    if source_response is not None:
        source_result = {
            "source_response_json": str(source_response),
            "source_response_json_sha256": source_response_sha256,
        }
        if exception_key is None:
            source_result["completion_basis"] = "completed_before_stop"
        else:
            source_result["exception_key"] = exception_key
        result.update(source_result)
    if source_terminal_identity is not None:
        result.update({
            "source_terminal_identity": source_terminal_identity,
            "exception_key": exception_key,
        })
    if source_diagnostic_identity is not None:
        result["source_diagnostic_identity"] = source_diagnostic_identity
    if preview_source_response is not None:
        result.update({
            "source_terminal_response_json": str(preview_source_response),
            "source_terminal_response_json_sha256": preview_source_sha256,
            "source_observation_revision": preview_source_observation_revision,
            "preview_url": perplexity_preview_url,
        })
    if completed_before_stop:
        completed_state = _completed_before_stop_state(args.platform)
        assert completed_state is not None
        result.update({
            "completion_basis": "completed_before_stop",
            "handoff": completed_state["handoff"],
            "stop_seen": False,
            "monitor_id": None,
            "lease_release": lease_release,
        })
        if completed_before_stop_response_file is not None:
            result.update({
                "response_file": str(completed_before_stop_response_file),
                "response_bytes": completed_before_stop_response_file.stat().st_size,
                "response_sha256": _sha256(completed_before_stop_response_file),
            })
    if args.phase in {
        "recover-claude-pre-send",
        "recover-grok-pre-send",
        "diagnose-chatgpt-model-menu",
        "diagnose-chatgpt-power-right",
        "reset-chatgpt-model-menu-compact",
        "diagnose-perplexity-artifacts",
        "diagnose-perplexity-report-card",
        "extract-perplexity-report-card",
        "extract-perplexity-report-preview",
        "extract-perplexity-report-open-menu",
        "extract-gemini-terminal-clipboard",
    }:
        result["lease_release"] = lease_release
    if gemini_clipboard_source is not None:
        result.update({
            "source_terminal_receipt": str(gemini_terminal_receipt),
            "source_terminal_receipt_sha256": gemini_terminal_receipt_sha256,
            "source_copy_result_json": str(gemini_copy_result_json),
            "source_copy_result_json_sha256": gemini_copy_result_json_sha256,
            "source_seat_id": gemini_clipboard_source["source_seat_id"],
            "source_copy_tool_round": gemini_clipboard_source[
                "source_copy_tool_round"
            ],
            "clipboard_source_certainty": gemini_clipboard_source[
                "clipboard_source_certainty"
            ],
            "provider_output_proven": gemini_clipboard_source[
                "provider_output_proven"
            ],
            "global_capture_roots_scanned": gemini_clipboard_source[
                "global_capture_roots_scanned"
            ],
            "later_clipboard_affecting_records": gemini_clipboard_source[
                "later_clipboard_affecting_records"
            ],
            "uncertain_capture_records": gemini_clipboard_source[
                "uncertain_capture_records"
            ],
        })
    if perplexity_diagnostic_thread_url is not None:
        result["thread_url"] = perplexity_diagnostic_thread_url
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(1)
