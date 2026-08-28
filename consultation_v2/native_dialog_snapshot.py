from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping

from consultation_v2.platforms import routing as platform_routing

from .yaml_contract import load_platform_yaml


_CONTRACT_KEYS = frozenset({'elements', 'max_depth', 'root', 'schema'})
_ELEMENT_KEYS = frozenset({
    'capture_name',
    'capture_text',
    'name',
    'name_absent',
    'required',
    'required_states',
    'role',
    'scope',
    'structural',
})
_STRUCTURAL_KEYS = frozenset({'anchor', 'parent_scope', 'relation'})
_STRUCTURAL_RELATIONS = frozenset({'descendant', 'direct_child'})


class NativeDialogContractError(ValueError):
    pass


class NativeDialogObservationError(RuntimeError):
    pass


class NativeDialogRevisionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NativeDialogElementRef:
    key: str
    ref: str
    name: str
    role: str
    scope: str
    path: str
    states: tuple[str, ...]
    text: str | None = None
    atspi_obj: Any = field(default=None, repr=False, compare=False)

    def serializable(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'key': self.key,
            'ref': self.ref,
            'name': self.name,
            'role': self.role,
            'scope': self.scope,
            'path': self.path,
            'states': list(self.states),
        }
        if self.text is not None:
            payload['text'] = self.text
        return payload


@dataclass(frozen=True, slots=True)
class NativeDialogSnapshot:
    platform: str
    revision: str
    contract_sha256: str
    root_key: str
    mapped: Mapping[str, tuple[NativeDialogElementRef, ...]]
    raw_count: int
    schema: str = 'native_dialog_snapshot.v1'
    surface: str = 'native_dialog'

    def assert_revision(self, expected_revision: str) -> None:
        if not isinstance(expected_revision, str) or not hmac.compare_digest(
            self.revision,
            expected_revision,
        ):
            raise NativeDialogRevisionError(
                f'native dialog revision is stale: expected {expected_revision!r}, '
                f'observed {self.revision!r}'
            )

    def resolve(
        self,
        key: str,
        *,
        revision: str,
        ref: str,
    ) -> NativeDialogElementRef:
        self.assert_revision(revision)
        items = self.mapped.get(key) or ()
        if len(items) != 1:
            raise NativeDialogObservationError(
                f'native dialog key {key!r} has {len(items)} mapped elements; expected 1'
            )
        element = items[0]
        if not hmac.compare_digest(element.ref, ref):
            raise NativeDialogRevisionError(
                f'native dialog ref is not bound to revision {revision!r}: '
                f'expected {element.ref!r}, received {ref!r}'
            )
        return element

    def serializable(self) -> Dict[str, Any]:
        return {
            'schema': self.schema,
            'surface': self.surface,
            'platform': self.platform,
            'revision': self.revision,
            'contract_sha256': self.contract_sha256,
            'root_key': self.root_key,
            'mapped': {
                key: [item.serializable() for item in items]
                for key, items in self.mapped.items()
            },
            'mapped_counts': {
                key: len(items)
                for key, items in self.mapped.items()
            },
            'raw_count': self.raw_count,
        }


