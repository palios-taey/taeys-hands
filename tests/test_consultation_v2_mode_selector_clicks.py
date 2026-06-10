from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from consultation_v2.drivers.gemini import GeminiConsultationDriver
from consultation_v2.drivers.perplexity import PerplexityConsultationDriver
from consultation_v2.types import ConsultationRequest


def _request(platform: str, mode: str) -> ConsultationRequest:
    return ConsultationRequest(platform=platform, message='hello', mode=mode)


def _snapshot() -> MagicMock:
    snap = MagicMock()
    snap.serializable.return_value = {'ok': True}
    return snap


def test_perplexity_deep_research_uses_menu_item_pointer_click_and_pill_verify() -> None:
    driver = PerplexityConsultationDriver()
    driver.runtime = MagicMock()
    initial_snap = _snapshot()
    menu_snap_missing = _snapshot()
    menu_snap_missing.first.return_value = None
    menu_snap_found = _snapshot()
    verify_snap = _snapshot()
    driver.runtime.snapshot.side_effect = [initial_snap, verify_snap]

    trigger = MagicMock()
    trigger.states = []
    trigger.serializable.return_value = {'name': 'attach'}
    driver.find_first = MagicMock(side_effect=[trigger, None, None])

    extents = SimpleNamespace(x=100, y=200, width=40, height=20)
    component = MagicMock()
    component.get_extents.return_value = extents
    atspi_obj = MagicMock()
    atspi_obj.get_component_iface.return_value = component
    item = SimpleNamespace(atspi_obj=atspi_obj, states=[])

    menu_snap_found.first.side_effect = lambda key: item if key == 'deep_research' else None

    menu_iter = iter([menu_snap_missing, menu_snap_found])
    driver.runtime.menu_snapshot.side_effect = lambda: next(menu_iter)
    driver.runtime.wait_until.side_effect = [
        (menu_snap_found, item),
        verify_snap,
    ]
    driver.runtime.click.return_value = True

    def validation(snapshot, key, filename=None):
        return snapshot is verify_snap and key == 'deep_research_active'

    driver.validation_passes = MagicMock(side_effect=validation)
    result = driver.result(_request('perplexity', 'deep_research'))

    with patch('consultation_v2.drivers.perplexity.inp.click_at', return_value=True) as click_at:
        assert driver._select_mode_direct('deep_research', 'deep_research_active', driver.cfg['workflow']['selection'], result) is True

    click_at.assert_called_once_with(120, 210)
    assert result.steps[-1].success is True
    assert result.steps[-1].step == 'select_mode'


def test_gemini_deep_think_verifies_active_pill_from_document_snapshot() -> None:
    driver = GeminiConsultationDriver()
    driver.runtime = MagicMock()
    initial_snap = _snapshot()
    menu_snap = _snapshot()
    verify_snap = _snapshot()
    driver.runtime.snapshot.side_effect = [initial_snap, verify_snap, verify_snap]

    tools_button = MagicMock()
    tools_button.serializable.return_value = {'name': 'tools'}
    item = MagicMock()
    item.serializable.return_value = {'name': 'Deep think'}

    def find_first(snapshot, key):
        mapping = {
            'tools_button': tools_button,
            'tool_deep_think': item,
            'more_tools': None,
        }
        return mapping.get(key)

    driver.find_first = MagicMock(side_effect=find_first)
    driver.runtime.click.return_value = True
    driver.runtime.menu_snapshot.return_value = menu_snap

    def wait_until(predicate, timeout, interval):
        return verify_snap

    driver.runtime.wait_until.side_effect = wait_until

    def validation(snapshot, key, filename=None):
        if snapshot is initial_snap and key == 'deep_think_active':
            return False
        return snapshot is verify_snap and key == 'deep_think_active'

    driver.validation_passes = MagicMock(side_effect=validation)
    result = driver.result(_request('gemini', 'deep_think'))

    assert driver.select_model_mode_tools(result.request, result) is True
    driver.runtime.menu_snapshot.assert_called_once()
    assert result.steps[-1].success is True
    assert result.steps[-1].step == 'select_mode'
