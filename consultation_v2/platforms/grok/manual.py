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


def _pre_send_pointer_recovery_rule() -> tuple[str, frozenset[str]]:
    cfg = load_platform_yaml('grok')
    pre_send = ((cfg.get('workflow') or {}).get('pre_send') or {})
    exceptions = pre_send.get('exceptions') if isinstance(pre_send, dict) else None
    if not isinstance(exceptions, dict):
        raise ValueError('grok workflow.pre_send.exceptions must be a mapping')
    pointer_rules: list[tuple[str, frozenset[str]]] = []
    for exception in exceptions.values():
        if not isinstance(exception, dict):
            raise ValueError('grok pre-send exception must be a mapping')
        recovery = exception.get('recovery')
        if not isinstance(recovery, dict):
            raise ValueError('grok pre-send exception recovery must be a mapping')
        if recovery.get('action') != 'operate':
            continue
        if recovery.get('expected_primitive') != 'mapped_pointer_activate':
            raise ValueError(
                'grok operate recovery must expect mapped_pointer_activate'
            )
        element = recovery.get('element')
        detect = exception.get('detect')
        detect_states = exception.get('detect_states')
        if (
            not isinstance(element, str)
            or not element
            or not isinstance(detect, list)
            or element not in detect
            or not isinstance(detect_states, dict)
        ):
            raise ValueError('grok operate recovery element is not exactly detected')
        states = detect_states.get(element)
        if (
            not isinstance(states, list)
            or not states
            or not all(isinstance(state, str) and state for state in states)
        ):
            raise ValueError('grok operate recovery states are invalid')
        pointer_rules.append((
            element,
            frozenset(
                state.strip().lower().replace('_', ' ') for state in states
            ),
        ))
    if len(pointer_rules) != 1:
        raise ValueError('grok must declare exactly one pre-send pointer recovery')
    return pointer_rules[0]


def element_operation(
    element_key: str,
    states: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    del context
    attachment_trigger = _attachment_rule()
    normalized_states = {
        str(state).strip().lower().replace('_', ' ') for state in states
    }
    if element_key == attachment_trigger:
        allowed_now = (
            [] if 'expanded' in normalized_states else ['mapped_pointer_activate']
        )
    else:
        recovery_element, recovery_states = _pre_send_pointer_recovery_rule()
        if element_key != recovery_element:
            return None
        allowed_now = (
            ['mapped_pointer_activate']
            if recovery_states.issubset(normalized_states)
            else []
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
