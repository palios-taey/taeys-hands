"""AT-SPI interaction: element cache, click, focus, state checks."""

import time
import logging
from typing import Dict, List, Optional

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from consultation_v2 import input as inp

logger = logging.getLogger(__name__)

# Element cache keyed by platform — updated by inspect after each scan
_element_cache: Dict[str, List[Dict]] = {}
_cache_timestamps: Dict[str, float] = {}
CACHE_TTL_SECONDS = 10  # Invalidate cached elements after this many seconds


def cache_elements(platform: str, elements: List[Dict]):
    """Store elements from last AT-SPI scan (must include 'atspi_obj')."""
    _element_cache[platform] = elements
    _cache_timestamps[platform] = time.time()


def extend_cache(platform: str, elements: List[Dict]):
    """Add elements to existing cache (e.g., dropdown items after click)."""
    _element_cache[platform] = _element_cache.get(platform, []) + elements
    _cache_timestamps[platform] = time.time()


def is_cache_stale(platform: str) -> bool:
    """Check if the cache for this platform has exceeded its TTL."""
    ts = _cache_timestamps.get(platform)
    if ts is None:
        return True
    return (time.time() - ts) > CACHE_TTL_SECONDS


def invalidate_cache(platform: str):
    """Explicitly invalidate cache for a platform."""
    _element_cache.pop(platform, None)
    _cache_timestamps.pop(platform, None)


def find_element_at(platform: str, x: int, y: int,
                    tolerance: int = 30) -> Optional[Dict]:
    """Find cached element closest to (x, y) by Manhattan distance.

    Returns None if cache is stale (caller should re-inspect).
    """
    if is_cache_stale(platform):
        logger.debug("Cache stale for %s (age=%.1fs), returning None",
                     platform, time.time() - _cache_timestamps.get(platform, 0))
        return None
    best, best_dist = None, float('inf')
    for e in _element_cache.get(platform, []):
        if not e.get('atspi_obj') or is_defunct(e):
            continue
        dist = abs(int(e.get('x', 0)) - x) + abs(int(e.get('y', 0)) - y)
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


def atspi_element_viewport_state(element: Dict) -> Dict[str, object]:
    """Report whether one exact bound object's live extent fits the display."""
    evidence: Dict[str, object] = {
        'atspi_object_bound': False,
        'live_extent_resolved': False,
        'display_geometry_resolved': False,
        'live_extent_in_viewport': False,
        'intersects_viewport': False,
        'x': 0,
        'y': 0,
        'width': 0,
        'height': 0,
        'display_width': 0,
        'display_height': 0,
        'available_below_px': 0,
        'error': None,
    }
    obj = element.get('atspi_obj')
    if not obj or is_defunct(element):
        evidence['error'] = 'missing_or_defunct_atspi_object'
        return evidence
    evidence['atspi_object_bound'] = True
    try:
        component = obj.get_component_iface()
        if component is None:
            evidence['error'] = 'missing_component_iface'
            return evidence
        rect = component.get_extents(Atspi.CoordType.SCREEN)
        if (
            rect is None
            or rect.width <= 0
            or rect.height <= 0
        ):
            evidence['error'] = 'invalid_live_extent'
            return evidence
        evidence['live_extent_resolved'] = True
        display_width, display_height = inp.display_geometry()
        display_width = int(display_width)
        display_height = int(display_height)
        evidence['display_width'] = display_width
        evidence['display_height'] = display_height
        if display_width <= 0 or display_height <= 0:
            evidence['error'] = 'invalid_display_geometry'
            return evidence
        evidence['display_geometry_resolved'] = True
        evidence.update({
            'x': int(rect.x),
            'y': int(rect.y),
            'width': int(rect.width),
            'height': int(rect.height),
            'display_width': display_width,
            'display_height': display_height,
            'available_below_px': max(
                0,
                int(display_height - (rect.y + rect.height)),
            ),
            'intersects_viewport': bool(
                rect.width > 0
                and rect.height > 0
                and display_width > 0
                and display_height > 0
                and rect.x < display_width
                and rect.x + rect.width > 0
                and rect.y < display_height
                and rect.y + rect.height > 0
            ),
            'live_extent_in_viewport': bool(
                rect.width > 0
                and rect.height > 0
                and display_width > 0
                and display_height > 0
                and rect.x >= 0
                and rect.y >= 0
                and rect.x + rect.width <= display_width
                and rect.y + rect.height <= display_height
            ),
        })
        if evidence['live_extent_in_viewport'] is not True:
            evidence['error'] = 'live_extent_outside_display'
            return evidence
        return evidence
    except Exception as exc:
        evidence['error'] = f'viewport_state_failed:{type(exc).__name__}'
        return evidence


def atspi_mapped_pointer_activate(element: Dict) -> Dict[str, object]:
    """Activate one exact bound object at the center of its live AT-SPI extent."""
    evidence: Dict[str, object] = {
        'ok': False,
        'atspi_object_bound': False,
        'live_extent_resolved': False,
        'display_geometry_resolved': False,
        'live_extent_in_viewport': False,
        'pointer_event_sent': False,
    }
    obj = element.get('atspi_obj')
    if not obj or is_defunct(element):
        evidence['error'] = 'missing_or_defunct_atspi_object'
        return evidence
    evidence['atspi_object_bound'] = True
    try:
        component = obj.get_component_iface()
        if component is None:
            evidence['error'] = 'missing_component_iface'
            return evidence
        rect = component.get_extents(Atspi.CoordType.SCREEN)
        if (
            rect is None
            or rect.width <= 0
            or rect.height <= 0
        ):
            evidence['error'] = 'invalid_live_extent'
            return evidence
        evidence['live_extent_resolved'] = True
        display_width, display_height = inp.display_geometry()
        evidence['display_geometry_resolved'] = True
        if (
            rect.x < 0
            or rect.y < 0
            or rect.x + rect.width > display_width
            or rect.y + rect.height > display_height
        ):
            evidence['error'] = 'live_extent_outside_display'
            return evidence
        evidence['live_extent_in_viewport'] = True
        sent = inp.click_at(
            rect.x + rect.width // 2,
            rect.y + rect.height // 2,
        )
        evidence['pointer_event_sent'] = bool(sent)
    except Exception as exc:
        evidence['error'] = f'pointer_event_failed:{type(exc).__name__}'
        return evidence
    if evidence['pointer_event_sent'] is not True:
        evidence['error'] = 'pointer_event_returned_false'
        return evidence
    evidence['ok'] = True
    return evidence


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


def atspi_activate(element: Dict) -> bool:
    obj = element.get('atspi_obj')
    if is_defunct(element):
        return False
    try:
        action = obj.get_action_iface()
        if not action or action.get_n_actions() <= 0:
            return False
        for index in range(action.get_n_actions()):
            if action.get_action_name(index) == 'activate':
                return bool(action.do_action(index))
        return bool(action.do_action(0))
    except Exception:
        return False
