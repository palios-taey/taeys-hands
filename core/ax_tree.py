from __future__ import annotations
"""
macOS accessibility tree traversal and element extraction.

Drop-in replacement for core/tree.py (Linux AT-SPI-based).
Uses AXUIElement API via pyobjc for Chrome/Safari accessibility trees.

Provides the same interface: find_elements, filter_useful_elements,
find_copy_buttons, find_menu_items, detect_chrome_y, compute_structure_hash.
"""

import hashlib
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import macOS AX API
try:
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
    )
    HAS_AX = True
except ImportError:
    HAS_AX = False

# Purely decorative roles — filter when unnamed
_DECORATIVE_ROLES = {'image', 'static', 'separator', 'paragraph'}

# States that make an element interesting
IMPORTANT_STATE_NAMES = {'editable', 'checked', 'selected', 'pressed', 'focused'}

# Popup-like roles that bypass visibility filter
POPUP_ROLES = {
    'menu', 'menu item', 'menu bar', 'popup menu',
    'combo box', 'list box', 'list item',
    'dialog', 'alert', 'tool tip', 'window',
}

# Default chrome Y (toolbar area to skip)
BROWSER_CHROME_Y = 100


def find_elements(scope, max_depth: int = 25,
                  exclude_landmarks: Optional[List[str]] = None) -> List[Dict]:
    """Find all visible elements in a macOS AX tree.

    On macOS, `scope` can be:
    - A dict with 'pid' key (from ax_browser.find_browser/get_platform_document)
    - An AXUIElement directly

    Args:
        scope: Root scope (browser dict or AXUIElement).
        max_depth: Maximum traversal depth.
        exclude_landmarks: Not used on macOS (AT-SPI concept).

    Returns:
        List of element dicts with name, role, x, y, states.
    """
    if not HAS_AX:
        logger.error("macOS AX API not available")
        return []

    # If scope is a dict from our browser module, get the PID
    if isinstance(scope, dict):
        pid = scope.get('pid')
        if not pid:
            return []
        ax_root = AXUIElementCreateApplication(pid)
    else:
        ax_root = scope

    results = []

    def _get_attr(el, attr):
        err, val = AXUIElementCopyAttributeValue(el, attr, None)
        return val if err == 0 else None

    def traverse(el, depth=0):
        if depth > max_depth:
            return
        try:
            role = _get_attr(el, 'AXRole') or ''
            title = _get_attr(el, 'AXTitle') or ''
            desc = _get_attr(el, 'AXDescription') or ''
            subrole = _get_attr(el, 'AXSubrole') or ''
            enabled = _get_attr(el, 'AXEnabled')
            focused = _get_attr(el, 'AXFocused')

            pos = _get_attr(el, 'AXPosition')
            size = _get_attr(el, 'AXSize')

            x, y, w, h = 0, 0, 0, 0
            if pos:
                x = int(pos.x)
                y = int(pos.y)
            if size:
                w = int(size.width)
                h = int(size.height)

            center_x = x + w // 2
            center_y = y + h // 2

            mapped_role = _map_role(role, subrole)
            name = title or desc or ''

            if w > 0 and h > 0 and center_x >= 0 and center_y >= 0:
                element = {
                    'name': name,
                    'role': mapped_role,
                    'x': center_x,
                    'y': center_y,
                    'ax_ref': el,
                    'atspi_obj': el,  # Alias for tool compatibility
                }

                states = ['showing']  # Visible elements have non-zero extents
                if enabled is not False:
                    states.append('enabled')
                if focused:
                    states.append('focused')
                if role in ('AXTextArea', 'AXTextField', 'AXComboBox'):
                    states.append('editable')
                    states.append('focusable')
                selected = _get_attr(el, 'AXSelected')
                if selected:
                    states.append('selected')
                if role in ('AXCheckBox', 'AXRadioButton'):
                    val = _get_attr(el, 'AXValue')
                    if val:
                        states.append('checked')

                if states:
                    element['states'] = states
                if desc:
                    element['description'] = desc

                results.append(element)

            # Traverse children
            children = _get_attr(el, 'AXChildren')
            if children:
                for child in children:
                    traverse(child, depth + 1)
        except Exception as e:
            logger.debug(f"AX traversal error at depth {depth}: {e}")

    traverse(ax_root)
    return results


def _map_role(ax_role: str, subrole: str = '') -> str:
    """Map AX roles to AT-SPI-compatible role names."""
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
        'AXWebArea': 'document web',
        'AXOutline': 'tree',
        'AXOutlineRow': 'tree item',
        'AXDisclosureTriangle': 'toggle button',
        'AXSheet': 'dialog',
        'AXDialog': 'dialog',
    }
    return mapping.get(ax_role, ax_role.replace('AX', '').lower())


