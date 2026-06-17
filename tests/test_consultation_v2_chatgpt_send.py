from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from consultation_v2.drivers.chatgpt import ChatGPTConsultationDriver
from consultation_v2.types import ConsultationRequest


ROOT = Path(__file__).resolve().parents[1]


def _request(message: str = 'hello world') -> ConsultationRequest:
    return ConsultationRequest(platform='chatgpt', message=message)


def _snapshot(elements: list[object] | None = None) -> MagicMock:
    snap = MagicMock()
    snap.mapped = {'main': list(elements or [])}
    snap.unknown = []
    snap.sidebar = []
    snap.menu_items = []
    snap.serializable.return_value = {'ok': True}
    return snap


def _stop_button() -> dict[str, object]:
    return {'name': 'Stop answering', 'role': 'push button', 'states': []}


def _composer_node() -> SimpleNamespace:
    return SimpleNamespace(role='paragraph', states=['editable'])


def test_chatgpt_send_prompt_refocuses_input_and_submits_with_return() -> None:
    driver = ChatGPTConsultationDriver()
    driver.runtime = MagicMock()
    composer = _composer_node()
    snap = _snapshot([composer])
    verify_snap = _snapshot([_stop_button()])
    driver.runtime.snapshot.side_effect = [snap, verify_snap]
    driver.runtime.wait_until.side_effect = lambda predicate, timeout, interval: predicate()
    driver.runtime.current_url.return_value = 'https://example.test/thread'
    driver.runtime.wait_for_url_change.return_value = 'https://example.test/thread'
    driver.runtime.click.return_value = True
    driver.runtime.press = MagicMock()

    result = driver.result(_request())
    result.session_url_before = 'https://example.test/new'

    assert driver.send_prompt(result.request, result) is True
    driver.runtime.click.assert_called_once_with(composer, strategy='atspi_only')
    driver.runtime.press.assert_called_once_with('Return')
