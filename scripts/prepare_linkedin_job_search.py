#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PRIVATE_ROOT_ENV = 'TAEY_LINKEDIN_JOB_SEARCH_PRIVATE_ROOT'
DRAFT_ENV = 'TAEY_LINKEDIN_JOB_SEARCH_DRAFT'
RESULT_SCHEMA = 'linkedin_job_search_preparation_result_v1'
TERMINAL_MARKER_SCHEMA = 'linkedin_job_search_preparation_terminal_v1'
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_DRAFT_FIELDS = frozenset({'schema', 'operation', 'search_ref', 'sink_ref'})


class PreparationRefused(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _strict_object(raw_bytes: bytes) -> dict[str, Any]:
    from consultation_v2.linkedin_jobs_contract import LinkedInJobsContractError

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LinkedInJobsContractError('draft manifest contains duplicate fields')
            result[key] = value
        return result

    try:
        value = json.loads(
            raw_bytes.decode('utf-8'),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                LinkedInJobsContractError('draft manifest contains a non-JSON constant')
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LinkedInJobsContractError('draft manifest is not strict UTF-8 JSON') from exc
    if not isinstance(value, dict):
        raise LinkedInJobsContractError('draft manifest must be an object')
    return value


def _environment_path(name: str) -> Path:
    raw_value = os.environ.get(name, '')
    if not raw_value:
        raise PreparationRefused('environment_invalid')
    return Path(raw_value)


def _public_identity(value: str) -> str:
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        validate_requester,
    )

    try:
        return validate_requester(value)
    except LinkedInJobsContractError as exc:
        raise argparse.ArgumentTypeError('identity must be public-safe') from exc


def _sha256(value: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise argparse.ArgumentTypeError('digest must be lowercase SHA-256')
    return value


def _private_root() -> Path:
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        validate_external_private_root,
    )

    try:
        return validate_external_private_root(_environment_path(PRIVATE_ROOT_ENV), REPO_ROOT)
    except (LinkedInJobsContractError, OSError, ValueError):
        raise PreparationRefused('private_root_invalid') from None


def _derived_paths(private_root: Path, seat_id: str, correlation_id: str) -> dict[str, Path]:
    paths = {
        'transaction_parent': private_root / 'transactions' / seat_id,
        'transaction': private_root / 'transactions' / seat_id / f'{correlation_id}.json',
        'claim_parent': private_root / 'claims' / seat_id,
        'claim': private_root / 'claims' / seat_id / f'{correlation_id}.json',
        'receipt_parent': private_root / 'receipts' / seat_id,
        'receipt': private_root / 'receipts' / seat_id / f'{correlation_id}.json',
        'sink_parent': private_root / 'sinks' / seat_id,
        'sink': private_root / 'sinks' / seat_id / correlation_id,
    }
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        validate_path_beneath_private_root,
    )

    try:
        for name, path in paths.items():
            validate_path_beneath_private_root(path, private_root, name)
    except (LinkedInJobsContractError, OSError, ValueError):
        raise PreparationRefused('topology_invalid') from None
    return paths


def _read_draft(
    private_root: Path,
    expected_sink: Path,
) -> tuple[dict[str, str], bytes]:
    from consultation_v2.linkedin_job_search_contract import (
        OPERATION,
        PRIVATE_INPUT_SCHEMA,
    )
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        canonical_json_bytes,
        read_owned_private_bytes,
        validate_path_beneath_private_root,
    )

    try:
        draft_path = validate_path_beneath_private_root(
            _environment_path(DRAFT_ENV),
            private_root,
            'draft manifest',
        )
        current_parent = draft_path.parent
        private_ancestors: list[Path] = []
        while current_parent != private_root:
            private_ancestors.append(current_parent)
            current_parent = current_parent.parent
        for parent in reversed(private_ancestors):
            _validate_private_directory(parent)
        raw_bytes = read_owned_private_bytes(draft_path, 'draft manifest')
        if len(raw_bytes) > 16384:
            raise LinkedInJobsContractError('draft manifest is too large')
        value = _strict_object(raw_bytes)
        if canonical_json_bytes(value) != raw_bytes:
            raise LinkedInJobsContractError('draft manifest is not canonical')
        if frozenset(value) != _DRAFT_FIELDS:
            raise LinkedInJobsContractError('draft manifest fields are not exact')
        if value['schema'] != PRIVATE_INPUT_SCHEMA or value['operation'] != OPERATION:
            raise LinkedInJobsContractError('draft manifest contract is unsupported')
        for field in ('search_ref', 'sink_ref'):
            item = value[field]
            if not isinstance(item, str) or not item or len(item) > 4096:
                raise LinkedInJobsContractError('draft manifest field is invalid')
        sink_path = validate_path_beneath_private_root(
            value['sink_ref'],
            private_root,
            'private sink',
        )
        if sink_path != expected_sink:
            raise LinkedInJobsContractError('private sink is not the derived identity sink')
    except (LinkedInJobsContractError, OSError, PreparationRefused, ValueError):
        raise PreparationRefused('draft_invalid') from None
    return {key: str(value[key]) for key in value}, raw_bytes


