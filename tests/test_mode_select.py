"""Tests for mode/model selection — YAML config loading and routing."""

import importlib
import os
import sys
from pathlib import Path

import pytest
import yaml

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
    assert 'instant' in mg
    assert 'thinking' in mg
    assert 'pro' in mg
    assert 'pro_extended' in mg
    assert 'extended_thinking' in mg
    assert mg['pro_extended']['steps'] == [
        {'trigger': 'model_selector', 'select': 'model_pro'},
    ]
    assert mg['pro']['timeout'] == 7200


def test_chatgpt_consultation_defaults():
    from core.config import get_platform_config

    defaults = get_platform_config('chatgpt', reload=True)['consultation_defaults']
    assert defaults['model'] is None
    assert defaults['mode'] == 'pro'


def test_consultation_v2_chatgpt_exact_map() -> None:
    data = yaml.safe_load((Path(__file__).resolve().parents[1] / 'consultation_v2' / 'platforms' / 'chatgpt.yaml').read_text())
    element_map = data['tree']['element_map']
    workflow = data['workflow']['selection']

    assert element_map['model_selector']['name'] == 'Pro Extended'
    assert element_map['copy_button']['name'] == 'Copy response'
    assert element_map['model_instant']['name'] == 'Instant'
    assert element_map['model_thinking']['name'] == 'Medium'
    assert element_map['model_medium']['name'] == 'Medium'
    assert element_map['model_high']['name'] == 'High'
    assert element_map['model_extra_high']['name'] == 'Extra High'
    assert element_map['model_pro']['name'] == 'Pro Extended'
    assert element_map['tool_upload']['name'] == 'Add photos & files Control U'
    assert element_map['tool_more']['name'] == 'More'
    assert workflow['model_targets'] == {
        'instant': 'model_instant',
        'thinking': 'model_thinking',
        'pro': 'model_pro',
        'medium': 'model_medium',
        'high': 'model_high',
        'extra_high': 'model_extra_high',
    }


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
            'selected_item': 'Pro Extended',
            'completed_steps': [
                {'step': 1, 'verified': True},
                {'step': 2, 'verified': True},
            ],
        },
    )

    assert result['verified'] is True
    assert result['method'] == 'all_steps_verified'


