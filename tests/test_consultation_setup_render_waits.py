from consultation_v2.platforms.claude.driver import ClaudeConsultationDriver
from consultation_v2.platforms.gemini.driver import GeminiConsultationDriver
from consultation_v2.platforms.grok.driver import GrokConsultationDriver
from consultation_v2.platforms.perplexity.driver import PerplexityConsultationDriver
from consultation_v2.types import ElementRef, Snapshot


OBSERVED_FAILED_SCAN_SECONDS = 32.0


class RecordingResult:
    def __init__(self):
        self.steps = []

    def add_step(self, *args, **kwargs):
        self.steps.append((args, kwargs))


class ActiveTriggerRuntime:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.calls = []

    def wait_for_stable_snapshot(self, **kwargs):
        self.calls.append(kwargs)
        return self._snapshot

    def snapshot(self):
        return self._snapshot


def _driver(driver_class, cfg):
    driver = object.__new__(driver_class)
    driver.cfg = cfg
    return driver


def _empty_snapshot(platform='perplexity'):
    return Snapshot(platform=platform, url='https://example.test/', mapped={}, raw_count=0)


def _active_trigger_snapshot(platform):
    return Snapshot(
        platform=platform,
        url='https://example.test/',
        mapped={
            'model_menu': [
                ElementRef(
                    key='model_menu',
                    name='Selected render-ready model',
                    role='button',
                    x=100,
                    y=100,
                )
            ]
        },
        raw_count=200,
    )


def test_grok_selection_scan_waits_for_render_beyond_observed_loaded_latency():
    driver = _driver(GrokConsultationDriver, {'settle': {'selection_ms': 8000}})

    assert driver._selection_render_wait_timeout_seconds() == 48.0
    assert driver._selection_render_wait_timeout_seconds() > OBSERVED_FAILED_SCAN_SECONDS
    assert driver._setup_step_timeout_seconds('mode-select') == 60.0
    assert driver._setup_step_timeout_seconds('mode-select') > OBSERVED_FAILED_SCAN_SECONDS


def test_claude_hover_submenu_uses_render_wait_instead_of_effort_constant():
    driver = _driver(
        ClaudeConsultationDriver,
        {'settle': {'default_ms': 1500, 'effort_menu_reveal_ms': 20000}},
    )

    assert driver._selection_hover_revealed_anchor_timeout_seconds('effort_high_default') == 45.0
    assert driver._selection_hover_revealed_anchor_timeout_seconds('effort_high_default') > 20.0
    assert driver._selection_hover_revealed_anchor_timeout_seconds('some_future_hover_key') == 45.0


def test_post_select_active_trigger_validation_uses_render_wait():
    for driver_class, platform in (
        (ClaudeConsultationDriver, 'claude'),
        (GeminiConsultationDriver, 'gemini'),
    ):
        driver = _driver(driver_class, {'settle': {'selection_ms': 8000}})
        driver.runtime = ActiveTriggerRuntime(_active_trigger_snapshot(platform))
        render_wait_calls = []

        def render_wait():
            render_wait_calls.append(platform)
            return 48.0

        driver._selection_render_wait_timeout_seconds = render_wait

        snapshot, present, active_name = driver._selection_wait_for_active_trigger(
            'model_menu',
            ('Selected render-ready model',),
        )

        assert snapshot.platform == platform
        assert present is True
        assert active_name == 'Selected render-ready model'
        assert render_wait_calls == [platform]
        assert driver.runtime.calls[0]['anchor_key'] == 'model_menu'
        assert driver.runtime.calls[0]['timeout'] == 0.8

        driver.runtime.calls.clear()
        render_wait_calls.clear()

        snapshot, present, active_name = driver._selection_wait_for_active_trigger(
            'model_menu',
            ('Selected render-ready model',),
            timeout=0.8,
        )

        assert snapshot.platform == platform
        assert present is True
        assert active_name == 'Selected render-ready model'
        assert render_wait_calls == []


def test_perplexity_prompt_ready_uses_render_wait_for_input_key():
    driver = _driver(
        PerplexityConsultationDriver,
        {
            'settle': {'default_ms': 8000},
            'workflow': {'prompt': {'input': 'input'}},
        },
    )
    calls = []

    def wait_for_key(key, *, timeout, interval):
        calls.append({'key': key, 'timeout': timeout, 'interval': interval})
        return _empty_snapshot(), None

    driver.wait_for_key = wait_for_key
    result = RecordingResult()

    assert driver._wait_for_prompt_ready(result) is False
    assert calls == [{'key': 'input', 'timeout': 48.0, 'interval': 0.4}]
    assert result.steps[-1][0][0] == 'prompt_ready'
    assert result.steps[-1][0][1] is False
