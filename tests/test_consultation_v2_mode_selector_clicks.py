from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call

from consultation_v2.drivers.claude import ClaudeConsultationDriver
from consultation_v2.drivers.gemini import GeminiConsultationDriver
from consultation_v2.drivers.perplexity import PerplexityConsultationDriver
from consultation_v2.types import ConsultationRequest, ElementRef, Snapshot


def _request(platform: str, mode: str, model: str | None = None) -> ConsultationRequest:
    return ConsultationRequest(platform=platform, message='hello', mode=mode, model=model)


def _snapshot() -> MagicMock:
    snap = MagicMock()
    snap.serializable.return_value = {'ok': True}
    return snap


def test_perplexity_deep_research_uses_search_toggle_dropdown_and_pill_verify() -> None:
    driver = PerplexityConsultationDriver()
    driver.runtime = MagicMock()
    initial_snap = Snapshot('perplexity', 'https://www.perplexity.ai/')
    doc_probe_missing = Snapshot('perplexity', 'https://www.perplexity.ai/')
    verify_snap = Snapshot('perplexity', 'https://www.perplexity.ai/')
    driver.runtime.snapshot.side_effect = [initial_snap, doc_probe_missing, verify_snap]

    trigger = MagicMock()
    trigger.states = []
    trigger.serializable.return_value = {'name': 'search_mode_trigger'}

    atspi_obj = MagicMock()
    item = ElementRef(
        key='deep_research',
        name='Deep research',
        role='toggle button',
        x=100,
        y=100,
        states=[],
        atspi_obj=atspi_obj,
    )

    menu_snap_missing = Snapshot('perplexity', 'https://www.perplexity.ai/')
    menu_snap_found = Snapshot(
        'perplexity',
        'https://www.perplexity.ai/',
        mapped={'deep_research': [item]},
    )
    menu_snap_closed = Snapshot('perplexity', 'https://www.perplexity.ai/')

    def find_first(snapshot, key):
        if key == 'search_mode_trigger':
            return trigger
        return snapshot.first(key)

    driver.find_first = MagicMock(side_effect=find_first)
    menu_iter = iter([menu_snap_missing, menu_snap_found, menu_snap_closed])
    driver.runtime.menu_snapshot.side_effect = lambda: next(menu_iter)

    wait_calls = []

    def wait_until(predicate, timeout, interval):
        wait_calls.append((timeout, interval))
        if len(wait_calls) == 1:
            assert predicate() is None
        return predicate()

    driver.runtime.wait_until.side_effect = wait_until
    driver.runtime.click.return_value = True

    def validation(snapshot, key, filename=None):
        return snapshot is verify_snap and key == 'deep_research_active'

    driver.validation_passes = MagicMock(side_effect=validation)
    result = driver.result(_request('perplexity', 'deep_research'))

    assert driver._select_mode_via_search_toggle(
        'deep_research',
        'deep_research_active',
        driver.cfg['workflow']['selection'],
        result,
    ) is True

    assert driver.runtime.click.call_args_list == [
        call(trigger, strategy='coordinate_only'),
        call(item, strategy='atspi_only'),
    ]
    assert result.steps[-1].success is True
    assert result.steps[-1].step == 'select_mode'
    assert result.steps[-1].evidence['activation_attempts'] == [
        {
            'strategy': 'atspi_only',
            'clicked': True,
            'validated': True,
            'menu_open_after': False,
        },
    ]


def test_perplexity_prompt_ready_gates_on_input_entry_not_submit_button() -> None:
    driver = PerplexityConsultationDriver()
    driver.runtime = MagicMock()
    ready_snap = _snapshot()
    driver.runtime.snapshot.side_effect = [ready_snap]
    driver.validation_passes = MagicMock(side_effect=lambda snapshot, key, filename=None: snapshot is ready_snap and key == 'prompt_ready')
    result = driver.result(_request('perplexity', 'deep_research'))

    assert driver._wait_for_prompt_ready(result) is True
    driver.validation_passes.assert_called_once_with(ready_snap, 'prompt_ready')
    assert result.steps[-1].step == 'prompt_ready'
    assert result.steps[-1].success is True