def test_chatgpt_pro_extended_rejects_unverified_completed_step():
    import sys

    sys.argv = ['consultation.py', '--platform', 'chatgpt', '--message', 'x']
    from scripts import consultation

    result = consultation._verify_mode_selection(
        'chatgpt',
        'pro_extended',
        {
            'success': True,
            'selected_item': 'Thinking',
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
        {'name': 'Pro Extended', 'role': 'push button'}
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


def test_multi_step_select_honors_yaml_role_for_select_target(monkeypatch):
    from core.mode_select import _multi_step_select

    calls = []
    match_targets = []

    monkeypatch.setattr('core.mode_select.get_platform_config', lambda platform: {
        'element_map': {
            'more_tools_button': {
                'name': 'More tools',
                'role': 'push button',
            },
        },
    })
    monkeypatch.setattr('core.mode_select._find_button_by_element_map', lambda *args, **kwargs: {
        'name': 'Upload & tools',
        'x': 1,
        'y': 1,
    })
    monkeypatch.setattr('core.mode_select._click_element', lambda *args, **kwargs: True)
    def _fake_find_menu_items(*args, **kwargs):
        calls.append(kwargs.get('allowed_roles'))
        items = [
            {'name': 'Upload files', 'role': 'menu item'},
            {'name': 'More tools', 'role': 'push button'},
            {'name': 'Deep research', 'role': 'menu item'},
        ]
        allowed_roles = kwargs.get('allowed_roles')
        if allowed_roles:
            items = [item for item in items if item['role'] in allowed_roles]
        return items

    monkeypatch.setattr('core.mode_select.find_menu_items', _fake_find_menu_items)
    def _fake_match_and_click(items, target, platform):
        match_targets.append(target)
        return {
            'success': True,
            'selected_item': items[0]['name'],
        }

    monkeypatch.setattr('core.mode_select._match_and_click', _fake_match_and_click)
    monkeypatch.setattr(
        'core.mode_select._verify_multi_step_selection',
        lambda *args, **kwargs: {'verified': True, 'method': 'checked_state'},
    )

    result = _multi_step_select(
        'gemini',
        [{'trigger': 'upload_tools', 'select': 'more_tools_button'}],
        'deep_think',
        object(),
        object(),
    )

    assert result['success'] is True
    assert calls == [['push button']]
    assert match_targets == ['more tools']
    assert result['selected_item'] == 'More tools'
    assert result['completed_steps'] == [
        {
            'step': 1,
            'trigger': 'upload_tools',
            'selected': 'More tools',
            'verified': True,
            'verify_method': 'checked_state',
        }
    ]


def test_multi_step_select_scans_null_trigger_step_after_settle_delay(monkeypatch):
    from core.mode_select import _multi_step_select

    calls = []
    sleep_calls = []
    match_targets = []

    monkeypatch.setattr('core.mode_select.get_platform_config', lambda platform: {
        'element_map': {
            'more_tools_button': {
                'name': 'More tools',
                'role': 'push button',
            },
            'deep_think_item': {
                'name': 'Deep think',
                'role': 'check menu item',
            },
        },
    })
    monkeypatch.setattr('core.mode_select._find_button_by_element_map', lambda *args, **kwargs: {
        'name': 'Upload & tools',
        'x': 1,
        'y': 1,
    })
    monkeypatch.setattr('core.mode_select._click_element', lambda *args, **kwargs: True)
    monkeypatch.setattr('core.mode_select.time.sleep', lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr('core.mode_select.atspi.get_platform_document', lambda *args, **kwargs: object())

    def _fake_find_menu_items(*args, **kwargs):
        allowed_roles = kwargs.get('allowed_roles')
        calls.append(allowed_roles)
        if allowed_roles == ['push button']:
            return [{'name': 'More tools', 'role': 'push button'}]
        if allowed_roles == ['check menu item']:
            return [{'name': 'Deep think', 'role': 'check menu item'}]
        return []

    monkeypatch.setattr('core.mode_select.find_menu_items', _fake_find_menu_items)
    monkeypatch.setattr('core.mode_select.find_elements', lambda *args, **kwargs: [])

    def _fake_match_and_click(items, target, platform):
        match_targets.append(target)
        return {
            'success': True,
            'selected_item': items[0]['name'],
        }

    monkeypatch.setattr('core.mode_select._match_and_click', _fake_match_and_click)
    monkeypatch.setattr(
        'core.mode_select._verify_multi_step_selection',
        lambda *args, **kwargs: {'verified': True, 'method': 'checked_state'},
    )

    result = _multi_step_select(
        'gemini',
        [
            {'trigger': 'upload_tools', 'select': 'more_tools_button'},
            {'trigger': None, 'select': 'deep_think_item'},
        ],
        'deep_think',
        object(),
        object(),
    )

    assert result['success'] is True
    assert calls == [['push button'], ['check menu item']]
    assert match_targets == ['more tools', 'deep think']
    assert 0.75 in sleep_calls
    assert result['selected_item'] == 'Deep think'


def test_find_button_by_element_map_discovers_live_gemini_mode_picker(monkeypatch):
    from core.mode_select import _find_button_by_element_map

    monkeypatch.setattr('core.mode_select.get_element_spec', lambda platform, key: {
        'name_pattern': 'Open mode picker, currently *',
        'role': 'push button',
    })
    monkeypatch.setattr('core.mode_select.get_platform_config', lambda platform: {
        'fence_after': [],
    })
    monkeypatch.setattr('core.mode_select.find_elements', lambda doc, fence_after=None: [
        {'name': 'Upload & tools', 'role': 'push button', 'x': 10, 'y': 20},
        {'name': 'Open mode picker, currently 3.5 Thinking', 'role': 'push button', 'x': 20, 'y': 30},
    ])

    result = _find_button_by_element_map(object(), 'mode_picker', 'gemini')

    assert result == {
        'name': 'Open mode picker, currently 3.5 Thinking',
        'role': 'push button',
        'x': 20,
        'y': 30,
    }


def test_select_mode_model_uses_single_step_workflow_when_steps_present(monkeypatch):
    from core.mode_select import select_mode_model

    monkeypatch.setattr('core.mode_select.get_mode_guidance', lambda platform: {
        'deep_research': {
            'how': "Click 'Search' toggle button, select 'Deep research' radio menu item from dropdown",
            'timeout': 7200,
            'steps': [{'trigger': 'search_toggle', 'select': 'deep_research_radio'}],
        },
    })
    monkeypatch.setattr('core.mode_select.atspi.find_firefox_for_platform', lambda *args, **kwargs: object())
    monkeypatch.setattr('core.mode_select.atspi.get_platform_document', lambda *args, **kwargs: object())

    captured = {}

    def _fake_multi_step(platform, steps, target_mode, firefox, doc):
        captured['platform'] = platform
        captured['steps'] = steps
        captured['target_mode'] = target_mode
        return {
            'success': True,
            'selected_mode': target_mode,
            'selected_item': 'Deep research',
            'platform': platform,
            'completed_steps': [],
        }

    monkeypatch.setattr('core.mode_select._multi_step_select', _fake_multi_step)

    result = select_mode_model('perplexity', mode='deep_research')

    assert result['success'] is True
    assert result['timeout'] == 7200
    assert captured == {
        'platform': 'perplexity',
        'steps': [{'trigger': 'search_toggle', 'select': 'deep_research_radio'}],
        'target_mode': 'deep_research',
    }


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
