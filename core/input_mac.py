from __future__ import annotations
"""
macOS input operations via AppleScript and cliclick.

Drop-in replacement for core/input.py (Linux xdotool-based).
Uses AppleScript keystroke/key code via System Events for keyboard input,
and cliclick (if available) or AppleScript for mouse clicks.

Requires: macOS Accessibility permissions for the calling process.
"""

import subprocess
import time
import logging

logger = logging.getLogger(__name__)

# Map common key names to AppleScript key codes
# Reference: https://eastmanreference.com/complete-list-of-applescript-key-codes
_KEY_CODES = {
    'Return': 36, 'Enter': 36,
    'Escape': 53, 'Tab': 48,
    'Delete': 51, 'BackSpace': 51,
    'space': 49,
    'Home': 115, 'End': 119,
    'Page_Up': 116, 'Page_Down': 121,
    'Up': 126, 'Down': 125, 'Left': 123, 'Right': 124,
    'F1': 122, 'F2': 120, 'F3': 99, 'F4': 118,
    'F5': 96, 'F6': 97, 'F7': 98, 'F8': 100,
}

# Map modifier names to AppleScript modifier syntax
_MODIFIERS = {
    'ctrl': 'control down',
    'control': 'control down',
    'alt': 'option down',
    'option': 'option down',
    'shift': 'shift down',
    'super': 'command down',
    'cmd': 'command down',
    'command': 'command down',
    'meta': 'command down',
}

# Whether cliclick is available (checked lazily)
_cliclick_available = None


def _has_cliclick() -> bool:
    """Check if cliclick is installed."""
    global _cliclick_available
    if _cliclick_available is None:
        try:
            result = subprocess.run(['which', 'cliclick'],
                                    capture_output=True, timeout=3)
            _cliclick_available = result.returncode == 0
        except Exception:
            _cliclick_available = False
    return _cliclick_available


def _run_applescript(script: str, timeout: int = 10) -> tuple:
    """Run an AppleScript and return (success, stdout).

    Args:
        script: AppleScript source code.
        timeout: Max seconds to wait.

    Returns:
        (True, stdout) on success, (False, stderr) on failure.
    """
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning(f"AppleScript failed: {result.stderr.strip()}")
            return False, result.stderr.strip()
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error(f"AppleScript timed out after {timeout}s")
        return False, "timeout"
    except Exception as e:
        logger.error(f"AppleScript error: {e}")
        return False, str(e)


def set_display(display: str):
    """No-op on macOS (no X11 DISPLAY)."""
    pass


def press_key(key: str, timeout: int = 10) -> bool:
    """Press a key combination via AppleScript.

    Supports modifier combos like 'ctrl+l', 'alt+1', 'cmd+v', 'Return'.

    On macOS, browser tab shortcuts use Cmd+N (not Alt+N).
    This function auto-maps alt+N to cmd+N for Chrome compatibility.

    Args:
        key: Key name (e.g., 'Return', 'ctrl+l', 'alt+1').
        timeout: Maximum seconds to wait.

    Returns:
        True if key press succeeded.
    """
    parts = key.split('+')
    modifiers = []
    key_name = parts[-1]

    for part in parts[:-1]:
        mod = _MODIFIERS.get(part.lower())
        if mod:
            modifiers.append(mod)

    # macOS Chrome uses Cmd+N for tab switching, not Alt+N
    # Auto-remap alt+N → cmd+N for tab shortcuts
    if 'option down' in modifiers and len(key_name) == 1 and key_name.isdigit():
        modifiers = [m.replace('option down', 'command down') for m in modifiers]

    # Also remap ctrl+v → cmd+v, ctrl+a → cmd+a, ctrl+l → cmd+l, etc.
    if 'control down' in modifiers:
        modifiers = [m.replace('control down', 'command down') for m in modifiers]

    modifier_str = ', '.join(f'{m}' for m in modifiers)

    # Build AppleScript
    if key_name in _KEY_CODES:
        key_code = _KEY_CODES[key_name]
        if modifier_str:
            script = f'tell application "System Events" to key code {key_code} using {{{modifier_str}}}'
        else:
            script = f'tell application "System Events" to key code {key_code}'
    elif len(key_name) == 1:
        # Single character — use keystroke
        if modifier_str:
            script = f'tell application "System Events" to keystroke "{key_name}" using {{{modifier_str}}}'
        else:
            script = f'tell application "System Events" to keystroke "{key_name}"'
    else:
        logger.warning(f"Unknown key: {key_name}")
        return False

    ok, _ = _run_applescript(script, timeout=timeout)
    return ok


