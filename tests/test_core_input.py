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


class _DummyFirefox:
    def __init__(self, pid):
        self._pid = pid

    def get_process_id(self):
        return self._pid


def _make_subprocess_run(pid_to_wid):
    def _fake_subprocess_run(*args, **kwargs):
        cmd = args[0]
        if cmd[:3] == ['xdotool', 'search', '--pid']:
            pid = int(cmd[3])
            wid = pid_to_wid.get(pid)
            return SimpleNamespace(returncode=0, stdout=(f'{wid}\n' if wid else ''), stderr='')
        if cmd[:2] == ['xdotool', 'windowactivate']:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        raise AssertionError(f"Unexpected subprocess command: {cmd}")

    return _fake_subprocess_run


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
         patch('core.input.subprocess.run', side_effect=_make_subprocess_run({123: 111})), \
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
         patch('core.input.subprocess.run', side_effect=_make_subprocess_run({123: 111})), \
         patch('core.input.press_key', return_value=True) as press_key:
        assert input_mod.switch_to_platform('grok') is False

    press_key.assert_called_once_with('alt+4')


def test_switch_to_platform_multidisplay_uses_atspi_discovery_when_pidfile_missing():
    fake_gi = MagicMock()
    fake_atspi_enum = SimpleNamespace(StateType=SimpleNamespace(SHOWING=object()))
    right_doc = _DummyDoc(showing=True)
    firefox = _DummyFirefox(pid=456)

    with patch.dict(
        'sys.modules',
        {
            'gi': fake_gi,
            'gi.repository': SimpleNamespace(Atspi=fake_atspi_enum),
        },
    ), patch('core.platforms.get_platform_display', return_value=':5'), \
         patch('core.platforms.get_platform_firefox_pid', return_value=None), \
         patch.dict('core.platforms.TAB_SHORTCUTS', {'grok': 'alt+4'}, clear=False), \
         patch.dict('core.platforms.URL_PATTERNS', {'grok': 'grok.com'}, clear=False), \
         patch('core.clipboard.set_display') as clip_set_display, \
         patch('core.atspi.find_firefox_for_platform', side_effect=lambda platform, pid=None: firefox if pid in (None, 456) else None), \
         patch('core.atspi.get_platform_document', side_effect=lambda ff, platform: right_doc if ff.get_process_id() == 456 else None), \
         patch('core.input.subprocess.run', side_effect=_make_subprocess_run({456: 222})), \
         patch('core.input.press_key') as press_key:
        assert input_mod.switch_to_platform('grok') is True

    clip_set_display.assert_called_once_with(':5')
    press_key.assert_not_called()


def test_switch_to_platform_multidisplay_falls_back_to_atspi_discovery_when_pidfile_is_stale():
    fake_gi = MagicMock()
    fake_atspi_enum = SimpleNamespace(StateType=SimpleNamespace(SHOWING=object()))
    wrong_doc = _DummyDoc(showing=False)
    right_doc = _DummyDoc(showing=True)
    stale_firefox = _DummyFirefox(pid=123)
    discovered_firefox = _DummyFirefox(pid=456)

    def find_firefox(platform, pid=None):
        if pid == 123:
            return stale_firefox
        if pid == 456 or pid is None:
            return discovered_firefox
        return None

    def get_doc(ff, platform):
        return wrong_doc if ff.get_process_id() == 123 else right_doc

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
         patch('core.atspi.find_firefox_for_platform', side_effect=find_firefox), \
         patch('core.atspi.get_platform_document', side_effect=get_doc), \
         patch('core.input.subprocess.run', side_effect=_make_subprocess_run({123: None, 456: 222})), \
         patch('core.input.press_key') as press_key:
        assert input_mod.switch_to_platform('grok') is True

    press_key.assert_not_called()
