#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.supervised_ui_contract import (  # noqa: E402
    TRAINING_PROTOCOL_COMMIT,
    clear_supervised_policy_cache,
    load_supervised_policy,
)


PAIR_SCHEMA = 'ui_sft_design_rule_pair_v1'
PAIR_LANE = 'ui_supervised_design_rule_v1'
RECEIPT_SCHEMA = 'ui_sft_design_rule_receipt_v1'
VALIDATOR_PATH = 'consultation_v2/validators/validate_supervised_ui_design_rules.py'
TRAINING_REPO = 'palios-taey/palios-training'
TRAINING_COMMIT = '58b108042e66fa508765a6277c033cc5a8f86abd'
HANDS_REPO = 'palios-taey/taeys-hands'
HANDS_COMMIT = '96847ebba90f6031d35cd76d579a75f9b937dc02'
NO_TRACE_CLAIM = 'design-backed rule only; no production trace or tool result'
MAX_CANDIDATE_BYTES = 16 * 1024 * 1024

TRAINING_SOURCES = (
    {
        'path': 'careers-qwen/SFT_STANDARDS_MAP.md',
        'sha256': '6dc6a48486b580671ad80ac8d6a1085f34a89ab26c03d45de53fb238a0507097',
    },
    {
        'path': 'careers-qwen/docs/SFT_SUPERVISED_CAPTURE_DESIGN.md',
        'sha256': '00b820c35428ec200d267fca2d07b30f6a8779da7d945706d24ac97f19811966',
    },
    {
        'path': 'careers-qwen/docs/SFT_SELF_TRAINING_LOOP_PROTOCOL.md',
        'sha256': 'abe750e969c64c5cdbd3efe3b4594022e8f892049b13aab7583210262eec2b22',
    },
    {
        'path': 'careers-qwen/docs/SFT_PAIR_INVENTORY_2026-08-04.json',
        'sha256': '8a577fe2b6bafa53ce820b318adfe9e86ecebcb3ad7dea0d2a234839d148dca0',
    },
)

HANDS_SOURCE_SHA256 = {
    'consultation_v2/supervised_ui_contract.py': (
        'f3be0eeb6c4535529a5e0acf6778335cde9f446b368dadd998b0e75ede7dfcc3'
    ),
    'consultation_v2/supervised_ui_receipts.py': (
        '30a8afe01ce76e40483ed7de32cc73bb1c0da0192576f94e69528858e9394880'
    ),
    'consultation_v2/supervised_ui_seat.py': (
        '5b8517541a4d6ead65b411e8bd18b9d153d873c95dacea10dd1162d46d032efd'
    ),
    'scripts/run_supervised_ui_seat.py': (
        'a454355f4c5dab4f1ce3b7d960522c58b6f106d8f1baf2eb7590d1699e9cd362'
    ),
    'consultation_v2/platforms/chatgpt/supervised_ui.yaml': (
        '50d307f0cd265de420aef6ece6985baa2943a213508fba40dbed0a9e4513e2ba'
    ),
    'consultation_v2/platforms/claude/supervised_ui.yaml': (
        '02ce600e094f0565102fb5ecb97cc7638e50eef14ee963a9592c54a2247d9668'
    ),
    'consultation_v2/platforms/gemini/supervised_ui.yaml': (
        '02ce600e094f0565102fb5ecb97cc7638e50eef14ee963a9592c54a2247d9668'
    ),
    'consultation_v2/platforms/grok/supervised_ui.yaml': (
        '02ce600e094f0565102fb5ecb97cc7638e50eef14ee963a9592c54a2247d9668'
    ),
    'consultation_v2/platforms/perplexity/supervised_ui.yaml': (
        'fd8c76a22eb3a9f5e59dc5dd3b40c85eeda682f0ecd91cbe3db347bbdcfb8400'
    ),
}

