"""
macOS clipboard operations via pbcopy/pbpaste.

Drop-in replacement for core/clipboard.py (Linux xsel-based).
Same interface: read(), clear(), write_marker().
"""

import subprocess
import logging

logger = logging.getLogger(__name__)


def set_display(display: str):
    """No-op on macOS (no X11 DISPLAY needed)."""
    pass


def read() -> str | None:
    """Read text from the macOS clipboard.

    Returns:
        Clipboard content as string, or None on failure.
    """
    try:
        result = subprocess.run(
            ['pbpaste'],
            capture_output=True, text=True, timeout=3.0,
        )
        return result.stdout if result.returncode == 0 else None
    except subprocess.TimeoutExpired:
        logger.error("Clipboard read timed out")
        return None
    except Exception as e:
        logger.error(f"Clipboard read failed: {e}")
        return None


def clear():
    """Clear the macOS clipboard.

    Raises:
        RuntimeError: If clipboard cannot be cleared.
    """
    try:
        result = subprocess.run(
            ['pbcopy'],
            input=b'',
            capture_output=True, timeout=3.0,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pbcopy clear failed: {result.stderr.decode()}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Clipboard clear timed out after 3s")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Clipboard clear failed: {e}") from e


def write_marker(marker: str):
    """Write a marker string to clipboard.

    Args:
        marker: Text to write.

    Raises:
        RuntimeError: If write fails.
    """
    try:
        result = subprocess.run(
            ['pbcopy'],
            input=marker.encode('utf-8'),
            capture_output=True, timeout=3.0,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pbcopy write failed: {result.stderr.decode()}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Clipboard write_marker timed out after 3s")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Clipboard write_marker failed: {e}") from e
