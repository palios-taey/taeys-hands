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


def _send_button() -> ElementRef:
    return _element('send_button', 'Send prompt', 'push button', [])


def _composer_node(states: list[str] | None = None) -> ElementRef:
    return _element('input', 'Chat with ChatGPT', 'entry', states or ['editable'])


def _poll_until(predicate, timeout, interval):
    for _ in range(8):
        value = predicate()
        if value:
            return value
    return value


def test_chatgpt_send_prompt_refocuses_input_and_submits_with_return() -> None:
    driver = ChatGPTConsultationDriver()
    driver.runtime = MagicMock()
    composer = _composer_node()
    focused_composer = _composer_node(['editable', 'focused'])
    snap = _snapshot('input', [composer])
    focused_snap = _snapshot('input', [focused_composer])
    verify_snap = _snapshot('stop_button', [_stop_button()])
    driver.runtime.snapshot.side_effect = [snap, focused_snap, focused_snap, verify_snap]
    driver.runtime.wait_until.side_effect = _poll_until
    driver.runtime.current_url.return_value = 'https://chatgpt.com/c/thread'
    driver.runtime.wait_for_url_change.return_value = 'https://chatgpt.com/c/thread'
    driver.runtime.click.return_value = True
    driver.runtime.press = MagicMock()

    result = driver.result(_request())
    result.session_url_before = 'https://example.test/new'

    assert driver.send_prompt(result.request, result) is True
    driver.runtime.click.assert_called_once_with(composer)
    driver.runtime.press.assert_called_once_with('Return')
    assert result.session_url_after == 'https://chatgpt.com/c/thread'


def test_chatgpt_send_prompt_reclicks_input_when_first_enter_leaves_prompt_staged() -> None:
    driver = ChatGPTConsultationDriver()
    driver.runtime = MagicMock()
    composer = _composer_node()
    focused_composer = _composer_node(['editable', 'focused'])
    input_snap = _snapshot('input', [composer])
    focused_snap = _snapshot('input', [focused_composer])
    no_stop_snap = Snapshot('chatgpt', 'https://chatgpt.com/', mapped={})
    prompt_staged_snap = _snapshot('send_button', [_send_button()])
    stop_snap = _snapshot('stop_button', [_stop_button()])
    driver.runtime.snapshot.side_effect = [
        input_snap,
        focused_snap,
        focused_snap,
        prompt_staged_snap,
        input_snap,
        focused_snap,
        focused_snap,
    ]
    driver.wait_for_validation = MagicMock(side_effect=[no_stop_snap, stop_snap])
    driver.runtime.wait_until.side_effect = _poll_until
    driver._wait_for_answer_thread_url = MagicMock(side_effect=[
        None,
        'https://chatgpt.com/c/thread',
    ])
    driver.runtime.current_url.return_value = 'https://chatgpt.com/'
    driver.runtime.wait_for_url_change.side_effect = [
        'https://chatgpt.com/',
        'https://chatgpt.com/',
    ]
    driver.runtime.click.return_value = True
    driver.runtime.press = MagicMock(return_value=True)

    result = driver.result(_request())
    result.session_url_before = 'https://example.test/new'

    assert driver.send_prompt(result.request, result) is True
    assert driver.runtime.click.call_count == 2
    assert driver.runtime.press.call_count == 2
    attempts = result.steps[-1].evidence['attempts']
    assert attempts[0]['prompt_still_staged'] is True
    assert attempts[1]['stop_seen'] is True
    assert attempts[1]['answer_thread'] is True
    assert result.session_url_after == 'https://chatgpt.com/c/thread'


def test_chatgpt_send_prompt_waits_for_answer_thread_url_after_stop() -> None:
    driver = ChatGPTConsultationDriver()
    driver.runtime = MagicMock()
    composer = _composer_node()
    focused_composer = _composer_node(['editable', 'focused'])
    snap = _snapshot('input', [composer])
    focused_snap = _snapshot('input', [focused_composer])
    verify_snap = _snapshot('stop_button', [_stop_button()])
    driver.runtime.snapshot.side_effect = [snap, focused_snap, focused_snap, verify_snap]
    driver.runtime.wait_until.side_effect = _poll_until
    driver.runtime.current_url.return_value = 'https://chatgpt.com/c/thread'
    driver.runtime.wait_for_url_change.return_value = 'https://chatgpt.com/'
    driver.runtime.click.return_value = True
    driver.runtime.press = MagicMock(return_value=True)

    result = driver.result(_request())
    result.session_url_before = 'https://old.example/thread'

    assert driver.send_prompt(result.request, result) is True
    assert result.session_url_after == 'https://chatgpt.com/c/thread'
    driver.runtime.wait_for_url_change.assert_not_called()
    attempts = result.steps[-1].evidence['attempts']
    assert attempts[-1]['answer_thread'] is True


def test_chatgpt_answer_thread_reassert_adopts_current_thread_when_capture_is_home() -> None:
    driver = ChatGPTConsultationDriver.__new__(ChatGPTConsultationDriver)
    driver.runtime = MagicMock()
    driver.runtime.current_url.return_value = 'https://chatgpt.com/c/live-thread'
    request = ConsultationRequest(platform='chatgpt', message='hello')
    result = driver.result(request)
    result.session_url_after = 'https://chatgpt.com/'

    assert driver.reassert_captured_session_url(
        result,
        answer_url_predicate=driver._is_answer_thread_url,
    ) is True
    assert result.session_url_after == 'https://chatgpt.com/c/live-thread'
    assert result.steps[-1].step == 'answer_thread'
    assert result.steps[-1].success is True
    assert result.steps[-1].evidence['adopted_current'] is True
