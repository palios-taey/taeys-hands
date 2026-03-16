"""Clipboard operations via xsel (X11)."""

import fcntl
import os
import subprocess
import logging

logger = logging.getLogger(__name__)

_LOCK_DIR = os.path.expanduser('~/.taey')
os.makedirs(_LOCK_DIR, exist_ok=True)

_ENV = None


def _get_env() -> dict:
    global _ENV
    if _ENV is None:
        _ENV = {**os.environ}
    return _ENV


def set_display(display: str):
    _get_env()['DISPLAY'] = display


def _get_lock_path() -> str:
    display = os.environ.get('DISPLAY', ':0').replace(':', '_')
    return os.path.join(_LOCK_DIR, f'clipboard_{display}.lock')


def acquire_clipboard_lock():
    """Acquire exclusive clipboard lock. Caller MUST call release_clipboard_lock()."""
    fh = open(_get_lock_path(), 'w')
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fh


def release_clipboard_lock(fh):
    try:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
    except Exception:
        pass


def read() -> str | None:
    """Read clipboard text. Returns None on failure."""
    try:
        r = subprocess.run(
            ['xsel', '--clipboard', '--output'],
            capture_output=True, text=True, timeout=3.0, env=_get_env(),
        )
        return r.stdout if r.returncode == 0 else None
    except subprocess.TimeoutExpired:
        logger.error("Clipboard read timed out")
        return None
    except Exception as e:
        logger.error(f"Clipboard read failed: {e}")
        return None


def clear():
    """Clear clipboard."""
    try:
        r = subprocess.run(
            ['xsel', '--clipboard', '--input'],
            input=b'', capture_output=True, timeout=3.0, env=_get_env(),
        )
        if r.returncode != 0:
            raise RuntimeError(f"xsel clear failed: {r.stderr.decode()}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Clipboard clear failed: {e}") from e


def write_marker(marker: str):
    """Write text to clipboard (for paste or change detection)."""
    try:
        r = subprocess.run(
            ['xsel', '--clipboard', '--input'],
            input=marker.encode('utf-8'),
            capture_output=True, timeout=3.0, env=_get_env(),
        )
        if r.returncode != 0:
            raise RuntimeError(f"xsel write failed: {r.stderr.decode()}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Clipboard write failed: {e}") from e


def kill_stale_xsel():
    """Kill lingering xsel processes that stay resident as clipboard owner on Xvfb.

    On Xvfb, xsel --input stays running to hold clipboard ownership (no
    clipboard manager). This accumulates zombie-like processes. Safe to call
    periodically — only kills xsel processes, not other clipboard users.
    """
    try:
        subprocess.run(
            ['pkill', '-f', 'xsel.*--clipboard'],
            capture_output=True, timeout=3,
        )
    except Exception:
        pass
