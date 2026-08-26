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
COMMAND = REPO_ROOT / 'scripts/prepare_linkedin_job_search.py'
PRIVATE_MARKER = 'private-search-policy-sentinel'
SEAT = 'linkedin-search-prepare-validator'
CORRELATION = 'linkedin-search-prepare-001'
TERMINAL_MARKER_SCHEMA = 'linkedin_job_search_preparation_terminal_v1'


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


def fixture(
    case_root: Path,
    *,
    raw_override: bytes | None = None,
    sink_override: str | None = None,
    extra: dict[str, Any] | None = None,
    draft_mode: int = 0o400,
) -> tuple[Path, Path, dict[str, Any]]:
    private_root = case_root / 'private'
    private_root.mkdir(mode=0o700, parents=True)
    os.chmod(private_root, 0o700)
    sink = private_root / 'sinks' / SEAT / CORRELATION
    transaction = {
        'schema': 'linkedin_job_search_private_input_v1',
        'operation': 'capture_mounted_job_search',
        'search_ref': PRIVATE_MARKER,
        'sink_ref': sink_override if sink_override is not None else str(sink),
    }
    if extra:
        transaction.update(extra)
    draft = private_root / 'drafts' / 'mounted-search.json'
    write_private_file(
        draft,
        raw_override if raw_override is not None else canonical_bytes(transaction),
        draft_mode,
    )
    return private_root, draft, transaction


def invoke(
    command: str,
    private_root: Path,
    draft: Path,
    *,
    digest: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment['TAEY_LINKEDIN_JOB_SEARCH_PRIVATE_ROOT'] = str(private_root)
    environment['TAEY_LINKEDIN_JOB_SEARCH_DRAFT'] = str(draft)
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
    assert PRIVATE_MARKER not in arguments
    assert str(private_root) not in arguments
    assert str(draft) not in arguments
    result = subprocess.run(
        arguments,
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,  # lint-allow: adversarial validator asserts exact refusal status and receipt
    )
    for private_value in (PRIVATE_MARKER, str(private_root), str(draft)):
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
    marker_path: Path | None = None,
    command: str = 'prepare',
) -> None:
    assert result.returncode == 2, (code, result.returncode, result.stdout, result.stderr)
    assert result.stdout == '', (code, result.stdout)
    refusal = json.loads(result.stderr)
    expected = {
        'correlation_id': CORRELATION,
        'failure_code': code,
        'identity_spent': identity_spent,
        'schema': 'linkedin_job_search_preparation_result_v1',
        'seat_id': SEAT,
        'state': 'refused',
        'terminal_marker_sha256': refusal['terminal_marker_sha256'],
    }
    assert refusal == expected, refusal
    if marker_path is None:
        assert refusal['terminal_marker_sha256'] is None
    else:
        marker_bytes = marker_path.read_bytes()
        assert refusal['terminal_marker_sha256'] == hashlib.sha256(marker_bytes).hexdigest()
        assert stat.S_IMODE(marker_path.stat().st_mode) == 0o400
        assert marker_path.stat().st_uid == os.geteuid()
        assert json.loads(marker_bytes) == {
            'command': command,
            'correlation_id': CORRELATION,
            'failure_code': code,
            'schema': TERMINAL_MARKER_SCHEMA,
            'seat_id': SEAT,
            'state': 'spent',
        }
        assert marker_bytes == canonical_bytes(json.loads(marker_bytes))
    assert PRIVATE_MARKER not in result.stderr


