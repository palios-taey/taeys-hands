"""AT-SPI tree traversal and element extraction."""

import hashlib
import logging
from typing import Any, Dict, List, Optional

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


def _validate_prune_relation_spec(spec: Dict, label: str) -> None:
    for key in spec:
        if key not in {'role', 'name', 'names_any_of'}:
            raise ValueError(f'unsupported prune_subtree_specs {label} key {key!r}')
    if not any(key in spec for key in ('role', 'name', 'names_any_of')):
        raise ValueError(f'prune_subtree_specs {label} must declare role, name, or names_any_of')
    if 'role' in spec and not isinstance(spec['role'], str):
        raise ValueError(f'prune_subtree_specs {label} role must be an exact string')
    if 'name' in spec and not isinstance(spec['name'], str):
        raise ValueError(f'prune_subtree_specs {label} name must be an exact string')
    if 'names_any_of' in spec:
        candidates = spec['names_any_of']
        if (
            not isinstance(candidates, list)
            or not all(isinstance(item, str) for item in candidates)
        ):
            raise ValueError(f'prune_subtree_specs {label} names_any_of must be a list of exact strings')


def _validate_prune_subtree_specs(specs: Optional[List[Dict]]) -> List[Dict[str, Any]]:
    normalized = []
    for spec in specs or []:
        if not isinstance(spec, dict):
            raise ValueError('prune_subtree_specs entries must be mappings')
        for key in spec:
            if key not in {'role', 'name', 'names_any_of', 'ancestor', 'parent', 'min_child_count'}:
                raise ValueError(f'unsupported prune_subtree_specs key {key!r}')
        if not any(key in spec for key in ('role', 'name', 'names_any_of')):
            raise ValueError('prune_subtree_specs entries must declare role, name, or names_any_of')
        if 'role' in spec and not isinstance(spec['role'], str):
            raise ValueError('prune_subtree_specs role must be an exact string')
        if 'name' in spec and not isinstance(spec['name'], str):
            raise ValueError('prune_subtree_specs name must be an exact string')
        if 'names_any_of' in spec:
            candidates = spec['names_any_of']
            if (
                not isinstance(candidates, list)
                or not all(isinstance(item, str) for item in candidates)
            ):
                raise ValueError('prune_subtree_specs names_any_of must be a list of exact strings')
        if 'ancestor' in spec:
            ancestor = spec['ancestor']
            if not isinstance(ancestor, dict):
                raise ValueError('prune_subtree_specs ancestor must be a mapping')
            _validate_prune_relation_spec(ancestor, 'ancestor')
        if 'parent' in spec:
            parent = spec['parent']
            if not isinstance(parent, dict):
                raise ValueError('prune_subtree_specs parent must be a mapping')
            _validate_prune_relation_spec(parent, 'parent')
        if 'min_child_count' in spec and not isinstance(spec['min_child_count'], int):
            raise ValueError('prune_subtree_specs min_child_count must be an integer')
        normalized.append(dict(spec))
    return normalized


def _node_matches_prune_spec(name: str, role: str, spec: Dict[str, Any]) -> bool:
    if 'role' in spec and role != spec['role']:
        return False
    if 'name' in spec and name != spec['name']:
        return False
    if 'names_any_of' in spec and name not in set(spec['names_any_of']):
        return False
    return True


def _has_matching_ancestor(ancestors: List[tuple[str, str]], spec: Dict[str, Any]) -> bool:
    return any(
        _node_matches_prune_spec(ancestor_name, ancestor_role, spec)
        for ancestor_name, ancestor_role in ancestors
    )


def _has_matching_parent(ancestors: List[tuple[str, str]], spec: Dict[str, Any]) -> bool:
    if not ancestors:
        return False
    parent_name, parent_role = ancestors[-1]
    return _node_matches_prune_spec(parent_name, parent_role, spec)


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
                  fence_after: Optional[List[Dict]] = None,
                  prune_subtree_roles: Optional[List[str]] = None,
                  prune_subtree_specs: Optional[List[Dict]] = None) -> List[Dict]:
    """Find all visible elements in an AT-SPI subtree.

    fence_after: list of {name, role} dicts. When an element matches,
    it is collected but traversal stops for all remaining siblings in the
    parent. Used to exclude sidebar history (siblings after a known trigger).
    The fence propagates one level: the parent stops iterating, but the
    grandparent continues normally.

    prune_subtree_roles: list of AT-SPI role names whose ENTIRE subtree is
    skipped (not collected, not descended). Used when scanning from the Firefox
    app root to drop browser chrome (tool bar / menu bar / page tab list) so it
    never floods the snapshot — page content lives under the content panel /
    document, never under these chrome containers. Default None = no pruning,
    so every existing caller is unchanged.

    prune_subtree_specs: exact structural container specs whose ENTIRE subtree
    is skipped (not collected, not descended). Supports exact role/name,
    names_any_of, optional exact ancestor, and optional min_child_count.
    """
    results = []
    exclude_lower = [n.lower() for n in (exclude_landmarks or [])]
    prune_lower = {r.lower() for r in (prune_subtree_roles or [])}
    subtree_specs = _validate_prune_subtree_specs(prune_subtree_specs)
    fence_set = set()
    if fence_after:
        for item in fence_after:
            fence_set.add((str(item.get('name', '')).lower(), item.get('role', '')))

    def should_prune_by_spec(obj, name: str, role: str, ancestors: List[tuple[str, str]]) -> bool:
        for spec in subtree_specs:
            if not _node_matches_prune_spec(name, role, spec):
                continue
            if obj.get_child_count() < int(spec.get('min_child_count', 0)):
                continue
            ancestor = spec.get('ancestor')
            if ancestor and not _has_matching_ancestor(ancestors, ancestor):
                continue
            parent = spec.get('parent')
            if parent and not _has_matching_parent(ancestors, parent):
                continue
            return True
        return False

    def traverse(obj, depth=0, ancestors=None):
        """Returns True if a fence element was found (signals parent to stop siblings)."""
        ancestor_stack = list(ancestors or [])
        if depth > max_depth:
            return False
        try:
            name = obj.get_name() or ''
            role = obj.get_role_name() or ''

            # Chrome prune: skip browser-chrome container subtrees entirely
            # (no collect, no descend). Returns False so the parent keeps
            # iterating its remaining siblings (this is not a fence).
            if prune_lower and role.lower() in prune_lower:
                return False
            if subtree_specs and should_prune_by_spec(obj, name, role, ancestor_stack):
                return False

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
                    if traverse(child, depth + 1, ancestor_stack + [(name, role)]):
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


