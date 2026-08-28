#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import gi  # noqa: F401
except ModuleNotFoundError:
    class _EnumNamespace:
        def __getattr__(self, name: str) -> str:
            return name.casefold()

    atspi_stub = types.SimpleNamespace(
        CoordType=_EnumNamespace(),
        ScrollType=_EnumNamespace(),
        StateType=_EnumNamespace(),
        Text=types.SimpleNamespace(),
    )
    gi_stub = types.ModuleType('gi')
    repository_stub = types.ModuleType('gi.repository')
    gi_stub.require_version = lambda *_args: None
    gi_stub.repository = repository_stub
    repository_stub.Atspi = atspi_stub
    sys.modules['gi'] = gi_stub
    sys.modules['gi.repository'] = repository_stub

from consultation_v2.ats.greenhouse_one_action import (  # noqa: E402
    MUTATION_PRIMITIVE_BY_ACTION,
    GreenhouseOneActionError,
    _capture_options,
    _complete_form_sha256,
    _native_public,
    load_frozen_action_fd,
    load_action_spec,
    project_form_surface,
)
from consultation_v2.ats import greenhouse_one_action as greenhouse  # noqa: E402
from consultation_v2.ats.provider_contract import load_provider_spec  # noqa: E402
from consultation_v2.ats.read_only import Rect  # noqa: E402
from consultation_v2.ats.route_contract import match_provider_route  # noqa: E402
from consultation_v2.native_dialog_snapshot import (  # noqa: E402
    NativeDialogElementRef,
    NativeDialogObservationError,
    NativeDialogSnapshot,
    build_native_dialog_snapshot,
    build_native_dialog_snapshot_from_contract,
)
from consultation_v2 import native_dialog_snapshot as native_snapshot  # noqa: E402


ONE_ACTION_PATH = REPO_ROOT / 'consultation_v2/ats/greenhouse_one_action.py'
NATIVE_PATH = REPO_ROOT / 'consultation_v2/native_dialog_snapshot.py'
RUNNER_PATH = REPO_ROOT / 'scripts/run_ats_greenhouse_one_action.py'


class _FakeState:
    def __init__(self, name: str) -> None:
        self.value_nick = name


class _FakeStateSet:
    def __init__(self, names: list[str]) -> None:
        self._states = [_FakeState(name) for name in names]

    def get_states(self) -> list[_FakeState]:
        return self._states

    def contains(self, state: object) -> bool:
        candidate = str(getattr(state, 'value_nick', state)).casefold().replace('_', ' ')
        return candidate in {
            item.value_nick.casefold().replace('_', ' ')
            for item in self._states
        }


class _FakeNode:
    def __init__(
        self,
        name: str,
        role: str,
        states: list[str],
        *,
        children: list['_FakeNode'] | None = None,
        pid: int = 4242,
        text: str = '',
    ) -> None:
        self._name = name
        self._role = role
        self._states = states
        self._children = children or []
        self._pid = pid
        self._parent: _FakeNode | None = None
        self.text = text
        self.cache_clears = 0
        for child in self._children:
            child._parent = self

    def get_name(self) -> str:
        return self._name

    def get_role_name(self) -> str:
        return self._role

    def get_state_set(self) -> _FakeStateSet:
        return _FakeStateSet(self._states)

    def get_child_count(self) -> int:
        return len(self._children)

    def get_child_at_index(self, index: int) -> '_FakeNode':
        return self._children[index]

    def get_process_id(self) -> int:
        return self._pid

    def get_parent(self) -> '_FakeNode | None':
        return self._parent

    def get_text_iface(self) -> None:
        return None

    def get_selection_iface(self) -> None:
        return None

    def clear_cache_single(self) -> None:
        self.cache_clears += 1


def _native_tree() -> tuple[_FakeNode, _FakeNode]:
    location_entry = _FakeNode(
        '',
        'text',
        ['showing', 'visible', 'enabled', 'focusable', 'focused', 'editable'],
        text='/private/redacted.pdf',
    )
    location_layer = _FakeNode(
        'Location Layer',
        'filler',
        ['showing', 'visible', 'enabled'],
        children=[location_entry],
    )
    chooser = _FakeNode(
        'File Chooser Widget',
        'file chooser',
        ['showing', 'visible', 'enabled'],
        children=[location_layer],
    )
    cancel = _FakeNode(
        'Cancel',
        'push button',
        ['showing', 'visible', 'enabled', 'focusable'],
    )
    open_button = _FakeNode(
        'Open',
        'push button',
        ['showing', 'visible', 'enabled', 'focusable'],
    )
    dialog = _FakeNode(
        'File Upload',
        'file chooser',
        ['showing', 'visible', 'enabled', 'active'],
        children=[chooser, cancel, open_button],
    )
    firefox = _FakeNode('Firefox', 'application', ['enabled'], children=[dialog])
    return firefox, location_entry


