"""taey_click - Coordinate-based clicking with platform-aware strategy."""

import time
import logging
from typing import Any, Dict, Optional

from core import atspi, input as inp
from core.config import get_click_strategy
from core.interact import find_element_at, atspi_click, cache_elements
from core.tree import find_elements

logger = logging.getLogger(__name__)

_CLICKABLE_ROLES = {
    'push button', 'toggle button', 'link', 'entry',
    'check menu item', 'menu item', 'radio menu item',
}


def _fresh_atspi_find(platform: str, x: int, y: int, tolerance: int = 30) -> Optional[Dict]:
    """Fresh AT-SPI scan to find clickable element near (x, y)."""
    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        return None
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return None
    all_elements = find_elements(doc)
    if not all_elements:
        return None
    cache_elements(platform, all_elements)

    best, best_dist = None, float('inf')
    for e in all_elements:
        if not e.get('atspi_obj') or e.get('role', '') not in _CLICKABLE_ROLES:
            continue
        dist = abs(int(e.get('x', 0)) - x) + abs(int(e.get('y', 0)) - y)
        if dist < best_dist and dist <= tolerance:
            best, best_dist = e, dist
    return best


def _click_atspi_first(platform: str, x: int, y: int) -> Dict[str, Any]:
    element = find_element_at(platform, x, y)
    if element and atspi_click(element):
        time.sleep(0.3)
        return {"platform": platform, "clicked_at": {"x": x, "y": y}, "method": "atspi"}

    element = _fresh_atspi_find(platform, x, y)
    if element and atspi_click(element):
        time.sleep(0.3)
        return {"platform": platform, "clicked_at": {"x": x, "y": y}, "method": "atspi_fresh"}

    if inp.click_at(x, y):
        time.sleep(0.3)
        return {"platform": platform, "clicked_at": {"x": x, "y": y}, "method": "xdotool"}
    return {"error": f"Click at ({x},{y}) failed via AT-SPI and xdotool"}


def _click_xdotool_first(platform: str, x: int, y: int) -> Dict[str, Any]:
    if inp.click_at(x, y):
        time.sleep(0.3)
        return {"platform": platform, "clicked_at": {"x": x, "y": y}, "method": "xdotool"}

    element = find_element_at(platform, x, y)
    if element and atspi_click(element):
        time.sleep(0.3)
        return {"platform": platform, "clicked_at": {"x": x, "y": y}, "method": "atspi"}
    return {"error": f"Click at ({x},{y}) failed via xdotool and AT-SPI"}


def handle_click(platform: str, x: int, y: int) -> Dict[str, Any]:
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}
    strategy = get_click_strategy(platform)
    if strategy == 'atspi_first':
        return _click_atspi_first(platform, x, y)
    return _click_xdotool_first(platform, x, y)
