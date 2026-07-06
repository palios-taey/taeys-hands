#!/usr/bin/env python3
"""Consultation V2 CLI entrypoint.

Selects and binds the target display BEFORE importing the V2 CLI. libatspi
(gi.repository.Atspi) reads the bus address once at first use and caches the
connection for the process lifetime, so the env must be correct before the
import chain reaches `from gi.repository import Atspi`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _arg_value(argv: list[str], name: str) -> str | None:
    prefix = f'{name}='
    for index, arg in enumerate(argv):
        if arg == name and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return None


def _select_value(argv: list[str], menu: str) -> str | None:
    for index, arg in enumerate(argv):
        raw = None
        if arg == '--select' and index + 1 < len(argv):
            raw = argv[index + 1]
        elif arg.startswith('--select='):
            raw = arg.split('=', 1)[1]
        if not raw or '=' not in raw:
            continue
        key, value = raw.split('=', 1)
        if key.strip() != menu:
            continue
        value = value.strip()
        if value.startswith('default:'):
            return 'default'
        if value.startswith('none:'):
            return 'none'
        return value
    return None


def _display_lock_free(display: str) -> bool:
    try:
        import redis
        host = os.environ.get('REDIS_HOST') or os.environ.get('TAEY_REDIS_HOST') or '127.0.0.1'
        port = int(os.environ.get('REDIS_PORT') or os.environ.get('TAEY_REDIS_PORT') or '6379')
        client = redis.Redis(host=host, port=port, decode_responses=True, socket_timeout=2.0)
        return not bool(client.exists(f'taey:plan_active:{display}'))
    except Exception as exc:
        raise RuntimeError(
            f'Redis display-lock check failed before browser import for {display}: {exc}'
        ) from exc


def _gemini_requires_primary_display(argv: list[str]) -> bool:
    mode = _select_value(argv, 'mode')
    if mode in (None, 'default'):
        return True
    return mode in {'deep_think', 'deep_research'}


def _select_gemini_primary_display() -> str | None:
    from consultation_v2.platforms_runtime import (
        get_platform_displays,
        set_platform_display,
    )

    candidates = get_platform_displays('gemini')
    if not candidates:
        return None
    primary = os.environ.get('TAEY_GEMINI_PRIMARY_DISPLAY') or candidates[0]
    if primary and not primary.startswith(':'):
        primary = f':{primary}'
    if primary not in candidates:
        raise RuntimeError(
            f"TAEY_GEMINI_PRIMARY_DISPLAY={primary!r} is not configured for gemini; "
            f"candidates={list(candidates)!r}"
        )
    if not _display_lock_free(primary):
        raise RuntimeError(
            f"Gemini deep mode requires primary display {primary}, but that display is locked"
        )
    return set_platform_display('gemini', primary)


def _bind_display_env() -> None:
    from consultation_v2.platforms_runtime import display_environment, select_platform_display

    argv = sys.argv[1:]
    platform = _arg_value(argv, '--platform')
    if platform == 'gemini' and _gemini_requires_primary_display(argv):
        display = _select_gemini_primary_display()
        if display is None:
            display = select_platform_display(platform, is_available=_display_lock_free)
    elif platform:
        display = select_platform_display(platform, is_available=_display_lock_free)
    else:
        display = os.environ.get('DISPLAY', ':0')
    if not display:
        return
    scoped = display_environment(display)
    for key in ('DISPLAY', 'AT_SPI_BUS_ADDRESS', 'DBUS_SESSION_BUS_ADDRESS'):
        value = scoped.get(key)
        if value:
            os.environ[key] = value


_bind_display_env()

from consultation_v2.cli import main


if __name__ == '__main__':
    raise SystemExit(main())
