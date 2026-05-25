from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_root_perplexity_attach_uses_file_dialog_close() -> None:
    data = yaml.safe_load((ROOT / 'platforms' / 'perplexity.yaml').read_text())
    assert data['validation']['attach_success'] == {
        'method': 'file_dialog_close',
    }