def detect_chrome_y(doc) -> int:
    """Detect browser chrome height from document info.

    On macOS, the chrome area (toolbar, bookmarks bar) is typically
    ~90-120px depending on screen resolution and DPI scaling.

    Args:
        doc: Document dict from ax_browser.get_platform_document().

    Returns:
        Y pixel threshold for chrome area.
    """
    # On macOS with Retina displays, Chrome toolbar is around 80-100px
    # This is a reasonable default; could be refined with AX inspection
    return BROWSER_CHROME_Y


def filter_useful_elements(elements: List[Dict], chrome_y: int = None) -> List[Dict]:
    """Filter elements to useful content (skip chrome, decorative noise).

    Same interface as tree.py's filter_useful_elements.
    """
    threshold = chrome_y if chrome_y is not None else BROWSER_CHROME_Y

    def is_useful(e):
        if e.get('y', 0) < threshold:
            return False

        role = e.get('role', '')
        name = e.get('name', '').strip()
        states = set(s.lower() for s in e.get('states', []))

        if role in POPUP_ROLES:
            return bool(name) or bool(states & IMPORTANT_STATE_NAMES)

        if 'showing' not in states:
            return False

        if role in _DECORATIVE_ROLES and not name and not (states & IMPORTANT_STATE_NAMES):
            return False

        return True

    filtered = [e for e in elements if is_useful(e)]
    filtered.sort(key=lambda x: x['y'])
    return filtered


def find_copy_buttons(elements: List[Dict]) -> List[Dict]:
    """Find copy buttons from element list, sorted by Y."""
    buttons = [
        e for e in elements
        if 'button' in e.get('role', '')
        and 'copy' in (e.get('name') or '').lower()
    ]
    buttons.sort(key=lambda b: b.get('y', 0))
    return buttons


def find_menu_items(browser=None, platform_doc=None) -> List[Dict]:
    """Find visible menu items in the AX tree.

    On macOS, menus render as AXMenu containers with AXMenuItem children.
    Chrome's web content menus appear in the AX tree when open.

    Args:
        browser: Browser dict from find_browser().
        platform_doc: Document dict (used to get PID for AX tree search).

    Returns:
        List of menu item dicts with name, role, x, y.
    """
    pid = None
    if platform_doc and isinstance(platform_doc, dict):
        pid = platform_doc.get('pid')
    elif browser and isinstance(browser, dict):
        pid = browser.get('pid')

    if not pid or not HAS_AX:
        return []

    # Search the AX tree for menu containers
    ax_app = AXUIElementCreateApplication(pid)

    def _get_attr(el, attr):
        err, val = AXUIElementCopyAttributeValue(el, attr, None)
        return val if err == 0 else None

    menu_items = []

    def search(el, depth=0, max_depth=15):
        if depth > max_depth or menu_items:
            return
        try:
            role = _get_attr(el, 'AXRole') or ''

            if role in ('AXMenu', 'AXList'):
                children = _get_attr(el, 'AXChildren') or []
                for child in children:
                    child_role = _get_attr(child, 'AXRole') or ''
                    if child_role in ('AXMenuItem', 'AXRadioButton', 'AXCheckBox'):
                        name = _get_attr(child, 'AXTitle') or _get_attr(child, 'AXDescription') or ''
                        if name:
                            pos = _get_attr(child, 'AXPosition')
                            size = _get_attr(child, 'AXSize')
                            if pos and size and size.width > 0 and size.height > 0:
                                menu_items.append({
                                    'name': name,
                                    'role': _map_role(child_role),
                                    'x': int(pos.x + size.width // 2),
                                    'y': int(pos.y + size.height // 2),
                                    'ax_ref': child,
                                    'atspi_obj': child,
                                })

            children = _get_attr(el, 'AXChildren') or []
            for child in children:
                search(child, depth + 1)
        except Exception as e:
            logger.debug(f"Menu search error at depth {depth}: {e}")

    search(ax_app)
    menu_items.sort(key=lambda x: x['y'])
    return menu_items


# Backward-compatible alias
find_dropdown_menus = find_menu_items


def compute_tree_hash(elements: List[Dict]) -> str:
    """Compute SHA256 hash of element role:name pairs."""
    pairs = sorted(f"{e.get('role', '')}:{e.get('name', '')}" for e in elements
                   if e.get('role') or e.get('name'))
    content = "|".join(pairs)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_structure_hash(elements: List[Dict], screen_height: int = 982,
                           grid_rows: int = 12) -> str:
    """Compute structure-only fingerprint of the UI layout.

    Same algorithm as tree.py — roles + Y-grid bands.
    """
    band_height = max(screen_height // grid_rows, 1)
    _CONTENT_ROLES = {'link', 'list item', 'heading', 'static', 'label',
                      'paragraph', 'text', 'section'}

    structure_pairs = []
    for e in elements:
        role = e.get('role', '')
        if not role or role in _CONTENT_ROLES:
            continue
        y = e.get('y', 0)
        band = y // band_height
        structure_pairs.append(f"{role}@{band}")

    structure_pairs.sort()
    content = "|".join(structure_pairs)
    return hashlib.sha256(content.encode()).hexdigest()[:16]
