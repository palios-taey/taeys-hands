#!/usr/bin/env python3
"""consultation_v2 contract lint.

Build gate for consultation_v2 YAML schema + AST-level binary-dispatch rules.
This complements the existing silent-fallback lint without changing its scope.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


MAX_GLOBAL_SETTLE_MS = 10000
FORBIDDEN_YAML_KEYS = {
    'name_contains',
    'name_not_contains',
    'name_contains_all',
    'name_pattern',
    'role_contains',
    'url_contains',
    'title_contains',
    'contains',
    'regex',
    'matches',
    'fuzzy',
    'complete_key',
    'complete_keys',
    'input_fallback',
}
ALLOW_RE = re.compile(r"#\s*lint-allow:\s*(.*)$")
ACTION_METHODS = {'click', 'paste', 'press', 'type_text'}
CRITICAL_DRIVER_STEPS = {'attach', 'prompt', 'send', 'extract_primary', 'extract_additional'}


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    label: str
    why: str
    text: str = ""


def is_consultation_v2_yaml(path: Path) -> bool:
    return len(path.parts) >= 3 and path.parts[0] == 'consultation_v2' and path.parts[1] == 'platforms' and path.suffix == '.yaml'


def is_consultation_v2_python(path: Path) -> bool:
    return len(path.parts) >= 2 and path.parts[0] == 'consultation_v2' and path.suffix == '.py'


def all_targets() -> list[Path]:
    yaml_targets = sorted(Path('consultation_v2/platforms').rglob('*.yaml'))
    py_targets = sorted(
        path for path in Path('consultation_v2').rglob('*.py')
        if '__pycache__' not in path.parts
    )
    return yaml_targets + py_targets


def staged_targets() -> list[Path]:
    out = subprocess.run(
        ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMRTUXB'],
        capture_output=True, text=True, check=True,
    ).stdout
    targets: list[Path] = []
    for raw in out.splitlines():
        path = Path(raw)
        if not path.exists():
            continue
        if is_consultation_v2_yaml(path) or is_consultation_v2_python(path):
            targets.append(path)
    return sorted(dict.fromkeys(targets))


def explicit_targets(paths: list[str]) -> list[Path]:
    return [Path(p) for p in paths]


def allowed(line: str) -> bool:
    allow = ALLOW_RE.search(line)
    return bool(allow and allow.group(1).strip())


def lines_for_key(lines: list[str], key: str) -> list[tuple[int, str]]:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:")
    matches: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        logical = line.split('#', 1)[0].rstrip()
        if pattern.match(logical):
            matches.append((idx, line.rstrip()))
    return matches


def scan_yaml_schema(path: Path, source: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        data = yaml.safe_load(source) or {}
    except yaml.YAMLError as exc:
        findings.append(Finding(str(path), 1, 'yaml-parse-error', str(exc)))
        return findings

    lines = source.splitlines()
    if not isinstance(data, dict):
        findings.append(Finding(str(path), 1, 'yaml-root-type', 'top-level YAML node must be a mapping'))
        return findings

    for idx, line in enumerate(lines, start=1):
        if ALLOW_RE.search(line):
            findings.append(Finding(
                str(path), idx, 'yaml-lint-allow',
                'consultation_v2 YAML forbids lint-allow escape hatches',
                line.rstrip(),
            ))

    if is_consultation_v2_yaml(path):
        settle = data.get('settle')
        if not isinstance(settle, dict):
            findings.append(Finding(str(path), 1, 'yaml-settle-missing',
                                    'consultation_v2 platform YAML must define top-level settle block'))
        else:
            required = ('default_ms', 'navigate_ms', 'attach_ms', 'rescan_attempts')
            missing = [key for key in required if key not in settle]
            if missing:
                findings.append(Finding(str(path), 1, 'yaml-settle-missing-keys',
                                        f'settle block missing keys: {missing}'))
            for key in ('default_ms', 'navigate_ms', 'attach_ms'):
                if key not in settle:
                    continue
                try:
                    value = int(settle[key])
                except (TypeError, ValueError):
                    findings.append(Finding(str(path), 1, 'yaml-settle-type',
                                            f'settle.{key} must be an integer'))
                    continue
                if value > MAX_GLOBAL_SETTLE_MS:
                    findings.append(Finding(str(path), 1, 'yaml-settle-max',
                                            f'settle.{key} exceeds MAX_GLOBAL_SETTLE_MS={MAX_GLOBAL_SETTLE_MS}'))
            if 'rescan_attempts' in settle:
                try:
                    attempts = int(settle['rescan_attempts'])
                except (TypeError, ValueError):
                    findings.append(Finding(str(path), 1, 'yaml-settle-type',
                                            'settle.rescan_attempts must be an integer'))
                else:
                    if attempts < 1:
                        findings.append(Finding(str(path), 1, 'yaml-settle-range',
                                                'settle.rescan_attempts must be >= 1'))

    def walk(node: object, prefix: str = '') -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_name = str(key)
                current = f'{prefix}.{key_name}' if prefix else key_name
                if key_name in FORBIDDEN_YAML_KEYS:
                    for loc in lines_for_key(lines, key_name):
                        findings.append(Finding(
                            str(path), loc[0], f'yaml-forbidden-{key_name}',
                            f'Forbidden consultation_v2 matcher key: {key_name}',
                            loc[1],
                        ))
                if key_name == 'name' and (not isinstance(value, str) or not value):
                    for loc in lines_for_key(lines, key_name):
                        findings.append(Finding(
                            str(path), loc[0], 'yaml-empty-name',
                            'YAML name matchers must be exact non-empty strings',
                            loc[1],
                        ))
                walk(value, current)
        elif isinstance(node, list):
            for item in node:
                walk(item, prefix)

    walk(data)
    return findings


class PythonContractVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self.func_stack: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.func_stack.append(node.name)
        self.generic_visit(node)
        self.func_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.func_stack.append(node.name)
        self.generic_visit(node)
        self.func_stack.pop()

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        if self._in_contract_function() and self._is_platform_branch(node.test):
            self.findings.append(Finding(
                str(self.path),
                getattr(node, 'lineno', 1),
                'py-platform-branch',
                'driver-side platform branching is forbidden in consultation_v2 python',
                ast.get_source_segment(self.source, node) or '',
            ))
        if self._is_driver_file():
            if self._is_paste_type_fallback(node):
                self.findings.append(Finding(
                    str(self.path),
                    getattr(node, 'lineno', 1),
                    'py-paste-type-fallback',
                    'driver must choose one file/prompt entry primitive; paste-to-type fallback chains are forbidden',
                    ast.get_source_segment(self.source, node) or '',
                ))
            if self._content_empty_test(node.test) and self._body_has_runtime_action(node.body):
                self.findings.append(Finding(
                    str(self.path),
                    getattr(node, 'lineno', 1),
                    'py-action-retry',
                    'driver must not perform another UI action after an action produced empty content',
                    ast.get_source_segment(self.source, node) or '',
                ))
            if self._miss_test(node.test) and self._body_has_critical_success_return(node.body):
                self.findings.append(Finding(
                    str(self.path),
                    getattr(node, 'lineno', 1),
                    'py-silent-proceed-on-miss',
                    'driver must not record success/return True from a critical miss branch',
                    ast.get_source_segment(self.source, node) or '',
                ))
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        if not self._in_contract_function():
            self.generic_visit(node)
            return
        if node.type is None:
            self.findings.append(Finding(
                str(self.path), getattr(node, 'lineno', 1), 'py-bare-except',
                'bare except is forbidden in consultation_v2 python',
                ast.get_source_segment(self.source, node) or '',
            ))
        if self._body_is_pass_only(node.body):
            self.findings.append(Finding(
                str(self.path), getattr(node, 'lineno', 1), 'py-except-pass',
                'exception handler must not swallow errors with pass',
                ast.get_source_segment(self.source, node) or '',
            ))
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        if self._in_contract_function() and self._body_is_pass_only(node.finalbody):
            self.findings.append(Finding(
                str(self.path), getattr(node, 'lineno', 1), 'py-finally-pass',
                'finally block body is only pass; silent cleanup placeholder is forbidden',
                ast.get_source_segment(self.source, node) or '',
            ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if self._in_contract_function() and self._is_subprocess_check_false(node):
            self.findings.append(Finding(
                str(self.path), getattr(node, 'lineno', 1), 'py-subprocess-check-false',
                'subprocess(check=False) hides failure in consultation_v2',  # lint-allow: diagnostic string, not subprocess configuration
                ast.get_source_segment(self.source, node) or '',
            ))
        if self._is_driver_file() and self._is_runtime_action_call(node):
            if self._is_coordinate_only_click(node):
                self.findings.append(Finding(
                    str(self.path),
                    getattr(node, 'lineno', 1),
                    'py-coordinate-only-downgrade',
                    'driver code must not downgrade a click to coordinate_only',
                    ast.get_source_segment(self.source, node) or '',
                ))
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        if self._in_contract_function() and self._looks_like_element_ref(node.value):
            self.findings.append(Finding(
                str(self.path), getattr(node, 'lineno', 1), 'py-validator-element-ref',
                'validate functions must return Match/NoMatch data, not live element refs',
                ast.get_source_segment(self.source, node) or '',
            ))
        self.generic_visit(node)

    def _is_platform_branch(self, test: ast.AST) -> bool:
        if not isinstance(test, ast.Compare):
            return False
        if len(test.ops) != 1 or not isinstance(test.ops[0], (ast.Eq, ast.NotEq)):
            return False
        left = test.left
        if not isinstance(left, ast.Name) or left.id not in {'platform', 'platform_name'}:
            return False
        right = test.comparators[0]
        return isinstance(right, ast.Constant) and isinstance(right.value, str)

    def _body_is_pass_only(self, body: list[ast.stmt]) -> bool:
        return bool(body) and all(isinstance(stmt, ast.Pass) for stmt in body)

    def _in_contract_function(self) -> bool:
        if not self.func_stack:
            return False
        current = self.func_stack[-1]
        return (
            current == 'match_or_halt'
            or current.startswith('_validate')
            or current.startswith('validate_')
        )

    def _is_driver_file(self) -> bool:
        return (
            'drivers' in self.path.parts
            and self.path.name != 'base.py'
            and self.path.suffix == '.py'
        )

    def _runtime_action_name(self, node: ast.Call) -> str | None:
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in ACTION_METHODS:
            return None
        owner = fn.value
        if not isinstance(owner, ast.Attribute) or owner.attr != 'runtime':
            return None
        if not isinstance(owner.value, ast.Name) or owner.value.id != 'self':
            return None
        return fn.attr

    def _is_runtime_action_call(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Call) and self._runtime_action_name(node) is not None

    def _is_coordinate_only_click(self, node: ast.Call) -> bool:
        if self._runtime_action_name(node) != 'click':
            return False
        for kw in node.keywords:
            if kw.arg == 'strategy' and isinstance(kw.value, ast.Constant):
                return kw.value.value == 'coordinate_only'
        return False

    def _first_arg_name(self, node: ast.Call) -> str | None:
        if not node.args:
            return None
        first = node.args[0]
        if isinstance(first, ast.Name):
            return first.id
        if isinstance(first, ast.Attribute):
            return first.attr
        return None

    def _miss_test(self, test: ast.AST) -> bool:
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return isinstance(test.operand, ast.Name)
        if isinstance(test, ast.Compare):
            return (
                isinstance(test.left, ast.Name)
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.Is)
                and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value is None
            )
        if isinstance(test, ast.BoolOp):
            return any(self._miss_test(value) for value in test.values)
        return False

    def _content_empty_test(self, test: ast.AST) -> bool:
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return isinstance(test.operand, ast.Name) and test.operand.id in {'content', 'clipboard'}
        if isinstance(test, ast.BoolOp):
            return any(self._content_empty_test(value) for value in test.values)
        return False

    def _is_paste_type_fallback(self, node: ast.If) -> bool:
        test = node.test
        if not (
            isinstance(test, ast.UnaryOp)
            and isinstance(test.op, ast.Not)
            and isinstance(test.operand, ast.Call)
            and self._runtime_action_name(test.operand) == 'paste'
        ):
            return False
        return any(
            isinstance(child, ast.Call) and self._runtime_action_name(child) == 'type_text'
            for stmt in node.body
            for child in ast.walk(stmt)
        )

    def _body_has_runtime_action(self, body: list[ast.stmt]) -> bool:
        return any(
            isinstance(node, ast.Call) and self._is_runtime_action_call(node)
            for stmt in body
            for node in ast.walk(stmt)
        )

    def _body_has_critical_success_return(self, body: list[ast.stmt]) -> bool:
        saw_critical_success_step = False
        saw_true_return = False
        for stmt in body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call) and self._is_success_add_step(node):
                    saw_critical_success_step = True
                if (
                    isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Constant)
                    and node.value.value is True
                ):
                    saw_true_return = True
        return saw_critical_success_step and saw_true_return

    def _is_success_add_step(self, node: ast.Call) -> bool:
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr != 'add_step':
            return False
        if len(node.args) < 2:
            return False
        step_arg = node.args[0]
        if not isinstance(step_arg, ast.Constant) or step_arg.value not in CRITICAL_DRIVER_STEPS:
            return False
        success_arg = node.args[1]
        return isinstance(success_arg, ast.Constant) and success_arg.value is True

    def _is_subprocess_check_false(self, node: ast.Call) -> bool:
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in {'run', 'call', 'Popen'}:
            return False
        base = fn.value
        if not isinstance(base, ast.Name) or base.id != 'subprocess':
            return False
        for kw in node.keywords:
            if kw.arg == 'check' and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                return True
        return False

    def _looks_like_element_ref(self, value: ast.AST | None) -> bool:
        if value is None:
            return False
        if isinstance(value, ast.Call):
            if isinstance(value.func, ast.Name) and value.func.id in {
                'find_first', 'find_last', 'find_elements', 'find_menu_items', 'match_or_halt'
            }:
                return True
        if isinstance(value, ast.Name) and value.id in {'element', 'item', 'trigger', 'ref', 'element_ref'}:
            return True
        if isinstance(value, ast.Attribute) and value.attr in {'element', 'item', 'trigger', 'ref'}:
            return True
        return False


def scan_python_contract(path: Path, source: str) -> list[Finding]:
    if path.name == '__init__.py':
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [Finding(str(path), exc.lineno or 1, 'py-syntax-error', str(exc))]
    visitor = PythonContractVisitor(path)
    visitor.source = source
    visitor.tree = tree
    visitor.visit(tree)
    return visitor.findings


def scan_file(path: Path) -> list[Finding]:
    if not path.exists():
        raise FileNotFoundError(path)
    source = path.read_text(encoding='utf-8')
    findings: list[Finding] = []
    if is_consultation_v2_yaml(path):
        findings.extend(scan_yaml_schema(path, source))
    elif is_consultation_v2_python(path):
        findings.extend(scan_python_contract(path, source))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--all', action='store_true', help='scan the consultation_v2 contract baseline')
    ap.add_argument('--staged', action='store_true', help='scan staged files in scope')
    ap.add_argument('files', nargs='*', help='explicit files to scan')
    args = ap.parse_args()

    modes = sum(bool(mode) for mode in (args.all, args.staged, bool(args.files)))
    if modes != 1:
        ap.error('specify exactly one of --all, --staged, or explicit files')
        return 2

    if args.all:
        targets = all_targets()
    elif args.staged:
        targets = staged_targets()
    else:
        targets = explicit_targets(args.files)

    findings: list[Finding] = []
    unreadable: list[str] = []
    for path in targets:
        try:
            findings.extend(scan_file(path))
        except (FileNotFoundError, UnicodeDecodeError) as exc:
            unreadable.append(f'{path}: {exc}')

    if unreadable:
        print('consultation_v2 contract lint ERROR — unreadable targets:', file=sys.stderr)
        for item in unreadable:
            print(f'  {item}', file=sys.stderr)
        return 2

    if not findings:
        print(f'consultation_v2 contract lint CLEAN — {len(targets)} file(s) scanned, 0 findings')
        return 0

    by_label: dict[str, int] = {}
    for finding in findings:
        by_label[finding.label] = by_label.get(finding.label, 0) + 1
        if finding.text:
            print(f'{finding.path}:{finding.line_no}: [{finding.label}] {finding.text}')
        else:
            print(f'{finding.path}:{finding.line_no}: [{finding.label}]')
        print(f'    -> {finding.why}')

    print()
    print(f'consultation_v2 contract lint FAIL — {len(findings)} finding(s) across {len(targets)} file(s):')
    for label, count in sorted(by_label.items(), key=lambda item: (-item[1], item[0])):
        print(f'    {count:>3}  {label}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
