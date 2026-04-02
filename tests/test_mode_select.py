"""Tests for mode/model selection — YAML config loading and routing."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_load_config_all_platforms():
    """All platform YAMLs load without error and have mode_guidance."""
    from core.mode_select import _load_config

    for platform in ['chatgpt', 'gemini', 'grok', 'perplexity', 'claude']:
        config = _load_config(platform)
        assert config is not None, f"{platform} config is None"
        assert 'mode_guidance' in config, f"{platform} missing mode_guidance"
        assert len(config['mode_guidance']) > 0, f"{platform} has empty mode_guidance"


def test_chatgpt_mode_guidance():
    from core.mode_select import _load_config
    config = _load_config('chatgpt')
    mg = config['mode_guidance']

    assert 'auto' in mg
    assert 'thinking' in mg
    assert 'pro' in mg
    assert mg['pro']['timeout'] == 7200


def test_gemini_mode_guidance():
    from core.mode_select import _load_config
    config = _load_config('gemini')
    mg = config['mode_guidance']

    assert 'deep_think' in mg
    assert 'deep_research' in mg
    assert 'tools' in mg['deep_think']['how'].lower()


def test_grok_mode_guidance():
    from core.mode_select import _load_config
    config = _load_config('grok')
    mg = config['mode_guidance']

    assert 'expert' in mg
    assert 'heavy' in mg
    assert mg['heavy']['timeout'] == 7200


def test_perplexity_mode_guidance():
    from core.mode_select import _load_config
    config = _load_config('perplexity')
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
    from core.mode_select import _load_config

    for platform in ['x_twitter', 'linkedin']:
        config = _load_config(platform)
        assert config is not None


def test_element_map_coverage():
    """All chat platforms have required element_map keys."""
    from core.mode_select import _load_config

    required_keys = {'input', 'copy_button'}
    for platform in ['chatgpt', 'gemini', 'grok', 'perplexity', 'claude']:
        config = _load_config(platform)
        em = config.get('element_map', {})
        for key in required_keys:
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
