from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER_DIR = ROOT / 'consultation_v2' / 'drivers'
DRIVER_FILES = [
    DRIVER_DIR / 'chatgpt.py',
    DRIVER_DIR / 'claude.py',
    DRIVER_DIR / 'gemini.py',
    DRIVER_DIR / 'grok.py',
    DRIVER_DIR / 'perplexity.py',
]
REQUIRED_METHODS = {
    'run',
    'select_model_mode_tools',
    'attach_files',
    'enter_prompt',
    'send_prompt',
    'monitor_generation',
    'extract_primary',
    'extract_additional',
    'store_in_neo4j',
}
BANNED_IMPORT_FRAGMENTS = {
    'tools.attach',
    'tools.send',
    'tools.extract',
    'tools.dropdown',
    'core.mode_select',
    'monitor.central',
}


def _import_targets(tree: ast.AST) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                targets.add(node.module)
    return targets


def _class_methods(tree: ast.AST) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for node in tree.body:  # type: ignore[attr-defined]
        if isinstance(node, ast.ClassDef):
            result[node.name] = {child.name for child in node.body if isinstance(child, ast.FunctionDef)}
    return result


def test_each_driver_is_self_contained() -> None:
    for path in DRIVER_FILES:
        tree = ast.parse(path.read_text())
        imports = _import_targets(tree)
        for banned in BANNED_IMPORT_FRAGMENTS:
            assert all(banned not in target for target in imports), f'{path.name} imports banned module fragment {banned}'
        classes = _class_methods(tree)
        concrete = [name for name in classes if name.endswith('ConsultationDriver') and name != 'BaseConsultationDriver']
        assert len(concrete) == 1, f'{path.name} should define exactly one concrete driver class'
        methods = classes[concrete[0]]
        assert REQUIRED_METHODS.issubset(methods), f'{path.name} missing methods {REQUIRED_METHODS - methods}'


def test_drivers_do_not_import_each_other() -> None:
    for path in DRIVER_FILES:
        tree = ast.parse(path.read_text())
        imports = _import_targets(tree)
        siblings = {f'consultation_v2.drivers.{other.stem}' for other in DRIVER_FILES if other != path}
        assert not (imports & siblings), f'{path.name} imports sibling drivers {imports & siblings}'