def _assert_public_native_walker() -> None:
    from gi.repository import Atspi

    action_spec = load_action_spec()
    contract = action_spec.document['native_dialog']
    desktop = _FakeNode('Desktop', 'desktop', ['enabled'])
    firefox, _entry = _native_tree()
    binding = 'a' * 64
    with (
        mock.patch.object(Atspi, 'get_desktop', return_value=desktop, create=True),
        mock.patch.object(native_snapshot, '_read_text', lambda obj: obj.text),
    ):
        bound = build_native_dialog_snapshot_from_contract(
            'greenhouse',
            contract=contract,
            firefox=firefox,
            expected_firefox_pid=4242,
            revision_binding_sha256=binding,
        )
        unbound = build_native_dialog_snapshot_from_contract(
            'greenhouse',
            contract=contract,
            firefox=firefox,
            expected_firefox_pid=4242,
        )
        with (
            mock.patch.object(
                native_snapshot,
                '_native_dialog_contract',
                return_value=contract,
            ),
            mock.patch.object(
                native_snapshot.platform_routing,
                'find_firefox_for_platform',
                return_value=firefox,
            ),
        ):
            legacy = build_native_dialog_snapshot('greenhouse')
    if bound.revision == unbound.revision:
        raise RuntimeError('native revision binding did not affect the bound snapshot')
    if legacy.revision != unbound.revision:
        raise RuntimeError('legacy native-dialog wrapper revision behavior changed')
    if len(bound.mapped['open_button']) != 1 or bound.contract_sha256 != unbound.contract_sha256:
        raise RuntimeError('public native-dialog helper did not use the shared exact contract')
    if desktop.cache_clears != 3 or firefox.cache_clears != 3:
        raise RuntimeError('native-dialog cache invalidation count changed')
    try:
        build_native_dialog_snapshot_from_contract(
            'greenhouse',
            contract=contract,
            firefox=firefox,
            expected_firefox_pid=9999,
        )
    except NativeDialogObservationError:
        pass
    else:
        raise RuntimeError('public native-dialog helper accepted a Firefox PID mismatch')


def _assert_greenhouse_surface() -> None:
    provider_spec = load_provider_spec('greenhouse')
    action_spec = load_action_spec()
    job = match_provider_route(
        provider_spec,
        'https://boards.greenhouse.io/example/jobs/123456',
    )
    confirmation = match_provider_route(
        provider_spec,
        'https://boards.greenhouse.io/example/jobs/123456/confirmation',
    )
    if confirmation.grammar_id != 'hosted_confirmation':
        raise RuntimeError('Greenhouse confirmation route is not exact')
    if confirmation.application_identity_sha256 != job.application_identity_sha256:
        raise RuntimeError('Greenhouse confirmation route lost application identity')

    states = ['showing', 'visible', 'enabled', 'focusable']
    elements = [
        {
            'name': 'Country',
            'role': 'combo box',
            'states': states,
            'x': 120,
            'y': 200,
            'extent': {'x': 100, 'y': 180, 'width': 300, 'height': 40},
        },
        {
            'name': 'Referral source',
            'role': 'combo box',
            'states': states,
            'x': 120,
            'y': 60,
            'extent': {'x': 100, 'y': 40, 'width': 300, 'height': 40},
        },
        {
            'name': 'Submit Application',
            'role': 'push button',
            'states': states,
            'x': 120,
            'y': 500,
            'extent': {'x': 100, 'y': 480, 'width': 220, 'height': 40},
        },
    ]
    public, _bindings = project_form_surface(
        provider_spec,
        action_spec,
        job,
        elements,
        Rect(0, 100, 1000, 700),
        b'x' * 32,
    )
    controls = {item['name']: item for item in public['controls']}
    if controls['Country']['operations'] != ['open_combo']:
        raise RuntimeError('contained Greenhouse combo did not compile to open_combo')
    if controls['Referral source']['operations'] != ['scroll_combo']:
        raise RuntimeError('off-document Greenhouse combo lost its scroll frontier')
    if controls['Referral source']['combo_safety']['refusal'] != (
        'combo_rect_outside_document_rect'
    ):
        raise RuntimeError('PR218 exact off-document combo refusal was not preserved')
    if controls['Submit Application']['operations'] != ['submit']:
        raise RuntimeError('exact enabled Greenhouse Submit boundary is absent')
    if public['complete_form_sha256'] != _complete_form_sha256(
        job.application_identity_sha256,
        public['controls'],
    ):
        raise RuntimeError('Greenhouse complete-form digest is not reproducible')
    if public['required_controls_complete'] is not False:
        raise RuntimeError('absent required controls did not fail closed')
    public['controls'][0]['semantic_values'] = ['private-applicant-value']
    public['controls'][0]['value_length'] = len('private-applicant-value')
    public['controls'][0]['value_sha256'] = hashlib.sha256(
        b'private-applicant-value'
    ).hexdigest()
    capsule = greenhouse._next_action_surface_capsule(
        public,
        job.application_identity_sha256,
    )
    encoded_capsule = json.dumps(capsule, sort_keys=True)
    if (
        capsule['schema'] != 'ats_greenhouse_next_action_surface_v1'
        or capsule['revision'] != public['revision']
        or capsule['required_controls_complete'] is not False
        or capsule['controls'][0].get('has_semantic_value') is not True
        or 'private-applicant-value' in encoded_capsule
        or 'value_sha256' in encoded_capsule
        or 'semantic_values' in encoded_capsule
    ):
        raise RuntimeError('next-action surface capsule exposed applicant values')

    complete_elements = [
        {
            'name': 'Accept terms',
            'role': 'check box',
            'states': [*states, 'required', 'checked'],
            'x': 120,
            'y': 440,
        },
        elements[-1],
    ]
    complete_public, _ = project_form_surface(
        provider_spec,
        action_spec,
        job,
        complete_elements,
        Rect(0, 100, 1000, 700),
        b'y' * 32,
    )
    complete_capsule = greenhouse._next_action_surface_capsule(
        complete_public,
        job.application_identity_sha256,
    )
    if (
        complete_public['required_controls_complete'] is not True
        or complete_capsule['required_controls_complete'] is not True
    ):
        raise RuntimeError('complete required controls were not carried into the capsule')

    ambiguous_public = dict(complete_public)
    ambiguous_public.pop('required_controls_complete')
    try:
        greenhouse._next_action_surface_capsule(
            ambiguous_public,
            job.application_identity_sha256,
        )
    except GreenhouseOneActionError as exc:
        if 'completion evidence is ambiguous' not in str(exc):
            raise
    else:
        raise RuntimeError('missing required-controls evidence did not fail closed')


