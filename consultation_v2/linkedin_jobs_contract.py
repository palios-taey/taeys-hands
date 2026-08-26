from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping
from urllib.parse import urlsplit


PRIVATE_INPUT_SCHEMA = 'linkedin_jobs_private_input_v1'
ENGAGEMENT_PRIVATE_INPUT_SCHEMA = 'linkedin_engagement_private_input_v2'
PUBLIC_OPERATIONS = frozenset({
    'capture_selected_job',
    'capture_visible_new_engagement_signal',
    'select_and_capture_job',
})
PUBLIC_PLATFORM = 'linkedin'
RECEIPT_SCHEMA = 'linkedin_jobs_receipt_v1'
ENGAGEMENT_RECEIPT_SCHEMA_V1 = 'linkedin_engagement_receipt_v1'
ENGAGEMENT_RECEIPT_SCHEMA = 'linkedin_engagement_receipt_v2'
SELECTED_JOB_SCHEMA = 'linkedin_selected_job_v1'
ENGAGEMENT_SIGNAL_SCHEMA = 'linkedin_engagement_signal_v1'

_DISPLAY_RE = re.compile(r'^:[0-9]{1,3}$')
_REQUESTER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
FAILURE_CODES = frozenset({
    'deadline_expired',
    'display_lock_unavailable',
    'lock_release_indeterminate',
    'post_observation_indeterminate',
    'postcondition_failed',
    'pre_observation_failed',
    'private_input_invalid',
    'selected_job_not_exact',
    'sink_write_indeterminate',
})
FAILURE_CODES_BY_STATE = {
    'no_selected_job': frozenset({'selected_job_not_exact'}),
    'postcondition_failed': frozenset({'postcondition_failed'}),
    'technical_failure': frozenset({
        'deadline_expired',
        'display_lock_unavailable',
        'lock_release_indeterminate',
        'post_observation_indeterminate',
        'pre_observation_failed',
        'private_input_invalid',
        'sink_write_indeterminate',
    }),
}

ENGAGEMENT_TECHNICAL_FAILURE_CODES = frozenset({
    'action_failed',
    'deadline_expired',
    'display_lock_unavailable',
    'lock_release_indeterminate',
    'navigation_not_exact',
    'post_observation_indeterminate',
    'pre_observation_failed',
    'private_input_invalid',
    'restore_indeterminate',
})


class LinkedInJobsContractError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')


def sha256_hex(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def validate_display(value: str) -> str:
    if not isinstance(value, str) or not _DISPLAY_RE.fullmatch(value):
        raise LinkedInJobsContractError('display must use the :N form')
    return value


def validate_requester(value: str) -> str:
    if not isinstance(value, str) or not _REQUESTER_RE.fullmatch(value):
        raise LinkedInJobsContractError('requester must be a public-safe identifier')
    return value


def validate_return_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise LinkedInJobsContractError('return_url is invalid')
    parsed = urlsplit(value)
    normalized_path = parsed.path.rstrip('/') or '/'
    if (
        parsed.scheme != 'https'
        or parsed.hostname != 'www.linkedin.com'
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or normalized_path != '/jobs/search-results'
        or parsed.fragment
    ):
        raise LinkedInJobsContractError(
            'return_url must be an exact HTTPS LinkedIn Jobs search-results URL'
        )
    return value


def _strict_object(raw_bytes: bytes, context: str) -> dict[str, Any]:
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
                LinkedInJobsContractError(f'{context} contains non-JSON constant {token!r}')
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LinkedInJobsContractError(f'{context} must be strict UTF-8 JSON') from exc
    if not isinstance(value, dict):
        raise LinkedInJobsContractError(f'{context} must be an object')
    return value


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise LinkedInJobsContractError(f'path component is a symlink: {current}')


def _owned_regular_file(path: Path, mode: int, context: str) -> None:
    if not path.is_absolute():
        raise LinkedInJobsContractError(f'{context} must be absolute')
    _assert_no_symlink_components(path)
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode):
        raise LinkedInJobsContractError(f'{context} must be a regular file')
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise LinkedInJobsContractError(f'{context} mode must be exactly {mode:04o}')
    if metadata.st_uid != os.geteuid():
        raise LinkedInJobsContractError(f'{context} must be owned by the worker user')


