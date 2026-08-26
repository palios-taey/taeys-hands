#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMAND = REPO_ROOT / 'scripts/prepare_linkedin_engagement.py'
SEAT = 'linkedin-engagement-prepare-validator'
CORRELATION = 'linkedin-engagement-prepare-001'
SOURCE_REF = 'private-engagement-source-sentinel'
RETURN_URL = 'https://www.linkedin.com/jobs/search-results/?keywords=private-return-sentinel'
RESULT_SCHEMA = 'linkedin_engagement_preparation_result_v1'
TERMINAL_MARKER_SCHEMA = 'linkedin_engagement_preparation_terminal_v1'


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')


def write_private_file(path: Path, raw_bytes: bytes, mode: int = 0o400) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        os.write(descriptor, raw_bytes)
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def transaction(private_root: Path, **changes: Any) -> dict[str, Any]:
    value = {
        'schema': 'linkedin_jobs_private_input_v1',
        'operation': 'capture_visible_new_engagement_signal',
        'source_ref': SOURCE_REF,
        'sink_ref': str(private_root / 'sinks' / SEAT / CORRELATION),
        'return_url': RETURN_URL,
    }
    value.update(changes)
    return value


def fixture(
    case_root: Path,
    *,
    value: dict[str, Any] | None = None,
    raw_bytes: bytes | None = None,
    draft_mode: int = 0o400,
) -> tuple[Path, Path, dict[str, Any]]:
    private_root = case_root / 'private'
    private_root.mkdir(mode=0o700, parents=True)
    os.chmod(private_root, 0o700)
    draft_value = value if value is not None else transaction(private_root)
    draft = private_root / 'drafts' / 'engagement.json'
    write_private_file(
        draft,
        canonical_bytes(draft_value) if raw_bytes is None else raw_bytes,
        draft_mode,
    )
    return private_root, draft, draft_value


