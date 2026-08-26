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
    'structural_candidates': 0,
    'valid_cards': 0,
    'duplicate_cards': 0,
}


class LinkedInJobSearchDeadlineExpired(TimeoutError):
    pass


def _display_argument(value: str) -> str:
    from consultation_v2.linkedin_job_search_contract import validate_display

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
        description='Capture one mounted LinkedIn Jobs search batch into a private sink.',
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


@contextmanager
def _internal_deadline(deadline_at: float) -> Iterator[None]:
    remaining = deadline_at - time.monotonic()
    if remaining <= 0:
        raise LinkedInJobSearchDeadlineExpired('LinkedIn job-search deadline expired')
    prior_delay, prior_interval = signal.getitimer(signal.ITIMER_REAL)
    if prior_delay or prior_interval:
        raise RuntimeError('runner refuses to replace an existing process alarm')
    prior_handler = signal.getsignal(signal.SIGALRM)

    def expire(_signum: int, _frame: Any) -> None:
        raise LinkedInJobSearchDeadlineExpired('LinkedIn job-search deadline expired')

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
            raise RuntimeError('AT-SPI bus binding changed while it was read')
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
    from consultation_v2.linkedin_job_search_contract import sha256_hex

    return sha256_hex(value.encode('utf-8')) if value is not None else None


def _turn_lineage_sha256(
    requester: str,
    turn_id: str,
    correlation_id: str,
    process_generation: str,
) -> str:
    from consultation_v2.linkedin_job_search_contract import canonical_json_bytes, sha256_hex

    return sha256_hex(canonical_json_bytes({
        'correlation_id': correlation_id,
        'process_generation': process_generation,
        'requester': requester,
        'turn_id': turn_id,
    }))


def _lock_request_id(transaction_sha256: str, turn_lineage_sha256: str) -> str:
    from consultation_v2.linkedin_job_search_contract import canonical_json_bytes, sha256_hex

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
        'owner_token_sha256': _digest_text(
            owner_token if isinstance(owner_token, str) else None
        ),
        'wait_ms': int(lock.get('wait_ms') or 0),
        'turn_lineage_sha256': turn_lineage_sha256,
        'correlation_id_sha256': correlation_id_sha256,
        'deadline_seconds': deadline_seconds,
    }


