#!/usr/bin/env python3
"""lint_exact_match.py — enforce EXACT-MATCH-ONLY in consultation platform YAML.

THE RULE (100_TIMES.md): every element_map entry and every validation spec
matches by exact `name`/`names_any_of` + `role`. NO name_contains /
role_contains / url_contains / wildcards / fallbacks.

THE ONE EXCEPTION (dynamic values — file chips with timestamped names,
response text, generated ids): match the STRUCTURAL element via a typed
locator that is itself exact — `structural:` with exact `role` (+ optional
exact `parent` key and integer `index`/`ordinal`). The leaf text may vary
because it must; the locator does not loosen.

Exit non-zero (fails .githooks/pre-commit) if any loose matcher is found.

Usage:
  python3 consultation_v2/validators/lint_exact_match.py [--staged] [paths...]
Default paths: consultation_v2/platforms/*.yaml
"""
import sys
import subprocess
from pathlib import Path

# Loose matchers that are FORBIDDEN (the structural exception uses 'structural:'
# with exact role/parent/index, so '*_contains' keys are never legitimate).
FORBIDDEN = ("name_contains", "name_not_contains", "name_contains_all",
             "name_pattern", "role_contains", "url_contains",
             "title_contains", "contains", "regex", "matches", "fuzzy",
             "complete_key", "complete_keys", "input_fallback")


def _staged_yaml() -> list:
    out = subprocess.run(["git", "diff", "--cached", "--name-only"],
                         capture_output=True, text=True).stdout.split()
    return [p for p in out if p.endswith((".yaml", ".yml"))
            and ("platforms/" in p)]


def _default_paths() -> list:
    return sorted(str(path) for path in Path("consultation_v2/platforms").rglob("*.yaml"))


def lint(paths: list) -> int:
    findings = []
    for path in paths:
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except FileNotFoundError:
            continue
        for n, line in enumerate(lines, 1):
            stripped = line.split("#", 1)[0]  # ignore trailing comments
            key = stripped.split(":", 1)[0].strip()
            if key in FORBIDDEN:
                findings.append((path, n, key, line.strip()))
            if key == "name" and stripped.split(":", 1)[1].strip() in {'""', "''"}:
                findings.append((path, n, "empty-name", line.strip()))
    if findings:
        print("EXACT-MATCH LINT FAIL — loose matchers are forbidden "
              "(use exact name+role, or a 'structural:' locator for dynamic values):")
        for path, n, key, text in findings:
            print(f"  {path}:{n}  [{key}]  {text}")
        print(f"\n{len(findings)} loose matcher(s) across "
              f"{len(set(f[0] for f in findings))} file(s). Replace each with an "
              f"exact name+role from a LIVE AT-SPI scan, or a structural: locator.")
        return 1
    print(f"EXACT-MATCH LINT PASS — {len(paths)} file(s), 0 loose matchers.")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--staged"]
    if "--staged" in sys.argv:
        paths = _staged_yaml()
        if not paths:
            print("exact-match lint: no staged platform YAML.")
            sys.exit(0)
    else:
        paths = args or _default_paths()
    sys.exit(lint(paths))
