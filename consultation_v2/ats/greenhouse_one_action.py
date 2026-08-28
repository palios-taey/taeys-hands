from __future__ import annotations

from dataclasses import dataclass
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any, Callable, Iterable, Mapping
import uuid

import yaml

from consultation_v2 import atspi, input as inp
from consultation_v2.interact import atspi_click, atspi_focus, atspi_mapped_pointer_activate
from consultation_v2.native_dialog_snapshot import (
    NativeDialogElementRef,
    NativeDialogObservationError,
    NativeDialogSnapshot,
    build_native_dialog_snapshot_from_contract,
    normalize_native_dialog_contract,
)
from consultation_v2.runtime import ConsultationRuntime
from consultation_v2.snapshot import _direct_child_elements
from consultation_v2.supervised_ui_contract import canonical_json_bytes
from consultation_v2.supervised_ui_receipts import HandsReceiptStore
from consultation_v2.tree import find_elements
from consultation_v2.types import ElementRef

from .provider_contract import ProviderSpec, load_provider_spec
from .read_only import (
    Rect,
    _document_rect,
    _element_rect,
    _invalidate_and_reacquire,
    _live_states,
)
from .route_contract import RouteContractError, RouteMatch, match_provider_route


ACTION_SCHEMA = 'ats_greenhouse_frozen_action_v1'
RESULT_SCHEMA = 'ats_greenhouse_one_action_result_v1'
SURFACE_SCHEMA = 'ats_greenhouse_action_surface_v1'
SPEC_SCHEMA = 'ats_greenhouse_one_action_v1'
SPEC_PATH = Path(__file__).resolve().parent / 'providers' / 'greenhouse_one_action.yaml'
PUBLIC_REPO_ROOT = Path(__file__).resolve().parents[2]

_SHA256 = frozenset('0123456789abcdef')
_UUID_FIELDS = ('transaction_id', 'action_id')
_MAX_FROZEN_ACTION_BYTES = 4 * 1024 * 1024
_INTERACTIVE_STATES = frozenset({'showing', 'visible', 'enabled'})
_TIMEOUT_COUNTRY_RAW_MAX_DEPTH = 8
_TIMEOUT_COUNTRY_RAW_MAX_ELEMENTS = 128
_TIMEOUT_COUNTRY_TEXT_MAX_CHARS = 512
_COUNTRY_CALLING_CODE_SUFFIX = re.compile(
    r'(?P<semantic_token>\S(?:.*\S)?) \+[0-9]{1,3}',
    flags=re.ASCII,
)
_STOP_CODES = frozenset({
    'exact_postcondition_failure',
    'missing_truthful_applicant_data',
    'policy_or_authority_boundary',
    'side_effect_uncertainty',
    'unmapped_ui_or_question',
})
_TERMINAL_EVENTS = frozenset({'ats_terminal', 'ats_submitted', 'indeterminate'})
_ACTION_KEYS = {
    'observe_form': frozenset({'kind'}),
    'focus': frozenset({'kind', 'ref', 'revision'}),
    'fill': frozenset({'kind', 'ref', 'revision', 'value', 'value_sha256'}),
    'scroll_combo': frozenset({'kind', 'ref', 'revision'}),
    'open_combo': frozenset({'kind', 'ref', 'revision'}),
    'select_option': frozenset({
        'kind',
        'ref',
        'revision',
        'combo_ref',
        'expected_option_name',
    }),
    'activate_choice': frozenset({'kind', 'ref', 'revision', 'expected_state'}),
    'open_upload': frozenset({'kind', 'ref', 'revision', 'slot'}),
    'chooser_location': frozenset({'kind', 'ref', 'revision'}),
    'chooser_select_all': frozenset({'kind', 'ref', 'revision'}),
    'chooser_type_path': frozenset({
        'kind',
        'ref',
        'revision',
        'artifact',
    }),
    'chooser_confirm': frozenset({
        'kind',
        'ref',
        'revision',
        'artifact',
    }),
    'submit': frozenset({'kind', 'ref', 'revision', 'precondition'}),
}
MUTATION_PRIMITIVE_BY_ACTION = {
    'observe_form': (),
    'focus': ('atspi_focus',),
    'fill': ('input.type_text',),
    'scroll_combo': ('ConsultationRuntime.scroll_element_into_view',),
    'open_combo': ('atspi_mapped_pointer_activate',),
    'select_option': ('atspi_click',),
    'activate_choice': ('atspi_click',),
    'open_upload': ('atspi_click',),
    'chooser_location': ('input.press_key_cleared',),
    'chooser_select_all': ('input.press_key_cleared',),
    'chooser_type_path': ('input.type_text',),
    'chooser_confirm': ('atspi_click',),
    'submit': ('atspi_click',),
}


