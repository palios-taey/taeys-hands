#!/usr/bin/env python3
"""Build gate for PLATFORM_INDEPENDENCE_SPEC section 5.

The current tree has legacy flat YAML files under consultation_v2/platforms and
no per-platform package directories yet. This lint is intentionally quiet until
consultation_v2/platforms/<platform>/ packages appear, then fails package PRs
that reintroduce shared-driver coupling or cross-platform imports.
"""
from __future__ import annotations

import argparse
import ast
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import lint_consultation_v2_contract as contract_lint  # noqa: E402


CHAT_PLATFORM_PACKAGES = frozenset({'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'})
PACKAGE_ROOT = Path('consultation_v2/platforms')
LEAF_MODULES = (
    Path('consultation_v2/clipboard.py'),
    Path('consultation_v2/tree.py'),
    Path('consultation_v2/yaml_contract.py'),
    Path('consultation_v2/types.py'),
    Path('consultation_v2/notify.py'),
    Path('consultation_v2/identity.py'),
    Path('consultation_v2/storage_policy.py'),
    Path('consultation_v2/ingest.py'),
    Path('consultation_v2/stop_conditions.py'),
)
FORBIDDEN_SHARED_MODULES = ('consultation_v2.drivers.base', 'consultation_v2.completion')
DELIVERY_GATE = 'reject_prompt_echo_response'


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    label: str
    why: str
    text: str = ''


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _parse_python(path: Path, root: Path) -> ast.Module | None:
    try:
        return ast.parse(_read(path), filename=str(path))
    except SyntaxError as exc:
        raise ValueError(f'{_display_path(path, root)}:{exc.lineno}: python parse error: {exc.msg}') from exc


def _package_dirs(root: Path) -> list[Path]:
    base = root / PACKAGE_ROOT
    if not base.exists():
        return []
    return sorted(
        item for item in base.iterdir()
        if item.is_dir() and item.name != '__pycache__' and not item.name.startswith('.')
    )


def _package_python_files(package_dir: Path) -> list[Path]:
    return sorted(
        path for path in package_dir.rglob('*.py')
        if '__pycache__' not in path.parts
    )


def _module_parts(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root).with_suffix('')
    parts = list(rel.parts)
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return parts


def _package_parts(path: Path, root: Path) -> list[str]:
    parts = _module_parts(path, root)
    if path.name == '__init__.py':
        return parts
    return parts[:-1]


