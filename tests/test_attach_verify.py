from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_verify_attach_success_uses_file_dialog_close_method(monkeypatch):
    from tools import attach

    monkeypatch.setattr('tools.attach.get_platform_config', lambda platform: {
        'validation': {
            'attach_success': {
                'method': 'file_dialog_close',
            },
        },
    })
    monkeypatch.setattr('tools.attach.atspi.find_firefox', lambda platform: object())
    monkeypatch.setattr('tools.attach._any_file_dialog_open', lambda firefox: '')
    monkeypatch.setattr('tools.attach._scan_elements_for_platform', lambda platform: [
        {'name': 'not visible in real gemini', 'role': 'static'},
    ])

    assert attach._verify_attach_success('gemini') is True


def test_verify_attach_success_file_dialog_close_fails_when_dialog_still_open(monkeypatch):
    from tools import attach

    monkeypatch.setattr('tools.attach.get_platform_config', lambda platform: {
        'validation': {
            'attach_success': {
                'method': 'file_dialog_close',
            },
        },
    })
    monkeypatch.setattr('tools.attach.atspi.find_firefox', lambda platform: object())
    monkeypatch.setattr('tools.attach._any_file_dialog_open', lambda firefox: 'gtk')

    assert attach._verify_attach_success('gemini') is False
