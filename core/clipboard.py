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
    """Read clipboard text. Tries xsel first, falls back to xclip."""
    env = _get_env()
    # Try xsel first
    try:
        r = subprocess.run(
            ['xsel', '--clipboard', '--output'],
            capture_output=True, text=True, timeout=3.0, env=env,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except subprocess.TimeoutExpired:
        logger.debug("xsel read timed out, trying xclip")
    except Exception:
        pass
    # Fallback to xclip
    try:
        r = subprocess.run(
            ['xclip', '-selection', 'clipboard', '-o'],
            capture_output=True, text=True, timeout=3.0, env=env,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except Exception:
        pass
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
