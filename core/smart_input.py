"""
Smart text entry with hybrid fallback cascade.

Bypasses xdotool's character-drop bug (delay /= 2 causes X server
to suppress doubled consonants) by using a priority cascade:

  1. AT-SPI EditableText.insert_text() - direct DOM injection
  2. Clipboard paste via xsel + Ctrl+V - always triggers full event chain
  3. xdotool type --delay 50 - last resort with safe delay

Based on Perplexity Deep Research audit (Feb 2026).
Does NOT modify frozen core/input.py.
"""

import subprocess
import time
import logging
from typing import Optional

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from core import input as inp

logger = logging.getLogger(__name__)

# Per-platform strategy overrides.
# 'atspi' = try AT-SPI first, 'clipboard' = skip AT-SPI, go straight to paste.
PLATFORM_STRATEGY = {
    'chatgpt': 'atspi',
    'claude': 'atspi',
    'gemini': 'atspi',
    'grok': 'atspi',
    'perplexity': 'atspi',
    'x_twitter': 'clipboard',   # DraftJS ignores AT-SPI DOM insertion
    'linkedin': 'clipboard',
}

# Minimum xdotool delay to avoid X server repeat suppression.
# xdotool halves this: 50ms -> 25ms gap between key-up and key-down.
XDOTOOL_SAFE_DELAY_MS = 50


def smart_type(text: str, platform: str = 'chatgpt',
               entry_element=None) -> dict:
    """Type text using the best available method.

    Args:
        text: Text to enter.
        platform: Platform name for strategy selection.
        entry_element: AT-SPI accessible element for the input field.
                       If None, AT-SPI insert is skipped.

    Returns:
        Dict with 'success', 'method' used, and optional 'error'.
    """
    strategy = PLATFORM_STRATEGY.get(platform, 'atspi')

    # Strategy 1: AT-SPI direct text injection
    if strategy == 'atspi' and entry_element is not None:
        result = _try_atspi_insert(entry_element, text)
        if result['success']:
            # Verify text landed
            if _verify_text(entry_element, text):
                return {**result, 'verified': True}
            else:
                logger.warning("AT-SPI insert succeeded but verification failed, falling back")

    # Strategy 2: Clipboard paste (xsel + Ctrl+V)
    result = _try_clipboard_paste(text)
    if result['success']:
        return result

    # Strategy 3: xdotool with safe delay (last resort)
    return _try_xdotool_safe(text)


def _try_atspi_insert(element, text: str) -> dict:
    """Insert text directly via AT-SPI EditableText interface.

    This bypasses keystroke simulation entirely - text arrives as
    a complete string, zero character drops, no clipboard side effects.
    """
    try:
        iface = element.get_editable_text_iface()
        if iface is None:
            return {'success': False, 'method': 'atspi', 'error': 'No EditableText interface'}

        # Get current text length to append at end
        text_iface = element.get_text_iface()
        position = text_iface.get_character_count() if text_iface else 0

        # insert_text takes (position, text, byte_length)
        ok = iface.insert_text(position, text, len(text.encode('utf-8')))
        if ok:
            logger.info(f"AT-SPI insert_text succeeded ({len(text)} chars at pos {position})")
            return {'success': True, 'method': 'atspi'}
        else:
            return {'success': False, 'method': 'atspi', 'error': 'insert_text returned False'}
    except Exception as e:
        logger.warning(f"AT-SPI insert_text failed: {e}")
        return {'success': False, 'method': 'atspi', 'error': str(e)}


def _verify_text(element, expected: str) -> bool:
    """Verify inserted text via AT-SPI Text interface (static methods).

    Critical because some contenteditable implementations silently
    ignore AT-SPI insertion (React state out of sync with DOM).
    Uses Atspi.Text static methods, not deprecated instance methods.
    """
    try:
        char_count = Atspi.Text.get_character_count(element)
        if char_count < len(expected):
            return False
        actual = Atspi.Text.get_text(element, 0, char_count)
        # Check if expected text is present (may have existing text before it)
        return expected in (actual or '')
    except Exception:
        return False


