from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

import yaml

from .types import ElementRef, Snapshot


CONTRACT_VERSION = 'supervised_ui_v1'
POLICY_SCHEMA = 'supervised_ui_policy_v1'
PROJECTION_SCHEMA = 'supervised_ui_projection_v1'
TRAINING_PROTOCOL_COMMIT = '58b108042e66fa508765a6277c033cc5a8f86abd'

_PLATFORM_RE = re.compile(r'^[a-z][a-z0-9_]{0,31}$')
_CONTROL_ID_RE = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
_REF_RE = re.compile(r'^r_[0-9a-f]{32}$')
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
)
_PUBLIC_ROLES = frozenset({
    'check box',
    'combo box',
    'entry',
    'menu item',
    'option',
    'page tab',
    'push button',
    'radio button',
    'radio menu item',
    'toggle button',
})
_PUBLIC_STATES = frozenset({
    'active',
    'checked',
    'editable',
    'enabled',
    'expandable',
    'expanded',
    'focusable',
    'focused',
    'indeterminate',
    'modal',
    'multi line',
    'pressed',
    'required',
    'selectable',
    'selected',
    'showing',
    'single line',
    'visible',
})
_ACTION_OPERATIONS = frozenset({'activate', 'focus'})
_READ_OPERATIONS = frozenset({'observe', 'verify'})
RUNTIME_CONFIG_SCHEMA = 'supervised_ui_runtime_config_v1'
_PUBLIC_TEXT_FORBIDDEN = re.compile(
    r'(?:https?://|www\.|[/\\]|@|token|secret|password|credential|api[_ -]?key|'
    r'claude|chatgpt|openai|gemini|google|grok|perplexity|nvidia|reddit)',
    re.IGNORECASE,
)


class SupervisedUiContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PolicyControl:
    mapping_key: str
    control_id: str
    label: str
    role: str
    operations: tuple[str, ...]
    effect_class: str
    postconditions: Mapping[str, 'OperationPostcondition']


@dataclass(frozen=True, slots=True)
class StatePredicate:
    present: bool
    states_include: tuple[str, ...]
    states_exclude: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperationPostcondition:
    before: StatePredicate
    after: StatePredicate


@dataclass(frozen=True, slots=True)
class SupervisedPolicy:
    platform: str
    controls: Mapping[str, PolicyControl]


@dataclass(frozen=True, slots=True)
class ProjectedSnapshot:
    public: Mapping[str, Any]
    bindings: Mapping[str, ElementRef]
    omissions: tuple[Mapping[str, Any], ...]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')