def validate_happy_path(case_root: Path) -> None:
    private_root, draft, transaction = fixture(case_root)
    prepared = invoke('prepare', private_root, draft)
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
    assert result['state'] == 'prepared'
    assert result['seat_id'] == SEAT and result['correlation_id'] == CORRELATION
    assert PRIVATE_MARKER not in prepared.stdout and str(private_root) not in prepared.stdout
    transaction_path = private_root / 'transactions' / SEAT / f'{CORRELATION}.json'
    claim_path = private_root / 'claims' / SEAT / f'{CORRELATION}.json'
    receipt_path = private_root / 'receipts' / SEAT / f'{CORRELATION}.json'
    sink_path = Path(transaction['sink_ref'])
    assert transaction_path.read_bytes() == canonical_bytes(transaction)
    assert hashlib.sha256(transaction_path.read_bytes()).hexdigest() == result['transaction_sha256']
    assert stat.S_IMODE(transaction_path.stat().st_mode) == 0o400
    for path in (
        private_root / 'transactions',
        private_root / 'transactions' / SEAT,
        private_root / 'claims',
        private_root / 'claims' / SEAT,
        private_root / 'receipts',
        private_root / 'receipts' / SEAT,
        private_root / 'sinks',
        private_root / 'sinks' / SEAT,
        sink_path,
    ):
        assert path.is_dir() and stat.S_IMODE(path.stat().st_mode) == 0o700, path
        assert path.stat().st_uid == os.geteuid(), path
    assert not claim_path.exists() and not receipt_path.exists()
    assert not any(sink_path.iterdir())
    ready = invoke(
        'preflight',
        private_root,
        draft,
        digest=result['transaction_sha256'],
    )
    assert ready.returncode == 0, (ready.stdout, ready.stderr)
    ready_result = json.loads(ready.stdout)
    assert ready_result['state'] == 'ready'
    assert ready_result['transaction_sha256'] == result['transaction_sha256']
    assert ready_result['topology_sha256'] == result['topology_sha256']
    require_refusal(
        invoke('prepare', private_root, draft),
        'identity_spent',
        identity_spent=True,
        marker_path=claim_path,
    )
    require_refusal(
        invoke(
            'preflight',
            private_root,
            draft,
            digest=result['transaction_sha256'],
        ),
        'identity_spent',
        identity_spent=True,
        command='preflight',
    )


def validate_bad_drafts(base: Path) -> None:
    case = base / 'extra-field'
    root, draft, _ = fixture(case, extra={'unexpected': True})
    marker = claim_path(root)
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=marker,
    )
    corrected = root / 'drafts' / 'corrected-search.json'
    write_private_file(corrected, canonical_bytes({
        'operation': 'capture_mounted_job_search',
        'schema': 'linkedin_job_search_private_input_v1',
        'search_ref': PRIVATE_MARKER,
        'sink_ref': str(root / 'sinks' / SEAT / CORRELATION),
    }))
    require_refusal(
        invoke('prepare', root, corrected),
        'identity_spent',
        identity_spent=True,
    )
    assert marker.read_bytes() == canonical_bytes({
        'command': 'prepare',
        'correlation_id': CORRELATION,
        'failure_code': 'draft_invalid',
        'schema': TERMINAL_MARKER_SCHEMA,
        'seat_id': SEAT,
        'state': 'spent',
    })
    assert not (root / 'transactions' / SEAT / f'{CORRELATION}.json').exists()
    assert not (root / 'sinks' / SEAT / CORRELATION).exists()

    case = base / 'noncanonical'
    sink = case / 'private' / 'sinks' / SEAT / CORRELATION
    value = {
        'schema': 'linkedin_job_search_private_input_v1',
        'operation': 'capture_mounted_job_search',
        'search_ref': PRIVATE_MARKER,
        'sink_ref': str(sink),
    }
    root, draft, _ = fixture(case, raw_override=json.dumps(value, indent=2).encode('utf-8'))
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'duplicate-field'
    sink = case / 'private' / 'sinks' / SEAT / CORRELATION
    raw = (
        '{"operation":"capture_mounted_job_search",'
        '"schema":"linkedin_job_search_private_input_v1",'
        f'"search_ref":"{PRIVATE_MARKER}","search_ref":"duplicate",'
        f'"sink_ref":"{sink}"}}'
    ).encode('utf-8')
    root, draft, _ = fixture(case, raw_override=raw)
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'wrong-draft-mode'
    root, draft, _ = fixture(case, draft_mode=0o600)
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'wrong-draft-parent-mode'
    root, draft, _ = fixture(case)
    os.chmod(draft.parent, 0o755)
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'oversized-draft'
    sink = case / 'private' / 'sinks' / SEAT / CORRELATION
    value = {
        'schema': 'linkedin_job_search_private_input_v1',
        'operation': 'capture_mounted_job_search',
        'search_ref': PRIVATE_MARKER + ('x' * 17000),
        'sink_ref': str(sink),
    }
    root, draft, _ = fixture(case, raw_override=canonical_bytes(value))
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'out-of-root-sink'
    root, draft, _ = fixture(case, sink_override=str(case / 'outside' / 'sink'))
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'relative-sink'
    root, draft, _ = fixture(case, sink_override='sinks/not-absolute')
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'wrong-identity-sink'
    root, draft, _ = fixture(case, sink_override=str(case / 'private' / 'sinks' / 'other'))
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'nul-sink'
    root, draft, _ = fixture(case, sink_override='/private/unsafe\x00sink')
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )


