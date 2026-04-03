from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import core.input as input_mod


class _DummyStateSet:
    def __init__(self, showing):
        self._showing = showing

    def contains(self, _state_type):
        return self._showing


class _DummyDoc:
    def __init__(self, showing):
        self._state_set = _DummyStateSet(showing)

    def get_state_set(self):
        return self._state_set


def _fake_subprocess_run(*args, **kwargs):
    cmd = args[0]
    if cmd[:3] == ['xdotool', 'search', '--pid']:
        return SimpleNamespace(returncode=0, stdout='111\n', stderr='')
    if cmd[:2] == ['xdotool', 'windowactivate']:
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    raise AssertionError(f"Unexpected subprocess command: {cmd}")


def test_switch_to_platform_multidisplay_retargets_tab_when_window_focus_is_wrong():
    fake_gi = MagicMock()
    fake_atspi_enum = SimpleNamespace(StateType=SimpleNamespace(SHOWING=object()))
    wrong_doc = _DummyDoc(showing=False)
    right_doc = _DummyDoc(showing=True)

    with patch.dict(
        'sys.modules',
        {
            'gi': fake_gi,
            'gi.repository': SimpleNamespace(Atspi=fake_atspi_enum),
        },
    ), patch('core.platforms.get_platform_display', return_value=':5'), \
         patch('core.platforms.get_platform_firefox_pid', return_value=123), \
         patch.dict('core.platforms.TAB_SHORTCUTS', {'grok': 'alt+4'}, clear=False), \
         patch.dict('core.platforms.URL_PATTERNS', {'grok': 'grok.com'}, clear=False), \
         patch('core.clipboard.set_display') as clip_set_display, \
         patch('core.atspi.find_firefox_for_platform', return_value=object()), \
         patch('core.atspi.get_platform_document', side_effect=[wrong_doc, right_doc]), \
         patch('core.input.subprocess.run', side_effect=_fake_subprocess_run), \
         patch('core.input.press_key', return_value=True) as press_key:
        assert input_mod.switch_to_platform('grok') is True

    clip_set_display.assert_called_once_with(':5')
    press_key.assert_called_once_with('alt+4')


def test_switch_to_platform_multidisplay_fails_when_tab_cannot_be_verified():
    fake_gi = MagicMock()
    fake_atspi_enum = SimpleNamespace(StateType=SimpleNamespace(SHOWING=object()))
    wrong_doc = _DummyDoc(showing=False)

    with patch.dict(
        'sys.modules',
        {
            'gi': fake_gi,
            'gi.repository': SimpleNamespace(Atspi=fake_atspi_enum),
        },
    ), patch('core.platforms.get_platform_display', return_value=':5'), \
         patch('core.platforms.get_platform_firefox_pid', return_value=123), \
         patch.dict('core.platforms.TAB_SHORTCUTS', {'grok': 'alt+4'}, clear=False), \
         patch.dict('core.platforms.URL_PATTERNS', {'grok': 'grok.com'}, clear=False), \
         patch('core.clipboard.set_display'), \
         patch('core.atspi.find_firefox_for_platform', return_value=object()), \
         patch('core.atspi.get_platform_document', side_effect=[wrong_doc, wrong_doc, wrong_doc]), \
         patch('core.input.subprocess.run', side_effect=_fake_subprocess_run), \
         patch('core.input.press_key', return_value=True) as press_key:
        assert input_mod.switch_to_platform('grok') is False

    press_key.assert_called_once_with('alt+4')