class GreenhouseOneActionError(RuntimeError):
    def __init__(
        self,
        reason: str,
        *,
        code: str = 'exact_postcondition_failure',
        mutation_started: bool = False,
        barrier_evidence: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(reason)
        if code not in _STOP_CODES:
            raise ValueError(f'invalid Greenhouse stop code {code!r}')
        self.reason = reason
        self.code = code
        self.mutation_started = mutation_started
        self.barrier_evidence = (
            None if barrier_evidence is None else dict(barrier_evidence)
        )


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise GreenhouseOneActionError(f'duplicate one-action spec key {key!r}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True, slots=True)
class ActionSpec:
    document: Mapping[str, Any]
    sha256: str


@dataclass(frozen=True, slots=True)
class BoundSurface:
    public: Mapping[str, Any]
    bindings: Mapping[str, Mapping[str, Any]]
    firefox: Any
    document: Any
    route: RouteMatch


@dataclass(frozen=True, slots=True)
class BarrierResult:
    surface: Any
    samples: tuple[Mapping[str, Any], ...]


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise GreenhouseOneActionError(f'{context} must be a string-keyed mapping')
    return dict(value)


def _exact_keys(value: Mapping[str, Any], expected: Iterable[str], context: str) -> None:
    required = frozenset(expected)
    actual = frozenset(value)
    if actual != required:
        raise GreenhouseOneActionError(
            f'{context} keys mismatch: missing={sorted(required - actual)}, '
            f'unknown={sorted(actual - required)}'
        )


def _string_list(value: Any, context: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise GreenhouseOneActionError(f'{context} must be a non-empty unique string list')
    return list(value)


def _sha256_text(value: Any, context: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _SHA256 for character in value)
    ):
        raise GreenhouseOneActionError(f'{context} must be one lowercase SHA-256')
    return value


def _uuid_text(value: Any, context: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise GreenhouseOneActionError(f'{context} must be a lowercase UUID') from exc
    normalized = str(parsed)
    if value != normalized:
        raise GreenhouseOneActionError(f'{context} must be a lowercase UUID')
    return normalized


def _validate_barrier(value: Any, context: str, refresh_policy: str) -> dict[str, Any]:
    barrier = _mapping(value, context)
    _exact_keys(
        barrier,
        {'refresh_policy', 'stable_cycles', 'interval_ms', 'timeout_ms'},
        context,
    )
    if barrier['refresh_policy'] != refresh_policy:
        raise GreenhouseOneActionError(f'{context}.refresh_policy is invalid')
    for key in ('stable_cycles', 'interval_ms', 'timeout_ms'):
        raw = barrier[key]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise GreenhouseOneActionError(f'{context}.{key} must be a positive integer')
    if barrier['stable_cycles'] < 2:
        raise GreenhouseOneActionError(f'{context}.stable_cycles must be at least two')
    return barrier


def _validate_native_dialog(value: Any) -> dict[str, Any]:
    try:
        native = normalize_native_dialog_contract(value, authority='greenhouse')
    except Exception as exc:
        raise GreenhouseOneActionError('native_dialog contract is invalid') from exc
    if native['root'] != 'dialog_root' or native['max_depth'] != 32:
        raise GreenhouseOneActionError('native_dialog identity is invalid')
    elements = native['elements']
    _exact_keys(
        elements,
        {
            'dialog_root',
            'chooser_widget',
            'location_layer',
            'location_entry',
            'cancel_button',
            'open_button',
        },
        'native_dialog.elements',
    )
    return native


def load_action_spec() -> ActionSpec:
    if not SPEC_PATH.is_file() or SPEC_PATH.is_symlink():
        raise GreenhouseOneActionError('Greenhouse one-action spec is missing or unsafe')
    raw = SPEC_PATH.read_bytes()
    try:
        document = yaml.load(raw.decode('utf-8'), Loader=_UniqueKeyLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise GreenhouseOneActionError('Greenhouse one-action spec is not strict UTF-8 YAML') from exc
    document = _mapping(document, 'greenhouse_one_action')
    _exact_keys(
        document,
        {
            'schema',
            'provider',
            'execution',
            'surface',
            'options_surface',
            'barriers',
            'attachment_proof',
            'confirmation',
            'native_dialog',
        },
        'greenhouse_one_action',
    )
    if document['schema'] != SPEC_SCHEMA or document['provider'] != 'greenhouse':
        raise GreenhouseOneActionError('Greenhouse one-action spec identity is invalid')
    execution = _mapping(document['execution'], 'execution')
    _exact_keys(
        execution,
        {
            'lifecycle',
            'maximum_ui_mutations_per_call',
            'dropdown_options',
            'first_mismatch',
            'stop_codes',
        },
        'execution',
    )
    if execution != {
        'lifecycle': 'autonomous_to_employer_confirmation',
        'maximum_ui_mutations_per_call': 1,
        'dropdown_options': 'fresh_observation_required',
        'first_mismatch': 'terminal',
        'stop_codes': [
            'exact_postcondition_failure',
            'unmapped_ui_or_question',
            'missing_truthful_applicant_data',
            'policy_or_authority_boundary',
            'side_effect_uncertainty',
        ],
    }:
        raise GreenhouseOneActionError('Greenhouse autonomous execution contract is invalid')
    surface = _mapping(document['surface'], 'surface')
    _exact_keys(
        surface,
        {'actionable_roles', 'text_roles', 'choice_roles', 'upload_slots', 'submit'},
        'surface',
    )
    for key in ('actionable_roles', 'text_roles', 'choice_roles'):
        _string_list(surface[key], f'surface.{key}')
    slots = _mapping(surface['upload_slots'], 'surface.upload_slots')
    _exact_keys(slots, {'resume', 'cover'}, 'surface.upload_slots')
    for slot, raw_slot in slots.items():
        slot_spec = _mapping(raw_slot, f'surface.upload_slots.{slot}')
        _exact_keys(
            slot_spec,
            {'ancestor_names_any_of', 'control_names_any_of'},
            f'surface.upload_slots.{slot}',
        )
        _string_list(
            slot_spec['ancestor_names_any_of'],
            f'surface.upload_slots.{slot}.ancestor_names_any_of',
        )
        _string_list(
            slot_spec['control_names_any_of'],
            f'surface.upload_slots.{slot}.control_names_any_of',
        )
    submit = _mapping(surface['submit'], 'surface.submit')
    _exact_keys(submit, {'names_any_of', 'role'}, 'surface.submit')
    _string_list(submit['names_any_of'], 'surface.submit.names_any_of')
    if submit['role'] != 'push button':
        raise GreenhouseOneActionError('surface.submit.role must be push button')
    options_surface = _mapping(document['options_surface'], 'options_surface')
    _exact_keys(
        options_surface,
        {
            'observation_root',
            'max_depth',
            'prune_subtree_roles',
            'origin',
            'semantic_projection',
            'container',
            'option',
        },
        'options_surface',
    )
    if options_surface['observation_root'] != 'firefox_application':
        raise GreenhouseOneActionError(
            'options_surface.observation_root must be firefox_application'
        )
    if (
        isinstance(options_surface['max_depth'], bool)
        or not isinstance(options_surface['max_depth'], int)
        or options_surface['max_depth'] < 1
    ):
        raise GreenhouseOneActionError('options_surface.max_depth must be a positive integer')
    _string_list(
        options_surface['prune_subtree_roles'],
        'options_surface.prune_subtree_roles',
    )
    origin = _mapping(options_surface['origin'], 'options_surface.origin')
    _exact_keys(origin, {'role', 'states_all'}, 'options_surface.origin')
    if origin['role'] != 'combo box' or _string_list(
        origin['states_all'],
        'options_surface.origin.states_all',
    ) != ['expanded']:
        raise GreenhouseOneActionError('options_surface.origin contract is invalid')
    semantic_projection = _mapping(
        options_surface['semantic_projection'],
        'options_surface.semantic_projection',
    )
    _exact_keys(
        semantic_projection,
        {'origin', 'kind'},
        'options_surface.semantic_projection',
    )
    semantic_origin = _mapping(
        semantic_projection['origin'],
        'options_surface.semantic_projection.origin',
    )
    _exact_keys(
        semantic_origin,
        {'name', 'role'},
        'options_surface.semantic_projection.origin',
    )
    if semantic_origin != {'name': 'Country', 'role': 'combo box'}:
        raise GreenhouseOneActionError(
            'options_surface semantic projection origin is invalid'
        )
    if semantic_projection['kind'] != 'country_calling_code_suffix_v1':
        raise GreenhouseOneActionError(
            'options_surface semantic projection kind is invalid'
        )
    for key in ('container', 'option'):
        option_part = _mapping(options_surface[key], f'options_surface.{key}')
        _exact_keys(
            option_part,
            {'roles_any_of', 'states_all'},
            f'options_surface.{key}',
        )
        _string_list(
            option_part['roles_any_of'],
            f'options_surface.{key}.roles_any_of',
        )
        _string_list(
            option_part['states_all'],
            f'options_surface.{key}.states_all',
        )
    barriers = _mapping(document['barriers'], 'barriers')
    _exact_keys(barriers, {'form', 'options', 'native_dialog', 'confirmation'}, 'barriers')
    _validate_barrier(barriers['form'], 'barriers.form', 'invalidate_reacquire')
    _validate_barrier(
        barriers['options'],
        'barriers.options',
        'live_reacquire_no_clear',
    )
    _validate_barrier(
        barriers['native_dialog'],
        'barriers.native_dialog',
        'native_invalidate_reacquire',
    )
    _validate_barrier(
        barriers['confirmation'],
        'barriers.confirmation',
        'invalidate_reacquire',
    )
    proof = _mapping(document['attachment_proof'], 'attachment_proof')
    _exact_keys(proof, {'rendered_name_templates'}, 'attachment_proof')
    templates = _string_list(
        proof['rendered_name_templates'],
        'attachment_proof.rendered_name_templates',
    )
    if any(template.count('{filename}') != 1 for template in templates):
        raise GreenhouseOneActionError('attachment proof templates must contain {filename} once')
    confirmation = _mapping(document['confirmation'], 'confirmation')
    _exact_keys(confirmation, {'route_grammar', 'anchors_any'}, 'confirmation')
    if confirmation['route_grammar'] != 'hosted_confirmation':
        raise GreenhouseOneActionError('confirmation.route_grammar is invalid')
    if not isinstance(confirmation['anchors_any'], list) or not confirmation['anchors_any']:
        raise GreenhouseOneActionError('confirmation.anchors_any must be non-empty')
    for index, raw_anchor in enumerate(confirmation['anchors_any']):
        anchor = _mapping(raw_anchor, f'confirmation.anchors_any[{index}]')
        _exact_keys(anchor, {'name', 'roles_any_of'}, f'confirmation.anchors_any[{index}]')
        if not isinstance(anchor['name'], str) or not anchor['name']:
            raise GreenhouseOneActionError('confirmation anchor name is invalid')
        _string_list(anchor['roles_any_of'], 'confirmation anchor roles_any_of')
    document['native_dialog'] = _validate_native_dialog(document['native_dialog'])
    return ActionSpec(document=document, sha256=hashlib.sha256(raw).hexdigest())


def _secure_private_json_fd(fd_value: int, expected_sha256: str) -> dict[str, Any]:
    if isinstance(fd_value, bool) or not isinstance(fd_value, int) or fd_value < 3:
        raise GreenhouseOneActionError(
            'frozen action descriptor is invalid',
            code='policy_or_authority_boundary',
        )
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in _SHA256 for character in expected_sha256)
    ):
        raise GreenhouseOneActionError(
            'expected frozen action SHA-256 is invalid',
            code='policy_or_authority_boundary',
        )
    try:
        descriptor_flags = fcntl.fcntl(fd_value, fcntl.F_GETFL)
        before = os.fstat(fd_value)
    except OSError as exc:
        raise GreenhouseOneActionError(
            'frozen action descriptor is unavailable',
            code='policy_or_authority_boundary',
        ) from exc
    if descriptor_flags & os.O_ACCMODE != os.O_RDONLY:
        raise GreenhouseOneActionError(
            'frozen action descriptor must be read-only',
            code='policy_or_authority_boundary',
        )
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) != 0o400
        or not 0 < before.st_size <= _MAX_FROZEN_ACTION_BYTES
    ):
        raise GreenhouseOneActionError(
            'frozen action descriptor is not an exact owner-only regular file',
            code='policy_or_authority_boundary',
        )
    signature = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_gid,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    chunks: list[bytes] = []
    offset = 0
    try:
        while offset < before.st_size:
            chunk = os.pread(
                fd_value,
                min(1024 * 1024, before.st_size - offset),
                offset,
            )
            if not chunk:
                raise OSError('short read')
            chunks.append(chunk)
            offset += len(chunk)
        if os.pread(fd_value, 1, before.st_size):
            raise OSError('frozen action grew while read')
        after = os.fstat(fd_value)
    except OSError as exc:
        raise GreenhouseOneActionError(
            'frozen action descriptor changed while read',
            code='policy_or_authority_boundary',
        ) from exc
    after_signature = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    raw = b''.join(chunks)
    if signature != after_signature or len(raw) != before.st_size:
        raise GreenhouseOneActionError(
            'frozen action descriptor changed while read',
            code='policy_or_authority_boundary',
        )
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
        raise GreenhouseOneActionError(
            'frozen action descriptor digest mismatch',
            code='policy_or_authority_boundary',
        )

    def exact_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        if len(pairs) != len({key for key, _value in pairs}):
            raise ValueError('duplicate frozen action key')
        return dict(pairs)

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=exact_object)
    except (UnicodeDecodeError, ValueError) as exc:
        raise GreenhouseOneActionError('frozen action is not exact UTF-8 JSON') from exc
    return _mapping(value, 'frozen_action')


