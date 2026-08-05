#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
from typing import Any, Mapping
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_DISPLAY_RE = re.compile(r'^:[0-9]{1,3}$')
_GIT_COMMIT_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
_REQUEST_LIMIT = 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Run the approval-gated supervised Taey UI Hands worker.',
    )
    parser.add_argument(
        '--platform',
        required=True,
        choices=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'],
    )
    parser.add_argument('--display', required=True)
    parser.add_argument('--receipt-root', required=True)
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--presence-incarnation-id', required=True)
    parser.add_argument('--lease-expires-at', required=True)
    parser.add_argument('--lease-secret-env', required=True)
    parser.add_argument('--hands-commit', required=True)
    parser.add_argument('--public-repo-root', action='append', required=True)
    parser.add_argument('--lock-wait-seconds', type=float, default=0.0)
    return parser


def _strict_json(raw_text: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate key')
            value[key] = item
        return value

    parsed = json.loads(
        raw_text,
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError('non-JSON constant')),
    )
    if not isinstance(parsed, dict):
        raise ValueError('request must be an object')
    return parsed


def _require_keys(value: Mapping[str, Any], required: frozenset[str]) -> None:
    if frozenset(value) != required:
        raise ValueError('request fields are incomplete or unknown')


def _uuid_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError('request_id must be a UUID')
    parsed = uuid.UUID(value)
    if str(parsed) != value:
        raise ValueError('request_id must be a lowercase canonical UUID')
    return value


def _decode_b64(value: Any, context: str, *, minimum: int = 1) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f'{context} must be base64')
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError(f'{context} must be base64') from exc
    if len(decoded) < minimum:
        raise ValueError(f'{context} is too short')
    return decoded


def _bind_display(display: str) -> None:
    if not _DISPLAY_RE.fullmatch(display):
        raise RuntimeError('display must use the :N form')
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