def read_owned_private_bytes(path: Path, context: str) -> bytes:
    _owned_regular_file(path, 0o400, context)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        remaining = metadata.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise LinkedInJobsContractError(f'{context} ended before its declared size')
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise LinkedInJobsContractError(f'{context} changed while it was read')
        return b''.join(chunks)
    finally:
        os.close(descriptor)


def validate_external_private_root(value: str | os.PathLike[str], public_root: Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise LinkedInJobsContractError('private root must be absolute')
    _assert_no_symlink_components(root)
    metadata = os.lstat(root)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise LinkedInJobsContractError('private root must be a directory with exact mode 0700')
    if metadata.st_uid != os.geteuid():
        raise LinkedInJobsContractError('private root must be owned by the worker user')
    resolved = root.resolve(strict=True)
    resolved_public = public_root.resolve(strict=True)
    if (
        resolved == resolved_public
        or resolved_public in resolved.parents
        or resolved in resolved_public.parents
    ):
        raise LinkedInJobsContractError('private root must not overlap the public repository')
    return resolved


def validate_path_beneath_private_root(
    path_value: str | os.PathLike[str],
    private_root: Path,
    context: str,
) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise LinkedInJobsContractError(f'{context} must be absolute')
    _assert_no_symlink_components(path)
    resolved = path.resolve(strict=False)
    if resolved == private_root or private_root not in resolved.parents:
        raise LinkedInJobsContractError(f'{context} must resolve beneath the private root')
    return resolved


def read_private_input(
    path_value: str | os.PathLike[str],
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
    operation = value.get('operation')
    if operation == 'capture_selected_job':
        expected = frozenset({'schema', 'operation', 'search_ref', 'sink_ref'})
    elif operation == 'select_and_capture_job':
        expected = frozenset({
            'schema',
            'operation',
            'search_ref',
            'sink_ref',
            'target_card_name',
            'detail_title_name',
            'detail_company_name',
        })
    elif operation == 'capture_visible_new_engagement_signal':
        if value.get('schema') == PRIVATE_INPUT_SCHEMA:
            expected = frozenset({
                'schema',
                'operation',
                'source_ref',
                'sink_ref',
                'notifications_name',
                'return_url',
            })
        else:
            expected = frozenset({
                'schema',
                'operation',
                'source_ref',
                'sink_ref',
                'return_url',
            })
    else:
        raise LinkedInJobsContractError('transaction operation is unsupported')
    if frozenset(value) != expected:
        raise LinkedInJobsContractError('transaction fields are incomplete or unknown')
    supported_schema = (
        value['schema'] in {PRIVATE_INPUT_SCHEMA, ENGAGEMENT_PRIVATE_INPUT_SCHEMA}
        if operation == 'capture_visible_new_engagement_signal'
        else value['schema'] == PRIVATE_INPUT_SCHEMA
    )
    if not supported_schema or value['operation'] not in PUBLIC_OPERATIONS:
        raise LinkedInJobsContractError('transaction schema or operation is unsupported')
    string_fields = {'sink_ref'}
    if operation in {'capture_selected_job', 'select_and_capture_job'}:
        string_fields.add('search_ref')
    if operation == 'select_and_capture_job':
        string_fields.update({
            'target_card_name',
            'detail_title_name',
            'detail_company_name',
        })
    elif operation == 'capture_visible_new_engagement_signal':
        string_fields.add('source_ref')
        if value['schema'] == PRIVATE_INPUT_SCHEMA:
            string_fields.add('notifications_name')
    for key in string_fields:
        item = value[key]
        if not isinstance(item, str) or not item or len(item) > 4096:
            raise LinkedInJobsContractError(f'transaction {key} is invalid')
    if operation == 'capture_visible_new_engagement_signal':
        validate_return_url(value['return_url'])
    sink_root = validate_path_beneath_private_root(
        value['sink_ref'],
        private_root,
        'private sink',
    )
    metadata = os.lstat(sink_root)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise LinkedInJobsContractError('private sink must be a directory with exact mode 0700')
    if metadata.st_uid != os.geteuid():
        raise LinkedInJobsContractError('private sink must be owned by the worker user')
    validate_external_private_root(sink_root, public_root)
    return {key: str(item) for key, item in value.items()}, transaction_sha256


def _validate_engagement_public_result(result: dict[str, Any]) -> dict[str, Any]:
    expected = frozenset({
        'ok',
        'platform',
        'display',
        'state',
        'failure_code',
        'records_observed',
        'records_written',
        'content_digest',
        'receipt_sha256',
        'turn_lineage_sha256',
        'restore_verified',
    })
    if frozenset(result) != expected:
        raise LinkedInJobsContractError(
            'engagement public result fields are incomplete or unknown'
        )
    if not isinstance(result['ok'], bool) or result['platform'] != PUBLIC_PLATFORM:
        raise LinkedInJobsContractError('engagement public result identity is invalid')
    validate_display(result['display'])
    state = result['state']
    failure_code = result['failure_code']
    exact_failure = {
        'already_known': None,
        'ambiguous_signal': 'ambiguous_signal',
        'captured': None,
        'no_new_signal': None,
        'postcondition_failed': 'postcondition_failed',
        'sink_write_indeterminate': 'sink_write_indeterminate',
    }
    if state == 'technical_failure':
        if failure_code not in ENGAGEMENT_TECHNICAL_FAILURE_CODES:
            raise LinkedInJobsContractError('engagement technical failure code is invalid')
    elif state not in exact_failure or failure_code != exact_failure[state]:
        raise LinkedInJobsContractError('engagement public result failure code is invalid')
    success = state in {'already_known', 'captured', 'no_new_signal'}
    if result['ok'] is not success:
        raise LinkedInJobsContractError('engagement public result success is invalid')
    if not isinstance(result['restore_verified'], bool):
        raise LinkedInJobsContractError('engagement restore verdict is invalid')
    if success and result['restore_verified'] is not True:
        raise LinkedInJobsContractError('engagement success requires verified restoration')
    observed = result['records_observed']
    written = result['records_written']
    digest = result['content_digest']
    if isinstance(observed, bool) or observed not in {0, 1}:
        raise LinkedInJobsContractError('engagement records_observed is invalid')
    if isinstance(written, bool) or written not in {0, 1, None}:
        raise LinkedInJobsContractError('engagement records_written is invalid')
    if digest is not None and (
        not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest)
    ):
        raise LinkedInJobsContractError('engagement content_digest is invalid')
    exact_facts = {
        'already_known': (1, 0, True),
        'ambiguous_signal': (0, 0, False),
        'captured': (1, 1, True),
        'no_new_signal': (0, 0, False),
        'sink_write_indeterminate': (1, None, True),
    }
    if state in exact_facts:
        if (observed, written, digest is not None) != exact_facts[state]:
            raise LinkedInJobsContractError('engagement public state facts are invalid')
    elif state == 'postcondition_failed':
        if not (
            (observed, written, digest) == (0, 0, None)
            or (observed == 1 and written in {0, 1} and digest is not None)
        ):
            raise LinkedInJobsContractError('engagement postcondition facts are invalid')
    else:
        before_signal = (observed, written, digest) == (0, 0, None)
        after_signal = (
            observed == 1 and written in {0, 1} and digest is not None
        )
        if not (before_signal or after_signal):
            raise LinkedInJobsContractError('engagement technical facts are invalid')
    for key in ('receipt_sha256', 'turn_lineage_sha256'):
        item = result[key]
        if not isinstance(item, str) or not _SHA256_RE.fullmatch(item):
            raise LinkedInJobsContractError(f'engagement {key} is invalid')
    return result


def validate_public_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    if 'restore_verified' in result:
        return _validate_engagement_public_result(result)
    expected = frozenset({
        'ok',
        'platform',
        'display',
        'state',
        'failure_code',
        'records_observed',
        'records_written',
        'content_digest',
        'receipt_sha256',
        'turn_lineage_sha256',
    })
    if frozenset(result) != expected:
        raise LinkedInJobsContractError('public result fields are incomplete or unknown')
    if not isinstance(result['ok'], bool) or result['platform'] != PUBLIC_PLATFORM:
        raise LinkedInJobsContractError('public result identity is invalid')
    validate_display(result['display'])
    if result['state'] not in {
        'captured',
        'already_captured',
        'no_selected_job',
        'postcondition_failed',
        'technical_failure',
    }:
        raise LinkedInJobsContractError('public result state is invalid')
    success_state = result['state'] in {'captured', 'already_captured'}
    failure_code = result['failure_code']
    if result['ok'] is not success_state:
        raise LinkedInJobsContractError('public result success identity is invalid')
    if success_state:
        if failure_code is not None:
            raise LinkedInJobsContractError('successful public result cannot have a failure code')
    elif (
        not isinstance(failure_code, str)
        or failure_code not in FAILURE_CODES_BY_STATE[result['state']]
    ):
        raise LinkedInJobsContractError('failed public result failure_code is invalid')
    if isinstance(result['records_observed'], bool) or result['records_observed'] not in {0, 1}:
        raise LinkedInJobsContractError('public result records_observed is invalid')
    if (
        isinstance(result['records_written'], bool)
        or result['records_written'] not in {0, 1, None}
    ):
        raise LinkedInJobsContractError('public result records_written is invalid')
    content_digest = result['content_digest']
    if content_digest is not None and (
        not isinstance(content_digest, str) or not _SHA256_RE.fullmatch(content_digest)
    ):
        raise LinkedInJobsContractError('public result content_digest is invalid')
    state_facts = {
        'captured': (1, frozenset({1}), True),
        'already_captured': (1, frozenset({0}), True),
        'no_selected_job': (0, frozenset({0}), False),
        'postcondition_failed': (1, frozenset({0, 1}), True),
    }
    if result['state'] in state_facts:
        expected_observed, expected_written, requires_digest = state_facts[result['state']]
        if (
            result['records_observed'] != expected_observed
            or result['records_written'] not in expected_written
            or (content_digest is not None) is not requires_digest
        ):
            raise LinkedInJobsContractError('public result state facts are invalid')
    elif result['state'] == 'technical_failure':
        sink_indeterminate = (
            failure_code == 'sink_write_indeterminate'
            and result['records_observed'] == 1
            and result['records_written'] is None
            and content_digest is not None
        )
        before_selection = (
            failure_code != 'sink_write_indeterminate'
            and result['records_observed'] == 0
            and result['records_written'] == 0
            and content_digest is None
        )
        after_selection = (
            failure_code != 'sink_write_indeterminate'
            and result['records_observed'] == 1
            and result['records_written'] in {0, 1}
            and content_digest is not None
        )
        if not (sink_indeterminate or before_selection or after_selection):
            raise LinkedInJobsContractError('public result technical phase facts are invalid')
    if (
        not isinstance(result['receipt_sha256'], str)
        or not _SHA256_RE.fullmatch(result['receipt_sha256'])
    ):
        raise LinkedInJobsContractError('public result receipt_sha256 is invalid')
    if (
        not isinstance(result['turn_lineage_sha256'], str)
        or not _SHA256_RE.fullmatch(result['turn_lineage_sha256'])
    ):
        raise LinkedInJobsContractError('public result turn_lineage_sha256 is invalid')
    return result


def validate_new_private_output_path(path: Path) -> Path:
    if not path.is_absolute():
        raise LinkedInJobsContractError('output path must be absolute')
    _assert_no_symlink_components(path.parent)
    parent_metadata = os.lstat(path.parent)
    if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_IMODE(parent_metadata.st_mode) != 0o700:
        raise LinkedInJobsContractError('output parent must be a directory with exact mode 0700')
    if parent_metadata.st_uid != os.geteuid():
        raise LinkedInJobsContractError('output parent must be owned by the worker user')
    if path.exists() or path.is_symlink():
        raise LinkedInJobsContractError('output path already exists')
    return path


def validate_new_private_output_beneath_root(path: Path, private_root: Path) -> Path:
    resolved = validate_path_beneath_private_root(path, private_root, 'output path')
    return validate_new_private_output_path(resolved)


def write_new_private_json(path: Path, value: Mapping[str, Any]) -> bytes:
    validate_new_private_output_path(path)
    raw_bytes = canonical_json_bytes(value)
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        pending = memoryview(raw_bytes)
        while pending:
            written = os.write(descriptor, pending)
            if written <= 0:
                raise LinkedInJobsContractError('immutable artifact write made no progress')
            pending = pending[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent_descriptor = os.open(
        path.parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    return raw_bytes
