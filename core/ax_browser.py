from __future__ import annotations
"""
macOS browser discovery via AXUIElement API.

Drop-in replacement for core/atspi.py (Linux AT-SPI-based).
Finds Chrome/Safari and locates platform documents by URL pattern.

Requires: macOS Accessibility permissions for the calling process.
For tab switching without AX permissions, use input_mac.switch_to_platform()
which uses JXA (Chrome's scripting API).
"""

import logging
import re
import subprocess
import json

logger = logging.getLogger(__name__)

# Try to import macOS-specific modules
try:
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        AXUIElementCopyAttributeNames,
    )
    from AppKit import NSWorkspace
    HAS_AX = True
except ImportError:
    HAS_AX = False
    logger.warning("macOS AX API not available — pyobjc not installed")

from core.platforms import URL_PATTERNS


def _get_chrome_pid() -> int | None:
    """Get Chrome's process ID."""
    if not HAS_AX:
        return None
    try:
        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            if app.localizedName() == 'Google Chrome':
                return app.processIdentifier()
    except Exception as e:
        logger.error(f"Chrome PID lookup failed: {e}")
    return None


def _get_chrome_tabs_jxa() -> list:
    """Get Chrome tabs via JXA (requires Chrome automation permission).

    Returns list of {window, tab, title, url} dicts.
    Returns empty list if permission denied (-1743) or JXA unavailable.
    """
    script = '''
    var chrome = Application("Google Chrome");
    var result = [];
    var wins = chrome.windows();
    for (var i = 0; i < wins.length; i++) {
        var tabs = wins[i].tabs();
        for (var j = 0; j < tabs.length; j++) {
            result.push({window: i, tab: j, title: tabs[j].title(), url: tabs[j].url()});
        }
    }
    JSON.stringify(result);
    '''
    try:
        result = subprocess.run(
            ['osascript', '-l', 'JavaScript', '-e', script],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
        stderr = result.stderr.strip()
        if '-1743' in stderr:
            logger.info("JXA Chrome automation permission denied (-1743) — using fallback")
        else:
            logger.warning(f"JXA tab listing failed: {stderr}")
    except json.JSONDecodeError as e:
        logger.warning(f"JXA tab listing returned invalid JSON: {e}")
    except Exception as e:
        logger.error(f"JXA tab listing failed: {e}")
    return []


def _get_ax_tree(pid: int, max_depth: int = 20) -> list:
    """Traverse the AXUIElement tree for an application.

    Returns a flat list of element dicts with role, title, position, size.
    Each element also carries an 'ax_ref' key with the live AXUIElement.

    Args:
        pid: Process ID of the application.
        max_depth: Maximum traversal depth.

    Returns:
        List of element dicts.
    """
    if not HAS_AX:
        return []

    elements = []
    ax_app = AXUIElementCreateApplication(pid)

    def _get_attr(el, attr):
        err, val = AXUIElementCopyAttributeValue(el, attr, None)
        return val if err == 0 else None

    def _parse_point(val):
        if val is None:
            return 0, 0
        try:
            return int(val.x), int(val.y)
        except AttributeError:
            pass
        m = re.search(r'x:([\d.]+)\s+y:([\d.]+)', repr(val))
        return (int(float(m.group(1))), int(float(m.group(2)))) if m else (0, 0)

    def _parse_size(val):
        if val is None:
            return 0, 0
        try:
            return int(val.width), int(val.height)
        except AttributeError:
            pass
        m = re.search(r'w:([\d.]+)\s+h:([\d.]+)', repr(val))
        return (int(float(m.group(1))), int(float(m.group(2)))) if m else (0, 0)

    def traverse(el, depth=0):
        if depth > max_depth:
            return
        try:
            role = _get_attr(el, 'AXRole') or ''
            title = _get_attr(el, 'AXTitle') or ''
            desc = _get_attr(el, 'AXDescription') or ''
            value = _get_attr(el, 'AXValue')
            role_desc = _get_attr(el, 'AXRoleDescription') or ''
            subrole = _get_attr(el, 'AXSubrole') or ''
            enabled = _get_attr(el, 'AXEnabled')
            focused = _get_attr(el, 'AXFocused')

            # Get position and size
            pos = _get_attr(el, 'AXPosition')
            size = _get_attr(el, 'AXSize')

            x, y = _parse_point(pos)
            w, h = _parse_size(size)

            # Compute center coordinates (matching AT-SPI convention)
            center_x = x + w // 2
            center_y = y + h // 2

            # Map AX roles to AT-SPI-like role names for compatibility
            mapped_role = _map_ax_role(role, subrole)

            name = title or desc or ''

            element = {
                'name': name,
                'role': mapped_role,
                'x': center_x,
                'y': center_y,
                'width': w,
                'height': h,
                'ax_ref': el,
                'ax_role': role,  # Original AX role for debugging
            }

            # Build states list (matching AT-SPI convention)
            states = []
            if w > 0 and h > 0:
                states.append('showing')
            if enabled is not False:
                states.append('enabled')
            if focused:
                states.append('focused')

            # Check for editable
            if role in ('AXTextArea', 'AXTextField', 'AXComboBox'):
                states.append('editable')
                states.append('focusable')

            # Check for selected/checked
            selected = _get_attr(el, 'AXSelected')
            if selected:
                states.append('selected')
            checked = _get_attr(el, 'AXValue')
            if role in ('AXCheckBox', 'AXRadioButton') and checked:
                states.append('checked')

            if states:
                element['states'] = states

            if desc:
                element['description'] = desc

            if w > 0 and h > 0:
                elements.append(element)

            # Traverse children
            children = _get_attr(el, 'AXChildren')
            if children:
                for child in children:
                    traverse(child, depth + 1)
        except Exception as e:
            logger.debug(f"AX traversal error at depth {depth}: {e}")

    traverse(ax_app)
    return elements


def _map_ax_role(ax_role: str, subrole: str = '') -> str:
    """Map macOS AX role names to AT-SPI-like role names.

    This enables tools to work with consistent role names across platforms.
    """
    mapping = {
        'AXApplication': 'application',
        'AXWindow': 'frame',
        'AXButton': 'push button',
        'AXCheckBox': 'check box',
        'AXRadioButton': 'radio button',
        'AXTextField': 'entry',
        'AXTextArea': 'entry',
        'AXComboBox': 'combo box',
        'AXList': 'list',
        'AXMenu': 'menu',
        'AXMenuBar': 'menu bar',
        'AXMenuItem': 'menu item',
        'AXMenuButton': 'push button',
        'AXPopUpButton': 'push button',
        'AXStaticText': 'static',
        'AXHeading': 'heading',
        'AXLink': 'link',
        'AXImage': 'image',
        'AXGroup': 'section',
        'AXToolbar': 'tool bar',
        'AXTabGroup': 'page tab list',
        'AXTab': 'page tab',
        'AXScrollArea': 'scroll pane',
        'AXScrollBar': 'scroll bar',
        'AXTable': 'table',
        'AXRow': 'table row',
        'AXCell': 'table cell',
        'AXColumn': 'table column',
        'AXSlider': 'slider',
        'AXProgressIndicator': 'progress bar',
        'AXSplitter': 'separator',
        'AXWebArea': 'document web',
        'AXOutline': 'tree',
        'AXOutlineRow': 'tree item',
        'AXDisclosureTriangle': 'toggle button',
        'AXSheet': 'dialog',
        'AXDialog': 'dialog',
    }
    return mapping.get(ax_role, ax_role.replace('AX', '').lower())


# =========================================================================
# Public API (matching core/atspi.py interface)
# =========================================================================

def find_browser():
    """Find Chrome application on macOS.

    Returns a dict with browser info, or None if not found.
    On Linux this returns an AT-SPI accessible; on macOS we return
    a dict with 'pid' and 'name' for downstream use.
    """
    pid = _get_chrome_pid()
    if pid:
        return {'pid': pid, 'name': 'Google Chrome', 'type': 'chrome'}
    logger.warning("Google Chrome not found running on macOS")
    return None


# Alias for tools that call find_firefox
find_firefox = find_browser


def get_document_url(doc) -> str | None:
    """Get the URL of a platform document (tab).

    On macOS, `doc` is a dict from get_platform_document
    containing the tab URL.
    """
    if isinstance(doc, dict):
        return doc.get('url')
    return None


def detect_platform_from_url(url: str) -> str | None:
    """Detect which platform a URL belongs to."""
    if not url:
        return None
    url_lower = url.lower()
    for platform, domain in URL_PATTERNS.items():
        if domain in url_lower:
            return platform
    return None


def get_platform_document(browser, platform: str):
    """Find the document (tab) for a specific platform.

    Strategy:
    1. Try JXA to find the tab by URL pattern (most precise).
    2. Fallback: return a synthetic document when JXA is unavailable
       (permission denied). Tab switching uses keyboard shortcuts
       instead (handled by input_mac.switch_to_platform).

    Args:
        browser: Browser dict from find_browser().
        platform: Platform name (e.g., 'claude').

    Returns:
        Tab info dict, or None if not found.
    """
    if not browser:
        return None

    url_pattern = URL_PATTERNS.get(platform)
    if not url_pattern:
        return None

    tabs = _get_chrome_tabs_jxa()
    for tab in tabs:
        if url_pattern in (tab.get('url') or '').lower():
            return {
                'url': tab['url'],
                'title': tab.get('title', ''),
                'window': tab.get('window', 0),
                'tab': tab.get('tab', 0),
                'platform': platform,
                'pid': browser.get('pid'),
            }

    # JXA returned no matching tabs — either permission denied or tab
    # doesn't exist. Return a synthetic document so downstream tools
    # (inspect, click, etc.) can still work via AX tree + keyboard shortcuts.
    if not tabs:
        logger.info(
            f"JXA unavailable for {platform} — returning synthetic document "
            f"(tab switching will use keyboard shortcut)"
        )
        return {
            'url': f'https://{url_pattern}/',
            'title': platform,
            'window': 0,
            'tab': 0,
            'platform': platform,
            'pid': browser.get('pid'),
            'synthetic': True,
        }
    return None


def get_platform_ax_tree(browser, max_depth: int = 20) -> list:
    """Get the full AX element tree for the browser.

    Requires AX accessibility permissions. Returns flat list of elements.

    Args:
        browser: Browser dict from find_browser().
        max_depth: Maximum traversal depth.

    Returns:
        List of element dicts with name, role, x, y, states.
    """
    pid = browser.get('pid') if browser else None
    if not pid:
        return []
    return _get_ax_tree(pid, max_depth=max_depth)


def is_file_dialog_open(browser) -> bool:
    """Check if a file chooser dialog is open.

    On macOS, checks for AXSheet or open/save panel.
    Falls back to JXA window count check.
    """
    if not browser:
        return False

    # JXA approach: check if Chrome has a sheet/dialog
    script = '''
    var chrome = Application("Google Chrome");
    var wins = chrome.windows();
    // Chrome shows file dialogs as separate windows
    // If there are more windows than expected, likely a dialog
    wins.length;
    '''
    try:
        result = subprocess.run(
            ['osascript', '-l', 'JavaScript', '-e', script],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            # A simple heuristic — could be improved with AX check
            pass
    except Exception:
        pass

    # AX approach (requires permissions)
    pid = browser.get('pid')
    if pid and HAS_AX:
        try:
            ax_app = AXUIElementCreateApplication(pid)
            err, windows = AXUIElementCopyAttributeValue(ax_app, 'AXWindows', None)
            if err == 0 and windows:
                for win in windows:
                    err, role = AXUIElementCopyAttributeValue(win, 'AXRole', None)
                    err2, subrole = AXUIElementCopyAttributeValue(win, 'AXSubrole', None)
                    if subrole in ('AXDialog', 'AXSheet', 'AXStandardWindow'):
                        err3, title = AXUIElementCopyAttributeValue(win, 'AXTitle', None)
                        if title and any(kw in (title or '').lower()
                                         for kw in ['open', 'upload', 'file', 'save']):
                            return True
        except Exception as e:
            logger.debug(f"AX file dialog check failed: {e}")

    return False
