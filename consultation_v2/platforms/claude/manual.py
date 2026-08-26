from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from consultation_v2.types import ElementRef, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


_SHA256_RE = re.compile(r'[0-9a-f]{64}')
_PROJECTION = 'attachment_shortcut_v1'


def _exact_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'claude {label} must be an exact non-empty string')
    return value


def _exact_string_list(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(
            isinstance(item, str) and item and item == item.strip()
            for item in value
        )
    ):
        raise ValueError(f'claude {label} must be a non-empty exact string list')
    return tuple(value)


def _attachment_rule() -> tuple[
    str,
    str,
    str,
    tuple[str, ...],
    str,
    tuple[str, ...],
    tuple[str, ...],
]:
    cfg = load_platform_yaml('claude')
    workflow = cfg.get('workflow') or {}
    attachment = workflow.get('attachment') or {}
    if not isinstance(attachment, dict):
        raise ValueError('claude workflow.attachment must be a mapping')
    if attachment.get('open_method') != 'keyboard_shortcut':
        raise ValueError('claude attachment open_method must be keyboard_shortcut')
    shortcut = _exact_string(
        attachment.get('keyboard_shortcut'),
        'workflow.attachment.keyboard_shortcut',
    )
    precondition = attachment.get('key_precondition') or {}
    if not isinstance(precondition, dict):
        raise ValueError('claude attachment key_precondition must be a mapping')
    if precondition.get('projection') != _PROJECTION:
        raise ValueError(
            f'claude attachment key_precondition projection must be {_PROJECTION!r}'
        )
    scope = _exact_string(
        precondition.get('scope'),
        'workflow.attachment.key_precondition.scope',
    )
    if scope != 'base':
        raise ValueError('claude attachment key_precondition scope must be base')
    attachment_count_element = _exact_string(
        precondition.get('attachment_count_element'),
        'workflow.attachment.key_precondition.attachment_count_element',
    )
    element_map = ((cfg.get('tree') or {}).get('element_map') or {})
    if attachment_count_element not in element_map:
        raise ValueError(
            'claude attachment key_precondition attachment_count_element must '
            'name an exact tree.element_map key'
        )

    navigation = workflow.get('navigation') or {}
    postcondition = navigation.get('postcondition') or {}
    if not isinstance(postcondition, dict):
        raise ValueError('claude navigation postcondition must be a mapping')
    if postcondition.get('scope') != scope:
        raise ValueError(
            'claude attachment key precondition must reuse navigation base scope'
        )
    exact_singletons = _exact_string_list(
        postcondition.get('exact_singletons'),
        'workflow.navigation.postcondition.exact_singletons',
    )
    required_controls = {'input', 'model_selector', 'toggle_menu'}
    missing = sorted(required_controls - set(exact_singletons))
    if missing:
        raise ValueError(
            f'claude navigation exact_singletons omit required controls {missing}'
        )

    urls = cfg.get('urls') or {}
    fresh_url = _exact_string(urls.get('fresh'), 'urls.fresh')

    stop_keys: set[str] = set()
    for section_name in ('send', 'monitor'):
        section = workflow.get(section_name) or {}
        if not isinstance(section, dict):
            raise ValueError(f'claude workflow.{section_name} must be a mapping')
        stop_keys.update(
            _exact_string_list(
                section.get('stop_keys'),
                f'workflow.{section_name}.stop_keys',
            )
        )

    exception_keys: set[str] = set()
    pre_send = workflow.get('pre_send') or {}
    exceptions = pre_send.get('exceptions') or {}
    if not isinstance(exceptions, dict):
        raise ValueError('claude workflow.pre_send.exceptions must be a mapping')
    for name, spec in exceptions.items():
        if not isinstance(spec, dict):
            raise ValueError(f'claude pre-send exception {name!r} must be a mapping')
        exception_keys.update(
            _exact_string_list(
                spec.get('detect'),
                f'workflow.pre_send.exceptions.{name}.detect',
            )
        )

    full_consult = workflow.get('full_consult') or {}
    if not isinstance(full_consult, dict):
        raise ValueError('claude workflow.full_consult must be a mapping')
    exception_keys.update(
        _exact_string_list(
            full_consult.get('failures'),
            'workflow.full_consult.failures',
        )
    )

    monitor = workflow.get('monitor') or {}
    exception_states = monitor.get('exception_states') or []
    if not isinstance(exception_states, list) or not exception_states:
        raise ValueError('claude workflow.monitor.exception_states must be a list')
    for index, spec in enumerate(exception_states):
        if not isinstance(spec, dict):
            raise ValueError(
                f'claude workflow.monitor.exception_states[{index}] must be a mapping'
            )
        exception_keys.update(
            _exact_string_list(
                spec.get('detect'),
                f'workflow.monitor.exception_states[{index}].detect',
            )
        )

    return (
        shortcut,
        scope,
        fresh_url,
        exact_singletons,
        attachment_count_element,
        tuple(sorted(stop_keys)),
        tuple(sorted(exception_keys)),
    )


