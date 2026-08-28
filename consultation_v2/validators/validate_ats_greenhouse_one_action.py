#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
import sys
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


def _assert_combo_owned_options_surface() -> None:
    provider_spec = load_provider_spec('greenhouse')
    action_spec = load_action_spec()
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
    option_a = _FakeNode('Canada', 'list item', ['showing', 'visible', 'enabled'])
    option_b = _FakeNode('United States', 'list item', ['showing', 'visible', 'enabled'])
    container = _FakeNode(
        '',
        'list box',
        ['showing', 'visible'],
        children=[option_a, option_b],
    )
    option_tree = [
        {'name': '', 'role': 'list box', 'states': ['showing'], 'atspi_obj': container},
        {
            'name': 'Canada',
            'role': 'list item',
            'states': ['showing', 'enabled'],
            'x': 120,
            'y': 240,
            'atspi_obj': option_a,
        },
        {
            'name': 'United States',
            'role': 'list item',
            'states': ['showing', 'enabled'],
            'x': 120,
            'y': 280,
            'atspi_obj': option_b,
        },
    ]
    firefox = _FakeNode('Firefox', 'application', ['enabled'])
    document = _FakeNode('Greenhouse', 'document web', ['showing', 'visible'])

    def capture(form_elements: list[dict], option_elements: list[dict]):
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
            return _capture_options(provider_spec, action_spec, secret, origin_ref)

    exact = capture(expanded_form, option_tree)
    if exact.public['origin']['combo_ref'] != origin_ref:
        raise RuntimeError('options surface lost its exact origin combo ref')
    if exact.public['origin']['form_revision'] != expanded_public['revision']:
        raise RuntimeError('options surface lost its expanded form revision')
    if exact.public['container']['match_count'] != 1:
        raise RuntimeError('options surface did not prove one exact container')
    if [item['name'] for item in exact.public['controls']] != ['Canada', 'United States']:
        raise RuntimeError('options surface did not expose exact container descendants')

    try:
        capture(collapsed_form, option_tree)
    except GreenhouseOneActionError as exc:
        if 'not owned by the activated combo' not in str(exc):
            raise
    else:
        raise RuntimeError('unrelated nonempty options passed a collapsed combo')

    duplicate_option = _FakeNode('Other', 'list item', ['showing', 'visible', 'enabled'])
    duplicate_container = _FakeNode(
        '',
        'list box',
        ['showing', 'visible'],
        children=[duplicate_option],
    )
    duplicate_tree = [
        *option_tree,
        {
            'name': '',
            'role': 'list box',
            'states': ['showing'],
            'atspi_obj': duplicate_container,
        },
        {
            'name': 'Other',
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
        if isinstance(node, ast.FunctionDef) and node.name == 'execute_frozen_action'
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


def main() -> int:
    _assert_one_action_static_contract()
    _assert_greenhouse_surface()
    _assert_combo_owned_options_surface()
    _assert_native_text_redaction()
    _assert_public_native_walker()
    print('ATS_GREENHOUSE_ONE_ACTION_OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
