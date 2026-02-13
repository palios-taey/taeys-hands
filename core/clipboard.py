"""
System clipboard operations via xclip.

Provides read/write/clear operations for the X11 clipboard,
used to extract AI responses from chat platforms.

FROZEN once working - do not modify without approval.
"""

import subprocess
import os
import logging

logger = logging.getLogger(__name__)

# Environment with DISPLAY set (populated at import time)
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
            ['xclip', '-selection', 'clipboard', '-o'],
            capture_output=True, text=True, env=_get_env(),
        )
        return result.stdout if result.returncode == 0 else None
    except Exception as e:
        logger.error(f"Clipboard read failed: {e}")
        return None


def clear():
    """Clear the system clipboard.

    Uses Popen pattern because subprocess.run with input= hangs on xclip.
    """
    try:
        proc = subprocess.Popen(
            ['xclip', '-selection', 'clipboard'],
            stdin=subprocess.PIPE, env=_get_env(),
        )
        proc.stdin.write(b'')
        proc.stdin.close()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    except Exception as e:
        logger.error(f"Clipboard clear failed: {e}")


def write_marker(marker: str):
    """Write a marker string to clipboard for change detection.

    Args:
        marker: Text to write as a detection marker.
    """
    try:
        proc = subprocess.Popen(
            ['xclip', '-selection', 'clipboard'],
            stdin=subprocess.PIPE, env=_get_env(),
        )
        proc.stdin.write(marker.encode())
        proc.stdin.close()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    except Exception as e:
        logger.error(f"Clipboard write marker failed: {e}")
