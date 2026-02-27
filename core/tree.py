"""
AT-SPI tree traversal and element extraction.

Provides BFS/DFS traversal of the accessibility tree, extracting
visible elements with their names, roles, states, and coordinates.

FROZEN once working - do not modify without approval.
"""

import hashlib
import logging
from typing import Dict, List, Optional

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

logger = logging.getLogger(__name__)

# States worth reporting on elements
IMPORTANT_STATES = [
    Atspi.StateType.SELECTED,
    Atspi.StateType.CHECKED,
    Atspi.StateType.PRESSED,
    Atspi.StateType.FOCUSED,
    Atspi.StateType.EXPANDED,
    Atspi.StateType.EDITABLE,
    Atspi.StateType.FOCUSABLE,
    Atspi.StateType.ENABLED,
    Atspi.StateType.MULTI_LINE,
]

# Roles that bypass SHOWING filter (transient popups)
POPUP_ROLES = {
    'menu', 'menu item', 'menu bar', 'popup menu',
    'combo box', 'list box', 'list item',
    'dialog', 'alert', 'tool tip', 'window',
}

# Noise roles to filter out (containers, decorations)
NOISE_ROLES = {
    'section', 'panel', 'separator', 'image', 'static', 'paragraph',
    'landmark', 'scroll pane', 'internal frame', 'tool bar', 'page tab list',
}

# Actionable roles to keep even without special states
ACTIONABLE_ROLES = {
    'push button', 'toggle button', 'radio button', 'entry',
    'link', 'combo box', 'menu item', 'menu', 'check menu item',
}

# States that make an element interesting regardless of role
IMPORTANT_STATE_NAMES = {'editable', 'checked', 'selected', 'pressed', 'focused'}

# Y threshold to skip Firefox chrome area (toolbar, tabs)
# Default is conservative (100px) - overridden at runtime by detect_chrome_y()
FIREFOX_CHROME_Y = 100