RULE_ID = re.compile(r'[a-z][a-z0-9_]{2,63}\Z')
MESSAGE_FORBIDDEN = re.compile(
    r'(?:https?://|www\.|/home/|/tmp/|[A-Za-z]:\\|'
    r'\b(?:10|127|169\.254|172\.(?:1[6-9]|2[0-9]|3[01])|192\.168)\.'
    r'|\b[0-9a-f]{32,64}\b|chatgpt|claude|gemini|grok|perplexity|reddit|nvidia)',
    re.IGNORECASE,
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')


def _strict_object(raw: bytes, line_no: int) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'line {line_no}: duplicate key {key!r}')
            result[key] = value
        return result

    value = json.loads(
        raw.decode('utf-8'),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f'line {line_no}: non-JSON constant {token!r}')
        ),
    )
    if not isinstance(value, dict):
        raise ValueError(f'line {line_no}: pair must be an object')
    return value


def _qualified_symbols(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.add(f'{node.name}.{child.name}')
    return frozenset(symbols)


def _validate_source_tree() -> tuple[list[str], dict[str, frozenset[str]]]:
    errors: list[str] = []
    symbols: dict[str, frozenset[str]] = {}
    for relative_path, expected_sha256 in sorted(HANDS_SOURCE_SHA256.items()):
        path = REPO_ROOT / relative_path
        if not path.is_file() or path.is_symlink():
            errors.append(f'source path is missing or unsafe: {relative_path}')
            continue
        raw = path.read_bytes()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != expected_sha256:
            errors.append(
                f'source drift for {relative_path}: expected {expected_sha256}, got {actual_sha256}'
            )
        if path.suffix == '.py':
            try:
                symbols[relative_path] = _qualified_symbols(path)
            except (SyntaxError, UnicodeDecodeError) as exc:
                errors.append(f'cannot index symbols in {relative_path}: {exc}')
    return errors, symbols


def _validate_live_policy() -> list[str]:
    errors: list[str] = []
    if TRAINING_PROTOCOL_COMMIT != TRAINING_COMMIT:
        errors.append('runtime training protocol commit differs from the validator provenance')
    for platform in ('chatgpt', 'claude', 'gemini', 'grok', 'perplexity'):
        clear_supervised_policy_cache()
        try:
            policy = load_supervised_policy(platform)
        except Exception as exc:
            errors.append(f'cannot load supervised policy {platform}: {type(exc).__name__}: {exc}')
            continue
        for control in policy.controls.values():
            if control.effect_class != 'local' or control.operations != ('focus',):
                errors.append(f'P0 policy {platform}.{control.mapping_key} is not local focus-only')
    return errors


def _private_candidate_bytes(candidate: Path, private_root: Path) -> tuple[bytes | None, list[str]]:
    errors: list[str] = []
    if not candidate.is_absolute() or not private_root.is_absolute():
        return None, ['candidate and private root paths must be absolute']
    try:
        resolved_root = private_root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
    except OSError as exc:
        return None, [f'cannot resolve private candidate boundary: {exc}']
    if resolved_root != private_root or resolved_candidate != candidate:
        errors.append('candidate and private root must not traverse symlinks or aliases')
    if candidate.parent != private_root:
        errors.append('candidate must be a direct child of the exclusive private root')
    public_root = REPO_ROOT.resolve(strict=True)
    if resolved_root.is_relative_to(public_root) or resolved_candidate.is_relative_to(public_root):
        errors.append('private candidate must remain outside the public Hands repository')
    try:
        root_stat = private_root.lstat()
        candidate_stat = candidate.lstat()
    except OSError as exc:
        return None, errors + [f'cannot inspect private candidate boundary: {exc}']
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_IMODE(root_stat.st_mode) != 0o700:
        errors.append('private root must be a directory with exact mode 0700')
    if root_stat.st_uid != os.geteuid():
        errors.append('private root must be owned by the current effective user')
    if not stat.S_ISREG(candidate_stat.st_mode) or stat.S_IMODE(candidate_stat.st_mode) != 0o600:
        errors.append('private candidate must be a regular file with exact mode 0600')
    if candidate_stat.st_uid != os.geteuid():
        errors.append('private candidate must be owned by the current effective user')
    if candidate_stat.st_size > MAX_CANDIDATE_BYTES:
        errors.append(f'private candidate exceeds {MAX_CANDIDATE_BYTES} bytes')
    if errors:
        return None, errors
    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        return None, [f'cannot read private candidate: {exc}']
    return raw, []


def validate_pair(
    row: dict[str, Any],
    line_no: int,
    source_symbols: dict[str, frozenset[str]],
) -> list[str]:
    errors: list[str] = []
    if frozenset(row) != frozenset({'messages', 'meta'}):
        return [f'line {line_no}: top-level keys must be exactly messages and meta']
    messages = row['messages']
    if not isinstance(messages, list) or len(messages) != 3:
        errors.append(f'line {line_no}: messages must contain system, user, assistant')
    else:
        expected_roles = ('system', 'user', 'assistant')
        for index, (message, role) in enumerate(zip(messages, expected_roles, strict=True)):
            if not isinstance(message, dict) or frozenset(message) != frozenset({'role', 'content'}):
                errors.append(f'line {line_no}: message {index} must contain only role and content')
                continue
            if message['role'] != role:
                errors.append(f'line {line_no}: message {index} role must be {role}')
            content = message['content']
            if not isinstance(content, str) or not content.strip() or len(content) > 1600:
                errors.append(f'line {line_no}: message {index} content is invalid')
            elif MESSAGE_FORBIDDEN.search(content):
                errors.append(f'line {line_no}: message {index} contains private or runtime data')

    meta = row['meta']
    if not isinstance(meta, dict) or frozenset(meta) != frozenset({
        'frozen_regression', 'lane', 'provenance', 'rule', 'schema', 'source_class'
    }):
        return errors + [f'line {line_no}: meta keys are incomplete or unknown']
    if meta['schema'] != PAIR_SCHEMA or meta['lane'] != PAIR_LANE:
        errors.append(f'line {line_no}: pair schema or lane mismatch')
    if meta['source_class'] != 'design_rule':
        errors.append(f'line {line_no}: source_class must be design_rule')
    if not isinstance(meta['frozen_regression'], bool):
        errors.append(f'line {line_no}: frozen_regression must be boolean')

    rule = meta['rule']
    if not isinstance(rule, dict) or frozenset(rule) != frozenset({'id', 'validator'}):
        errors.append(f'line {line_no}: rule binding is invalid')
    else:
        rule_id = rule['id']
        if not isinstance(rule_id, str) or RULE_ID.fullmatch(rule_id) is None:
            errors.append(f'line {line_no}: rule id is invalid')
        if rule['validator'] != {'path': VALIDATOR_PATH, 'symbol': 'validate_pair'}:
            errors.append(f'line {line_no}: rule validator binding is invalid')

    provenance = meta['provenance']
    if not isinstance(provenance, dict) or frozenset(provenance) != frozenset({
        'claim', 'hands', 'public_training'
    }):
        return errors + [f'line {line_no}: provenance keys are incomplete or unknown']
    if provenance['claim'] != NO_TRACE_CLAIM:
        errors.append(f'line {line_no}: row must disclaim production-trace evidence')
    if provenance['public_training'] != {
        'commit': TRAINING_COMMIT,
        'repo': TRAINING_REPO,
        'sources': list(TRAINING_SOURCES),
    }:
        errors.append(f'line {line_no}: public training provenance is not exact')

    hands = provenance['hands']
    if not isinstance(hands, dict) or frozenset(hands) != frozenset({'commit', 'repo', 'sources'}):
        return errors + [f'line {line_no}: Hands provenance keys are incomplete or unknown']
    if hands.get('repo') != HANDS_REPO or hands.get('commit') != HANDS_COMMIT:
        errors.append(f'line {line_no}: Hands repository provenance is not exact')
    sources = hands.get('sources')
    if not isinstance(sources, list) or not sources:
        errors.append(f'line {line_no}: rule must cite at least one Hands source')
        return errors
    prior_path = ''
    for source in sources:
        if not isinstance(source, dict) or frozenset(source) != frozenset({'path', 'sha256', 'symbols'}):
            errors.append(f'line {line_no}: Hands source binding is invalid')
            continue
        path = source['path']
        if not isinstance(path, str) or path not in HANDS_SOURCE_SHA256:
            errors.append(f'line {line_no}: unrecognized Hands source {path!r}')
            continue
        if path <= prior_path:
            errors.append(f'line {line_no}: Hands sources must be unique and path-sorted')
        prior_path = path
        if source['sha256'] != HANDS_SOURCE_SHA256[path]:
            errors.append(f'line {line_no}: Hands source digest mismatch for {path}')
        supplied_symbols = source['symbols']
        if not isinstance(supplied_symbols, list) or not all(
            isinstance(symbol, str) for symbol in supplied_symbols
        ):
            errors.append(f'line {line_no}: source symbols for {path} must be strings')
            continue
        if supplied_symbols != sorted(set(supplied_symbols)):
            errors.append(f'line {line_no}: source symbols for {path} must be sorted and unique')
            continue
        if Path(path).suffix == '.py' and not supplied_symbols:
            errors.append(f'line {line_no}: Python source {path} must name an executable symbol')
        expected_symbols = source_symbols.get(path, frozenset())
        for symbol in supplied_symbols:
            if symbol not in expected_symbols:
                errors.append(f'line {line_no}: source symbol {path}:{symbol} does not exist')
    return errors


def _rows_from_candidate(
    raw_file: bytes,
    source_symbols: dict[str, frozenset[str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    if not raw_file.endswith(b'\n'):
        errors.append('candidate artifact must end with one newline')
    lines = raw_file.splitlines()
    if not lines:
        errors.append('candidate artifact must not be empty')
    for line_no, raw_line in enumerate(lines, 1):
        if not raw_line:
            errors.append(f'line {line_no}: blank lines are forbidden')
            continue
        try:
            row = _strict_object(raw_line, line_no)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))
            continue
        if _canonical_bytes(row) != raw_line:
            errors.append(f'line {line_no}: pair is not canonical JSON')
        errors.extend(validate_pair(row, line_no, source_symbols))
        rows.append(row)
    return rows, errors


def _rule_ids(rows: list[dict[str, Any]]) -> list[str]:
    rule_ids: list[str] = []
    for row in rows:
        meta = row.get('meta')
        if not isinstance(meta, dict):
            continue
        rule = meta.get('rule')
        if not isinstance(rule, dict):
            continue
        rule_id = rule.get('id')
        if isinstance(rule_id, str):
            rule_ids.append(rule_id)
    return rule_ids


def _referenced_paths(rows: list[dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for row in rows:
        meta = row.get('meta')
        if not isinstance(meta, dict):
            continue
        provenance = meta.get('provenance')
        if not isinstance(provenance, dict):
            continue
        hands = provenance.get('hands')
        if not isinstance(hands, dict):
            continue
        sources = hands.get('sources')
        if not isinstance(sources, list):
            continue
        for source in sources:
            if isinstance(source, dict) and isinstance(source.get('path'), str):
                paths.add(source['path'])
    return paths


def _candidate_receipt(raw_file: bytes, rows: list[dict[str, Any]], frozen_count: int) -> dict[str, Any]:
    return {
        'artifact': {
            'bytes': len(raw_file),
            'rows': len(rows),
            'sha256': hashlib.sha256(raw_file).hexdigest(),
        },
        'frozen_regression_rows': frozen_count,
        'hands': {'commit': HANDS_COMMIT, 'repo': HANDS_REPO},
        'public_training': {'commit': TRAINING_COMMIT, 'repo': TRAINING_REPO},
        'schema': RECEIPT_SCHEMA,
        'validator': {
            'path': VALIDATOR_PATH,
            'sha256': hashlib.sha256((REPO_ROOT / VALIDATOR_PATH).read_bytes()).hexdigest(),
        },
    }


def _write_receipt(receipt_path: Path, private_root: Path, receipt: dict[str, Any]) -> list[str]:
    if not receipt_path.is_absolute() or receipt_path.parent != private_root:
        return ['receipt must be an absolute direct child of the exclusive private root']
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(receipt_path, flags, 0o600)
    except OSError as exc:
        return [f'cannot create write-once receipt: {exc}']
    raw = _canonical_bytes(receipt) + b'\n'
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        return [f'cannot durably write receipt: {exc}']
    try:
        receipt_stat = receipt_path.lstat()
    except OSError as exc:
        return [f'cannot inspect written receipt: {exc}']
    if not stat.S_ISREG(receipt_stat.st_mode) or stat.S_IMODE(receipt_stat.st_mode) != 0o600:
        return ['written receipt is not a regular mode-0600 file']
    return []


def _print_errors(errors: list[str], label: str) -> int:
    for error in errors:
        print(f'FAIL: {error}')
    print(f'supervised UI design-rule {label} FAIL — {len(errors)} finding(s)')
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Validate a private supervised UI design-rule candidate without publishing it.'
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--self-check', action='store_true')
    mode.add_argument('--candidate', type=Path, metavar='ABSOLUTE_PATH')
    parser.add_argument('--private-root', type=Path, metavar='ABSOLUTE_PATH')
    parser.add_argument('--receipt', type=Path, metavar='ABSOLUTE_PATH')
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.self_check and (args.private_root is not None or args.receipt is not None):
        parser.error('--private-root and --receipt require --candidate')
    if args.candidate is not None and args.private_root is None:
        parser.error('--private-root is required with --candidate')

    errors, source_symbols = _validate_source_tree()
    errors.extend(_validate_live_policy())
    if args.self_check:
        if errors:
            return _print_errors(errors, 'public contract gate')
        print('supervised UI design-rule public contract gate CLEAN — no private candidate read')
        return 0

    raw_file, boundary_errors = _private_candidate_bytes(args.candidate, args.private_root)
    errors.extend(boundary_errors)
    if raw_file is None:
        return _print_errors(errors, 'candidate gate')
    rows, row_errors = _rows_from_candidate(raw_file, source_symbols)
    errors.extend(row_errors)
    rule_ids = _rule_ids(rows)
    if len(rule_ids) != len(rows):
        errors.append('every candidate row must expose one valid rule id')
    if len(rule_ids) != len(set(rule_ids)):
        errors.append('rule ids must be unique')
    if rule_ids != sorted(rule_ids):
        errors.append('pairs must be sorted by rule id')
    frozen_count = sum(
        isinstance(row.get('meta'), dict)
        and row['meta'].get('frozen_regression') is True
        for row in rows
    )
    if rows and frozen_count < math.ceil(len(rows) * 0.10):
        errors.append('at least ten percent of the rule lane must remain frozen regression rows')
    referenced_paths = _referenced_paths(rows)
    if referenced_paths != set(HANDS_SOURCE_SHA256):
        errors.append(
            f'Hands source coverage mismatch: missing='
            f'{sorted(set(HANDS_SOURCE_SHA256) - referenced_paths)}'
        )
    if errors:
        return _print_errors(errors, 'candidate gate')

    receipt = _candidate_receipt(raw_file, rows, frozen_count)
    if args.receipt is not None:
        receipt_errors = _write_receipt(args.receipt, args.private_root, receipt)
        if receipt_errors:
            return _print_errors(receipt_errors, 'receipt gate')
    print(_canonical_bytes(receipt).decode('utf-8'))
    print(
        f'supervised UI design-rule candidate gate CLEAN — {len(rows)} pair(s), '
        f'{frozen_count} frozen, exact public provenance verified'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