def validate_unsafe_topology(base: Path) -> None:
    case = base / 'wrong-root-mode'
    root, draft, _ = fixture(case)
    os.chmod(root, 0o755)
    require_refusal(
        invoke('prepare', root, draft),
        'private_root_invalid',
        identity_spent=False,
    )

    case = base / 'symlink-root'
    root, draft, _ = fixture(case)
    linked_root = case / 'linked-private'
    linked_root.symlink_to(root, target_is_directory=True)
    require_refusal(
        invoke('prepare', linked_root, draft),
        'private_root_invalid',
        identity_spent=False,
    )

    case = base / 'wrong-base-mode'
    root, draft, _ = fixture(case)
    (root / 'claims').mkdir(mode=0o755)
    os.chmod(root / 'claims', 0o755)
    require_refusal(
        invoke('prepare', root, draft),
        'topology_invalid',
        identity_spent=False,
    )

    case = base / 'symlink-draft'
    root, draft, _ = fixture(case)
    target = draft.with_name('target.json')
    draft.rename(target)
    draft.symlink_to(target)
    require_refusal(
        invoke('prepare', root, draft),
        'draft_invalid',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'symlink-sink-component'
    root, draft, _ = fixture(case)
    outside = case / 'outside'
    outside.mkdir()
    (root / 'sinks').symlink_to(outside, target_is_directory=True)
    require_refusal(
        invoke('prepare', root, draft),
        'topology_invalid',
        identity_spent=False,
    )

    case = base / 'existing-claim'
    root, draft, _ = fixture(case)
    claim = root / 'claims' / SEAT / f'{CORRELATION}.json'
    write_private_file(claim, b'{}')
    os.chmod(root / 'claims', 0o700)
    require_refusal(
        invoke('prepare', root, draft),
        'identity_spent',
        identity_spent=True,
    )

    case = base / 'existing-receipt'
    root, draft, _ = fixture(case)
    receipt = root / 'receipts' / SEAT / f'{CORRELATION}.json'
    write_private_file(receipt, b'{}')
    require_refusal(
        invoke('prepare', root, draft),
        'identity_spent',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'existing-transaction'
    root, draft, _ = fixture(case)
    transaction = root / 'transactions' / SEAT / f'{CORRELATION}.json'
    write_private_file(transaction, b'{}')
    require_refusal(
        invoke('prepare', root, draft),
        'identity_spent',
        identity_spent=True,
        marker_path=claim_path(root),
    )

    case = base / 'existing-sink'
    root, draft, transaction = fixture(case)
    sink = Path(transaction['sink_ref'])
    sink.mkdir(mode=0o700, parents=True)
    os.chmod(sink, 0o700)
    require_refusal(
        invoke('prepare', root, draft),
        'identity_spent',
        identity_spent=True,
        marker_path=claim_path(root),
    )


def validate_digest_mismatch_spends_identity(case_root: Path) -> None:
    private_root, draft, _ = fixture(case_root)
    prepared = invoke('prepare', private_root, draft)
    assert prepared.returncode == 0, (prepared.stdout, prepared.stderr)
    transaction_sha256 = json.loads(prepared.stdout)['transaction_sha256']
    wrong_digest = '0' * 64
    if transaction_sha256 == wrong_digest:
        wrong_digest = '1' * 64
    marker = claim_path(private_root)
    require_refusal(
        invoke('preflight', private_root, draft, digest=wrong_digest),
        'digest_mismatch',
        identity_spent=True,
        marker_path=marker,
        command='preflight',
    )
    marker_bytes = marker.read_bytes()
    require_refusal(
        invoke('preflight', private_root, draft, digest=transaction_sha256),
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
    assert "os.O_EXCL" not in source or "write_new_private_json" in source
    assert "write_new_private_json(paths['claim'], marker)" in source
    assert 'os.O_CREAT | os.O_EXCL | os.O_WRONLY' in contract_source
    assert 'os.fchmod(descriptor, 0o400)' in contract_source
    assert contract_source.count('os.fsync(descriptor)') >= 2
    assert 'os.fsync(parent_descriptor)' in contract_source
    assert 'build_snapshot' not in source
    assert 'run_linkedin_job_search' not in source
    assert 'search_ref' not in source.split('def _result', 1)[1]


def main() -> int:
    validate_static_boundary()
    with tempfile.TemporaryDirectory(prefix='linkedin-search-prepare-validator-') as raw:
        base = Path(raw)
        validate_happy_path(base / 'happy')
        validate_bad_drafts(base / 'drafts')
        validate_unsafe_topology(base / 'topology')
        validate_digest_mismatch_spends_identity(base / 'digest-mismatch')
    print(json.dumps({
        'adversarial_cases': 23,
        'private_values_on_argv': False,
        'profile': 'linkedin-job-search',
        'status': 'PASS',
    }, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
