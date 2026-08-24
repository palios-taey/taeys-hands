from __future__ import annotations

from typing import Any

from consultation_v2.yaml_contract import get_extraction, load_platform_yaml


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


def _download_elements() -> tuple[tuple[str, ...], str]:
    workflow = get_extraction('perplexity', 'research_report')
    if workflow is None:
        raise ValueError('perplexity research_report extraction is not declared')
    triggers = [
        step.element
        for step in workflow.steps
        if step.action == 'click' and step.element
    ]
    targets = [
        step.element
        for step in workflow.steps
        if step.action == 'download' and step.element
    ]
    if len(triggers) < 1 or len(targets) != 1:
        raise ValueError(
            'perplexity research_report extraction requires one or more ordered '
            'click triggers and one download target'
        )
    return tuple(triggers), targets[0]


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

    trigger_keys, target_key = _download_elements()
    if element_key not in {*trigger_keys, target_key}:
        return None
    allowed_now = (
        []
        if element_key in trigger_keys and 'expanded' in normalized_states
        else ['mapped_pointer_activate']
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
