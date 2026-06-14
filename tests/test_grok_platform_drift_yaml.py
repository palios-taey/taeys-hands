from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_grok_live_model_menu_names() -> None:
    data = yaml.safe_load((ROOT / 'consultation_v2' / 'platforms' / 'grok.yaml').read_text())
    element_map = data['tree']['element_map']
    defaults = data['workflow']['defaults']
    validation = data['validation']

    assert defaults['mode'] is None
    assert element_map['model_auto']['name'] == 'Auto Chooses Fast or Expert'
    assert element_map['model_fast']['name'] == 'Fast Powered by Grok 4.3'
    assert element_map['model_expert']['name'] == 'Expert Powered by Grok 4.3'
    assert element_map['model_heavy']['name'] == 'Heavy Team of Experts'
    assert element_map['upload_files_item']['name'] == 'Upload a file'
    assert element_map['recent_item']['name'] == 'Recent'
    assert element_map['skills_item']['name'] == 'Skills'
    assert element_map['connectors_item']['name'] == 'Connectors'
    assert validation['heavy_active']['indicators'][0]['name'] == 'Heavy Team of Experts'
    assert 'coordinate_fallback' not in data['imagine']['input']