def _lease_runtime_seconds(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise RuntimeError('lease expiry must include a timezone')
    remaining = (parsed.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        raise RuntimeError('lease is already expired')
    return remaining


def _emit(value: Mapping[str, Any], seat: Any | None = None) -> None:
    try:
        sys.stdout.write(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
        sys.stdout.flush()
    except BrokenPipeError:
        if seat is not None:
            seat.mark_response_loss()
        raise


def _approval_request(request: Mapping[str, Any]) -> tuple[str, bytes, Mapping[str, Any], bytes]:
    _require_keys(
        request,
        frozenset({'approval', 'capability_b64', 'command', 'proposal_b64', 'request_id'}),
    )
    request_id = _uuid_text(request['request_id'])
    proposal_bytes = _decode_b64(request['proposal_b64'], 'proposal_b64')
    capability = _decode_b64(request['capability_b64'], 'capability_b64', minimum=32)
    approval = request['approval']
    if not isinstance(approval, dict):
        raise ValueError('approval must be an object')
    return request_id, proposal_bytes, approval, capability


def _serve(seat: Any) -> int:
    _emit({'ok': True, 'type': 'handshake', **seat.handshake()}, seat)
    for raw_line in sys.stdin:
        if len(raw_line.encode('utf-8')) > _REQUEST_LIMIT:
            seat.reject_protocol('request_too_large')
            _emit({'ok': False, 'refusal_class': 'request_too_large', 'state': seat.state}, seat)
            return 2
        request_id: str | None = None
        try:
            request = _strict_json(raw_line)
            command = request.get('command')
            if command in {'execute_approved', 'observe'}:
                request_id, proposal_bytes, approval, capability = _approval_request(request)
                proposal = _strict_json(proposal_bytes.decode('utf-8'))
                operation = proposal.get('op')
                if command == 'observe' and operation not in {'observe', 'verify'}:
                    raise ValueError('observe command requires a read proposal')
                if command == 'execute_approved' and operation not in {'activate', 'focus'}:
                    raise ValueError('execute_approved requires an action proposal')
                result = seat.execute_approved(proposal_bytes, approval, capability)
                _emit({
                    'ok': True,
                    'request_id': request_id,
                    'result': result,
                    'state': seat.state,
                }, seat)
                continue
            if command == 'cancel':
                _require_keys(request, frozenset({'command', 'request_id'}))
                request_id = _uuid_text(request['request_id'])
                result = seat.cancel()
                _emit({'ok': True, 'request_id': request_id, 'result': result}, seat)
                return 0
            if command == 'close':
                _require_keys(request, frozenset({'command', 'request_id'}))
                request_id = _uuid_text(request['request_id'])
                result = seat.close()
                _emit({'ok': True, 'request_id': request_id, 'result': result})
                return 0
            raise ValueError('unknown command')
        except ValueError:
            if seat.state not in {'cancelled', 'failed', 'indeterminate', 'rejected', 'replayed', 'stale'}:
                seat.reject_protocol('protocol_invalid')
            _emit({
                'ok': False,
                'refusal_class': 'protocol_invalid',
                'request_id': request_id,
                'state': seat.state,
            }, seat)
            return 2
        except Exception as exc:
            refusal_class = getattr(exc, 'refusal_class', 'worker_failure')
            _emit({
                'ok': False,
                'refusal_class': refusal_class,
                'request_id': request_id,
                'state': seat.state,
            }, seat)
            return 2
    seat.mark_response_loss()
    return 2


def main() -> int:
    args = build_parser().parse_args()
    if args.lock_wait_seconds < 0:
        raise RuntimeError('lock wait must be nonnegative')
    actual_commit = _current_commit()
    if args.hands_commit != actual_commit:
        raise RuntimeError('declared Hands commit does not match the running checkout')
    lease_runtime = _lease_runtime_seconds(args.lease_expires_at)
    secret_value = os.environ.pop(args.lease_secret_env, None)
    if secret_value is None:
        raise RuntimeError('lease secret environment variable is missing')
    lease_secret = _decode_b64(secret_value, 'lease_secret', minimum=32)
    _bind_display(args.display)

    from consultation_v2.display_lock import display_lock_ttl, entrypoint_display_lock
    from consultation_v2.supervised_ui_receipts import HandsReceiptStore
    from consultation_v2.supervised_ui_seat import SupervisedUiSeat

    hands_incarnation_id = str(uuid.uuid4())
    public_roots = [str(REPO_ROOT.resolve(strict=True)), *args.public_repo_root]
    resolved_public_roots = {str(Path(root).resolve(strict=True)) for root in public_roots}
    if len(resolved_public_roots) < 2:
        raise RuntimeError('Hands and at least one additional public repository root are required')
    if any(not (Path(root) / '.git').exists() for root in resolved_public_roots):
        raise RuntimeError('every public repository root must identify a Git checkout')
    store = HandsReceiptStore.open_external(
        args.receipt_root,
        sorted(resolved_public_roots),
        session_id=args.session_id,
        presence_incarnation_id=args.presence_incarnation_id,
        hands_incarnation_id=hands_incarnation_id,
        hands_commit=actual_commit,
    )
    seat = None
    try:
        with entrypoint_display_lock(
            display=args.display,
            policy='discretionary',
            request_id=args.session_id,
            entrypoint='scripts/run_supervised_ui_seat.py',
            payload={'seat_mode': 'supervised_ui'},
            wait_seconds=args.lock_wait_seconds,
            ttl=display_lock_ttl(lease_runtime),
        ):
            seat = SupervisedUiSeat(
                platform=args.platform,
                lease_secret=lease_secret,
                lease_expires_at=args.lease_expires_at,
                presence_incarnation_id=args.presence_incarnation_id,
                hands_incarnation_id=hands_incarnation_id,
                hands_commit=actual_commit,
                receipt_store=store,
            )
            return _serve(seat)
    finally:
        if seat is not None and not seat.closed:
            try:
                seat.close()
            except Exception:
                store.close()
        elif seat is None:
            store.close()


def _exit_on_signal(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, _exit_on_signal)
    signal.signal(signal.SIGINT, _exit_on_signal)
    raise SystemExit(main())
