"""
AT-SPI tree traversal and element extraction.

Provides BFS/DFS traversal of the accessibility tree, extracting
visible elements with their names, roles, states, and coordinates.
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
    Atspi.StateType.SHOWING,    # must come first — used by filter_useful_elements
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

# Purely decorative roles — filter when unnamed and lacking important states.
# Structural containers (section, panel, form, etc.) are NOT in this list
# so that file chips and other unnamed SHOWING containers remain visible.
_DECORATIVE_ROLES = {'image', 'static', 'separator', 'paragraph'}

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
    """Filter elements to active main-window content.

    Strategy:
    - Require SHOWING state for non-popup elements. AT-SPI's SHOWING means
      "currently rendered and on screen". VISIBLE-only elements are sidebar
      bleed-through or off-screen content — not part of the active main window.
    - Drop unnamed purely decorative roles (images, static text, separators,
      paragraphs) that carry no actionable or structural meaning.
    - Keep everything else that is SHOWING, including unnamed containers
      (sections, panels, forms) that wrap file chips or input widgets.

    Popup roles (menus, tooltips, dialogs) bypass the SHOWING requirement
    since they are transient and may lack that state.

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

        # Popups bypass SHOWING (transient menus, tooltips, dialogs)
        if role in POPUP_ROLES:
            return bool(name) or bool(states & IMPORTANT_STATE_NAMES)

        # Non-popup must be SHOWING (VISIBLE-only = sidebar/inactive bleed-through)
        if 'showing' not in states:
            return False

        # Drop unnamed decorative elements (icons, text spans, dividers)
        if role in _DECORATIVE_ROLES and not name and not (states & IMPORTANT_STATE_NAMES):
            return False

        # Keep everything else that is SHOWING
        return True

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


def find_menu_items(firefox, platform_doc=None) -> List[Dict]:
    """Find visible menu items in the AT-SPI tree.

    Searches for elements with menu-related roles, collecting children.
    Only returns items from menus that are actually SHOWING (visible).
    This filters out Firefox's persistent context menu which stays in
    the tree with non-zero extents even when not displayed.

    Searches platform_doc first (avoids cross-tab contamination), then
    Firefox root (dropdowns render outside the document element).
    Falls back to searching document for menu-role items without a
    menu container (some platforms render items directly).

    Args:
        firefox: Firefox AT-SPI accessible.
        platform_doc: Platform document element (preferred search scope).

    Returns:
        List of menu item dicts with name, role, x, y, sorted by Y.
    """
    _MENU_ITEM_ROLES = {'menu item', 'radio menu item', 'check menu item', 'list item', 'option'}

    def _is_menu_showing(menu_obj) -> bool:
        """Check if a menu element is actually visible on screen."""
        try:
            state_set = menu_obj.get_state_set()
            return (state_set.contains(Atspi.StateType.SHOWING) or
                    state_set.contains(Atspi.StateType.VISIBLE))
        except Exception:
            return False

    def _collect_items_from_child(child):
        """Extract a menu item dict from an AT-SPI child element."""
        child_role = child.get_role_name() or ''
        child_name = child.get_name() or ''
        if child_name and child_role in _MENU_ITEM_ROLES:
            try:
                comp = child.get_component_iface()
                if comp:
                    ext = comp.get_extents(Atspi.CoordType.SCREEN)
                    if ext.width > 0 and ext.height > 0:
                        return {
                            'name': child_name,
                            'role': child_role,
                            'x': ext.x + ext.width // 2,
                            'y': ext.y + ext.height // 2,
                            'atspi_obj': child,
                        }
            except Exception as e:
                logger.debug(f"Menu item extent error: {e}")
        return None

    def _collect_from(scope, max_depth=15, require_showing=True):
        """Find first menu with items in scope."""
        found = []

        def search(obj, depth=0):
            nonlocal found
            if depth > max_depth or found:
                return
            try:
                role = obj.get_role_name() or ''

                # Skip menu bar (Firefox chrome)
                if role == 'menu bar':
                    return

                # Match menu containers: menu, listbox, popup menu, panel
                _MENU_CONTAINERS = {'menu', 'listbox', 'popup menu', 'panel'}
                if role in _MENU_CONTAINERS:
                    if require_showing and not _is_menu_showing(obj):
                        pass
                    else:
                        items = []
                        for i in range(min(obj.get_child_count(), 30)):
                            child = obj.get_child_at_index(i)
                            if not child:
                                continue
                            item = _collect_items_from_child(child)
                            if item:
                                items.append(item)
                        if items:
                            found = items
                            return

                for i in range(min(obj.get_child_count(), 30)):
                    child = obj.get_child_at_index(i)
                    if child:
                        search(child, depth + 1)
            except Exception as e:
                logger.debug(f"Menu search error at depth {depth}: {e}")

        search(scope)
        return found

    # Search platform_doc first (avoids cross-tab contamination)
    if platform_doc:
        items = _collect_from(platform_doc)
        if items:
            items.sort(key=lambda x: x['y'])
            return items

    # Then Firefox root (dropdowns render outside document)
    if firefox:
        items = _collect_from(firefox)
        if items:
            items.sort(key=lambda x: x['y'])
            return items

    # Retry WITHOUT requiring SHOWING state — platform_doc only.
    # NEVER retry on firefox root without SHOWING: persistent Firefox
    # chrome menus (tab context menu) are always in the tree with
    # non-zero extents even when not displayed.
    logger.debug("Strict SHOWING search failed, retrying platform_doc without SHOWING requirement")
    if platform_doc:
        items = _collect_from(platform_doc, require_showing=False)
        if items:
            items.sort(key=lambda x: x['y'])
            return items

    # Fallback: search document for menu items without a menu container.
    if platform_doc:
        _fallback_roles = ('menu item', 'radio menu item', 'check menu item')
        all_elements = find_elements(platform_doc)
        items = [e for e in all_elements
                 if e.get('name') and e.get('role', '') in _fallback_roles]
        if items:
            items.sort(key=lambda x: x['y'])
            return items

    return []