def _assert_confirmation_capsule_receipt_order() -> None:
    provider_spec = load_provider_spec('greenhouse')
    action_spec = load_action_spec()
    route = match_provider_route(
        provider_spec,
        'https://boards.greenhouse.io/example/jobs/123456/confirmation',
    )
    revision = '8' * 64
    samples = [
        {
            'sample': index,
            'elapsed_ms': index * 100,
            'revision': revision,
            'postcondition_matched': True,
            'refresh_policy': 'invalidate_reacquire',
        }
        for index in (1, 2)
    ]
    surface = greenhouse.BoundSurface(
        public={'revision': revision},
        bindings={},
        firefox=None,
        document=object(),
        route=route,
    )
    anchor = {
        'name': 'Application submitted',
        'role': 'heading',
        'states': ['showing', 'visible'],
    }
    with mock.patch.object(greenhouse, 'find_elements', return_value=[anchor]):
        evidence = greenhouse._employer_confirmation_evidence(
            surface,
            provider_spec,
            action_spec,
            samples,
        )
    if (
        evidence['schema'] != 'ats_greenhouse_employer_confirmation_v1'
        or evidence['route_id'] != 'hosted_confirmation'
        or evidence['stable_surface_revision'] != revision
        or evidence['stable_sample_count'] != 2
        or 'receipt_sha256' in evidence
    ):
        raise RuntimeError('employer confirmation evidence is not exact')

    class ReceiptStore:
        def __init__(self) -> None:
            self.raw_payloads: list[dict[str, object]] = []
            self.events: tuple[dict[str, object], ...] = ()

        def __enter__(self) -> 'ReceiptStore':
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def has_execution(self, _action_id: str) -> bool:
            return False

        def write_once(
            self,
            _event: dict[str, object],
            raw: bytes,
        ) -> dict[str, str]:
            self.raw_payloads.append(json.loads(raw))
            return {
                'event_hash': ('a' if len(self.raw_payloads) == 1 else 'b') * 64,
            }

    store = ReceiptStore()
    request = {
        'schema': 'ats_greenhouse_frozen_action_v1',
        'provider': 'greenhouse',
        'transaction_id': '00000000-0000-4000-8000-000000000000',
        'action_id': '00000000-0000-4000-8000-000000000001',
        'application_identity_sha256': route.application_identity_sha256,
        'expected_prior_event_hash': None,
        'action': {
            'kind': 'submit',
            'ref': 'r_' + ('1' * 32),
            'revision': revision,
            'precondition': {
                'required_controls_complete': True,
                'truth_attested': True,
                'complete_form_sha256': '2' * 64,
                'truth_attestation_sha256': '3' * 64,
                'artifacts': [],
            },
        },
    }
    performed = {
        'state': 'employer_confirmation_proven',
        'source_samples': samples,
        'postcondition_samples': samples,
        'surface': {'revision': revision},
        'mutation_count': 1,
        'next_mutation_authorized': False,
        'employer_confirmation': evidence,
    }
    fake_spec = types.SimpleNamespace(sha256='4' * 64)
    with (
        mock.patch.object(greenhouse, 'load_frozen_action_fd', return_value=request),
        mock.patch.object(greenhouse, 'load_provider_spec', return_value=fake_spec),
        mock.patch.object(greenhouse, 'load_action_spec', return_value=fake_spec),
        mock.patch.object(greenhouse, '_lease_secret', return_value=b'x' * 32),
        mock.patch.object(greenhouse, '_display', return_value=':17'),
        mock.patch.object(greenhouse, '_firefox_pid', return_value=4242),
        mock.patch.object(greenhouse, '_receipt_store', return_value=store),
        mock.patch.object(greenhouse, '_perform_action', return_value=(performed, True)),
        mock.patch.dict(os.environ, {'AT_SPI_BUS_ADDRESS': 'unix:path=/synthetic'}),
    ):
        returned = greenhouse.execute_frozen_action_fd(9, '5' * 64)
    durable = store.raw_payloads[-1]['employer_confirmation']
    if (
        not isinstance(durable, dict)
        or 'receipt_sha256' in durable
        or returned['employer_confirmation']['receipt_sha256'] != 'b' * 64
        or returned['receipt_event_hash'] != 'b' * 64
    ):
        raise RuntimeError('confirmation receipt binding became self-referential')


