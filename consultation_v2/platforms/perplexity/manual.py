from __future__ import annotations

from typing import Any

from consultation_v2.yaml_contract import load_platform_yaml


def _attachment_trigger() -> str:
    cfg = load_platform_yaml('perplexity')
    attachment = (cfg.get('workflow') or {}).get('attachment') or {}
    if not isinstance(attachment, dict):
        raise ValueError('perplexity workflow.attachment must be a mapping')
    trigger_key = attachment.get('trigger')
    if not isinstance(trigger_key, str) or not trigger_key:
        raise ValueError('perplexity attachment trigger is not declared')
    if attachment.get('open_method') != 'mapped_pointer_activate':
        raise ValueError(
            'perplexity attachment open_method must be mapped_pointer_activate'
        )
    if 'open_key' in attachment:
        raise ValueError(
            'perplexity mapped_pointer_activate attachment must not declare open_key'
        )
    return trigger_key


def element_operation(
    element_key: str,
    states: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    del context
    normalized_states = {
        str(state).strip().lower().replace('_', ' ') for state in states
    }
    attachment_trigger = _attachment_trigger()
    if element_key == attachment_trigger:
        allowed_now = (
            []
            if 'expanded' in normalized_states
            else ['mapped_pointer_activate']
        )
        return {
            'method': 'mapped_pointer_activate',
            'primitives': ['mapped_pointer_activate'],
            'allowed_now': allowed_now,
            'forbidden': ['activate', 'click', 'focus', 'hover'],
        }

    return None


def key_requires_state(_key: str) -> bool:
    return False


__all__ = [
    'element_operation',
    'key_requires_state',
]
