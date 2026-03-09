from __future__ import annotations
"""
System clipboard operations via xsel.

Provides read/write/clear operations for the X11 clipboard,
used to extract AI responses and paste text into chat platforms.

Uses xsel (not xclip) to avoid fork-hang issues with subprocess.run().
"""

import fcntl
import subprocess
import os
import logging

logger = logging.getLogger(__name__)

# Per-DISPLAY clipboard lock to prevent race conditions between
# clipboard write and Ctrl+V paste (another process can overwrite
# clipboard in the gap). All clipboard-modifying operations acquire this.
_LOCK_DIR = os.path.expanduser('~/.taey')
os.makedirs(_LOCK_DIR, exist_ok=True)


def _get_lock_path() -> str:
    """Get DISPLAY-scoped lock file path."""
    display = os.environ.get('DISPLAY', ':0').replace(':', '_')
    return os.path.join(_LOCK_DIR, f'clipboard_{display}.lock')


def acquire_clipboard_lock():
    """Acquire exclusive clipboard lock. Returns lock file handle.

    Caller MUST call release_clipboard_lock(fh) when done.
    """
    fh = open(_get_lock_path(), 'w')
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fh


def release_clipboard_lock(fh):
    """Release clipboard lock."""
    try:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
    except Exception:
        pass

_ENV = None


def _get_env() -> dict:
    """Get subprocess environment with DISPLAY set."""
    global _ENV
    if _ENV is None:
        _ENV = {**os.environ}
    return _ENV


def set_display(display: str):
    """Set the DISPLAY for clipboard operations."""
    env = _get_env()
    env['DISPLAY'] = display


def read() -> str | None:
    """Read text from the system clipboard.

    Returns:
        Clipboard content as string, or None on failure.
    """
    try:
        result = subprocess.run(
            ['xsel', '--clipboard', '--output'],
            capture_output=True, text=True, timeout=3.0,
            env=_get_env(),
        )
        return result.stdout if result.returncode == 0 else None
    except subprocess.TimeoutExpired:
        logger.error("Clipboard read timed out")
        return None
    except Exception as e:
        logger.error(f"Clipboard read failed: {e}")
        return None


def clear():
    """Clear the system clipboard.

    Raises:
        RuntimeError: If clipboard cannot be cleared.
    """
    try:
        result = subprocess.run(
            ['xsel', '--clipboard', '--input'],
            input=b'',
            capture_output=True, timeout=3.0,
            env=_get_env(),
        )
        if result.returncode != 0:
            raise RuntimeError(f"xsel clear failed: {result.stderr.decode()}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Clipboard clear timed out after 3s")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Clipboard clear failed: {e}") from e


def write_marker(marker: str):
    """Write a marker string to clipboard for change detection.

    Args:
        marker: Text to write as a detection marker.

    Raises:
        RuntimeError: If marker cannot be written to clipboard.
    """
    try:
        result = subprocess.run(
            ['xsel', '--clipboard', '--input'],
            input=marker.encode('utf-8'),
            capture_output=True, timeout=3.0,
            env=_get_env(),
        )
        if result.returncode != 0:
            raise RuntimeError(f"xsel write failed: {result.stderr.decode()}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Clipboard write_marker timed out after 3s")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Clipboard write_marker failed: {e}") from e
