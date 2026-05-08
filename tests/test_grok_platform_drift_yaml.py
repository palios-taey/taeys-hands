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
    assert element_map['model_fast']['name'] == 'Fast Quick responses'
    assert element_map['model_expert']['name'] == 'Expert Thinks hard'
    assert element_map['model_heavy']['name'] == 'Heavy Team of Experts'
    assert validation['heavy_active']['indicators'][0]['name'] == 'Heavy Team of Experts'
