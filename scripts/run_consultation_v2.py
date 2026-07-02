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


def _bind_display_env() -> None:
    from consultation_v2.platforms_runtime import display_environment, select_platform_display

    platform = _arg_value(sys.argv[1:], '--platform')
    if platform:
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