def _assert_combo_owned_options_surface() -> None:
    provider_spec = load_provider_spec('greenhouse')
    action_spec = load_action_spec()
    if action_spec.document['options_surface']['semantic_projection'] != {
        'origin': {'name': 'Country', 'role': 'combo box'},
        'kind': 'country_calling_code_suffix_v1',
    }:
        raise RuntimeError('Greenhouse country semantic contract is not exact')
    route = match_provider_route(
        provider_spec,
        'https://boards.greenhouse.io/example/jobs/123456',
    )
    secret = b'z' * 32
    base_states = ['showing', 'visible', 'enabled', 'focusable']
    combo_node = _FakeNode('Country', 'combo box', [*base_states, 'expanded'])
    expanded_form = [{
        'name': 'Country',
        'role': 'combo box',
        'states': [*base_states, 'expanded'],
        'x': 120,
        'y': 200,
        'extent': {'x': 100, 'y': 180, 'width': 300, 'height': 40},
        'atspi_obj': combo_node,
    }]
    expanded_public, _ = project_form_surface(
        provider_spec,
        action_spec,
        route,
        expanded_form,
        Rect(0, 100, 1000, 700),
        secret,
    )
    origin_ref = expanded_public['controls'][0]['ref']
    if expanded_public['controls'][0]['operations']:
        raise RuntimeError('expanded combo retained mutation authority')

    collapsed_node = _FakeNode('Country', 'combo box', base_states)
    collapsed_form = [{**expanded_form[0], 'states': base_states, 'atspi_obj': collapsed_node}]
    firefox = _FakeNode('Firefox', 'application', ['enabled'])
    document = _FakeNode('Greenhouse', 'document web', ['showing', 'visible'])

    def option_tree(names: list[str]) -> list[dict]:
        nodes = [
            _FakeNode(name, 'list item', ['showing', 'visible', 'enabled'])
            for name in names
        ]
        container = _FakeNode(
            '',
            'list box',
            ['showing', 'visible'],
            children=nodes,
        )
        return [
            {
                'name': '',
                'role': 'list box',
                'states': ['showing'],
                'atspi_obj': container,
            },
            *[
                {
                    'name': name,
                    'role': 'list item',
                    'states': ['showing', 'enabled'],
                    'x': 120,
                    'y': 240 + (index * 40),
                    'atspi_obj': node,
                }
                for index, (name, node) in enumerate(zip(names, nodes, strict=True))
            ],
        ]

    def capture(
        form_elements: list[dict],
        option_elements: list[dict],
        combo_ref: str = origin_ref,
    ):
        with (
            mock.patch.object(greenhouse, '_firefox_pid', return_value=4242),
            mock.patch.object(greenhouse.atspi, 'find_all_firefox', return_value=[firefox]),
            mock.patch.object(
                greenhouse.atspi,
                'document_web_elements',
                return_value=[document],
            ),
            mock.patch.object(
                greenhouse.atspi,
                'get_document_url',
                return_value='https://boards.greenhouse.io/example/jobs/123456',
            ),
            mock.patch.object(
                greenhouse,
                'find_elements',
                side_effect=[form_elements, option_elements],
            ),
            mock.patch.object(
                greenhouse,
                '_document_rect',
                return_value=Rect(0, 100, 1000, 700),
            ),
        ):
            return _capture_options(provider_spec, action_spec, secret, combo_ref)

    option_elements = option_tree(['Canada +1', 'United States +1'])
    exact = capture(expanded_form, option_elements)
    if exact.public['origin']['combo_ref'] != origin_ref:
        raise RuntimeError('options surface lost its exact origin combo ref')
    if exact.public['origin']['form_revision'] != expanded_public['revision']:
        raise RuntimeError('options surface lost its expanded form revision')
    if exact.public['container']['match_count'] != 1:
        raise RuntimeError('options surface did not prove one exact container')
    if [item['name'] for item in exact.public['controls']] != [
        'Canada +1',
        'United States +1',
    ]:
        raise RuntimeError('options surface did not expose exact container descendants')
    if [item.get('semantic_token') for item in exact.public['controls']] != [
        'Canada',
        'United States',
    ]:
        raise RuntimeError('country option semantic tokens are not exact')
    capsule = greenhouse._next_action_surface_capsule(
        exact.public,
        route.application_identity_sha256,
    )
    if [
        (item.get('name'), item.get('semantic_token'))
        for item in capsule['controls']
    ] != [
        ('Canada +1', 'Canada'),
        ('United States +1', 'United States'),
    ]:
        raise RuntimeError('country tokens lost their exact public rendered-name binding')

    selected_combo = _FakeNode('Country', 'combo box', base_states)
    selected_value = _FakeNode(
        '',
        'section',
        ['showing', 'visible'],
        text='+1',
    )
    selected_section = _FakeNode(
        '',
        'section',
        ['showing', 'visible'],
        children=[selected_value, selected_combo],
        text='\ufffc \ufffc',
    )
    selected_form = [{
        **collapsed_form[0],
        'atspi_obj': selected_combo,
    }]
    selected_public, selected_bindings = project_form_surface(
        provider_spec,
        action_spec,
        route,
        selected_form,
        Rect(0, 100, 1000, 700),
        secret,
    )
    selected_surface = greenhouse.BoundSurface(
        selected_public,
        selected_bindings,
        firefox,
        document,
        route,
    )
    selected_option = exact.public['controls'][0]
    selected_action = {
        'kind': 'select_option',
        'revision': exact.public['revision'],
        'ref': selected_option['ref'],
        'combo_ref': origin_ref,
        'expected_option_name': selected_option['name'],
    }
    selected_request = {
        'application_identity_sha256': route.application_identity_sha256,
        'action': selected_action,
    }

    if greenhouse._selected_option_matches(selected_surface, selected_action):
        raise RuntimeError('r17 unchanged Country plus ambiguous +1 sibling passed')
    selected_public['controls'][0]['semantic_values'] = [selected_option['name']]

    with (
        mock.patch.object(
            greenhouse,
            '_resolve_option_source',
            return_value=(
                exact,
                exact.bindings[selected_option['ref']],
                (),
            ),
        ),
        mock.patch.object(greenhouse, 'atspi_click', return_value=True),
        mock.patch.object(greenhouse, '_capture_form', return_value=selected_surface),
        mock.patch.object(greenhouse.time, 'sleep', return_value=None),
    ):
        selected_result, selected_mutation_started = greenhouse._perform_action(
            selected_request,
            provider_spec,
            action_spec,
            secret,
        )
        if (
            selected_mutation_started is not True
            or selected_result['mutation_count'] != 1
            or selected_result['next_mutation_authorized'] is not True
            or selected_result['surface'] != selected_public
            or len(selected_result['postcondition_samples']) != 2
            or any(
                sample['postcondition_matched'] is not True
                for sample in selected_result['postcondition_samples']
            )
        ):
            raise RuntimeError('exact Country semantic-value postcondition did not pass')

        if not greenhouse._selected_option_matches(
            selected_surface,
            selected_action,
        ):
            raise RuntimeError('existing exact combo semantic-value proof regressed')

    try:
        capture(collapsed_form, option_elements)
    except GreenhouseOneActionError as exc:
        if 'not owned by the activated combo' not in str(exc):
            raise
    else:
        raise RuntimeError('unrelated nonempty options passed a collapsed combo')

    referral_node = _FakeNode(
        'Referral source',
        'combo box',
        [*base_states, 'expanded'],
    )
    referral_form = [{
        **expanded_form[0],
        'name': 'Referral source',
        'atspi_obj': referral_node,
    }]
    referral_public, _ = project_form_surface(
        provider_spec,
        action_spec,
        route,
        referral_form,
        Rect(0, 100, 1000, 700),
        secret,
    )
    referral_ref = referral_public['controls'][0]['ref']
    referral = capture(
        referral_form,
        option_tree(['Employee referral', 'LinkedIn']),
        referral_ref,
    )
    referral_capsule = greenhouse._next_action_surface_capsule(
        referral.public,
        route.application_identity_sha256,
    )
    if any(
        'semantic_token' in item
        for item in [*referral.public['controls'], *referral_capsule['controls']]
    ):
        raise RuntimeError('non-Country option received a semantic token')
    referral_surface = greenhouse.BoundSurface(
        referral_public,
        {referral_ref: referral_form[0]},
        firefox,
        document,
        route,
    )
    if greenhouse._selected_option_matches(
        referral_surface,
        {
            **selected_action,
            'combo_ref': referral_ref,
            'expected_option_name': 'Employee referral',
        },
    ):
        raise RuntimeError('Country parent-section proof leaked to another combo')

    for drifted_name in ('Canada', 'Canada  +1', 'Canada +1234', 'Canada +١'):
        try:
            capture(expanded_form, option_tree([drifted_name]))
        except GreenhouseOneActionError as exc:
            if 'country_calling_code_suffix_v1' not in str(exc):
                raise
        else:
            raise RuntimeError(f'country option drift passed: {drifted_name!r}')

    try:
        capture(expanded_form, option_tree(['Canada +1', 'Canada +7']))
    except GreenhouseOneActionError as exc:
        if 'duplicate semantic tokens' not in str(exc):
            raise
    else:
        raise RuntimeError('duplicate country semantic tokens did not fail loud')

    try:
        capture(expanded_form, option_tree([]))
    except GreenhouseOneActionError as exc:
        if 'cardinality is 0' not in str(exc):
            raise
    else:
        raise RuntimeError('zero country semantic tokens did not fail loud')

    duplicate_option = _FakeNode('Other +2', 'list item', ['showing', 'visible', 'enabled'])
    duplicate_container = _FakeNode(
        '',
        'list box',
        ['showing', 'visible'],
        children=[duplicate_option],
    )
    duplicate_tree = [
        *option_elements,
        {
            'name': '',
            'role': 'list box',
            'states': ['showing'],
            'atspi_obj': duplicate_container,
        },
        {
            'name': 'Other +2',
            'role': 'list item',
            'states': ['showing', 'enabled'],
            'x': 500,
            'y': 240,
            'atspi_obj': duplicate_option,
        },
    ]
    try:
        capture(expanded_form, duplicate_tree)
    except GreenhouseOneActionError as exc:
        if 'cardinality is 2' not in str(exc):
            raise
    else:
        raise RuntimeError('duplicate options containers did not fail loud')

    collapsed_public, _ = project_form_surface(
        provider_spec,
        action_spec,
        route,
        collapsed_form,
        Rect(0, 100, 1000, 700),
        secret,
    )
    multi_public, _ = project_form_surface(
        provider_spec,
        action_spec,
        route,
        [expanded_form[0], referral_form[0]],
        Rect(0, 100, 1000, 700),
        secret,
    )
    request = {
        'application_identity_sha256': route.application_identity_sha256,
        'action': {'kind': 'observe_form'},
    }
    captured_option_refs: list[str] = []

    def observe(
        form_public: dict,
        inherited_surface: greenhouse.BoundSurface | GreenhouseOneActionError | None,
    ) -> tuple[dict, bool]:
        captured_option_refs.clear()
        form_surface = greenhouse.BoundSurface(
            form_public,
            {},
            firefox,
            document,
            route,
        )

        def inherited_capture(
            _provider_spec: object,
            _action_spec: object,
            _secret: bytes,
            combo_ref: str,
        ) -> greenhouse.BoundSurface:
            captured_option_refs.append(combo_ref)
            if isinstance(inherited_surface, GreenhouseOneActionError):
                raise inherited_surface
            if not isinstance(inherited_surface, greenhouse.BoundSurface):
                raise RuntimeError('unexpected inherited options capture')
            return inherited_surface

        with (
            mock.patch.object(greenhouse, '_capture_form', return_value=form_surface),
            mock.patch.object(greenhouse, '_capture_options', side_effect=inherited_capture),
            mock.patch.object(greenhouse.time, 'sleep', return_value=None),
        ):
            return greenhouse._perform_action(
                request,
                provider_spec,
                action_spec,
                secret,
            )

    base_result, base_mutation_started = observe(collapsed_public, None)
    if (
        base_mutation_started
        or set(base_result) != {
            'state',
            'surface',
            'surface_capsule',
            'samples',
            'mutation_count',
            'next_mutation_authorized',
        }
        or base_result['state'] != 'action_ready'
        or base_result['surface'] != collapsed_public
        or base_result['surface']['surface'] != 'form'
        or base_result['surface_capsule'] != greenhouse._next_action_surface_capsule(
            collapsed_public,
            route.application_identity_sha256,
        )
        or base_result['mutation_count'] != 0
        or base_result['next_mutation_authorized'] is not True
        or len(base_result['samples']) != 2
        or {
            sample['refresh_policy']
            for sample in base_result['samples']
        } != {'invalidate_reacquire'}
        or captured_option_refs
    ):
        raise RuntimeError('zero-expanded observe_form behavior changed')

    country_result, country_mutation_started = observe(expanded_public, exact)
    if (
        country_mutation_started
        or country_result['surface'] != exact.public
        or country_result['surface']['origin']['combo_ref'] != origin_ref
        or country_result['surface']['origin']['match_count'] != 1
        or [
            control.get('semantic_token')
            for control in country_result['surface_capsule']['controls']
        ] != ['Canada', 'United States']
        or country_result['mutation_count'] != 0
        or len(country_result['samples']) != 2
        or {
            sample['refresh_policy']
            for sample in country_result['samples']
        } != {'live_reacquire_no_clear'}
        or captured_option_refs != [origin_ref, origin_ref]
    ):
        raise RuntimeError('inherited Country options were not classified exactly')

    referral_result, referral_mutation_started = observe(referral_public, referral)
    if (
        referral_mutation_started
        or referral_result['surface'] != referral.public
        or referral_result['surface']['origin']['combo_ref'] != referral_ref
        or referral_result['surface']['origin']['match_count'] != 1
        or any(
            'semantic_token' in control
            for control in referral_result['surface_capsule']['controls']
        )
        or referral_result['mutation_count'] != 0
        or captured_option_refs != [referral_ref, referral_ref]
    ):
        raise RuntimeError('inherited non-Country options classification changed')

    try:
        observe(multi_public, exact)
    except GreenhouseOneActionError as exc:
        if (
            'inherited expanded combo cardinality is 2' not in str(exc)
            or exc.mutation_started
            or captured_option_refs
        ):
            raise
    else:
        raise RuntimeError('multiple inherited expanded combos did not halt')

    try:
        observe(
            expanded_public,
            GreenhouseOneActionError('inherited exact options are invalid'),
        )
    except GreenhouseOneActionError as exc:
        if (
            str(exc) != 'inherited exact options are invalid'
            or exc.mutation_started
            or captured_option_refs != [origin_ref]
        ):
            raise
    else:
        raise RuntimeError('invalid inherited options did not halt')


