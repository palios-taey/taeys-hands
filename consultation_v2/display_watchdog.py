from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Iterator

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 300.0


def display_number(display: str) -> str:
    value = str(display or '').strip()
    if value.startswith(':'):
        value = value[1:]
    value = value.split('.', 1)[0]
    if not value or not value.isdigit():
        raise ValueError(f'invalid display for watchdog pause flag: {display!r}')
    return value


def pause_flag_paths(platform: str, display: str) -> tuple[Path, ...]:
    platform_key = str(platform or '').strip()
    if not platform_key or '/' in platform_key:
        raise ValueError(f'invalid platform for watchdog pause flag: {platform!r}')
    root = Path.home() / '.taey'
    paths = [
        root / f'display_watchdog_pause_{platform_key}',
        root / f'display_watchdog_pause_{display_number(display)}',
    ]
    return tuple(dict.fromkeys(paths))


def _remove_pause_flags(paths: tuple[Path, ...]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.error("Failed to remove display watchdog pause flag %s: %s", path, exc)


def _pause_payload(platform: str, display: str) -> str:
    return (
        f'platform={platform}\n'
        f'display={display}\n'
        f'refreshed_at={datetime.now(timezone.utc).isoformat()}\n'
    )


def _touch_pause_flags(paths: tuple[Path, ...], platform: str, display: str) -> None:
    payload = _pause_payload(platform, display)
    for path in paths:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(payload)


def _heartbeat_pause_flags(
    paths: tuple[Path, ...],
    platform: str,
    display: str,
    stop: Event,
    interval_seconds: float,
) -> None:
    while not stop.wait(interval_seconds):
        try:
            _touch_pause_flags(paths, platform, display)
        except OSError as exc:
            logger.error("Failed to refresh display watchdog pause flags %s: %s", paths, exc)


@contextmanager
def pause_display_watchdog(
    platform: str,
    display: str,
    *,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> Iterator[tuple[Path, ...]]:
    paths = pause_flag_paths(platform, display)
    stop = Event()
    heartbeat = Thread(
        target=_heartbeat_pause_flags,
        args=(paths, platform, display, stop, heartbeat_seconds),
        name=f'display-watchdog-pause-{platform}-{display_number(display)}',
        daemon=True,
    )
    try:
        _touch_pause_flags(paths, platform, display)
    except OSError:
        _remove_pause_flags(paths)
        raise
    heartbeat.start()
    try:
        yield paths
    finally:
        stop.set()
        heartbeat.join(timeout=2.0)
        if heartbeat.is_alive():
            logger.error("Display watchdog pause heartbeat did not stop cleanly for %s", paths)
        _remove_pause_flags(paths)