def invoke(
    command: str,
    private_root: Path,
    draft: Path,
    digest: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment['TAEY_LINKEDIN_ENGAGEMENT_PRIVATE_ROOT'] = str(private_root)
    environment['TAEY_LINKEDIN_ENGAGEMENT_DRAFT'] = str(draft)
    arguments = [
        sys.executable,
        str(COMMAND),
        command,
        '--seat-id',
        SEAT,
        '--correlation-id',
        CORRELATION,
    ]
    if digest is not None:
        arguments.extend(['--expected-transaction-sha256', digest])
    assert str(private_root) not in arguments and str(draft) not in arguments
    result = subprocess.run(
        arguments,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,  # lint-allow: adversarial validator asserts exact refusal status and marker
    )
    for private_value in (
        SOURCE_REF,
        RETURN_URL,
        str(private_root),
        str(draft),
    ):
        assert private_value not in result.stdout
        assert private_value not in result.stderr
    return result


def claim_path(private_root: Path) -> Path:
    return private_root / 'claims' / SEAT / f'{CORRELATION}.json'


def require_refusal(
    result: subprocess.CompletedProcess[str],
    code: str,
    *,
    identity_spent: bool,
    marker: Path | None = None,
    command: str = 'prepare',
) -> None:
    assert result.returncode == 2, (code, result.returncode, result.stdout, result.stderr)
    assert result.stdout == ''
    refusal = json.loads(result.stderr)
    assert refusal == {
        'correlation_id': CORRELATION,
        'failure_code': code,
        'identity_spent': identity_spent,
        'schema': RESULT_SCHEMA,
        'seat_id': SEAT,
        'state': 'refused',
        'terminal_marker_sha256': refusal['terminal_marker_sha256'],
    }
    if marker is None:
        assert refusal['terminal_marker_sha256'] is None
        return
    marker_bytes = marker.read_bytes()
    assert refusal['terminal_marker_sha256'] == hashlib.sha256(marker_bytes).hexdigest()
    assert stat.S_IMODE(marker.stat().st_mode) == 0o400
    assert marker.stat().st_uid == os.geteuid()
    assert marker_bytes == canonical_bytes({
        'command': command,
        'correlation_id': CORRELATION,
        'failure_code': code,
        'schema': TERMINAL_MARKER_SCHEMA,
        'seat_id': SEAT,
        'state': 'spent',
    })


def validate_happy_path(case_root: Path) -> None:
    private_root = case_root / 'private'
    value = transaction(private_root)
    root, draft, _ = fixture(
        case_root,
        value=value,
        raw_bytes=(json.dumps(value, indent=2, sort_keys=False) + '\n').encode('utf-8'),
    )
    prepared = invoke('prepare', root, draft)
    assert prepared.returncode == 0, (prepared.stdout, prepared.stderr)
    result = json.loads(prepared.stdout)
    assert set(result) == {
        'correlation_id',
        'schema',
        'seat_id',
        'state',
        'topology_sha256',
        'transaction_sha256',
    }
    assert result['schema'] == RESULT_SCHEMA and result['state'] == 'prepared'
    assert result['seat_id'] == SEAT and result['correlation_id'] == CORRELATION
    transaction_path = root / 'transactions' / SEAT / f'{CORRELATION}.json'
    receipt_path = root / 'receipts' / SEAT / f'{CORRELATION}.json'
    sink = Path(value['sink_ref'])
    transaction_bytes = transaction_path.read_bytes()
    assert transaction_bytes == canonical_bytes(value)
    assert not transaction_bytes.endswith(b'\n')
    assert hashlib.sha256(transaction_bytes).hexdigest() == result['transaction_sha256']
    assert stat.S_IMODE(transaction_path.stat().st_mode) == 0o400
    assert result['topology_sha256'] == hashlib.sha256(canonical_bytes({
        'claim': 'absent',
        'correlation_id': CORRELATION,
        'directory_mode': '0700',
        'receipt': 'absent',
        'schema': 'linkedin_engagement_prepared_topology_v1',
        'seat_id': SEAT,
        'sink_entries': 0,
        'transaction_mode': '0400',
        'transaction_sha256': result['transaction_sha256'],
    })).hexdigest()
    for path in (
        root / 'transactions',
        root / 'transactions' / SEAT,
        root / 'claims',
        root / 'claims' / SEAT,
        root / 'receipts',
        root / 'receipts' / SEAT,
        root / 'sinks',
        root / 'sinks' / SEAT,
        sink,
    ):
        assert path.is_dir() and stat.S_IMODE(path.stat().st_mode) == 0o700
        assert path.stat().st_uid == os.geteuid()
    assert not claim_path(root).exists() and not receipt_path.exists() and not any(sink.iterdir())
    alternate_draft = root / 'drafts' / 'engagement-preflight.json'
    write_private_file(alternate_draft, canonical_bytes(value))
    ready = invoke('preflight', root, alternate_draft, result['transaction_sha256'])
    assert ready.returncode == 0, (ready.stdout, ready.stderr)
    ready_result = json.loads(ready.stdout)
    assert ready_result['state'] == 'ready'
    assert ready_result['transaction_sha256'] == result['transaction_sha256']
    assert ready_result['topology_sha256'] == result['topology_sha256']


def validate_draft_refusals(base: Path) -> int:
    cases: list[tuple[str, dict[str, Any] | None, bytes | None, int]] = []
    root_hint = base / 'root-hint' / 'private'
    valid = transaction(root_hint)
    cases.extend([
        ('extra-field', {**valid, 'unexpected': True}, None, 0o400),
        ('wrong-schema', {**valid, 'schema': 'wrong'}, None, 0o400),
        ('wrong-operation', {**valid, 'operation': 'capture_selected_job'}, None, 0o400),
        ('bad-return-url', {**valid, 'return_url': 'http://www.linkedin.com/jobs/search/'}, None, 0o400),
        ('relative-sink', {**valid, 'sink_ref': 'sinks/not-absolute'}, None, 0o400),
        ('wrong-mode', valid, None, 0o600),
        ('non-object', None, b'[]', 0o400),
    ])
    for field in tuple(valid):
        cases.append((f'missing-{field}', {k: v for k, v in valid.items() if k != field}, None, 0o400))
    duplicate_raw = canonical_bytes(valid).replace(
        b'"source_ref":"private-engagement-source-sentinel"',
        b'"source_ref":"private-engagement-source-sentinel","source_ref":"duplicate"',
    )
    cases.append(('duplicate-field', None, duplicate_raw, 0o400))
    nan_raw = canonical_bytes(valid).replace(
        b'"source_ref":"private-engagement-source-sentinel"',
        b'"source_ref":NaN',
    )
    cases.append(('nan', None, nan_raw, 0o400))
    for name, value, raw, mode in cases:
        case_root = base / name
        private_root = case_root / 'private'
        if value is not None:
            value = {
                key: (
                    str(private_root / 'sinks' / SEAT / CORRELATION)
                    if key == 'sink_ref' and item == valid['sink_ref']
                    else item
                )
                for key, item in value.items()
            }
        elif raw is not None:
            raw = raw.replace(str(root_hint).encode(), str(private_root).encode())
        root, draft, _ = fixture(case_root, value=value, raw_bytes=raw, draft_mode=mode)
        require_refusal(
            invoke('prepare', root, draft),
            'draft_invalid',
            identity_spent=True,
            marker=claim_path(root),
        )
    return len(cases)


def validate_topology_refusals(base: Path) -> int:
    root, draft, _ = fixture(base / 'wrong-root-mode')
    os.chmod(root, 0o755)
    require_refusal(invoke('prepare', root, draft), 'private_root_invalid', identity_spent=False)

    root, draft, _ = fixture(base / 'wrong-draft-parent-mode')
    os.chmod(draft.parent, 0o755)
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker=claim_path(root),
    )

    root, draft, _ = fixture(base / 'symlink-draft')
    target = draft.with_name('target.json')
    draft.rename(target)
    draft.symlink_to(target)
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker=claim_path(root),
    )

    existing_cases = {
        'claim': lambda root: write_private_file(claim_path(root), b'{}'),
        'receipt': lambda root: write_private_file(
            root / 'receipts' / SEAT / f'{CORRELATION}.json', b'{}'
        ),
        'transaction': lambda root: write_private_file(
            root / 'transactions' / SEAT / f'{CORRELATION}.json', b'{}'
        ),
        'sink': lambda root: (
            root / 'sinks' / SEAT / CORRELATION
        ).mkdir(mode=0o700, parents=True),
    }
    for name, create in existing_cases.items():
        root, draft, _ = fixture(base / f'existing-{name}')
        create(root)
        for parent in ('claims', 'receipts', 'transactions', 'sinks'):
            path = root / parent
            if path.exists():
                os.chmod(path, 0o700)
        marker = None if name == 'claim' else claim_path(root)
        require_refusal(
            invoke('prepare', root, draft),
            'identity_spent',
            identity_spent=True,
            marker=marker,
        )
    return 7


