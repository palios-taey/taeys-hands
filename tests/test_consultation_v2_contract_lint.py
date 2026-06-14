from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'lint_consultation_v2_contract.py'


def test_contract_lint_rejects_forbidden_yaml_and_python(tmp_path: Path) -> None:
    yaml_path = tmp_path / 'consultation_v2' / 'platforms' / 'demo.yaml'
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        '\n'.join([
            'platform: demo',
            'urls: {fresh: https://example.com}',
            'tree:',
            '  element_map: {}',
            'workflow: {}',
            'validation: {}',
            'settle:',
            '  default_ms: 1000',
            '  navigate_ms: 9001',
            '  attach_ms: 1000',
            '  rescan_attempts: 1',
            'tree_extra:',
            '  name_pattern: "bad*"',
        ]),
        encoding='utf-8',
    )

    py_path = tmp_path / 'consultation_v2' / 'demo.py'
    py_path.write_text(
        '\n'.join([
            'def validate_demo(snapshot):',
            '    if platform == "grok":',
            '        return find_first(snapshot, "demo")',
            '    return {"matched": False}',
        ]),
        encoding='utf-8',
    )

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(yaml_path.relative_to(tmp_path)), str(py_path.relative_to(tmp_path))],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert proc.returncode != 0
    assert 'yaml-settle-max' in proc.stdout
    assert 'yaml-forbidden-name_pattern' in proc.stdout
    assert 'py-platform-branch' in proc.stdout
    assert 'py-validator-element-ref' in proc.stdout
