from __future__ import annotations
"""Button discovery: element cache lookup + fresh AT-SPI tree search."""

import sys
import logging
from typing import Any, Dict, List, Optional

IS_MACOS = sys.platform == 'darwin'

if not IS_MACOS:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
else:
    Atspi = None

from core.tree import find_elements

logger = logging.getLogger(__name__)

# Button names for attach/upload triggers across platforms.
ATTACH_NAMES = [
    'open upload file menu',  # Gemini
    'attach',                 # Grok
    'add files and more',     # ChatGPT
    'add files or tools',     # Perplexity
    'toggle menu',            # Claude (attach trigger)
]


def find_attach_button(doc, platform: str = None):
    """Search for the attach/upload button by name.

    Checks element cache first (populated by taey_inspect), which has
    no child-per-node limit and reliably finds buttons even on pages
    with extensive conversation history. Falls back to fresh DFS if
    cache miss.

    Returns the raw AT-SPI accessible object (with action interface) or None.
    """
    # Check element cache first — inspect already found this button
    if platform:
        from core.atspi_interact import _element_cache, is_defunct
        for e in _element_cache.get(platform, []):
            name = (e.get('name') or '').strip().lower()
            role = e.get('role', '')
            if 'button' in role and name in ATTACH_NAMES:
                obj = e.get('atspi_obj')
                if obj and not is_defunct(e):
                    logger.info(f"Found attach button in cache: '{e.get('name')}' at ({e.get('x')}, {e.get('y')})")
                    return obj

    # Fall back to fresh tree search
    if IS_MACOS:
        all_elements = find_elements(doc)
        for e in all_elements:
            name = (e.get('name') or '').strip().lower()
            role = e.get('role', '')
            if 'button' in role and name in ATTACH_NAMES:
                obj = e.get('atspi_obj') or e.get('ax_ref')
                if obj:
                    logger.info(f"Found attach button in AX tree: '{e.get('name')}' at ({e.get('x')}, {e.get('y')})")
                    return obj
        return None

    # Linux: DFS through raw AT-SPI tree (50-child limit may miss on large pages)
    def search(obj, depth=0, max_depth=25):
        if depth > max_depth:
            return None
        try:
            role = obj.get_role_name() or ''
            name = (obj.get_name() or '').strip().lower()
            if 'button' in role and name in ATTACH_NAMES:
                comp = obj.get_component_iface()
                if comp:
                    ext = comp.get_extents(Atspi.CoordType.SCREEN)
                    if ext and ext.x >= 0 and ext.y >= 0:
                        return obj
            for i in range(min(obj.get_child_count(), 50)):
                child = obj.get_child_at_index(i)
                if child:
                    result = search(child, depth + 1)
                    if result:
                        return result
        except Exception:
            pass
        return None

    return search(doc)


def get_attach_button_coords(doc, platform: str = None) -> Optional[Dict]:
    """Find attach button and return its center coordinates.

    Returns dict with x, y, atspi_obj if found, None otherwise.
    """
    # Check element cache first — has coords directly
    if platform:
        from core.atspi_interact import _element_cache, is_defunct
        for e in _element_cache.get(platform, []):
            name = (e.get('name') or '').strip().lower()
            role = e.get('role', '')
            if 'button' in role and name in ATTACH_NAMES:
                obj = e.get('atspi_obj') or e.get('ax_ref')
                if obj and not is_defunct(e):
                    return {
                        'x': e.get('x', 0),
                        'y': e.get('y', 0),
                        'atspi_obj': obj,
                    }

    btn = find_attach_button(doc, platform=platform)
    if not btn:
        return None

    if IS_MACOS:
        all_elements = find_elements(doc)
        for e in all_elements:
            ref = e.get('atspi_obj') or e.get('ax_ref')
            if ref is btn:
                return {'x': e.get('x', 0), 'y': e.get('y', 0), 'atspi_obj': btn}
        return None

    # Linux: get extents from raw AT-SPI component interface
    try:
        comp = btn.get_component_iface()
        if comp:
            ext = comp.get_extents(Atspi.CoordType.SCREEN)
            if ext and ext.x >= 0 and ext.y >= 0:
                return {
                    'x': ext.x + (ext.width // 2 if ext.width else 0),
                    'y': ext.y + (ext.height // 2 if ext.height else 0),
                    'atspi_obj': btn,
                }
    except Exception:
        pass
    return None


def is_attach_button_disabled(atspi_obj) -> bool:
    """Check if an attach button is disabled (ENABLED=False in AT-SPI state)."""
    if IS_MACOS or not atspi_obj:
        return False
    try:
        state_set = atspi_obj.get_state_set()
        return not state_set.contains(Atspi.StateType.ENABLED)
    except Exception:
        return False
