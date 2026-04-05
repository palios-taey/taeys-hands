"""Tests for mode/model selection — YAML config loading and routing."""

import importlib
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_load_config_all_platforms():
    """All platform YAMLs load without error and have mode_guidance."""
    from core.config import get_platform_config

    for platform in ['chatgpt', 'gemini', 'grok', 'perplexity', 'claude']:
        config = get_platform_config(platform, reload=True)
        assert config is not None, f"{platform} config is None"
        assert 'mode_guidance' in config, f"{platform} missing mode_guidance"
        assert len(config['mode_guidance']) > 0, f"{platform} has empty mode_guidance"


def test_consultation_defaults_all_platforms():
    """All consultation platforms expose consultation_defaults in YAML."""
    from core.config import get_platform_config

    expected = {
        'chatgpt': {
            'model': 'pro',
            'mode': 'pro_extended',
            'attach_method': 'atspi_menu',
            'extract_method': 'last_copy_button',
        },
        'claude': {
            'model': None,
            'mode': 'extended_thinking',
            'attach_method': 'atspi_menu',
            'extract_method': 'last_copy_button',
        },
        'gemini': {
            'model': None,
            'mode': 'deep_think',
            'attach_method': 'atspi_menu',
            'extract_method': 'last_copy_button',
        },
        'grok': {
            'model': None,
            'mode': 'heavy',
            'attach_method': 'atspi_menu',
            'extract_method': 'last_copy_button',
        },
        'perplexity': {
            'model': None,
            'mode': 'deep_research',
            'attach_method': 'keyboard_nav',
            'extract_method': 'copy_contents',
        },
    }

    for platform, defaults in expected.items():
        config = get_platform_config(platform, reload=True)
        assert config.get('consultation_defaults') == defaults


def test_verify_navigation_is_yaml_driven_per_platform():
    """Navigation verification should be explicitly configured per platform."""
    from core.config import get_platform_config

    expected = {
        'chatgpt': False,
        'claude': False,
        'gemini': False,
        'grok': True,
        'perplexity': False,
    }

    for platform, verify_navigation in expected.items():
        config = get_platform_config(platform, reload=True)
        assert config.get('verify_navigation') is verify_navigation


def test_chatgpt_mode_guidance():
    from core.config import get_platform_config
    config = get_platform_config('chatgpt', reload=True)
    mg = config['mode_guidance']

    assert 'auto' in mg
    assert 'thinking' in mg
    assert 'pro' in mg
    assert 'extended' in mg
    assert mg['pro_extended']['steps'] == [
        {'trigger': 'model_selector', 'select': 'pro'},
        {'trigger': 'thinking_mode', 'select': 'extended'},
    ]
    assert mg['pro_extended']['verification'] == {
        'check': 'completed_steps',
        'expected_steps': 2,
    }
    assert mg['pro']['timeout'] == 7200


def test_chatgpt_consultation_defaults():
    from core.config import get_platform_config

    defaults = get_platform_config('chatgpt', reload=True)['consultation_defaults']
    assert defaults['model'] == 'pro'
    assert defaults['mode'] == 'pro_extended'


def test_consultation_uses_yaml_defaults_for_fresh_sessions():
    sys.argv = ['consultation.py', '--platform', 'chatgpt', '--message', 'x']
    consultation = importlib.import_module('scripts.consultation')
    consultation = importlib.reload(consultation)

    assert consultation.args.model == 'pro'
    assert consultation.args.mode == 'pro_extended'


def test_consultation_skips_yaml_defaults_for_followups():
    sys.argv = [
        'consultation.py',
        '--platform', 'chatgpt',
        '--message', 'x',
        '--session-url', 'https://chatgpt.com/c/example',
    ]
    consultation = importlib.import_module('scripts.consultation')
    consultation = importlib.reload(consultation)

    assert consultation.args.model is None
    assert consultation.args.mode is None


def test_chatgpt_pro_extended_verifies_by_completed_steps():
    import sys

    sys.argv = ['consultation.py', '--platform', 'chatgpt', '--message', 'x']
    from scripts import consultation

    result = consultation._verify_mode_selection(
        'chatgpt',
        'pro_extended',
        {
            'success': True,
            'selected_item': 'Extended Pro',
            'completed_steps': [
                {'step': 1, 'verified': True},
                {'step': 2, 'verified': True},
            ],
        },
    )

    assert result['verified'] is True
    assert result['method'] == 'completed_steps'


def test_chatgpt_pro_extended_rejects_unverified_completed_step():
    import sys

    sys.argv = ['consultation.py', '--platform', 'chatgpt', '--message', 'x']
    from scripts import consultation

    result = consultation._verify_mode_selection(
        'chatgpt',
        'pro_extended',
        {
            'success': True,
            'selected_item': 'Extended Pro',
            'completed_steps': [
                {'step': 1, 'verified': True},
                {'step': 2, 'verified': False},
            ],
        },
    )

    assert result['verified'] is False


