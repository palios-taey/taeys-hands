from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_consultation_v2_chatgpt_pro_extended_uses_live_model_selector_signal() -> None:
    data = yaml.safe_load((ROOT / 'consultation_v2' / 'platforms' / 'chatgpt.yaml').read_text())
    element_map = data['tree']['element_map']
    validation = data['validation']

    assert element_map['model_selector'] == {
        'names_any_of': ['Instant', 'Medium', 'High', 'Extra High', 'Pro Extended'],
        'role': 'push button',
    }
    assert element_map['pro_indicator'] == {
        'name': 'Pro Extended',
        'role': 'push button',
    }
    assert element_map['extended_pro'] == {
        'name': 'Pro Extended',
        'role': 'push button',
    }
    assert element_map['model_instant']['role'] == 'radio menu item'
    assert element_map['model_medium']['role'] == 'radio menu item'
    assert element_map['model_high']['role'] == 'radio menu item'
    assert element_map['model_extra_high']['role'] == 'radio menu item'
    assert element_map['model_pro']['role'] == 'radio menu item'
    assert element_map['stop_button'] == {
        'names_any_of': [
            'Stop streaming',
            'Stop answering',
        ],
        'role': 'push button',
    }
    assert element_map['thinking_mode'] == {
        'name': 'Pro Extended',
        'role': 'push button',
    }
    assert validation['pro_active'] == {
        'indicators': [
            {
                'name': 'Pro Extended',
                'role': 'push button',
            },
        ],
    }
    assert validation['pro_extended_active'] == {
        'indicators': [
            {
                'name': 'Pro Extended',
                'role': 'push button',
            },
        ],
    }
    assert validation['extended_thinking_active'] == {
        'indicators': [
            {
                'name': 'Pro Extended',
                'role': 'push button',
            },
        ],
    }
    assert validation['attach_success'] == {
        'file_chip': {
            'roles': ['push button'],
        },
    }
    assert validation['send_success']['indicators'][0] == {
        'names_any_of': [
            'Stop streaming',
            'Stop answering',
        ],
        'role': 'push button',
    }
