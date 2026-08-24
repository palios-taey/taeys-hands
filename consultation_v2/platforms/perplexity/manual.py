from __future__ import annotations

from typing import Any

from consultation_v2.yaml_contract import get_extraction


def _download_elements() -> tuple[str, str]:
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
    if len(triggers) != 1 or len(targets) != 1:
        raise ValueError(
            'perplexity research_report extraction requires one click trigger '
            'and one download target'
        )
    return triggers[0], targets[0]


def element_operation(
    element_key: str,
    states: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    del context
    trigger_key, target_key = _download_elements()
    if element_key not in {trigger_key, target_key}:
        return None
    normalized_states = {
        str(state).strip().lower().replace('_', ' ') for state in states
    }
    allowed_now = (
        []
        if element_key == trigger_key and 'expanded' in normalized_states
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
