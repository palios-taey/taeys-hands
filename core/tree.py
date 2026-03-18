"""AT-SPI tree traversal and element extraction."""

import hashlib
import logging
from typing import Dict, List, Optional

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

logger = logging.getLogger(__name__)

IMPORTANT_STATES = [
    Atspi.StateType.SHOWING, Atspi.StateType.SELECTED, Atspi.StateType.CHECKED,
    Atspi.StateType.PRESSED, Atspi.StateType.FOCUSED, Atspi.StateType.EXPANDED,
    Atspi.StateType.EDITABLE, Atspi.StateType.FOCUSABLE, Atspi.StateType.ENABLED,
    Atspi.StateType.MULTI_LINE,
]

POPUP_ROLES = {
    'menu', 'menu item', 'check menu item', 'radio menu item',
    'menu bar', 'popup menu',
    'combo box', 'list box', 'list item',
    'dialog', 'alert', 'tool tip', 'window',
}

_DECORATIVE_ROLES = {'image', 'static', 'separator', 'paragraph'}
IMPORTANT_STATE_NAMES = {'editable', 'checked', 'selected', 'pressed', 'focused'}

# Social platform text extraction
_TEXT_EXTRACT_ROLES = {'article', 'section'}
_TEXT_EXTRACT_MAX_CHARS = 300
_TEXT_EXTRACT_MAX_CHILDREN = 8

FIREFOX_CHROME_Y = 100


def _collect_child_text(obj, max_children=_TEXT_EXTRACT_MAX_CHILDREN,
                        max_chars=_TEXT_EXTRACT_MAX_CHARS) -> str:
    """Collect text from direct children of unnamed containers (tweets, etc.)."""
    parts, chars = [], 0
    try:
        for i in range(min(obj.get_child_count(), max_children)):
            child = obj.get_child_at_index(i)
            if not child:
                continue
            name = child.get_name() or ''
            if name:
                parts.append(name.strip())
                chars += len(name)
                if chars >= max_chars:
                    break
            for j in range(min(child.get_child_count(), 4)):
                sub = child.get_child_at_index(j)
                if sub and (sub.get_name() or ''):
                    parts.append(sub.get_name().strip())
                    chars += len(sub.get_name())
                    if chars >= max_chars:
                        break
            if chars >= max_chars:
                break
    except Exception:
        pass
    text = ' | '.join(parts)
    return text[:max_chars] if text else ''