def _resolve_import_from(path: Path, root: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ''
    package_parts = _package_parts(path, root)
    keep = len(package_parts) - node.level + 1
    if keep < 0:
        return node.module or ''
    parts = package_parts[:keep]
    if node.module:
        parts.extend(part for part in node.module.split('.') if part)
    return '.'.join(parts)


def _is_forbidden_shared_module(module: str) -> bool:
    return any(module == forbidden or module.startswith(f'{forbidden}.') for forbidden in FORBIDDEN_SHARED_MODULES)


def _platform_from_module(module: str, alias_name: str | None, platform_names: set[str]) -> str | None:
    parts = [part for part in module.split('.') if part]
    if len(parts) >= 3 and parts[:2] == ['consultation_v2', 'platforms'] and parts[2] in platform_names:
        return parts[2]
    if parts == ['consultation_v2', 'platforms'] and alias_name in platform_names:
        return alias_name
    return None


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        root = _dotted_name(node.value)
        if root:
            return f'{root}.{node.attr}'
    if isinstance(node, ast.Subscript):
        return _dotted_name(node.value)
    return None


def _import_aliases(tree: ast.Module, path: Path, root: Path) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                elif len(alias.name.split('.')) == 1:
                    aliases[alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(path, root, node)
            for alias in node.names:
                if alias.name == '*':
                    continue
                aliases[alias.asname or alias.name] = f'{module}.{alias.name}' if module else alias.name
    return aliases


def _resolve_base_name(base: ast.AST, aliases: dict[str, str]) -> str:
    dotted = _dotted_name(base) or '<unknown>'
    first, _, rest = dotted.partition('.')
    if first in aliases:
        return f'{aliases[first]}.{rest}' if rest else aliases[first]
    return dotted


def _package_class_names(package_dir: Path, root: Path) -> set[str]:
    names: set[str] = set()
    for path in _package_python_files(package_dir):
        try:
            tree = _parse_python(path, root)
        except ValueError:
            continue
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
    return names


def _base_allowed(resolved: str, current_package: str, package_classes: set[str]) -> bool:
    if resolved == 'object':
        return True
    if resolved in package_classes:
        return True
    package_prefix = f'consultation_v2.platforms.{current_package}'
    if resolved == package_prefix or resolved.startswith(f'{package_prefix}.'):
        return True
    return resolved.startswith('consultation_v2.types.')


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _calls_delivery_gate(function: ast.AST) -> bool:
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and _call_name(node.func) == DELIVERY_GATE:
            return True
    return False


def _function_defs(tree: ast.Module, name: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]


def _source_segment(source: str, node: ast.AST) -> str:
    return (ast.get_source_segment(source, node) or '').strip().splitlines()[0] if source else ''


def _scan_package_imports(
    path: Path,
    root: Path,
    tree: ast.Module,
    current_package: str,
    platform_names: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    display = _display_path(path, root)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target_package = _platform_from_module(alias.name, None, platform_names)
                if target_package and target_package != current_package:
                    findings.append(Finding(
                        display, node.lineno, 'package-cross-platform-import',
                        f'platform package {current_package} must not import platform package {target_package}',
                        f'import {alias.name}',
                    ))
                if _is_forbidden_shared_module(alias.name):
                    label = 'package-shared-base-import' if 'drivers.base' in alias.name else 'package-shared-completion-import'
                    findings.append(Finding(
                        display, node.lineno, label,
                        'platform packages must not import drivers.base or completion',
                        f'import {alias.name}',
                    ))
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(path, root, node)
            modules_to_check = [module]
            modules_to_check.extend(f'{module}.{alias.name}' for alias in node.names if alias.name != '*')
            for module_name in modules_to_check:
                target_package = _platform_from_module(module_name, None, platform_names)
                if target_package and target_package != current_package:
                    findings.append(Finding(
                        display, node.lineno, 'package-cross-platform-import',
                        f'platform package {current_package} must not import platform package {target_package}',
                        _source_segment(_read(path), node),
                    ))
                    break
            for alias in node.names:
                if alias.name == '*':
                    continue
                full_name = f'{module}.{alias.name}' if module else alias.name
                if _is_forbidden_shared_module(module) or _is_forbidden_shared_module(full_name):
                    label = (
                        'package-shared-base-import'
                        if 'drivers.base' in module or 'drivers.base' in full_name
                        else 'package-shared-completion-import'
                    )
                    findings.append(Finding(
                        display, node.lineno, label,
                        'platform packages must not import drivers.base or completion',
                        _source_segment(_read(path), node),
                    ))
    return findings


def _scan_package_inheritance(
    path: Path,
    root: Path,
    tree: ast.Module,
    current_package: str,
    package_classes: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    aliases = _import_aliases(tree, path, root)
    source = _read(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            resolved = _resolve_base_name(base, aliases)
            if _base_allowed(resolved, current_package, package_classes):
                continue
            findings.append(Finding(
                _display_path(path, root),
                getattr(base, 'lineno', node.lineno),
                'package-out-of-package-inheritance',
                'platform package classes must not inherit from out-of-package classes except consultation_v2.types dataclasses',
                _source_segment(source, base) or resolved,
            ))
    return findings


def _scan_driver_entry_contract(package_dir: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    driver = package_dir / 'driver.py'
    package_name = package_dir.name
    display = _display_path(driver, root)
    if not driver.exists():
        return [Finding(
            display, 1, 'package-driver-missing',
            'each platform package must expose driver.py with run() and reject_prompt_echo_response',
        )]
    tree = _parse_python(driver, root)
    if tree is None:
        return findings
    source = _read(driver)
    gate_defs = _function_defs(tree, DELIVERY_GATE)
    if not gate_defs:
        findings.append(Finding(
            display, 1, 'package-delivery-gate-missing',
            f'{package_name} driver.py must define {DELIVERY_GATE}',
        ))
    run_defs = _function_defs(tree, 'run')
    if not run_defs:
        findings.append(Finding(
            display, 1, 'package-run-missing',
            f'{package_name} driver.py must define run()',
        ))
    elif not any(_calls_delivery_gate(run_def) for run_def in run_defs):
        findings.append(Finding(
            display,
            getattr(run_defs[0], 'lineno', 1),
            'package-run-delivery-gate-not-invoked',
            f'{package_name} run() must invoke {DELIVERY_GATE} before returning/delivering',
            _source_segment(source, run_defs[0]),
        ))
    return findings


def _scan_package_yaml(package_dir: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(package_dir.glob('*.y*ml')):
        rel = path.relative_to(root)
        source = _read(path)
        for item in contract_lint.scan_yaml_schema(rel, source):
            findings.append(Finding(
                item.path,
                item.line_no,
                f'package-yaml-{item.label}',
                item.why,
                item.text,
            ))
    return findings


def _scan_package(package_dir: Path, root: Path, platform_names: set[str]) -> list[Finding]:
    current_package = package_dir.name
    package_classes = _package_class_names(package_dir, root)
    findings: list[Finding] = []
    for path in _package_python_files(package_dir):
        try:
            tree = _parse_python(path, root)
        except ValueError as exc:
            findings.append(Finding(_display_path(path, root), 1, 'package-python-parse-error', str(exc)))
            continue
        if tree is None:
            continue
        findings.extend(_scan_package_imports(path, root, tree, current_package, platform_names))
        findings.extend(_scan_package_inheritance(path, root, tree, current_package, package_classes))
    findings.extend(_scan_driver_entry_contract(package_dir, root))
    findings.extend(_scan_package_yaml(package_dir, root))
    return findings


def _names_and_attrs(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _string_literals(node: ast.AST) -> set[str]:
    values: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.add(child.value)
    return values


def _is_platform_subject(name: str) -> bool:
    lowered = name.lower()
    return lowered == 'platform' or lowered.endswith('_platform')


def _is_platform_conditional_test(node: ast.AST) -> bool:
    names = _names_and_attrs(node)
    if not any(_is_platform_subject(name) for name in names):
        return False
    return bool(_string_literals(node) & CHAT_PLATFORM_PACKAGES)


def _match_has_platform_literal(node: ast.Match) -> bool:
    for case in node.cases:
        for child in ast.walk(case.pattern):
            if isinstance(child, ast.MatchValue) and isinstance(child.value, ast.Constant):
                if child.value.value in CHAT_PLATFORM_PACKAGES:
                    return True
    return False


class LeafBranchVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, root: Path, source: str) -> None:
        self.path = path
        self.root = root
        self.source = source
        self.findings: list[Finding] = []

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        if _is_platform_conditional_test(node.test):
            self._add(node, node.test)
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:  # noqa: N802
        if _is_platform_conditional_test(node.test):
            self._add(node, node.test)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:  # noqa: N802
        subject_names = _names_and_attrs(node.subject)
        if any(_is_platform_subject(name) for name in subject_names) and _match_has_platform_literal(node):
            self._add(node, node.subject)
        self.generic_visit(node)

    def _add(self, node: ast.AST, source_node: ast.AST) -> None:
        self.findings.append(Finding(
            _display_path(self.path, self.root),
            getattr(node, 'lineno', 1),
            'leaf-platform-branch',
            'leaf modules must not branch behavior on platform identity; only declared data registries are exempt',
            _source_segment(self.source, source_node),
        ))


def _scan_leaf_modules(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for rel_path in LEAF_MODULES:
        path = root / rel_path
        if not path.exists():
            continue
        try:
            source = _read(path)
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            findings.append(Finding(str(rel_path), exc.lineno or 1, 'leaf-python-parse-error', exc.msg))
            continue
        visitor = LeafBranchVisitor(path, root, source)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    return findings


def scan_root(root: Path) -> tuple[list[Finding], int, int]:
    root = root.resolve()
    packages = _package_dirs(root)
    platform_names = set(CHAT_PLATFORM_PACKAGES) | {package.name for package in packages}
    findings: list[Finding] = []
    for package_dir in packages:
        findings.extend(_scan_package(package_dir, root, platform_names))
    findings.extend(_scan_leaf_modules(root))
    leaf_count = sum(1 for rel_path in LEAF_MODULES if (root / rel_path).exists())
    return findings, len(packages), leaf_count


def _write_self_test_fixture(root: Path) -> None:
    chatgpt = root / 'consultation_v2' / 'platforms' / 'chatgpt'
    claude = root / 'consultation_v2' / 'platforms' / 'claude'
    chatgpt.mkdir(parents=True)
    claude.mkdir(parents=True)
    (root / 'consultation_v2').mkdir(exist_ok=True)
    (root / 'consultation_v2' / 'clipboard.py').write_text(
        "def choose(platform):\n"
        "    if " "platform == 'chatgpt':\n"
        "        return 'bad'\n"
        "    return 'ok'\n",
        encoding='utf-8',
    )
    (claude / 'driver.py').write_text(
        "class ClaudeDriver:\n"
        "    pass\n",
        encoding='utf-8',
    )
    (chatgpt / 'driver.py').write_text(
        "from consultation_v2.platforms.claude.driver import ClaudeDriver\n"
        "from consultation_v2.drivers.base import BaseConsultationDriver\n"
        "from consultation_v2.completion import CompletionDetector\n\n"
        "class ChatGPTDriver(BaseConsultationDriver):\n"
        "    def reject_prompt_echo_response(self, text):\n"
        "        return False\n\n"
        "    def run(self, request):\n"
        "        return request\n",
        encoding='utf-8',
    )
    (chatgpt / 'chatgpt.yaml').write_text(
        "platform: chatgpt\n"
        "tree:\n"
        "  element_map:\n"
        "    input:\n"
        "      name_contains: Prompt\n"
        "      role: entry\n"
        "workflow: {}\n",
        encoding='utf-8',
    )


def _print_findings(findings: list[Finding], package_count: int, leaf_count: int) -> int:
    if not findings:
        print(
            'platform isolation lint CLEAN - '
            f'{package_count} package(s), {leaf_count} leaf module(s), 0 findings'
        )
        return 0
    by_label: dict[str, int] = {}
    for finding in findings:
        by_label[finding.label] = by_label.get(finding.label, 0) + 1
        print(f'{finding.path}:{finding.line_no}: [{finding.label}] {finding.text}')
        print(f'    -> {finding.why}')
    print()
    print(
        'platform isolation lint FAIL - '
        f'{len(findings)} finding(s) across {package_count} package(s), {leaf_count} leaf module(s):'
    )
    for label, count in sorted(by_label.items(), key=lambda item: (-item[1], item[0])):
        print(f'    {count:>3}  {label}')
    return 1


def _self_test() -> int:
    required_labels = {
        'package-cross-platform-import',
        'package-shared-base-import',
        'package-shared-completion-import',
        'package-out-of-package-inheritance',
        'package-run-delivery-gate-not-invoked',
        'package-yaml-yaml-settle-missing',
        'package-yaml-yaml-forbidden-name_contains',
        'leaf-platform-branch',
    }
    with tempfile.TemporaryDirectory(prefix='platform-isolation-lint-') as tmp:
        root = Path(tmp)
        _write_self_test_fixture(root)
        findings, package_count, leaf_count = scan_root(root)
        labels = {finding.label for finding in findings}
        missing = sorted(required_labels - labels)
        if missing:
            _print_findings(findings, package_count, leaf_count)
            print(f'platform isolation lint SELF-TEST FAIL - missing labels: {missing}', file=sys.stderr)
            return 1
        print(
            'platform isolation lint SELF-TEST PASS - deliberately violating '
            f'fixture rejected with labels: {", ".join(sorted(required_labels))}'
        )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='scan repository root')
    parser.add_argument('--self-test', action='store_true', help='prove a deliberately violating fixture fails')
    parser.add_argument('--root', default='.', help='repository root to scan')
    args = parser.parse_args()

    modes = sum(bool(mode) for mode in (args.all, args.self_test))
    if modes != 1:
        parser.error('specify exactly one of --all or --self-test')
        return 2
    if args.self_test:
        return _self_test()

    findings, package_count, leaf_count = scan_root(Path(args.root))
    return _print_findings(findings, package_count, leaf_count)


if __name__ == '__main__':
    raise SystemExit(main())