def test_gemini_deep_think_verifies_active_pill_from_document_snapshot() -> None:
    driver = GeminiConsultationDriver()
    driver.runtime = MagicMock()
    initial_model_snap = _snapshot()
    verify_model_root = _snapshot()
    model_evidence_snap = _snapshot()
    mode_snap = _snapshot()
    menu_snap = _snapshot()
    verify_snap = _snapshot()
    driver.runtime.snapshot.side_effect = [
        initial_model_snap,
        verify_model_root,
        model_evidence_snap,
        mode_snap,
        verify_snap,
    ]

    mode_picker = MagicMock()
    tools_button = MagicMock()
    tools_button.serializable.return_value = {'name': 'tools'}
    model_item = MagicMock()
    model_item.serializable.return_value = {'name': 'Pro'}
    item = MagicMock()
    item.serializable.return_value = {'name': 'Deep think'}

    def find_first(snapshot, key):
        mapping = {
            'mode_picker': mode_picker,
            'mode_pro': model_item,
            'tools_button': tools_button,
            'tool_deep_think': item,
            'more_tools': None,
        }
        return mapping.get(key)

    driver.find_first = MagicMock(side_effect=find_first)
    driver.runtime.click.return_value = True
    driver.runtime.menu_snapshot.return_value = menu_snap

    def wait_until(predicate, timeout, interval):
        return predicate()

    driver.runtime.wait_until.side_effect = wait_until

    def validation(snapshot, key, filename=None):
        if snapshot is menu_snap and key == 'pro_active':
            return True
        if snapshot is mode_snap and key == 'deep_think_active':
            return False
        return snapshot is verify_snap and key == 'deep_think_active'

    driver.validation_passes = MagicMock(side_effect=validation)
    result = driver.result(_request('gemini', 'deep_think'))

    assert driver.select_model_mode_tools(result.request, result) is True
    assert driver.runtime.menu_snapshot.call_count == 3
    assert result.steps[-1].success is True
    assert result.steps[-1].step == 'select_mode'


def test_claude_extended_thinking_hovers_effort_menu_and_selects_extra() -> None:
    driver = ClaudeConsultationDriver()
    driver.runtime = MagicMock()
    initial_snap = _snapshot()
    ready_snap = _snapshot()
    open_snap = _snapshot()
    effort_open_snap = _snapshot()
    menu_snap = _snapshot()
    submenu_snap = _snapshot()
    verify_snap = _snapshot()
    driver.runtime.snapshot.side_effect = [
        initial_snap,
        ready_snap,
        open_snap,
        effort_open_snap,
        verify_snap,
    ]
    menu_snap.has.side_effect = lambda key: key in {'model_opus', 'effort_menu'}
    submenu_snap.has.side_effect = lambda key: key == 'effort_extra'
    driver.runtime.menu_snapshot.side_effect = [menu_snap, submenu_snap]

    selector = MagicMock()
    item = MagicMock()
    effort_menu = MagicMock()
    extra = MagicMock()
    driver._find_claude_model_selector = MagicMock(return_value=selector)
    driver.find_first = MagicMock(side_effect=lambda snapshot, key: {
        'model_opus': item,
        'effort_menu': effort_menu,
        'effort_extra': extra,
    }.get(key))
    driver.runtime.click.side_effect = [True, True, True, True]
    driver.runtime.hover.return_value = True
    driver.runtime.press.return_value = True
    driver.runtime.menu_snapshot.side_effect = [menu_snap, menu_snap, submenu_snap, submenu_snap]

    def wait_until(predicate, timeout, interval):
        return predicate()

    driver.runtime.wait_until.side_effect = wait_until

    def validation(snapshot, key, filename=None):
        return snapshot is verify_snap and key == 'extended_thinking_active'

    driver.validation_passes = MagicMock(side_effect=validation)
    result = driver.result(_request('claude', 'extended_thinking'))

    assert driver.select_model_mode_tools(result.request, result) is True
    driver.runtime.hover.assert_called_once_with(effort_menu)
    assert driver.runtime.click.call_count == 4
    assert result.steps[-1].success is True
    assert result.steps[-1].step == 'select_mode'


def test_claude_model_selector_helper_prefers_rightmost_composer_button() -> None:
    driver = ClaudeConsultationDriver()
    toggle_menu = SimpleNamespace(name='Add files, connectors, and more', role='push button', x=681, y=570)
    left_button = SimpleNamespace(name='Left', role='push button', x=900, y=570)
    right_button = SimpleNamespace(name='Right', role='push button', x=1163, y=570)
    snap = MagicMock()
    snap.mapped = {
        'toggle_menu': [toggle_menu],
        'left_button': [left_button],
        'right_button': [right_button],
    }
    driver.find_first = MagicMock(side_effect=lambda snapshot, key: toggle_menu if key == 'toggle_menu' else None)

    selector = driver._find_claude_model_selector(snap)

    assert selector is right_button
