from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_gemini_yaml_uses_learn_tool_label() -> None:
    data = yaml.safe_load((ROOT / 'consultation_v2' / 'platforms' / 'gemini.yaml').read_text())
    tool = data['tree']['element_map']['tool_guided_learning']
    assert tool['name'] == 'Learn'


def test_root_gemini_deep_think_uses_more_tools_flow() -> None:
    data = yaml.safe_load((ROOT / 'platforms' / 'gemini.yaml').read_text())

    element_map = data['element_map']
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
