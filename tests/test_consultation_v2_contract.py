from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_DIR = ROOT / 'consultation_v2' / 'platforms'
REQUIRED_TOP_LEVEL = {'platform', 'urls', 'tree', 'workflow', 'validation'}
REQUIRED_ELEMENT_KEYS = {
    'chatgpt': {'input', 'model_selector', 'attach_trigger', 'send_button', 'stop_button', 'copy_button'},
    'claude': {'input', 'toggle_menu', 'send_button', 'stop_button', 'copy_button'},
    'gemini': {'input', 'mode_picker', 'tools_button', 'upload_menu', 'send_button', 'stop_button', 'copy_button'},
    'grok': {'input', 'attach_trigger', 'model_selector', 'stop_button', 'copy_button'},
    'perplexity': {'input', 'attach_trigger', 'model_selector', 'submit_button', 'stop_button', 'copy_button'},
}


def test_platform_yaml_files_exist() -> None:
    names = {path.stem for path in PLATFORM_DIR.glob('*.yaml')}
    assert names == {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}


def test_platform_yaml_contract() -> None:
    for path in sorted(PLATFORM_DIR.glob('*.yaml')):
        data = yaml.safe_load(path.read_text()) or {}
        assert REQUIRED_TOP_LEVEL.issubset(data), f'{path.name} missing {REQUIRED_TOP_LEVEL - set(data)}'
        tree = data.get('tree') or {}
        workflow = data.get('workflow') or {}
        assert 'element_map' in tree, f'{path.name} missing tree.element_map'
        assert 'selection' in workflow, f'{path.name} missing workflow.selection'
        assert 'attachment' in workflow, f'{path.name} missing workflow.attachment'
        assert 'prompt' in workflow, f'{path.name} missing workflow.prompt'
        assert 'send' in workflow, f'{path.name} missing workflow.send'
        assert 'monitor' in workflow, f'{path.name} missing workflow.monitor'
        assert 'extract' in workflow, f'{path.name} missing workflow.extract'
        assert REQUIRED_ELEMENT_KEYS[path.stem].issubset(set((tree.get('element_map') or {}).keys()))
