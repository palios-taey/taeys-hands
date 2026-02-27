"""
Universal AT-SPI interaction layer.

Provides AT-SPI-first click, focus, scroll, and text input with
xdotool fallback. Eliminates per-platform hardcoding by probing
element capabilities at interaction time.

Based on Perplexity Deep Research architecture audit (Feb 2026).
Does NOT modify frozen core/input.py - wraps it as fallback.
"""

import subprocess
import time
import logging
from typing import Dict, List, Optional

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

logger = logging.getLogger(__name__)

# Module-level cache of last scan elements (with atspi_obj)
# Keyed by platform name. Updated by inspect tool after each scan.
_element_cache: Dict[str, List[Dict]] = {}


# =========================================================================
# Element cache
# =========================================================================

def cache_elements(platform: str, elements: List[Dict]):
    """Store elements from last AT-SPI scan for later lookup.

    Called by inspect tool after find_elements(). Elements must
    include 'atspi_obj' key with live AT-SPI accessible reference.
    """
    _element_cache[platform] = elements


def find_element_at(platform: str, x: int, y: int,
                    tolerance: int = 30) -> Optional[Dict]:
    """Find cached element closest to given coordinates.

    Uses Manhattan distance with tolerance threshold.
    Returns element dict with atspi_obj, or None.
    """
    elements = _element_cache.get(platform, [])
    best = None
    best_dist = float('inf')

    for e in elements:
        if not e.get('atspi_obj'):
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


def clear_cache(platform: str = None):
    """Clear element cache. If platform is None, clears all."""
    if platform:
        _element_cache.pop(platform, None)
    else:
        _element_cache.clear()


# =========================================================================
# Click: 3-tier strategy
# =========================================================================

def atspi_click(element: Dict, timeout: float = 0.3) -> bool:
    """Universal click: AT-SPI do_action first, xdotool fallback.

    Strategy hierarchy:
    1. AT-SPI do_action(0) - D-Bus, bypasses X11 entirely
    2. AT-SPI grab_focus() + Enter key - for focusable elements
    3. xdotool coordinate click - last resort

    Args:
        element: Element dict with 'atspi_obj' key.
        timeout: Post-click delay for UI to respond.

    Returns:
        True if click succeeded via any method.
    """
    obj = element.get('atspi_obj')

    # Reject defunct D-Bus proxies immediately (DOM node destroyed)
    if is_defunct(element):
        logger.debug(f"Skipping defunct element: '{element.get('name', '')[:50]}'")
        return False

    # Strategy 1: AT-SPI do_action (most reliable for buttons/links)
    if obj and _try_do_action(obj):
        logger.info(f"AT-SPI do_action click: '{element.get('name', '')[:50]}' "
                     f"[{element.get('role', '')}]")
        time.sleep(timeout)
        return True

    # Strategy 2: AT-SPI grab_focus + activate key
    if obj and _try_focus_and_activate(obj):
        logger.info(f"AT-SPI focus+Enter click: '{element.get('name', '')[:50]}' "
                     f"[{element.get('role', '')}]")
        time.sleep(timeout)
        return True

    # Strategy 3: xdotool coordinate click (fallback)
    x, y = element.get('x', 0), element.get('y', 0)
    if x > 0 and y > 0:
        logger.info(f"xdotool fallback click at ({x}, {y}): "
                     f"'{element.get('name', '')[:50]}'")
        return _xdotool_click(x, y)

    return False


def _try_do_action(obj) -> bool:
    """Invoke AT-SPI action on the object. Bypasses X11 entirely."""
    try:
        action_iface = obj.get_action_iface()
        if not action_iface:
            return False
        n_actions = action_iface.get_n_actions()
        if n_actions <= 0:
            return False

        # Prefer named actions, fall back to index 0
        for i in range(n_actions):
            action_name = action_iface.get_action_name(i)
            if action_name in ('click', 'activate', 'press', 'jump'):
                result = action_iface.do_action(i)
                logger.debug(f"do_action({i}) '{action_name}': {result}")
                return bool(result)

        # Default: action index 0
        result = action_iface.do_action(0)
        logger.debug(f"do_action(0) default: {result}")
        return bool(result)
    except Exception as e:
        logger.debug(f"do_action failed: {e}")
        return False


def _try_focus_and_activate(obj) -> bool:
    """Focus element via AT-SPI, then send Enter to activate."""
    try:
        state_set = obj.get_state_set()
        if not state_set.contains(Atspi.StateType.FOCUSABLE):
            return False

        comp = obj.get_component_iface()
        if not comp:
            return False

        result = comp.grab_focus()
        if not result:
            return False

        time.sleep(0.1)

        # Verify focus was acquired
        state_set = obj.get_state_set()
        if not state_set.contains(Atspi.StateType.FOCUSED):
            return False

        # Send Enter key via xdotool to activate
        subprocess.run(
            ['xdotool', 'key', 'Return'],
            capture_output=True, timeout=3
        )
        return True
    except Exception as e:
        logger.debug(f"focus+activate failed: {e}")
        return False


def _xdotool_click(x: int, y: int) -> bool:
    """Fallback: coordinate-based xdotool click."""
    try:
        result = subprocess.run(
            ['xdotool', 'mousemove', str(x), str(y), 'click', '1'],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception as e:
        logger.debug(f"xdotool click failed: {e}")
        return False


# =========================================================================
# Focus management
# =========================================================================

def atspi_focus(element: Dict) -> bool:
    """Focus an element via AT-SPI Component.grab_focus().

    Returns True if focus was acquired and verified.
    """
    obj = element.get('atspi_obj')
    if not obj:
        return False

    if is_defunct(element):
        return False

    try:
        comp = obj.get_component_iface()
        if not comp:
            return False

        result = comp.grab_focus()
        if not result:
            return False

        time.sleep(0.15)  # Allow focus transition

        # Verify focus
        state_set = obj.get_state_set()
        return state_set.contains(Atspi.StateType.FOCUSED)
    except Exception as e:
        logger.debug(f"grab_focus failed: {e}")
        return False


def atspi_scroll_into_view(element: Dict) -> bool:
    """Scroll element into view using AT-SPI Component.scroll_to()."""
    obj = element.get('atspi_obj')
    if not obj:
        return False

    try:
        comp = obj.get_component_iface()
        if not comp:
            return False
        return bool(comp.scroll_to(Atspi.ScrollType.ANYWHERE))
    except Exception as e:
        logger.debug(f"scroll_to failed: {e}")
        return False


# =========================================================================
# State verification
# =========================================================================

def is_defunct(element: Dict) -> bool:
    """Check if an AT-SPI element reference is no longer valid."""
    obj = element.get('atspi_obj')
    if not obj:
        return True
    try:
        state_set = obj.get_state_set()
        return state_set.contains(Atspi.StateType.DEFUNCT)
    except Exception:
        return True


def has_state(element: Dict, state: Atspi.StateType) -> bool:
    """Check if element has a specific AT-SPI state."""
    obj = element.get('atspi_obj')
    if not obj:
        return False
    try:
        state_set = obj.get_state_set()
        return state_set.contains(state)
    except Exception:
        return False


# =========================================================================
# Serialization helpers
# =========================================================================

def strip_atspi_obj(elements: List[Dict]) -> List[Dict]:
    """Strip atspi_obj from element dicts for JSON serialization.

    AT-SPI objects are D-Bus proxies and cannot be serialized.
    Call this before any JSON.dumps() or MCP result return.
    """
    return [{k: v for k, v in e.items() if k != 'atspi_obj'}
            for e in elements]
