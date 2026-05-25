from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_root_perplexity_attach_uses_file_dialog_close() -> None:
    data = yaml.safe_load((ROOT / 'platforms' / 'perplexity.yaml').read_text())
    assert data['validation']['attach_success'] == {
        'method': 'file_dialog_close',
    }


def test_root_perplexity_deep_research_restored_as_default_mode() -> None:
    data = yaml.safe_load((ROOT / 'platforms' / 'perplexity.yaml').read_text())

    assert data['consultation_defaults']['mode'] == 'deep_research'
    assert data['element_map']['search_toggle'] == {
        'name': 'Search',
        'role': 'toggle button',
    }
    assert data['element_map']['deep_research_radio'] == {
        'name': 'Deep research',
        'role': 'radio menu item',
    }
    assert data['mode_guidance']['deep_research']['steps'] == [
        {'trigger': 'search_toggle', 'select': 'deep_research_radio'},
    ]
