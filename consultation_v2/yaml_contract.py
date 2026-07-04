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
FORBIDDEN_WORKFLOW_KEYS = frozenset({
    'complete_key',
    'complete_keys',
    'input_fallback',
})
MATCH_SPEC_KEYS = frozenset({
    'name',
    'names_any_of',
    'role',
    'scope',
    'active_state',
    'states_include',
    'structural',
    'attributes',
    'testid',
    'name_must_be_nonempty',
    'pick',
    'trigger_type',
    'select',
    'match_strategy',
    'reason',
})
MATCH_STRATEGIES = frozenset({'name_agnostic_structural'})
STRUCTURAL_ORDINAL_VALUES = frozenset({'first', 'last'})
STRUCTURAL_KEYS = frozenset({
    'after',
    'before',
    'container_path',
    'index',
    'name_must_be_nonempty',
    'ordinal',
    'parent',
    'role',
})
IDENTITY_SCHEMA = 'identity_v1'
IDENTITY_ELEMENT_KEYS = frozenset({
    'name',
    'role',
    'scope',
    'active_state',
    'match_strategy',
    'structural',
    'reason',
})
IDENTITY_ACTIVE_STATES = frozenset({'checked', 'selected', 'pressed', 'expanded', 'focused'})
MENU_ACTIVE_RECOGNITIONS = IDENTITY_ACTIVE_STATES | frozenset({'selected_name_prefix', 'click_only'})
IDENTITY_MATCH_STRATEGIES = frozenset({'name_agnostic_structural'})
IDENTITY_STRUCTURAL_KEYS = frozenset({'after', 'before'})
MENU_SELECTION_KEYS = frozenset({'menus'})
MENU_KEYS = frozenset({
    'select',
    'active_recognition',
    'must_choose',
    'resettable_on_followup',
    'operate',
    'options',
    'default_for_fresh',
    'example_rationale',
})
MENU_SELECT_VALUES = frozenset({'single', 'multi'})
MENU_OPERATE_KEYS = frozenset({'trigger', 'scope'})
MENU_OPERATE_SCOPES = frozenset({'app_root_snapshot', 'menu_snapshot', 'snapshot'})
MENU_CLICK_STRATEGIES = frozenset({'atspi_only', 'atspi_first', 'coordinate_only', 'xdotool_first'})
MENU_OPTION_KEYS = frozenset({
    'element',
    'path',
    'active_element',
    'active_trigger_names',
    'click_strategy',
})
MENU_PATH_KEYS = frozenset({'element', 'action'})
MENU_PATH_ACTIONS = frozenset({'hover', 'press', 'click'})
LEGACY_SELECTION_KEYS = frozenset({
    'options',
    'model_targets',
    'tool_targets',
    'driver_operations',
    'composite_modes',
})
IDENTITY_FORBIDDEN_KEYS = FORBIDDEN_MATCHER_KEYS | frozenset({
    'names_any_of',
    'states_include',
    'best_effort',
    'active',
    'active_value',
    'checked',
    'selected',
    'pressed',
    'state',
    'states',
    'state_value',
    'state_values',
    'stored_state',
    'value',
    'stop_present',
})
VALIDATION_KEYS = frozenset({
    'indicators',
    'file_chip',
    'absent',
    'stop_absent',
    'stop_present',
    'timeout',
})
# Extraction-by-output-type schema (FLOW_CONSULTATION_ENGINE.md §2/§11,
# consultation_v2/EXTRACTION_SCHEMA.md). The enumerated set of output types a
# request may declare/derive. A platform's `extraction:` section maps each
# SUPPORTED output type to an ordered workflow of exact-matched steps. An output
# type the platform cannot serve is simply NOT listed (cannot-lie); the engine
# never downgrades an unsupported type to another and never falls back.
EXTRACTION_OUTPUT_TYPES = frozenset({
    'assistant_text',
    'research_report',
    'artifact',
    'downloaded_file',
    'attachment_echo',
})
# Enumerated step action verbs. Each maps to a shared runtime primitive the
# driver invokes; no platform strings, no fuzzy discovery.
EXTRACTION_STEP_ACTIONS = frozenset({
    'scroll_to_bottom',       # scroll the conversation to the final answer (anchor on element)
    'scroll_into_view',       # bring a specific report/artifact control on-screen
    'click',                  # activate a mapped trigger/menu element via AT-SPI element action
    'copy_element',           # activate a mapped copy control (the clipboard-producing button)
    'read_clipboard',         # read the clipboard the prior copy_element populated
    'read_tree_text',         # collect report text from AT-SPI tree nodes when copy control is absent
    'open_panel',             # open an artifact/canvas/report panel via a mapped control
    'download',               # invoke a mapped export/download control producing a file
    'verify_against_source',  # verify extracted content against a source attachment hash
})
# Actions that MUST name an exact element_map control via `element:`.
EXTRACTION_ELEMENT_REQUIRED_ACTIONS = frozenset({
    'scroll_to_bottom',
    'scroll_into_view',
    'click',
    'copy_element',
    'open_panel',
    'download',
})
# Actions that MUST NOT carry an `element:` key.
EXTRACTION_ELEMENT_FORBIDDEN_ACTIONS = frozenset({
    'read_clipboard',
    'read_tree_text',
    'verify_against_source',
})
# 'select' picks among >1 matching elements for an exact element_map key. Exact
# enum only — never an index expression, never a fuzzy ranker. Mirrors
# Snapshot.first / Snapshot.last.
EXTRACTION_SELECT_VALUES = frozenset({'first', 'last'})
# Keys legal inside one extraction step. Unknown keys are rejected at load.
EXTRACTION_STEP_KEYS = frozenset({
    'action',      # required: one of EXTRACTION_STEP_ACTIONS
    'element',     # exact element_map key the step touches (required/forbidden per action)
    'select',      # optional: one of EXTRACTION_SELECT_VALUES (default last)
    'validation',  # optional: exact validation: key gating the step result
})
# Keys legal inside one output-type workflow.
EXTRACTION_WORKFLOW_KEYS = frozenset({
    'steps',             # required: ordered list of step mappings
    'validate_markers',  # optional: list of exact markers the result must carry
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


@dataclass(frozen=True)
class ExtractionStep:
    """One exact-matched step of an extraction workflow.

    `element` is an exact element_map key (never a fuzzy matcher). `select`
    disambiguates among >1 matching elements for that key (Snapshot.first /
    Snapshot.last). `validation` is an exact validation: key that gates the
    step's result. Only the action-relevant fields are populated.
    """
    action: str
    element: str | None = None
    select: str = 'last'
    validation: str | None = None


@dataclass(frozen=True)
class ExtractionWorkflow:
    """The ordered, exact-matched workflow for one output type on one platform.

    `validate_markers` are exact substrings the extracted content must carry for
    this output type (used by research_report/artifact to reject summary-only
    grabs); empty when the output type declares none.
    """
    output_type: str
    steps: tuple[ExtractionStep, ...]
    validate_markers: tuple[str, ...] = ()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def platforms_dir() -> Path:
    return _repo_root() / 'consultation_v2' / 'platforms'


def platform_yaml_path(platform: str) -> Path:
    if platform not in KNOWN_PLATFORMS:
        raise ValueError(f'Unsupported platform: {platform}')
    packaged = platforms_dir() / platform / f'{platform}.yaml'
    if packaged.exists():
        return packaged
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
    for raw_key in structural:
        key_name = str(raw_key)
        if key_name not in STRUCTURAL_KEYS:
            _add(findings, lines, structural_path + (key_name,), key_name,
                 'unsupported structural locator key')
    role = structural.get('role')
    if not isinstance(role, str) or not role or role != role.strip() or _has_wildcard(role):
        if 'role' in structural:
            _add(findings, lines, structural_path + ('role',), 'role',
                 'structural.role must be an exact non-pattern role string')
    parent = structural.get('parent')
    container_path = structural.get('container_path')
    after = structural.get('after')
    before = structural.get('before')
    if parent is None and container_path is None and after is None and before is None:
        _add(findings, lines, structural_path, 'structural',
             'structural locator must declare parent, container_path, after, or before')
    if parent is not None:
        if not isinstance(parent, str) or parent not in element_map:
            _add(findings, lines, structural_path + ('parent',), 'parent',
                 'structural.parent must be an exact element_map key')
    for anchor_key, anchor_value in (('after', after), ('before', before)):
        if anchor_value is not None and (
            not isinstance(anchor_value, str) or anchor_value not in element_map
        ):
            _add(findings, lines, structural_path + (anchor_key,), anchor_key,
                 f'structural.{anchor_key} must be an exact element_map key')
    if container_path is not None:
        if (
            not isinstance(container_path, list)
            or not container_path
            or not all(isinstance(item, str) and item for item in container_path)
        ):
            _add(findings, lines, structural_path + ('container_path',), 'container_path',
                 'structural.container_path must be a non-empty list of exact container keys')
    if (
        'index' in structural
        and (
            isinstance(structural['index'], bool)
            or not isinstance(structural['index'], int)
            or structural['index'] < 0
        )
    ):
        _add(findings, lines, structural_path + ('index',), 'index',
             'structural.index must be a non-negative integer')
    if 'ordinal' in structural and structural['ordinal'] not in STRUCTURAL_ORDINAL_VALUES:
        _add(findings, lines, structural_path + ('ordinal',), 'ordinal',
             f'structural.ordinal must be one of {sorted(STRUCTURAL_ORDINAL_VALUES)}')


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
    strategy = spec.get('match_strategy')
    if strategy is not None and strategy not in MATCH_STRATEGIES:
        _add(findings, lines, key_path + ('match_strategy',), 'match_strategy',
             f'match_strategy must be one of {sorted(MATCH_STRATEGIES)}')
    if strategy == 'name_agnostic_structural':
        if 'name' in spec:
            _add(findings, lines, key_path + ('name',), 'name',
                 'name_agnostic_structural entries must not declare a visible name')
        if not isinstance(spec.get('role'), str) or not spec.get('role'):
            _add(findings, lines, key_path + ('role',), 'role',
                 'name_agnostic_structural entries must declare an exact role')
        if not isinstance(spec.get('structural'), dict) or not spec.get('structural'):
            _add(findings, lines, key_path + ('structural',), 'structural',
                 'name_agnostic_structural entries must declare structural anchors')
        reason = spec.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            _add(findings, lines, key_path + ('reason',), 'reason',
                 'name_agnostic_structural entries must explain the dynamic visible name')
    _validate_names_any_of(findings, lines, spec, key_path)
    _validate_structural(findings, lines, spec, key_path, element_map)
    _validate_attributes(findings, lines, spec, key_path)
    name = spec.get('name')
    if 'name' in spec and (not isinstance(name, str) or not name or name != name.strip() or _has_wildcard(name)):
        _add(findings, lines, key_path + ('name',), 'name',
             'name must be an exact non-empty non-pattern string')
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


def _validate_global_exactness(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    node: object,
    key_path: tuple[str, ...] = (),
) -> None:
    if isinstance(node, dict):
        keys = {str(key) for key in node}
        for raw_key, value in node.items():
            key_name = str(raw_key)
            child_path = key_path + (key_name,)
            if key_name in FORBIDDEN_MATCHER_KEYS:
                _add(findings, lines, child_path, key_name,
                     f'forbidden consultation_v2 matcher key {key_name!r}')
            if key_name in FORBIDDEN_WORKFLOW_KEYS:
                _add(findings, lines, child_path, key_name,
                     f'forbidden consultation_v2 fallback/completion key {key_name!r}')
            if key_name == 'name' and (not isinstance(value, str) or not value):
                _add(findings, lines, child_path, key_name,
                     'name must be an exact non-empty string')
            if key_name == 'names_any_of':
                if (
                    not isinstance(value, list)
                    or not value
                    or not all(isinstance(item, str) and item and item == item.strip() and not _has_wildcard(item) for item in value)
                ):
                    _add(findings, lines, child_path, key_name,
                         'names_any_of must contain exact non-empty labels only')
            _validate_global_exactness(findings, lines, value, child_path)
        matcherish = bool(keys & {'role', 'states_include', 'active_state'})
        exact_locator = bool(keys & {'name', 'names_any_of', 'structural', 'attributes', 'testid', 'match_strategy'})
        if matcherish and not exact_locator:
            _add(findings, lines, key_path, key_path[-1] if key_path else 'mapping',
                 'presence-only matcher maps role/state without an exact stable locator')
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            _validate_global_exactness(findings, lines, value, key_path + (str(idx),))


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
        absent = spec.get('absent')
        if absent is not None:
            absent_keys = absent if isinstance(absent, list) else [absent]
            if (
                not absent_keys
                or not all(isinstance(key, str) and key in element_map for key in absent_keys)
            ):
                _add(findings, lines, validation_path + ('absent',), 'absent',
                     'absent must name one or more element_map keys')
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


def _validate_extraction_step(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    step: object,
    step_path: tuple[str, ...],
    element_map: dict[str, Any],
    validation: dict[str, Any],
) -> None:
    if not isinstance(step, dict):
        _add(findings, lines, step_path, 'step', 'extraction step must be a mapping')
        return
    for key in step:
        key_name = str(key)
        if key_name not in EXTRACTION_STEP_KEYS:
            _add(findings, lines, step_path + (key_name,), key_name,
                 'unsupported extraction step key; use action/element/select/validation')
    action = step.get('action')
    if not isinstance(action, str) or action not in EXTRACTION_STEP_ACTIONS:
        _add(findings, lines, step_path + ('action',), 'action',
             f'extraction step action must be one of {sorted(EXTRACTION_STEP_ACTIONS)}')
        action = None
    element = step.get('element')
    if 'element' in step:
        if not isinstance(element, str) or element not in element_map:
            _add(findings, lines, step_path + ('element',), 'element',
                 'extraction step element must name an exact element_map key')
        if action in EXTRACTION_ELEMENT_FORBIDDEN_ACTIONS:
            _add(findings, lines, step_path + ('element',), 'element',
                 f'extraction step action {action!r} must not carry an element key')
    if action in EXTRACTION_ELEMENT_REQUIRED_ACTIONS and 'element' not in step:
        _add(findings, lines, step_path + ('action',), 'action',
             f'extraction step action {action!r} requires an exact element_map key')
    select = step.get('select')
    if 'select' in step and select not in EXTRACTION_SELECT_VALUES:
        _add(findings, lines, step_path + ('select',), 'select',
             f'extraction step select must be one of {sorted(EXTRACTION_SELECT_VALUES)}')
    validation_key = step.get('validation')
    if 'validation' in step:
        if not isinstance(validation_key, str) or validation_key not in validation:
            _add(findings, lines, step_path + ('validation',), 'validation',
                 'extraction step validation must name an exact validation: key')


def _validate_extraction_specs(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    data: dict[str, Any],
) -> None:
    if 'extraction' not in data:
        return
    extraction = data.get('extraction')
    element_map = ((data.get('tree') or {}).get('element_map') or {})
    validation = data.get('validation') or {}
    if not isinstance(extraction, dict) or not extraction:
        _add(findings, lines, ('extraction',), 'extraction',
             'extraction must be a non-empty mapping of output-type -> workflow')
        return
    for output_type, workflow in extraction.items():
        output_name = str(output_type)
        extraction_path = ('extraction', output_name)
        if output_name not in EXTRACTION_OUTPUT_TYPES:
            _add(findings, lines, extraction_path, output_name,
                 f'unknown extraction output type; use one of {sorted(EXTRACTION_OUTPUT_TYPES)}')
            continue
        if not isinstance(workflow, dict):
            _add(findings, lines, extraction_path, output_name,
                 'extraction workflow must be a mapping with a steps list')
            continue
        for key in workflow:
            key_name = str(key)
            if key_name not in EXTRACTION_WORKFLOW_KEYS:
                _add(findings, lines, extraction_path + (key_name,), key_name,
                     'unsupported extraction workflow key; use steps/validate_markers')
        steps = workflow.get('steps')
        if not isinstance(steps, list) or not steps:
            _add(findings, lines, extraction_path + ('steps',), 'steps',
                 'extraction workflow steps must be a non-empty ordered list')
        else:
            for idx, step in enumerate(steps):
                _validate_extraction_step(
                    findings, lines, step,
                    extraction_path + ('steps', str(idx)),
                    element_map, validation,
                )
        markers = workflow.get('validate_markers')
        if markers is not None and (
            not isinstance(markers, list)
            or not markers
            or not all(isinstance(item, str) and item for item in markers)
        ):
            _add(findings, lines, extraction_path + ('validate_markers',), 'validate_markers',
                'validate_markers must be a non-empty list of exact marker strings')


def _uses_identity_schema(data: dict[str, Any]) -> bool:
    return data.get('schema') == IDENTITY_SCHEMA or (data.get('tree') or {}).get('schema') == IDENTITY_SCHEMA


def _validate_identity_element_map(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    element_map: object,
) -> None:
    if not isinstance(element_map, dict) or not element_map:
        _add(findings, lines, ('tree', 'element_map'), 'element_map',
             'identity_v1 requires a non-empty tree.element_map')
        return
    for element_key, spec in element_map.items():
        key_path = ('tree', 'element_map', str(element_key))
        if not isinstance(spec, dict):
            _add(findings, lines, key_path, str(element_key),
                 'identity_v1 element entries must be mappings')
            continue
        for raw_key in spec:
            key_name = str(raw_key)
            if key_name not in IDENTITY_ELEMENT_KEYS:
                _add(findings, lines, key_path + (key_name,), key_name,
                     'identity_v1 element entries may only declare exact identity fields or explicit structural strategy fields')
        match_strategy = spec.get('match_strategy')
        if match_strategy is not None:
            if match_strategy not in IDENTITY_MATCH_STRATEGIES:
                _add(findings, lines, key_path + ('match_strategy',), 'match_strategy',
                     f'identity_v1 match_strategy must be one of {sorted(IDENTITY_MATCH_STRATEGIES)}')
            if match_strategy == 'name_agnostic_structural' and 'name' in spec:
                _add(findings, lines, key_path + ('name',), 'name',
                     'identity_v1 name_agnostic_structural entries must not declare a name')
        required_fields = ('role', 'scope') if match_strategy == 'name_agnostic_structural' else ('name', 'role', 'scope')
        for required in required_fields:
            value = spec.get(required)
            if not isinstance(value, str) or not value or value != value.strip() or _has_wildcard(value):
                _add(findings, lines, key_path + (required,), required,
                     f'identity_v1 {required} must be an exact non-pattern string')
        structural = spec.get('structural')
        if match_strategy == 'name_agnostic_structural':
            if not isinstance(structural, dict) or not structural:
                _add(findings, lines, key_path + ('structural',), 'structural',
                     'identity_v1 name_agnostic_structural requires after/before structural anchors')
            else:
                for structural_key, structural_value in structural.items():
                    structural_key_name = str(structural_key)
                    if structural_key_name not in IDENTITY_STRUCTURAL_KEYS:
                        _add(findings, lines, key_path + ('structural', structural_key_name), structural_key_name,
                             f'identity_v1 structural may only declare {sorted(IDENTITY_STRUCTURAL_KEYS)}')
                        continue
                    if (
                        not isinstance(structural_value, str)
                        or not structural_value
                        or structural_value != structural_value.strip()
                        or _has_wildcard(structural_value)
                    ):
                        _add(findings, lines, key_path + ('structural', structural_key_name), structural_key_name,
                             'identity_v1 structural anchors must be exact element_map keys')
                        continue
                    if structural_value == str(element_key):
                        _add(findings, lines, key_path + ('structural', structural_key_name), structural_key_name,
                             'identity_v1 structural anchors cannot point at the entry they identify')
                    elif structural_value not in element_map:
                        _add(findings, lines, key_path + ('structural', structural_key_name), structural_key_name,
                             'identity_v1 structural anchor must reference an existing element_map key')
                if not any(anchor in structural for anchor in IDENTITY_STRUCTURAL_KEYS):
                    _add(findings, lines, key_path + ('structural',), 'structural',
                         'identity_v1 structural requires at least one after/before anchor')
            reason = spec.get('reason')
            if not isinstance(reason, str) or not reason.strip():
                _add(findings, lines, key_path + ('reason',), 'reason',
                     'identity_v1 name_agnostic_structural requires a non-empty reason')
        elif structural is not None:
            _add(findings, lines, key_path + ('structural',), 'structural',
                 'identity_v1 structural is only allowed with match_strategy: name_agnostic_structural')
        elif 'reason' in spec:
            _add(findings, lines, key_path + ('reason',), 'reason',
                 'identity_v1 reason is only allowed with match_strategy: name_agnostic_structural')
        active_state = spec.get('active_state')
        if active_state is not None:
            if (
                not isinstance(active_state, str)
                or active_state not in IDENTITY_ACTIVE_STATES
                or active_state != active_state.strip()
            ):
                _add(findings, lines, key_path + ('active_state',), 'active_state',
                     f'identity_v1 active_state must be one of {sorted(IDENTITY_ACTIVE_STATES)}')


def _validate_selection_menus(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    data: dict[str, Any],
) -> None:
    workflow = data.get('workflow') or {}
    selection = workflow.get('selection') if isinstance(workflow, dict) else None
    selection_path = ('workflow', 'selection')
    element_map = ((data.get('tree') or {}).get('element_map') or {})
    if not isinstance(selection, dict):
        _add(findings, lines, selection_path, 'selection',
             'identity_v1 requires workflow.selection.menus')
        return
    for key in selection:
        key_name = str(key)
        if key_name not in MENU_SELECTION_KEYS:
            if key_name in LEGACY_SELECTION_KEYS:
                _add(findings, lines, selection_path + (key_name,), key_name,
                     'workflow.selection must use one canonical menus block, not legacy scattered selection keys')
            else:
                _add(findings, lines, selection_path + (key_name,), key_name,
                     'unsupported workflow.selection key; use menus')
    menus = selection.get('menus')
    if not isinstance(menus, dict) or not menus:
        _add(findings, lines, selection_path + ('menus',), 'menus',
             'workflow.selection.menus must be a non-empty mapping')
        return
    for menu_key, menu in menus.items():
        _validate_menu(
            findings,
            lines,
            str(menu_key),
            menu,
            selection_path + ('menus', str(menu_key)),
            element_map,
        )


def _validate_menu(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    menu_key: str,
    menu: object,
    menu_path: tuple[str, ...],
    element_map: dict[str, Any],
) -> None:
    if not isinstance(menu, dict):
        _add(findings, lines, menu_path, menu_key, 'menu entry must be a mapping')
        return
    for raw_key in menu:
        key_name = str(raw_key)
        if key_name not in MENU_KEYS:
            _add(findings, lines, menu_path + (key_name,), key_name,
                 'unsupported menu key')
    select = menu.get('select')
    if select not in MENU_SELECT_VALUES:
        _add(findings, lines, menu_path + ('select',), 'select',
             f'menu.select must be one of {sorted(MENU_SELECT_VALUES)}')
    active_recognition = menu.get('active_recognition')
    if active_recognition not in MENU_ACTIVE_RECOGNITIONS:
        _add(findings, lines, menu_path + ('active_recognition',), 'active_recognition',
             f'menu.active_recognition must be one of {sorted(MENU_ACTIVE_RECOGNITIONS)}')
    for bool_key in ('must_choose', 'resettable_on_followup'):
        if not isinstance(menu.get(bool_key), bool):
            _add(findings, lines, menu_path + (bool_key,), bool_key,
                 f'menu.{bool_key} must be true or false')
    operate = menu.get('operate')
    if not isinstance(operate, dict):
        _add(findings, lines, menu_path + ('operate',), 'operate',
             'menu.operate must be a mapping')
    else:
        _validate_menu_operate(findings, lines, operate, menu_path + ('operate',), element_map)
    options = menu.get('options')
    if not isinstance(options, dict) or not options:
        _add(findings, lines, menu_path + ('options',), 'options',
             'menu.options must be a non-empty mapping')
        options = {}
    else:
        for option_key, option in options.items():
            _validate_menu_option(
                findings,
                lines,
                str(option_key),
                option,
                menu_path + ('options', str(option_key)),
                element_map,
            )
    default_for_fresh = menu.get('default_for_fresh')
    if not isinstance(default_for_fresh, str) or not default_for_fresh.strip():
        _add(findings, lines, menu_path + ('default_for_fresh',), 'default_for_fresh',
             'menu.default_for_fresh must be an option key or none')
    elif default_for_fresh != 'none' and default_for_fresh not in options:
        _add(findings, lines, menu_path + ('default_for_fresh',), 'default_for_fresh',
             'menu.default_for_fresh must name an option key or none')
    example = menu.get('example_rationale')
    if not isinstance(example, str) or not example.strip():
        _add(findings, lines, menu_path + ('example_rationale',), 'example_rationale',
             'menu.example_rationale must be a non-empty teaching string')


def _validate_menu_operate(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    operate: dict[str, Any],
    operate_path: tuple[str, ...],
    element_map: dict[str, Any],
) -> None:
    for raw_key in operate:
        key_name = str(raw_key)
        if key_name not in MENU_OPERATE_KEYS:
            _add(findings, lines, operate_path + (key_name,), key_name,
                 'unsupported menu.operate key')
    trigger = operate.get('trigger')
    if not isinstance(trigger, str) or trigger not in element_map:
        _add(findings, lines, operate_path + ('trigger',), 'trigger',
             'menu.operate.trigger must name an element_map key')
    scope = operate.get('scope')
    if scope not in MENU_OPERATE_SCOPES:
        _add(findings, lines, operate_path + ('scope',), 'scope',
             f'menu.operate.scope must be one of {sorted(MENU_OPERATE_SCOPES)}')


def _validate_menu_option(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    option_key: str,
    option: object,
    option_path: tuple[str, ...],
    element_map: dict[str, Any],
) -> None:
    if not isinstance(option, dict):
        _add(findings, lines, option_path, option_key, 'menu option must be a mapping')
        return
    for raw_key in option:
        key_name = str(raw_key)
        if key_name not in MENU_OPTION_KEYS:
            _add(findings, lines, option_path + (key_name,), key_name,
                 'unsupported menu option key')
    element = option.get('element')
    if not isinstance(element, str) or element not in element_map:
        _add(findings, lines, option_path + ('element',), 'element',
             'menu option element must name an element_map key')
    active_element = option.get('active_element')
    if active_element is not None and (
        not isinstance(active_element, str) or active_element not in element_map
    ):
        _add(findings, lines, option_path + ('active_element',), 'active_element',
             'menu option active_element must name an element_map key')
    active_trigger_names = option.get('active_trigger_names')
    if active_trigger_names is not None and (
        not isinstance(active_trigger_names, list)
        or not active_trigger_names
        or not all(isinstance(name, str) and name.strip() for name in active_trigger_names)
    ):
        _add(findings, lines, option_path + ('active_trigger_names',), 'active_trigger_names',
             'menu option active_trigger_names must be a non-empty list of exact trigger names')
    click_strategy = option.get('click_strategy')
    if click_strategy is not None and click_strategy not in MENU_CLICK_STRATEGIES:
        _add(findings, lines, option_path + ('click_strategy',), 'click_strategy',
             f'menu option click_strategy must be one of {sorted(MENU_CLICK_STRATEGIES)}')
    path = option.get('path')
    if path is None:
        return
    if not isinstance(path, list) or not path:
        _add(findings, lines, option_path + ('path',), 'path',
             'menu option path must be a non-empty ordered list')
        return
    for idx, step in enumerate(path):
        step_path = option_path + ('path', str(idx))
        if not isinstance(step, dict):
            _add(findings, lines, step_path, 'path', 'menu path entries must be mappings')
            continue
        for raw_key in step:
            key_name = str(raw_key)
            if key_name not in MENU_PATH_KEYS:
                _add(findings, lines, step_path + (key_name,), key_name,
                     'unsupported menu path key')
        path_element = step.get('element')
        if not isinstance(path_element, str) or path_element not in element_map:
            _add(findings, lines, step_path + ('element',), 'element',
                 'menu path element must name an element_map key')
        action = step.get('action')
        if action not in MENU_PATH_ACTIONS:
            _add(findings, lines, step_path + ('action',), 'action',
                 f'menu path action must be one of {sorted(MENU_PATH_ACTIONS)}')


def _validate_identity_yaml(
    findings: list[ContractFinding],
    lines: dict[tuple[str, ...], int],
    data: dict[str, Any],
    source: str,
) -> None:
    if ALLOW_RE in source:
        for idx, line in enumerate(source.splitlines(), start=1):
            if ALLOW_RE in line:
                findings.append(ContractFinding(idx, 'lint-allow',
                                                'identity_v1 forbids lint-allow escape hatches'))
    if 'validation' in data:
        _add(findings, lines, ('validation',), 'validation',
             'identity_v1 deletes validation; read live state through active_state recognition rules')
    for key_path, key in _iter_mapping_keys(data):
        if key in IDENTITY_FORBIDDEN_KEYS:
            _add(findings, lines, key_path, key,
                 f'identity_v1 forbids stored/fuzzy matcher key {key!r}')
    element_map = ((data.get('tree') or {}).get('element_map') or {})
    _validate_identity_element_map(findings, lines, element_map)
    _validate_selection_menus(findings, lines, data)


def _validate_chat_yaml(platform: str, path: Path, data: dict[str, Any], source: str) -> None:
    if platform not in CHAT_PLATFORMS:
        return
    lines = _yaml_key_lines(source)
    findings: list[ContractFinding] = []
    if ALLOW_RE in source:
        for idx, line in enumerate(source.splitlines(), start=1):
            if ALLOW_RE in line:
                findings.append(ContractFinding(idx, 'lint-allow',
                                                'consultation_v2 YAML forbids lint-allow escape hatches'))
    _validate_global_exactness(findings, lines, data)
    identity_schema = _uses_identity_schema(data)
    if identity_schema:
        _validate_identity_yaml(findings, lines, data, source)
        _validate_extraction_specs(findings, lines, data)
    else:
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
        _validate_extraction_specs(findings, lines, data)

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
    base_required = ('platform', 'urls', 'tree', 'workflow')
    required = base_required if _uses_identity_schema(data) else base_required + ('validation',)
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


def _build_extraction_workflow(output_type: str, raw: Dict[str, Any]) -> ExtractionWorkflow:
    steps: list[ExtractionStep] = []
    for step in (raw.get('steps') or []):
        steps.append(ExtractionStep(
            action=str(step.get('action')),
            element=step.get('element'),
            select=str(step.get('select', 'last')),
            validation=step.get('validation'),
        ))
    markers = tuple(str(m) for m in (raw.get('validate_markers') or []))
    return ExtractionWorkflow(output_type=output_type, steps=tuple(steps), validate_markers=markers)


def get_extraction(
    platform: str, output_type: str | None = None
) -> Dict[str, ExtractionWorkflow] | ExtractionWorkflow | None:
    """Return the validated extraction workflow(s) for a platform.

    With no `output_type`: a dict of output_type -> ExtractionWorkflow for every
    output type the platform's `extraction:` section maps (empty when absent).
    With an `output_type`: the ExtractionWorkflow for that type, or None when the
    platform does not declare it (the caller fails loud — never downgrades).
    """
    extraction = dict(load_platform_yaml(platform).get('extraction') or {})
    workflows: Dict[str, ExtractionWorkflow] = {
        str(name): _build_extraction_workflow(str(name), dict(raw or {}))
        for name, raw in extraction.items()
    }
    if output_type is None:
        return workflows
    return workflows.get(output_type)


def get_settle(platform: str) -> Dict[str, Any]:
    return dict(load_platform_yaml(platform).get('settle', {}))