def click_at(x: int, y: int, timeout: int = 5) -> bool:
    """Click at specific screen coordinates.

    Uses cliclick if available, otherwise AppleScript.

    Args:
        x: X coordinate.
        y: Y coordinate.
        timeout: Maximum seconds to wait.

    Returns:
        True if click succeeded.
    """
    if _has_cliclick():
        try:
            result = subprocess.run(
                ['cliclick', f'c:{x},{y}'],
                capture_output=True, timeout=timeout,
            )
            if result.returncode != 0:
                logger.warning(f"cliclick at ({x}, {y}) failed: {result.stderr.decode()}")
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.error(f"cliclick at ({x}, {y}) timed out")
            return False
        except Exception as e:
            logger.error(f"cliclick at ({x}, {y}) error: {e}")
            return False
    else:
        # AppleScript mouse click fallback
        script = f'''
tell application "System Events"
    click at {{{x}, {y}}}
end tell
'''
        ok, _ = _run_applescript(script, timeout=timeout)
        return ok


def type_text(text: str, delay_ms: int = 5, timeout: int = 30) -> bool:
    """Type text via AppleScript keystroke.

    For short text only (URLs, etc). Long text should use clipboard_paste.

    Args:
        text: Text to type.
        delay_ms: Ignored on macOS (AppleScript handles timing).
        timeout: Base timeout in seconds.

    Returns:
        True if typing succeeded.
    """
    # Escape special characters for AppleScript string
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    actual_timeout = timeout + (len(text) * 0.1)
    script = f'tell application "System Events" to keystroke "{escaped}"'
    ok, _ = _run_applescript(script, timeout=int(actual_timeout))
    return ok


def focus_browser(timeout: int = 5) -> bool:
    """Activate/focus Chrome (or Safari) window.

    Uses `open -a` first (no automation permission needed), falls back
    to AppleScript `activate` if that fails.

    Returns:
        True if browser was activated.
    """
    # Primary: `open -a` works via LaunchServices — no TCC permission needed
    try:
        result = subprocess.run(
            ['open', '-a', 'Google Chrome'],
            capture_output=True, timeout=timeout,
        )
        if result.returncode == 0:
            time.sleep(0.3)
            return True
    except Exception:
        pass

    # Fallback: AppleScript activate (needs automation permission)
    script = 'tell application "Google Chrome" to activate'
    ok, _ = _run_applescript(script, timeout=timeout)
    if ok:
        time.sleep(0.3)
    return ok


# Alias for compatibility with tools that call focus_firefox
focus_firefox = focus_browser


