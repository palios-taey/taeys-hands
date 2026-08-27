from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from consultation_v2.types import ElementRef, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


_CARD_SCHEMA = 'taey.gemini_dr_send_phase.v1'
_SHA256_RE = re.compile(r'[0-9a-f]{64}')
_WAITING_PHASES = {
    'awaiting_initial_send',
    'awaiting_start_research',
    'awaiting_research_stop',
}


def _exact_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'gemini {label} must be an exact non-empty string')
    return value


def _single_element_key(value: object, label: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f'gemini {label} must be a mapping')
    elements = value.get('elements')
    if (
        not isinstance(elements, list)
        or len(elements) != 1
        or not isinstance(elements[0], str)
        or not elements[0]
        or elements[0] != elements[0].strip()
    ):
        raise ValueError(f'gemini {label}.elements must contain one exact key')
    return elements[0]


def _deep_research_rule() -> dict[str, Any]:
    cfg = load_platform_yaml('gemini')
    workflow = cfg.get('workflow') or {}
    full_consult = workflow.get('full_consult') or {}
    steps = full_consult.get('steps') or {}
    if not isinstance(steps, dict):
        raise ValueError('gemini workflow.full_consult.steps must be a mapping')

    submit = steps.get('submit') or {}
    if not isinstance(submit, dict):
        raise ValueError('gemini workflow.full_consult.steps.submit must be a mapping')
    if submit.get('action') != 'focus_and_key':
        raise ValueError('gemini submit action must be focus_and_key')
    send_key = _exact_string(
        submit.get('key'),
        'workflow.full_consult.steps.submit.key',
    )
    send_element = _single_element_key(
        submit,
        'workflow.full_consult.steps.submit',
    )
    start_element = _single_element_key(
        steps.get('post_submit'),
        'workflow.full_consult.steps.post_submit',
    )
    stop_element = _single_element_key(
        steps.get('completion'),
        'workflow.full_consult.steps.completion',
    )

    send = workflow.get('send') or {}
    if not isinstance(send, dict):
        raise ValueError('gemini workflow.send must be a mapping')
    if send.get('trigger') != send_element:
        raise ValueError('gemini workflow.send.trigger must equal submit element')
    if send.get('post_send_key') != start_element:
        raise ValueError(
            'gemini workflow.send.post_send_key must equal post_submit element'
        )
    if send.get('stop_key') != stop_element:
        raise ValueError('gemini workflow.send.stop_key must equal completion element')

    selection = workflow.get('selection') or {}
    menus = selection.get('menus') or {}
    mode = menus.get('mode') or {}
    tools = menus.get('tools') or {}
    mode_trigger = _exact_string(
        (mode.get('operate') or {}).get('trigger'),
        'Extended mode trigger',
    )
    extended = ((mode.get('options') or {}).get('extended') or {})
    extended_names = extended.get('active_trigger_names')
    if (
        not isinstance(extended_names, list)
        or not extended_names
        or not all(
            isinstance(name, str) and name and name == name.strip()
            for name in extended_names
        )
    ):
        raise ValueError(
            'gemini Extended mode must declare exact active_trigger_names'
        )
    deep_research = ((tools.get('options') or {}).get('deep_research') or {})
    active_element = _exact_string(
        deep_research.get('active_element'),
        'Deep Research active_element',
    )
    composer_input = _exact_string(
        (workflow.get('prompt') or {}).get('input'),
        'workflow.prompt.input',
    )

    element_map = ((cfg.get('tree') or {}).get('element_map') or {})
    required_keys = {
        send_element,
        start_element,
        stop_element,
        active_element,
        composer_input,
        mode_trigger,
    }
    missing = sorted(required_keys - set(element_map))
    if missing:
        raise ValueError(f'gemini Deep Research send keys are unmapped: {missing}')

    return {
        'send_key': send_key,
        'send_element': send_element,
        'start_element': start_element,
        'stop_element': stop_element,
        'active_element': active_element,
        'composer_input': composer_input,
        'mode_trigger': mode_trigger,
        'extended_names': tuple(extended_names),
    }


