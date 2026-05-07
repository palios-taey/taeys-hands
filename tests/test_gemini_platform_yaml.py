from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_gemini_yaml_uses_learn_tool_label() -> None:
    data = yaml.safe_load((ROOT / 'consultation_v2' / 'platforms' / 'gemini.yaml').read_text())
    tool = data['tree']['element_map']['tool_guided_learning']
    assert tool['name'] == 'Learn'
