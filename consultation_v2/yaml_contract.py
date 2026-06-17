from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

KNOWN_PLATFORMS = ('chatgpt', 'claude', 'gemini', 'grok', 'perplexity', 'x_twitter', 'grok_x_scout', 'reddit', 'nvidia_forum')
CHAT_PLATFORMS = frozenset({'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'})

FORBIDDEN_MATCHER_KEYS = frozenset({
    'name_contains',  # lint-allow: strict loader enumerates rejected matcher grammar
    'name_not_contains',  # lint-allow: strict loader enumerates rejected matcher grammar
    'name_contains_all',  # lint-allow: strict loader enumerates rejected matcher grammar
    'name_pattern',  # lint-allow: strict loader enumerates rejected matcher grammar
    'role_contains',  # lint-allow: strict loader enumerates rejected matcher grammar
    'url_contains',  # lint-allow: strict loader enumerates rejected matcher grammar
    'title_contains',  # lint-allow: strict loader enumerates rejected matcher grammar
    'contains',  # lint-allow: strict loader enumerates rejected matcher grammar
    'regex',  # lint-allow: strict loader enumerates rejected matcher grammar
    'matches',  # lint-allow: strict loader enumerates rejected matcher grammar
    'fuzzy',  # lint-allow: strict loader enumerates rejected matcher grammar
    'substring',
})
MATCH_SPEC_KEYS = frozenset({
    'name',
    'names_any_of',
    'role',
    'states_include',
    'structural',
    'attributes',
    'testid',
    'name_must_be_nonempty',
    'pick',
    'trigger_type',
    'select',
})
VALIDATION_KEYS = frozenset({
    'indicators',
    'file_chip',
    'stop_absent',
    'stop_present',
    'timeout',
})
DYNAMIC_CONTROL_KEY_PARTS = ('model_selector', 'mode_selector', 'model_picker', 'mode_picker', 'effort_menu')
DYNAMIC_NAME_PREFIXES = ('Model:', 'Effort ')
DYNAMIC_NAME_SNIPPETS = (' currently ', ', currently ', ' currently')
ALLOW_RE = "# lint-allow:"


@dataclass(frozen=True)
class ContractFinding:
    line: int
    key: str
    message: str

    def render(self, path: Path) -> str:
        return f'{path}:{self.line}: {self.message} (key={self.key})'


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def platforms_dir() -> Path:
    return _repo_root() / 'consultation_v2' / 'platforms'


def platform_yaml_path(platform: str) -> Path:
    if platform not in KNOWN_PLATFORMS:
        raise ValueError(f'Unsupported platform: {platform}')
    return platforms_dir() / f'{platform}.yaml'


def _yaml_key_lines(source: str) -> dict[tuple[str, ...], int]:
    root = yaml.compose(source)
    lines: dict[tuple[str, ...], int] = {}

    def walk(node: Node | None, prefix: tuple[str, ...]) -> None:
        if isinstance(node, MappingNode):
            for key_node, value_node in node.value:
                if not isinstance(key_node, ScalarNode):
                    continue
                key = str(key_node.value)
                key_path = prefix + (key,)
                lines.setdefault(key_path, key_node.start_mark.line + 1)
                walk(value_node, key_path)
        elif isinstance(node, SequenceNode):
            for idx, item in enumerate(node.value):
                walk(item, prefix + (str(idx),))

    walk(root, ())
    return lines


def _line_for(lines: dict[tuple[str, ...], int], path: Iterable[str]) -> int:
    parts = tuple(path)
    while parts:
        if parts in lines:
            return lines[parts]
        parts = parts[:-1]
    return 1


def _allowed_debt_lines(source: str) -> set[int]:
    return {
        idx for idx, line in enumerate(source.splitlines(), start=1)
        if ALLOW_RE in line and line.split(ALLOW_RE, 1)[1].strip()
    }


def _add(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    key_path: tuple[str, ...],
    key: str,
    message: str,
) -> None:
    findings.append(ContractFinding(_line_for(lines, key_path), key, message))