def test_multi_step_select_requires_verified_steps(monkeypatch):
    from core.mode_select import _multi_step_select

    monkeypatch.setattr('core.mode_select._find_button_by_element_map', lambda *args, **kwargs: {
        'name': 'trigger',
        'x': 1,
        'y': 1,
    })
    monkeypatch.setattr('core.mode_select._click_element', lambda *args, **kwargs: True)
    monkeypatch.setattr('core.mode_select.find_menu_items', lambda *args, **kwargs: [
        {'name': 'Pro Research-grade intelligence', 'role': 'push button'}
    ])
    monkeypatch.setattr('core.mode_select.find_elements', lambda *args, **kwargs: [])
    monkeypatch.setattr('core.mode_select._match_and_click', lambda items, target, platform: {
        'success': True,
        'selected_item': target.title(),
    })

    verifications = iter([
        {'verified': True, 'method': 'mode_select_verify'},
        {'verified': False, 'note': 'Extended state not found'},
    ])
    monkeypatch.setattr(
        'core.mode_select._verify_multi_step_selection',
        lambda *args, **kwargs: next(verifications),
    )
    monkeypatch.setattr('core.mode_select.atspi.get_platform_document', lambda *args, **kwargs: object())

    result = _multi_step_select(
        'chatgpt',
        [
            {'trigger': 'model_selector', 'select': 'pro'},
            {'trigger': 'thinking_mode', 'select': 'extended'},
        ],
        'pro_extended',
        object(),
        object(),
    )

    assert result['success'] is False
    assert result['step'] == 2
    assert result['completed_steps'] == [
        {
            'step': 1,
            'trigger': 'model_selector',
            'selected': 'Pro',
            'verified': True,
            'verify_method': 'mode_select_verify',
        }
    ]


def test_gemini_mode_guidance():
    from core.config import get_platform_config
    config = get_platform_config('gemini', reload=True)
    mg = config['mode_guidance']

    assert 'deep_think' in mg
    assert 'deep_research' in mg
    assert 'tools' in mg['deep_think']['how'].lower()


def test_grok_mode_guidance():
    from core.config import get_platform_config
    config = get_platform_config('grok', reload=True)
    mg = config['mode_guidance']

    assert 'expert' in mg
    assert 'heavy' in mg
    assert mg['heavy']['timeout'] == 7200


def test_perplexity_mode_guidance():
    from core.config import get_platform_config
    config = get_platform_config('perplexity', reload=True)
    mg = config['mode_guidance']

    assert 'deep_research' in mg
    assert 'computer' in mg


def test_select_mode_no_mode_returns_success():
    """When no mode requested, should return success."""
    from core.mode_select import select_mode_model
    result = select_mode_model('chatgpt', mode=None, model=None)
    assert result.get('success') is True


def test_select_mode_invalid_platform():
    """Unknown platform mode should fail gracefully."""
    from core.mode_select import select_mode_model
    result = select_mode_model('chatgpt', mode='nonexistent_mode_xyz')
    assert result.get('success') is False
    assert 'available_modes' in result


def test_social_platform_configs():
    """Social platform stubs load without error."""
    from core.config import get_platform_config

    for platform in ['x_twitter', 'linkedin']:
        config = get_platform_config(platform, reload=True)
        assert config is not None


def test_element_map_coverage():
    """All chat platforms have required element_map keys."""
    from core.config import get_platform_config

    required_keys = {'input', 'copy_button'}
    for platform in ['chatgpt', 'gemini', 'grok', 'perplexity', 'claude']:
        config = get_platform_config(platform, reload=True)
        em = config.get('element_map', {})
        for key in required_keys:
            assert key in em, f"{platform} missing element_map.{key}"


def test_git_connector_element_map_coverage():
    """Platforms with git connector flows expose the connector menu item in YAML."""
    from core.config import get_platform_config

    expected = {
        'chatgpt': 'tool_github',
        'claude': 'git_connector_item',
        'gemini': 'import_code_item',
        'perplexity': 'git_connector_item',
    }
    for platform, key in expected.items():
        config = get_platform_config(platform, reload=True)
        em = config.get('element_map', {})
        assert key in em, f"{platform} missing element_map.{key}"


def test_match_and_click_skips_click_for_already_selected(monkeypatch):
    """Already-selected menu items should not be clicked again."""
    from core.mode_select import _match_and_click

    clicked = {'value': False}

    def fail_click(_item):
        clicked['value'] = True
        raise AssertionError("click should not be attempted for already-selected item")

    monkeypatch.setattr('core.interact.atspi_click', fail_click)

    result = _match_and_click(
        [{'name': 'Deep Research', 'role': 'check menu item', 'states': ['checked']}],
        'deep_research',
        'perplexity',
    )

    assert result.get('success') is True
    assert result.get('method') == 'already_selected'
    assert result.get('selected_item') == 'Deep Research'
    assert clicked['value'] is False
