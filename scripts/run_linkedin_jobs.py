#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Iterator, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_GIT_COMMIT_RE = re.compile(r'^[0-9a-f]{40}$')
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_TRACE_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$')
_PROCESS_GENERATION_RE = re.compile(r'^[0-9a-f]{32}$')
_MINIMUM_DEADLINE_SECONDS = 30
_MAXIMUM_DEADLINE_SECONDS = 1700
_EMPTY_MATCH_COUNTS = {
    'about_job_heading': 0,
    'selected_job_description_path': 0,
}


def _selection_receipt(
    *,
    verdict: str,
    target_card_name: str | None,
    detail_title_name: str | None,
    detail_company_name: str | None,
    target_match_count: int,
    detail_title_match_count: int | None,
    detail_company_match_count: int | None,
    stable_cycles_observed: int,
    action_name: str | None = None,
    action_index: int | None = None,
    action_match_count: int = 0,
) -> dict[str, Any]:
    return {
        'kind': 'private_exact_job_card_atspi_activate',
        'verdict': verdict,
        'target_card_name_sha256': _digest_text(target_card_name),
        'detail_title_name_sha256': _digest_text(detail_title_name),
        'detail_company_name_sha256': _digest_text(detail_company_name),
        'target_match_count': target_match_count,
        'detail_title_match_count': detail_title_match_count,
        'detail_company_match_count': detail_company_match_count,
        'stable_cycles_observed': stable_cycles_observed,
        'action_name': action_name,
        'action_index': action_index,
        'action_match_count': action_match_count,
    }


def _display_argument(value: str) -> str:
    from consultation_v2.linkedin_jobs_contract import validate_display

    return validate_display(value)


def _trace_id_argument(value: str) -> str:
    if not isinstance(value, str) or not _TRACE_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError('turn ID is invalid')
    return value


def _process_generation_argument(value: str) -> str:
    if not isinstance(value, str) or not _PROCESS_GENERATION_RE.fullmatch(value):
        raise argparse.ArgumentTypeError('process generation is invalid')
    return value


def _sha256_argument(value: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise argparse.ArgumentTypeError('expected transaction digest is invalid')
    return value


def _deadline_argument(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('deadline must be an integer') from exc
    if not _MINIMUM_DEADLINE_SECONDS <= parsed <= _MAXIMUM_DEADLINE_SECONDS:
        raise argparse.ArgumentTypeError(
            f'deadline must be {_MINIMUM_DEADLINE_SECONDS}-{_MAXIMUM_DEADLINE_SECONDS} seconds'
        )
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Select or capture one frozen LinkedIn job into a private sink.',
    )
    parser.add_argument('--display', required=True, type=_display_argument)
    parser.add_argument('--transaction-file', required=True)
    parser.add_argument(
        '--expected-transaction-sha256',
        required=True,
        type=_sha256_argument,
    )
    parser.add_argument('--receipt-file', required=True)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--requester', required=True)
    parser.add_argument('--turn-id', required=True, type=_trace_id_argument)
    parser.add_argument('--correlation-id', required=True, type=_trace_id_argument)
    parser.add_argument(
        '--process-generation',
        required=True,
        type=_process_generation_argument,
    )
    parser.add_argument('--deadline-seconds', required=True, type=_deadline_argument)
    return parser


class LinkedInJobsDeadlineExpired(TimeoutError):
    pass


@contextmanager
def _internal_deadline(deadline_at: float) -> Iterator[None]:
    remaining = deadline_at - time.monotonic()
    if remaining <= 0:
        raise LinkedInJobsDeadlineExpired('LinkedIn Jobs internal deadline expired')
    prior_delay, prior_interval = signal.getitimer(signal.ITIMER_REAL)
    if prior_delay or prior_interval:
        raise RuntimeError('runner refuses to replace an existing process alarm')
    prior_handler = signal.getsignal(signal.SIGALRM)

    def expire(_signum: int, _frame: Any) -> None:
        raise LinkedInJobsDeadlineExpired('LinkedIn Jobs internal deadline expired')

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, prior_handler)