def load_frozen_action_fd(fd_value: int, expected_sha256: str) -> dict[str, Any]:
    request = _secure_private_json_fd(fd_value, expected_sha256)
    _exact_keys(
        request,
        {
            'schema',
            'provider',
            'transaction_id',
            'action_id',
            'application_identity_sha256',
            'expected_prior_event_hash',
            'action',
        },
        'frozen_action',
    )
    if request['schema'] != ACTION_SCHEMA or request['provider'] != 'greenhouse':
        raise GreenhouseOneActionError('frozen action identity is invalid')
    for field in _UUID_FIELDS:
        _uuid_text(request[field], f'frozen_action.{field}')
    _sha256_text(
        request['application_identity_sha256'],
        'frozen_action.application_identity_sha256',
    )
    prior = request['expected_prior_event_hash']
    if prior is not None:
        _sha256_text(prior, 'frozen_action.expected_prior_event_hash')
    action = _mapping(request['action'], 'frozen_action.action')
    kind = action.get('kind')
    if kind not in _ACTION_KEYS:
        raise GreenhouseOneActionError(f'unsupported Greenhouse one-action kind {kind!r}')
    _exact_keys(action, _ACTION_KEYS[kind], f'frozen_action.action.{kind}')
    for key in ('ref', 'revision', 'combo_ref', 'expected_option_name', 'slot', 'value'):
        if key in action and (not isinstance(action[key], str) or not action[key]):
            raise GreenhouseOneActionError(f'frozen_action.action.{key} must be non-empty')
    if 'value_sha256' in action:
        expected = _sha256_text(action['value_sha256'], 'frozen_action.action.value_sha256')
        actual = hashlib.sha256(action['value'].encode('utf-8')).hexdigest()
        if not hmac.compare_digest(expected, actual):
            raise GreenhouseOneActionError('frozen action value digest mismatch')
    if kind == 'activate_choice' and action['expected_state'] not in {'checked', 'selected'}:
        raise GreenhouseOneActionError('activate_choice.expected_state is invalid')
    if kind in {'chooser_type_path', 'chooser_confirm'}:
        _validate_artifact(action['artifact'])
    if kind == 'submit':
        _validate_submit_precondition(action['precondition'])
    return request


