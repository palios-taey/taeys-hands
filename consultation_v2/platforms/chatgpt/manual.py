from __future__ import annotations

from typing import Any

from consultation_v2.types import Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


def _navigation_rule() -> tuple[str, str, str, str]:
    cfg = load_platform_yaml('chatgpt')
    navigation = (cfg.get('workflow') or {}).get('navigation') or {}
    if not isinstance(navigation, dict):
        raise ValueError('chatgpt workflow.navigation must be a mapping')
    trigger_key = navigation.get('trigger')
    if not isinstance(trigger_key, str) or not trigger_key:
        raise ValueError('chatgpt navigation trigger is not declared')
    if navigation.get('method') != 'focus_select_paste_submit':
        raise ValueError(
            'chatgpt navigation method must be focus_select_paste_submit'
        )
    select_key = navigation.get('select_key')
    submit_key = navigation.get('submit_key')
    if not isinstance(select_key, str) or not select_key:
        raise ValueError('chatgpt navigation select_key must be exact')
    if not isinstance(submit_key, str) or not submit_key:
        raise ValueError('chatgpt navigation submit_key must be exact')
    if navigation.get('paste_value') != 'urls.fresh':
        raise ValueError('chatgpt navigation paste_value must be urls.fresh')
    fresh_url = (cfg.get('urls') or {}).get('fresh')
    if not isinstance(fresh_url, str) or not fresh_url:
        raise ValueError('chatgpt urls.fresh must be exact')
    return trigger_key, select_key, fresh_url, submit_key


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
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    navigation_key, select_key, fresh_url, submit_key = _navigation_rule()
    normalized_states = {
        str(state).strip().lower().replace('_', ' ') for state in states
    }
    if element_key == navigation_key:
        current = dict(context or {})
        current_text = str(current.get('text') or '')
        selections = current.get('text_selections') or []
        full_selection = bool(current_text) and any(
            isinstance(selection, dict)
            and selection.get('start') == 0
            and selection.get('end') == len(current_text)
            for selection in selections
        )
        if 'focused' not in normalized_states:
            allowed_now = ['focus']
        elif current_text == fresh_url:
            allowed_now = [f'key:{submit_key}']
        elif full_selection:
            allowed_now = [f'paste:{fresh_url}']
        else:
            allowed_now = [f'key:{select_key}']
        return {
            'method': 'focus_select_paste_submit',
            'primitives': [
                'focus',
                f'key:{select_key}',
                f'paste:{fresh_url}',
                f'key:{submit_key}',
            ],
            'allowed_now': allowed_now,
            'forbidden': ['activate', 'click'],
        }

    trigger_key, open_key = _attachment_rule()
    if element_key != trigger_key:
        return None
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


def _single(snapshot: Snapshot, element_key: str):
    matches = list(snapshot.mapped.get(element_key) or ())
    if len(matches) != 1:
        raise ValueError(
            f'chatgpt {element_key} matched {len(matches)} elements; expected one'
        )
    return matches[0]


def _context(element) -> dict[str, Any]:
    context = dict(element.raw or {})
    if element.text is not None:
        context['text'] = element.text
    return context


def validate_key_action(key: str, snapshot: Snapshot) -> None:
    if snapshot.platform != 'chatgpt':
        raise ValueError(
            f'ChatGPT key validation received platform {snapshot.platform!r}'
        )
    navigation_key, select_key, _fresh_url, submit_key = _navigation_rule()
    for declared_key in (select_key, submit_key):
        if key.casefold() == declared_key.casefold() and key != declared_key:
            raise ValueError(
                f'chatgpt navigation key must exactly equal YAML {declared_key!r}'
            )
    address_bar = _single(snapshot, navigation_key)
    address_states = {
        str(state).strip().lower().replace('_', ' ')
        for state in address_bar.states
    }
    if 'focused' in address_states:
        declared = element_operation(
            navigation_key,
            list(address_bar.states),
            _context(address_bar),
        )
        expected = f'key:{key}'
        if declared is None or expected not in declared['allowed_now']:
            raise ValueError(
                f'chatgpt address_bar navigation refuses key {key!r} in the '
                f'fresh tree state (allowed_now='
                f'{declared["allowed_now"] if declared else []})'
            )
        return

    _trigger_key, open_key = _attachment_rule()
    if key.casefold() == open_key.casefold() and key != open_key:
        raise ValueError(
            f'chatgpt attachment opening key must exactly equal YAML {open_key!r}'
        )
    if key == open_key:
        trigger = _single(snapshot, _trigger_key)
        declared = element_operation(_trigger_key, list(trigger.states), _context(trigger))
        expected = f'key:{open_key}'
        if declared is None or expected not in declared['allowed_now']:
            raise ValueError(
                f'chatgpt YAML opening key {key!r} is not allowed in the fresh '
                f'trigger state (allowed_now='
                f'{declared["allowed_now"] if declared else []})'
            )


def validate_paste_action(text: str, snapshot: Snapshot) -> None:
    if snapshot.platform != 'chatgpt':
        raise ValueError(
            f'ChatGPT paste validation received platform {snapshot.platform!r}'
        )
    navigation_key, _select_key, fresh_url, _submit_key = _navigation_rule()
    address_bar = _single(snapshot, navigation_key)
    address_states = {
        str(state).strip().lower().replace('_', ' ')
        for state in address_bar.states
    }
    if 'focused' not in address_states:
        return
    declared = element_operation(
        navigation_key,
        list(address_bar.states),
        _context(address_bar),
    )
    expected = f'paste:{fresh_url}'
    if text != fresh_url or declared is None or expected not in declared['allowed_now']:
        raise ValueError(
            f'chatgpt address_bar paste must exactly equal YAML fresh URL '
            f'{fresh_url!r} after full selection (allowed_now='
            f'{declared["allowed_now"] if declared else []})'
        )


def validate_key_state(key: str, snapshot: Snapshot) -> None:
    validate_key_action(key, snapshot)


__all__ = [
    'element_operation',
    'key_requires_state',
    'validate_key_action',
    'validate_key_state',
    'validate_paste_action',
]
