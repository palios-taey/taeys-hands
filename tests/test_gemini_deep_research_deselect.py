from consultation_v2.planner import build_selection_plan
from consultation_v2.platforms.gemini.driver import GeminiConsultationDriver
from consultation_v2.types import (
    Choice,
    ConsultationRequest,
    ConsultationResult,
    ElementRef,
    Snapshot,
)


class FakeRuntime:
    def __init__(self, snapshots, calls=None, click_ok=True):
        self._snapshots = list(snapshots)
        self.calls = calls if calls is not None else []
        self.click_ok = click_ok

    def snapshot(self):
        if len(self._snapshots) > 1:
            return self._snapshots.pop(0)
        return self._snapshots[0]

    def wait_until(self, probe, *, timeout, interval):
        last = None
        for _ in range(8):
            last = probe()
            if last:
                return last
        return last

    def click(self, target, strategy=None):
        self.calls.append(f'click:{target.key}:{strategy}')
        return self.click_ok

    def switch(self):
        return True

    def current_url(self):
        return 'https://gemini.google.com/app'

    def navigate(self, _target_url, *, verify_change=False):
        return True


def _deselect_element():
    return ElementRef(
        key='tool_deselect_deep_research',
        name='Deselect Deep research',
        role='push button',
        x=10,
        y=20,
    )


def _snapshot(active=False):
    mapped = {}
    if active:
        mapped['tool_deselect_deep_research'] = [_deselect_element()]
    return Snapshot(
        platform='gemini',
        url='https://gemini.google.com/app',
        mapped=mapped,
        raw_count=1 if active else 0,
    )


def _driver(runtime):
    driver = GeminiConsultationDriver()
    driver.runtime = runtime
    return driver


def _request(**selections):
    return ConsultationRequest(
        platform='gemini',
        message='hello',
        selections={key: Choice(value) for key, value in selections.items()},
    )


def _result(request):
    return ConsultationResult(platform='gemini', request=request)


def test_non_deep_research_setup_deselects_deep_research_before_send(monkeypatch):
    calls = []
    runtime = FakeRuntime([_snapshot(), _snapshot(active=True), _snapshot()], calls)
    driver = _driver(runtime)
    request = _request(model='pro')
    result = _result(request)

    monkeypatch.setattr(driver, 'wait_for_page_ready_after_navigation', lambda _result: True)
    monkeypatch.setattr(driver, 'attach_files', lambda _request, _result: calls.append('attach') or True)
    monkeypatch.setattr(driver, 'enter_prompt', lambda _request, _result: calls.append('prompt') or True)
    monkeypatch.setattr(driver, 'guarded_send', lambda _request, _result: calls.append('send') or True)

    def apply_selection_plan(request_arg, _result):
        driver._current_selection_plan = build_selection_plan(request_arg)
        calls.append('select')
        return True

    monkeypatch.setattr(driver, 'apply_selection_plan', apply_selection_plan)

    assert driver.setup_and_send(request, result) is True

    assert driver._resolved_mode_label(request) == 'none'
    assert calls == [
        'select',
        'attach',
        'prompt',
        'click:tool_deselect_deep_research:atspi_first',
        'send',
    ]
    step = result.steps[-1]
    assert step.step == 'deep_research_deselect'
    assert step.success is True
    assert step.evidence['active_before'] is True
    assert step.evidence['active_after'] is False


def test_non_deep_research_fails_closed_when_deselect_does_not_clear():
    runtime = FakeRuntime([_snapshot(active=True), _snapshot(active=True)])
    driver = _driver(runtime)
    request = _request(model='thinking')
    driver._current_selection_plan = build_selection_plan(request)
    result = _result(request)

    assert driver._ensure_non_deep_research_tool_state(request, result) is False

    assert runtime.calls == ['click:tool_deselect_deep_research:atspi_first']
    step = result.steps[-1]
    assert step.step == 'deep_research_deselect'
    assert step.success is False
    assert step.evidence['active_before'] is True
    assert step.evidence['active_after'] is True


def test_deep_research_mode_keeps_deep_research_selected():
    runtime = FakeRuntime([_snapshot(active=True)])
    driver = _driver(runtime)
    request = _request(model='pro', mode='deep_research')
    driver._current_selection_plan = build_selection_plan(request)
    result = _result(request)

    assert driver._resolved_mode_label(request) == 'deep_research'
    assert driver._ensure_non_deep_research_tool_state(request, result) is True

    assert runtime.calls == []
    assert result.steps == []