def _assert_one_action_static_contract() -> None:
    expected = {
        'observe_form': 0,
        'focus': 1,
        'fill': 1,
        'scroll_combo': 1,
        'open_combo': 1,
        'select_option': 1,
        'activate_choice': 1,
        'open_upload': 1,
        'chooser_location': 1,
        'chooser_select_all': 1,
        'chooser_type_path': 1,
        'chooser_confirm': 1,
        'submit': 1,
    }
    observed = {
        action: len(primitives)
        for action, primitives in MUTATION_PRIMITIVE_BY_ACTION.items()
    }
    if observed != expected:
        raise RuntimeError(f'one-action mutation cardinality changed: {observed}')

    tree = ast.parse(ONE_ACTION_PATH.read_text(encoding='utf-8'))
    perform = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == '_perform_action'
    )

    def dotted_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            owner = dotted_name(node.value)
            return f'{owner}.{node.attr}' if owner else node.attr
        return None

    mutation_calls = {
        primitive
        for primitives in MUTATION_PRIMITIVE_BY_ACTION.values()
        for primitive in primitives
    }

    def canonical_call(node: ast.AST) -> str | None:
        value = dotted_name(node)
        if value is not None and value.startswith('inp.'):
            return f'input.{value.removeprefix("inp.")}'
        return value

    branch_counts: dict[str, list[int]] = {}
    for node in ast.walk(perform):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        compare = node.test
        if (
            not isinstance(compare.left, ast.Name)
            or compare.left.id != 'kind'
            or len(compare.ops) != 1
            or not isinstance(compare.ops[0], ast.Eq)
            or len(compare.comparators) != 1
            or not isinstance(compare.comparators[0], ast.Constant)
            or not isinstance(compare.comparators[0].value, str)
        ):
            continue
        action = compare.comparators[0].value
        body = ast.Module(body=node.body, type_ignores=[])
        count = sum(
            1
            for candidate in ast.walk(body)
            if isinstance(candidate, ast.Call)
            and canonical_call(candidate.func) in mutation_calls
        )
        branch_counts.setdefault(action, []).append(count)
    for action, maximum in expected.items():
        counts = branch_counts.get(action) or []
        if not counts or max(counts) != maximum or any(count > 1 for count in counts):
            raise RuntimeError(
                f'{action} AST mutation cardinality is {counts}; expected maximum {maximum}'
            )

    private_native_imports: list[str] = []
    forbidden_walker_calls: list[int] = []
    forbidden_menu_fallback_calls: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == (
            'consultation_v2.native_dialog_snapshot'
        ):
            private_native_imports.extend(
                alias.name for alias in node.names if alias.name.startswith('_')
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {'get_child_at_index', 'get_child_count'}:
                forbidden_walker_calls.append(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'find_menu_items'
        ):
            forbidden_menu_fallback_calls.append(node.lineno)
    if private_native_imports:
        raise RuntimeError(f'ATS imports private native walker helpers: {private_native_imports}')
    if forbidden_walker_calls:
        raise RuntimeError(f'ATS implements a second native walker at {forbidden_walker_calls}')
    if forbidden_menu_fallback_calls:
        raise RuntimeError(
            f'ATS options use the chat menu fallback at {forbidden_menu_fallback_calls}'
        )

    execute = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == 'execute_frozen_action_fd'
    )
    start_lines = [
        node.lineno
        for node in ast.walk(execute)
        if isinstance(node, ast.Constant) and node.value == 'execution_started'
    ]
    mutation_lines = [
        node.lineno
        for node in ast.walk(execute)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == '_perform_action'
    ]
    if len(start_lines) != 1 or len(mutation_lines) != 1 or start_lines[0] >= mutation_lines[0]:
        raise RuntimeError('durable action-start receipt is not ordered before execution')

    native_tree = ast.parse(NATIVE_PATH.read_text(encoding='utf-8'))
    public_helper = next(
        node for node in native_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == 'build_native_dialog_snapshot_from_contract'
    )
    wrapper = next(
        node for node in native_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == 'build_native_dialog_snapshot'
    )
    for function in (public_helper, wrapper):
        calls = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if '_capture_native_dialog_snapshot' not in calls:
            raise RuntimeError(f'{function.name} does not use the sole shared native walker')


