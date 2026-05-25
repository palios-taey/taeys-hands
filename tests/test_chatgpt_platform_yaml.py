from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_root_chatgpt_stop_button_uses_exact_name_alternatives() -> None:
    data = yaml.safe_load((ROOT / 'platforms' / 'chatgpt.yaml').read_text())
    assert data['element_map']['stop_button'] == {
        'names_any_of': [
            'Stop answering',
            'Stop response',
            'Stop streaming',
            'Stop generating',
            'Stop',
        ],
        'role': 'push button',
    }
