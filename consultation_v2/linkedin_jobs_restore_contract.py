from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from consultation_v2.linkedin_jobs_contract import (
    LinkedInJobsContractError,
    canonical_json_bytes,
    read_owned_private_bytes,
    sha256_hex,
    validate_display,
    validate_path_beneath_private_root,
    validate_return_url,
    write_new_private_json,
)


PRIVATE_INPUT_SCHEMA = 'linkedin_jobs_restore_private_input_v1'
PUBLIC_PLATFORM = 'linkedin'
RECEIPT_SCHEMA = 'linkedin_jobs_restore_receipt_v1'
OPERATION = 'restore_linkedin_jobs_surface'

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
FAILURE_CODES = frozenset({
    'deadline_expired',
    'display_lock_unavailable',
    'lock_release_indeterminate',
    'private_input_invalid',
    'restore_indeterminate',
})


def _strict_object(raw_bytes: bytes, context: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LinkedInJobsContractError(
                    f'{context} contains duplicate key {key!r}'
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw_bytes.decode('utf-8'),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                LinkedInJobsContractError(
                    f'{context} contains non-JSON constant {token!r}'
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LinkedInJobsContractError(
            f'{context} must be strict UTF-8 JSON'
        ) from exc
    if not isinstance(value, dict):
        raise LinkedInJobsContractError(f'{context} must be an object')
    return value


def read_private_input(
    path_value: str | Path,
    private_root: Path,
) -> tuple[dict[str, str], str]:
    path = validate_path_beneath_private_root(
        path_value,
        private_root,
        'transaction file',
    )
    raw_bytes = read_owned_private_bytes(path, 'transaction file')
    transaction_sha256 = sha256_hex(raw_bytes)
    value = _strict_object(raw_bytes, 'transaction file')
    if canonical_json_bytes(value) != raw_bytes:
        raise LinkedInJobsContractError(
            'transaction file must use canonical JSON bytes'
        )
    if set(value) != {'schema', 'operation', 'return_url'}:
        raise LinkedInJobsContractError(
            'transaction fields are incomplete or unknown'
        )
    if value['schema'] != PRIVATE_INPUT_SCHEMA or value['operation'] != OPERATION:
        raise LinkedInJobsContractError(
            'transaction schema or operation is unsupported'
        )
    return_url = validate_return_url(value['return_url'])
    return {
        'schema': PRIVATE_INPUT_SCHEMA,
        'operation': OPERATION,
        'return_url': return_url,
    }, transaction_sha256


def validate_public_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    expected = {
        'ok',
        'platform',
        'display',
        'state',
        'failure_code',
        'target_url_sha256',
        'firefox_pid_sha256',
        'restore_proof_sha256',
        'stable_cycles_observed',
        'receipt_sha256',
        'turn_lineage_sha256',
    }
    if set(result) != expected:
        raise LinkedInJobsContractError(
            'public result fields are incomplete or unknown'
        )
    if not isinstance(result['ok'], bool) or result['platform'] != PUBLIC_PLATFORM:
        raise LinkedInJobsContractError('public result identity is invalid')
    validate_display(result['display'])
    state = result['state']
    if state not in {'restored', 'technical_failure'}:
        raise LinkedInJobsContractError('public result state is invalid')
    if result['ok'] is not (state == 'restored'):
        raise LinkedInJobsContractError('public result success identity is invalid')
    failure_code = result['failure_code']
    if state == 'restored':
        if failure_code is not None:
            raise LinkedInJobsContractError(
                'successful result cannot have a failure code'
            )
    elif failure_code not in FAILURE_CODES:
        raise LinkedInJobsContractError('technical failure code is invalid')
    for key in (
        'target_url_sha256',
        'firefox_pid_sha256',
        'restore_proof_sha256',
    ):
        digest = result[key]
        if digest is not None and (
            not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest)
        ):
            raise LinkedInJobsContractError(f'public result {key} is invalid')
    stable_cycles = result['stable_cycles_observed']
    if (
        isinstance(stable_cycles, bool)
        or not isinstance(stable_cycles, int)
        or not 0 <= stable_cycles <= 2
    ):
        raise LinkedInJobsContractError(
            'public result stable_cycles_observed is invalid'
        )
    if state == 'restored' and not (
        result['target_url_sha256'] is not None
        and result['firefox_pid_sha256'] is not None
        and result['restore_proof_sha256'] is not None
        and stable_cycles == 2
    ):
        raise LinkedInJobsContractError('restored result facts are invalid')
    for key in ('receipt_sha256', 'turn_lineage_sha256'):
        digest = result[key]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise LinkedInJobsContractError(f'public result {key} is invalid')
    return result


__all__ = [
    'FAILURE_CODES',
    'OPERATION',
    'PRIVATE_INPUT_SCHEMA',
    'PUBLIC_PLATFORM',
    'RECEIPT_SCHEMA',
    'canonical_json_bytes',
    'read_private_input',
    'sha256_hex',
    'validate_display',
    'validate_public_result',
    'write_new_private_json',
]
