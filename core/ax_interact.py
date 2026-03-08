from __future__ import annotations
"""
macOS AX element interaction layer.

Drop-in replacement for core/atspi_interact.py (Linux AT-SPI-based).
Element cache, AX action press, focus, state checks, serialization.
"""

import time
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import macOS AX API
try:
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCopyActionNames,
        AXUIElementPerformAction,
        AXUIElementSetAttributeValue,
    )
    HAS_AX = True
except ImportError:
    HAS_AX = False

# Module-level cache of last scan elements (with ax_ref)
_element_cache: Dict[str, List[Dict]] = {}


# =========================================================================
# Element cache
# =========================================================================

def cache_elements(platform: str, elements: List[Dict]):
    """Store elements from last AX scan for later lookup."""
    _element_cache[platform] = elements


def extend_cache(platform: str, elements: List[Dict]):
    """Add elements to existing cache for a platform."""
    existing = _element_cache.get(platform, [])
    _element_cache[platform] = existing + elements


def find_element_at(platform: str, x: int, y: int,
                    tolerance: int = 30) -> Optional[Dict]:
    """Find cached element closest to given coordinates.

    Uses Manhattan distance with tolerance threshold.
    """
    elements = _element_cache.get(platform, [])
    best = None
    best_dist = float('inf')

    for e in elements:
        if not (e.get('ax_ref') or e.get('atspi_obj')):
            continue
        if is_defunct(e):
            continue
        dx = abs(e.get('x', 0) - x)
        dy = abs(e.get('y', 0) - y)
        dist = dx + dy
        if dist < best_dist and dist <= tolerance:
            best = e
            best_dist = dist

    return best


# =========================================================================
# Click: AX action
# =========================================================================

def ax_click(element: Dict, timeout: float = 0.3) -> bool:
    """Click element via AXUIElement AXPress action.

    No fallback. If AX press fails, returns False.

    Args:
        element: Element dict with 'ax_ref' key.
        timeout: Post-click delay for UI to respond.

    Returns:
        True if AX action succeeded.
    """
    ref = element.get('ax_ref') or element.get('atspi_obj')
    if not ref or not HAS_AX:
        return False

    if is_defunct(element):
        logger.debug(f"Skipping defunct element: '{element.get('name', '')[:50]}'")
        return False

    if _try_ax_action(ref):
        logger.info(f"AX press action: '{element.get('name', '')[:50]}' "
                     f"[{element.get('role', '')}]")
        time.sleep(timeout)
        return True

    logger.warning(f"AX action FAILED for '{element.get('name', '')[:50]}' "
                   f"[{element.get('role', '')}]")
    return False


# Alias for compat with code that calls atspi_click
atspi_click = ax_click


def _try_ax_action(ref) -> bool:
    """Invoke AXPress action on the element."""
    try:
        err, actions = AXUIElementCopyActionNames(ref, None)
        if err != 0 or not actions:
            return False

        # Prefer AXPress, then AXConfirm
        for action_name in ('AXPress', 'AXConfirm', 'AXPick'):
            if action_name in actions:
                err = AXUIElementPerformAction(ref, action_name)
                logger.debug(f"AX action '{action_name}': err={err}")
                return err == 0

        # Default: first action
        err = AXUIElementPerformAction(ref, actions[0])
        logger.debug(f"AX action '{actions[0]}' (default): err={err}")
        return err == 0
    except Exception as e:
        logger.debug(f"AX action failed: {e}")
        return False


# =========================================================================
# Focus management
# =========================================================================

def ax_focus(element: Dict) -> bool:
    """Focus an element via AXUIElement.

    Sets AXFocused attribute to True.
    """
    ref = element.get('ax_ref') or element.get('atspi_obj')
    if not ref or not HAS_AX:
        return False

    if is_defunct(element):
        return False

    try:
        err = AXUIElementSetAttributeValue(ref, 'AXFocused', True)
        if err != 0:
            return False
        time.sleep(0.15)

        # Verify focus
        err, focused = AXUIElementCopyAttributeValue(ref, 'AXFocused', None)
        return err == 0 and focused
    except Exception as e:
        logger.debug(f"AX focus failed: {e}")
        return False


# Alias for compat
atspi_focus = ax_focus


# =========================================================================
# State verification
# =========================================================================

def is_defunct(element: Dict) -> bool:
    """Check if an AX element reference is no longer valid.

    On macOS, we check if we can still read the role attribute.
    """
    ref = element.get('ax_ref') or element.get('atspi_obj')
    if not ref:
        return True
    if not HAS_AX:
        return True
    try:
        err, role = AXUIElementCopyAttributeValue(ref, 'AXRole', None)
        return err != 0
    except Exception:
        return True


def has_state(element: Dict, state_name: str) -> bool:
    """Check if element has a specific state (by string name).

    On macOS we check the cached states list or query AX attributes directly.
    """
    # Check cached states first
    states = element.get('states', [])
    if state_name.lower() in [s.lower() for s in states]:
        return True

    # Dynamic check for common states
    ref = element.get('ax_ref')
    if not ref or not HAS_AX:
        return False

    try:
        state_attr_map = {
            'focused': 'AXFocused',
            'selected': 'AXSelected',
            'enabled': 'AXEnabled',
        }
        attr = state_attr_map.get(state_name.lower())
        if attr:
            err, val = AXUIElementCopyAttributeValue(ref, attr, None)
            return err == 0 and bool(val)
    except Exception:
        pass
    return False


# =========================================================================
# Serialization helpers
# =========================================================================

def strip_ax_ref(elements: List[Dict]) -> List[Dict]:
    """Strip ax_ref from element dicts for JSON serialization.

    AXUIElement objects cannot be serialized to JSON.
    """
    return [{k: v for k, v in e.items() if k not in ('ax_ref', 'atspi_obj')}
            for e in elements]


# Alias for compat with code that calls strip_atspi_obj
strip_atspi_obj = strip_ax_ref
