from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_consultation_v2_gemini_exact_map() -> None:
    data = yaml.safe_load((ROOT / 'consultation_v2' / 'platforms' / 'gemini.yaml').read_text())
    element_map = data['tree']['element_map']

    assert element_map['input']['name'] == 'Enter a prompt for Gemini'
    assert element_map['mode_picker']['name'] == 'Open mode picker, currently Pro'
    assert element_map['tools_button']['name'] == 'Upload & tools'
    assert element_map['upload_menu']['name'] == 'Upload & tools'
    assert element_map['mode_fast']['name'] == '3.5 Flash'
    assert element_map['mode_thinking']['name'] == '3.5 Thinking'
    assert element_map['mode_pro']['name'] == 'Selected 3.1 Pro Advanced math and code'
    assert element_map['upload_files_item']['name'] == 'Upload files. Documents, data, code files'
    assert element_map['tool_guided_learning']['name'] == 'Guided learning'
    assert element_map['tool_deep_think']['name'] == 'Deep think'
    assert element_map['copy_button']['name'] == 'Copy'


def test_root_gemini_deep_think_uses_more_tools_flow() -> None:
    data = yaml.safe_load((ROOT / 'platforms' / 'gemini.yaml').read_text())

    element_map = data['element_map']
    assert element_map['mode_picker'] == {
        'name_pattern': 'Open mode picker, currently *',
        'role': 'push button',
    }
    assert element_map['model_3_5_thinking'] == {
        'name': '3.5 Thinking Solves complex problems',
        'role': 'radio menu item',
    }
    assert element_map['upload_tools'] == {
        'name': 'Upload & tools',
        'role': 'push button',
    }
    assert element_map['more_tools_button'] == {
        'name': 'More tools',
        'role': 'push button',
    }
    assert element_map['deep_think_item'] == {
        'name': 'Deep think',
        'role': 'check menu item',
    }
    assert element_map['deep_think_active'] == {
        'name': 'Deselect Deep think',
        'role': 'push button',
    }

    deep_think = data['mode_guidance']['deep_think']
    assert deep_think['steps'] == [
        {'trigger': 'mode_picker', 'select': 'mode_pro'},
        {'trigger': 'upload_tools', 'select': 'more_tools_button'},
        {'trigger': None, 'select': 'deep_think_item'},
    ]
    assert deep_think['validation'] == {
        'deep_think_active': {
            'indicators': [
                {'name': 'Deselect Deep think', 'role': 'push button'},
            ],
        },
    }