def find_elements(scope, max_depth: int = 25,
                  exclude_landmarks: Optional[List[str]] = None,
                  fence_after: Optional[List[Dict]] = None) -> List[Dict]:
    """Find all visible elements in an AT-SPI subtree.

    fence_after: list of {name, role} dicts. When an element matches,
    it is collected but traversal stops for all remaining siblings in the
    parent. Used to exclude sidebar history (siblings after a known trigger).
    The fence propagates one level: the parent stops iterating, but the
    grandparent continues normally.
    """
    results = []
    exclude_lower = [n.lower() for n in (exclude_landmarks or [])]
    fence_set = set()
    if fence_after:
        for item in fence_after:
            fence_set.add((str(item.get('name', '')).lower(), item.get('role', '')))

    def traverse(obj, depth=0):
        """Returns True if a fence element was found (signals parent to stop siblings)."""
        if depth > max_depth:
            return False
        try:
            name = obj.get_name() or ''
            role = obj.get_role_name() or ''
            state_set = obj.get_state_set()

            if role == 'landmark' and name and exclude_lower:
                if name.lower() in exclude_lower:
                    return False

            has_showing = state_set.contains(Atspi.StateType.SHOWING)
            has_visible = state_set.contains(Atspi.StateType.VISIBLE)
            is_popup = role in POPUP_ROLES

            comp = obj.get_component_iface()
            if comp and (has_showing or has_visible or is_popup):
                rect = comp.get_extents(Atspi.CoordType.SCREEN)
                if rect and rect.x >= 0 and rect.y >= 0:
                    cx = rect.x + (rect.width // 2 if rect.width else 0)
                    cy = rect.y + (rect.height // 2 if rect.height else 0)
                    element = {'name': name, 'role': role, 'x': cx, 'y': cy, 'atspi_obj': obj}

                    states = [s.value_nick for s in IMPORTANT_STATES if state_set.contains(s)]
                    if states:
                        element['states'] = states
                    desc = obj.get_description()
                    if desc:
                        element['description'] = desc
                    if not name and role in _TEXT_EXTRACT_ROLES:
                        child_text = _collect_child_text(obj)
                        if child_text:
                            element['text'] = child_text
                    results.append(element)

            # Fence: collect this element, skip children, tell parent to stop siblings
            if fence_set and name and (name.lower(), role) in fence_set:
                return True

            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child:
                    if traverse(child, depth + 1):
                        break  # Fence found in child — stop remaining siblings
        except Exception as e:
            logger.debug(f"Traversal error at depth {depth}: {e}")
        return False

    traverse(scope)
    return results


def detect_chrome_y(doc) -> int:
    """Detect Firefox chrome height from document element position."""
    try:
        comp = doc.get_component_iface()
        if comp:
            rect = comp.get_extents(Atspi.CoordType.SCREEN)
            if rect and rect.y > 0:
                return rect.y
    except Exception:
        pass
    return FIREFOX_CHROME_Y


def filter_useful_elements(elements: List[Dict], chrome_y: int = None) -> List[Dict]:
    """Filter to active main-window content (SHOWING/ENABLED + chrome Y threshold)."""
    threshold = chrome_y if chrome_y is not None else FIREFOX_CHROME_Y
    _INTERACTIVE = {
        'push button', 'toggle button', 'entry', 'combo box',
        'check box', 'radio button', 'link', 'menu item',
        'page tab', 'page tab list',
    }

    def is_useful(e):
        if e.get('y', 0) < threshold:
            return False
        role = e.get('role', '')
        name = e.get('name', '').strip()
        states = set(s.lower() for s in e.get('states', []))

        # Editable elements are always useful (input fields)
        if 'editable' in states:
            return True
        # Named enabled interactive elements (some platforms lack SHOWING)
        if 'enabled' in states and role in _INTERACTIVE and name:
            return True
        if role in POPUP_ROLES:
            return bool(name) or bool(states & IMPORTANT_STATE_NAMES)
        if 'showing' not in states:
            return False
        if role in _DECORATIVE_ROLES and not name and not (states & IMPORTANT_STATE_NAMES):
            return False
        return True

    filtered = [e for e in elements if is_useful(e)]

    # Fallback for platforms that don't set SHOWING on interactive elements
    if not filtered and elements:
        logger.warning("Primary filter returned 0 elements, using ENABLED-only fallback")
        def is_enabled_interactive(e):
            if e.get('y', 0) < threshold:
                return False
            states = set(s.lower() for s in e.get('states', []))
            if 'enabled' not in states:
                return False
            role = e.get('role', '')
            name = e.get('name', '').strip()
            return (role in _INTERACTIVE and name) or 'editable' in states

        filtered = [e for e in elements if is_enabled_interactive(e)]

    filtered.sort(key=lambda x: x['y'])
    return filtered


def find_copy_buttons(elements: List[Dict]) -> List[Dict]:
    """Find copy buttons sorted by Y (newest last)."""
    buttons = [e for e in elements
               if 'button' in e.get('role', '') and 'copy' in (e.get('name') or '').lower()]
    buttons.sort(key=lambda b: b.get('y', 0))
    return buttons


def find_menu_items(firefox, platform_doc=None) -> List[Dict]:
    """Find visible menu items (4-pass: strict doc, containerless doc, strict firefox, loose)."""
    _ITEM_ROLES = {'menu item', 'radio menu item', 'check menu item', 'list item', 'option'}
    _STRICT = {'menu', 'popup menu', 'listbox'}
    _LOOSE = {'list', 'panel'}

    def _is_showing(obj):
        try:
            ss = obj.get_state_set()
            return ss.contains(Atspi.StateType.SHOWING) or ss.contains(Atspi.StateType.VISIBLE)
        except Exception:
            return False

    def _item_from_child(child, require_showing=False):
        role = child.get_role_name() or ''
        name = child.get_name() or ''
        if not (name and role in _ITEM_ROLES):
            return None
        try:
            if require_showing and not child.get_state_set().contains(Atspi.StateType.SHOWING):
                return None
            comp = child.get_component_iface()
            if comp:
                ext = comp.get_extents(Atspi.CoordType.SCREEN)
                if ext.width > 0 and ext.height > 0:
                    return {'name': name, 'role': role,
                            'x': ext.x + ext.width // 2, 'y': ext.y + ext.height // 2,
                            'atspi_obj': child}
        except Exception:
            pass
        return None

    def _collect(scope, max_depth=15, require_showing=True,
                 require_item_showing=False, containers=None):
        if containers is None:
            containers = _STRICT | _LOOSE
        found = []

        def search(obj, depth=0):
            nonlocal found
            if depth > max_depth or found:
                return
            try:
                role = obj.get_role_name() or ''
                if role == 'menu bar':
                    return
                if role in containers:
                    if not require_showing or _is_showing(obj):
                        items = []
                        for i in range(min(obj.get_child_count(), 30)):
                            child = obj.get_child_at_index(i)
                            if child:
                                item = _item_from_child(child, require_item_showing)
                                if item:
                                    items.append(item)
                        if items:
                            found = items
                            return
                for i in range(min(obj.get_child_count(), 30)):
                    child = obj.get_child_at_index(i)
                    if child:
                        search(child, depth + 1)
            except Exception:
                pass

        search(scope)
        return found

    def _sorted(items):
        items.sort(key=lambda x: x['y'])
        return items

    # Pass 1: Strict containers in platform_doc (with SHOWING on container)
    if platform_doc:
        items = _collect(platform_doc, containers=_STRICT)
        if items:
            return _sorted(items)

    # Pass 2: Strict containers WITHOUT SHOWING requirement
    # (Gemini doesn't set SHOWING on menu containers when sidebar collapsed)
    if platform_doc:
        items = _collect(platform_doc, require_showing=False, containers=_STRICT)
        if items:
            return _sorted(items)

    # Pass 3: Containerless menu items in platform_doc
    if platform_doc:
        _fallback = ('menu item', 'radio menu item', 'check menu item')
        all_el = find_elements(platform_doc)
        items = [e for e in all_el if e.get('name') and e.get('role', '') in _fallback]
        if items:
            return _sorted(items)

    # Pass 4: Firefox root (strict then loose containers)
    if firefox:
        items = _collect(firefox, require_item_showing=True, containers=_STRICT)
        if items:
            return _sorted(items)
    if platform_doc:
        items = _collect(platform_doc, containers=_LOOSE)
        if items:
            return _sorted(items)
    if firefox:
        items = _collect(firefox, require_item_showing=True, containers=_LOOSE)
        if items:
            return _sorted(items)

    return []


# Backward-compatible alias
find_dropdown_menus = find_menu_items


def compute_structure_hash(elements: List[Dict], screen_height: int = 1080,
                           grid_rows: int = 12) -> str:
    """Structural fingerprint (roles + Y-grid, not names). Detects UI redesigns."""
    band_height = max(screen_height // grid_rows, 1)
    _CONTENT_ROLES = {'link', 'list item', 'heading', 'static', 'label',
                      'paragraph', 'text', 'section'}
    pairs = []
    for e in elements:
        role = e.get('role', '')
        if not role or role in _CONTENT_ROLES:
            continue
        pairs.append(f"{role}@{e.get('y', 0) // band_height}")
    pairs.sort()
    return hashlib.sha256("|".join(pairs).encode()).hexdigest()[:16]
