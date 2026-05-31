#!/usr/bin/env python3
"""Mechanical integrity gate for consultation_v2 YAML + driver rules.

This gate is intentionally narrow: it only scans the consultation_v2 YAML
catalog and driver/runtime Python surface named in p0-gate. Anything it
flags is a hard failure for commit/CI unless the exact line carries:

    # lint-allow: <non-empty reason>

Usage:
  tools/lint_no_yaml_silent_fallbacks.py --all
  tools/lint_no_yaml_silent_fallbacks.py --staged
  tools/lint_no_yaml_silent_fallbacks.py path/to/file ...
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ALLOW_RE = re.compile(r"#\s*lint-allow:\s*(.*)$")


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    label: str
    why: str


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    label: str
    why: str
    text: str


YAML_RULES: list[Rule] = [
    Rule(re.compile(r"name_contains:"), "yaml-name-contains",
         "THE RULE §1: YAML must not use name_contains in consultation_v2/platforms"),
    Rule(re.compile(r"name_pattern:"), "yaml-name-pattern",
         "THE RULE §1: YAML must not use name_pattern in consultation_v2/platforms"),
    Rule(re.compile(r"role_contains:"), "yaml-role-contains",
         "THE RULE §1: YAML must not use role_contains in consultation_v2/platforms"),
    Rule(re.compile(r"name_contains_model:"), "yaml-name-contains-model",
         "model-specific substring fallback is forbidden everywhere"),
]

PY_RULES: list[Rule] = [
    Rule(re.compile(r"\bif\s+platform\s*=="), "py-if-platform-eq",
         "driver-side platform branching is forbidden in consultation_v2 python"),
    Rule(re.compile(r"\bif\s+platform_name\s*=="), "py-if-platform-name-eq",
         "driver-side platform branching is forbidden in consultation_v2 python"),
    Rule(re.compile(r"^\s*except\s*:"), "py-bare-except",
         "bare except swallows control-flow and violates HALT-LOUD"),
    Rule(re.compile(r"except\b[^:\n]*:\s*pass\s*$"), "py-except-pass",
         "exception swallowing with pass is forbidden"),
    Rule(re.compile(r"^\s*finally\s*:\s*pass\s*$"), "py-finally-pass-inline",
         "finally: pass is dead cleanup and forbidden"),
    Rule(re.compile(r"\bcheck\s*=\s*False\b"), "py-subprocess-check-false",
         "subprocess(check=False) hides failure in consultation_v2"),
    Rule(re.compile(r"\bname_contains_model\b"), "py-name-contains-model",
         "model-specific substring fallback is forbidden everywhere"),
]


def is_consultation_v2_yaml(path: Path) -> bool:
    parts = path.parts
    return len(parts) >= 3 and parts[0] == "consultation_v2" and parts[1] == "platforms" and path.suffix == ".yaml"


def is_consultation_v2_python(path: Path) -> bool:
    parts = path.parts
    return len(parts) >= 2 and parts[0] == "consultation_v2" and path.suffix == ".py"


def all_targets() -> list[Path]:
    yaml_targets = sorted(Path("consultation_v2/platforms").glob("*.yaml"))
    py_targets = sorted(p for p in Path("consultation_v2").rglob("*.py") if "__pycache__" not in p.parts)
    return yaml_targets + py_targets


def staged_targets() -> list[Path]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        capture_output=True, text=True, check=True,
    ).stdout
    targets: list[Path] = []
    for raw in out.splitlines():
        path = Path(raw)
        if not path.exists():
            continue
        if is_consultation_v2_yaml(path) or is_consultation_v2_python(path):
            targets.append(path)
        elif path == Path("tools/lint_no_yaml_silent_fallbacks.py"):
            targets.append(path)
        elif path == Path(".githooks/pre-commit"):
            targets.append(path)
        elif path == Path(".github/workflows/yaml-integrity-gate.yml"):
            targets.append(path)
    return sorted(dict.fromkeys(targets))


def explicit_targets(paths: list[str]) -> list[Path]:
    return [Path(p) for p in paths]


def allowed(line: str) -> bool:
    allow = ALLOW_RE.search(line)
    return bool(allow and allow.group(1).strip())


def scan_file(path: Path) -> list[Finding]:
    if path.resolve() == Path(__file__).resolve():
        return []

    if not path.exists():
        raise FileNotFoundError(path)

    findings: list[Finding] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    rules: list[Rule] = []
    if is_consultation_v2_yaml(path):
        rules = YAML_RULES
    elif is_consultation_v2_python(path):
        rules = PY_RULES
    else:
        return findings

    for idx, line in enumerate(lines, start=1):
        for rule in rules:
            if not rule.pattern.search(line):
                continue
            if allowed(line):
                continue
            findings.append(Finding(str(path), idx, rule.label, rule.why, line.rstrip()))

    if is_consultation_v2_python(path):
        findings.extend(scan_finally_blocks(path, lines))
    return findings


def scan_finally_blocks(path: Path, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for idx, line in enumerate(lines):
        if not re.match(r"^\s*finally\s*:\s*$", line):
            continue
        if allowed(line):
            continue
        indent = len(line) - len(line.lstrip(" "))
        body_line = None
        for probe in lines[idx + 1:]:
            if not probe.strip():
                continue
            probe_indent = len(probe) - len(probe.lstrip(" "))
            if probe_indent <= indent:
                break
            body_line = probe
            break
        if body_line and re.match(r"^\s*pass\s*$", body_line):
            findings.append(Finding(
                str(path), idx + 1, "py-finally-pass",
                "finally block body is only pass; silent cleanup placeholder is forbidden",
                line.rstrip(),
            ))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="scan consultation_v2 baseline")
    ap.add_argument("--staged", action="store_true", help="scan staged files in scope")
    ap.add_argument("files", nargs="*", help="explicit files to scan")
    args = ap.parse_args()

    modes = sum(bool(mode) for mode in (args.all, args.staged, bool(args.files)))
    if modes != 1:
        ap.error("specify exactly one of --all, --staged, or explicit files")
        return 2

    if args.all:
        targets = all_targets()
        if not targets:
            print("integrity gate ERROR — no consultation_v2 yaml/python targets found", file=sys.stderr)
            return 2
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
            unreadable.append(f"{path}: {exc}")

    if unreadable:
        print("integrity gate ERROR — unreadable targets:", file=sys.stderr)
        for item in unreadable:
            print(f"  {item}", file=sys.stderr)
        return 2

    if not findings:
        print(f"integrity gate CLEAN — {len(targets)} file(s) scanned, 0 findings")
        return 0

    by_label: dict[str, int] = {}
    for finding in findings:
        by_label[finding.label] = by_label.get(finding.label, 0) + 1
        print(f"{finding.path}:{finding.line_no}: [{finding.label}] {finding.text}")
        print(f"    -> {finding.why}")

    print()
    print(f"integrity gate FAIL — {len(findings)} finding(s) across {len(targets)} file(s):")
    for label, count in sorted(by_label.items(), key=lambda item: (-item[1], item[0])):
        print(f"    {count:>3}  {label}")
    print()
    print("Add '# lint-allow: <reason>' on the exact line only when the debt is known and")
    print("explicitly accepted. Empty reasons still fail.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
