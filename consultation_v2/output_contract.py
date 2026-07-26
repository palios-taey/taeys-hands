from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


class OutputContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutputTargets:
    result: Path
    response: Path
    lock: Path


def _targets(output_path: str) -> OutputTargets:
    result = Path(output_path)
    response = result.with_suffix('.txt')
    if response == result:
        raise OutputContractError(
            f'--output {str(result)!r} cannot use a .txt suffix because the '
            'same-run response sibling is also .txt'
        )
    lock = result.with_name(f'.{result.name}.consultation-output.lock')
    return OutputTargets(result=result, response=response, lock=lock)


@contextmanager
def reserve_output_targets(output_path: str) -> Iterator[OutputTargets]:
    targets = _targets(output_path)
    if not targets.result.parent.is_dir():
        raise OutputContractError(
            f'--output parent directory does not exist: '
            f'{str(targets.result.parent)!r}'
        )
    try:
        lock_fd = os.open(
            targets.lock,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as exc:
        raise OutputContractError(
            f'output namespace is already reserved by another run: '
            f'{str(targets.lock)!r}'
        ) from exc
    except OSError as exc:
        raise OutputContractError(
            f'cannot reserve output namespace {str(targets.lock)!r}: {exc}'
        ) from exc
    try:
        with os.fdopen(lock_fd, 'w', encoding='utf-8') as handle:
            handle.write(f'pid={os.getpid()}\n')
        conflicts = [
            str(path)
            for path in (targets.result, targets.response)
            if path.exists()
        ]
        if conflicts:
            raise OutputContractError(
                'consultation output paths already exist; use a unique '
                'run-id or timestamped output directory: '
                + ', '.join(conflicts)
            )
        yield targets
    finally:
        targets.lock.unlink(missing_ok=True)


def _atomic_write(path: Path, content: str) -> None:
    temp_path: str | None = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=f'.{path.name}.',
            suffix='.tmp',
            text=True,
        )
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    except OSError as exc:
        raise OutputContractError(
            f'failed to write consultation output {str(path)!r}: {exc}'
        ) from exc
    finally:
        if temp_path is not None:
            Path(temp_path).unlink(missing_ok=True)


def write_dry_run_output(targets: OutputTargets, payload: dict[str, Any]) -> None:
    _atomic_write(targets.result, json.dumps(payload, indent=2, sort_keys=True))


def write_consultation_outputs(
    targets: OutputTargets,
    payload: dict[str, Any],
    response_text: str,
) -> None:
    _atomic_write(targets.response, response_text)
    _atomic_write(targets.result, json.dumps(payload, indent=2, sort_keys=True))
