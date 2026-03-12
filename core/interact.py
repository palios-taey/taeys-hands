"""AT-SPI interaction: element cache, click, focus, state checks."""

import time
import logging
from typing import Dict, List, Optional

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

logger = logging.getLogger(__name__)

# Element cache keyed by platform — updated by inspect after each scan
_element_cache: Dict[str, List[Dict]] = {}


def cache_elements(platform: str, elements: List[Dict]):
    """Store elements from last AT-SPI scan (must include 'atspi_obj')."""
    _element_cache[platform] = elements


def extend_cache(platform: str, elements: List[Dict]):
    """Add elements to existing cache (e.g., dropdown items after click)."""
    _element_cache[platform] = _element_cache.get(platform, []) + elements


def find_element_at(platform: str, x: int, y: int,
                    tolerance: int = 30) -> Optional[Dict]:
    """Find cached element closest to (x, y) by Manhattan distance."""
    best, best_dist = None, float('inf')
    for e in _element_cache.get(platform, []):
        if not e.get('atspi_obj') or is_defunct(e):
            continue
        dist = abs(e.get('x', 0) - x) + abs(e.get('y', 0) - y)
        if dist < best_dist and dist <= tolerance:
            best, best_dist = e, dist
    return best


def atspi_click(element: Dict, timeout: float = 0.3) -> bool:
    """Click via AT-SPI do_action. No fallback — caller decides alternatives."""
    obj = element.get('atspi_obj')
    if is_defunct(element):
        return False
    if obj and _try_do_action(obj):
        logger.info(f"AT-SPI click: '{element.get('name', '')[:50]}' [{element.get('role', '')}]")
        time.sleep(timeout)
        return True
    return False


def _try_do_action(obj) -> bool:
    """Invoke AT-SPI action (bypasses X11 entirely)."""
    try:
        action = obj.get_action_iface()
        if not action or action.get_n_actions() <= 0:
            return False
        for i in range(action.get_n_actions()):
            if action.get_action_name(i) in ('click', 'activate', 'press', 'jump'):
                return bool(action.do_action(i))
        return bool(action.do_action(0))
    except Exception:
        return False


def atspi_focus(element: Dict) -> bool:
    """Focus element via grab_focus(). Returns True if focused."""
    obj = element.get('atspi_obj')
    if not obj or is_defunct(element):
        return False
    try:
        comp = obj.get_component_iface()
        if not comp or not comp.grab_focus():
            return False
        time.sleep(0.15)
        return obj.get_state_set().contains(Atspi.StateType.FOCUSED)
    except Exception:
        return False


def is_defunct(element: Dict) -> bool:
    """Check if AT-SPI reference is no longer valid."""
    obj = element.get('atspi_obj')
    if not obj:
        return True
    try:
        return obj.get_state_set().contains(Atspi.StateType.DEFUNCT)
    except Exception:
        return True


def has_state(element: Dict, state: Atspi.StateType) -> bool:
    obj = element.get('atspi_obj')
    if not obj:
        return False
    try:
        return obj.get_state_set().contains(state)
    except Exception:
        return False


def strip_atspi_obj(elements: List[Dict]) -> List[Dict]:
    """Strip atspi_obj for JSON serialization (D-Bus proxies can't serialize)."""
    return [{k: v for k, v in e.items() if k != 'atspi_obj'} for e in elements]