def sha256_hex(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def _policy_path(platform: str) -> Path:
    if not isinstance(platform, str) or not _PLATFORM_RE.fullmatch(platform):
        raise SupervisedUiContractError('invalid supervised UI platform identifier')
    return Path(__file__).resolve().parent / 'platforms' / platform / 'supervised_ui.yaml'


def _runtime_config_paths(platform: str) -> Mapping[str, Path]:
    policy_path = _policy_path(platform)
    package_root = Path(__file__).resolve().parent
    return {
        'consultation_v2/firefox_chrome.yaml': package_root / 'firefox_chrome.yaml',
        f'consultation_v2/platforms/{platform}/{platform}.yaml': (
            package_root / 'platforms' / platform / f'{platform}.yaml'
        ),
        f'consultation_v2/platforms/{platform}/supervised_ui.yaml': policy_path,
    }


def validate_runtime_config_manifest(
    value: Any,
    platform: str,
) -> dict[str, Any]:
    document = _plain_mapping(value, 'runtime_config')
    _require_exact_keys(
        document,
        required=frozenset({'files', 'platform', 'schema', 'sha256'}),
        context='runtime_config',
    )
    if document['schema'] != RUNTIME_CONFIG_SCHEMA or document['platform'] != platform:
        raise SupervisedUiContractError('runtime_config identity is invalid')
    files = _plain_mapping(document['files'], 'runtime_config.files')
    expected_paths = frozenset(_runtime_config_paths(platform))
    if frozenset(files) != expected_paths:
        raise SupervisedUiContractError('runtime_config file set is invalid')
    normalized_files: dict[str, str] = {}
    for relative_path, digest in sorted(files.items()):
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise SupervisedUiContractError(
                f'runtime_config digest is invalid for {relative_path}'
            )
        normalized_files[relative_path] = digest
    unsigned = {
        'files': normalized_files,
        'platform': platform,
        'schema': RUNTIME_CONFIG_SCHEMA,
    }
    expected_digest = sha256_hex(canonical_json_bytes(unsigned))
    if not isinstance(document['sha256'], str) or not hmac.compare_digest(
        document['sha256'],
        expected_digest,
    ):
        raise SupervisedUiContractError('runtime_config aggregate digest is invalid')
    return {**unsigned, 'sha256': expected_digest}


def runtime_config_manifest(platform: str) -> dict[str, Any]:
    package_root = Path(__file__).resolve().parent
    files: dict[str, str] = {}
    for relative_path, path in sorted(_runtime_config_paths(platform).items()):
        resolved = path.resolve(strict=True)
        current = path
        while current != package_root:
            if current.is_symlink():
                raise SupervisedUiContractError(
                    f'runtime config path is missing or unsafe: {relative_path}'
                )
            current = current.parent
        if not resolved.is_relative_to(package_root):
            raise SupervisedUiContractError(
                f'runtime config path is missing or unsafe: {relative_path}'
            )
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise SupervisedUiContractError(
                    f'runtime config path is missing or unsafe: {relative_path}'
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(descriptor)
        files[relative_path] = sha256_hex(b''.join(chunks))
    unsigned = {
        'files': files,
        'platform': platform,
        'schema': RUNTIME_CONFIG_SCHEMA,
    }
    return {**unsigned, 'sha256': sha256_hex(canonical_json_bytes(unsigned))}


def _plain_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise SupervisedUiContractError(f'{context} must be a string-keyed mapping')
    return dict(value)


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    context: str,
) -> None:
    keys = frozenset(value)
    if keys != required:
        missing = sorted(required - keys)
        unknown = sorted(keys - required)
        raise SupervisedUiContractError(
            f'{context} keys mismatch: missing={missing}, unknown={unknown}'
        )


def _public_label(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise SupervisedUiContractError(f'{context} must be a string')
    normalized = ' '.join(value.split())
    if not normalized or len(normalized) > 80:
        raise SupervisedUiContractError(f'{context} must contain 1-80 visible characters')
    if not normalized.isascii() or _PUBLIC_TEXT_FORBIDDEN.search(normalized):
        raise SupervisedUiContractError(f'{context} is not public-safe')
    return normalized


def _normalized_state(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise SupervisedUiContractError(f'{context} must be a string')
    normalized = ' '.join(value.strip().lower().replace('_', ' ').split())
    if normalized not in _PUBLIC_STATES:
        raise SupervisedUiContractError(f'{context} contains disallowed state {value!r}')
    return normalized


def _state_predicate(value: Any, context: str) -> StatePredicate:
    predicate = _plain_mapping(value, context)
    predicate_keys = frozenset(predicate)
    state_keys = frozenset({'states_include', 'states_exclude'})
    if predicate_keys not in {state_keys, state_keys | {'present'}}:
        raise SupervisedUiContractError(f'{context} fields are incomplete or unknown')
    present = predicate.get('present', True)
    if not isinstance(present, bool):
        raise SupervisedUiContractError(f'{context}.present must be boolean')
    normalized: dict[str, tuple[str, ...]] = {}
    for condition_key in ('states_include', 'states_exclude'):
        values = predicate[condition_key]
        if not isinstance(values, list):
            raise SupervisedUiContractError(f'{context}.{condition_key} must be a list')
        states = tuple(sorted({
            _normalized_state(item, f'{context}.{condition_key}')
            for item in values
        }))
        if len(states) != len(values):
            raise SupervisedUiContractError(f'{context}.{condition_key} contains duplicates')
        normalized[condition_key] = states
    included = frozenset(normalized['states_include'])
    excluded = frozenset(normalized['states_exclude'])
    if included & excluded:
        raise SupervisedUiContractError(f'{context} includes and excludes the same state')
    if not present and (included or excluded):
        raise SupervisedUiContractError(f'{context} cannot assert states while absent')
    return StatePredicate(
        present=present,
        states_include=normalized['states_include'],
        states_exclude=normalized['states_exclude'],
    )


@lru_cache(maxsize=None)
def load_supervised_policy(platform: str) -> SupervisedPolicy:
    path = _policy_path(platform)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    document = _plain_mapping(raw, path.name)
    _require_exact_keys(
        document,
        required=frozenset({'schema', 'controls'}),
        context=path.name,
    )
    if document['schema'] != POLICY_SCHEMA:
        raise SupervisedUiContractError(f'{path.name} has unsupported schema')
    raw_controls = _plain_mapping(document['controls'], f'{path.name}.controls')
    if not raw_controls:
        raise SupervisedUiContractError(f'{path.name}.controls must not be empty')

    controls: dict[str, PolicyControl] = {}
    public_ids: set[str] = set()
    for mapping_key, raw_control in sorted(raw_controls.items()):
        if not _CONTROL_ID_RE.fullmatch(mapping_key):
            raise SupervisedUiContractError(f'invalid mapping key {mapping_key!r}')
        control = _plain_mapping(raw_control, f'controls.{mapping_key}')
        _require_exact_keys(
            control,
            required=frozenset({
                'control_id',
                'effect_class',
                'label',
                'operations',
                'postconditions',
                'role',
            }),
            context=f'controls.{mapping_key}',
        )
        control_id = control['control_id']
        if not isinstance(control_id, str) or not _CONTROL_ID_RE.fullmatch(control_id):
            raise SupervisedUiContractError(f'controls.{mapping_key}.control_id is invalid')
        if _PUBLIC_TEXT_FORBIDDEN.search(control_id):
            raise SupervisedUiContractError(f'controls.{mapping_key}.control_id is not public-safe')
        if control_id in public_ids:
            raise SupervisedUiContractError(f'duplicate public control_id {control_id!r}')
        public_ids.add(control_id)
        label = _public_label(control['label'], f'controls.{mapping_key}.label')
        role = control['role']
        if role not in _PUBLIC_ROLES:
            raise SupervisedUiContractError(f'controls.{mapping_key}.role is not allowlisted')
        operations_value = control['operations']
        if not isinstance(operations_value, list) or not operations_value:
            raise SupervisedUiContractError(f'controls.{mapping_key}.operations must be a list')
        if any(operation not in _ACTION_OPERATIONS for operation in operations_value):
            raise SupervisedUiContractError(f'controls.{mapping_key}.operations is not P0-safe')
        operations = tuple(sorted(set(operations_value)))
        if len(operations) != len(operations_value):
            raise SupervisedUiContractError(f'controls.{mapping_key}.operations contains duplicates')
        if control['effect_class'] != 'local':
            raise SupervisedUiContractError(f'controls.{mapping_key}.effect_class must be local')
        raw_postconditions = _plain_mapping(
            control['postconditions'],
            f'controls.{mapping_key}.postconditions',
        )
        if frozenset(raw_postconditions) != frozenset(operations):
            raise SupervisedUiContractError(
                f'controls.{mapping_key}.postconditions must cover exactly its operations'
            )
        postconditions: dict[str, OperationPostcondition] = {}
        for operation in operations:
            postcondition = _plain_mapping(
                raw_postconditions[operation],
                f'controls.{mapping_key}.postconditions.{operation}',
            )
            context = f'controls.{mapping_key}.postconditions.{operation}'
            if frozenset(postcondition) == frozenset({'before', 'after'}):
                before = _state_predicate(postcondition['before'], f'{context}.before')
                after = _state_predicate(postcondition['after'], f'{context}.after')
                if before == after:
                    raise SupervisedUiContractError(
                        f'{context} before and after predicates must differ'
                    )
            else:
                if operation == 'activate':
                    raise SupervisedUiContractError(
                        f'{context} must define distinct before and after predicates'
                    )
                after = _state_predicate(postcondition, context)
                if not after.states_include:
                    raise SupervisedUiContractError(
                        f'{context} must include a state for an implicit before predicate'
                    )
                before = StatePredicate(
                    present=True,
                    states_include=(),
                    states_exclude=after.states_include,
                )
            postconditions[operation] = OperationPostcondition(before=before, after=after)
        controls[mapping_key] = PolicyControl(
            mapping_key=mapping_key,
            control_id=control_id,
            label=label,
            role=role,
            operations=operations,
            effect_class='local',
            postconditions=postconditions,
        )
    return SupervisedPolicy(platform=platform, controls=controls)


def clear_supervised_policy_cache() -> None:
    load_supervised_policy.cache_clear()


def _lease_secret(value: bytes | bytearray) -> bytes:
    if not isinstance(value, (bytes, bytearray)) or len(value) < 32:
        raise SupervisedUiContractError('lease secret must contain at least 32 bytes')
    return bytes(value)


def _public_states(states: list[str]) -> list[str]:
    public: set[str] = set()
    for value in states:
        if not isinstance(value, str):
            continue
        normalized = ' '.join(value.strip().lower().replace('_', ' ').split())
        if normalized in _PUBLIC_STATES:
            public.add(normalized)
    return sorted(public)


def state_predicate_matches(
    present: bool,
    states: set[str],
    predicate: StatePredicate,
) -> bool:
    return (
        present == predicate.present
        and set(predicate.states_include).issubset(states)
        and set(predicate.states_exclude).isdisjoint(states)
    )


def project_snapshot(snapshot: Snapshot, lease_secret: bytes) -> ProjectedSnapshot:
    secret = _lease_secret(lease_secret)
    policy = load_supervised_policy(snapshot.platform)
    public_elements: list[dict[str, Any]] = []
    bindings: dict[str, ElementRef] = {}
    omissions: list[Mapping[str, Any]] = []
    for mapping_key, control in sorted(policy.controls.items()):
        matches = list((snapshot.mapped or {}).get(mapping_key) or ())
        if len(matches) != 1:
            if matches:
                omissions.append({
                    'control_id': control.control_id,
                    'reason': 'mapping_collision',
                    'match_count': len(matches),
                })
            continue
        element = matches[0]
        runtime_role = ' '.join(str(element.role).strip().lower().split())
        if runtime_role != control.role:
            omissions.append({
                'control_id': control.control_id,
                'reason': 'role_mismatch',
                'match_count': 1,
            })
            continue
        digest = hmac.new(
            secret,
            b'supervised-ui-ref-v1\x00' + mapping_key.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()[:32]
        ref = f'r_{digest}'
        if ref in bindings:
            raise SupervisedUiContractError('opaque ref collision')
        bindings[ref] = element
        public_states = _public_states(element.states)
        permitted_operations = [
            operation
            for operation in control.operations
            if state_predicate_matches(
                True,
                set(public_states),
                control.postconditions[operation].before,
            )
        ]
        public_elements.append({
            'control_id': control.control_id,
            'effect_class': control.effect_class,
            'label': control.label,
            'operations': permitted_operations,
            'ref': ref,
            'role': control.role,
            'states': public_states,
        })
    public_elements.sort(key=lambda item: (item['control_id'], item['ref']))
    public = {
        'schema': PROJECTION_SCHEMA,
        'elements': public_elements,
    }
    return ProjectedSnapshot(
        public=public,
        bindings=bindings,
        omissions=tuple(omissions),
    )


def snapshot_revision(
    projection: ProjectedSnapshot | Mapping[str, Any],
    lease_secret: bytes,
) -> str:
    secret = _lease_secret(lease_secret)
    public = projection.public if isinstance(projection, ProjectedSnapshot) else projection
    digest = hmac.new(
        secret,
        b'supervised-ui-revision-v1\x00' + canonical_json_bytes(public),
        hashlib.sha256,
    ).hexdigest()
    return f'v1_{digest}'


def _read_parameters(operation: str) -> dict[str, Any]:
    return {
        'type': 'object',
        'additionalProperties': False,
        'properties': {'op': {'type': 'string', 'const': operation}},
        'required': ['op'],
    }


def build_live_ui_action_schema(
    state: str,
    projection: ProjectedSnapshot | Mapping[str, Any] | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    if state == 'needs_observe':
        parameters = _read_parameters('observe')
    elif state == 'needs_verify':
        parameters = _read_parameters('verify')
    elif state == 'action_ready':
        if projection is None or not isinstance(revision, str) or not revision.startswith('v1_'):
            raise SupervisedUiContractError('action_ready schema requires projection and revision')
        public = projection.public if isinstance(projection, ProjectedSnapshot) else projection
        elements = public.get('elements') if isinstance(public, Mapping) else None
        if not isinstance(elements, list):
            raise SupervisedUiContractError('invalid public projection')
        alternatives: list[dict[str, Any]] = []
        for element in elements:
            if not isinstance(element, Mapping):
                raise SupervisedUiContractError('invalid projected element')
            ref = element.get('ref')
            operations = element.get('operations')
            if not isinstance(ref, str) or not _REF_RE.fullmatch(ref):
                raise SupervisedUiContractError('invalid projected ref')
            if not isinstance(operations, list):
                raise SupervisedUiContractError('invalid projected operations')
            for operation in operations:
                if operation not in _ACTION_OPERATIONS:
                    raise SupervisedUiContractError('invalid projected operation')
                alternatives.append({
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'op': {'type': 'string', 'const': operation},
                        'ref': {'type': 'string', 'const': ref},
                        'revision': {'type': 'string', 'const': revision},
                    },
                    'required': ['op', 'ref', 'revision'],
                })
        if not alternatives:
            raise SupervisedUiContractError('projection exposes no permitted local action')
        parameters = {'type': 'object', 'oneOf': alternatives}
    else:
        raise SupervisedUiContractError(f'state {state!r} has no live tool schema')
    return {
        'type': 'function',
        'function': {
            'name': 'ui_action',
            'description': 'Propose exactly one operation permitted by the current public UI state.',
            'strict': True,
            'parameters': parameters,
        },
    }


def _parse_exact_call(raw_bytes: bytes) -> dict[str, Any]:
    if not isinstance(raw_bytes, bytes) or not raw_bytes:
        raise SupervisedUiContractError('proposal must be nonempty exact bytes')

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SupervisedUiContractError(f'duplicate proposal key {key!r}')
            result[key] = value
        return result

    try:
        text = raw_bytes.decode('utf-8')
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                SupervisedUiContractError('proposal contains a non-JSON constant')
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisedUiContractError('proposal is not strict UTF-8 JSON') from exc
    return _plain_mapping(value, 'proposal')


def _opaque_uuid(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        raise SupervisedUiContractError(f'{context} must be a lowercase UUID')
    return value


def validate_approved_call(
    call: bytes,
    approval: Mapping[str, Any],
    projection: ProjectedSnapshot | None,
) -> dict[str, Any]:
    proposal = _parse_exact_call(call)
    approval_map = _plain_mapping(approval, 'approval')
    required_approval = frozenset({
        'actor_id',
        'approval_id',
        'capability_sha256',
        'effect_class',
        'execution_id',
        'expires_at',
        'hands_incarnation_id',
        'observation_id',
        'operation',
        'presence_incarnation_id',
        'proposal_id',
        'proposal_sha256',
        'ref',
        'revision',
        'turn_id',
    })
    _require_exact_keys(approval_map, required=required_approval, context='approval')
    for key in (
        'actor_id',
        'approval_id',
        'execution_id',
        'hands_incarnation_id',
        'presence_incarnation_id',
        'proposal_id',
        'turn_id',
    ):
        _opaque_uuid(approval_map[key], f'approval.{key}')
    observation_id = approval_map['observation_id']
    if observation_id is not None:
        _opaque_uuid(observation_id, 'approval.observation_id')
    for key in ('capability_sha256', 'proposal_sha256'):
        if not isinstance(approval_map[key], str) or not _SHA256_RE.fullmatch(approval_map[key]):
            raise SupervisedUiContractError(f'approval.{key} must be a SHA-256 digest')
    if not hmac.compare_digest(approval_map['proposal_sha256'], sha256_hex(call)):
        raise SupervisedUiContractError('approval proposal digest mismatch')
    operation = proposal.get('op')
    if operation not in _READ_OPERATIONS | _ACTION_OPERATIONS:
        raise SupervisedUiContractError('proposal operation is not allowed')
    if approval_map['operation'] != operation:
        raise SupervisedUiContractError('approval operation mismatch')
    if operation in _READ_OPERATIONS:
        _require_exact_keys(proposal, required=frozenset({'op'}), context='proposal')
        if any(approval_map[key] is not None for key in ('ref', 'revision', 'observation_id')):
            raise SupervisedUiContractError('read approval must not bind a prior UI target')
        if approval_map['effect_class'] != 'read_only':
            raise SupervisedUiContractError('read approval effect must be read_only')
        return proposal
    _require_exact_keys(
        proposal,
        required=frozenset({'op', 'ref', 'revision'}),
        context='proposal',
    )
    if projection is None:
        raise SupervisedUiContractError('action proposal requires a current projection')
    ref = proposal['ref']
    revision = proposal['revision']
    if not isinstance(ref, str) or not _REF_RE.fullmatch(ref):
        raise SupervisedUiContractError('proposal ref is invalid')
    if not isinstance(revision, str) or not revision.startswith('v1_'):
        raise SupervisedUiContractError('proposal revision is invalid')
    if approval_map['ref'] != ref or approval_map['revision'] != revision:
        raise SupervisedUiContractError('approval target mismatch')
    element = next(
        (item for item in projection.public['elements'] if item['ref'] == ref),
        None,
    )
    if element is None or operation not in element['operations']:
        raise SupervisedUiContractError('proposal is outside the live projection')
    if approval_map['effect_class'] != element['effect_class']:
        raise SupervisedUiContractError('approval effect mismatch')
    if observation_id is None:
        raise SupervisedUiContractError('action approval must bind its observation')
    return proposal
