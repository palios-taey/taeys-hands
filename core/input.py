"""Keyboard/mouse input via xdotool, clipboard paste via xsel+Ctrl+V."""

import os
import subprocess
import time
import logging

logger = logging.getLogger(__name__)

_ENV = None


def _get_env() -> dict:
    global _ENV
    if _ENV is None:
        _ENV = {**os.environ}
    return _ENV


def set_display(display: str):
    _get_env()['DISPLAY'] = display


def press_key(key: str, timeout: int = 10) -> bool:
    """Press a key combination via xdotool."""
    try:
        r = subprocess.run(
            ['xdotool', 'key', key],
            env=_get_env(), capture_output=True, timeout=timeout,
        )
        if r.returncode != 0:
            logger.warning(f"xdotool key {key} failed: {r.stderr.decode()}")
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"xdotool key {key} timed out")
        return False
    except Exception as e:
        logger.error(f"xdotool key {key} error: {e}")
        return False


def click_at(x: int, y: int, timeout: int = 5) -> bool:
    """Click at screen coordinates."""
    try:
        r = subprocess.run(
            ['xdotool', 'mousemove', str(x), str(y), 'click', '1'],
            env=_get_env(), capture_output=True, timeout=timeout,
        )
        if r.returncode != 0:
            logger.warning(f"Click at ({x},{y}) failed: {r.stderr.decode()}")
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"Click at ({x},{y}) timed out")
        return False
    except Exception as e:
        logger.error(f"Click at ({x},{y}) error: {e}")
        return False


def type_text(text: str, delay_ms: int = 5, timeout: int = 30) -> bool:
    """Type text via xdotool (use clipboard_paste for long text)."""
    actual_timeout = timeout + (len(text) * 0.1)
    try:
        r = subprocess.run(
            ['xdotool', 'type', '--clearmodifiers', '--delay', str(delay_ms), '--', text],
            env=_get_env(), capture_output=True, timeout=actual_timeout,
        )
        if r.returncode != 0:
            logger.warning(f"Type failed: {r.stderr.decode()}")
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"Typing timed out (len={len(text)})")
        return False
    except Exception as e:
        logger.error(f"Type error: {e}")
        return False


def focus_firefox(timeout: int = 5) -> bool:
    """Activate the Firefox window. Uses LAST window ID (mutter decorator workaround).
    Falls back to wmctrl for GNOME Shell where xdotool windowactivate fails."""
    try:
        r = subprocess.run(
            ['xdotool', 'search', '--name', 'Mozilla Firefox'],
            env=_get_env(), capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return False
        window_id = r.stdout.strip().split('\n')[-1]
        r2 = subprocess.run(
            ['xdotool', 'windowactivate', window_id],
            env=_get_env(), capture_output=True, text=True, timeout=timeout,
        )
        # xdotool windowactivate can fail on GNOME Shell (BadMatch) — try wmctrl
        if r2.returncode != 0 or 'BadMatch' in (r2.stderr or ''):
            r3 = subprocess.run(
                ['wmctrl', '-a', 'Mozilla Firefox'],
                env=_get_env(), capture_output=True, timeout=timeout,
            )
            if r3.returncode != 0:
                logger.warning("Both xdotool and wmctrl failed to focus Firefox")
                return False
            logger.info("Firefox focused via wmctrl fallback")
        time.sleep(0.3)
        return True
    except subprocess.TimeoutExpired:
        logger.error("Firefox focus timed out")
        return False
    except Exception as e:
        logger.error(f"Firefox focus error: {e}")
        return False


def switch_to_platform(platform: str) -> bool:
    """Switch to a platform tab via Alt+N shortcut."""
    from core.platforms import TAB_SHORTCUTS, URL_PATTERNS
    from core import atspi

    if platform not in URL_PATTERNS:
        return False
    if not focus_firefox():
        return False

    def _on_target() -> bool:
        firefox = atspi.find_firefox()
        if not firefox:
            return False
        doc = atspi.get_platform_document(firefox, platform)
        if not doc:
            return False
        try:
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi as _A
            return doc.get_state_set().contains(_A.StateType.SHOWING)
        except Exception:
            return True

    if _on_target():
        return True

    shortcut = TAB_SHORTCUTS.get(platform)
    if shortcut:
        press_key(shortcut)
        time.sleep(0.5)
        return True

    # No shortcut: Ctrl+Tab cycling
    for _ in range(8):
        press_key('ctrl+Tab')
        time.sleep(0.4)
        if _on_target():
            return True
    logger.warning(f"Could not switch to {platform}")
    return False


def press_key_split(key: str, gap_ms: int = 50, timeout: int = 10) -> bool:
    """Separate keydown/keyup (prevents key release leaking into dialogs)."""
    env = _get_env()
    try:
        r1 = subprocess.run(['xdotool', 'keydown', key], env=env, capture_output=True, timeout=timeout)
        time.sleep(gap_ms / 1000.0)
        r2 = subprocess.run(['xdotool', 'keyup', key], env=env, capture_output=True, timeout=timeout)
        return r1.returncode == 0 and r2.returncode == 0
    except Exception as e:
        logger.error(f"press_key_split {key} error: {e}")
        try:
            subprocess.run(['xdotool', 'keyup', key], env=env, timeout=3)
        except Exception:
            pass
        return False


def scroll_to_bottom():
    press_key('End')
    time.sleep(0.3)


def scroll_to_top():
    press_key('Home')
    time.sleep(0.5)


def scroll_page_down():
    press_key('Page_Down')
    time.sleep(0.3)


def scroll_page_up():
    press_key('Page_Up')
    time.sleep(0.3)


def clipboard_paste(text: str, timeout: float = 3.0) -> bool:
    """Write text to clipboard and paste with Ctrl+V. Primary text input method."""
    from core import clipboard
    lock = clipboard.acquire_clipboard_lock()
    try:
        clipboard.write_marker(text)
        time.sleep(0.05)
        ok = press_key('ctrl+v', timeout=5)
        time.sleep(0.1)
        return ok
    except RuntimeError as e:
        logger.error(f"Clipboard write failed: {e}")
        return False
    finally:
        clipboard.release_clipboard_lock(lock)
