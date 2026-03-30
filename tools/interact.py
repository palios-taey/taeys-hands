"""
taey_click - Coordinate-based clicking.

Click strategy is data-driven via platform YAML `click_strategy` field:
- atspi_first: AT-SPI do_action → fresh AT-SPI scan → xdotool (Gemini)
- xdotool_first: xdotool coordinate click → AT-SPI fallback (ChatGPT, Grok, etc.)
"""

import os
import time
import logging
from typing import Any, Dict, Optional

import yaml

from core import atspi, input as inp
from core.atspi_interact import find_element_at, atspi_click, cache_elements
from core.tree import find_elements

logger = logging.getLogger(__name__)

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'platforms')

_CLICKABLE_ROLES = {
    'push button', 'toggle button', 'link', 'entry',
    'check menu item', 'menu item', 'radio menu item',
}

# Cache loaded click strategies so we don't re-read YAML on every click
_click_strategy_cache: Dict[str, str] = {}


def _get_click_strategy(platform: str) -> str:
    """Read click_strategy from platform YAML. Defaults to xdotool_first."""
    if platform in _click_strategy_cache:
        return _click_strategy_cache[platform]

    yaml_path = os.path.join(PLATFORMS_DIR, f'{platform}.yaml')
    strategy = 'xdotool_first'
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        if data and 'click_strategy' in data:
            strategy = data['click_strategy']
    except (FileNotFoundError, yaml.YAMLError):
        pass

    _click_strategy_cache[platform] = strategy
    return strategy


def _fresh_atspi_find(platform: str, x: int, y: int,
                      tolerance: int = 30) -> Optional[Dict]:
    """Fresh AT-SPI tree scan to find clickable element near (x, y).

    Bypasses stale element cache entirely. Searches the live AT-SPI tree,
    refreshes the cache with fresh elements, and returns the closest match.
    Used when cached D-Bus proxies are defunct (page inactive, DOM changed).
    """
    firefox = atspi.find_firefox()
    if not firefox:
        logger.warning("Fresh AT-SPI scan: Firefox not found")
        return None

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        logger.warning(f"Fresh AT-SPI scan: {platform} document not found")
        return None

    all_elements = find_elements(doc)
    if not all_elements:
        return None

    # Refresh cache with live elements
    cache_elements(platform, all_elements)

    best = None
    best_dist = float('inf')
    for e in all_elements:
        if not e.get('atspi_obj'):
            continue
        role = e.get('role', '')
        if role not in _CLICKABLE_ROLES:
            continue
        dx = abs(e.get('x', 0) - x)
        dy = abs(e.get('y', 0) - y)
        dist = dx + dy
        if dist < best_dist and dist <= tolerance:
            best = e
            best_dist = dist

    if best:
        logger.info(f"Fresh AT-SPI found: '{best.get('name', '')[:50]}' "
                     f"[{best.get('role', '')}] at dist={best_dist}")
    else:
        logger.warning(f"Fresh AT-SPI scan: no clickable element within "
                       f"{tolerance}px of ({x},{y})")
    return best


def _click_atspi_first(platform: str, x: int, y: int) -> Dict[str, Any]:
    """AT-SPI do_action primary, xdotool fallback."""
    element = find_element_at(platform, x, y)
    if element and atspi_click(element):
        time.sleep(0.3)
        return {
            "platform": platform,
            "clicked_at": {"x": x, "y": y},
            "method": "atspi",
        }

    # Cache miss — fresh AT-SPI tree scan
    logger.info(f"AT-SPI cache miss at ({x},{y}), doing fresh scan")
    element = _fresh_atspi_find(platform, x, y)
    if element and atspi_click(element):
        time.sleep(0.3)
        return {
            "platform": platform,
            "clicked_at": {"x": x, "y": y},
            "method": "atspi_fresh",
        }

    # xdotool last resort
    logger.warning(f"Fresh AT-SPI also missed at ({x},{y}), trying xdotool")
    if inp.click_at(x, y):
        time.sleep(0.3)
        return {
            "platform": platform,
            "clicked_at": {"x": x, "y": y},
            "method": "xdotool",
        }
    return {"error": f"Click at ({x}, {y}) failed via AT-SPI (cached+fresh) and xdotool"}


def _click_xdotool_first(platform: str, x: int, y: int) -> Dict[str, Any]:
    """xdotool coordinate click primary, AT-SPI fallback."""
    if inp.click_at(x, y):
        time.sleep(0.3)
        return {
            "platform": platform,
            "clicked_at": {"x": x, "y": y},
            "method": "xdotool",
        }

    # AT-SPI fallback
    logger.warning(f"xdotool click failed at ({x},{y}), trying AT-SPI do_action")
    element = find_element_at(platform, x, y)
    if element and atspi_click(element):
        time.sleep(0.3)
        return {
            "platform": platform,
            "clicked_at": {"x": x, "y": y},
            "method": "atspi",
        }

    return {"error": f"Click at ({x}, {y}) failed via both xdotool and AT-SPI"}


def handle_click(platform: str, x: int, y: int) -> Dict[str, Any]:
    """Click at specific screen coordinates.

    Strategy is read from platform YAML `click_strategy` field:
    - atspi_first: AT-SPI do_action → fresh scan → xdotool
    - xdotool_first: xdotool → AT-SPI fallback

    Returns what happened. Claude verifies by inspecting.
    """
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}

    strategy = _get_click_strategy(platform)

    if strategy == 'atspi_first':
        return _click_atspi_first(platform, x, y)
    else:
        return _click_xdotool_first(platform, x, y)