def find_menu_items(firefox, platform_doc=None, allowed_roles=None) -> List[Dict]:
    """Find visible menu items with flat subtree search and container fallback."""
    _ITEM_ROLES = set(allowed_roles or {
        'menu item', 'radio menu item', 'check menu item', 'list item', 'option',
    })
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
            state_set = child.get_state_set()
            if require_showing and not state_set.contains(Atspi.StateType.SHOWING):
                return None
            comp = child.get_component_iface()
            if comp:
                ext = comp.get_extents(Atspi.CoordType.SCREEN)
                if ext.width > 0 and ext.height > 0:
                    item = {
                        'name': name,
                        'role': role,
                        'x': ext.x + ext.width // 2,
                        'y': ext.y + ext.height // 2,
                        'atspi_obj': child,
                    }
                    states = [s.value_nick for s in IMPORTANT_STATES if state_set.contains(s)]
                    if states:
                        item['states'] = states
                    return item
        except Exception:
            pass
        return None

    def _dedupe(items):
        merged = []
        seen = set()
        for item in items:
            key = (item.get('name', ''), item.get('role', ''))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def _collect_flat(scope, max_depth=15, require_item_showing=True):
        current_level = [scope]
        depth = 0
        items = []

        while current_level and depth <= max_depth:
            next_level = []

            for obj in current_level:
                try:
                    role = obj.get_role_name() or ''
                    if role != 'menu bar':
                        item = _item_from_child(obj, require_item_showing)
                        if item:
                            items.append(item)

                    for i in range(min(obj.get_child_count(), 30)):
                        child = obj.get_child_at_index(i)
                        if child:
                            next_level.append(child)
                except Exception:
                    pass

            current_level = next_level
            depth += 1

        return _dedupe(items)

    def _collect(scope, max_depth=15, require_showing=True,
                 require_item_showing=False, containers=None):
        if containers is None:
            containers = _STRICT | _LOOSE

        current_level = [scope]
        depth = 0

        while current_level and depth <= max_depth:
            next_level = []
            level_items = []

            for obj in current_level:
                try:
                    role = obj.get_role_name() or ''
                    if role == 'menu bar':
                        continue

                    if role in containers and (not require_showing or _is_showing(obj)):
                        items = []
                        for i in range(min(obj.get_child_count(), 30)):
                            child = obj.get_child_at_index(i)
                            if child:
                                item = _item_from_child(child, require_item_showing)
                                if item:
                                    items.append(item)
                        if items:
                            level_items.extend(items)

                    for i in range(min(obj.get_child_count(), 30)):
                        child = obj.get_child_at_index(i)
                        if child:
                            next_level.append(child)
                except Exception:
                    pass

            if level_items:
                return _dedupe(level_items)

            current_level = next_level
            depth += 1

        return []

    def _sorted(items):
        items.sort(key=lambda x: x['y'])
        return items

    # Pass 1: Flat subtree search in platform_doc for visible menu items.
    if platform_doc:
        items = _collect_flat(platform_doc, require_item_showing=True)
        if items:
            return _sorted(items)

    # Pass 2: Flat subtree search in firefox root for visible menu items.
    if firefox:
        items = _collect_flat(firefox, require_item_showing=True)
        if items:
            return _sorted(items)

    # Pass 3: Strict containers in platform_doc (with SHOWING on container)
    if platform_doc:
        items = _collect(platform_doc, containers=_STRICT)
        if items:
            return _sorted(items)

    # Pass 4: Strict containers WITHOUT SHOWING requirement
    # (Gemini doesn't set SHOWING on menu containers when sidebar collapsed)
    if platform_doc:
        items = _collect(platform_doc, require_showing=False, containers=_STRICT)
        if items:
            return _sorted(items)

    # Pass 5: Containerless menu items in platform_doc
    if platform_doc:
        _fallback = ('menu item', 'radio menu item', 'check menu item')
        all_el = find_elements(platform_doc)
        items = _dedupe([e for e in all_el if e.get('name') and e.get('role', '') in _fallback])
        if items:
            return _sorted(items)

    # Pass 6: Firefox root (strict then loose containers)
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