def validate_digest_mismatch(case_root: Path) -> None:
    root, draft, _ = fixture(case_root)
    prepared = invoke('prepare', root, draft)
    assert prepared.returncode == 0, (prepared.stdout, prepared.stderr)
    digest = json.loads(prepared.stdout)['transaction_sha256']
    wrong_digest = '0' * 64 if digest != '0' * 64 else '1' * 64
    marker = claim_path(root)
    require_refusal(
        invoke('preflight', root, draft, wrong_digest),
        'digest_mismatch',
        identity_spent=True,
        marker=marker,
        command='preflight',
    )
    marker_bytes = marker.read_bytes()
    require_refusal(
        invoke('preflight', root, draft, digest),
        'identity_spent',
        identity_spent=True,
        command='preflight',
    )
    assert marker.read_bytes() == marker_bytes


def validate_static_boundary() -> None:
    source = COMMAND.read_text(encoding='utf-8')
    contract_source = (
        REPO_ROOT / 'consultation_v2/linkedin_jobs_contract.py'
    ).read_text(encoding='utf-8')
    assert "metadata.st_uid != os.geteuid()" in source
    assert "write_new_private_json(paths['claim'], marker)" in source
    assert 'os.O_CREAT | os.O_EXCL | os.O_WRONLY' in contract_source
    assert 'os.fchmod(descriptor, 0o400)' in contract_source
    assert 'build_snapshot' not in source
    assert 'run_linkedin_jobs' not in source
    assert 'source_ref' not in source.split('def _result', 1)[1]


def main() -> int:
    validate_static_boundary()
    with tempfile.TemporaryDirectory(prefix='linkedin-engagement-prepare-validator-') as raw:
        base = Path(raw)
        validate_happy_path(base / 'happy')
        draft_cases = validate_draft_refusals(base / 'drafts')
        topology_cases = validate_topology_refusals(base / 'topology')
        validate_digest_mismatch(base / 'digest-mismatch')
    print(json.dumps({
        'adversarial_cases': draft_cases + topology_cases + 1,
        'private_values_on_argv': False,
        'profile': 'linkedin-engagement',
        'semantic_canonicalization': True,
        'status': 'PASS',
    }, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
