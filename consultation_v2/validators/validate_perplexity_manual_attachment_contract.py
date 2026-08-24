#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.platforms.perplexity.manual import (
    element_operation,
    key_requires_state,
)
from consultation_v2.yaml_contract import load_platform_yaml
from scripts.run_manual_chat_worker import _send_content


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    cfg = load_platform_yaml('perplexity')
    attachment = (cfg.get('workflow') or {}).get('attachment') or {}
    trigger_key = attachment.get('trigger')
    _require(trigger_key == 'attach_trigger', 'Perplexity attachment trigger drifted')
    _require(
        attachment.get('open_method') == 'mapped_pointer_activate',
        'Perplexity attachment open method drifted',
    )
    _require(
        attachment.get('scope') == 'app_root_snapshot',
        'Perplexity attachment observation scope drifted',
    )
    _require(
        'open_key' not in attachment,
        'Perplexity mapped-pointer attachment unexpectedly declares open_key',
    )

    ready = element_operation(trigger_key, ['showing', 'enabled'])
    _require(
        ready == {
            'method': 'mapped_pointer_activate',
            'primitives': ['mapped_pointer_activate'],
            'allowed_now': ['mapped_pointer_activate'],
            'forbidden': ['activate', 'click', 'focus', 'hover'],
        },
        'Perplexity attachment trigger does not expose its YAML pointer operation',
    )
    expanded = element_operation(trigger_key, ['showing', 'expanded', 'enabled'])
    _require(
        expanded is not None and expanded['allowed_now'] == [],
        'Perplexity expanded attachment trigger does not refuse a second toggle',
    )
    _require(
        element_operation('upload_files_item', ['showing', 'enabled']) is None,
        'Perplexity manual operation leaked onto the upload menu target',
    )
    for key in ('space', 'Space', 'ctrl+l', 'ctrl+a', 'Return', 'ctrl+End'):
        _require(
            not key_requires_state(key),
            f'Perplexity unrelated raw/native key path was captured: {key}',
        )

    content = _send_content(
        'perplexity',
        ':6',
        Path('/frozen/bundle-a.md'),
        Path('/frozen/bundle-b.md'),
        Path('/frozen/prompt.txt'),
    )
    semantic_step = (
        'operate element=attach_trigger and require '
        'performed_primitive=mapped_pointer_activate; observe '
        'scope=app_root_snapshot'
    )
    _require(
        content.count(semantic_step) == 2,
        'Perplexity Bundle A/B must each use the YAML pointer attachment operation',
    )
    _require(
        content.count(
            'observe scope=app_root_snapshot; require upload_files_item '
            'match_count 1 with name exactly Upload files or images'
        ) == 2,
        'Perplexity Bundle A/B must each prove the live app-root upload target',
    )
    _require(
        'focus element=attach_trigger' not in content and 'key space' not in content,
        'Perplexity worker card still exposes a focus/key attachment path',
    )
    print('perplexity mapped-pointer attachment contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