def _terminal(
    *,
    state: str,
    ok: bool,
    failure_code: str | None,
    batches_observed: int = 0,
    batches_written: int | None = 0,
    cards_observed: int = 0,
    content_digest: str | None = None,
    pre_match_counts: Mapping[str, int] = _EMPTY_MATCH_COUNTS,
    stable_cycles_observed: int = 0,
    sink_verdict: str = 'not_executed',
    postcondition_verdict: str = 'not_evaluated',
    post_observation_sha256: str | None = None,
    post_match_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    return {
        'state': state,
        'ok': ok,
        'failure_code': failure_code,
        'batches_observed': batches_observed,
        'batches_written': batches_written,
        'cards_observed': cards_observed,
        'content_digest': content_digest,
        'pre_match_counts': dict(pre_match_counts),
        'stable_cycles_observed': stable_cycles_observed,
        'sink_verdict': sink_verdict,
        'postcondition_verdict': postcondition_verdict,
        'post_observation_sha256': post_observation_sha256,
        'post_match_counts': (
            dict(post_match_counts) if post_match_counts is not None else None
        ),
    }


def _execute(
    *,
    lock: Mapping[str, Any],
    display: str,
    deadline_at: float,
    search_ref: str,
    sink_root: Path,
) -> dict[str, Any]:
    from consultation_v2.platforms.linkedin.search_driver import (
        LinkedInMountedJobSearchUnavailable,
        mounted_job_search_postcondition,
        observation_barrier_policy,
        observe_mounted_job_search,
        write_mounted_job_search_once,
    )
    from consultation_v2.snapshot import build_snapshot

    if lock.get('acquired') is not True:
        return _terminal(
            state='technical_failure',
            ok=False,
            failure_code='display_lock_unavailable',
        )
    before = None
    stable_cycles = 0
    try:
        with _internal_deadline(deadline_at):
            _bind_display(display)
            required_cycles, interval, barrier_timeout = observation_barrier_policy()
            barrier_deadline = min(deadline_at, time.monotonic() + barrier_timeout)
            prior_digest: str | None = None
            while time.monotonic() < barrier_deadline:
                _firefox, _document, snapshot = build_snapshot('linkedin')
                candidate = observe_mounted_job_search(snapshot, search_ref)
                if candidate.content_digest == prior_digest:
                    stable_cycles += 1
                else:
                    stable_cycles = 1
                    prior_digest = candidate.content_digest
                before = candidate
                if stable_cycles >= required_cycles:
                    break
                time.sleep(interval)
            if before is None or stable_cycles < required_cycles:
                raise LinkedInMountedJobSearchUnavailable(
                    'mounted job-search exact postcondition did not stabilize',
                    _EMPTY_MATCH_COUNTS,
                )
    except LinkedInJobSearchDeadlineExpired:
        return _terminal(
            state='technical_failure',
            ok=False,
            failure_code='deadline_expired',
        )
    except LinkedInMountedJobSearchUnavailable as exc:
        return _terminal(
            state='technical_failure',
            ok=False,
            failure_code='pre_observation_failed',
            pre_match_counts=exc.match_counts,
        )
    except Exception:
        return _terminal(
            state='technical_failure',
            ok=False,
            failure_code='pre_observation_failed',
        )

    try:
        with _internal_deadline(deadline_at):
            sink_result = write_mounted_job_search_once(before, sink_root)
    except (LinkedInJobSearchDeadlineExpired, Exception):
        return _terminal(
            state='technical_failure',
            ok=False,
            failure_code='sink_write_indeterminate',
            batches_observed=1,
            batches_written=None,
            cards_observed=before.card_count,
            content_digest=before.content_digest,
            pre_match_counts=before.match_counts,
            stable_cycles_observed=stable_cycles,
            sink_verdict='indeterminate',
        )

    sink_verdict = 'written' if sink_result.batches_written == 1 else 'already_present'
    try:
        with _internal_deadline(deadline_at):
            _firefox, _document, post_snapshot = build_snapshot('linkedin')
            after = observe_mounted_job_search(post_snapshot, search_ref)
    except LinkedInJobSearchDeadlineExpired:
        return _terminal(
            state='technical_failure',
            ok=False,
            failure_code='deadline_expired',
            batches_observed=1,
            batches_written=sink_result.batches_written,
            cards_observed=before.card_count,
            content_digest=before.content_digest,
            pre_match_counts=before.match_counts,
            stable_cycles_observed=stable_cycles,
            sink_verdict=sink_verdict,
            postcondition_verdict='indeterminate',
        )
    except LinkedInMountedJobSearchUnavailable as exc:
        return _terminal(
            state='postcondition_failed',
            ok=False,
            failure_code='postcondition_failed',
            batches_observed=1,
            batches_written=sink_result.batches_written,
            cards_observed=before.card_count,
            content_digest=before.content_digest,
            pre_match_counts=before.match_counts,
            stable_cycles_observed=stable_cycles,
            sink_verdict=sink_verdict,
            postcondition_verdict='failed',
            post_match_counts=exc.match_counts,
        )
    except Exception:
        return _terminal(
            state='technical_failure',
            ok=False,
            failure_code='post_observation_indeterminate',
            batches_observed=1,
            batches_written=sink_result.batches_written,
            cards_observed=before.card_count,
            content_digest=before.content_digest,
            pre_match_counts=before.match_counts,
            stable_cycles_observed=stable_cycles,
            sink_verdict=sink_verdict,
            postcondition_verdict='indeterminate',
        )
    if not mounted_job_search_postcondition(before, after):
        return _terminal(
            state='postcondition_failed',
            ok=False,
            failure_code='postcondition_failed',
            batches_observed=1,
            batches_written=sink_result.batches_written,
            cards_observed=before.card_count,
            content_digest=before.content_digest,
            pre_match_counts=before.match_counts,
            stable_cycles_observed=stable_cycles,
            sink_verdict=sink_verdict,
            postcondition_verdict='failed',
            post_observation_sha256=after.content_digest,
            post_match_counts=after.match_counts,
        )
    state = (
        'no_cards'
        if before.card_count == 0
        else ('captured' if sink_result.batches_written == 1 else 'already_captured')
    )
    return _terminal(
        state=state,
        ok=True,
        failure_code=None,
        batches_observed=1,
        batches_written=sink_result.batches_written,
        cards_observed=before.card_count,
        content_digest=before.content_digest,
        pre_match_counts=before.match_counts,
        stable_cycles_observed=stable_cycles,
        sink_verdict=sink_verdict,
        postcondition_verdict='satisfied',
        post_observation_sha256=after.content_digest,
        post_match_counts=after.match_counts,
    )


def _finalize(
    *,
    receipt_path: Path,
    display: str,
    requester: str,
    hands_commit: str,
    transaction_sha256: str | None,
    expected_transaction_sha256: str,
    search_ref: str | None,
    sink_ref: str | None,
    lock_lineage: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> dict[str, Any]:
    from consultation_v2.linkedin_job_search_contract import (
        OPERATION,
        RECEIPT_SCHEMA,
        sha256_hex,
        validate_public_result,
        write_new_private_json,
    )

    receipt = {
        'schema': RECEIPT_SCHEMA,
        'platform': 'linkedin',
        'operation': OPERATION,
        'display': display,
        'requester': requester,
        'turn_lineage_sha256': lock_lineage['turn_lineage_sha256'],
        'correlation_id_sha256': lock_lineage['correlation_id_sha256'],
        'deadline_seconds': lock_lineage['deadline_seconds'],
        'hands_commit': hands_commit,
        'state': terminal['state'],
        'ok': terminal['ok'],
        'failure_code': terminal['failure_code'],
        'transaction_sha256': transaction_sha256,
        'expected_transaction_sha256': expected_transaction_sha256,
        'search_ref_sha256': _digest_text(search_ref),
        'sink_ref_sha256': _digest_text(sink_ref),
        'pre_observation_sha256': terminal['content_digest'],
        'pre_match_counts': terminal['pre_match_counts'],
        'stable_cycles_observed': terminal['stable_cycles_observed'],
        'lock': dict(lock_lineage),
        'action': {
            'kind': 'private_sink_write_once',
            'verdict': terminal['sink_verdict'],
            'batches_observed': terminal['batches_observed'],
            'batches_written': terminal['batches_written'],
            'cards_observed': terminal['cards_observed'],
            'content_digest': terminal['content_digest'],
        },
        'postcondition': {
            'kind': 'mounted_job_card_set_digest_unchanged',
            'verdict': terminal['postcondition_verdict'],
            'post_observation_sha256': terminal['post_observation_sha256'],
            'post_match_counts': terminal['post_match_counts'],
        },
    }
    receipt_sha256 = sha256_hex(write_new_private_json(receipt_path, receipt))
    return validate_public_result({
        'ok': terminal['ok'],
        'platform': 'linkedin',
        'display': display,
        'state': terminal['state'],
        'failure_code': terminal['failure_code'],
        'batches_observed': terminal['batches_observed'],
        'batches_written': terminal['batches_written'],
        'cards_observed': terminal['cards_observed'],
        'content_digest': terminal['content_digest'],
        'receipt_sha256': receipt_sha256,
        'turn_lineage_sha256': lock_lineage['turn_lineage_sha256'],
    })


def run(args: argparse.Namespace) -> dict[str, Any]:
    from consultation_v2.display_lock import (
        CAREERS_POLICY,
        display_lock_ttl,
        entrypoint_display_lock,
    )
    from consultation_v2.linkedin_job_search_contract import read_private_input
    from consultation_v2.linkedin_jobs_contract import (
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
    search_ref: str | None = None
    sink_ref: str | None = None
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
        if transaction_sha256 != args.expected_transaction_sha256:
            raise RuntimeError('transaction digest differs from the permanent claim')
        search_ref = transaction['search_ref']
        sink_ref = transaction['sink_ref']
        sink_root = validate_path_beneath_private_root(
            sink_ref,
            private_root,
            'private sink',
        )
    except Exception:
        return _finalize(
            receipt_path=receipt_path,
            display=args.display,
            requester=requester,
            hands_commit=hands_commit,
            transaction_sha256=transaction_sha256,
            expected_transaction_sha256=args.expected_transaction_sha256,
            search_ref=search_ref,
            sink_ref=sink_ref,
            lock_lineage=unlocked_lineage,
            terminal=_terminal(
                state='technical_failure',
                ok=False,
                failure_code='private_input_invalid',
            ),
        )
    request_id = _lock_request_id(transaction_sha256, turn_lineage_sha256)
    deadline_at = time.monotonic() + args.deadline_seconds
    with entrypoint_display_lock(
        display=args.display,
        policy=CAREERS_POLICY,
        request_id=request_id,
        entrypoint='scripts/run_linkedin_job_search.py',
        payload={
            'platform': 'linkedin',
            'requester': requester,
            'transaction_sha256': transaction_sha256,
            'expected_transaction_sha256': args.expected_transaction_sha256,
            'operation': transaction['operation'],
            'turn_lineage_sha256': turn_lineage_sha256,
            'correlation_id_sha256': correlation_id_sha256,
            'deadline_seconds': args.deadline_seconds,
        },
        wait_seconds=0.0,
        ttl=display_lock_ttl(args.deadline_seconds),
    ) as lock:
        terminal = _execute(
            lock=lock,
            display=args.display,
            deadline_at=deadline_at,
            search_ref=search_ref,
            sink_root=sink_root,
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
        terminal = {
            **terminal,
            'state': 'technical_failure',
            'ok': False,
            'failure_code': 'lock_release_indeterminate',
        }
    return _finalize(
        receipt_path=receipt_path,
        display=args.display,
        requester=requester,
        hands_commit=hands_commit,
        transaction_sha256=transaction_sha256,
        expected_transaction_sha256=args.expected_transaction_sha256,
        search_ref=search_ref,
        sink_ref=sink_ref,
        lock_lineage=lineage,
        terminal=terminal,
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