def switch_to_platform(platform: str) -> bool:
    """Switch to a platform tab in Chrome.

    Strategy:
    1. Try JXA (Chrome scripting API) — finds tab by URL, most precise.
    2. Fallback: focus Chrome via `open -a` + Cmd+N keyboard shortcut.
       This works without Chrome automation permission (TCC).

    Args:
        platform: Platform name (e.g., 'claude').

    Returns:
        True if switch succeeded.
    """
    from core.platforms import URL_PATTERNS, TAB_SHORTCUTS

    if platform not in URL_PATTERNS:
        return False

    url_pattern = URL_PATTERNS[platform]

    # Try JXA first (most precise — switches by URL match)
    script = f'''
    (function() {{
        var chrome = Application("Google Chrome");
        chrome.activate();
        var wins = chrome.windows();
        for (var i = 0; i < wins.length; i++) {{
            var tabs = wins[i].tabs();
            for (var j = 0; j < tabs.length; j++) {{
                if (tabs[j].url().indexOf("{url_pattern}") !== -1) {{
                    wins[i].activeTabIndex = j + 1;
                    wins[i].index = 1;
                    return "true";
                }}
            }}
        }}
        return "false";
    }})();
    '''
    try:
        result = subprocess.run(
            ['osascript', '-l', 'JavaScript', '-e', script],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and 'true' in result.stdout.strip():
            time.sleep(0.5)
            return True
        stderr = result.stderr.strip()
        # If permission denied (-1743), fall through to keyboard shortcut
        if '-1743' not in stderr:
            logger.warning(f"JXA tab switch to {platform} failed: {stderr or result.stdout.strip()}")
    except subprocess.TimeoutExpired:
        logger.error(f"JXA tab switch to {platform} timed out")
    except Exception as e:
        logger.error(f"JXA tab switch to {platform} error: {e}")

    # Fallback 1: Use AXUIElement to find Chrome tab by title and click it.
    # This uses Accessibility permission (not Automation), which the MCP
    # process has. No tab order dependency.
    if _switch_tab_via_ax(url_pattern):
        return True

    # Fallback 2: Keyboard shortcut (requires correct tab order)
    shortcut = TAB_SHORTCUTS.get(platform)
    if not shortcut:
        logger.error(f"No tab shortcut defined for {platform}")
        return False

    logger.info(f"AX tab switch failed, using keyboard shortcut {shortcut} for {platform}")
    if not focus_browser():
        logger.error(f"Could not focus Chrome for {platform}")
        return False
    time.sleep(0.3)
    # press_key auto-remaps alt+N → cmd+N on macOS
    if press_key(shortcut):
        time.sleep(0.5)
        return True
    return False


def _switch_tab_via_ax(url_pattern: str) -> bool:
    """Switch Chrome tab using AXUIElement API (Accessibility permission).

    Searches Chrome's AX tree for tab elements whose title matches the
    platform. Chrome tabs show page titles (e.g., "ChatGPT", "Claude"),
    not URLs, so we match against both the URL domain and common tab
    title patterns.

    This works without Automation permission (JXA), only needs Accessibility.
    """
    try:
        from ApplicationServices import (
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
            AXUIElementPerformAction,
        )
        from AppKit import NSWorkspace
    except ImportError:
        return False

    # Find Chrome PID
    pid = None
    try:
        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            if app.localizedName() == 'Google Chrome':
                pid = app.processIdentifier()
                break
    except Exception:
        return False

    if not pid:
        return False

    # First activate Chrome
    focus_browser()

    ax_app = AXUIElementCreateApplication(pid)

    def _get_attr(el, attr):
        err, val = AXUIElementCopyAttributeValue(el, attr, None)
        return val if err == 0 else None

    # Build match patterns: URL domain + common page title keywords
    # Chrome tabs show "ChatGPT" not "chatgpt.com", so we need both
    _TAB_TITLE_PATTERNS = {
        'chatgpt.com': ['chatgpt'],
        'claude.ai': ['claude'],
        'gemini.google.com': ['gemini'],
        'grok.com': ['grok'],
        'perplexity.ai': ['perplexity'],
        'x.com': ['x.com', '/ x', 'home / x', 'twitter'],
        'linkedin.com': ['linkedin'],
    }
    match_terms = [url_pattern.lower()]
    for domain, terms in _TAB_TITLE_PATTERNS.items():
        if domain == url_pattern or url_pattern in domain:
            match_terms.extend(terms)
            break

    # Search for tab elements in the AX tree
    found_tabs = []

    def collect_tabs(el, depth=0, max_depth=6):
        """Collect all tab elements from Chrome's AX tree."""
        if depth > max_depth:
            return
        try:
            role = _get_attr(el, 'AXRole') or ''

            # Chrome tabs are AXRadioButton inside AXTabGroup
            if role in ('AXRadioButton', 'AXTab'):
                title = (_get_attr(el, 'AXTitle') or '').lower()
                if title:
                    found_tabs.append((el, title))
                return  # Don't recurse into tab elements

            children = _get_attr(el, 'AXChildren')
            if children:
                for child in children:
                    collect_tabs(child, depth + 1)
        except Exception:
            pass

    collect_tabs(ax_app)

    if found_tabs:
        logger.info(f"Found {len(found_tabs)} Chrome tabs: {[t for _, t in found_tabs]}")

    # Find matching tab
    for tab_el, title in found_tabs:
        if any(term in title for term in match_terms):
            try:
                err = AXUIElementPerformAction(tab_el, 'AXPress')
                if err == 0:
                    logger.info(f"Switched to tab via AX: '{title}' (pattern: {url_pattern})")
                    time.sleep(0.5)
                    return True
                else:
                    logger.warning(f"AXPress failed (err={err}) for tab '{title}'")
            except Exception as e:
                logger.debug(f"AX tab press failed: {e}")

    logger.info(f"AX tab switch: no matching tab for {match_terms} among {[t for _, t in found_tabs]}")
    return False


def scroll_to_bottom():
    """Scroll to bottom of page using Cmd+End (or End key)."""
    press_key('End')
    time.sleep(0.3)


def scroll_to_top():
    """Scroll to top of page using Cmd+Home (or Home key)."""
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
    """Write text to clipboard via pbcopy and paste with Cmd+V.

    Args:
        text: Text to paste.
        timeout: Clipboard write timeout in seconds.

    Returns:
        True if clipboard write and paste succeeded.
    """
    from core import clipboard_mac as clipboard
    try:
        clipboard.write_marker(text)
    except RuntimeError as e:
        logger.error(f"Clipboard write failed: {e}")
        return False

    time.sleep(0.05)
    # On macOS, Cmd+V is the paste shortcut. press_key auto-remaps ctrl+v → cmd+v.
    paste_ok = press_key('ctrl+v', timeout=5)
    time.sleep(0.1)
    return paste_ok
