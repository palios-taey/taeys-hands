from __future__ import annotations

from unittest.mock import MagicMock

from consultation_v2.drivers.claude import ClaudeConsultationDriver
from consultation_v2.types import ConsultationRequest


def _request(message: str = 'hello world') -> ConsultationRequest:
    return ConsultationRequest(platform='claude', message=message)


def _snapshot() -> MagicMock:
    snap = MagicMock()
    snap.serializable.return_value = {'ok': True}
    return snap


def test_claude_enter_prompt_falls_back_to_type_text_when_paste_lands_zero_chars() -> None:
    driver = ClaudeConsultationDriver()
    driver.runtime = MagicMock()
    driver.find_first = MagicMock()
    driver.validation_passes = MagicMock(side_effect=[True, True])
    driver._prompt_text_status = MagicMock(side_effect=[(0, False), (11, True)])

    input_el = MagicMock()
    initial_snap = _snapshot()
    verify_snap = _snapshot()
    fallback_snap = _snapshot()
    driver.runtime.snapshot.side_effect = [initial_snap, verify_snap, fallback_snap]
    driver.find_first.return_value = input_el
    driver.runtime.click.return_value = True
    driver.runtime.paste.return_value = True
    driver.runtime.type_text.return_value = True

    result = driver.result(_request('hello world'))

    assert driver.enter_prompt(result.request, result) is True
    driver.runtime.type_text.assert_called_once_with('hello world', delay_ms=5)
    assert result.steps[-1].message == 'Claude prompt entered via type_text fallback'
    assert result.steps[-1].evidence['landed_chars'] == 11