def _path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _validate_private_directory(path: Path) -> None:
    try:
        metadata = os.lstat(path)
    except OSError:
        raise PreparationRefused('topology_invalid') from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.geteuid()
    ):
        raise PreparationRefused('topology_invalid')


def _sync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_or_validate_directory(path: Path) -> None:
    if _path_exists(path):
        _validate_private_directory(path)
        return
    try:
        os.mkdir(path, 0o700)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _sync_directory(path.parent)
        _validate_private_directory(path)
    except (FileExistsError, OSError):
        raise PreparationRefused('topology_invalid') from None


def _create_new_private_directory(path: Path) -> None:
    if _path_exists(path):
        raise PreparationRefused('identity_spent')
    try:
        os.mkdir(path, 0o700)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _sync_directory(path.parent)
        _validate_private_directory(path)
    except (FileExistsError, OSError):
        raise PreparationRefused('identity_spent') from None


def _refuse_spent_identity(paths: dict[str, Path]) -> None:
    if any(_path_exists(paths[name]) for name in ('transaction', 'claim', 'receipt', 'sink')):
        raise PreparationRefused('identity_spent')


def _establish_claim_boundary(private_root: Path, paths: dict[str, Path]) -> None:
    _create_or_validate_directory(private_root / 'claims')
    _create_or_validate_directory(paths['claim_parent'])


def _spend_identity(
    paths: dict[str, Path],
    command: str,
    seat_id: str,
    correlation_id: str,
    failure_code: str,
) -> tuple[bool, str | None]:
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        sha256_hex,
        write_new_private_json,
    )

    if _path_exists(paths['claim']):
        return True, None
    marker = {
        'command': command,
        'correlation_id': correlation_id,
        'failure_code': failure_code,
        'schema': TERMINAL_MARKER_SCHEMA,
        'seat_id': seat_id,
        'state': 'spent',
    }
    try:
        marker_bytes = write_new_private_json(paths['claim'], marker)
    except (FileExistsError, LinkedInJobsContractError, OSError):
        if _path_exists(paths['claim']):
            return True, None
        return False, None
    return True, sha256_hex(marker_bytes)


def _topology_sha256(
    seat_id: str,
    correlation_id: str,
    transaction_sha256: str,
) -> str:
    from consultation_v2.linkedin_jobs_contract import canonical_json_bytes, sha256_hex

    return sha256_hex(canonical_json_bytes({
        'claim': 'absent',
        'correlation_id': correlation_id,
        'directory_mode': '0700',
        'receipt': 'absent',
        'schema': 'linkedin_job_search_prepared_topology_v1',
        'seat_id': seat_id,
        'sink_entries': 0,
        'transaction_mode': '0400',
        'transaction_sha256': transaction_sha256,
    }))


def _validate_prepared(
    private_root: Path,
    paths: dict[str, Path],
    draft: dict[str, str],
    draft_bytes: bytes,
    expected_transaction_sha256: str,
) -> str:
    from consultation_v2.linkedin_job_search_contract import read_private_input
    from consultation_v2.linkedin_jobs_contract import LinkedInJobsContractError, sha256_hex

    try:
        for relative in ('transactions', 'claims', 'receipts', 'sinks'):
            _validate_private_directory(private_root / relative)
        for name in ('transaction_parent', 'claim_parent', 'receipt_parent', 'sink_parent', 'sink'):
            _validate_private_directory(paths[name])
        if _path_exists(paths['claim']) or _path_exists(paths['receipt']):
            raise PreparationRefused('identity_spent')
        with os.scandir(paths['sink']) as entries:
            if any(entries):
                raise PreparationRefused('identity_spent')
        transaction, transaction_sha256 = read_private_input(
            paths['transaction'],
            REPO_ROOT,
            private_root,
        )
        if transaction != draft or sha256_hex(draft_bytes) != transaction_sha256:
            raise PreparationRefused('transaction_invalid')
        if transaction_sha256 != expected_transaction_sha256:
            raise PreparationRefused('digest_mismatch')
    except PreparationRefused:
        raise
    except (LinkedInJobsContractError, OSError):
        raise PreparationRefused('topology_invalid') from None
    return transaction_sha256


