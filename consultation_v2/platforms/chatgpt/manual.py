from __future__ import annotations

from typing import Any

from consultation_v2.types import Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


def _attachment_rule() -> tuple[str, str]:
    cfg = load_platform_yaml('chatgpt')
    attachment = (cfg.get('workflow') or {}).get('attachment') or {}
    if not isinstance(attachment, dict):
        raise ValueError('chatgpt workflow.attachment must be a mapping')
    trigger_key = attachment.get('trigger')
    if not isinstance(trigger_key, str) or not trigger_key:
        raise ValueError('chatgpt attachment trigger is not declared')
    if attachment.get('open_method') != 'focus_and_key_open':
        raise ValueError('chatgpt attachment open_method must be focus_and_key_open')
    open_key = attachment.get('open_key')
    if not isinstance(open_key, str) or not open_key:
        raise ValueError('chatgpt focus_and_key_open requires an exact open_key')
    return trigger_key, open_key


def element_operation(
    element_key: str,
    states: list[str],
) -> dict[str, Any] | None:
    trigger_key, open_key = _attachment_rule()
    if element_key != trigger_key:
        return None
    normalized_states = {
        str(state).strip().lower().replace('_', ' ') for state in states
    }
    if 'expanded' in normalized_states:
        allowed_now: list[str] = []
    elif 'focused' in normalized_states:
        allowed_now = [f'key:{open_key}']
    else:
        allowed_now = ['focus']
    return {
        'method': 'focus_and_key_open',
        'primitives': ['focus', f'key:{open_key}'],
        'allowed_now': allowed_now,
        'forbidden': ['activate', 'click'],
    }


def key_requires_state(key: str) -> bool:
    _trigger_key, open_key = _attachment_rule()
    if key.casefold() == open_key.casefold() and key != open_key:
        raise ValueError(
            f'chatgpt attachment opening key must exactly equal YAML {open_key!r}'
        )
    return key == open_key


def validate_key_state(key: str, snapshot: Snapshot) -> None:
    if snapshot.platform != 'chatgpt':
        raise ValueError(
            f'ChatGPT key validation received platform {snapshot.platform!r}'
        )
    trigger_key, open_key = _attachment_rule()
    if key != open_key:
        raise ValueError(
            f'chatgpt attachment opening key must exactly equal YAML {open_key!r}'
        )
    matches = list(snapshot.mapped.get(trigger_key) or ())
    if len(matches) != 1:
        raise ValueError(
            f'chatgpt {trigger_key} matched {len(matches)} elements; expected one'
        )
    declared = element_operation(trigger_key, list(matches[0].states))
    expected = f'key:{open_key}'
    if declared is None or expected not in declared['allowed_now']:
        raise ValueError(
            f'chatgpt YAML opening key {key!r} is not allowed in the fresh '
            f'trigger state (allowed_now='
            f'{declared["allowed_now"] if declared else []})'
        )


__all__ = ['element_operation', 'key_requires_state', 'validate_key_state']
