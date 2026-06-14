from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from consultation_v2.drivers.chatgpt import ChatGPTConsultationDriver
from consultation_v2.types import ConsultationRequest


ROOT = Path(__file__).resolve().parents[1]


def _request(message: str = 'hello world') -> ConsultationRequest:
    return ConsultationRequest(platform='chatgpt', message=message)


def _snapshot() -> MagicMock:
    snap = MagicMock()
    snap.serializable.return_value = {'ok': True}
    return snap


def test_chatgpt_send_prompt_refocuses_input_and_submits_with_return() -> None:
    driver = ChatGPTConsultationDriver()
    driver.runtime = MagicMock()
    snap = _snapshot()
    verify_snap = _snapshot()
    driver.runtime.snapshot.side_effect = [snap, verify_snap]
    driver.runtime.wait_until.return_value = True
    driver.runtime.current_url.return_value = 'https://example.test/thread'
    driver.runtime.click.return_value = True
    driver.runtime.press = MagicMock()

    input_el = MagicMock()

    def _find_first(snapshot, key):  # noqa: ANN001
        if key == 'input':
            return input_el
        if key == 'send_button':
            raise AssertionError('send_button lookup is forbidden in ChatGPT send_prompt')
        return None

    driver.find_first = MagicMock(side_effect=_find_first)
    driver._click = MagicMock(return_value=True)

    result = driver.result(_request())
    result.session_url_before = 'https://example.test/new'

    assert driver.send_prompt(result.request, result) is True
    driver.find_first.assert_called_once_with(snap, 'input')
    driver._click.assert_called_once_with(input_el)
    driver.runtime.press.assert_called_once_with('Return')
    driver.runtime.click.assert_not_called()
