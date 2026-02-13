"""
AT-SPI tree traversal and element extraction.

Provides BFS/DFS traversal of the accessibility tree, extracting
visible elements with their names, roles, states, and coordinates.

FROZEN once working - do not modify without approval.
"""

import hashlib
from typing import Dict, List, Optional

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

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
FIREFOX_CHROME_Y = 147


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
        except Exception:
            pass

    traverse(scope)
    return results


def filter_useful_elements(elements: List[Dict]) -> List[Dict]:
    """Filter elements to only useful, actionable ones.

    Removes noise (unnamed sections, panels, Firefox chrome area)
    and keeps actionable elements, named items, and stateful elements.

    Args:
        elements: Raw element list from find_elements.

    Returns:
        Filtered and Y-sorted element list.
    """
    def is_useful(e):
        if e.get('y', 0) < FIREFOX_CHROME_Y:
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

    Filters out Firefox's permanent context menu items.

    Args:
        firefox: Firefox AT-SPI accessible.
        platform_doc: Platform document element (fallback search scope).

    Returns:
        List of dropdown item dicts with name, role, x, y.
    """
    FIREFOX_CONTEXT_ITEMS = frozenset({
        'Back', 'Forward', 'Reload', 'Edit Bookmark…', 'Save Page As…',
        'Select All', 'Take Screenshot', 'View Page Source',
        'Inspect Accessibility Properties', 'Inspect',
    })

    dropdown_roles = ('menu item', 'radio menu item', 'list item', 'option')

    def search_menus(obj, depth=0, max_depth=15):
        items = []
        if depth > max_depth:
            return items
        try:
            role = obj.get_role_name()
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
                                    })
                        except Exception:
                            pass
                if items:
                    names = {item['name'] for item in items}
                    if names & FIREFOX_CONTEXT_ITEMS:
                        items = []
                    else:
                        return items

            for i in range(min(obj.get_child_count(), 30)):
                child = obj.get_child_at_index(i)
                if child:
                    result = search_menus(child, depth + 1, max_depth)
                    if result:
                        return result
        except Exception:
            pass
        return items

    if firefox:
        items = search_menus(firefox)
        if items:
            items.sort(key=lambda x: x['y'])
            return items

    # Fallback: search from document for upload-related buttons
    if platform_doc:
        all_elements = find_elements(
            platform_doc,
            exclude_landmarks=['Chat history', 'Sidebar', 'Conversation history'],
        )
        items = []
        for e in all_elements:
            role = e.get('role', '')
            name = e.get('name', '')
            if (role in dropdown_roles or
                (role == 'push button' and any(
                    kw in name.lower() for kw in ['upload', 'file', 'drive']
                ))) and name:
                items.append(e)
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