def _normalized_states(element: ElementRef) -> set[str]:
    return {
        str(state).strip().lower().replace('_', ' ')
        for state in element.states
    }


def _semantic_projection(
    snapshot: Snapshot,
    *,
    scope: str,
) -> dict[str, Any] | None:
    (
        shortcut,
        required_scope,
        fresh_url,
        exact_singletons,
        attachment_key,
        stop_keys,
        exception_keys,
    ) = _attachment_rule()
    if snapshot.platform != 'claude' or scope != required_scope:
        return None
    if snapshot.url != fresh_url:
        return None

    controls: dict[str, dict[str, str]] = {}
    selected: dict[str, ElementRef] = {}
    for element_key in exact_singletons:
        matches = list(snapshot.mapped.get(element_key) or ())
        if len(matches) != 1:
            return None
        element = matches[0]
        selected[element_key] = element
        controls[element_key] = {
            'name': element.name,
            'role': element.role,
        }

    input_element = selected['input']
    if 'focused' not in _normalized_states(input_element):
        return None
    model_selector_name = selected['model_selector'].name
    if not model_selector_name:
        return None
    if any(snapshot.mapped.get(key) for key in (*stop_keys, *exception_keys)):
        return None

    return {
        'projection': _PROJECTION,
        'platform': 'claude',
        'scope': required_scope,
        'shortcut': shortcut,
        'fresh_url': fresh_url,
        'controls': controls,
        'input_focused': True,
        'model_selector_name': model_selector_name,
        'remove_attachment_count': len(snapshot.mapped.get(attachment_key) or ()),
        'stop_keys_absent': list(stop_keys),
        'mapped_exception_keys_absent': list(exception_keys),
    }


def _projection_sha256(projection: dict[str, Any]) -> str:
    encoded = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def key_preconditions(snapshot: Snapshot, *, scope: str) -> dict[str, str]:
    shortcut, required_scope, *_rest = _attachment_rule()
    if scope != required_scope:
        return {}
    projection = _semantic_projection(snapshot, scope=scope)
    if projection is None:
        return {}
    return {shortcut: _projection_sha256(projection)}


def validate_key_precondition(
    key: str,
    snapshot: Snapshot,
    *,
    scope: str,
    expected_sha256: str,
) -> None:
    shortcut, required_scope, *_rest = _attachment_rule()
    if key.casefold() == shortcut.casefold() and key != shortcut:
        raise ValueError(
            f'claude attachment shortcut must exactly equal YAML {shortcut!r}'
        )
    if key != shortcut:
        raise ValueError(
            f'claude semantic key precondition is not declared for key {key!r}'
        )
    if scope != required_scope:
        raise ValueError(
            f'claude attachment shortcut requires semantic scope {required_scope!r}'
        )
    if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(
        expected_sha256
    ):
        raise ValueError('claude semantic key precondition requires one SHA-256 token')
    projection = _semantic_projection(snapshot, scope=scope)
    if projection is None:
        raise ValueError(
            'claude attachment shortcut live semantic postcondition is not satisfied'
        )
    actual_sha256 = _projection_sha256(projection)
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise ValueError(
            'claude attachment shortcut semantic state changed after the preceding observe'
        )


def validate_key_action(key: str, snapshot: Snapshot) -> None:
    shortcut, scope, *_rest = _attachment_rule()
    if key.casefold() == shortcut.casefold() and key != shortcut:
        raise ValueError(
            f'claude attachment shortcut must exactly equal YAML {shortcut!r}'
        )
    if key != shortcut:
        return
    if _semantic_projection(snapshot, scope=scope) is None:
        raise ValueError(
            'claude attachment shortcut requires the exact fresh semantic state'
        )


def key_requires_state(key: str) -> bool:
    shortcut, *_rest = _attachment_rule()
    if key.casefold() == shortcut.casefold() and key != shortcut:
        raise ValueError(
            f'claude attachment shortcut must exactly equal YAML {shortcut!r}'
        )
    return key == shortcut


def element_operation(
    element_key: str,
    states: list[str],
    context: dict[str, Any] | None = None,
) -> None:
    del element_key, states, context
    return None


__all__ = [
    'element_operation',
    'key_preconditions',
    'key_requires_state',
    'validate_key_action',
    'validate_key_precondition',
]
