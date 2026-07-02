"""External storage policy for consultation_v2.

Consult delivery is local-first: extracted responses must be returned to the
requester and written to the caller's output file even when Neo4j/ISMA storage
is disabled or unhealthy. External stores are therefore opt-in and bounded.
"""
from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from typing import Callable, TypeVar


_MACHINE_ENV = Path(os.environ.get('TAEY_MACHINE_ENV', '~/.taey/machine.env')).expanduser()
_STORE_ENABLED_KEYS = (
    'TAEY_CONSULTATION_STORE_ENABLED',
    'CONSULTATION_V2_STORE_ENABLED',
)
_STORE_TIMEOUT_KEYS = (
    'TAEY_CONSULTATION_STORE_TIMEOUT_SECONDS',
    'CONSULTATION_V2_STORE_TIMEOUT_SECONDS',
)
_TRUE_VALUES = {'1', 'true', 'yes', 'on', 'enabled'}
_FALSE_VALUES = {'', '0', 'false', 'no', 'off', 'disabled'}
_DEFAULT_STORE_TIMEOUT_SECONDS = 8.0

T = TypeVar('T')


class StorePolicyError(RuntimeError):
    """External storage configuration is invalid."""


class StoreTimeoutError(TimeoutError):
    """External storage exceeded its bounded timeout."""


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _read_machine_env_value(name: str) -> str:
    try:
        lines = _MACHINE_ENV.read_text().splitlines()
    except FileNotFoundError:
        return ''
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        if key.strip() == name:
            return _strip_env_value(value)
    return ''


def env_or_machine(name: str) -> str:
    return str(os.environ.get(name) or _read_machine_env_value(name) or '').strip()


def _first_config_value(names: tuple[str, ...]) -> tuple[str, str]:
    for name in names:
        value = env_or_machine(name)
        if value:
            return name, value
    return '', ''


def _parse_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise StorePolicyError(
        f'{name} must be one of {sorted(_TRUE_VALUES | _FALSE_VALUES)}; got {value!r}'
    )


def store_config_enabled() -> bool:
    name, value = _first_config_value(_STORE_ENABLED_KEYS)
    if not name:
        return False
    return _parse_bool(name, value)


def external_store_enabled(request: object | None = None) -> bool:
    if bool(getattr(request, 'no_neo4j', False)):
        return False
    if bool(getattr(request, 'store_enabled', False)):
        return True
    return store_config_enabled()


def disabled_record(request: object | None = None) -> dict[str, object]:
    if bool(getattr(request, 'no_neo4j', False)):
        reason = 'external storage disabled for this request'
    else:
        reason = (
            'external storage disabled by default; set '
            'TAEY_CONSULTATION_STORE_ENABLED=1 or pass --store to enable'
        )
    return {
        'stored': False,
        'skipped': True,
        'reason': reason,
    }


def store_timeout_seconds() -> float:
    name, value = _first_config_value(_STORE_TIMEOUT_KEYS)
    if not name:
        return _DEFAULT_STORE_TIMEOUT_SECONDS
    try:
        timeout = float(value)
    except ValueError as exc:
        raise StorePolicyError(f'{name} must be a positive number; got {value!r}') from exc
    if timeout <= 0:
        raise StorePolicyError(f'{name} must be positive; got {value!r}')
    return timeout


def run_bounded_store_call(
    label: str,
    callback: Callable[[], T],
    *,
    timeout_seconds: float | None = None,
) -> T:
    timeout = float(timeout_seconds or store_timeout_seconds())
    started = time.monotonic()
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def _on_timeout(_signum, _frame):
        elapsed = time.monotonic() - started
        raise StoreTimeoutError(f'{label} exceeded {timeout:.1f}s after {elapsed:.3f}s')

    signal.signal(signal.SIGALRM, _on_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        return callback()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)
        previous_remaining, previous_interval = previous_timer
        if previous_remaining > 0:
            elapsed = time.monotonic() - started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(previous_remaining - elapsed, 0.001),
                previous_interval,
            )