def _prepare(
    private_root: Path,
    paths: dict[str, Path],
    seat_id: str,
    correlation_id: str,
) -> dict[str, str]:
    from consultation_v2.linkedin_jobs_contract import (
        LinkedInJobsContractError,
        sha256_hex,
        write_new_private_json,
    )

    draft, draft_bytes = _read_draft(private_root, paths['sink'])
    _refuse_spent_identity(paths)
    for relative in ('transactions', 'receipts', 'sinks'):
        _create_or_validate_directory(private_root / relative)
    for name in ('transaction_parent', 'receipt_parent', 'sink_parent'):
        _create_or_validate_directory(paths[name])
    _create_new_private_directory(paths['sink'])
    try:
        transaction_bytes = write_new_private_json(paths['transaction'], draft)
    except (LinkedInJobsContractError, OSError):
        raise PreparationRefused('transaction_write_refused') from None
    transaction_sha256 = sha256_hex(transaction_bytes)
    if transaction_bytes != draft_bytes:
        raise PreparationRefused('transaction_invalid')
    _validate_prepared(
        private_root,
        paths,
        draft,
        draft_bytes,
        transaction_sha256,
    )
    return _result('prepared', seat_id, correlation_id, transaction_sha256)


def _preflight(
    private_root: Path,
    paths: dict[str, Path],
    seat_id: str,
    correlation_id: str,
    expected_transaction_sha256: str,
) -> dict[str, str]:
    draft, draft_bytes = _read_draft(private_root, paths['sink'])
    transaction_sha256 = _validate_prepared(
        private_root,
        paths,
        draft,
        draft_bytes,
        expected_transaction_sha256,
    )
    return _result('ready', seat_id, correlation_id, transaction_sha256)


def _result(
    state: str,
    seat_id: str,
    correlation_id: str,
    transaction_sha256: str,
) -> dict[str, str]:
    return {
        'correlation_id': correlation_id,
        'schema': RESULT_SCHEMA,
        'seat_id': seat_id,
        'state': state,
        'topology_sha256': _topology_sha256(
            seat_id,
            correlation_id,
            transaction_sha256,
        ),
        'transaction_sha256': transaction_sha256,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Prepare one immutable LinkedIn mounted-search transaction topology.',
    )
    subparsers = parser.add_subparsers(dest='command', required=True)
    for command in ('prepare', 'preflight'):
        subparser = subparsers.add_parser(command)
        subparser.add_argument('--seat-id', required=True, type=_public_identity)
        subparser.add_argument('--correlation-id', required=True, type=_public_identity)
        if command == 'preflight':
            subparser.add_argument(
                '--expected-transaction-sha256',
                required=True,
                type=_sha256,
            )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    accepted_paths: dict[str, Path] | None = None
    identity_spent = False
    terminal_marker_sha256: str | None = None
    try:
        private_root = _private_root()
        paths = _derived_paths(private_root, args.seat_id, args.correlation_id)
        _establish_claim_boundary(private_root, paths)
        accepted_paths = paths
        if args.command == 'prepare':
            result = _prepare(
                private_root,
                paths,
                args.seat_id,
                args.correlation_id,
            )
        else:
            result = _preflight(
                private_root,
                paths,
                args.seat_id,
                args.correlation_id,
                args.expected_transaction_sha256,
            )
    except PreparationRefused as exc:
        failure_code = exc.code
    except Exception:
        failure_code = 'internal_refused'
    else:
        sys.stdout.buffer.write(
            json.dumps(result, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n'
        )
        return 0
    if accepted_paths is not None:
        identity_spent, terminal_marker_sha256 = _spend_identity(
            accepted_paths,
            args.command,
            args.seat_id,
            args.correlation_id,
            failure_code,
        )
        if not identity_spent:
            failure_code = 'terminalization_indeterminate'
    refusal = {
        'correlation_id': args.correlation_id,
        'failure_code': failure_code,
        'identity_spent': identity_spent,
        'schema': RESULT_SCHEMA,
        'seat_id': args.seat_id,
        'state': 'refused',
        'terminal_marker_sha256': terminal_marker_sha256,
    }
    sys.stderr.buffer.write(
        json.dumps(refusal, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n'
    )
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
