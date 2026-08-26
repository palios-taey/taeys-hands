from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

import yaml


SCHEMA = 'ats_provider_surface_v1'
PROVIDERS = ('ashby', 'greenhouse', 'lever', 'workday')
PROVIDERS_DIR = Path(__file__).resolve().parent / 'providers'

_IDENTIFIER = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
_HOST = re.compile(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z')
_CAPTURE_TYPES = frozenset({
    'base64url',
    'integer',
    'locale',
    'slug',
    'token',
    'uuid',
    'workday_job',
    'workday_text',
})
_STATUSES = frozenset({'inactive_mapping', 'mapping_only', 'qualification_candidate'})
_ROLES = frozenset({
    'check box',
    'combo box',
    'entry',
    'heading',
    'password text',
    'push button',
    'radio button',
    'section',
    'spin button',
    'toggle button',
})
_STATES = frozenset({
    'editable',
    'enabled',
    'focusable',
    'required',
    'showing',
    'visible',
})


class ProviderContractError(ValueError):
    pass


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ProviderContractError(f'duplicate provider-spec key {key!r}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    provider: str
    path: Path
    sha256: str
    document: Mapping[str, Any]

    @property
    def executable(self) -> bool:
        return bool(self.document['executable'])


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ProviderContractError(f'{context} must be a string-keyed mapping')
    return dict(value)


def _exact_keys(value: Mapping[str, Any], required: set[str], context: str) -> None:
    actual = set(value)
    if actual != required:
        raise ProviderContractError(
            f'{context} keys mismatch: missing={sorted(required - actual)}, '
            f'unknown={sorted(actual - required)}'
        )


def _string_list(value: Any, context: str, *, nonempty: bool = True) -> list[str]:
    if (
        not isinstance(value, list)
        or (nonempty and not value)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ProviderContractError(f'{context} must be a duplicate-free list of strings')
    return list(value)


def _validate_route(route_value: Any) -> None:
    route = _mapping(route_value, 'route')
    _exact_keys(
        route,
        {'scheme', 'exact_hosts', 'suffix_hosts', 'identity_fields', 'grammars'},
        'route',
    )
    if route['scheme'] != 'https':
        raise ProviderContractError('route.scheme must be https')
    exact_hosts = _string_list(route['exact_hosts'], 'route.exact_hosts', nonempty=False)
    suffix_hosts = _string_list(route['suffix_hosts'], 'route.suffix_hosts', nonempty=False)
    if not exact_hosts and not suffix_hosts:
        raise ProviderContractError('route must declare an exact or suffix host')
    for host in exact_hosts:
        if host != host.casefold() or not _HOST.fullmatch(host):
            raise ProviderContractError(f'invalid exact host {host!r}')
    for suffix in suffix_hosts:
        if not suffix.startswith('.') or not _HOST.fullmatch(suffix[1:]):
            raise ProviderContractError(f'invalid suffix host {suffix!r}')
    identity_fields = _string_list(route['identity_fields'], 'route.identity_fields')
    if any(field != 'host' and not _IDENTIFIER.fullmatch(field) for field in identity_fields):
        raise ProviderContractError('route.identity_fields contains an invalid capture')
    grammars = route['grammars']
    if not isinstance(grammars, list) or not grammars:
        raise ProviderContractError('route.grammars must be a non-empty list')
    grammar_ids: set[str] = set()
    captured: set[str] = set()
    for index, grammar_value in enumerate(grammars):
        grammar = _mapping(grammar_value, f'route.grammars[{index}]')
        _exact_keys(grammar, {'id', 'path', 'query'}, f'route.grammars[{index}]')
        grammar_id = grammar['id']
        if not isinstance(grammar_id, str) or not _IDENTIFIER.fullmatch(grammar_id):
            raise ProviderContractError(f'route.grammars[{index}].id is invalid')
        if grammar_id in grammar_ids:
            raise ProviderContractError(f'duplicate route grammar {grammar_id!r}')
        grammar_ids.add(grammar_id)
        path = grammar['path']
        if not isinstance(path, list) or not path:
            raise ProviderContractError(f'route.grammars[{index}].path must be non-empty')
        grammar_captures: set[str] = set()
        for part_index, part_value in enumerate(path):
            part = _mapping(part_value, f'route.grammars[{index}].path[{part_index}]')
            if set(part) == {'literal'}:
                if not isinstance(part['literal'], str) or not part['literal']:
                    raise ProviderContractError('route path literal must be a non-empty string')
                continue
            _exact_keys(
                part,
                {'capture', 'type'},
                f'route.grammars[{index}].path[{part_index}]',
            )
            capture = part['capture']
            if not isinstance(capture, str) or not _IDENTIFIER.fullmatch(capture):
                raise ProviderContractError('route path capture is invalid')
            if part['type'] not in _CAPTURE_TYPES:
                raise ProviderContractError(f'unsupported route capture type {part["type"]!r}')
            grammar_captures.add(capture)
            captured.add(capture)
        query = grammar['query']
        if not isinstance(query, list):
            raise ProviderContractError(f'route.grammars[{index}].query must be a list')
        query_keys: set[str] = set()
        for query_index, query_value in enumerate(query):
            item = _mapping(query_value, f'route.grammars[{index}].query[{query_index}]')
            _exact_keys(
                item,
                {'key', 'capture', 'type'},
                f'route.grammars[{index}].query[{query_index}]',
            )
            if not isinstance(item['key'], str) or not item['key'] or item['key'] in query_keys:
                raise ProviderContractError('route query keys must be unique non-empty strings')
            query_keys.add(item['key'])
            if not isinstance(item['capture'], str) or not _IDENTIFIER.fullmatch(item['capture']):
                raise ProviderContractError('route query capture is invalid')
            if item['type'] not in _CAPTURE_TYPES:
                raise ProviderContractError(f'unsupported route query type {item["type"]!r}')
            grammar_captures.add(item['capture'])
            captured.add(item['capture'])
        missing_identity = set(identity_fields) - {'host'} - grammar_captures
        if missing_identity:
            raise ProviderContractError(
                f'route grammar {grammar_id!r} misses identity captures {sorted(missing_identity)}'
            )
    if set(identity_fields) - {'host'} - captured:
        raise ProviderContractError('route identity fields are not captured')


def _validate_selector(selector_value: Any, context: str) -> None:
    selector = _mapping(selector_value, context)
    _exact_keys(
        selector,
        {'id', 'names_any_of', 'roles_any_of', 'states_all', 'cardinality'},
        context,
    )
    if not isinstance(selector['id'], str) or not _IDENTIFIER.fullmatch(selector['id']):
        raise ProviderContractError(f'{context}.id is invalid')
    _string_list(selector['names_any_of'], f'{context}.names_any_of')
    roles = _string_list(selector['roles_any_of'], f'{context}.roles_any_of')
    states = _string_list(selector['states_all'], f'{context}.states_all')
    if set(roles) - _ROLES:
        raise ProviderContractError(f'{context}.roles_any_of contains an unsupported role')
    if set(states) - _STATES:
        raise ProviderContractError(f'{context}.states_all contains an unsupported state')
    if selector['cardinality'] != 'exactly_one':
        raise ProviderContractError(f'{context}.cardinality must be exactly_one')


def _validate_form_projection(form_value: Any, *, executable: bool) -> None:
    form = _mapping(form_value, 'form_projection')
    _exact_keys(
        form,
        {'enabled', 'max_depth', 'anchors_all', 'required_controls', 'observation_barrier'},
        'form_projection',
    )
    if not isinstance(form['enabled'], bool) or form['enabled'] is not executable:
        raise ProviderContractError('form_projection.enabled must equal executable')
    if isinstance(form['max_depth'], bool) or not isinstance(form['max_depth'], int):
        raise ProviderContractError('form_projection.max_depth must be an integer')
    if not 1 <= form['max_depth'] <= 64:
        raise ProviderContractError('form_projection.max_depth must be between 1 and 64')
    anchors = form['anchors_all']
    if not isinstance(anchors, list) or not anchors:
        raise ProviderContractError('form_projection.anchors_all must be a non-empty list')
    anchor_ids: set[str] = set()
    for index, selector in enumerate(anchors):
        _validate_selector(selector, f'form_projection.anchors_all[{index}]')
        anchor_id = selector['id']
        if anchor_id in anchor_ids:
            raise ProviderContractError(f'duplicate form anchor {anchor_id!r}')
        anchor_ids.add(anchor_id)
    required_controls = _mapping(form['required_controls'], 'form_projection.required_controls')
    _exact_keys(required_controls, {'roles_any_of', 'states_all'}, 'form_projection.required_controls')
    roles = _string_list(
        required_controls['roles_any_of'],
        'form_projection.required_controls.roles_any_of',
    )
    states = _string_list(
        required_controls['states_all'],
        'form_projection.required_controls.states_all',
    )
    if set(roles) - _ROLES or set(states) - _STATES:
        raise ProviderContractError('form_projection.required_controls is not exact-role/state bounded')
    if 'required' not in states:
        raise ProviderContractError('required-field projection must require the AT-SPI required state')
    barrier = _mapping(form['observation_barrier'], 'form_projection.observation_barrier')
    _exact_keys(
        barrier,
        {'refresh_policy', 'stable_cycles', 'interval_ms', 'timeout_ms'},
        'form_projection.observation_barrier',
    )
    if barrier['refresh_policy'] != 'invalidate_reacquire':
        raise ProviderContractError('ATS form observation uses invalidate_reacquire only')
    for key in ('stable_cycles', 'interval_ms', 'timeout_ms'):
        if isinstance(barrier[key], bool) or not isinstance(barrier[key], int):
            raise ProviderContractError(f'form_projection.observation_barrier.{key} must be an integer')
    if barrier['stable_cycles'] < 2 or barrier['interval_ms'] < 1 or barrier['timeout_ms'] < 1:
        raise ProviderContractError('ATS observation barrier bounds are invalid')


def _validate_combo_safety(value: Any) -> None:
    combo = _mapping(value, 'combo_safety')
    _exact_keys(
        combo,
        {
            'geometry',
            'outside_document_refusal',
            'invalid_extent_refusal',
            'scroll_frontier',
            'scroll_primitive',
            'activation_authority',
        },
        'combo_safety',
    )
    expected = {
        'geometry': 'contained_by_active_document',
        'outside_document_refusal': 'combo_rect_outside_document_rect',
        'invalid_extent_refusal': 'combo_rect_invalid',
        'scroll_frontier': 'retain_refused_combo_when_scroll_supported',
        'scroll_primitive': 'consultation_v2.runtime.ConsultationRuntime.scroll_element_into_view',
        'activation_authority': 'none',
    }
    if combo != expected:
        raise ProviderContractError('combo_safety must retain the exact read-only containment contract')


def _validate_transitions(value: Any) -> None:
    transitions = _mapping(value, 'transitions')
    _exact_keys(transitions, {'read_only_form_projection'}, 'transitions')
    transition = _mapping(transitions['read_only_form_projection'], 'transitions.read_only_form_projection')
    _exact_keys(
        transition,
        {
            'operation',
            'grammar',
            'call',
            'traversal_primitive',
            'match_primitive',
            'next',
        },
        'transitions.read_only_form_projection',
    )
    call = _mapping(transition['call'], 'transitions.read_only_form_projection.call')
    expected = {
        'operation': 'observe',
        'grammar': 'ui_action',
        'call': {'op': 'observe'},
        'traversal_primitive': 'consultation_v2.tree.find_elements',
        'match_primitive': 'consultation_v2.snapshot.matches_spec',
        'next': 'terminal',
    }
    if {**transition, 'call': call} != expected:
        raise ProviderContractError('ATS transition must compile to the existing read-only ui_action path')


def _validate_document(document_value: Any, provider: str) -> dict[str, Any]:
    document = _mapping(document_value, provider)
    _exact_keys(
        document,
        {
            'schema',
            'provider',
            'status',
            'executable',
            'route',
            'form_projection',
            'combo_safety',
            'authorities',
            'transitions',
        },
        provider,
    )
    if document['schema'] != SCHEMA or document['provider'] != provider:
        raise ProviderContractError(f'{provider} provider identity is invalid')
    if document['status'] not in _STATUSES or not isinstance(document['executable'], bool):
        raise ProviderContractError(f'{provider} provider status is invalid')
    if document['executable'] is not (provider == 'greenhouse'):
        raise ProviderContractError('Greenhouse must be the sole executable read-only provider')
    if document['status'] != (
        'qualification_candidate' if provider == 'greenhouse'
        else 'inactive_mapping' if provider == 'workday'
        else 'mapping_only'
    ):
        raise ProviderContractError(f'{provider} provider status does not match the release matrix')
    _validate_route(document['route'])
    _validate_form_projection(document['form_projection'], executable=document['executable'])
    _validate_combo_safety(document['combo_safety'])
    authorities = _mapping(document['authorities'], 'authorities')
    _exact_keys(authorities, {'fill', 'upload', 'submit'}, 'authorities')
    if authorities != {'fill': False, 'upload': False, 'submit': False}:
        raise ProviderContractError('ATS provider mutation authority must remain disabled')
    _validate_transitions(document['transitions'])
    return document


def load_provider_spec(provider: str) -> ProviderSpec:
    if provider not in PROVIDERS:
        raise ProviderContractError(f'unsupported ATS provider {provider!r}')
    path = PROVIDERS_DIR / f'{provider}.yaml'
    if not path.is_file() or path.is_symlink():
        raise ProviderContractError(f'provider spec path is missing or unsafe: {provider}')
    raw = path.read_bytes()
    try:
        value = yaml.load(raw.decode('utf-8'), Loader=_UniqueKeyLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProviderContractError(f'{provider} provider spec is not strict UTF-8 YAML') from exc
    document = _validate_document(value, provider)
    return ProviderSpec(
        provider=provider,
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        document=document,
    )
