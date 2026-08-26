#!/usr/bin/env python3
from __future__ import annotations

import ast
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

CONTRACT = REPO_ROOT / 'consultation_v2/linkedin_jobs_restore_contract.py'
RUNNER = REPO_ROOT / 'scripts/run_linkedin_jobs_restore.py'
SCHEMA = (
    REPO_ROOT
    / 'consultation_v2/platforms/linkedin/jobs-restore-receipt.schema.json'
)
PRIVATE_SENTINEL = 'linkedin-restore-private-sentinel'
TARGET_URL = (
    'https://www.linkedin.com/jobs/search-results/'
    f'?keywords={PRIVATE_SENTINEL}'
)
_DIGEST = 'a' * 64
_FIREFOX_DIGEST = 'b' * 64


def _write_private(path: Path, raw_bytes: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        pending = memoryview(raw_bytes)
        while pending:
            written = os.write(descriptor, pending)
            assert written > 0
            pending = pending[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o400)
    finally:
        os.close(descriptor)


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        'linkedin_jobs_restore_validator_runner',
        RUNNER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _success_restore(contract) -> dict[str, Any]:
    return {
        'verdict': 'satisfied',
        'failed_substep': None,
        'firefox_pid_sha256': _FIREFOX_DIGEST,
        'stable_cycles_required': 2,
        'stable_cycles_observed': 2,
        'return_url_sha256': contract.sha256_hex(TARGET_URL.encode('utf-8')),
    }


def _lineage() -> dict[str, Any]:
    return {
        'policy': 'careers',
        'request_id': _DIGEST,
        'acquired': True,
        'released': True,
        'owner_token_sha256': _DIGEST,
        'wait_ms': 0,
        'turn_lineage_sha256': _DIGEST,
        'correlation_id_sha256': _DIGEST,
        'deadline_seconds': 120,
    }


def _validate_source_shape() -> None:
    for path in (CONTRACT, RUNNER):
        ast.parse(path.read_text(encoding='utf-8'))
    runner_source = RUNNER.read_text(encoding='utf-8')
    runner_tree = ast.parse(runner_source)
    calls = [node for node in ast.walk(runner_tree) if isinstance(node, ast.Call)]
    exact_return_calls = [
        call for call in calls
        if isinstance(call.func, ast.Name)
        and call.func.id == 'exact_engagement_return'
    ]
    lock_calls = [
        call for call in calls
        if isinstance(call.func, ast.Name)
        and call.func.id == 'entrypoint_display_lock'
    ]
    assert len(exact_return_calls) == 1
    assert len(lock_calls) == 1
    wait_values = [
        keyword.value
        for keyword in lock_calls[0].keywords
        if keyword.arg == 'wait_seconds'
    ]
    assert len(wait_values) == 1
    assert isinstance(wait_values[0], ast.Constant)
    assert wait_values[0].value == 0.0
    for forbidden in (
        '/' + 'home/' + 'mira',
        '10.' + '0.' + '0.',
        'build_snapshot(',
        'clipboard_paste(',
        'do_action(',
        'find_elements',
        'get_extents',
        'press_key_cleared(',
        'pyautogui',
        'xdotool',
    ):
        assert forbidden not in runner_source


def _validate_private_contract(base: Path, contract) -> str:
    private_root = base / 'private'
    private_root.mkdir(mode=0o700)
    transaction = {
        'schema': contract.PRIVATE_INPUT_SCHEMA,
        'operation': contract.OPERATION,
        'return_url': TARGET_URL,
    }
    transaction_path = private_root / 'transactions' / 'valid.json'
    raw_bytes = contract.canonical_json_bytes(transaction)
    _write_private(transaction_path, raw_bytes)
    parsed, digest = contract.read_private_input(transaction_path, private_root)
    assert parsed == transaction
    assert digest == contract.sha256_hex(raw_bytes)

    invalid_values = (
        ('extra-field', {**transaction, 'scope': 'forbidden'}),
        ('wrong-operation', {**transaction, 'operation': 'capture_selected_job'}),
        ('wrong-schema', {**transaction, 'schema': 'linkedin_jobs_private_input_v1'}),
        ('wrong-url', {**transaction, 'return_url': 'https://example.com/jobs/search-results/'}),
    )
    for name, value in invalid_values:
        path = private_root / 'transactions' / f'{name}.json'
        _write_private(path, contract.canonical_json_bytes(value))
        try:
            contract.read_private_input(path, private_root)
        except Exception:
            pass
        else:
            raise AssertionError(f'{name} was accepted')

    noncanonical = private_root / 'transactions' / 'noncanonical.json'
    _write_private(noncanonical, raw_bytes + b'\n')
    try:
        contract.read_private_input(noncanonical, private_root)
    except Exception:
        pass
    else:
        raise AssertionError('noncanonical transaction was accepted')

    duplicate = private_root / 'transactions' / 'duplicate.json'
    _write_private(
        duplicate,
        (
            '{"operation":"restore_linkedin_jobs_surface",'
            '"operation":"restore_linkedin_jobs_surface",'
            f'"return_url":"{TARGET_URL}",'
            '"schema":"linkedin_jobs_restore_private_input_v1"}'
        ).encode('utf-8'),
    )
    try:
        contract.read_private_input(duplicate, private_root)
    except Exception:
        pass
    else:
        raise AssertionError('duplicate transaction field was accepted')
    return digest


def _validate_execution_and_receipt(base: Path, contract, runner) -> None:
    from consultation_v2.platforms.linkedin import driver

    original_return = driver.exact_engagement_return
    original_bind = runner._bind_display
    original_deadline = runner._internal_deadline
    calls: list[tuple[str, str, float]] = []

    def success(display: str, return_url: str, deadline_at: float):
        calls.append((display, return_url, deadline_at))
        return _success_restore(contract)

    try:
        driver.exact_engagement_return = success
        runner._bind_display = lambda _display: None
        runner._internal_deadline = lambda _deadline: nullcontext()
        terminal = runner._execute(
            lock={'acquired': True},
            display=':18',
            deadline_at=100.0,
            return_url=TARGET_URL,
        )
        assert len(calls) == 1
        assert terminal['state'] == 'restored' and terminal['ok'] is True
        assert terminal['stable_cycles_observed'] == 2
        assert terminal['restore'] == _success_restore(contract)

        output = base / 'receipt-parent'
        output.mkdir(mode=0o700)
        receipt_path = output / 'receipt.json'
        public_result = runner._finalize(
            receipt_path=receipt_path,
            display=':18',
            requester='linkedin-restore-validator',
            hands_commit='c' * 40,
            transaction_sha256=_DIGEST,
            expected_transaction_sha256=_DIGEST,
            target_url_sha256=contract.sha256_hex(TARGET_URL.encode('utf-8')),
            lock_lineage=_lineage(),
            terminal=terminal,
        )
        contract.validate_public_result(public_result)
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(receipt)
        assert receipt_bytes == contract.canonical_json_bytes(receipt)
        assert receipt['restore_proof_sha256'] == contract.sha256_hex(
            contract.canonical_json_bytes(receipt['restore'])
        )
        assert public_result['restore_proof_sha256'] == receipt[
            'restore_proof_sha256'
        ]
        assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o400
        assert PRIVATE_SENTINEL not in receipt_bytes.decode('utf-8')
        assert PRIVATE_SENTINEL not in json.dumps(public_result, sort_keys=True)

        calls.clear()

        def failed(display: str, return_url: str, deadline_at: float):
            calls.append((display, return_url, deadline_at))
            receipt = {
                'verdict': 'indeterminate',
                'failed_substep': 'address_bar_focus',
                'firefox_pid_sha256': _FIREFOX_DIGEST,
                'stable_cycles_required': 0,
                'stable_cycles_observed': 0,
                'return_url_sha256': contract.sha256_hex(
                    return_url.encode('utf-8')
                ),
            }
            raise driver.LinkedInEngagementRestoreFailed(
                'address_bar_focus',
                receipt,
            )

        driver.exact_engagement_return = failed
        failure = runner._execute(
            lock={'acquired': True},
            display=':18',
            deadline_at=100.0,
            return_url=TARGET_URL,
        )
        assert len(calls) == 1
        assert failure['state'] == 'technical_failure'
        assert failure['failure_code'] == 'restore_indeterminate'
        calls.clear()
        refused = runner._execute(
            lock={'acquired': False},
            display=':18',
            deadline_at=100.0,
            return_url=TARGET_URL,
        )
        assert refused['failure_code'] == 'display_lock_unavailable'
        assert calls == []
    finally:
        driver.exact_engagement_return = original_return
        runner._bind_display = original_bind
        runner._internal_deadline = original_deadline


def main() -> int:
    from consultation_v2 import linkedin_jobs_restore_contract as contract

    _validate_source_shape()
    runner = _load_runner()
    with tempfile.TemporaryDirectory(prefix='linkedin-restore-validator-') as raw:
        base = Path(raw)
        _validate_private_contract(base, contract)
        _validate_execution_and_receipt(base, contract, runner)
    print('PASS LinkedIn Jobs standalone restore contract')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