def _validate_artifact(value: Any) -> dict[str, Any]:
    artifact = _mapping(value, 'artifact')
    _exact_keys(artifact, {'slot', 'name', 'path', 'sha256'}, 'artifact')
    if artifact['slot'] not in {'resume', 'cover'}:
        raise GreenhouseOneActionError('artifact.slot is invalid')
    for key in ('name', 'path'):
        if not isinstance(artifact[key], str) or not artifact[key]:
            raise GreenhouseOneActionError(f'artifact.{key} must be non-empty')
    _sha256_text(artifact['sha256'], 'artifact.sha256')
    path = Path(artifact['path'])
    if not path.is_absolute() or path.name != artifact['name']:
        raise GreenhouseOneActionError(
            'artifact path/name binding is invalid',
            code='missing_truthful_applicant_data',
        )
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise GreenhouseOneActionError(
            'artifact path is unavailable',
            code='missing_truthful_applicant_data',
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise GreenhouseOneActionError(
            'artifact must be a real regular file',
            code='missing_truthful_applicant_data',
        )
    if metadata.st_uid != os.getuid():
        raise GreenhouseOneActionError('artifact must be worker-owned')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hmac.compare_digest(digest, artifact['sha256']):
        raise GreenhouseOneActionError(
            'artifact content digest mismatch',
            code='missing_truthful_applicant_data',
        )
    return artifact


def _validate_submit_precondition(value: Any) -> dict[str, Any]:
    precondition = _mapping(value, 'submit.precondition')
    _exact_keys(
        precondition,
        {
            'required_controls_complete',
            'truth_attested',
            'complete_form_sha256',
            'truth_attestation_sha256',
            'artifacts',
        },
        'submit.precondition',
    )
    if precondition['required_controls_complete'] is not True:
        raise GreenhouseOneActionError(
            'submit precondition does not attest complete required controls',
            code='missing_truthful_applicant_data',
        )
    if precondition['truth_attested'] is not True:
        raise GreenhouseOneActionError(
            'submit precondition does not attest truthful answers',
            code='missing_truthful_applicant_data',
        )
    _sha256_text(precondition['complete_form_sha256'], 'submit.complete_form_sha256')
    _sha256_text(precondition['truth_attestation_sha256'], 'submit.truth_attestation_sha256')
    artifacts = precondition['artifacts']
    if not isinstance(artifacts, list) or not artifacts:
        raise GreenhouseOneActionError(
            'submit precondition must bind at least one artifact',
            code='missing_truthful_applicant_data',
        )
    slots: set[str] = set()
    for artifact in artifacts:
        validated = _validate_artifact(artifact)
        if validated['slot'] in slots:
            raise GreenhouseOneActionError('submit precondition has a duplicate artifact slot')
        slots.add(validated['slot'])
    if 'resume' not in slots:
        raise GreenhouseOneActionError(
            'submit precondition must bind one resume artifact',
            code='missing_truthful_applicant_data',
        )
    return precondition


def _lease_secret() -> bytes:
    raw = str(os.environ.get('ATS_ONE_ACTION_LEASE_SECRET') or '').strip()
    if len(raw) != 64 or any(character not in _SHA256 for character in raw):
        raise GreenhouseOneActionError(
            'ATS_ONE_ACTION_LEASE_SECRET must be exactly 64 lowercase hex characters'
        )
    return bytes.fromhex(raw)


def _firefox_pid() -> int:
    raw = str(os.environ.get('ATS_FIREFOX_PID') or '').strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise GreenhouseOneActionError('ATS_FIREFOX_PID must be a positive integer')
    return int(raw)


def _display() -> str:
    display = str(os.environ.get('DISPLAY') or '').strip()
    bus = str(os.environ.get('AT_SPI_BUS_ADDRESS') or '').strip()
    if not display or not bus:
        raise GreenhouseOneActionError('DISPLAY and AT_SPI_BUS_ADDRESS must be explicitly bound')
    inp.set_display(display)
    return display


def _receipt_store(request: Mapping[str, Any]) -> HandsReceiptStore:
    root = str(os.environ.get('ATS_ONE_ACTION_RECEIPT_ROOT') or '').strip()
    hands_commit = str(os.environ.get('ATS_HANDS_COMMIT') or '').strip()
    presence_id = _uuid_text(
        str(os.environ.get('ATS_PRESENCE_INCARNATION_ID') or '').strip(),
        'ATS_PRESENCE_INCARNATION_ID',
    )
    hands_id = _uuid_text(
        str(os.environ.get('ATS_HANDS_INCARNATION_ID') or '').strip(),
        'ATS_HANDS_INCARNATION_ID',
    )
    if not root:
        raise GreenhouseOneActionError('ATS_ONE_ACTION_RECEIPT_ROOT is required')
    return HandsReceiptStore.open_external(
        root,
        [str(PUBLIC_REPO_ROOT)],
        session_id=request['transaction_id'],
        presence_incarnation_id=presence_id,
        hands_incarnation_id=hands_id,
        hands_commit=hands_commit,
    )


def _write_event(
    store: HandsReceiptStore,
    request: Mapping[str, Any],
    kind: str,
    payload: Mapping[str, Any],
    *,
    observation_id: str | None = None,
) -> Mapping[str, Any]:
    return store.write_once(
        {
            'approval_id': None,
            'event_id': str(uuid.uuid4()),
            'execution_id': request['action_id'],
            'kind': kind,
            'observation_id': observation_id,
            'proposal_id': None,
            'turn_id': request['action_id'],
        },
        canonical_json_bytes(payload),
    )


def _assert_receipt_frontier(store: HandsReceiptStore, request: Mapping[str, Any]) -> None:
    events = store.events
    if any(event['kind'] in _TERMINAL_EVENTS for event in events):
        raise GreenhouseOneActionError(
            'Greenhouse transaction is already terminal',
            code='policy_or_authority_boundary',
        )
    if events and events[-1]['kind'] == 'execution_started':
        raise GreenhouseOneActionError(
            'Greenhouse transaction has an incomplete prior action; side effect is uncertain',
            code='side_effect_uncertainty',
        )
    if store.has_execution(request['action_id']):
        raise GreenhouseOneActionError('Greenhouse action identity was already used')
    observed = events[-1]['event_hash'] if events else None
    if observed != request['expected_prior_event_hash']:
        raise GreenhouseOneActionError('Greenhouse action prior receipt hash is stale')


def _opaque_ref(
    secret: bytes,
    application_identity: str,
    surface: str,
    name: str,
    role: str,
    ordinal: int,
) -> str:
    identity = canonical_json_bytes({
        'application_identity_sha256': application_identity,
        'surface': surface,
        'name': name,
        'role': role,
        'ordinal': ordinal,
    })
    digest = hmac.new(secret, b'ats-one-action-ref-v1\x00' + identity, hashlib.sha256)
    return f'r_{digest.hexdigest()[:32]}'


def _revision(secret: bytes, public: Mapping[str, Any]) -> str:
    return hmac.new(
        secret,
        b'ats-one-action-revision-v1\x00' + canonical_json_bytes(public),
        hashlib.sha256,
    ).hexdigest()


def _ancestor_names(element: Mapping[str, Any], limit: int = 24) -> tuple[str, ...]:
    obj = element.get('atspi_obj')
    names: list[str] = []
    for _ in range(limit):
        if obj is None:
            break
        try:
            obj = obj.get_parent()
            if obj is None:
                break
            name = str(obj.get_name() or '')
        except Exception as exc:
            raise GreenhouseOneActionError('ATS control ancestry is unavailable') from exc
        if name:
            names.append(name)
    return tuple(names)


def _ancestor_objects(element: Mapping[str, Any], limit: int = 64) -> tuple[Any, ...]:
    obj = element.get('atspi_obj')
    if obj is None:
        raise GreenhouseOneActionError('ATS option has no structural object')
    ancestors: list[Any] = []
    for _ in range(limit):
        try:
            obj = obj.get_parent()
        except Exception as exc:
            raise GreenhouseOneActionError('ATS option ancestry is unavailable') from exc
        if obj is None:
            return tuple(ancestors)
        ancestors.append(obj)
    raise GreenhouseOneActionError('ATS option ancestry exceeded the exact depth bound')


def _upload_slot(element: Mapping[str, Any], action_spec: ActionSpec) -> str | None:
    name = str(element.get('name') or '')
    ancestors = set(_ancestor_names(element))
    matches: list[str] = []
    for slot, raw in action_spec.document['surface']['upload_slots'].items():
        if name not in set(raw['control_names_any_of']):
            continue
        if ancestors.intersection(raw['ancestor_names_any_of']) or name in set(
            raw['ancestor_names_any_of']
        ):
            matches.append(slot)
    if len(matches) > 1:
        raise GreenhouseOneActionError('ATS upload control maps to multiple artifact slots')
    return matches[0] if matches else None


def _control_text(element: Mapping[str, Any]) -> str:
    obj = element.get('atspi_obj')
    if obj is None:
        return ''
    try:
        text_iface = obj.get_text_iface()
        if text_iface is not None:
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi

            count = int(Atspi.Text.get_character_count(text_iface))
            if count >= 0:
                return str(Atspi.Text.get_text(text_iface, 0, count) or '')
    except Exception as exc:
        raise GreenhouseOneActionError('ATS control text is unreadable') from exc
    return ''


def _control_semantic_values(element: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    text = _control_text(element)
    if text:
        values.append(text)
    obj = element.get('atspi_obj')
    if obj is not None:
        try:
            selection = obj.get_selection_iface()
            count = int(selection.get_n_selected_children()) if selection is not None else 0
            for index in range(count):
                selected = selection.get_selected_child(index)
                name = str(selected.get_name() or '') if selected is not None else ''
                if name:
                    values.append(name)
        except Exception as exc:
            raise GreenhouseOneActionError('ATS selection state is unreadable') from exc
    return tuple(dict.fromkeys(values))


def _required_elements_complete(elements: Iterable[Mapping[str, Any]]) -> bool:
    required = [
        element
        for element in elements
        if 'required' in _live_states(element)
    ]
    if not required:
        return False
    for element in required:
        role = str(element.get('role') or '').strip().lower()
        states = _live_states(element)
        if role in {'entry', 'password text'} and not _control_text(element):
            return False
        if role == 'combo box' and not _control_semantic_values(element):
            return False
        if role in {'check box', 'radio button', 'toggle button'} and not (
            {'checked', 'selected'} & states
        ):
            return False
    return True


def _combo_safety(element: Mapping[str, Any], document_rect: Rect) -> dict[str, Any]:
    rect = _element_rect(element)
    if rect is None or not rect.valid:
        return {
            'geometry': 'refused',
            'refusal': 'combo_rect_invalid',
            'scroll_frontier': True,
        }
    if not document_rect.contains(rect):
        return {
            'geometry': 'refused',
            'refusal': 'combo_rect_outside_document_rect',
            'scroll_frontier': True,
        }
    return {
        'geometry': 'contained_by_active_document',
        'refusal': None,
        'scroll_frontier': False,
    }


def _complete_form_sha256(
    application_identity_sha256: str,
    controls: Iterable[Mapping[str, Any]],
) -> str:
    projection: list[dict[str, Any]] = []
    for control in controls:
        states = set(control.get('states') or [])
        item: dict[str, Any] = {
            'ref': control['ref'],
            'role': control['role'],
            'active_states': sorted(states.intersection({'checked', 'selected'})),
        }
        for key in ('value_length', 'value_sha256', 'semantic_values', 'artifact_slot'):
            if key in control:
                item[key] = control[key]
        projection.append(item)
    return hashlib.sha256(canonical_json_bytes({
        'schema': 'ats_greenhouse_complete_form_v1',
        'application_identity_sha256': application_identity_sha256,
        'controls': projection,
    })).hexdigest()


def project_form_surface(
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
    route: RouteMatch,
    elements: Iterable[Mapping[str, Any]],
    document_rect: Rect,
    secret: bytes,
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    surface = action_spec.document['surface']
    actionable_roles = set(surface['actionable_roles'])
    text_roles = set(surface['text_roles'])
    choice_roles = set(surface['choice_roles'])
    submit = surface['submit']
    candidates = [
        dict(element)
        for element in elements
        if str(element.get('role') or '').strip().lower() in actionable_roles
    ]
    candidates.sort(key=lambda item: (
        int(item.get('y') or 0),
        int(item.get('x') or 0),
        str(item.get('role') or ''),
        str(item.get('name') or ''),
    ))
    public_controls: list[dict[str, Any]] = []
    bindings: dict[str, Mapping[str, Any]] = {}
    for ordinal, element in enumerate(candidates):
        name = str(element.get('name') or '')
        role = str(element.get('role') or '').strip().lower()
        states = sorted(_live_states(element))
        interactive = _INTERACTIVE_STATES.issubset(states)
        ref = _opaque_ref(
            secret,
            route.application_identity_sha256,
            'form',
            name,
            role,
            ordinal,
        )
        operations: list[str] = []
        item: dict[str, Any] = {
            'ref': ref,
            'name': name,
            'role': role,
            'states': states,
            'operations': operations,
        }
        if role in text_roles and interactive and 'editable' in states:
            operations.append('focus')
            text = _control_text(element)
            item['value_length'] = len(text)
            item['value_sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
            if 'focused' in states and not text:
                operations.append('fill')
        elif role == 'combo box':
            safety = _combo_safety(element, document_rect)
            item['combo_safety'] = safety
            item['semantic_values'] = list(_control_semantic_values(element))
            if 'enabled' in states and 'expanded' not in states:
                operations.append(
                    'open_combo'
                    if interactive and safety['geometry'] == 'contained_by_active_document'
                    else 'scroll_combo'
                )
        elif (
            role in choice_roles
            and interactive
            and not {'checked', 'selected'}.intersection(states)
        ):
            operations.append('activate_choice')
        slot = _upload_slot(element, action_spec)
        if slot is not None:
            operations[:] = ['open_upload'] if interactive else []
            item['artifact_slot'] = slot
        if role == submit['role'] and name in set(submit['names_any_of']):
            operations[:] = ['submit'] if interactive else []
            item['boundary'] = 'submit'
        bindings[ref] = element
        public_controls.append(item)
    public = {
        'schema': SURFACE_SCHEMA,
        'surface': 'form',
        'provider': 'greenhouse',
        'provider_sha256': provider_spec.sha256,
        'action_spec_sha256': action_spec.sha256,
        'application_identity_sha256': route.application_identity_sha256,
        'route_grammar': route.grammar_id,
        'controls': public_controls,
        'required_controls_complete': _required_elements_complete(bindings.values()),
    }
    public['complete_form_sha256'] = _complete_form_sha256(
        route.application_identity_sha256,
        public_controls,
    )
    public['revision'] = _revision(secret, public)
    return public, bindings


def _capture_form(
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
    secret: bytes,
) -> BoundSurface:
    firefox, document, url, _refresh = _invalidate_and_reacquire(provider_spec)
    route = match_provider_route(provider_spec, url)
    elements = find_elements(
        document,
        max_depth=provider_spec.document['form_projection']['max_depth'],
    )
    public, bindings = project_form_surface(
        provider_spec,
        action_spec,
        route,
        elements,
        _document_rect(document),
        secret,
    )
    return BoundSurface(public, bindings, firefox, document, route)


def _option_semantic_token(rendered_name: str, contract_kind: str) -> str:
    if contract_kind != 'country_calling_code_suffix_v1':
        raise GreenhouseOneActionError('country option semantic contract kind is invalid')
    match = _COUNTRY_CALLING_CODE_SUFFIX.fullmatch(rendered_name)
    if match is None:
        raise GreenhouseOneActionError(
            'country option does not satisfy country_calling_code_suffix_v1'
        )
    semantic_token = match.group('semantic_token')
    if not semantic_token:
        raise GreenhouseOneActionError('country option semantic token is empty')
    return semantic_token


def _selected_option_matches(
    surface: Any,
    action: Mapping[str, Any],
) -> bool:
    if not isinstance(surface, BoundSurface):
        return False
    combo = _public_control(surface, action['combo_ref'])
    if combo is None or 'expanded' in (combo.get('states') or []):
        return False
    return action['expected_option_name'] in combo.get('semantic_values', [])


def _capture_options(
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
    secret: bytes,
    origin_combo_ref: str,
) -> BoundSurface:
    matches: list[tuple[Any, Any, str]] = []
    for firefox in atspi.find_all_firefox(pid=_firefox_pid()):
        for document in atspi.document_web_elements(
            firefox,
            max_depth=provider_spec.document['form_projection']['max_depth'],
        ):
            url = atspi.get_document_url(document)
            if not url:
                continue
            try:
                match_provider_route(provider_spec, url)
            except RouteContractError:
                continue
            matches.append((firefox, document, url))
    if len(matches) != 1:
        raise GreenhouseOneActionError(
            f'exact ATS options route matched {len(matches)} active documents'
        )
    firefox, document, url = matches[0]
    route = match_provider_route(provider_spec, url)
    form_public, _form_bindings = project_form_surface(
        provider_spec,
        action_spec,
        route,
        find_elements(
            document,
            max_depth=provider_spec.document['form_projection']['max_depth'],
        ),
        _document_rect(document),
        secret,
    )
    origin_contract = action_spec.document['options_surface']['origin']
    expanded = [
        control
        for control in form_public['controls']
        if control.get('role') == origin_contract['role']
        and set(origin_contract['states_all']) <= set(control.get('states') or [])
    ]
    if len(expanded) != 1 or expanded[0].get('ref') != origin_combo_ref:
        raise GreenhouseOneActionError(
            'exact options surface is not owned by the activated combo'
        )
    options_contract = action_spec.document['options_surface']
    elements = find_elements(
        firefox,
        max_depth=options_contract['max_depth'],
        prune_subtree_roles=options_contract['prune_subtree_roles'],
    )
    container_contract = options_contract['container']
    container_roles = set(container_contract['roles_any_of'])
    container_states = set(container_contract['states_all'])
    containers = [
        dict(element)
        for element in elements
        if str(element.get('role') or '').strip().lower() in container_roles
        and container_states <= _live_states(element)
        and element.get('atspi_obj') is not None
    ]
    option_contract = options_contract['option']
    option_roles = set(option_contract['roles_any_of'])
    option_states = set(option_contract['states_all'])
    candidates_by_container: list[tuple[Mapping[str, Any], list[dict[str, Any]]]] = []
    for container in containers:
        container_obj = container['atspi_obj']
        members: list[dict[str, Any]] = []
        for element in elements:
            if (
                str(element.get('role') or '').strip().lower() not in option_roles
                or not str(element.get('name') or '')
                or not option_states <= _live_states(element)
            ):
                continue
            if container_obj in _ancestor_objects(element):
                members.append(dict(element))
        if members:
            candidates_by_container.append((container, members))
    if len(candidates_by_container) != 1:
        raise GreenhouseOneActionError(
            'exact activated combo options container cardinality is '
            f'{len(candidates_by_container)}; expected 1'
        )
    container, candidates = candidates_by_container[0]
    candidates.sort(key=lambda item: (
        int(item.get('y') or 0),
        int(item.get('x') or 0),
        str(item.get('role') or ''),
        str(item.get('name') or ''),
    ))
    option_names = [str(item.get('name') or '') for item in candidates]
    if len(option_names) != len(set(option_names)):
        raise GreenhouseOneActionError('exact activated combo options contain duplicate names')
    semantic_projection = options_contract['semantic_projection']
    semantic_origin = semantic_projection['origin']
    projects_semantic_tokens = (
        expanded[0].get('name') == semantic_origin['name']
        and expanded[0].get('role') == semantic_origin['role']
    )
    bindings: dict[str, Mapping[str, Any]] = {}
    options: list[dict[str, Any]] = []
    semantic_tokens: list[str] = []
    for ordinal, element in enumerate(candidates):
        name = str(element.get('name') or '')
        role = str(element.get('role') or '').strip().lower()
        ref = _opaque_ref(
            secret,
            route.application_identity_sha256,
            f'options:{origin_combo_ref}:{form_public["revision"]}',
            name,
            role,
            ordinal,
        )
        bindings[ref] = element
        option = {
            'ref': ref,
            'name': name,
            'role': role,
            'states': sorted(_live_states(element)),
            'operations': ['select_option'],
        }
        if projects_semantic_tokens:
            semantic_token = _option_semantic_token(
                name,
                semantic_projection['kind'],
            )
            semantic_tokens.append(semantic_token)
            option['semantic_token'] = semantic_token
        options.append(option)
    if projects_semantic_tokens:
        if not semantic_tokens:
            raise GreenhouseOneActionError('country options contain zero semantic tokens')
        if len(semantic_tokens) != len(set(semantic_tokens)):
            raise GreenhouseOneActionError('country options contain duplicate semantic tokens')
    public = {
        'schema': SURFACE_SCHEMA,
        'surface': 'options',
        'provider': 'greenhouse',
        'provider_sha256': provider_spec.sha256,
        'action_spec_sha256': action_spec.sha256,
        'application_identity_sha256': route.application_identity_sha256,
        'route_grammar': route.grammar_id,
        'origin': {
            'combo_ref': origin_combo_ref,
            'name': expanded[0]['name'],
            'role': expanded[0]['role'],
            'states': expanded[0]['states'],
            'form_revision': form_public['revision'],
            'match_count': 1,
        },
        'container': {
            'name': str(container.get('name') or ''),
            'role': str(container.get('role') or '').strip().lower(),
            'states': sorted(_live_states(container)),
            'match_count': 1,
        },
        'controls': options,
    }
    public['revision'] = _revision(secret, public)
    return BoundSurface(public, bindings, firefox, document, route)


def _capture_native_dialog(
    action_spec: ActionSpec,
    application_identity_sha256: str,
) -> NativeDialogSnapshot:
    try:
        firefox_candidates = atspi.find_all_firefox(pid=_firefox_pid())
        if len(firefox_candidates) != 1:
            raise NativeDialogObservationError(
                f'Greenhouse Firefox cardinality is {len(firefox_candidates)}; expected 1'
            )
        return build_native_dialog_snapshot_from_contract(
            platform='greenhouse',
            contract=action_spec.document['native_dialog'],
            firefox=firefox_candidates[0],
            expected_firefox_pid=_firefox_pid(),
            revision_binding_sha256=application_identity_sha256,
        )
    except NativeDialogObservationError:
        raise
    except Exception as exc:
        raise NativeDialogObservationError('greenhouse native dialog observation failed') from exc


def _surface_digest(surface: Any) -> str:
    if isinstance(surface, BoundSurface):
        return str(surface.public['revision'])
    if isinstance(surface, NativeDialogSnapshot):
        return surface.revision
    raise GreenhouseOneActionError('unsupported barrier surface')


def _surface_public(surface: Any) -> Mapping[str, Any]:
    if isinstance(surface, BoundSurface):
        return surface.public
    if isinstance(surface, NativeDialogSnapshot):
        return _native_public(surface)
    raise GreenhouseOneActionError('unsupported barrier surface')


def _timeout_raw_element(element: Mapping[str, Any]) -> dict[str, Any]:
    item = {
        'name': str(element.get('name') or ''),
        'role': str(element.get('role') or ''),
        'states': sorted(_live_states(element)),
    }
    for key in ('description', 'text'):
        value = element.get(key)
        if isinstance(value, str) and value:
            item[key] = value
    obj = element.get('atspi_obj')
    if obj is not None:
        try:
            text = _control_text(element)
        except GreenhouseOneActionError as exc:
            item['control_text'] = {
                'status': 'unreadable',
                'error': exc.reason,
            }
        else:
            if text:
                item['control_text'] = {
                    'status': 'read',
                    'length': len(text),
                    'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                    'value': text[:_TIMEOUT_COUNTRY_TEXT_MAX_CHARS],
                    'truncated': len(text) > _TIMEOUT_COUNTRY_TEXT_MAX_CHARS,
                }
    return item


def _timeout_country_evidence(surface: Any) -> dict[str, Any] | None:
    if not isinstance(surface, BoundSurface) or surface.public.get('surface') != 'form':
        return None
    matches = [
        control
        for control in surface.public.get('controls') or ()
        if control.get('name') == 'Country'
        and control.get('role') == 'combo box'
    ]
    evidence: dict[str, Any] = {
        'canonical_match_count': len(matches),
        'canonical_control': dict(matches[0]) if len(matches) == 1 else None,
        'raw_subtree': None,
    }
    if len(matches) != 1:
        return evidence
    binding = surface.bindings.get(str(matches[0].get('ref') or ''))
    obj = binding.get('atspi_obj') if isinstance(binding, Mapping) else None
    if obj is None:
        evidence['raw_subtree'] = {
            'capture_status': 'unavailable',
            'reason': 'canonical Country binding has no AT-SPI object',
        }
        return evidence
    try:
        raw = find_elements(obj, max_depth=_TIMEOUT_COUNTRY_RAW_MAX_DEPTH)
        captured = raw[:_TIMEOUT_COUNTRY_RAW_MAX_ELEMENTS]
        evidence['raw_subtree'] = {
            'capture_status': 'captured',
            'walker': 'consultation_v2.tree.find_elements',
            'max_depth': _TIMEOUT_COUNTRY_RAW_MAX_DEPTH,
            'observed_count': len(raw),
            'retained_count': len(captured),
            'truncated': len(raw) > len(captured),
            'elements': [_timeout_raw_element(element) for element in captured],
        }
    except Exception as exc:
        evidence['raw_subtree'] = {
            'capture_status': 'failed',
            'error': type(exc).__name__,
        }
    return evidence


def _timeout_barrier_evidence(
    barrier: Mapping[str, Any],
    samples: Iterable[Mapping[str, Any]],
    last_surface: Any,
) -> dict[str, Any]:
    public = _surface_public(last_surface) if last_surface is not None else None
    return {
        'schema': 'ats_greenhouse_postcondition_timeout_evidence_v1',
        'refresh_policy': barrier['refresh_policy'],
        'timeout_ms': barrier['timeout_ms'],
        'interval_ms': barrier['interval_ms'],
        'required_stable_cycles': barrier['stable_cycles'],
        'samples': [dict(sample) for sample in samples],
        'last_surface': None if public is None else {
            'surface': public.get('surface'),
            'revision': public.get('revision'),
        },
        'last_country_projection': _timeout_country_evidence(last_surface),
        'screenshot_authority': 'diagnostic_only_not_captured_by_runner',
    }


def _wait_barrier(
    capture: Callable[[], Any],
    barrier: Mapping[str, Any],
    predicate: Callable[[Any], bool],
) -> BarrierResult:
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    last_surface: Any = None
    last_digest: str | None = None
    stable = 0
    while (time.monotonic() - started) * 1000 <= barrier['timeout_ms']:
        try:
            surface = capture()
            last_surface = surface
            digest = _surface_digest(surface)
            matched = bool(predicate(surface))
        except GreenhouseOneActionError:
            raise
        except Exception as exc:
            raise GreenhouseOneActionError(
                f'exact observation failed: {type(exc).__name__}'
            ) from exc
        samples.append({
            'sample': len(samples) + 1,
            'elapsed_ms': int((time.monotonic() - started) * 1000),
            'revision': digest,
            'postcondition_matched': matched,
            'refresh_policy': barrier['refresh_policy'],
        })
        stable = stable + 1 if matched and digest == last_digest else 1 if matched else 0
        last_digest = digest
        if stable >= barrier['stable_cycles']:
            return BarrierResult(surface=surface, samples=tuple(samples))
        time.sleep(barrier['interval_ms'] / 1000)
    raise GreenhouseOneActionError(
        'exact postcondition barrier timed out',
        barrier_evidence=_timeout_barrier_evidence(
            barrier,
            samples,
            last_surface,
        ),
    )


def _post_action_barrier(
    capture: Callable[[], Any],
    barrier: Mapping[str, Any],
    predicate: Callable[[Any], bool],
) -> BarrierResult:
    try:
        return _wait_barrier(capture, barrier, predicate)
    except GreenhouseOneActionError as exc:
        raise GreenhouseOneActionError(
            exc.reason,
            code=exc.code,
            mutation_started=True,
            barrier_evidence=exc.barrier_evidence,
        ) from exc
    except Exception as exc:
        raise GreenhouseOneActionError(
            f'postcondition observation failed: {type(exc).__name__}',
            mutation_started=True,
        ) from exc


def _resolve_form_source(
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
    secret: bytes,
    action: Mapping[str, Any],
) -> tuple[BoundSurface, Mapping[str, Any], tuple[Mapping[str, Any], ...]]:
    barrier = action_spec.document['barriers']['form']
    result = _wait_barrier(
        lambda: _capture_form(provider_spec, action_spec, secret),
        barrier,
        lambda surface: (
            isinstance(surface, BoundSurface)
            and surface.public['revision'] == action['revision']
            and action['ref'] in surface.bindings
        ),
    )
    surface = result.surface
    assert isinstance(surface, BoundSurface)
    return surface, surface.bindings[action['ref']], result.samples


def _resolve_option_source(
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
    secret: bytes,
    action: Mapping[str, Any],
) -> tuple[BoundSurface, Mapping[str, Any], tuple[Mapping[str, Any], ...]]:
    barrier = action_spec.document['barriers']['options']
    result = _wait_barrier(
        lambda: _capture_options(
            provider_spec,
            action_spec,
            secret,
            action['combo_ref'],
        ),
        barrier,
        lambda surface: (
            isinstance(surface, BoundSurface)
            and surface.public['revision'] == action['revision']
            and surface.public['origin']['combo_ref'] == action['combo_ref']
            and action['ref'] in surface.bindings
        ),
    )
    surface = result.surface
    assert isinstance(surface, BoundSurface)
    return surface, surface.bindings[action['ref']], result.samples


def _resolve_native_source(
    action_spec: ActionSpec,
    application_identity: str,
    action: Mapping[str, Any],
) -> tuple[NativeDialogSnapshot, NativeDialogElementRef, tuple[Mapping[str, Any], ...]]:
    barrier = action_spec.document['barriers']['native_dialog']
    result = _wait_barrier(
        lambda: _capture_native_dialog(action_spec, application_identity),
        barrier,
        lambda snapshot: (
            isinstance(snapshot, NativeDialogSnapshot)
            and snapshot.revision == action['revision']
            and any(
                element.ref == action['ref']
                for elements in snapshot.mapped.values()
                for element in elements
            )
        ),
    )
    snapshot = result.surface
    assert isinstance(snapshot, NativeDialogSnapshot)
    matches = [
        element
        for elements in snapshot.mapped.values()
        for element in elements
        if element.ref == action['ref']
    ]
    if len(matches) != 1:
        raise GreenhouseOneActionError('native source ref is not exact')
    return snapshot, matches[0], result.samples


def _element_ref(element: Mapping[str, Any], ref: str) -> ElementRef:
    return ElementRef(
        key='ats_control',
        name=str(element.get('name') or ''),
        role=str(element.get('role') or ''),
        x=element.get('x'),
        y=element.get('y'),
        states=list(element.get('states') or []),
        raw=dict(element),
        atspi_obj=element.get('atspi_obj'),
    )


def _public_control(surface: BoundSurface, ref: str) -> Mapping[str, Any] | None:
    return next((item for item in surface.public['controls'] if item['ref'] == ref), None)


def _native_public(snapshot: NativeDialogSnapshot) -> Mapping[str, Any]:
    public = snapshot.serializable()
    for elements in public['mapped'].values():
        for element in elements:
            text = element.pop('text', None)
            if text is not None:
                element['text_length'] = len(text)
                element['text_sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return public


def _full_text_selection(element: NativeDialogElementRef) -> bool:
    obj = element.atspi_obj
    if obj is None:
        return False
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi

        text_iface = obj.get_text_iface()
        if text_iface is None:
            return False
        count = int(Atspi.Text.get_character_count(text_iface))
        selection_count = int(Atspi.Text.get_n_selections(text_iface))
        if count == 0:
            return selection_count == 0
        if selection_count != 1:
            return False
        selection = Atspi.Text.get_selection(text_iface, 0)
        if isinstance(selection, (tuple, list)) and len(selection) == 2:
            start_offset, end_offset = selection
        else:
            start_offset = selection.start_offset
            end_offset = selection.end_offset
        return int(start_offset) == 0 and int(end_offset) == count
    except Exception:
        return False


def _artifact_summary(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'slot': artifact['slot'],
        'name': artifact['name'],
        'sha256': artifact['sha256'],
    }


def _artifact_proven(
    surface: BoundSurface,
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
    artifact: Mapping[str, Any],
) -> bool:
    templates = action_spec.document['attachment_proof']['rendered_name_templates']
    exact_names = {template.format(filename=artifact['name']) for template in templates}
    elements = find_elements(
        surface.document,
        max_depth=provider_spec.document['form_projection']['max_depth'],
    )
    slot_names = set(
        action_spec.document['surface']['upload_slots'][artifact['slot']]['ancestor_names_any_of']
    )
    matches = []
    for element in elements:
        if str(element.get('name') or '') not in exact_names:
            continue
        ancestors = set(_ancestor_names(element))
        if ancestors.intersection(slot_names):
            matches.append(element)
    return len(matches) == 1


def _required_controls_complete(surface: BoundSurface) -> bool:
    return _required_elements_complete(surface.bindings.values())


def _confirmation_matches(
    surface: BoundSurface,
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
) -> bool:
    return _confirmation_anchor(surface, provider_spec, action_spec) is not None


def _confirmation_anchor(
    surface: BoundSurface,
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
) -> dict[str, str] | None:
    confirmation = action_spec.document['confirmation']
    if surface.route.grammar_id != confirmation['route_grammar']:
        return None
    elements = find_elements(
        surface.document,
        max_depth=provider_spec.document['form_projection']['max_depth'],
    )
    proven: list[dict[str, str]] = []
    for anchor in confirmation['anchors_any']:
        matches = [
            element
            for element in elements
            if str(element.get('name') or '') == anchor['name']
            and str(element.get('role') or '').strip().lower() in set(anchor['roles_any_of'])
            and {'showing', 'visible'}.issubset(_live_states(element))
        ]
        if len(matches) == 1:
            proven.append({
                'name': anchor['name'],
                'role': str(matches[0].get('role') or '').strip().lower(),
            })
        if len(matches) > 1:
            raise GreenhouseOneActionError('employer confirmation anchor is ambiguous')
    if len(proven) > 1:
        raise GreenhouseOneActionError('multiple employer confirmation anchors are visible')
    return proven[0] if proven else None


def _route_sha256(route: RouteMatch) -> str:
    return hashlib.sha256(canonical_json_bytes({
        'provider': route.provider,
        'route_id': route.grammar_id,
        'host': route.host,
        'application_identity_sha256': route.application_identity_sha256,
    })).hexdigest()


def _trailing_stable_sample_count(samples: Iterable[Mapping[str, Any]]) -> int:
    materialized = list(samples)
    if not materialized:
        return 0
    revision = materialized[-1].get('revision')
    count = 0
    for sample in reversed(materialized):
        if (
            sample.get('postcondition_matched') is not True
            or sample.get('revision') != revision
        ):
            break
        count += 1
    return count


def _employer_confirmation_evidence(
    surface: BoundSurface,
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
    samples: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    materialized = list(samples)
    anchor = _confirmation_anchor(surface, provider_spec, action_spec)
    stable_sample_count = _trailing_stable_sample_count(materialized)
    stable_surface_revision = (
        str(materialized[-1].get('revision') or '')
        if materialized
        else ''
    )
    if (
        anchor is None
        or stable_sample_count < 2
        or stable_surface_revision != surface.public.get('revision')
    ):
        raise GreenhouseOneActionError(
            'stable employer confirmation evidence is incomplete',
            mutation_started=True,
        )
    _sha256_text(
        stable_surface_revision,
        'employer confirmation stable surface revision',
    )
    return {
        'schema': 'ats_greenhouse_employer_confirmation_v1',
        'provider': 'greenhouse',
        'application_identity_sha256': surface.route.application_identity_sha256,
        'route_id': surface.route.grammar_id,
        'route_sha256': _route_sha256(surface.route),
        'anchor_sha256': hashlib.sha256(canonical_json_bytes(anchor)).hexdigest(),
        'stable_surface_revision': stable_surface_revision,
        'stable_sample_count': stable_sample_count,
        'observation_samples_sha256': hashlib.sha256(
            canonical_json_bytes(materialized)
        ).hexdigest(),
    }


def _next_action_surface_capsule(
    surface: Mapping[str, Any],
    application_identity_sha256: str,
) -> dict[str, Any]:
    source_sha256 = hashlib.sha256(canonical_json_bytes(surface)).hexdigest()
    if surface.get('schema') == SURFACE_SCHEMA:
        controls: list[dict[str, Any]] = []
        for raw in surface.get('controls') or []:
            control = {
                key: raw[key]
                for key in ('ref', 'name', 'role', 'operations')
                if key in raw
            }
            if 'value_length' in raw:
                control['is_empty'] = raw['value_length'] == 0
            if 'semantic_values' in raw:
                control['has_semantic_value'] = bool(raw['semantic_values'])
            if 'semantic_token' in raw:
                control['semantic_token'] = raw['semantic_token']
            for key in ('artifact_slot', 'boundary', 'combo_safety'):
                if key in raw:
                    control[key] = raw[key]
            controls.append(control)
        capsule: dict[str, Any] = {
            'schema': 'ats_greenhouse_next_action_surface_v1',
            'provider': 'greenhouse',
            'application_identity_sha256': application_identity_sha256,
            'surface': surface.get('surface'),
            'revision': surface.get('revision'),
            'source_surface_sha256': source_sha256,
            'controls': controls,
        }
        if surface.get('surface') == 'form':
            required_controls_complete = surface.get('required_controls_complete')
            if not isinstance(required_controls_complete, bool):
                raise GreenhouseOneActionError(
                    'form required-controls completion evidence is ambiguous'
                )
            capsule['route_grammar'] = surface.get('route_grammar')
            capsule['complete_form_sha256'] = surface.get('complete_form_sha256')
            capsule['required_controls_complete'] = required_controls_complete
        elif surface.get('surface') == 'options':
            origin = surface.get('origin') or {}
            capsule['origin'] = {
                key: origin[key]
                for key in ('combo_ref', 'name', 'role', 'form_revision', 'match_count')
                if key in origin
            }
        return capsule
    if surface.get('schema') == 'native_dialog_snapshot.v1':
        mapped: dict[str, list[dict[str, Any]]] = {}
        for key, elements in (surface.get('mapped') or {}).items():
            mapped[key] = [
                {
                    field: element[field]
                    for field in ('key', 'ref', 'role', 'states')
                    if field in element
                }
                for element in elements
            ]
        return {
            'schema': 'ats_greenhouse_next_action_surface_v1',
            'provider': 'greenhouse',
            'application_identity_sha256': application_identity_sha256,
            'surface': 'native_dialog',
            'revision': surface.get('revision'),
            'source_surface_sha256': source_sha256,
            'mapped': mapped,
        }
    raise GreenhouseOneActionError('next-action surface type is unsupported')


def _action_summary(action: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {'kind': action['kind']}
    for key in ('ref', 'revision', 'combo_ref', 'expected_option_name', 'expected_state', 'slot'):
        if key in action:
            summary[key] = action[key]
    if action['kind'] == 'fill':
        summary['value_length'] = len(action['value'])
        summary['value_sha256'] = action['value_sha256']
    if 'artifact' in action:
        summary['artifact'] = _artifact_summary(action['artifact'])
    if action['kind'] == 'submit':
        precondition = action['precondition']
        summary['precondition'] = {
            'required_controls_complete': precondition['required_controls_complete'],
            'truth_attested': precondition['truth_attested'],
            'complete_form_sha256': precondition['complete_form_sha256'],
            'truth_attestation_sha256': precondition['truth_attestation_sha256'],
            'artifacts': [_artifact_summary(item) for item in precondition['artifacts']],
        }
    return summary


def _perform_action(
    request: Mapping[str, Any],
    provider_spec: ProviderSpec,
    action_spec: ActionSpec,
    secret: bytes,
) -> tuple[dict[str, Any], bool]:
    action = request['action']
    kind = action['kind']
    identity = request['application_identity_sha256']
    barriers = action_spec.document['barriers']
    if kind == 'observe_form':
        barrier = _wait_barrier(
            lambda: _capture_form(provider_spec, action_spec, secret),
            barriers['form'],
            lambda surface: (
                isinstance(surface, BoundSurface)
                and surface.route.application_identity_sha256 == identity
                and bool(surface.public['controls'])
            ),
        )
        surface = barrier.surface
        assert isinstance(surface, BoundSurface)
        origin_contract = action_spec.document['options_surface']['origin']
        expanded = [
            control
            for control in surface.public['controls']
            if control.get('role') == origin_contract['role']
            and set(origin_contract['states_all']) <= set(control.get('states') or [])
        ]
        if len(expanded) > 1:
            raise GreenhouseOneActionError(
                'inherited expanded combo cardinality is '
                f'{len(expanded)}; expected at most 1'
            )
        if expanded:
            origin_ref = expanded[0].get('ref')
            if not isinstance(origin_ref, str) or not origin_ref:
                raise GreenhouseOneActionError(
                    'inherited expanded combo has no exact ref'
                )
            inherited_form_revision = surface.public['revision']
            barrier = _wait_barrier(
                lambda: _capture_options(
                    provider_spec,
                    action_spec,
                    secret,
                    origin_ref,
                ),
                barriers['options'],
                lambda candidate: (
                    isinstance(candidate, BoundSurface)
                    and candidate.public.get('surface') == 'options'
                    and candidate.route.application_identity_sha256 == identity
                    and candidate.public['application_identity_sha256'] == identity
                    and candidate.public['origin']['combo_ref'] == origin_ref
                    and candidate.public['origin']['name'] == expanded[0]['name']
                    and candidate.public['origin']['role'] == expanded[0]['role']
                    and candidate.public['origin']['form_revision']
                    == inherited_form_revision
                    and candidate.public['origin']['match_count'] == 1
                    and candidate.public['container']['match_count'] == 1
                    and bool(candidate.public['controls'])
                ),
            )
            surface = barrier.surface
            assert isinstance(surface, BoundSurface)
        return {
            'state': 'action_ready',
            'surface': surface.public,
            'surface_capsule': _next_action_surface_capsule(
                surface.public,
                identity,
            ),
            'samples': list(barrier.samples),
            'mutation_count': 0,
            'next_mutation_authorized': True,
        }, False

    if kind == 'select_option':
        source, element, source_samples = _resolve_option_source(
            provider_spec,
            action_spec,
            secret,
            action,
        )
    elif kind.startswith('chooser_'):
        source, element, source_samples = _resolve_native_source(
            action_spec,
            identity,
            action,
        )
    else:
        source, element, source_samples = _resolve_form_source(
            provider_spec,
            action_spec,
            secret,
            action,
        )
    if (
        isinstance(source, BoundSurface)
        and source.route.application_identity_sha256 != identity
    ):
        raise GreenhouseOneActionError('action application identity does not match the live route')

    mutation_started = False
    if kind == 'focus':
        public = _public_control(source, action['ref'])
        if public is None or 'focus' not in public['operations']:
            raise GreenhouseOneActionError('exact focus control is not focus-ready')
        mutation_started = True
        if not atspi_focus(element):
            raise GreenhouseOneActionError('exact focus primitive failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_form(provider_spec, action_spec, secret),
            barriers['form'],
            lambda surface: (
                (_public_control(surface, action['ref']) or {}).get('states') is not None
                and 'focused' in (_public_control(surface, action['ref']) or {})['states']
            ),
        )
    elif kind == 'fill':
        public = _public_control(source, action['ref'])
        if public is None or 'fill' not in public['operations']:
            raise GreenhouseOneActionError('exact text control is not fill-ready')
        mutation_started = True
        if not inp.type_text(action['value']):
            raise GreenhouseOneActionError('exact fill primitive failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_form(provider_spec, action_spec, secret),
            barriers['form'],
            lambda surface: (
                (_public_control(surface, action['ref']) or {}).get('value_sha256')
                == action['value_sha256']
            ),
        )
    elif kind == 'scroll_combo':
        public = _public_control(source, action['ref'])
        if public is None or public['operations'] != ['scroll_combo']:
            raise GreenhouseOneActionError('combo is not an exact scroll frontier')
        ref = _element_ref(element, action['ref'])
        mutation_started = True
        if not ConsultationRuntime.scroll_element_into_view(None, ref):
            raise GreenhouseOneActionError('exact combo scroll primitive failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_form(provider_spec, action_spec, secret),
            barriers['form'],
            lambda surface: (
                ((_public_control(surface, action['ref']) or {}).get('combo_safety') or {}).get(
                    'geometry'
                ) == 'contained_by_active_document'
            ),
        )
    elif kind == 'open_combo':
        public = _public_control(source, action['ref'])
        if public is None or public['operations'] != ['open_combo']:
            refusal = (public or {}).get('combo_safety', {}).get('refusal')
            raise GreenhouseOneActionError(
                str(refusal or 'combo is not activation-ready')
            )
        mutation_started = True
        actuation = atspi_mapped_pointer_activate(element)
        if actuation.get('ok') is not True:
            raise GreenhouseOneActionError('exact combo activation failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_options(
                provider_spec,
                action_spec,
                secret,
                action['ref'],
            ),
            barriers['options'],
            lambda surface: (
                isinstance(surface, BoundSurface)
                and surface.public['origin']['combo_ref'] == action['ref']
                and surface.public['origin']['form_revision'] != action['revision']
                and surface.public['container']['match_count'] == 1
                and bool(surface.public['controls'])
            ),
        )
    elif kind == 'select_option':
        public = _public_control(source, action['ref'])
        if (
            public is None
            or public.get('name') != action['expected_option_name']
            or public.get('operations') != ['select_option']
        ):
            raise GreenhouseOneActionError('fresh option ref/name binding is invalid')
        mutation_started = True
        if not atspi_click(element):
            raise GreenhouseOneActionError('exact option activation failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_form(provider_spec, action_spec, secret),
            barriers['form'],
            lambda surface: _selected_option_matches(surface, action),
        )
    elif kind == 'activate_choice':
        public = _public_control(source, action['ref'])
        if public is None or public.get('operations') != ['activate_choice']:
            raise GreenhouseOneActionError('choice control is not activation-ready')
        mutation_started = True
        if not atspi_click(element):
            raise GreenhouseOneActionError('exact choice activation failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_form(provider_spec, action_spec, secret),
            barriers['form'],
            lambda surface: action['expected_state'] in (
                (_public_control(surface, action['ref']) or {}).get('states') or []
            ),
        )
    elif kind == 'open_upload':
        public = _public_control(source, action['ref'])
        if (
            public is None
            or public.get('operations') != ['open_upload']
            or public.get('artifact_slot') != action['slot']
        ):
            raise GreenhouseOneActionError('upload control/slot binding is invalid')
        mutation_started = True
        if not atspi_click(element):
            raise GreenhouseOneActionError('exact upload activation failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_native_dialog(action_spec, identity),
            barriers['native_dialog'],
            lambda snapshot: (
                isinstance(snapshot, NativeDialogSnapshot)
                and len(snapshot.mapped.get('dialog_root') or ()) == 1
                and len(snapshot.mapped.get('chooser_widget') or ()) == 1
            ),
        )
    elif kind == 'chooser_location':
        assert isinstance(source, NativeDialogSnapshot)
        if element.key != 'chooser_widget':
            raise GreenhouseOneActionError('native chooser widget binding is invalid')
        mutation_started = True
        if not inp.press_key_cleared('ctrl+l'):
            raise GreenhouseOneActionError('native chooser location action failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_native_dialog(action_spec, identity),
            barriers['native_dialog'],
            lambda snapshot: len(snapshot.mapped.get('location_entry') or ()) == 1,
        )
    elif kind == 'chooser_select_all':
        assert isinstance(source, NativeDialogSnapshot)
        if element.key != 'location_entry':
            raise GreenhouseOneActionError('native location entry binding is invalid')
        mutation_started = True
        if not inp.press_key_cleared('ctrl+a'):
            raise GreenhouseOneActionError('native chooser select-all action failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_native_dialog(action_spec, identity),
            barriers['native_dialog'],
            lambda snapshot: (
                len(snapshot.mapped.get('location_entry') or ()) == 1
                and _full_text_selection(snapshot.mapped['location_entry'][0])
            ),
        )
    elif kind == 'chooser_type_path':
        assert isinstance(source, NativeDialogSnapshot)
        artifact = _validate_artifact(action['artifact'])
        if element.key != 'location_entry' or not _full_text_selection(element):
            raise GreenhouseOneActionError('native location entry is not fully selected')
        mutation_started = True
        if not inp.type_text(artifact['path']):
            raise GreenhouseOneActionError('native artifact path action failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_native_dialog(action_spec, identity),
            barriers['native_dialog'],
            lambda snapshot: (
                len(snapshot.mapped.get('location_entry') or ()) == 1
                and snapshot.mapped['location_entry'][0].text == artifact['path']
            ),
        )
    elif kind == 'chooser_confirm':
        assert isinstance(source, NativeDialogSnapshot)
        artifact = _validate_artifact(action['artifact'])
        if element.key != 'open_button':
            raise GreenhouseOneActionError('native Open button binding is invalid')
        mutation_started = True
        if not atspi_click({
            'atspi_obj': element.atspi_obj,
            'name': element.name,
            'role': element.role,
        }):
            raise GreenhouseOneActionError('native chooser confirmation failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_form(provider_spec, action_spec, secret),
            barriers['form'],
            lambda surface: _artifact_proven(surface, provider_spec, action_spec, artifact),
        )
    elif kind == 'submit':
        precondition = _validate_submit_precondition(action['precondition'])
        public = _public_control(source, action['ref'])
        if public is None or public.get('operations') != ['submit']:
            raise GreenhouseOneActionError(
                'Submit is not exact and enabled',
                code='unmapped_ui_or_question',
            )
        if not hmac.compare_digest(
            source.public['complete_form_sha256'],
            precondition['complete_form_sha256'],
        ):
            raise GreenhouseOneActionError('live form state does not match submit precondition')
        if not _required_controls_complete(source):
            raise GreenhouseOneActionError(
                'live required controls are incomplete',
                code='missing_truthful_applicant_data',
            )
        if not all(
            _artifact_proven(source, provider_spec, action_spec, artifact)
            for artifact in precondition['artifacts']
        ):
            raise GreenhouseOneActionError(
                'live artifact proof does not match submit precondition',
                code='missing_truthful_applicant_data',
            )
        mutation_started = True
        if not atspi_click(element):
            raise GreenhouseOneActionError('exact Submit activation failed', mutation_started=True)
        after = _post_action_barrier(
            lambda: _capture_form(provider_spec, action_spec, secret),
            barriers['confirmation'],
            lambda surface: _confirmation_matches(surface, provider_spec, action_spec),
        )
    else:
        raise GreenhouseOneActionError('unsupported action dispatch')

    public_after = _surface_public(after.surface)
    state = 'employer_confirmation_proven' if kind == 'submit' else 'action_ready'
    result = {
        'state': state,
        'source_samples': list(source_samples),
        'postcondition_samples': list(after.samples),
        'surface': public_after,
        'mutation_count': 1,
        'next_mutation_authorized': kind != 'submit',
    }
    if kind == 'submit':
        assert isinstance(after.surface, BoundSurface)
        result['employer_confirmation'] = _employer_confirmation_evidence(
            after.surface,
            provider_spec,
            action_spec,
            after.samples,
        )
    else:
        result['surface_capsule'] = _next_action_surface_capsule(
            public_after,
            identity,
        )
    return result, mutation_started


def execute_frozen_action_fd(fd_value: int, expected_sha256: str) -> dict[str, Any]:
    request = load_frozen_action_fd(fd_value, expected_sha256)
    provider_spec = load_provider_spec('greenhouse')
    action_spec = load_action_spec()
    secret = _lease_secret()
    display = _display()
    environment = {
        'display': display,
        'atspi_bus_sha256': hashlib.sha256(
            str(os.environ['AT_SPI_BUS_ADDRESS']).encode('utf-8')
        ).hexdigest(),
        'firefox_pid': _firefox_pid(),
        'provider_sha256': provider_spec.sha256,
        'action_spec_sha256': action_spec.sha256,
    }
    mutation_started = False
    with _receipt_store(request) as store:
        _assert_receipt_frontier(store, request)
        observation_id = str(uuid.uuid4())
        _write_event(
            store,
            request,
            'execution_started',
            {
                'schema': 'ats_greenhouse_action_started_v1',
                'provider': 'greenhouse',
                'display': display,
                'transaction_id': request['transaction_id'],
                'action_id': request['action_id'],
                'application_identity_sha256': request['application_identity_sha256'],
                'action': _action_summary(request['action']),
                'environment': environment,
                'maximum_ui_mutations': len(
                    MUTATION_PRIMITIVE_BY_ACTION[request['action']['kind']]
                ),
            },
            observation_id=observation_id,
        )
        try:
            result, mutation_started = _perform_action(
                request,
                provider_spec,
                action_spec,
                secret,
            )
            payload = {
                'schema': RESULT_SCHEMA,
                'ok': True,
                'provider': 'greenhouse',
                'display': display,
                'transaction_id': request['transaction_id'],
                'action_id': request['action_id'],
                'application_identity_sha256': request['application_identity_sha256'],
                'action': _action_summary(request['action']),
                'environment': environment,
                **result,
            }
            kind = 'ats_submitted' if request['action']['kind'] == 'submit' else 'ats_action_result'
            receipt = _write_event(
                store,
                request,
                kind,
                payload,
                observation_id=observation_id,
            )
            returned = {**payload, 'receipt_event_hash': receipt['event_hash']}
            if request['action']['kind'] == 'submit':
                confirmation = dict(returned['employer_confirmation'])
                confirmation['receipt_sha256'] = receipt['event_hash']
                returned['employer_confirmation'] = confirmation
            return returned
        except Exception as exc:
            if isinstance(exc, GreenhouseOneActionError):
                mutation_started = mutation_started or exc.mutation_started
                stop_reason = exc.reason
                stop_code = (
                    'side_effect_uncertainty' if mutation_started else exc.code
                )
            else:
                mutation_started = request['action']['kind'] != 'observe_form'
                stop_reason = f'unhandled action failure: {type(exc).__name__}'
                stop_code = (
                    'side_effect_uncertainty'
                    if mutation_started
                    else 'exact_postcondition_failure'
                )
            payload = {
                'schema': RESULT_SCHEMA,
                'ok': False,
                'provider': 'greenhouse',
                'display': display,
                'transaction_id': request['transaction_id'],
                'action_id': request['action_id'],
                'application_identity_sha256': request['application_identity_sha256'],
                'action': _action_summary(request['action']),
                'environment': environment,
                'state': 'side_effect_uncertain' if mutation_started else 'terminal_halt',
                'stop_code': stop_code,
                'stop_reason': stop_reason,
                'mutation_started': mutation_started,
                'next_mutation_authorized': False,
            }
            if (
                isinstance(exc, GreenhouseOneActionError)
                and exc.barrier_evidence is not None
            ):
                payload['postcondition_evidence'] = exc.barrier_evidence
            receipt = _write_event(
                store,
                request,
                'ats_terminal',
                payload,
                observation_id=observation_id,
            )
            return {**payload, 'receipt_event_hash': receipt['event_hash']}


__all__ = [
    'ACTION_SCHEMA',
    'RESULT_SCHEMA',
    'SURFACE_SCHEMA',
    'ActionSpec',
    'BoundSurface',
    'GreenhouseOneActionError',
    'execute_frozen_action_fd',
    'load_action_spec',
    'load_frozen_action_fd',
    'project_form_surface',
]