# Backward-compatible alias
find_dropdown_menus = find_menu_items


def compute_tree_hash(elements: List[Dict]) -> str:
    """Compute SHA256 hash of element role:name pairs for state comparison.

    Used to detect whether an action actually changed the UI.
    Stable algorithm — do not change without updating all callers.

    Args:
        elements: Element list from find_elements.

    Returns:
        16-character hex digest (first 64 bits of SHA256).
    """
    pairs = sorted(f"{e.get('role', '')}:{e.get('name', '')}" for e in elements
                   if e.get('role') or e.get('name'))
    content = "|".join(pairs)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_structure_hash(elements: List[Dict], screen_height: int = 1080,
                           grid_rows: int = 12) -> str:
    """Compute a structure-only fingerprint of the UI layout.

    Unlike compute_tree_hash (which includes element names and changes
    with every conversation message), this captures only the structural
    skeleton: which roles appear in which vertical band of the screen.

    This detects when a platform redesigns their UI (buttons move,
    new controls appear, layout shifts) while being stable across
    normal content changes (new messages, different text).

    Content-variable roles (links, list items, headings, static text)
    are excluded entirely — these change with conversation history and
    sidebar state, not UI structure.

    Args:
        elements: Element list from find_elements or filter_useful_elements.
        screen_height: Screen height in pixels for grid calculation.
        grid_rows: Number of vertical bands to bucket elements into.

    Returns:
        16-character hex digest representing the structural fingerprint.
    """
    band_height = max(screen_height // grid_rows, 1)

    # Roles that represent content, not UI structure — these change with
    # conversation history, sidebar sessions, and page content
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

    # Sort for deterministic hashing
    structure_pairs.sort()
    content = "|".join(structure_pairs)
    return hashlib.sha256(content.encode()).hexdigest()[:16]
