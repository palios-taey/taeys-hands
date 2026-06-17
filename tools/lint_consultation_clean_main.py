#!/usr/bin/env python3
"""Mechanical gates for the consultation-clean-main contract.

This gate is deliberately baseline-aware for p1:
- known legacy entrypoints may exist until p2/p6 cutover, but edits to them must
  turn them into fail-loud stubs or forwarders.
- known loose matcher debt may exist only where an exact line has a
  ``lint-allow`` comment or is recorded as a p1 baseline debt line.
- production display substrate files may not be edited through normal commits.

Usage:
  python3 tools/lint_consultation_clean_main.py --all
  python3 tools/lint_consultation_clean_main.py --staged
  python3 tools/lint_consultation_clean_main.py path/to/file ...
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


CHAT_PLATFORMS = {"chatgpt", "claude", "gemini", "grok", "perplexity"}
ALLOW_RE = re.compile(r"#\s*lint-allow:\s*(.*)$")

FORBIDDEN_MATCHER_KEYS = {
    "name_contains",
    "name_not_contains",
    "name_contains_all",
    "name_pattern",
    "role_contains",
    "url_contains",
    "title_contains",
    "contains",
    "regex",
    "matches",
    "fuzzy",
    "name_contains_model",
    "filename_contains",
    "file_contains",
}

BANNED_CLEAN_IMPORTS = {
    "agents",
    "monitor.central",
    "monitor.daemon",
    "scripts.consultation",
    "server",
    "tools.attach",
    "tools.dropdown",
    "tools.extract",
    "tools.mode_select",
    "tools.monitors",
    "tools.send",
    "tools.send_message",
}

KNOWN_LEGACY_ENTRYPOINTS = {
    "scripts/consultation.py",
    "scripts/run_consultation_v2.py",
    "server.py",
    "tools/send.py",
    "tools/send_message.py",
    "tools/extract.py",
    "tools/attach.py",
    "tools/monitors.py",
    "agents/hmm_bot.py",
    "agents/dpo_bot.py",
    "agents/sft_gen_bot.py",
    "agents/training_gen_bot.py",
    "agents/unified_bot.py",
    "agents/conductor_bot.py",
    "agents/local_llm_agent.py",
}

NON_CONSULTATION_ENTRYPOINTS = {
    "scripts/build_consultation.py",
    "agents/login_bot.py",
    "agents/social_bot.py",
    "agents/x_reply_bot.py",
}

ENTRYPOINT_PATTERNS = (
    "scripts/*consult*.py",
    "server.py",
    "tools/send*.py",
    "tools/extract.py",
    "tools/attach.py",
    "tools/monitors.py",
    "agents/*bot.py",
    "agents/*agent.py",
)

LEGACY_EDIT_MARKERS = (
    "LEGACY_DO_NOT_USE",
    "fail-loud",
    "fail loud",
    "forwarder",
    "single clean entrypoint",
)

PROTECTED_SUBSTRATE_PATTERNS = (
    "systemd/user/taey-display-*.service",
    "systemd/user/taey-xvfb@.service",
    "systemd/user/taey-bus-watcher@.service",
    "systemd/user/firefox-user.js",
    "scripts/install_machine_displays.sh",
    "scripts/setup_display.sh",
    "scripts/setup_dpo_displays.sh",
    "scripts/setup_parallel_hmm.sh",
    "scripts/launch_isolated_display.sh",
    "scripts/launch_team.sh",
    "scripts/manage_displays.sh",
    "scripts/restart_display.sh",
    "scripts/bus_watcher.sh",
)

REQUIRED_STOP_CONDITION_IDS = {
    "unsupported_request_mapping",
    "missing_identity_package",
    "display_substrate_unhealthy",
    "navigation_validation_failed",
    "setup_validation_failed",
    "attachment_validation_failed",
    "prompt_readiness_failed",
    "send_stop_missing",
    "session_url_capture_failed",
    "monitor_registration_failed",
    "generation_stalled",
    "extraction_failed",
    "notification_ack_missing",
    "manual_recovery_required",
    "side_effect_uncertain",
    "duplicate_send_risk",
}

BASELINE_PY_DEBT = {
    # base.py debt shifted +3 lines by p2-dispatch-lock (3 added imports +
    # the _display_dispatch_lock block precede validation_passes). The debt
    # itself is UNCHANGED — same url_contains/file-chip lines in
    # validation_passes, still p1 baseline (slated for p5 platform migration);
    # only its line numbers moved. Re-pinned to the new true lines so the gate
    # keeps recognizing it as known debt rather than NEW.
    ("consultation_v2/drivers/base.py", 44, "py-forbidden-key-url_contains"),
    ("consultation_v2/drivers/base.py", 45, "py-forbidden-key-url_contains"),
    ("consultation_v2/drivers/base.py", 87, "py-file-chip-substring"),
    ("consultation_v2/snapshot.py", 57, "py-forbidden-key-name_contains"),
    ("consultation_v2/snapshot.py", 58, "py-forbidden-key-name_contains"),
    ("consultation_v2/snapshot.py", 59, "py-file-chip-substring"),
    ("consultation_v2/snapshot.py", 61, "py-forbidden-key-name_not_contains"),
    ("consultation_v2/snapshot.py", 62, "py-forbidden-key-name_not_contains"),
    ("consultation_v2/snapshot.py", 63, "py-file-chip-substring"),
    ("consultation_v2/snapshot.py", 65, "py-forbidden-key-name_contains_all"),
    ("consultation_v2/snapshot.py", 66, "py-forbidden-key-name_contains_all"),
    ("consultation_v2/snapshot.py", 67, "py-file-chip-substring"),
    ("consultation_v2/snapshot.py", 69, "py-forbidden-key-name_pattern"),
    ("consultation_v2/snapshot.py", 70, "py-forbidden-key-name_pattern"),
    ("consultation_v2/snapshot.py", 75, "py-forbidden-key-role_contains"),
    ("consultation_v2/snapshot.py", 76, "py-forbidden-key-role_contains"),
    ("consultation_v2/snapshot.py", 97, "py-forbidden-key-name_contains"),
    ("consultation_v2/snapshot.py", 98, "py-file-chip-substring"),
}


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    label: str
    why: str
    text: str = ""


def rel(path: Path) -> str:
    return path.as_posix()


def allowed(line: str) -> bool:
    allow = ALLOW_RE.search(line)
    return bool(allow and allow.group(1).strip())


def strip_trailing_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if ch == "#" and not in_single and not in_double:
            return line[:idx].rstrip()
    return line.rstrip()


def is_chat_yaml(path: Path) -> bool:
    if path.suffix not in {".yaml", ".yml"}:
        return False
    parts = path.parts
    return (
        len(parts) == 2
        and parts[0] == "platforms"
        and path.stem in CHAT_PLATFORMS
    ) or (
        len(parts) == 3
        and parts[0] == "consultation_v2"
        and parts[1] == "platforms"
        and path.stem in CHAT_PLATFORMS
    )


def is_clean_python(path: Path) -> bool:
    return len(path.parts) >= 2 and path.parts[0] == "consultation_v2" and path.suffix == ".py"


def is_entrypoint_candidate(path: Path) -> bool:
    value = rel(path)
    return any(fnmatch.fnmatch(value, pattern) for pattern in ENTRYPOINT_PATTERNS)


def is_protected_substrate(path: Path) -> bool:
    value = rel(path)
    return any(fnmatch.fnmatch(value, pattern) for pattern in PROTECTED_SUBSTRATE_PATTERNS)


def all_targets() -> list[Path]:
    roots = [
        Path("platforms"),
        Path("consultation_v2"),
        Path("scripts"),
        Path("tools"),
        Path("monitor"),
        Path("agents"),
        Path("systemd/user"),
        Path(".githooks"),
        Path(".github/workflows"),
    ]
    targets: list[Path] = [Path("server.py"), Path("consultation_v2/stop_conditions.py")]
    for root in roots:
        if not root.exists():
            continue
        targets.extend(path for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    return sorted(dict.fromkeys(path for path in targets if path.exists()))


def staged_targets() -> list[Path]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    targets = [Path(raw) for raw in out.splitlines() if raw.strip()]
    existing = [path for path in targets if path.exists()]
    if Path("consultation_v2/stop_conditions.py").exists():
        existing.append(Path("consultation_v2/stop_conditions.py"))
    return sorted(dict.fromkeys(existing))


def scan_yaml(path: Path, source: str) -> list[Finding]:
    if not is_chat_yaml(path):
        return []
    findings: list[Finding] = []
    for idx, line in enumerate(source.splitlines(), start=1):
        logical = strip_trailing_comment(line)
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", logical)
        if not match:
            continue
        key = match.group(1)
        if key not in FORBIDDEN_MATCHER_KEYS:
            continue
        if allowed(line):
            continue
        findings.append(Finding(
            rel(path),
            idx,
            f"yaml-forbidden-{key}",
            f"forbidden loose matcher key in active chat YAML: {key}",
            line.rstrip(),
        ))
    return findings


def import_targets(tree: ast.AST) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    return targets


def forbidden_literal_findings(path: Path, source: str) -> list[Finding]:
    findings: list[Finding] = []
    for idx, line in enumerate(source.splitlines(), start=1):
        logical = strip_trailing_comment(line)
        if allowed(line):
            continue
        for key in FORBIDDEN_MATCHER_KEYS:
            if repr(key) not in logical and f'"{key}"' not in logical:
                continue
            label = f"py-forbidden-key-{key}"
            finding = Finding(
                rel(path),
                idx,
                label,
                f"clean-engine python must not handle forbidden matcher key: {key}",
                line.rstrip(),
            )
            if (finding.path, finding.line_no, finding.label) not in BASELINE_PY_DEBT:
                findings.append(finding)
        if "probe in name" in logical or "probe in name_lower" in logical:
            finding = Finding(
                rel(path),
                idx,
                "py-file-chip-substring",
                "filename or URL substring matching is forbidden evidence in clean-engine code",
                line.rstrip(),
            )
            if (finding.path, finding.line_no, finding.label) not in BASELINE_PY_DEBT:
                findings.append(finding)
    return findings


def scan_python(path: Path, source: str) -> list[Finding]:
    if not is_clean_python(path):
        return []
    findings = forbidden_literal_findings(path, source)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return findings + [Finding(rel(path), exc.lineno or 1, "py-syntax-error", str(exc))]
    for target in import_targets(tree):
        for banned in BANNED_CLEAN_IMPORTS:
            if target == banned or target.startswith(f"{banned}."):
                findings.append(Finding(
                    rel(path),
                    1,
                    "py-legacy-import",
                    f"clean-engine python imports legacy platform-driving module {target}",
                ))
    return findings


def scan_entrypoint(path: Path, source: str, *, staged: bool) -> list[Finding]:
    if not is_entrypoint_candidate(path):
        return []
    value = rel(path)
    if value in NON_CONSULTATION_ENTRYPOINTS:
        return []
    if value not in KNOWN_LEGACY_ENTRYPOINTS:
        return [Finding(
            value,
            1,
            "new-consultation-entrypoint",
            "new runnable consultation-like entrypoint is forbidden before the p2 single-entrypoint decision",
        )]
    if staged and not any(marker.lower() in source.lower() for marker in LEGACY_EDIT_MARKERS):
        return [Finding(
            value,
            1,
            "legacy-entrypoint-edit",
            "known legacy entrypoint changed without becoming a fail-loud stub or pure forwarder",
        )]
    return []


def scan_substrate(path: Path, *, staged: bool) -> list[Finding]:
    if staged and is_protected_substrate(path):
        return [Finding(
            rel(path),
            1,
            "protected-display-substrate-edit",
            "production DBUS/Xvfb/Firefox substrate edits require display-substrate audit plus production verification",
        )]
    return []


def literal_string_set(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        result = set()
        for item in node.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                result.add(item.value)
        return result
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset" and node.args:
        return literal_string_set(node.args[0])
    return set()


def scan_stop_conditions() -> list[Finding]:
    path = Path("consultation_v2/stop_conditions.py")
    if not path.exists():
        return [Finding(rel(path), 1, "stop-conditions-missing", "machine-readable stop condition IDs are required")]
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [Finding(rel(path), exc.lineno or 1, "stop-conditions-syntax", str(exc))]
    ids: set[str] = set()
    refs: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "STOP_CONDITION_IDS" in names:
                ids = literal_string_set(node.value)
            if "STOP_CONDITION_REFS" in names and isinstance(node.value, ast.Dict):
                for key, value in zip(node.value.keys, node.value.values):
                    if (
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        refs[key.value] = value.value
    findings: list[Finding] = []
    missing = sorted(REQUIRED_STOP_CONDITION_IDS - ids)
    if missing:
        findings.append(Finding(rel(path), 1, "stop-conditions-missing-ids", f"missing stop condition IDs: {missing}"))
    missing_refs = sorted(REQUIRED_STOP_CONDITION_IDS - set(refs))
    if missing_refs:
        findings.append(Finding(rel(path), 1, "stop-conditions-missing-refs", f"missing stop condition refs: {missing_refs}"))
    for stop_id in sorted(REQUIRED_STOP_CONDITION_IDS & set(refs)):
        findings.extend(validate_contract_ref(path, stop_id, refs[stop_id]))
    return findings


def validate_contract_ref(path: Path, stop_id: str, ref: str) -> list[Finding]:
    match = re.fullmatch(r"([^:]+):(\d+)(?:-(\d+))?", ref)
    if not match:
        return [Finding(rel(path), 1, "stop-condition-ref-format", f"{stop_id} has invalid ref format: {ref}")]
    ref_path = Path(match.group(1))
    start = int(match.group(2))
    end = int(match.group(3) or match.group(2))
    if start > end:
        return [Finding(rel(path), 1, "stop-condition-ref-range", f"{stop_id} has inverted ref range: {ref}")]
    if not ref_path.exists():
        return [Finding(rel(path), 1, "stop-condition-ref-missing-file", f"{stop_id} references missing file: {ref}")]
    line_count = len(ref_path.read_text(encoding="utf-8").splitlines())
    if end > line_count:
        return [Finding(rel(path), 1, "stop-condition-ref-missing-line", f"{stop_id} references missing line in {ref}")]
    return []


def scan_file(path: Path, *, staged: bool) -> list[Finding]:
    if not path.exists():
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [Finding(rel(path), 1, "unreadable-file", str(exc))]
    findings: list[Finding] = []
    findings.extend(scan_yaml(path, source))
    findings.extend(scan_python(path, source))
    findings.extend(scan_entrypoint(path, source, staged=staged))
    findings.extend(scan_substrate(path, staged=staged))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="scan the current repo baseline")
    parser.add_argument("--staged", action="store_true", help="scan staged files plus stop-condition IDs")
    parser.add_argument("files", nargs="*", help="explicit files to scan")
    args = parser.parse_args()

    modes = sum(bool(mode) for mode in (args.all, args.staged, bool(args.files)))
    if modes != 1:
        parser.error("specify exactly one of --all, --staged, or explicit files")
        return 2

    if args.all:
        targets = all_targets()
        staged = False
    elif args.staged:
        targets = staged_targets()
        staged = True
    else:
        targets = [Path(item) for item in args.files]
        staged = False

    findings: list[Finding] = []
    for path in targets:
        findings.extend(scan_file(path, staged=staged))
    findings.extend(scan_stop_conditions())

    if not findings:
        print(f"consultation clean-main gate CLEAN - {len(targets)} file(s) scanned, 0 findings")
        return 0

    by_label: dict[str, int] = {}
    for finding in findings:
        by_label[finding.label] = by_label.get(finding.label, 0) + 1
        if finding.text:
            print(f"{finding.path}:{finding.line_no}: [{finding.label}] {finding.text}")
        else:
            print(f"{finding.path}:{finding.line_no}: [{finding.label}]")
        print(f"    -> {finding.why}")
    print()
    print(f"consultation clean-main gate FAIL - {len(findings)} finding(s) across {len(targets)} file(s):")
    for label, count in sorted(by_label.items(), key=lambda item: (-item[1], item[0])):
        print(f"    {count:>3}  {label}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
