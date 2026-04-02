"""Tests for worker-routed mode selection."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_select_mode_with_worker_prefers_ipc(monkeypatch):
    from tools.mode_select import select_mode_with_worker_fallback

    fallback_called = {'value': False}

    def fake_fallback(_platform, mode=None, model=None):
        fallback_called['value'] = True
        return {'success': True, 'selected_mode': mode or model}

    monkeypatch.setattr('tools.mode_select.is_multi_display', lambda: True)
    monkeypatch.setattr(
        'tools.mode_select.send_to_worker',
        lambda platform, cmd, timeout=120.0: {
            'success': True,
            'platform': platform,
            'selected_mode': cmd.get('mode') or cmd.get('model'),
        },
    )

    result = select_mode_with_worker_fallback(
        'perplexity',
        mode='deep_research',
        fallback=fake_fallback,
    )

    assert result['success'] is True
    assert result['selected_mode'] == 'deep_research'
    assert result['route'] == 'worker_ipc'
    assert fallback_called['value'] is False


def test_select_mode_with_worker_falls_back(monkeypatch):
    from tools.mode_select import select_mode_with_worker_fallback

    monkeypatch.setattr('tools.mode_select.is_multi_display', lambda: True)

    def fail_worker(_platform, _cmd, timeout=120.0):
        raise RuntimeError('worker down')

    monkeypatch.setattr('tools.mode_select.send_to_worker', fail_worker)

    result = select_mode_with_worker_fallback(
        'perplexity',
        mode='deep_research',
        fallback=lambda platform, mode=None, model=None: {
            'success': True,
            'platform': platform,
            'selected_mode': mode or model,
        },
    )

    assert result['success'] is True
    assert result['selected_mode'] == 'deep_research'
    assert result['route'] == 'in_process_fallback'
    assert result['worker_error'] == 'worker down'
