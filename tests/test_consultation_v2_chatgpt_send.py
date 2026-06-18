from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from consultation_v2.drivers.chatgpt import ChatGPTConsultationDriver
from consultation_v2.types import ConsultationRequest, ElementRef, Snapshot


ROOT = Path(__file__).resolve().parents[1]


def _request(message: str = 'hello world') -> ConsultationRequest:
    return ConsultationRequest(platform='chatgpt', message=message)


def _snapshot(key: str, elements: list[ElementRef]) -> Snapshot:
    return Snapshot('chatgpt', 'https://chatgpt.com/', mapped={key: elements})


def _element(key: str, name: str, role: str, states: list[str]) -> ElementRef:
    return ElementRef(key=key, name=name, role=role, x=100, y=100, states=states)


def _stop_button() -> ElementRef:
    return _element('stop_button', 'Stop answering', 'push button', [])


def _composer_node(states: list[str] | None = None) -> ElementRef:
    return _element('input', 'Chat with ChatGPT', 'entry', states or ['editable'])


def test_chatgpt_send_prompt_refocuses_input_and_submits_with_return() -> None:
    driver = ChatGPTConsultationDriver()
    driver.runtime = MagicMock()
    composer = _composer_node()
    focused_composer = _composer_node(['editable', 'focused'])
    snap = _snapshot('input', [composer])
    focused_snap = _snapshot('input', [focused_composer])
    verify_snap = _snapshot('stop_button', [_stop_button()])
    driver.runtime.snapshot.side_effect = [snap, focused_snap, verify_snap]
    driver.runtime.wait_until.side_effect = lambda predicate, timeout, interval: predicate()
    driver.runtime.current_url.return_value = 'https://example.test/thread'
    driver.runtime.wait_for_url_change.return_value = 'https://example.test/thread'
    driver.runtime.click.return_value = True
    driver.runtime.press = MagicMock()

    result = driver.result(_request())
    result.session_url_before = 'https://example.test/new'

    assert driver.send_prompt(result.request, result) is True
    driver.runtime.click.assert_called_once_with(composer)
    driver.runtime.press.assert_called_once_with('Return')