def _try_clipboard_paste(text: str) -> dict:
    """Write text to clipboard via xsel and paste with Ctrl+V.

    xsel does not fork to maintain ownership (unlike xclip),
    so subprocess.run() won't hang.
    """
    try:
        # Save current clipboard
        saved = _clipboard_read()

        # Write new text via xsel
        write_ok = _clipboard_write_xsel(text)
        if not write_ok:
            # Fallback to xclip pipe if xsel fails
            write_ok = _clipboard_write_xclip(text)

        if not write_ok:
            return {'success': False, 'method': 'clipboard', 'error': 'Failed to write to clipboard'}

        # Paste with Ctrl+V
        time.sleep(0.05)
        paste_ok = inp.press_key('ctrl+v', timeout=5)
        time.sleep(0.1)  # Let paste event propagate

        # Restore original clipboard (best effort)
        if saved:
            _clipboard_write_xsel(saved)

        if paste_ok:
            logger.info(f"Clipboard paste succeeded ({len(text)} chars)")
            return {'success': True, 'method': 'clipboard'}
        else:
            return {'success': False, 'method': 'clipboard', 'error': 'Ctrl+V press failed'}

    except Exception as e:
        logger.warning(f"Clipboard paste failed: {e}")
        return {'success': False, 'method': 'clipboard', 'error': str(e)}


def _try_xdotool_safe(text: str) -> dict:
    """Type via xdotool with delay >= 50ms to avoid repeat suppression.

    At delay=50, xdotool's delay/=2 gives 25ms between key-up and
    key-down, which clears most X server repeat detection thresholds.
    """
    ok = inp.type_text(text, delay_ms=XDOTOOL_SAFE_DELAY_MS)
    if ok:
        time.sleep(0.05)  # Post-type settle (race condition mitigation)
        logger.info(f"xdotool type succeeded ({len(text)} chars, delay={XDOTOOL_SAFE_DELAY_MS}ms)")
        return {'success': True, 'method': 'xdotool'}
    else:
        return {'success': False, 'method': 'xdotool', 'error': 'xdotool type failed'}


def _clipboard_write_xsel(text: str, timeout: float = 3.0) -> bool:
    """Write to clipboard via xsel (preferred - no fork hang)."""
    try:
        result = subprocess.run(
            ['xsel', '--clipboard', '--input'],
            input=text.encode('utf-8'),
            capture_output=True,
            timeout=timeout,
            env=inp._get_env(),
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError:
        return False


def _clipboard_write_xclip(text: str, timeout: float = 3.0) -> bool:
    """Write to clipboard via xclip -filter (fallback)."""
    try:
        proc = subprocess.Popen(
            ['xclip', '-selection', 'clipboard', '-filter'],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=inp._get_env(),
        )
        proc.communicate(input=text.encode('utf-8'), timeout=timeout)
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        proc.kill()
        return False
    except FileNotFoundError:
        return False


def _clipboard_read() -> Optional[str]:
    """Read current clipboard content (for save/restore)."""
    try:
        result = subprocess.run(
            ['xsel', '--clipboard', '--output'],
            capture_output=True, text=True,
            timeout=2.0,
            env=inp._get_env(),
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None


def find_entry_element(doc, platform: str = None):
    """Find the input/entry AT-SPI element in a platform document.

    Searches for elements with the 'editable' state and 'entry' role,
    or contenteditable elements that expose EditableText interface.

    Args:
        doc: AT-SPI document element from atspi.get_platform_document().
        platform: Platform name (unused currently, for future per-platform hints).

    Returns:
        AT-SPI accessible element, or None if not found.
    """
    if doc is None:
        return None

    def _search(obj, depth=0):
        if depth > 15:
            return None
        try:
            role = obj.get_role_name() or ''
            state_set = obj.get_state_set()

            # Look for editable entry elements
            is_editable = state_set.contains(Atspi.StateType.EDITABLE)
            is_entry = role == 'entry'
            is_focused = state_set.contains(Atspi.StateType.FOCUSED)

            if is_editable and (is_entry or is_focused):
                # Verify it has EditableText interface
                iface = obj.get_editable_text_iface()
                if iface is not None:
                    return obj

            # Recurse into children
            n = obj.get_child_count()
            for i in range(n):
                child = obj.get_child_at_index(i)
                if child:
                    result = _search(child, depth + 1)
                    if result:
                        return result
        except Exception:
            pass
        return None

    return _search(doc)
