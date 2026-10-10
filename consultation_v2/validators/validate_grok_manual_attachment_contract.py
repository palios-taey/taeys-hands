#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
DRIVER_PATH = REPO_ROOT / 'consultation_v2/platforms/grok/driver.py'
TAEY_EXTRACT_PATH = REPO_ROOT / 'consultation_v2/taey_extract.py'

from consultation_v2.platforms.grok.manual import (
    element_operation,
    key_requires_state,
)
from consultation_v2.yaml_contract import load_platform_yaml
from scripts.run_manual_chat_worker import (
    _recovery_content,
    _send_content,
    _sha256,
    _validate_consultation_recovery_source,
    build_parser,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _function_source(
    path: Path,
    name: str,
    *,
    owner: str | None = None,
) -> str:
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if owner is None and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                candidates.append(node)
        if owner is not None and isinstance(node, ast.ClassDef) and node.name == owner:
            candidates.extend(
                child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == name
            )
    _require(
        len(candidates) == 1,
        f'{path.relative_to(REPO_ROOT)} {owner or "module"}.{name} is not unique',
    )
    segment = ast.get_source_segment(source, candidates[0])
    _require(segment is not None, f'could not read source for {owner or "module"}.{name}')
    return str(segment)


def _write_consultation_recovery_fixture(
    root: Path,
    *,
    mutate_payload=None,
    display: str = ':5',
) -> tuple[Path, str, Path]:
    root.mkdir()
    session_url = 'https://grok.com/c/fixture'
    payload = {
        'ok': False,
        'platform': 'grok',
        'request': {'platform': 'grok'},
        'response_text': '',
        'session_url_after': session_url,
        'steps': [
            {
                'step': 'send_action',
                'success': True,
                'evidence': {'click_returned': True},
            },
            {
                'step': 'send',
                'success': True,
                'evidence': {
                    'stop_seen': True,
                    'answer_thread': True,
                    'url_after': session_url,
                },
            },
            {
                'step': 'monitor_register',
                'success': True,
                'evidence': {'monitor_id': 'grok:fixture', 'url': session_url},
            },
            {
                'step': 'monitor',
                'success': True,
                'evidence': {'seed_stop_seen': True, 'stop_seen': True},
            },
            {
                'step': 'extract',
                'success': False,
                'evidence': {
                    'snapshot': {
                        'platform': 'grok',
                        'url': session_url,
                        'mapped': {
                            'usage_limit_updated_alert': [{}],
                            'retry_button': [{}],
                        },
                    },
                },
            },
            {'step': 'notify_operator_failure', 'success': True, 'evidence': {}},
        ],
    }
    if mutate_payload is not None:
        mutate_payload(payload)
    consultation_receipt = root / 'consultation_receipt.json'
    consultation_receipt.write_text(
        json.dumps(payload, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    receipt_sha256 = _sha256(consultation_receipt)
    source_receipt = (
        'The consultation failed on the first attempt.\n\n'
        '**Result: Failed**\n'
        f'- **Display:** {display}\n'
        f'- **Receipt path:** `{consultation_receipt}`\n'
        f'- **Receipt SHA256:** `{receipt_sha256}`\n'
    )
    source_response = root / 'worker_response.json'
    source_response.write_text(
        json.dumps({
            'choices': [{
                'finish_reason': 'stop',
                'message': {'content': source_receipt},
            }],
        }, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    return source_response, source_receipt, consultation_receipt


def _require_rejected(call, expected: str) -> None:
    try:
        call()
    except RuntimeError as exc:
        _require(expected in str(exc), f'unexpected rejection: {exc}')
        return
    raise AssertionError(f'consultation recovery source accepted invalid {expected}')


def main() -> int:
    cfg = load_platform_yaml('grok')
    attachment = (cfg.get('workflow') or {}).get('attachment') or {}
    trigger_key = attachment.get('trigger')
    _require(trigger_key == 'attach_trigger', 'Grok attachment trigger drifted')
    _require(
        attachment.get('open_method') == 'mapped_pointer_activate',
        'Grok attachment open method drifted',
    )
    _require(
        'open_key' not in attachment,
        'Grok mapped-pointer attachment unexpectedly declares open_key',
    )

    ready = element_operation(trigger_key, ['showing', 'enabled'])
    _require(
        ready == {
            'method': 'mapped_pointer_activate',
            'primitives': ['mapped_pointer_activate'],
            'allowed_now': ['mapped_pointer_activate'],
            'forbidden': ['activate', 'click', 'focus', 'hover'],
        },
        'Grok attachment trigger does not expose the exact YAML pointer operation',
    )
    expanded = element_operation(trigger_key, ['showing', 'expanded', 'enabled'])
    _require(
        expanded is not None and expanded['allowed_now'] == [],
        'Grok expanded attachment trigger does not refuse a second toggle',
    )
    _require(
        element_operation('upload_files_item', ['showing', 'enabled']) is None,
        'Grok manual operation leaked beyond the attachment trigger',
    )
    for key in ('space', 'Space', 'ctrl+l', 'ctrl+a', 'Return', 'ctrl+End'):
        _require(
            not key_requires_state(key),
            f'Grok unrelated raw/native key path was captured: {key}',
        )

    driver_source = _function_source(
        DRIVER_PATH,
        'attach_files',
        owner='GrokConsultationDriver',
    )
    _require(
        driver_source.count('self.runtime.mapped_pointer_activate(trigger)') == 1,
        'Grok retained driver does not invoke the exact pointer operation once',
    )
    _require(
        "open_method != 'mapped_pointer_activate'" in driver_source,
        'Grok retained driver does not enforce the YAML pointer method',
    )
    for forbidden in ('atspi_focus', 'focus_and_key_open', 'press(open_key)'):
        _require(
            forbidden not in driver_source,
            f'Grok retained driver still exposes forbidden attachment path: {forbidden}',
        )
    selection_source = _function_source(
        DRIVER_PATH,
        '_open_selection_menu',
        owner='_GrokInlineBase',
    )
    _require(
        selection_source.count(
            'self.runtime.mapped_pointer_activate(trigger)'
        ) == 1,
        'Grok retained selection driver does not support the exact pointer operation',
    )

    tool_source = _function_source(
        TAEY_EXTRACT_PATH,
        'consult_extract_action_tool',
    )
    normalized_source = _function_source(
        TAEY_EXTRACT_PATH,
        '_normalized_action',
        owner='TaeyConsultExtractionSeat',
    )
    validated_source = _function_source(
        TAEY_EXTRACT_PATH,
        '_validated_action',
        owner='TaeyConsultExtractionSeat',
    )
    required_source = _function_source(
        TAEY_EXTRACT_PATH,
        '_required_full_consult_action',
        owner='TaeyConsultExtractionSeat',
    )
    actuator_source = _function_source(
        TAEY_EXTRACT_PATH,
        '_actuate_semantic_control',
        owner='TaeyConsultExtractionSeat',
    )
    execute_source = _function_source(
        TAEY_EXTRACT_PATH,
        '_execute_full_consult_action',
        owner='TaeyConsultExtractionSeat',
    )
    _require(
        tool_source.count("'mapped_pointer_activate'") == 1,
        'consult_extract_action tool enum does not expose pointer activation once',
    )
    _require(
        normalized_source.count("'mapped_pointer_activate'") >= 3
        and "name != 'attach_trigger'" in normalized_source,
        'consult_extract_action normalization does not restrict pointer activation',
    )
    _require(
        validated_source.count("'mapped_pointer_activate'") == 2,
        'consult_extract_action validation does not require live pointer state',
    )
    for method in (
        'atspi_menu',
        'click',
        'focus_and_key_open',
        'mapped_pointer_activate',
    ):
        _require(
            f"'{method}'" in required_source,
            f'full-consult attachment method {method} is not explicit',
        )
    _require(
        "'action': 'mapped_pointer_activate'" in required_source
        and "open_method in {'atspi_menu', 'click'}" in required_source
        and 'has unsupported' in required_source
        and "or 'click'" not in required_source,
        'full-consult required action can still fall through to click',
    )
    _require(
        actuator_source.count(
            'self.runtime.mapped_pointer_activate('
        ) == 2
        and "action == 'mapped_pointer_activate'" in actuator_source,
        'full-consult actuator does not bind both exact-control shapes to pointer',
    )
    _require(
        "'performed_primitive': 'mapped_pointer_activate'" in actuator_source,
        'full-consult pointer actuator does not return exact primitive evidence',
    )
    _require(
        "'mapped_pointer_activate'" in execute_source,
        'full-consult dispatch does not accept the exact pointer action',
    )

    content = _send_content(
        'grok',
        ':5',
        Path('/frozen/bundle-a.md'),
        Path('/frozen/bundle-b.md'),
        Path('/frozen/prompt.txt'),
    )
    semantic_step = (
        'operate element=attach_trigger and require '
        'performed_primitive=mapped_pointer_activate; observe scope=menu_snapshot'
    )
    _require(
        content.count(semantic_step) == 2,
        'Grok Bundle A/B must each use one mapped-pointer attachment operation',
    )
    _require(
        content.count(
            'observe scope=menu_snapshot; require upload_files_item match_count 1 '
            'with name exactly Upload a file'
        ) == 2,
        'Grok Bundle A/B must each prove the fresh YAML-owned menu target',
    )
    _require(
        'focus element=attach_trigger' not in content and 'key space' not in content,
        'Grok worker card still exposes a focus/key attachment path',
    )

    legacy_recovery = _recovery_content(
        'grok',
        ':5',
        'usage_limit_updated',
        'a' * 64,
    )
    _require(
        hashlib.sha256(legacy_recovery.encode('utf-8')).hexdigest()
        == '8b199efdfdc2bb477b69d4a115dbba21d8bc35bc5123e97664f296d2f560ab2c',
        'existing manual-worker recovery content changed',
    )
    consultation_recovery = _recovery_content(
        'grok',
        ':5',
        'usage_limit_updated',
        'a' * 64,
        'b' * 64,
    )
    _require(
        'Source evidence SHA-256 is ' + ('a' * 64) in consultation_recovery
        and 'Source consultation receipt SHA-256 is ' + ('b' * 64)
        in consultation_recovery,
        'one-call recovery content does not bind both source hashes',
    )
    parsed = build_parser().parse_args([
        'recover',
        '--platform', 'grok',
        '--display', ':5',
        '--seat-id', 'fixture',
        '--artifact-root', '/tmp/uncreated-fixture',
        '--exception-key', 'usage_limit_updated',
        '--source-response-json', '/tmp/worker_response.json',
        '--source-consultation-receipt', '/tmp/consultation_receipt.json',
    ])
    _require(
        parsed.source_consultation_receipt == '/tmp/consultation_receipt.json',
        'recover parser does not expose the explicit consultation receipt',
    )

    worker_main_source = _function_source(
        REPO_ROOT / 'scripts/run_manual_chat_worker.py',
        'main',
    )
    _require(
        worker_main_source.index('_validate_consultation_recovery_source(')
        < worker_main_source.index('root.mkdir(mode=0o700)')
        < worker_main_source.index('_invoke('),
        'consultation recovery validation does not precede artifact creation and invoke',
    )

    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        source_response, source_receipt, consultation_receipt = (
            _write_consultation_recovery_fixture(tmp / 'valid')
        )
        accepted_sha256 = _validate_consultation_recovery_source(
            source_response=source_response,
            source_receipt=source_receipt,
            consultation_receipt=consultation_receipt,
            platform='grok',
            display=':5',
            exception_key='usage_limit_updated',
        )
        _require(
            accepted_sha256 == _sha256(consultation_receipt),
            'valid one-call recovery source returned the wrong receipt hash',
        )

        wrong_display = _write_consultation_recovery_fixture(
            tmp / 'wrong-display',
            display=':6',
        )
        _require_rejected(
            lambda: _validate_consultation_recovery_source(
                source_response=wrong_display[0],
                source_receipt=wrong_display[1],
                consultation_receipt=wrong_display[2],
                platform='grok',
                display=':5',
                exception_key='usage_limit_updated',
            ),
            'display',
        )
        _require_rejected(
            lambda: _validate_consultation_recovery_source(
                source_response=source_response,
                source_receipt=source_receipt.replace(
                    _sha256(consultation_receipt),
                    '0' * 64,
                ),
                consultation_receipt=consultation_receipt,
                platform='grok',
                display=':5',
                exception_key='usage_limit_updated',
            ),
            'sibling receipt SHA-256',
        )

        invalid_cases = {
            'platform': lambda payload: payload.update(platform='gemini'),
            'response_text': lambda payload: payload.update(response_text='not empty'),
            'URL prefix': lambda payload: payload.update(
                session_url_after='https://example.invalid/c/fixture'
            ),
            'send or monitor evidence': lambda payload: payload['steps'][0][
                'evidence'
            ].update(click_returned=False),
            'prior retry or recovery': lambda payload: payload['steps'].insert(
                1,
                {'step': 'retry', 'success': True, 'evidence': {}},
            ),
            'exact send_action steps': lambda payload: payload['steps'].insert(
                1,
                {
                    'step': 'send_action',
                    'success': True,
                    'evidence': {'click_returned': True},
                },
            ),
            'singleton counts': lambda payload: payload['steps'][4]['evidence'][
                'snapshot'
            ]['mapped'].update(retry_button=[{}, {}]),
            'still maps Stop': lambda payload: payload['steps'][4]['evidence'][
                'snapshot'
            ]['mapped'].update(stop_button=[{}]),
        }
        for index, (expected, mutate_payload) in enumerate(invalid_cases.items()):
            invalid = _write_consultation_recovery_fixture(
                tmp / f'invalid-{index}',
                mutate_payload=mutate_payload,
            )
            _require_rejected(
                lambda invalid=invalid: _validate_consultation_recovery_source(
                    source_response=invalid[0],
                    source_receipt=invalid[1],
                    consultation_receipt=invalid[2],
                    platform='grok',
                    display=':5',
                    exception_key='usage_limit_updated',
                ),
                expected,
            )

        other = _write_consultation_recovery_fixture(tmp / 'other')
        _require_rejected(
            lambda: _validate_consultation_recovery_source(
                source_response=source_response,
                source_receipt=source_receipt.replace(
                    str(consultation_receipt),
                    str(other[2]),
                ).replace(_sha256(consultation_receipt), _sha256(other[2])),
                consultation_receipt=other[2],
                platform='grok',
                display=':5',
                exception_key='usage_limit_updated',
            ),
            'exact sibling',
        )

    print('grok mapped-pointer and one-call recovery contracts: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
