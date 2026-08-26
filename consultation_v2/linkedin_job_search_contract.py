from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from consultation_v2.linkedin_jobs_contract import (
    LinkedInJobsContractError,
    canonical_json_bytes,
    read_owned_private_bytes,
    sha256_hex,
    validate_display,
    validate_external_private_root,
    validate_path_beneath_private_root,
    write_new_private_json,
)


PRIVATE_INPUT_SCHEMA = 'linkedin_job_search_private_input_v1'
PUBLIC_PLATFORM = 'linkedin'
RECEIPT_SCHEMA = 'linkedin_job_search_receipt_v1'
RESULT_SCHEMA = 'linkedin_job_search_result_v1'
SEARCH_BATCH_SCHEMA = 'linkedin_mounted_job_search_v1'
OPERATION = 'capture_mounted_job_search'

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
FAILURE_CODES = frozenset({
    'deadline_expired',
    'display_lock_unavailable',
    'lock_release_indeterminate',
    'post_observation_indeterminate',
    'postcondition_failed',
    'pre_observation_failed',
    'private_input_invalid',
    'sink_write_indeterminate',
})


def _strict_object(raw_bytes: bytes, context: str) -> dict[str, Any]:
    import json

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LinkedInJobsContractError(f'{context} contains duplicate key {key!r}')
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
        raise LinkedInJobsContractError(f'{context} must be strict UTF-8 JSON') from exc
    if not isinstance(value, dict):
        raise LinkedInJobsContractError(f'{context} must be an object')
    return value


def read_private_input(
    path_value: str | Path,
    public_root: Path,
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
        raise LinkedInJobsContractError('transaction file must use canonical JSON bytes')
    expected = {'schema', 'operation', 'search_ref', 'sink_ref'}
    if set(value) != expected:
        raise LinkedInJobsContractError('transaction fields are incomplete or unknown')
    if value['schema'] != PRIVATE_INPUT_SCHEMA or value['operation'] != OPERATION:
        raise LinkedInJobsContractError('transaction schema or operation is unsupported')
    for key in ('search_ref', 'sink_ref'):
        item = value[key]
        if not isinstance(item, str) or not item or len(item) > 4096:
            raise LinkedInJobsContractError(f'transaction {key} is invalid')
    sink_root = validate_path_beneath_private_root(
        value['sink_ref'],
        private_root,
        'private sink',
    )
    validate_external_private_root(sink_root, public_root)
    return {key: str(item) for key, item in value.items()}, transaction_sha256


def validate_public_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    expected = {
        'ok',
        'platform',
        'display',
        'state',
        'failure_code',
        'batches_observed',
        'batches_written',
        'cards_observed',
        'content_digest',
        'receipt_sha256',
        'turn_lineage_sha256',
    }
    if set(result) != expected:
        raise LinkedInJobsContractError('public result fields are incomplete or unknown')
    if not isinstance(result['ok'], bool) or result['platform'] != PUBLIC_PLATFORM:
        raise LinkedInJobsContractError('public result identity is invalid')
    validate_display(result['display'])
    state = result['state']
    if state not in {
        'captured',
        'already_captured',
        'no_cards',
        'postcondition_failed',
        'technical_failure',
    }:
        raise LinkedInJobsContractError('public result state is invalid')
    success = state in {'captured', 'already_captured', 'no_cards'}
    if result['ok'] is not success:
        raise LinkedInJobsContractError('public result success identity is invalid')
    failure_code = result['failure_code']
    if success:
        if failure_code is not None:
            raise LinkedInJobsContractError('successful result cannot have a failure code')
    elif state == 'postcondition_failed':
        if failure_code != 'postcondition_failed':
            raise LinkedInJobsContractError('postcondition failure code is invalid')
    elif failure_code not in FAILURE_CODES:
        raise LinkedInJobsContractError('technical failure code is invalid')
    for key in ('batches_observed', 'cards_observed'):
        item = result[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise LinkedInJobsContractError(f'{key} is invalid')
    written = result['batches_written']
    if written is not None and (
        isinstance(written, bool) or not isinstance(written, int) or written not in {0, 1}
    ):
        raise LinkedInJobsContractError('batches_written is invalid')
    digest = result['content_digest']
    if digest is not None and (
        not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest)
    ):
        raise LinkedInJobsContractError('content_digest is invalid')
    if state == 'captured' and not (
        result['batches_observed'] == 1
        and written == 1
        and result['cards_observed'] > 0
        and digest is not None
    ):
        raise LinkedInJobsContractError('captured facts are invalid')
    if state == 'already_captured' and not (
        result['batches_observed'] == 1
        and written == 0
        and result['cards_observed'] > 0
        and digest is not None
    ):
        raise LinkedInJobsContractError('already-captured facts are invalid')
    if state == 'no_cards' and not (
        result['batches_observed'] == 1
        and written in {0, 1}
        and result['cards_observed'] == 0
        and digest is not None
    ):
        raise LinkedInJobsContractError('no-cards facts are invalid')
    if state in {'postcondition_failed', 'technical_failure'}:
        before_observation = (
            result['batches_observed'] == 0
            and written == 0
            and result['cards_observed'] == 0
            and digest is None
        )
        after_observation = (
            result['batches_observed'] == 1
            and written in {0, 1, None}
            and result['cards_observed'] >= 0
            and digest is not None
        )
        if not (before_observation or after_observation):
            raise LinkedInJobsContractError('failure phase facts are invalid')
    for key in ('receipt_sha256', 'turn_lineage_sha256'):
        item = result[key]
        if not isinstance(item, str) or not _SHA256_RE.fullmatch(item):
            raise LinkedInJobsContractError(f'{key} is invalid')
    return result


__all__ = [
    'FAILURE_CODES',
    'OPERATION',
    'PRIVATE_INPUT_SCHEMA',
    'PUBLIC_PLATFORM',
    'RECEIPT_SCHEMA',
    'RESULT_SCHEMA',
    'SEARCH_BATCH_SCHEMA',
    'canonical_json_bytes',
    'read_private_input',
    'sha256_hex',
    'validate_display',
    'validate_public_result',
    'write_new_private_json',
]
