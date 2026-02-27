"""
Smart text entry — no fallback cascade.

Two strategies, determined by element capabilities:
  1. AT-SPI EditableText.insert_text() - for elements with EditableText interface
  2. Clipboard paste via xsel + Ctrl+V - for all other elements

Each strategy either succeeds or returns failure. No silent cascading
to lower-quality methods (xdotool type has character-drop bugs).

Based on Perplexity Deep Research audits (Feb 2026).
Uses capability-based strategy detection - NO per-platform hardcoding.
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

# Minimum xdotool delay to avoid X server repeat suppression.
# xdotool halves this: 50ms -> 25ms gap between key-up and key-down.
XDOTOOL_SAFE_DELAY_MS = 50


def _detect_strategy(entry_element) -> str:
    """Detect input strategy by probing AT-SPI interfaces.

    No per-platform hardcoding. Checks what the element supports.
    """
    if entry_element is None:
        return 'clipboard'
    try:
        iface = entry_element.get_editable_text_iface()
        if iface is not None:
            return 'atspi'
    except Exception:
        pass
    return 'clipboard'


def smart_type(text: str, platform: str = 'chatgpt',
               entry_element=None) -> dict:
    """Type text using the best available method.

    Args:
        text: Text to enter.
        platform: Platform name (for logging only).
        entry_element: AT-SPI accessible element for the input field.
                       If None, AT-SPI insert is skipped.

    Returns:
        Dict with 'success', 'method' used, and optional 'error'.
    """
    strategy = _detect_strategy(entry_element)

    # AT-SPI direct text injection (when element supports EditableText)
    if strategy == 'atspi' and entry_element is not None:
        result = _try_atspi_insert(entry_element, text)
        if result['success']:
            if _verify_char_count(entry_element, text):
                return {**result, 'verified': True}
            else:
                logger.warning("AT-SPI insert succeeded but char count check failed, "
                               "trusting insert_text return value")
                return {**result, 'verified': False}
        # AT-SPI failed — return failure, no cascade
        logger.error(f"AT-SPI insert_text FAILED: {result.get('error', 'unknown')}")
        return result

    # Clipboard paste (when element doesn't support EditableText)
    result = _try_clipboard_paste(text)
    if result['success']:
        return result

    # Clipboard failed — return failure, no cascade to xdotool
    logger.error(f"Clipboard paste FAILED: {result.get('error', 'unknown')}")
    return result


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


def _verify_char_count(element, expected: str) -> bool:
    """Verify inserted text by character count only.

    Content comparison is unreliable on contenteditable divs because
    they may add formatting markup. Character count is sufficient to
    detect total insertion failure without triggering false negatives
    that cause the double-entry bug via retry.
    """
    try:
        char_count = Atspi.Text.get_character_count(element)
        return char_count >= len(expected)
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

    Searches for ANY element with the EDITABLE state that exposes
    an EditableText interface. This catches all contenteditable
    variants across platforms (entry role, section role, paragraph role, etc).

    Args:
        doc: AT-SPI document element from atspi.get_platform_document().
        platform: Platform name for logging.

    Returns:
        AT-SPI accessible element, or None if not found.
    """
    if doc is None:
        return None

    candidates = []

    def _search(obj, depth=0):
        if depth > 20:
            return
        try:
            role = obj.get_role_name() or ''
            state_set = obj.get_state_set()

            is_editable = state_set.contains(Atspi.StateType.EDITABLE)
            is_focusable = state_set.contains(Atspi.StateType.FOCUSABLE)

            if is_editable and is_focusable:
                iface = obj.get_editable_text_iface()
                if iface is not None:
                    is_entry = role == 'entry'
                    is_focused = state_set.contains(Atspi.StateType.FOCUSED)
                    # Priority: focused entry > entry > focused other > any editable
                    priority = (2 if is_entry else 0) + (1 if is_focused else 0)
                    candidates.append((priority, obj))
                    logger.debug(f"Entry candidate: role={role}, priority={priority}")

            # Recurse into children
            n = obj.get_child_count()
            for i in range(n):
                child = obj.get_child_at_index(i)
                if child:
                    _search(child, depth + 1)
        except Exception:
            pass

    _search(doc)

    if candidates:
        # Return highest priority candidate
        candidates.sort(key=lambda x: x[0], reverse=True)
        winner = candidates[0][1]
        logger.info(f"Found entry element: role={winner.get_role_name()}, "
                    f"priority={candidates[0][0]}, total_candidates={len(candidates)}")
        return winner

    return None