def _assert_native_text_redaction() -> None:
    element = NativeDialogElementRef(
        key='location_entry',
        ref='nd1_' + ('a' * 64),
        name='',
        role='text',
        scope='native_dialog.location',
        path='FIREFOX/0/0',
        states=('showing',),
        text='/private/redacted.pdf',
    )
    snapshot = NativeDialogSnapshot(
        platform='greenhouse',
        revision='b' * 64,
        contract_sha256='c' * 64,
        root_key='dialog_root',
        mapped={'location_entry': (element,)},
        raw_count=1,
    )
    public = _native_public(snapshot)
    projected = public['mapped']['location_entry'][0]
    if 'text' in projected or projected.get('text_length') != len('/private/redacted.pdf'):
        raise RuntimeError('private native chooser text was not redacted from receipts')


def _assert_fd_only_frozen_action_boundary() -> None:
    runner_tree = ast.parse(RUNNER_PATH.read_text(encoding='utf-8'))
    runner_strings = {
        node.value
        for node in ast.walk(runner_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    if '--transaction' in runner_strings:
        raise RuntimeError('Greenhouse runner retained a pathname transaction input')
    if not {
        '--transaction-fd',
        '--expected-transaction-sha256',
    }.issubset(runner_strings):
        raise RuntimeError('Greenhouse runner lost its exact descriptor contract')

    one_action_tree = ast.parse(ONE_ACTION_PATH.read_text(encoding='utf-8'))
    loader = next(
        node for node in one_action_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == '_secure_private_json_fd'
    )
    calls = {
        (
            f'{node.func.value.id}.{node.func.attr}'
            if isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            else node.func.id
            if isinstance(node.func, ast.Name)
            else ''
        )
        for node in ast.walk(loader)
        if isinstance(node, ast.Call)
    }
    if {'open', 'os.open', 'Path', 'Path.open', 'Path.read_text', 'Path.read_bytes'} & calls:
        raise RuntimeError('Greenhouse fd loader retained a pathname reopen')
    if not {'os.fstat', 'os.pread', 'fcntl.fcntl'}.issubset(calls):
        raise RuntimeError('Greenhouse fd loader lost exact inode reads')

    original = {
        'schema': 'ats_greenhouse_frozen_action_v1',
        'provider': 'greenhouse',
        'transaction_id': '00000000-0000-4000-8000-000000000000',
        'action_id': '00000000-0000-4000-8000-000000000001',
        'application_identity_sha256': '1' * 64,
        'expected_prior_event_hash': None,
        'action': {'kind': 'observe_form'},
    }
    replacement = {
        **original,
        'action_id': '00000000-0000-4000-8000-000000000002',
    }
    original_raw = json.dumps(
        original,
        ensure_ascii=True,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    replacement_raw = json.dumps(
        replacement,
        ensure_ascii=True,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    digest = hashlib.sha256(original_raw).hexdigest()
    with tempfile.TemporaryDirectory(prefix='ats-greenhouse-fd-') as temp:
        action_path = Path(temp) / 'action.json'
        replacement_path = Path(temp) / 'replacement.json'
        action_path.write_bytes(original_raw)
        replacement_path.write_bytes(replacement_raw)
        action_path.chmod(0o400)
        replacement_path.chmod(0o400)
        descriptor = os.open(
            action_path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            os.replace(replacement_path, action_path)
            loaded = load_frozen_action_fd(descriptor, digest)
            if loaded['action_id'] != original['action_id']:
                raise RuntimeError('path replacement substituted the held action inode')
            try:
                load_frozen_action_fd(descriptor, 'f' * 64)
            except GreenhouseOneActionError:
                pass
            else:
                raise RuntimeError('Greenhouse fd loader accepted a mismatched digest')
        finally:
            os.close(descriptor)

        action_path.chmod(0o600)
        descriptor = os.open(action_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            try:
                load_frozen_action_fd(
                    descriptor,
                    hashlib.sha256(replacement_raw).hexdigest(),
                )
            except GreenhouseOneActionError:
                pass
            else:
                raise RuntimeError('Greenhouse fd loader accepted a mode-0600 action')
        finally:
            os.close(descriptor)


def main() -> int:
    _assert_one_action_static_contract()
    _assert_greenhouse_surface()
    _assert_combo_owned_options_surface()
    _assert_native_text_redaction()
    _assert_fd_only_frozen_action_boundary()
    _assert_public_native_walker()
    _assert_confirmation_capsule_receipt_order()
    print('ATS_GREENHOUSE_ONE_ACTION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
