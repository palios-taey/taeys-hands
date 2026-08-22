from __future__ import annotations

from typing import Any

from consultation_v2.yaml_contract import load_platform_yaml


def _attachment_rule() -> str:
    cfg = load_platform_yaml('grok')
    attachment = (cfg.get('workflow') or {}).get('attachment') or {}
    if not isinstance(attachment, dict):
        raise ValueError('grok workflow.attachment must be a mapping')
    trigger_key = attachment.get('trigger')
    if not isinstance(trigger_key, str) or not trigger_key:
        raise ValueError('grok attachment trigger is not declared')
    if attachment.get('open_method') != 'mapped_pointer_activate':
        raise ValueError(
            'grok attachment open_method must be mapped_pointer_activate'
        )
    if 'open_key' in attachment:
        raise ValueError(
            'grok mapped_pointer_activate attachment must not declare open_key'
        )
    return trigger_key


def element_operation(
    element_key: str,
    states: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    del context
    trigger_key = _attachment_rule()
    if element_key != trigger_key:
        return None
    normalized_states = {
        str(state).strip().lower().replace('_', ' ') for state in states
    }
    allowed_now = (
        [] if 'expanded' in normalized_states else ['mapped_pointer_activate']
    )
    return {
        'method': 'mapped_pointer_activate',
        'primitives': ['mapped_pointer_activate'],
        'allowed_now': allowed_now,
        'forbidden': ['activate', 'click', 'focus', 'hover'],
    }


def key_requires_state(_key: str) -> bool:
    return False


__all__ = [
    'element_operation',
    'key_requires_state',
]