def _iter_mapping_keys(node: object, prefix: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            key_name = str(key)
            key_path = prefix + (key_name,)
            yield key_path, key_name
            yield from _iter_mapping_keys(value, key_path)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            yield from _iter_mapping_keys(value, prefix + (str(idx),))


def _has_wildcard(value: str) -> bool:
    return any(marker in value for marker in ('*', '?', '[', ']'))


def _validate_names_any_of(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    spec: dict[str, Any],
    key_path: tuple[str, ...],
) -> None:
    if 'names_any_of' not in spec:
        return
    candidates = spec['names_any_of']
    if not isinstance(candidates, list) or not candidates:
        _add(findings, lines, key_path + ('names_any_of',), 'names_any_of',
             'names_any_of must be a non-empty list of exact labels')
        return
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            _add(findings, lines, key_path + ('names_any_of',), 'names_any_of',
                 'names_any_of entries must be non-empty strings')
            continue
        if candidate != candidate.strip() or _has_wildcard(candidate):
            _add(findings, lines, key_path + ('names_any_of',), 'names_any_of',
                 'names_any_of entries must be exact labels, not patterns or padded strings')


def _validate_structural(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    spec: dict[str, Any],
    key_path: tuple[str, ...],
    element_map: dict[str, Any],
) -> None:
    if 'structural' not in spec:
        return
    structural = spec['structural']
    structural_path = key_path + ('structural',)
    if not isinstance(structural, dict):
        _add(findings, lines, structural_path, 'structural',
             'structural locator must be a mapping with exact role and container path')
        return
    role = structural.get('role')
    if not isinstance(role, str) or not role or role != role.strip() or _has_wildcard(role):
        _add(findings, lines, structural_path + ('role',), 'role',
             'structural.role must be an exact non-pattern role string')
    parent = structural.get('parent')
    container_path = structural.get('container_path')
    if parent is None and container_path is None:
        _add(findings, lines, structural_path, 'structural',
             'structural locator must declare parent or container_path')
    if parent is not None:
        if not isinstance(parent, str) or parent not in element_map:
            _add(findings, lines, structural_path + ('parent',), 'parent',
                 'structural.parent must be an exact element_map key')
    if container_path is not None:
        if (
            not isinstance(container_path, list)
            or not container_path
            or not all(isinstance(item, str) and item for item in container_path)
        ):
            _add(findings, lines, structural_path + ('container_path',), 'container_path',
                 'structural.container_path must be a non-empty list of exact container keys')
    if 'index' in structural and not isinstance(structural['index'], int):
        _add(findings, lines, structural_path + ('index',), 'index',
             'structural.index must be an integer')
    if 'ordinal' in structural and structural['ordinal'] not in {'first', 'last'}:
        _add(findings, lines, structural_path + ('ordinal',), 'ordinal',
             'structural.ordinal must be first or last')


def _validate_attributes(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    spec: dict[str, Any],
    key_path: tuple[str, ...],
) -> None:
    if 'testid' in spec:
        testid = spec['testid']
        if not isinstance(testid, str) or not testid or testid != testid.strip() or _has_wildcard(testid):
            _add(findings, lines, key_path + ('testid',), 'testid',
                 'testid must be an exact non-pattern string')
    if 'attributes' in spec:
        attributes = spec['attributes']
        if not isinstance(attributes, dict) or not attributes:
            _add(findings, lines, key_path + ('attributes',), 'attributes',
                 'attributes must be a non-empty mapping of exact key/value pairs')
            return
        for attr_key, attr_value in attributes.items():
            if not isinstance(attr_key, str) or not attr_key:
                _add(findings, lines, key_path + ('attributes',), 'attributes',
                     'attribute names must be non-empty strings')
            if not isinstance(attr_value, str) or attr_value != attr_value.strip() or _has_wildcard(attr_value):
                _add(findings, lines, key_path + ('attributes', str(attr_key)), str(attr_key),
                     'attribute values must be exact non-pattern strings')


def _is_dynamic_control(element_key: str, spec: dict[str, Any]) -> bool:
    lowered_key = element_key.lower()
    if 'names_any_of' in spec and any(part in lowered_key for part in DYNAMIC_CONTROL_KEY_PARTS):
        return True
    name = spec.get('name')
    if isinstance(name, str):
        if name.startswith(DYNAMIC_NAME_PREFIXES):
            return True
        lowered_name = f' {name.lower()} '
        if any(snippet in lowered_name for snippet in DYNAMIC_NAME_SNIPPETS):
            return True
    return False


def _has_stable_locator(spec: dict[str, Any]) -> bool:
    return any(key in spec for key in ('structural', 'attributes', 'testid'))


def _validate_match_spec(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    spec: object,
    key_path: tuple[str, ...],
    element_key: str,
    element_map: dict[str, Any],
) -> None:
    if not isinstance(spec, dict):
        _add(findings, lines, key_path, element_key, 'match spec must be a mapping')
        return
    for key in spec:
        key_name = str(key)
        if key_name in FORBIDDEN_MATCHER_KEYS:
            continue
        if key_name not in MATCH_SPEC_KEYS:
            _add(findings, lines, key_path + (key_name,), key_name,
                 'unsupported matcher key; use exact name/role/states_include, names_any_of, or structural')
    _validate_names_any_of(findings, lines, spec, key_path)
    _validate_structural(findings, lines, spec, key_path, element_map)
    _validate_attributes(findings, lines, spec, key_path)
    role = spec.get('role')
    if 'role' in spec and (not isinstance(role, str) or not role or role != role.strip() or _has_wildcard(role)):
        _add(findings, lines, key_path + ('role',), 'role',
             'role must be an exact non-pattern string')
    states = spec.get('states_include')
    if states is not None:
        if not isinstance(states, list) or not all(isinstance(item, str) and item for item in states):
            _add(findings, lines, key_path + ('states_include',), 'states_include',
                 'states_include must be a list of exact state strings')
    if _is_dynamic_control(element_key, spec) and not _has_stable_locator(spec):
        locator_key = 'names_any_of' if 'names_any_of' in spec else 'name'
        _add(findings, lines, key_path + (locator_key,), locator_key,
             f'dynamic-name control {element_key!r} must use structural, attributes, or testid locator')


def _validate_validation_specs(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    data: dict[str, Any],
) -> None:
    validation = data.get('validation') or {}
    element_map = ((data.get('tree') or {}).get('element_map') or {})
    if not isinstance(validation, dict):
        _add(findings, lines, ('validation',), 'validation', 'validation must be a mapping')
        return
    for validation_key, spec in validation.items():
        validation_path = ('validation', str(validation_key))
        if not isinstance(spec, dict):
            _add(findings, lines, validation_path, str(validation_key), 'validation state must be a mapping')
            continue
        for key in spec:
            key_name = str(key)
            if key_name not in VALIDATION_KEYS:
                _add(findings, lines, validation_path + (key_name,), key_name,
                     'unsupported or unmapped validation state key')
        for stop_key_name in ('stop_absent', 'stop_present'):
            if stop_key_name not in spec:
                continue
            value = spec[stop_key_name]
            if not isinstance(value, str) or value not in element_map:
                _add(findings, lines, validation_path + (stop_key_name,), stop_key_name,
                     f'{stop_key_name} must name an element_map key')
        indicators = spec.get('indicators')
        if indicators is not None:
            if not isinstance(indicators, list):
                _add(findings, lines, validation_path + ('indicators',), 'indicators',
                     'validation indicators must be a list of exact match specs')
            else:
                for idx, indicator in enumerate(indicators):
                    _validate_match_spec(
                        findings, lines, indicator,
                        validation_path + ('indicators', str(idx)),
                        f'{validation_key}.indicators[{idx}]',
                        element_map,
                    )
        file_chip = spec.get('file_chip')
        if file_chip is not None:
            if not isinstance(file_chip, dict):
                _add(findings, lines, validation_path + ('file_chip',), 'file_chip',
                     'file_chip validation must be a mapping')
                continue
            roles = file_chip.get('roles')
            if roles is not None and (
                not isinstance(roles, list)
                or not roles
                or not all(isinstance(role, str) and role for role in roles)
            ):
                _add(findings, lines, validation_path + ('file_chip', 'roles'), 'roles',
                     'file_chip.roles must be a non-empty list of exact roles')


def _validate_chat_yaml(platform: str, path: Path, data: dict[str, Any], source: str) -> None:
    if platform not in CHAT_PLATFORMS:
        return
    lines = _yaml_key_lines(source)
    allowed_debt_lines = _allowed_debt_lines(source)
    findings: list[ContractFinding] = []
    for key_path, key in _iter_mapping_keys(data):
        if key in FORBIDDEN_MATCHER_KEYS:
            _add(findings, lines, key_path, key, f'forbidden consultation_v2 matcher key {key!r}')

    element_map = ((data.get('tree') or {}).get('element_map') or {})
    if isinstance(element_map, dict):
        for element_key, spec in element_map.items():
            _validate_match_spec(
                findings, lines, spec,
                ('tree', 'element_map', str(element_key)),
                str(element_key),
                element_map,
            )
    _validate_validation_specs(findings, lines, data)
    findings = [finding for finding in findings if finding.line not in allowed_debt_lines]

    if findings:
        rendered = '\n'.join(finding.render(path) for finding in findings)
        raise ValueError(f'{path.name} violates consultation_v2 YAML contract:\n{rendered}')


@lru_cache(maxsize=None)
def load_platform_yaml(platform: str) -> Dict[str, Any]:
    path = platform_yaml_path(platform)
    if not path.exists():
        raise FileNotFoundError(path)
    source = path.read_text()
    data = yaml.safe_load(source) or {}
    if not isinstance(data, dict):
        raise ValueError(f'{path.name} top-level YAML node must be a mapping')
    required = ('platform', 'urls', 'tree', 'workflow', 'validation')
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f'{path.name} missing required keys: {missing}')
    _validate_chat_yaml(platform, path, data, source)
    return data


def clear_yaml_cache() -> None:
    load_platform_yaml.cache_clear()


def get_element_spec(platform: str, key: str) -> Dict[str, Any]:
    cfg = load_platform_yaml(platform)
    return dict((cfg.get('tree') or {}).get('element_map', {}).get(key, {}))


def get_workflow(platform: str) -> Dict[str, Any]:
    return dict(load_platform_yaml(platform).get('workflow', {}))


def get_validation(platform: str, key: str | None = None) -> Dict[str, Any]:
    validation = dict(load_platform_yaml(platform).get('validation', {}))
    if key is None:
        return validation
    return dict(validation.get(key, {}))


def get_settle(platform: str) -> Dict[str, Any]:
    return dict(load_platform_yaml(platform).get('settle', {}))
