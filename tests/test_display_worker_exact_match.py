from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import patch


def _load_display_worker():
    sys.modules.pop('workers.display_worker', None)
    sys.argv = ['display_worker.py', ':2', 'chatgpt']

    fake_run = SimpleNamespace(returncode=1, stdout='', stderr='xprop unavailable')
    with patch('subprocess.run', return_value=fake_run):
        return importlib.import_module('workers.display_worker')


def test_display_worker_spec_matches_names_any_of_exactly():
    worker = _load_display_worker()

    assert worker._spec_matches(
        {'name': 'Stop answering', 'role': 'push button', 'states': set()},
        {'names_any_of': ['Stop answering', 'Stop response'], 'role': 'push button'},
    ) is True
    assert worker._spec_matches(
        {'name': 'Stop answering now', 'role': 'push button', 'states': set()},
        {'names_any_of': ['Stop answering', 'Stop response'], 'role': 'push button'},
    ) is False
    assert worker._spec_matches(
        {'name': 'Stop response', 'role': 'push button', 'states': set()},
        {'name_contains': 'Stop response', 'role': 'push button'},
    ) is False


def test_display_worker_check_stop_button_uses_exact_alternatives(monkeypatch):
    worker = _load_display_worker()

    monkeypatch.setattr('core.atspi.find_firefox_for_platform', lambda platform: object())
    monkeypatch.setattr('core.atspi.get_platform_document', lambda firefox, platform: object())
    monkeypatch.setattr('core.config.get_platform_config', lambda platform: {
        'element_map': {
            'stop_button': {
                'names_any_of': ['Stop answering', 'Stop response'],
                'role': 'push button',
            },
        },
    })

    def _fake_scan_named_elements(_doc, elements, depth=0):
        elements.extend([
            {'name': 'Stop answering', 'role': 'push button', 'states': set()},
            {'name': 'Copy', 'role': 'push button', 'states': set()},
        ])

    monkeypatch.setattr(worker, '_scan_named_elements', _fake_scan_named_elements)

    result = worker._check_stop_button()

    assert result == {'stop_found': True, 'platform': 'chatgpt'}


def test_display_worker_reassert_worker_env_removes_platform_routing(monkeypatch):
    worker = _load_display_worker()

    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.setenv('PLATFORM_DISPLAYS', 'chatgpt:2,claude:3')
    monkeypatch.setenv('AT_SPI_BUS_ADDRESS', 'stale-bus')
    monkeypatch.setenv('DBUS_SESSION_BUS_ADDRESS', 'stale-dbus')
    monkeypatch.setattr(worker, '_read_isolated_bus', lambda display, bus_file: 'unix:path=/tmp/fresh-bus')

    worker._reassert_worker_env()

    assert worker.os.environ['DISPLAY'] == ':2'
    assert worker.os.environ['GTK_USE_PORTAL'] == '0'
    assert worker.os.environ['AT_SPI_BUS_ADDRESS'] == 'unix:path=/tmp/fresh-bus'
    assert worker.os.environ['DBUS_SESSION_BUS_ADDRESS'] == 'unix:path=/tmp/fresh-bus'
    assert 'PLATFORM_DISPLAYS' not in worker.os.environ
    assert worker._PLATFORM_DISPLAYS == {}


def test_display_worker_check_stop_button_falls_back_to_local_firefox(monkeypatch):
    worker = _load_display_worker()

    monkeypatch.setattr(worker, '_reassert_worker_env', lambda: None)
    monkeypatch.setattr('core.atspi.find_firefox_for_platform', lambda platform: None)
    monkeypatch.setattr('core.atspi.find_firefox', lambda platform=None: object())
    monkeypatch.setattr('core.atspi.get_platform_document', lambda firefox, platform: object())
    monkeypatch.setattr('core.config.get_platform_config', lambda platform: {
        'element_map': {
            'stop_button': {
                'name': 'Stop response',
                'role': 'push button',
            },
        },
    })
    monkeypatch.setattr(worker, '_scan_named_elements', lambda _doc, elements, depth=0: elements.extend([
        {'name': 'Stop response', 'role': 'push button', 'states': set()},
    ]))

    result = worker._check_stop_button()

    assert result == {'stop_found': True, 'platform': 'chatgpt'}
