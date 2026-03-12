"""taey_click - Coordinate-based clicking with platform-aware strategy."""

import os
import time
import logging
from typing import Any, Dict, Optional

import yaml

from core import atspi, input as inp
from core.interact import find_element_at, atspi_click, cache_elements
from core.tree import find_elements

logger = logging.getLogger(__name__)

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'platforms')

_CLICKABLE_ROLES = {
    'push button', 'toggle button', 'link', 'entry',
    'check menu item', 'menu item', 'radio menu item',
}

_strategy_cache: Dict[str, str] = {}


def _get_click_strategy(platform: str) -> str:
    if platform in _strategy_cache:
        return _strategy_cache[platform]
    strategy = 'xdotool_first'
    try:
        with open(os.path.join(PLATFORMS_DIR, f'{platform}.yaml')) as f:
            data = yaml.safe_load(f)
        if data and 'click_strategy' in data:
            strategy = data['click_strategy']
    except (FileNotFoundError, yaml.YAMLError):
        pass
    _strategy_cache[platform] = strategy
    return strategy


def _fresh_atspi_find(platform: str, x: int, y: int, tolerance: int = 30) -> Optional[Dict]:
    """Fresh AT-SPI scan to find clickable element near (x, y)."""
    firefox = atspi.find_firefox()
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
        dist = abs(e.get('x', 0) - x) + abs(e.get('y', 0) - y)
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
    strategy = _get_click_strategy(platform)
    if strategy == 'atspi_first':
        return _click_atspi_first(platform, x, y)
    return _click_xdotool_first(platform, x, y)