def find_elements(scope, max_depth: int = 25,
                  exclude_landmarks: Optional[List[str]] = None) -> List[Dict]:
    """Find all visible elements in an AT-SPI subtree.

    Uses visibility state filtering (SHOWING, VISIBLE) to return
    only active tab content. Popup roles bypass visibility filter.

    Args:
        scope: Root AT-SPI element to search from.
        max_depth: Maximum traversal depth.
        exclude_landmarks: Landmark names whose subtrees to skip.

    Returns:
        List of element dicts with name, role, x, y, and optional
        states and description fields.
    """
    results = []
    exclude_lower = [n.lower() for n in (exclude_landmarks or [])]

    def traverse(obj, depth=0):
        if depth > max_depth:
            return
        try:
            name = obj.get_name() or ''
            role = obj.get_role_name() or ''
            state_set = obj.get_state_set()

            # Skip excluded landmarks and their subtrees
            if role == 'landmark' and name and exclude_lower:
                if name.lower() in exclude_lower:
                    return

            has_showing = state_set.contains(Atspi.StateType.SHOWING)
            has_visible = state_set.contains(Atspi.StateType.VISIBLE)
            is_popup = role in POPUP_ROLES

            comp = obj.get_component_iface()
            if comp and (has_showing or has_visible or is_popup):
                rect = comp.get_extents(Atspi.CoordType.SCREEN)
                if rect and rect.x >= 0 and rect.y >= 0:
                    center_x = rect.x + (rect.width // 2 if rect.width else 0)
                    center_y = rect.y + (rect.height // 2 if rect.height else 0)
                    element = {
                        'name': name,
                        'role': role,
                        'x': center_x,
                        'y': center_y,
                        'atspi_obj': obj,
                    }

                    states = []
                    for state in IMPORTANT_STATES:
                        if state_set.contains(state):
                            states.append(state.value_nick)
                    if states:
                        element['states'] = states

                    desc = obj.get_description()
                    if desc:
                        element['description'] = desc

                    results.append(element)

            # Always traverse children - parents may hide but children show
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child:
                    traverse(child, depth + 1)
        except Exception as e:
            logger.debug(f"AT-SPI traversal error at depth {depth}: {e}")

    traverse(scope)
    return results


def detect_chrome_y(doc) -> int:
    """Detect Firefox chrome height from document element position.

    The document's top Y coordinate marks where content starts,
    which varies by screen resolution and Firefox configuration
    (bookmarks bar, etc.).

    Args:
        doc: AT-SPI document web element.

    Returns:
        Y pixel threshold for chrome area filtering.
    """
    try:
        comp = doc.get_component_iface()
        if comp:
            rect = comp.get_extents(Atspi.CoordType.SCREEN)
            if rect and rect.y > 0:
                return rect.y
    except Exception as e:
        logger.debug(f"Chrome Y detection failed: {e}")
    return FIREFOX_CHROME_Y


def filter_useful_elements(elements: List[Dict], chrome_y: int = None) -> List[Dict]:
    """Filter elements to only useful, actionable ones.

    Removes noise (unnamed sections, panels, Firefox chrome area)
    and keeps actionable elements, named items, and stateful elements.

    Args:
        elements: Raw element list from find_elements.
        chrome_y: Y threshold for chrome area. Auto-detected if None.

    Returns:
        Filtered and Y-sorted element list.
    """
    threshold = chrome_y if chrome_y is not None else FIREFOX_CHROME_Y

    def is_useful(e):
        if e.get('y', 0) < threshold:
            return False

        role = e.get('role', '')
        name = e.get('name', '').strip()
        states = set(s.lower() for s in e.get('states', []))

        if states & IMPORTANT_STATE_NAMES:
            return True
        if name and role in ACTIONABLE_ROLES:
            return True
        if role in NOISE_ROLES:
            return False
        return bool(name)

    filtered = [e for e in elements if is_useful(e)]
    filtered.sort(key=lambda x: x['y'])
    return filtered


def find_copy_buttons(elements: List[Dict]) -> List[Dict]:
    """Find copy buttons from a list of elements, sorted by Y (newest last).

    Args:
        elements: Element list from find_elements.

    Returns:
        Copy button elements sorted by Y position (ascending).
    """
    buttons = [
        e for e in elements
        if 'button' in e.get('role', '')
        and 'copy' in (e.get('name') or '').lower()
    ]
    buttons.sort(key=lambda b: b.get('y', 0))
    return buttons


def find_dropdown_menus(firefox, platform_doc=None) -> List[Dict]:
    """Find dropdown menu items in the AT-SPI tree.

    Searches from Firefox root for active menu elements (dropdowns
    render OUTSIDE the document element as separate menus).

    Filters out Firefox's permanent menus (context menu, menu bar)
    and skips sidebar/navigation landmark subtrees to avoid returning
    permanent sidebar items instead of transient dropdown items.

    Args:
        firefox: Firefox AT-SPI accessible.
        platform_doc: Platform document element (fallback search scope).

    Returns:
        List of dropdown item dicts with name, role, x, y.
    """
    # Firefox context menu items (page context + text edit context)
    FIREFOX_CONTEXT_ITEMS = frozenset({
        'Back', 'Forward', 'Reload', 'Edit Bookmark…', 'Save Page As…',
        'Select All', 'Take Screenshot', 'View Page Source',
        'Inspect Accessibility Properties', 'Inspect',
        'Undo', 'Redo', 'Cut', 'Copy', 'Paste', 'Delete',
        'Check Spelling', 'Languages', 'Reopen Closed Tab',
    })

    # Firefox menu bar items to skip
    FIREFOX_MENUBAR_ITEMS = frozenset({
        'File', 'Edit', 'View', 'History', 'Bookmarks', 'Tools', 'Help',
    })

    # Keywords in landmark names that indicate sidebar/navigation (skip these subtrees)
    _SIDEBAR_KEYWORDS = ('sidebar', 'navigation', 'chat history',
                         'conversation history', 'footer')

    dropdown_roles = ('menu item', 'radio menu item', 'check menu item', 'list item', 'option')

    def search_menus(obj, depth=0, max_depth=15):
        items = []
        if depth > max_depth:
            return items
        try:
            role = obj.get_role_name()
            name = obj.get_name() or ''

            # Skip sidebar/navigation landmark subtrees - these contain
            # permanent menus, not the transient dropdown we're looking for
            if role == 'landmark' and name:
                name_lower = name.lower()
                if any(kw in name_lower for kw in _SIDEBAR_KEYWORDS):
                    return items

            # Skip menu bar container (Firefox chrome)
            if role == 'menu bar':
                return items

            if role == 'menu':
                for i in range(min(obj.get_child_count(), 20)):
                    child = obj.get_child_at_index(i)
                    if not child:
                        continue
                    child_role = child.get_role_name()
                    child_name = child.get_name() or ''
                    if child_name and child_role in dropdown_roles:
                        try:
                            comp = child.get_component_iface()
                            if comp:
                                ext = comp.get_extents(Atspi.CoordType.SCREEN)
                                if ext.width > 0 and ext.height > 0:
                                    items.append({
                                        'name': child_name,
                                        'role': child_role,
                                        'x': ext.x + ext.width // 2,
                                        'y': ext.y + ext.height // 2,
                                        'atspi_obj': child,
                                    })
                        except Exception as e:
                            logger.debug(f"Menu item extent error: {e}")
                if items:
                    names = {item['name'] for item in items}
                    # Skip Firefox context menus and menu bar menus
                    if names & FIREFOX_CONTEXT_ITEMS or names <= FIREFOX_MENUBAR_ITEMS:
                        items = []
                    else:
                        return items

            for i in range(min(obj.get_child_count(), 30)):
                child = obj.get_child_at_index(i)
                if child:
                    result = search_menus(child, depth + 1, max_depth)
                    if result:
                        return result
        except Exception as e:
            logger.debug(f"Dropdown menu search error at depth {depth}: {e}")
        return items

    # Search platform_doc FIRST to avoid cross-tab contamination.
    # Dropdowns from other tabs (e.g. Grok's model selector) appear in the
    # Firefox root tree. By searching the active platform's document first,
    # we find the correct dropdown menu for the current tab.
    if platform_doc:
        items = search_menus(platform_doc)
        if items:
            items.sort(key=lambda x: x['y'])
            return items

    if firefox:
        items = search_menus(firefox)
        if items:
            items.sort(key=lambda x: x['y'])
            return items

    # Final fallback: search document for menu items without a menu container.
    # Some platforms render dropdown items directly in the document without
    # wrapping them in a menu-role element. Only uses narrow roles
    # (no list item/option/push button - those match page content).
    if platform_doc:
        _fallback_roles = ('menu item', 'radio menu item', 'check menu item')
        all_elements = find_elements(
            platform_doc,
            exclude_landmarks=['Chat history', 'Sidebar', 'Conversation history'],
        )
        items = [e for e in all_elements
                 if e.get('name') and e.get('role', '') in _fallback_roles]
        if items:
            items.sort(key=lambda x: x['y'])
            return items

    return []


def compute_tree_hash(elements: List[Dict]) -> str:
    """Compute SHA256 hash of element role:name pairs for state comparison.

    Used to detect whether an action actually changed the UI.
    Same algorithm as taey-ed-v7's compute_tree_hash for consistency.

    Args:
        elements: Element list from find_elements.

    Returns:
        16-character hex digest (first 64 bits of SHA256).
    """
    pairs = sorted(f"{e.get('role', '')}:{e.get('name', '')}" for e in elements
                   if e.get('role') or e.get('name'))
    content = "|".join(pairs)
    return hashlib.sha256(content.encode()).hexdigest()[:16]
