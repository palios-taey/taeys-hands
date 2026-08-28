#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
DRIVER_PATH = REPO_ROOT / 'consultation_v2/platforms/grok/driver.py'
TAEY_EXTRACT_PATH = REPO_ROOT / 'consultation_v2/taey_extract.py'

from consultation_v2.platforms.grok.manual import (
    element_operation,
    key_requires_state,
)
from consultation_v2.yaml_contract import load_platform_yaml
from scripts.run_manual_chat_worker import _send_content


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
    post_submit = attachment.get('post_submit') or {}
    _require(
        post_submit == {
            'scope': 'document',
            'elements': ['uploaded_file_chip', 'remove_attachment'],
            'observation': {
                'refresh_policy': 'invalidate_reacquire',
                'stable_cycles': 2,
                'interval_ms': 250,
                'timeout_ms': 15000,
            },
        },
        'Grok attachment exact-count post-submit contract drifted',
    )
    _require(
        'attach_present' not in (cfg.get('validation') or {}),
        'Grok retained the superseded generic attachment-presence validation',
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
        driver_source.count('_wait_for_grok_native_dialog_postcondition(') == 3
        and driver_source.count("self.runtime.press('ctrl+l')") == 1
        and driver_source.count('self.runtime.paste(abs_path)') == 1
        and driver_source.count("self.runtime.press('Return')") == 1,
        'Grok retained driver changed the proven native chooser proof path',
    )
    _require(
        'for attachment_index, file_path in enumerate(request.attachments, start=1)'
        in driver_source
        and 'expected_count=0' in driver_source
        and 'expected_count=attachment_index' in driver_source,
        'Grok retained driver does not prove the zero-then-requested attachment count',
    )
    _require(
        "wait_for_validation(\n                'attach_present'" not in driver_source,
        'Grok retained driver still accepts generic attachment presence',
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
    count_source = _function_source(
        DRIVER_PATH,
        '_wait_for_exact_attachment_count',
        owner='GrokConsultationDriver',
    )
    for required in (
        "last_snapshot = self.runtime.snapshot()",
        "last_snapshot.mapped.get('uploaded_file_chip')",
        "last_snapshot.mapped.get('remove_attachment')",
        "'revision': last_snapshot.revision",
        "'elapsed_ms':",
        "'stable_cycles_required': stable_cycles",
        "'classification': classification",
        "'absent_count'",
        "'stale_count'",
        'return False, last_snapshot, samples',
    ):
        _require(
            required in count_source,
            f'Grok exact attachment-count receipt is missing {required}',
        )
    _require(
        "classification in {'inconsistent_mapped_counts', 'excess_count'}"
        in count_source,
        'Grok exact attachment-count proof does not fail loud on ambiguous excess',
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
    print('grok mapped-pointer attachment contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