def _normalized_states(element: ElementRef) -> set[str]:
    return {
        str(state).strip().lower().replace('_', ' ')
        for state in element.states
    }


def _singleton(snapshot: Snapshot, key: str) -> ElementRef | None:
    matches = list(snapshot.mapped.get(key) or ())
    if len(matches) > 1:
        raise ValueError(
            f'gemini Deep Research send phase requires exact singleton {key!r}; '
            f'observed {len(matches)}'
        )
    return matches[0] if matches else None


def _initial_send_ready(snapshot: Snapshot, rule: dict[str, Any]) -> bool:
    input_element = _singleton(snapshot, str(rule['composer_input']))
    mode_picker = _singleton(snapshot, str(rule['mode_trigger']))
    active_element = _singleton(snapshot, str(rule['active_element']))
    send_element = _singleton(snapshot, str(rule['send_element']))
    if not all((input_element, mode_picker, active_element, send_element)):
        return False
    if mode_picker.name not in rule['extended_names']:
        return False
    send_states = _normalized_states(send_element)
    return 'focused' in send_states and 'enabled' in send_states


def _actionable(element: ElementRef | None) -> bool:
    if element is None:
        return False
    states = _normalized_states(element)
    return 'enabled' in states and 'showing' in states


def _card_sha256(card: dict[str, Any]) -> str:
    encoded = json.dumps(
        card,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _card(
    *,
    display: str,
    phase: str,
    snapshot_revision: str,
    allowed: dict[str, str] | None,
    next_phase: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'schema': _CARD_SCHEMA,
        'platform': 'gemini',
        'display': display,
        'phase': phase,
        'snapshot_revision': snapshot_revision,
        'allowed': allowed,
        'next_phase': next_phase,
    }
    payload['card_sha256'] = _card_sha256(payload)
    return payload


def deep_research_send_phase_card(
    snapshot: Snapshot,
    *,
    scope: str,
    phase: str,
    snapshot_revision: str,
    display: str,
) -> dict[str, Any] | None:
    if snapshot.platform != 'gemini':
        raise ValueError('Gemini Deep Research send phase requires platform gemini')
    if scope != 'base':
        raise ValueError('Gemini Deep Research send phase requires base scope')
    if phase not in _WAITING_PHASES:
        raise ValueError(f'unknown Gemini Deep Research send phase {phase!r}')
    if not isinstance(snapshot_revision, str) or not _SHA256_RE.fullmatch(
        snapshot_revision
    ):
        raise ValueError(
            'Gemini Deep Research send phase requires one lowercase SHA-256 revision'
        )
    if not isinstance(display, str) or not display or display != display.strip():
        raise ValueError(
            'Gemini Deep Research send phase requires an exact display identity'
        )

    rule = _deep_research_rule()
    allowed: dict[str, str] | None = {'action': 'observe', 'scope': 'base'}
    card_phase = phase
    next_phase: str | None = None

    if phase == 'awaiting_initial_send':
        if not _initial_send_ready(snapshot, rule):
            return None
        card_phase = 'ready_initial_send'
        allowed = {'action': 'key', 'key': str(rule['send_key'])}
        next_phase = 'awaiting_start_research'
    elif phase == 'awaiting_start_research':
        start_element = _singleton(snapshot, str(rule['start_element']))
        _singleton(snapshot, str(rule['stop_element']))
        if _actionable(start_element):
            card_phase = 'ready_start_research'
            allowed = {
                'action': 'click',
                'element': str(rule['start_element']),
            }
            next_phase = 'awaiting_research_stop'
    elif phase == 'awaiting_research_stop':
        stop_element = _singleton(snapshot, str(rule['stop_element']))
        _singleton(snapshot, str(rule['start_element']))
        if _actionable(stop_element):
            card_phase = 'monitor_ready'
            allowed = None

    return _card(
        display=display,
        phase=card_phase,
        snapshot_revision=snapshot_revision,
        allowed=allowed,
        next_phase=next_phase,
    )


__all__ = ['deep_research_send_phase_card']