@dataclass(frozen=True, slots=True)
class _ObservedNode:
    obj: Any = field(repr=False, compare=False)
    name: str = ''
    role: str = ''
    scope: str = ''
    path: str = ''
    parent_path: str | None = None
    ancestor_paths: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    text: str | None = None

    def public(self, key: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'key': key,
            'name': self.name,
            'role': self.role,
            'scope': self.scope,
            'path': self.path,
            'parent_path': self.parent_path,
            'ancestor_paths': list(self.ancestor_paths),
            'states': list(self.states),
        }
        if self.text is not None:
            payload['text'] = self.text
        return payload


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _exact_strings(value: Any, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        raise NativeDialogContractError(
            f'{label} must be a non-empty unique list of exact strings'
        )
    return tuple(value)


def normalize_native_dialog_contract(
    raw: Any,
    *,
    authority: str,
) -> Dict[str, Any]:
    if not isinstance(authority, str) or not authority:
        raise NativeDialogContractError('native dialog authority must be non-empty')
    platform = authority
    if not isinstance(raw, dict):
        raise NativeDialogContractError(f'{platform}: native_dialog contract is missing')
    if set(raw) != _CONTRACT_KEYS:
        raise NativeDialogContractError(
            f'{platform}: native_dialog keys must be exactly {sorted(_CONTRACT_KEYS)}'
        )
    if raw.get('schema') != 'native_dialog_v1':
        raise NativeDialogContractError(
            f'{platform}: native_dialog.schema must equal native_dialog_v1'
        )
    max_depth = raw.get('max_depth')
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 1 <= max_depth <= 64:
        raise NativeDialogContractError(
            f'{platform}: native_dialog.max_depth must be an integer from 1 through 64'
        )
    root_key = raw.get('root')
    elements = raw.get('elements')
    if not isinstance(root_key, str) or not root_key:
        raise NativeDialogContractError(
            f'{platform}: native_dialog.root must be one exact non-empty key'
        )
    if not isinstance(elements, dict) or not elements or root_key not in elements:
        raise NativeDialogContractError(
            f'{platform}: native_dialog.elements must map the declared root'
        )

    normalized: Dict[str, Dict[str, Any]] = {}
    for key, candidate in elements.items():
        if not isinstance(key, str) or not key:
            raise NativeDialogContractError(
                f'{platform}: native_dialog element keys must be non-empty strings'
            )
        if not isinstance(candidate, dict):
            raise NativeDialogContractError(
                f'{platform}: native_dialog.elements.{key} must be a mapping'
            )
        unknown = sorted(set(candidate) - _ELEMENT_KEYS)
        if unknown:
            raise NativeDialogContractError(
                f'{platform}: native_dialog.elements.{key} has unsupported keys {unknown}'
            )
        role = candidate.get('role')
        scope = candidate.get('scope')
        if not isinstance(role, str) or not role:
            raise NativeDialogContractError(
                f'{platform}: native_dialog.elements.{key}.role must be one exact string'
            )
        if not isinstance(scope, str) or not scope:
            raise NativeDialogContractError(
                f'{platform}: native_dialog.elements.{key}.scope must be one exact string'
            )
        required_states = _exact_strings(
            candidate.get('required_states'),
            f'{platform}: native_dialog.elements.{key}.required_states',
        )
        for boolean_key in ('capture_name', 'capture_text', 'required'):
            if boolean_key in candidate and not isinstance(candidate[boolean_key], bool):
                raise NativeDialogContractError(
                    f'{platform}: native_dialog.elements.{key}.{boolean_key} must be boolean'
                )

        spec = dict(candidate)
        spec['required_states'] = list(required_states)
        structural = spec.get('structural')
        if not isinstance(structural, dict) or not structural:
            raise NativeDialogContractError(
                f'{platform}: native_dialog.elements.{key}.structural must be a mapping'
            )
        if set(structural) - _STRUCTURAL_KEYS:
            raise NativeDialogContractError(
                f'{platform}: native_dialog.elements.{key}.structural has unsupported '
                f'keys {sorted(set(structural) - _STRUCTURAL_KEYS)}'
            )
        relation = structural.get('relation')
        if relation not in _STRUCTURAL_RELATIONS:
            raise NativeDialogContractError(
                f'{platform}: native_dialog.elements.{key}.structural.relation must '
                f'be one of {sorted(_STRUCTURAL_RELATIONS)}'
            )
        if key == root_key:
            if 'name' in spec:
                raise NativeDialogContractError(
                    f'{platform}: dynamic native root name is evidence, not selector authority'
                )
            if spec.get('capture_name') is not True:
                raise NativeDialogContractError(
                    f'{platform}: native dialog root must capture its dynamic exact name'
                )
            if structural != {
                'relation': 'direct_child',
                'parent_scope': 'firefox_application',
            }:
                raise NativeDialogContractError(
                    f'{platform}: native dialog root must be a direct Firefox-application child'
                )
            if spec.get('required') is False:
                raise NativeDialogContractError(
                    f'{platform}: native dialog root must be required'
                )
        else:
            name_absent = spec.get('name_absent')
            if name_absent is not None and not isinstance(name_absent, bool):
                raise NativeDialogContractError(
                    f'{platform}: native_dialog.elements.{key}.name_absent must be boolean'
                )
            has_exact_name = isinstance(spec.get('name'), str) and bool(spec['name'])
            if has_exact_name == bool(name_absent):
                raise NativeDialogContractError(
                    f'{platform}: native_dialog.elements.{key} must declare exactly one '
                    'exact non-empty name or name_absent: true'
                )
            if set(structural) != {'anchor', 'relation'}:
                raise NativeDialogContractError(
                    f'{platform}: native_dialog.elements.{key}.structural must declare '
                    'exactly relation and anchor'
                )
            relation_key = structural['anchor']
            if not isinstance(relation_key, str) or relation_key not in normalized:
                raise NativeDialogContractError(
                    f'{platform}: native_dialog.elements.{key}.structural.anchor must '
                    'reference an earlier exact element key'
                )
            if spec.get('capture_name'):
                raise NativeDialogContractError(
                    f'{platform}: only the dynamic native root may use capture_name'
                )
        normalized[key] = spec

    return {
        'schema': raw['schema'],
        'root': root_key,
        'max_depth': max_depth,
        'elements': normalized,
    }


def _native_dialog_contract(platform: str) -> Dict[str, Any]:
    raw = load_platform_yaml(platform).get('native_dialog')
    return normalize_native_dialog_contract(raw, authority=platform)


def _state_names(obj: Any) -> tuple[str, ...]:
    state_set = obj.get_state_set()
    if state_set is None:
        raise NativeDialogObservationError('AT-SPI element returned no state set')
    states = state_set.get_states()
    return tuple(sorted(state.value_nick for state in states))


def _observed_node(
    obj: Any,
    path: str,
    *,
    scope: str = '',
    parent_path: str | None = None,
    ancestor_paths: tuple[str, ...] = (),
) -> _ObservedNode:
    name = obj.get_name()
    role = obj.get_role_name()
    if name is None or role is None:
        raise NativeDialogObservationError('AT-SPI element returned null name or role')
    return _ObservedNode(
        obj=obj,
        name=str(name),
        role=str(role),
        scope=scope,
        path=path,
        parent_path=parent_path,
        ancestor_paths=ancestor_paths,
        states=_state_names(obj),
    )


def _children(obj: Any) -> list[tuple[int, Any]]:
    count = int(obj.get_child_count())
    children: list[tuple[int, Any]] = []
    for index in range(count):
        child = obj.get_child_at_index(index)
        if child is None:
            raise NativeDialogObservationError(
                f'AT-SPI child {index} of {count} is unavailable'
            )
        children.append((index, child))
    return children


def _subtree(
    root: Any,
    root_path: str,
    max_depth: int,
    capture_text_specs: tuple[Mapping[str, Any], ...],
) -> list[_ObservedNode]:
    observed: list[_ObservedNode] = []

    def walk(
        obj: Any,
        path: str,
        depth: int,
        ancestor_paths: tuple[str, ...],
    ) -> None:
        node = _observed_node(
            obj,
            path,
            parent_path=ancestor_paths[-1] if ancestor_paths else None,
            ancestor_paths=ancestor_paths,
        )
        if any(_node_matches(node, spec) for spec in capture_text_specs):
            node = _ObservedNode(
                obj=node.obj,
                name=node.name,
                role=node.role,
                scope=node.scope,
                path=node.path,
                parent_path=node.parent_path,
                ancestor_paths=node.ancestor_paths,
                states=node.states,
                text=_read_text(node.obj),
            )
        observed.append(node)
        if depth >= max_depth:
            return
        for index, child in _children(obj):
            walk(child, f'{path}/{index}', depth + 1, (*ancestor_paths, path))

    walk(root, root_path, 0, ())
    return observed


def _states_match(node: _ObservedNode, spec: Mapping[str, Any]) -> bool:
    return set(spec['required_states']).issubset(node.states)


def _node_matches(node: _ObservedNode, spec: Mapping[str, Any]) -> bool:
    if node.role != spec['role'] or not _states_match(node, spec):
        return False
    if spec.get('name_absent'):
        return node.name == ''
    return 'name' not in spec or node.name == spec['name']


def _has_parent(node: _ObservedNode, parent: _ObservedNode) -> bool:
    return node.parent_path == parent.path


def _has_ancestor(node: _ObservedNode, ancestor: _ObservedNode) -> bool:
    return ancestor.path in node.ancestor_paths


def _read_text(obj: Any) -> str:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi

    text_iface = obj.get_text_iface()
    if text_iface is None:
        raise NativeDialogObservationError('mapped text element has no AT-SPI Text interface')
    character_count = int(Atspi.Text.get_character_count(text_iface))
    if character_count < 0:
        raise NativeDialogObservationError(
            f'mapped text element returned invalid character count {character_count}'
        )
    return str(Atspi.Text.get_text(text_iface, 0, character_count))


def _candidate_evidence(nodes: Iterable[_ObservedNode]) -> list[Dict[str, Any]]:
    return [
        {
            'name': node.name,
            'role': node.role,
            'path': node.path,
            'states': list(node.states),
        }
        for node in nodes
    ]


def _capture_native_dialog_snapshot(
    platform: str,
    contract: Mapping[str, Any],
    firefox: Any,
    *,
    revision_binding_sha256: str | None = None,
) -> NativeDialogSnapshot:
    root_key = contract['root']
    root_spec = contract['elements'][root_key]

    direct_children = [
        _observed_node(child, f'FIREFOX/{index}')
        for index, child in _children(firefox)
    ]
    outer_roots = [node for node in direct_children if node.role == root_spec['role']]
    if not outer_roots:
        raise NativeDialogObservationError(
            f'{platform}: native dialog root not observed among direct Firefox children; '
            f'observed={json.dumps(_candidate_evidence(direct_children), sort_keys=True)}'
        )
    if len(outer_roots) != 1:
        raise NativeDialogObservationError(
            f'{platform}: native dialog root is ambiguous ({len(outer_roots)} direct '
            f'Firefox children); matches={json.dumps(_candidate_evidence(outer_roots), sort_keys=True)}'
        )
    root_probe = outer_roots[0]

    capture_text_specs = tuple(
        spec
        for spec in contract['elements'].values()
        if spec.get('capture_text')
    )
    subtree = _subtree(
        root_probe.obj,
        root_probe.path,
        contract['max_depth'],
        capture_text_specs,
    )
    root = subtree[0]
    if root.role != root_spec['role']:
        raise NativeDialogObservationError(
            f'{platform}: native dialog root role drift during capture at {root.path}; '
            f'expected={root_spec["role"]!r} observed={root.role!r}'
        )
    if not _states_match(root, root_spec):
        raise NativeDialogObservationError(
            f'{platform}: native dialog root state drift during capture at {root.path}; '
            f'expected={root_spec["required_states"]!r} observed={list(root.states)!r}'
        )
    selected: Dict[str, tuple[_ObservedNode, ...]] = {}
    for key, spec in contract['elements'].items():
        if key == root_key:
            matches = [root]
        else:
            structural = spec['structural']
            relation = structural['relation']
            relation_key = structural['anchor']
            relation_nodes = selected.get(relation_key) or ()
            if len(relation_nodes) != 1:
                if spec.get('required', True):
                    raise NativeDialogObservationError(
                        f'{platform}: native dialog {key!r} cannot bind required '
                        f'{relation} {relation_key!r}'
                    )
                selected[key] = ()
                continue
            anchor = relation_nodes[0]
            relation_matches = _has_parent if relation == 'direct_child' else _has_ancestor
            matches = [
                node
                for node in subtree
                if _node_matches(node, spec) and relation_matches(node, anchor)
            ]
        if len(matches) > 1:
            raise NativeDialogObservationError(
                f'{platform}: native dialog {key!r} is ambiguous ({len(matches)}); '
                f'matches={json.dumps(_candidate_evidence(matches), sort_keys=True)}'
            )
        if not matches:
            if spec.get('required', True):
                raise NativeDialogObservationError(
                    f'{platform}: required native dialog element {key!r} was not observed'
                )
            selected[key] = ()
            continue
        match = matches[0]
        selected[key] = (
            _ObservedNode(
                obj=match.obj,
                name=match.name,
                role=match.role,
                scope=spec['scope'],
                path=match.path,
                parent_path=match.parent_path,
                ancestor_paths=match.ancestor_paths,
                states=match.states,
                text=match.text if spec.get('capture_text') else None,
            ),
        )

    contract_sha256 = _canonical_digest(contract)
    revision_payload = {
        'schema': 'native_dialog_revision.v1',
        'surface': 'native_dialog',
        'platform': platform,
        'contract_sha256': contract_sha256,
        'mapped': {
            key: [node.public(key) for node in nodes]
            for key, nodes in selected.items()
        },
    }
    if revision_binding_sha256 is not None:
        revision_payload['binding_sha256'] = revision_binding_sha256
    revision = _canonical_digest(revision_payload)
    mapped: Dict[str, tuple[NativeDialogElementRef, ...]] = {}
    for key, nodes in selected.items():
        mapped[key] = tuple(
            NativeDialogElementRef(
                key=key,
                ref=f'nd1_{_canonical_digest([revision, key, node.path])}',
                name=node.name,
                role=node.role,
                scope=node.scope,
                path=node.path,
                states=node.states,
                text=node.text,
                atspi_obj=node.obj,
            )
            for node in nodes
        )
    return NativeDialogSnapshot(
        platform=platform,
        revision=revision,
        contract_sha256=contract_sha256,
        root_key=root_key,
        mapped=mapped,
        raw_count=len(subtree),
    )


def build_native_dialog_snapshot_from_contract(
    platform: str,
    *,
    contract: Mapping[str, Any],
    firefox: Any,
    expected_firefox_pid: int,
    revision_binding_sha256: str | None = None,
) -> NativeDialogSnapshot:
    if not isinstance(platform, str) or not platform:
        raise NativeDialogContractError('native dialog platform must be non-empty')
    if (
        isinstance(expected_firefox_pid, bool)
        or not isinstance(expected_firefox_pid, int)
        or expected_firefox_pid <= 0
    ):
        raise NativeDialogContractError('expected Firefox PID must be a positive integer')
    if revision_binding_sha256 is not None and (
        not isinstance(revision_binding_sha256, str)
        or len(revision_binding_sha256) != 64
        or any(character not in '0123456789abcdef' for character in revision_binding_sha256)
    ):
        raise NativeDialogContractError(
            'native dialog revision binding must be one lowercase SHA-256'
        )
    normalized = normalize_native_dialog_contract(contract, authority=platform)
    try:
        actual_firefox_pid = int(firefox.get_process_id())
    except Exception as exc:
        raise NativeDialogObservationError(
            f'{platform}: exact Firefox process identity is unavailable'
        ) from exc
    if actual_firefox_pid != expected_firefox_pid:
        raise NativeDialogObservationError(
            f'{platform}: Firefox PID mismatch: expected {expected_firefox_pid}, '
            f'observed {actual_firefox_pid}'
        )

    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi

    desktop = Atspi.get_desktop(0)
    desktop.clear_cache_single()
    firefox.clear_cache_single()
    return _capture_native_dialog_snapshot(
        platform,
        normalized,
        firefox,
        revision_binding_sha256=revision_binding_sha256,
    )


def build_native_dialog_snapshot(platform: str) -> NativeDialogSnapshot:
    contract = _native_dialog_contract(platform)

    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi

    desktop = Atspi.get_desktop(0)
    desktop.clear_cache_single()
    firefox = platform_routing.find_firefox_for_platform(platform)
    if firefox is None:
        raise NativeDialogObservationError(f'Firefox not found for {platform}')
    firefox.clear_cache_single()
    return _capture_native_dialog_snapshot(platform, contract, firefox)


__all__ = [
    'NativeDialogContractError',
    'NativeDialogElementRef',
    'NativeDialogObservationError',
    'NativeDialogRevisionError',
    'NativeDialogSnapshot',
    'build_native_dialog_snapshot',
    'build_native_dialog_snapshot_from_contract',
    'normalize_native_dialog_contract',
]
