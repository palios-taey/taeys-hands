"""
System input operations via xdotool.

Provides keyboard and mouse input for interacting with
Firefox through the X11 windowing system.
"""

import subprocess
import os
import time
import logging

logger = logging.getLogger(__name__)

_ENV = None


def _get_env() -> dict:
    """Get subprocess environment with DISPLAY set."""
    global _ENV
    if _ENV is None:
        _ENV = {**os.environ}
    return _ENV


def set_display(display: str):
    """Set the DISPLAY for input operations."""
    env = _get_env()
    env['DISPLAY'] = display


def press_key(key: str, timeout: int = 10) -> bool:
    """Press a key combination via xdotool.

    Args:
        key: Key name (e.g., 'Return', 'ctrl+l', 'alt+1').
        timeout: Maximum seconds to wait.

    Returns:
        True if key press succeeded.
    """
    try:
        result = subprocess.run(
            ['xdotool', 'key', key],
            env=_get_env(), capture_output=True, timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning(f"xdotool key {key} failed: {result.stderr.decode()}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"xdotool key {key} timed out after {timeout}s")
        return False
    except Exception as e:
        logger.error(f"xdotool key {key} error: {e}")
        return False


def click_at(x: int, y: int, timeout: int = 5) -> bool:
    """Click at specific screen coordinates.

    Args:
        x: X coordinate.
        y: Y coordinate.
        timeout: Maximum seconds to wait.

    Returns:
        True if click succeeded.
    """
    try:
        result = subprocess.run(
            ['xdotool', 'mousemove', str(x), str(y), 'click', '1'],
            env=_get_env(), capture_output=True, timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning(f"Click at ({x}, {y}) failed: {result.stderr.decode()}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"Click at ({x}, {y}) timed out")
        return False
    except Exception as e:
        logger.error(f"Click at ({x}, {y}) error: {e}")
        return False


def type_text(text: str, delay_ms: int = 5, timeout: int = 30) -> bool:
    """Type text via xdotool with per-character delay.

    For long text, timeout scales with length.

    Args:
        text: Text to type.
        delay_ms: Milliseconds between keystrokes.
        timeout: Base timeout in seconds (scales with text length).

    Returns:
        True if typing succeeded.
    """
    actual_timeout = timeout + (len(text) * 0.1)
    try:
        result = subprocess.run(
            ['xdotool', 'type', '--clearmodifiers', '--delay', str(delay_ms), '--', text],
            env=_get_env(), capture_output=True, timeout=actual_timeout,
        )
        if result.returncode != 0:
            logger.warning(f"Type failed: {result.stderr.decode()}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"Typing timed out (text length: {len(text)})")
        return False
    except Exception as e:
        logger.error(f"Type error: {e}")
        return False


def focus_firefox(timeout: int = 5) -> bool:
    """Activate/focus the Firefox window.

    Returns:
        True if Firefox was found and activated.
    """
    try:
        result = subprocess.run(
            ['xdotool', 'search', '--name', 'Mozilla Firefox'],
            env=_get_env(), capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False

        window_id = result.stdout.strip().split('\n')[0]
        subprocess.run(
            ['xdotool', 'windowactivate', window_id],
            env=_get_env(), capture_output=True, timeout=timeout,
        )
        time.sleep(0.3)
        return True
    except subprocess.TimeoutExpired:
        logger.error("Firefox focus timed out")
        return False
    except Exception as e:
        logger.error(f"Firefox focus error: {e}")
        return False


def switch_to_platform(platform: str) -> bool:
    """Switch to a platform tab via Alt+N shortcut.

    Alt+N is the primary and trusted mechanism (tab order is pre-configured).
    Verification uses AT-SPI document URL + SHOWING state, not frame titles
    (tabs show conversation titles like "New chat", not platform names).

    Args:
        platform: Platform name (e.g., 'claude').

    Returns:
        True if switch succeeded.
    """
    from core.platforms import TAB_SHORTCUTS, URL_PATTERNS
    from core import atspi

    if platform not in URL_PATTERNS:
        return False

    if not focus_firefox():
        return False

    def _on_target() -> bool:
        """Check if the platform's document is active (SHOWING) via URL match."""
        firefox = atspi.find_firefox()
        if not firefox:
            return False
        doc = atspi.get_platform_document(firefox, platform)
        if not doc:
            return False
        # SHOWING = active tab. Documents in background tabs exist
        # in the tree but lack SHOWING state.
        try:
            state_set = doc.get_state_set()
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi as _Atspi
            return state_set.contains(_Atspi.StateType.SHOWING)
        except Exception:
            # If state check fails, document exists — trust it
            return True

    # Already on the right tab?
    if _on_target():
        return True

    # Alt+N shortcut — primary mechanism, trusted
    shortcut = TAB_SHORTCUTS.get(platform)
    if shortcut:
        press_key(shortcut)
        time.sleep(0.5)
        # Trust Alt+N — return True without heavy verification.
        # Callers (inspect, extract) do their own document lookup.
        return True

    # No shortcut: Ctrl+Tab cycling with URL verification
    max_tabs = 8
    for _ in range(max_tabs):
        press_key('ctrl+Tab')
        time.sleep(0.4)
        if _on_target():
            return True

    logger.warning(f"Could not switch to {platform} via Ctrl+Tab cycling")
    return False


def scroll_to_bottom():
    """Scroll to bottom of page using End key."""
    press_key('End')
    time.sleep(0.3)


def scroll_to_top():
    """Scroll to top of page using Home key."""
    press_key('Home')
    time.sleep(0.5)


def scroll_page_down():
    """Scroll down one page."""
    press_key('Page_Down')
    time.sleep(0.3)


def scroll_page_up():
    """Scroll up one page."""
    press_key('Page_Up')
    time.sleep(0.3)


def clipboard_paste(text: str, timeout: float = 3.0) -> bool:
    """Write text to clipboard via xsel and paste with Ctrl+V.

    Uses xsel (no fork hang) + Ctrl+V for reliable text entry.
    This is the primary text input method - avoids xdotool character
    dropping on doubled letters (ss, ll, tt).

    Args:
        text: Text to paste.
        timeout: Clipboard write timeout in seconds.

    Returns:
        True if clipboard write and paste succeeded.
    """
    from core import clipboard
    try:
        clipboard.write_marker(text)
    except RuntimeError as e:
        logger.error(f"Clipboard write failed: {e}")
        return False

    time.sleep(0.05)
    paste_ok = press_key('ctrl+v', timeout=5)
    time.sleep(0.1)
    return paste_ok