def _bind_display(display: str) -> None:
    bus_path = Path('/tmp') / f'a11y_bus_{display}'
    descriptor = os.open(bus_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError('AT-SPI bus binding must be a regular nonsymlink file')
        bus = os.read(descriptor, 4096).decode('utf-8').strip()
        if os.read(descriptor, 1):
            raise RuntimeError('AT-SPI bus binding is unexpectedly large')
    finally:
        os.close(descriptor)
    if not bus:
        raise RuntimeError('AT-SPI bus binding is empty')
    os.environ['DISPLAY'] = display
    os.environ['AT_SPI_BUS_ADDRESS'] = bus


def _current_commit() -> str:
    status = subprocess.run(
        [
            'git',
            '-C',
            str(REPO_ROOT),
            'status',
            '--porcelain=v1',
            '--untracked-files=all',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout:
        raise RuntimeError('Hands checkout must be clean before a revenue transaction')
    completed = subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'rev-parse', 'HEAD'],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = completed.stdout.strip()
    if not _GIT_COMMIT_RE.fullmatch(commit):
        raise RuntimeError('unable to establish exact Hands commit')
    return commit


def _digest_text(value: str | None) -> str | None:
    from consultation_v2.linkedin_jobs_contract import sha256_hex

    return sha256_hex(value.encode('utf-8')) if value is not None else None


def _turn_lineage_sha256(
    requester: str,
    turn_id: str,
    correlation_id: str,
    process_generation: str,
) -> str:
    from consultation_v2.linkedin_jobs_contract import canonical_json_bytes, sha256_hex

    return sha256_hex(canonical_json_bytes({
        'correlation_id': correlation_id,
        'process_generation': process_generation,
        'requester': requester,
        'turn_id': turn_id,
    }))


def _lock_request_id(transaction_sha256: str, turn_lineage_sha256: str) -> str:
    from consultation_v2.linkedin_jobs_contract import canonical_json_bytes, sha256_hex

    return sha256_hex(canonical_json_bytes({
        'transaction_sha256': transaction_sha256,
        'turn_lineage_sha256': turn_lineage_sha256,
    }))


def _lock_lineage(
    lock: Mapping[str, Any],
    request_id: str,
    turn_lineage_sha256: str,
    correlation_id_sha256: str,
    deadline_seconds: int,
) -> dict[str, Any]:
    owner_token = lock.get('owner_token')
    return {
        'policy': 'careers',
        'request_id': request_id,
        'acquired': lock.get('acquired') is True,
        'released': lock.get('released') is True,
        'owner_token_sha256': _digest_text(owner_token if isinstance(owner_token, str) else None),
        'wait_ms': int(lock.get('wait_ms') or 0),
        'turn_lineage_sha256': turn_lineage_sha256,
        'correlation_id_sha256': correlation_id_sha256,
        'deadline_seconds': deadline_seconds,
    }


def _receipt_payload(
    *,
    display: str,
    requester: str,
    hands_commit: str,
    operation: str,
    terminal_state: str,
    ok: bool,
    failure_code: str | None,
    transaction_sha256: str | None,
    expected_transaction_sha256: str,
    search_ref: str | None,
    sink_ref: str | None,
    pre_observation_sha256: str | None,
    pre_match_counts: Mapping[str, int],
    selection: Mapping[str, Any],
    lock_lineage: Mapping[str, Any],
    action_verdict: str,
    records_observed: int,
    records_written: int | None,
    postcondition_verdict: str,
    post_observation_sha256: str | None,
    post_match_counts: Mapping[str, int] | None,
) -> dict[str, Any]:
    from consultation_v2.linkedin_jobs_contract import RECEIPT_SCHEMA

    return {
        'schema': RECEIPT_SCHEMA,
        'platform': 'linkedin',
        'operation': operation,
        'display': display,
        'requester': requester,
        'turn_lineage_sha256': lock_lineage['turn_lineage_sha256'],
        'correlation_id_sha256': lock_lineage['correlation_id_sha256'],
        'deadline_seconds': lock_lineage['deadline_seconds'],
        'hands_commit': hands_commit,
        'terminal_state': terminal_state,
        'ok': ok,
        'failure_code': failure_code,
        'transaction_sha256': transaction_sha256,
        'expected_transaction_sha256': expected_transaction_sha256,
        'search_ref_sha256': _digest_text(search_ref),
        'sink_ref_sha256': _digest_text(sink_ref),
        'pre_observation_sha256': pre_observation_sha256,
        'pre_match_counts': dict(pre_match_counts),
        'selection': dict(selection),
        'lock': dict(lock_lineage),
        'action': {
            'kind': 'private_sink_write_once',
            'verdict': action_verdict,
            'records_observed': records_observed,
            'records_written': records_written,
            'content_digest': pre_observation_sha256,
        },
        'postcondition': {
            'kind': 'selected_job_content_digest_unchanged',
            'verdict': postcondition_verdict,
            'post_observation_sha256': post_observation_sha256,
            'post_match_counts': (
                dict(post_match_counts)
                if post_match_counts is not None
                else None
            ),
        },
    }


def _public_result(
    *,
    ok: bool,
    display: str,
    state: str,
    failure_code: str | None,
    records_observed: int,
    records_written: int | None,
    content_digest: str | None,
    receipt_sha256: str,
    turn_lineage_sha256: str,
) -> dict[str, Any]:
    from consultation_v2.linkedin_jobs_contract import validate_public_result

    return validate_public_result({
        'ok': ok,
        'platform': 'linkedin',
        'display': display,
        'state': state,
        'failure_code': failure_code,
        'records_observed': records_observed,
        'records_written': records_written,
        'content_digest': content_digest,
        'receipt_sha256': receipt_sha256,
        'turn_lineage_sha256': turn_lineage_sha256,
    })


def _finalize(
    *,
    receipt_path: Path,
    display: str,
    requester: str,
    hands_commit: str,
    operation: str,
    terminal_state: str,
    ok: bool,
    failure_code: str | None,
    transaction_sha256: str | None,
    expected_transaction_sha256: str,
    search_ref: str | None,
    sink_ref: str | None,
    pre_observation_sha256: str | None,
    pre_match_counts: Mapping[str, int],
    selection: Mapping[str, Any],
    lock_lineage: Mapping[str, Any],
    action_verdict: str,
    records_observed: int,
    records_written: int | None,
    postcondition_verdict: str,
    post_observation_sha256: str | None,
    post_match_counts: Mapping[str, int] | None,
) -> dict[str, Any]:
    from consultation_v2.linkedin_jobs_contract import sha256_hex, write_new_private_json

    receipt = _receipt_payload(
        display=display,
        requester=requester,
        hands_commit=hands_commit,
        operation=operation,
        terminal_state=terminal_state,
        ok=ok,
        failure_code=failure_code,
        transaction_sha256=transaction_sha256,
        expected_transaction_sha256=expected_transaction_sha256,
        search_ref=search_ref,
        sink_ref=sink_ref,
        pre_observation_sha256=pre_observation_sha256,
        pre_match_counts=pre_match_counts,
        selection=selection,
        lock_lineage=lock_lineage,
        action_verdict=action_verdict,
        records_observed=records_observed,
        records_written=records_written,
        postcondition_verdict=postcondition_verdict,
        post_observation_sha256=post_observation_sha256,
        post_match_counts=post_match_counts,
    )
    receipt_sha256 = sha256_hex(write_new_private_json(receipt_path, receipt))
    return _public_result(
        ok=ok,
        display=display,
        state=terminal_state,
        failure_code=failure_code,
        records_observed=records_observed,
        records_written=records_written,
        content_digest=pre_observation_sha256,
        receipt_sha256=receipt_sha256,
        turn_lineage_sha256=str(lock_lineage['turn_lineage_sha256']),
    )


def _terminal_facts(
    *,
    terminal_state: str,
    ok: bool,
    failure_code: str | None,
    pre_observation_sha256: str | None,
    pre_match_counts: Mapping[str, int],
    action_verdict: str,
    records_observed: int,
    records_written: int | None,
    postcondition_verdict: str,
    post_observation_sha256: str | None,
    post_match_counts: Mapping[str, int] | None,
    selection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        'terminal_state': terminal_state,
        'ok': ok,
        'failure_code': failure_code,
        'pre_observation_sha256': pre_observation_sha256,
        'pre_match_counts': pre_match_counts,
        'action_verdict': action_verdict,
        'records_observed': records_observed,
        'records_written': records_written,
        'postcondition_verdict': postcondition_verdict,
        'post_observation_sha256': post_observation_sha256,
        'post_match_counts': post_match_counts,
        'selection': dict(selection or _selection_receipt(
            verdict='not_required',
            target_card_name=None,
            detail_title_name=None,
            detail_company_name=None,
            target_match_count=0,
            detail_title_match_count=None,
            detail_company_match_count=None,
            stable_cycles_observed=0,
        )),
    }


def _execute_locked_transaction(
    *,
    lock: Mapping[str, Any],
    display: str,
    deadline_at: float,
    operation: str,
    search_ref: str,
    sink_root: Path,
    target_card_name: str | None,
    detail_title_name: str | None,
    detail_company_name: str | None,
) -> dict[str, Any]:
    from consultation_v2.platforms.linkedin.driver import (
        LinkedInJobCardActionFailed,
        LinkedInJobCardUnavailable,
        LinkedInSelectedJobUnavailable,
        activate_private_job_card,
        job_selection_barrier_policy,
        observe_private_selected_job,
        observe_selected_job,
        selected_job_postcondition,
        write_selected_job_once,
    )
    from consultation_v2.snapshot import build_snapshot

    selection = _selection_receipt(
        verdict=('not_required' if operation == 'capture_selected_job' else 'not_executed'),
        target_card_name=target_card_name,
        detail_title_name=detail_title_name,
        detail_company_name=detail_company_name,
        target_match_count=0,
        detail_title_match_count=None,
        detail_company_match_count=None,
        stable_cycles_observed=0,
    )
    if lock.get('acquired') is not True:
        sys.stderr.write('RuntimeError: CAREERS display lock was not acquired\n')
        return _terminal_facts(
            terminal_state='technical_failure',
            ok=False,
            failure_code='display_lock_unavailable',
            pre_observation_sha256=None,
            pre_match_counts=_EMPTY_MATCH_COUNTS,
            action_verdict='not_executed',
            records_observed=0,
            records_written=0,
            postcondition_verdict='not_evaluated',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )
    try:
        with _internal_deadline(deadline_at):
            _bind_display(display)
            _firefox, _document, before_snapshot = build_snapshot('linkedin')
            if operation == 'select_and_capture_job':
                if not all((target_card_name, detail_title_name, detail_company_name)):
                    raise RuntimeError('private exact job-selection identity is incomplete')
                activated = activate_private_job_card(before_snapshot, target_card_name)
                selection = _selection_receipt(
                    verdict='action_executed',
                    target_card_name=target_card_name,
                    detail_title_name=detail_title_name,
                    detail_company_name=detail_company_name,
                    target_match_count=activated.target_match_count,
                    detail_title_match_count=None,
                    detail_company_match_count=None,
                    stable_cycles_observed=0,
                    action_name=activated.action_name,
                    action_index=activated.action_index,
                    action_match_count=activated.action_match_count,
                )
                required_cycles, interval, barrier_timeout = job_selection_barrier_policy()
                barrier_deadline = min(deadline_at, time.monotonic() + barrier_timeout)
                stable_cycles = 0
                prior_digest: str | None = None
                before = None
                detail_counts = None
                while time.monotonic() < barrier_deadline:
                    _firefox, _document, selected_snapshot = build_snapshot('linkedin')
                    try:
                        detail_counts = observe_private_selected_job(
                            selected_snapshot,
                            detail_title_name,
                            detail_company_name,
                        )
                        candidate = observe_selected_job(selected_snapshot, search_ref)
                    except (LinkedInJobCardUnavailable, LinkedInSelectedJobUnavailable):
                        stable_cycles = 0
                        prior_digest = None
                    else:
                        if candidate.content_digest == prior_digest:
                            stable_cycles += 1
                        else:
                            stable_cycles = 1
                            prior_digest = candidate.content_digest
                        before = candidate
                        if stable_cycles >= required_cycles:
                            break
                    time.sleep(interval)
                if (
                    before is None
                    or detail_counts is None
                    or stable_cycles < required_cycles
                ):
                    raise LinkedInJobCardUnavailable(
                        'selected-job exact postcondition did not stabilize',
                        0,
                    )
                selection = _selection_receipt(
                    verdict='satisfied',
                    target_card_name=target_card_name,
                    detail_title_name=detail_title_name,
                    detail_company_name=detail_company_name,
                    target_match_count=activated.target_match_count,
                    detail_title_match_count=detail_counts.detail_title_match_count,
                    detail_company_match_count=detail_counts.detail_company_match_count,
                    stable_cycles_observed=stable_cycles,
                    action_name=activated.action_name,
                    action_index=activated.action_index,
                    action_match_count=activated.action_match_count,
                )
            else:
                before = observe_selected_job(before_snapshot, search_ref)
    except LinkedInJobsDeadlineExpired as exc:
        sys.stderr.write(f'{type(exc).__name__}: internal deadline expired\n')
        return _terminal_facts(
            terminal_state='technical_failure',
            ok=False,
            failure_code='deadline_expired',
            pre_observation_sha256=None,
            pre_match_counts=_EMPTY_MATCH_COUNTS,
            action_verdict='not_executed',
            records_observed=0,
            records_written=0,
            postcondition_verdict='not_evaluated',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )
    except LinkedInJobCardUnavailable as exc:
        sys.stderr.write(f'{type(exc).__name__}: exact job selection failed\n')
        if selection['verdict'] == 'not_executed':
            selection = _selection_receipt(
                verdict='target_not_exact',
                target_card_name=target_card_name,
                detail_title_name=detail_title_name,
                detail_company_name=detail_company_name,
                target_match_count=exc.match_count,
                detail_title_match_count=None,
                detail_company_match_count=None,
                stable_cycles_observed=0,
            )
            failure_code = 'pre_observation_failed'
        else:
            selection['verdict'] = 'postcondition_failed'
            failure_code = 'pre_observation_failed'
        return _terminal_facts(
            terminal_state='technical_failure',
            ok=False,
            failure_code=failure_code,
            pre_observation_sha256=None,
            pre_match_counts=_EMPTY_MATCH_COUNTS,
            action_verdict='not_executed',
            records_observed=0,
            records_written=0,
            postcondition_verdict='not_evaluated',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )
    except LinkedInJobCardActionFailed as exc:
        sys.stderr.write(f'{type(exc).__name__}: exact job-card action failed\n')
        selection = _selection_receipt(
            verdict=exc.verdict,
            target_card_name=target_card_name,
            detail_title_name=detail_title_name,
            detail_company_name=detail_company_name,
            target_match_count=1,
            detail_title_match_count=None,
            detail_company_match_count=None,
            stable_cycles_observed=0,
            action_name=exc.action_name,
            action_index=exc.action_index,
            action_match_count=exc.action_match_count,
        )
        return _terminal_facts(
            terminal_state='technical_failure',
            ok=False,
            failure_code='pre_observation_failed',
            pre_observation_sha256=None,
            pre_match_counts=_EMPTY_MATCH_COUNTS,
            action_verdict='not_executed',
            records_observed=0,
            records_written=0,
            postcondition_verdict='not_evaluated',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )
    except LinkedInSelectedJobUnavailable as exc:
        sys.stderr.write(f'{type(exc).__name__}: no exact selected job\n')
        return _terminal_facts(
            terminal_state='no_selected_job',
            ok=False,
            failure_code='selected_job_not_exact',
            pre_observation_sha256=None,
            pre_match_counts=exc.match_counts,
            action_verdict='not_executed',
            records_observed=0,
            records_written=0,
            postcondition_verdict='not_evaluated',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )
    except Exception as exc:
        sys.stderr.write(f'{type(exc).__name__}: pre-observation failed\n')
        return _terminal_facts(
            terminal_state='technical_failure',
            ok=False,
            failure_code='pre_observation_failed',
            pre_observation_sha256=None,
            pre_match_counts=_EMPTY_MATCH_COUNTS,
            action_verdict='not_executed',
            records_observed=0,
            records_written=0,
            postcondition_verdict='not_evaluated',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )

    try:
        with _internal_deadline(deadline_at):
            sink_result = write_selected_job_once(before, sink_root)
    except LinkedInJobsDeadlineExpired as exc:
        sys.stderr.write(f'{type(exc).__name__}: internal deadline expired\n')
        return _terminal_facts(
            terminal_state='technical_failure',
            ok=False,
            failure_code='sink_write_indeterminate',
            pre_observation_sha256=before.content_digest,
            pre_match_counts=before.match_counts,
            action_verdict='indeterminate',
            records_observed=1,
            records_written=None,
            postcondition_verdict='not_evaluated',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )
    except Exception as exc:
        sys.stderr.write(f'{type(exc).__name__}: private sink action indeterminate\n')
        return _terminal_facts(
            terminal_state='technical_failure',
            ok=False,
            failure_code='sink_write_indeterminate',
            pre_observation_sha256=before.content_digest,
            pre_match_counts=before.match_counts,
            action_verdict='indeterminate',
            records_observed=1,
            records_written=None,
            postcondition_verdict='not_evaluated',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )

    action_verdict = (
        'written'
        if sink_result.records_written == 1
        else 'already_present'
    )
    try:
        with _internal_deadline(deadline_at):
            _firefox, _document, after_snapshot = build_snapshot('linkedin')
            after = observe_selected_job(after_snapshot, search_ref)
    except LinkedInJobsDeadlineExpired as exc:
        sys.stderr.write(f'{type(exc).__name__}: internal deadline expired\n')
        return _terminal_facts(
            terminal_state='technical_failure',
            ok=False,
            failure_code='deadline_expired',
            pre_observation_sha256=before.content_digest,
            pre_match_counts=before.match_counts,
            action_verdict=action_verdict,
            records_observed=1,
            records_written=sink_result.records_written,
            postcondition_verdict='indeterminate',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )
    except LinkedInSelectedJobUnavailable as exc:
        sys.stderr.write(f'{type(exc).__name__}: fresh exact mapping failed\n')
        return _terminal_facts(
            terminal_state='postcondition_failed',
            ok=False,
            failure_code='postcondition_failed',
            pre_observation_sha256=before.content_digest,
            pre_match_counts=before.match_counts,
            action_verdict=action_verdict,
            records_observed=1,
            records_written=sink_result.records_written,
            postcondition_verdict='failed',
            post_observation_sha256=None,
            post_match_counts=exc.match_counts,
            selection=selection,
        )
    except Exception as exc:
        sys.stderr.write(f'{type(exc).__name__}: fresh postcondition indeterminate\n')
        return _terminal_facts(
            terminal_state='technical_failure',
            ok=False,
            failure_code='post_observation_indeterminate',
            pre_observation_sha256=before.content_digest,
            pre_match_counts=before.match_counts,
            action_verdict=action_verdict,
            records_observed=1,
            records_written=sink_result.records_written,
            postcondition_verdict='indeterminate',
            post_observation_sha256=None,
            post_match_counts=None,
            selection=selection,
        )

    if not selected_job_postcondition(before, after):
        return _terminal_facts(
            terminal_state='postcondition_failed',
            ok=False,
            failure_code='postcondition_failed',
            pre_observation_sha256=before.content_digest,
            pre_match_counts=before.match_counts,
            action_verdict=action_verdict,
            records_observed=1,
            records_written=sink_result.records_written,
            postcondition_verdict='failed',
            post_observation_sha256=after.content_digest,
            post_match_counts=after.match_counts,
            selection=selection,
        )

    terminal_state = (
        'captured'
        if sink_result.records_written == 1
        else 'already_captured'
    )
    return _terminal_facts(
        terminal_state=terminal_state,
        ok=True,
        failure_code=None,
        pre_observation_sha256=before.content_digest,
        pre_match_counts=before.match_counts,
        action_verdict=action_verdict,
        records_observed=1,
        records_written=sink_result.records_written,
        postcondition_verdict='satisfied',
        post_observation_sha256=after.content_digest,
        post_match_counts=after.match_counts,
        selection=selection,
    )


def _empty_engagement_action(stage: str) -> dict[str, Any]:
    return {
        'stage': stage,
        'target_match_count': 0,
        'action_name': None,
        'action_index': None,
        'action_match_count': 0,
        'verdict': 'not_executed',
    }


def _empty_engagement_restore() -> dict[str, Any]:
    return {
        'verdict': 'not_executed',
        'failed_substep': None,
        'firefox_pid_sha256': None,
        'stable_cycles_required': 0,
        'stable_cycles_observed': 0,
        'return_url_sha256': None,
    }


def _engagement_terminal(
    *,
    state: str,
    failure_code: str | None,
    records_observed: int = 0,
    records_written: int | None = 0,
    content_digest: str | None = None,
    restore_verified: bool = False,
    start: Mapping[str, Any] | None = None,
    notifications_action: Mapping[str, Any] | None = None,
    notifications_postcondition: Mapping[str, Any] | None = None,
    my_posts_action: Mapping[str, Any] | None = None,
    my_posts_postcondition: Mapping[str, Any] | None = None,
    candidate_count: int = 0,
    sink_verdict: str = 'not_executed',
    signal_postcondition: str = 'not_evaluated',
    restore: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        'terminal_state': state,
        'ok': state in {'already_known', 'captured', 'no_new_signal'},
        'failure_code': failure_code,
        'records_observed': records_observed,
        'records_written': records_written,
        'content_digest': content_digest,
        'restore_verified': restore_verified,
        'start': dict(start or {}),
        'notifications_action': dict(
            notifications_action or _empty_engagement_action('notifications_navigation')
        ),
        'notifications_postcondition': dict(notifications_postcondition or {}),
        'my_posts_action': dict(
            my_posts_action or _empty_engagement_action('my_posts_filter')
        ),
        'my_posts_postcondition': dict(my_posts_postcondition or {}),
        'candidate_count': candidate_count,
        'sink_verdict': sink_verdict,
        'signal_postcondition': signal_postcondition,
        'restore': dict(restore or _empty_engagement_restore()),
    }


def _execute_engagement_transaction(
    *,
    lock: Mapping[str, Any],
    display: str,
    deadline_at: float,
    sink_root: Path,
    notifications_name: str,
    return_url: str,
) -> dict[str, Any]:
    from consultation_v2.platforms.linkedin.driver import (
        LinkedInEngagementActionFailed,
        LinkedInEngagementRestoreFailed,
        activate_my_posts,
        activate_notifications,
        engagement_signal_postcondition,
        exact_engagement_return,
        observe_engagement_signal,
        observe_engagement_start,
        stable_my_posts_observation,
        stable_notifications_observation,
        write_engagement_signal_once,
    )
    from consultation_v2.snapshot import build_snapshot

    if lock.get('acquired') is not True:
        return _engagement_terminal(
            state='technical_failure',
            failure_code='display_lock_unavailable',
        )
    start: dict[str, Any] = {}
    notifications_action = _empty_engagement_action('notifications_navigation')
    notifications_postcondition: dict[str, Any] = {}
    my_posts_action = _empty_engagement_action('my_posts_filter')
    my_posts_postcondition: dict[str, Any] = {}
    candidate_count = 0
    records_observed = 0
    records_written: int | None = 0
    content_digest: str | None = None
    sink_verdict = 'not_executed'
    signal_verdict = 'not_evaluated'
    phase = 'pre_observation'
    try:
        with _internal_deadline(deadline_at):
            _bind_display(display)
            _firefox, _document, snapshot = build_snapshot('linkedin')
            start = observe_engagement_start(snapshot, notifications_name, return_url)
            if not (
                start.get('route_exact') is True
                and start.get('route_kind_exact') is True
                and start.get('notifications_target_match_count') == 1
                and isinstance(start.get('notifications_target_state_digest'), str)
            ):
                return _engagement_terminal(
                    state='postcondition_failed',
                    failure_code='postcondition_failed',
                    start=start,
                )
            phase = 'notifications_action'
            notifications_action = activate_notifications(snapshot, notifications_name)
            phase = 'notifications_postcondition'
            notifications = stable_notifications_observation(deadline_at)
            notifications_postcondition = dict(notifications.receipt)
            if not (
                notifications.snapshot is not None
                and notifications_postcondition.get('route_exact') is True
                and notifications_postcondition.get('my_posts_match_count') == 1
                and notifications_postcondition.get('stable_cycles_observed') == 2
            ):
                return _engagement_terminal(
                    state='postcondition_failed',
                    failure_code='postcondition_failed',
                    start=start,
                    notifications_action=notifications_action,
                    notifications_postcondition=notifications_postcondition,
                )
            phase = 'my_posts_action'
            my_posts_action = activate_my_posts(notifications.snapshot)
            phase = 'my_posts_postcondition'
            filtered = stable_my_posts_observation(deadline_at)
            my_posts_postcondition = dict(filtered.receipt)
            if not (
                filtered.snapshot is not None
                and filtered.signal is not None
                and my_posts_postcondition.get('route_exact') is True
                and my_posts_postcondition.get('selected_filter_marker_match_count') == 1
                and my_posts_postcondition.get('stable_cycles_observed') == 2
            ):
                return _engagement_terminal(
                    state='technical_failure',
                    failure_code='navigation_not_exact',
                    start=start,
                    notifications_action=notifications_action,
                    notifications_postcondition=notifications_postcondition,
                    my_posts_action=my_posts_action,
                    my_posts_postcondition=my_posts_postcondition,
                )
            signal_before = filtered.signal
            candidate_count = signal_before.candidate_count
            if candidate_count > 1:
                return _engagement_terminal(
                    state='ambiguous_signal',
                    failure_code='ambiguous_signal',
                    start=start,
                    notifications_action=notifications_action,
                    notifications_postcondition=notifications_postcondition,
                    my_posts_action=my_posts_action,
                    my_posts_postcondition=my_posts_postcondition,
                    candidate_count=candidate_count,
                )
            if candidate_count == 1:
                records_observed = 1
                content_digest = signal_before.content_digest
                phase = 'sink_write'
                try:
                    result = write_engagement_signal_once(signal_before, sink_root)
                except Exception:
                    return _engagement_terminal(
                        state='sink_write_indeterminate',
                        failure_code='sink_write_indeterminate',
                        records_observed=1,
                        records_written=None,
                        content_digest=content_digest,
                        start=start,
                        notifications_action=notifications_action,
                        notifications_postcondition=notifications_postcondition,
                        my_posts_action=my_posts_action,
                        my_posts_postcondition=my_posts_postcondition,
                        candidate_count=1,
                        sink_verdict='indeterminate',
                    )
                records_written = result.records_written
                sink_verdict = 'written' if records_written == 1 else 'already_present'
                phase = 'signal_postcondition'
                _firefox, _document, post_snapshot = build_snapshot('linkedin')
                signal_after = observe_engagement_signal(post_snapshot)
                if not engagement_signal_postcondition(signal_before, signal_after):
                    return _engagement_terminal(
                        state='postcondition_failed',
                        failure_code='postcondition_failed',
                        records_observed=1,
                        records_written=records_written,
                        content_digest=content_digest,
                        start=start,
                        notifications_action=notifications_action,
                        notifications_postcondition=notifications_postcondition,
                        my_posts_action=my_posts_action,
                        my_posts_postcondition=my_posts_postcondition,
                        candidate_count=signal_after.candidate_count,
                        sink_verdict=sink_verdict,
                        signal_postcondition='failed',
                    )
                signal_verdict = 'satisfied'
            phase = 'restore'
            restore = exact_engagement_return(
                display,
                return_url,
                deadline_at,
            )
            return _engagement_terminal(
                state=(
                    'captured'
                    if records_written == 1
                    else ('already_known' if candidate_count == 1 else 'no_new_signal')
                ),
                failure_code=None,
                records_observed=records_observed,
                records_written=records_written,
                content_digest=content_digest,
                restore_verified=True,
                start=start,
                notifications_action=notifications_action,
                notifications_postcondition=notifications_postcondition,
                my_posts_action=my_posts_action,
                my_posts_postcondition=my_posts_postcondition,
                candidate_count=candidate_count,
                sink_verdict=sink_verdict,
                signal_postcondition=signal_verdict,
                restore=restore,
            )
    except LinkedInEngagementActionFailed as exc:
        if exc.stage == 'notifications_navigation':
            notifications_action = exc.receipt
        else:
            my_posts_action = exc.receipt
        return _engagement_terminal(
            state='technical_failure',
            failure_code='action_failed',
            start=start,
            notifications_action=notifications_action,
            notifications_postcondition=notifications_postcondition,
            my_posts_action=my_posts_action,
            my_posts_postcondition=my_posts_postcondition,
        )
    except LinkedInEngagementRestoreFailed as exc:
        return _engagement_terminal(
            state='technical_failure',
            failure_code='restore_indeterminate',
            records_observed=records_observed,
            records_written=records_written,
            content_digest=content_digest,
            start=start,
            notifications_action=notifications_action,
            notifications_postcondition=notifications_postcondition,
            my_posts_action=my_posts_action,
            my_posts_postcondition=my_posts_postcondition,
            candidate_count=candidate_count,
            sink_verdict=sink_verdict,
            signal_postcondition=signal_verdict,
            restore=exc.receipt,
        )
    except LinkedInJobsDeadlineExpired:
        return _engagement_terminal(
            state='sink_write_indeterminate' if phase == 'sink_write' else 'technical_failure',
            failure_code=(
                'sink_write_indeterminate'
                if phase == 'sink_write'
                else ('restore_indeterminate' if phase == 'restore' else 'deadline_expired')
            ),
            records_observed=records_observed,
            records_written=None if phase == 'sink_write' else records_written,
            content_digest=content_digest,
            start=start,
            notifications_action=notifications_action,
            notifications_postcondition=notifications_postcondition,
            my_posts_action=my_posts_action,
            my_posts_postcondition=my_posts_postcondition,
            candidate_count=candidate_count,
            sink_verdict='indeterminate' if phase == 'sink_write' else sink_verdict,
            signal_postcondition=signal_verdict,
        )
    except Exception:
        return _engagement_terminal(
            state='technical_failure',
            failure_code=(
                'restore_indeterminate'
                if phase == 'restore'
                else (
                    'post_observation_indeterminate'
                    if phase in {
                        'notifications_postcondition',
                        'my_posts_postcondition',
                        'signal_postcondition',
                    }
                    else 'pre_observation_failed'
                )
            ),
            records_observed=records_observed,
            records_written=records_written,
            content_digest=content_digest,
            start=start,
            notifications_action=notifications_action,
            notifications_postcondition=notifications_postcondition,
            my_posts_action=my_posts_action,
            my_posts_postcondition=my_posts_postcondition,
            candidate_count=candidate_count,
            sink_verdict=sink_verdict,
            signal_postcondition=signal_verdict,
        )


def _finalize_engagement(
    *,
    receipt_path: Path,
    display: str,
    requester: str,
    hands_commit: str,
    transaction_sha256: str | None,
    expected_transaction_sha256: str,
    source_ref: str | None,
    sink_ref: str | None,
    notifications_name: str | None,
    return_url: str | None,
    lock_lineage: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> dict[str, Any]:
    from consultation_v2.linkedin_jobs_contract import (
        ENGAGEMENT_RECEIPT_SCHEMA,
        sha256_hex,
        validate_public_result,
        write_new_private_json,
    )

    yaml_path = REPO_ROOT / 'consultation_v2/platforms/linkedin/linkedin.yaml'
    receipt = {
        'schema': ENGAGEMENT_RECEIPT_SCHEMA,
        'platform': 'linkedin',
        'operation': 'capture_visible_new_engagement_signal',
        'display': display,
        'requester': requester,
        'turn_lineage_sha256': lock_lineage['turn_lineage_sha256'],
        'correlation_id_sha256': lock_lineage['correlation_id_sha256'],
        'deadline_seconds': lock_lineage['deadline_seconds'],
        'hands_commit': hands_commit,
        'yaml_sha256': sha256_hex(yaml_path.read_bytes()),
        'terminal_state': terminal['terminal_state'],
        'ok': terminal['ok'],
        'failure_code': terminal['failure_code'],
        'records_observed': terminal['records_observed'],
        'records_written': terminal['records_written'],
        'content_digest': terminal['content_digest'],
        'restore_verified': terminal['restore_verified'],
        'transaction_sha256': transaction_sha256,
        'expected_transaction_sha256': expected_transaction_sha256,
        'source_ref_sha256': _digest_text(source_ref),
        'sink_ref_sha256': _digest_text(sink_ref),
        'notifications_name_sha256': _digest_text(notifications_name),
        'return_url_sha256': _digest_text(return_url),
        'start': terminal['start'],
        'notifications_action': terminal['notifications_action'],
        'notifications_postcondition': terminal['notifications_postcondition'],
        'my_posts_action': terminal['my_posts_action'],
        'my_posts_postcondition': terminal['my_posts_postcondition'],
        'candidate': {
            'match_count': terminal['candidate_count'],
            'content_digest': terminal['content_digest'],
        },
        'sink': {
            'kind': 'private_sink_write_once',
            'verdict': terminal['sink_verdict'],
            'records_written': terminal['records_written'],
        },
        'signal_postcondition': terminal['signal_postcondition'],
        'restore': terminal['restore'],
        'lock': dict(lock_lineage),
    }
    receipt_sha256 = sha256_hex(write_new_private_json(receipt_path, receipt))
    return validate_public_result({
        'ok': terminal['ok'],
        'platform': 'linkedin',
        'display': display,
        'state': terminal['terminal_state'],
        'failure_code': terminal['failure_code'],
        'records_observed': terminal['records_observed'],
        'records_written': terminal['records_written'],
        'content_digest': terminal['content_digest'],
        'receipt_sha256': receipt_sha256,
        'turn_lineage_sha256': lock_lineage['turn_lineage_sha256'],
        'restore_verified': terminal['restore_verified'],
    })


def run(args: argparse.Namespace) -> dict[str, Any]:
    from consultation_v2.display_lock import (
        CAREERS_POLICY,
        display_lock_ttl,
        entrypoint_display_lock,
    )
    from consultation_v2.linkedin_jobs_contract import (
        read_private_input,
        validate_external_private_root,
        validate_new_private_output_beneath_root,
        validate_path_beneath_private_root,
        validate_requester,
    )

    requester = validate_requester(args.requester)
    hands_commit = _current_commit()
    private_root = validate_external_private_root(args.private_root, REPO_ROOT)
    receipt_path = validate_new_private_output_beneath_root(
        Path(args.receipt_file),
        private_root,
    )
    turn_lineage_sha256 = _turn_lineage_sha256(
        requester,
        args.turn_id,
        args.correlation_id,
        args.process_generation,
    )
    correlation_id_sha256 = _digest_text(args.correlation_id)
    if correlation_id_sha256 is None:
        raise RuntimeError('correlation lineage could not be established')
    transaction_sha256: str | None = None
    operation: str | None = None
    search_ref: str | None = None
    sink_ref: str | None = None
    source_ref: str | None = None
    notifications_name: str | None = None
    return_url: str | None = None
    target_card_name: str | None = None
    detail_title_name: str | None = None
    detail_company_name: str | None = None
    unlocked_lineage = {
        'policy': CAREERS_POLICY,
        'request_id': turn_lineage_sha256,
        'acquired': False,
        'released': False,
        'owner_token_sha256': None,
        'wait_ms': 0,
        'turn_lineage_sha256': turn_lineage_sha256,
        'correlation_id_sha256': correlation_id_sha256,
        'deadline_seconds': args.deadline_seconds,
    }
    try:
        transaction, transaction_sha256 = read_private_input(
            args.transaction_file,
            REPO_ROOT,
            private_root,
        )
        operation = transaction['operation']
        if transaction_sha256 != args.expected_transaction_sha256:
            raise RuntimeError('transaction digest differs from the permanent claim')
        sink_ref = transaction['sink_ref']
        if operation == 'capture_visible_new_engagement_signal':
            source_ref = transaction['source_ref']
            notifications_name = transaction['notifications_name']
            return_url = transaction['return_url']
        else:
            search_ref = transaction['search_ref']
            target_card_name = transaction.get('target_card_name')
            detail_title_name = transaction.get('detail_title_name')
            detail_company_name = transaction.get('detail_company_name')
        sink_root = validate_path_beneath_private_root(
            sink_ref,
            private_root,
            'private sink',
        )
    except Exception as exc:
        sys.stderr.write(f'{type(exc).__name__}: private transaction rejected\n')
        if operation is None:
            raise
        if operation == 'capture_visible_new_engagement_signal':
            return _finalize_engagement(
                receipt_path=receipt_path,
                display=args.display,
                requester=requester,
                hands_commit=hands_commit,
                transaction_sha256=transaction_sha256,
                expected_transaction_sha256=args.expected_transaction_sha256,
                source_ref=source_ref,
                sink_ref=sink_ref,
                notifications_name=notifications_name,
                return_url=return_url,
                lock_lineage=unlocked_lineage,
                terminal=_engagement_terminal(
                    state='technical_failure',
                    failure_code='private_input_invalid',
                ),
            )
        return _finalize(
            receipt_path=receipt_path,
            display=args.display,
            requester=requester,
            hands_commit=hands_commit,
            operation=operation,
            terminal_state='technical_failure',
            ok=False,
            failure_code='private_input_invalid',
            transaction_sha256=transaction_sha256,
            expected_transaction_sha256=args.expected_transaction_sha256,
            search_ref=search_ref,
            sink_ref=sink_ref,
            pre_observation_sha256=None,
            pre_match_counts=_EMPTY_MATCH_COUNTS,
            selection=_selection_receipt(
                verdict=(
                    'not_required'
                    if operation == 'capture_selected_job'
                    else 'not_executed'
                ),
                target_card_name=target_card_name,
                detail_title_name=detail_title_name,
                detail_company_name=detail_company_name,
                target_match_count=0,
                detail_title_match_count=None,
                detail_company_match_count=None,
                stable_cycles_observed=0,
            ),
            lock_lineage=unlocked_lineage,
            action_verdict='not_executed',
            records_observed=0,
            records_written=0,
            postcondition_verdict='not_evaluated',
            post_observation_sha256=None,
            post_match_counts=None,
        )

    if operation is None:
        raise RuntimeError('private transaction operation was not established')

    request_id = _lock_request_id(transaction_sha256, turn_lineage_sha256)
    deadline_at = time.monotonic() + args.deadline_seconds
    with entrypoint_display_lock(
        display=args.display,
        policy=CAREERS_POLICY,
        request_id=request_id,
        entrypoint='scripts/run_linkedin_jobs.py',
        payload={
            'platform': 'linkedin',
            'requester': requester,
            'transaction_sha256': transaction_sha256,
            'expected_transaction_sha256': args.expected_transaction_sha256,
            'operation': operation,
            'turn_lineage_sha256': turn_lineage_sha256,
            'correlation_id_sha256': correlation_id_sha256,
            'deadline_seconds': args.deadline_seconds,
        },
        wait_seconds=0.0,
        ttl=display_lock_ttl(args.deadline_seconds),
    ) as lock:
        if operation == 'capture_visible_new_engagement_signal':
            if notifications_name is None or return_url is None:
                raise RuntimeError('engagement transaction identity is incomplete')
            terminal = _execute_engagement_transaction(
                lock=lock,
                display=args.display,
                deadline_at=deadline_at,
                sink_root=sink_root,
                notifications_name=notifications_name,
                return_url=return_url,
            )
        else:
            if search_ref is None:
                raise RuntimeError('job transaction search reference is incomplete')
            terminal = _execute_locked_transaction(
                lock=lock,
                display=args.display,
                deadline_at=deadline_at,
                operation=operation,
                search_ref=search_ref,
                sink_root=sink_root,
                target_card_name=target_card_name,
                detail_title_name=detail_title_name,
                detail_company_name=detail_company_name,
            )

    lineage = _lock_lineage(
        lock,
        request_id,
        turn_lineage_sha256,
        correlation_id_sha256,
        args.deadline_seconds,
    )
    if (
        lineage['acquired']
        and not lineage['released']
        and terminal['failure_code'] != 'sink_write_indeterminate'
    ):
        terminal['terminal_state'] = 'technical_failure'
        terminal['ok'] = False
        terminal['failure_code'] = 'lock_release_indeterminate'

    if operation == 'capture_visible_new_engagement_signal':
        return _finalize_engagement(
            receipt_path=receipt_path,
            display=args.display,
            requester=requester,
            hands_commit=hands_commit,
            transaction_sha256=transaction_sha256,
            expected_transaction_sha256=args.expected_transaction_sha256,
            source_ref=source_ref,
            sink_ref=sink_ref,
            notifications_name=notifications_name,
            return_url=return_url,
            lock_lineage=lineage,
            terminal=terminal,
        )
    return _finalize(
        receipt_path=receipt_path,
        display=args.display,
        requester=requester,
        hands_commit=hands_commit,
        operation=operation,
        transaction_sha256=transaction_sha256,
        expected_transaction_sha256=args.expected_transaction_sha256,
        search_ref=search_ref,
        sink_ref=sink_ref,
        lock_lineage=lineage,
        **terminal,
    )


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run(args)
    except Exception as exc:
        sys.stderr.write(f'{type(exc).__name__}: transaction aborted before durable terminal\n')
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n')
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
