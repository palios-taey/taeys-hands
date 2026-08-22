#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.platforms.grok.manual import (
    element_operation,
    key_requires_state,
    validate_key_state,
)
from consultation_v2.types import ElementRef, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml
from scripts.run_manual_chat_worker import _send_content


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _expect_value_error(action: Callable[[], object], message: str) -> None:
    try:
        action()
    except ValueError:
        return
    raise AssertionError(message)


def _trigger_ref(trigger_key: str, states: list[str]) -> ElementRef:
    return ElementRef(
        key=trigger_key,
        name='Attach',
        role='push button',
        x=None,
        y=None,
        states=states,
    )


def main() -> int:
    cfg = load_platform_yaml('grok')
    attachment = (cfg.get('workflow') or {}).get('attachment') or {}
    trigger_key = attachment.get('trigger')
    open_key = attachment.get('open_key')
    _require(trigger_key == 'attach_trigger', 'Grok attachment trigger drifted')
    _require(open_key == 'space', 'Grok attachment open key drifted')

    ready = element_operation(trigger_key, ['showing', 'enabled'])
    _require(
        ready == {
            'method': 'focus_and_key_open',
            'primitives': ['focus', f'key:{open_key}'],
            'allowed_now': ['focus'],
            'forbidden': ['activate', 'click'],
        },
        'Grok attachment trigger does not expose the exact YAML semantic operation',
    )
    focused = element_operation(trigger_key, ['showing', 'focused', 'enabled'])
    _require(
        focused is not None and focused['allowed_now'] == [f'key:{open_key}'],
        'Grok focused attachment trigger does not expose its exact YAML open key',
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

    _require(key_requires_state(open_key), 'Grok YAML open key lost state validation')
    _expect_value_error(
        lambda: key_requires_state('Space'),
        'Grok attachment opening key accepted a non-exact spelling',
    )
    for key in ('ctrl+l', 'ctrl+a', 'Return', 'ctrl+End'):
        _require(
            not key_requires_state(key),
            f'Grok unrelated raw/native key path was captured: {key}',
        )

    focused_snapshot = Snapshot(
        platform='grok',
        url='https://grok.com/',
        mapped={
            trigger_key: [
                _trigger_ref(trigger_key, ['showing', 'focused', 'enabled'])
            ]
        },
    )
    validate_key_state(open_key, focused_snapshot)
    missing_snapshot = Snapshot(platform='grok', url='https://grok.com/')
    _expect_value_error(
        lambda: validate_key_state(open_key, missing_snapshot),
        'Grok raw opening key accepted a missing attachment trigger',
    )
    duplicate_snapshot = Snapshot(
        platform='grok',
        url='https://grok.com/',
        mapped={
            trigger_key: [
                _trigger_ref(trigger_key, ['showing', 'focused', 'enabled']),
                _trigger_ref(trigger_key, ['showing', 'focused', 'enabled']),
            ]
        },
    )
    _expect_value_error(
        lambda: validate_key_state(open_key, duplicate_snapshot),
        'Grok raw opening key accepted duplicate attachment triggers',
    )
    foreign_snapshot = Snapshot(platform='chatgpt', url='https://chatgpt.com/')
    _expect_value_error(
        lambda: validate_key_state(open_key, foreign_snapshot),
        'Grok key-state validator accepted a foreign-platform snapshot',
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
        'performed_primitive=focus_and_key_open; observe scope=menu_snapshot'
    )
    _require(
        content.count(semantic_step) == 2,
        'Grok Bundle A/B must each use one attachment semantic operation',
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
        'Grok worker card still exposes an internal attachment primitive',
    )
    print('grok manual attachment contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
