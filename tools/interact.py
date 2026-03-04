"""
taey_click - Coordinate-based clicking.

Click strategy is platform-aware:
- Gemini: AT-SPI do_action first (xdotool coordinate clicks unreliable)
- ChatGPT/Grok/others: xdotool first (AT-SPI do_action lies - returns True
  without actually triggering React event handlers)
"""

import time
import logging
from typing import Any, Dict, Optional

from core import atspi, input as inp
from core.atspi_interact import find_element_at, atspi_click, cache_elements
from core.tree import find_elements

logger = logging.getLogger(__name__)


_CLICKABLE_ROLES = {
    'push button', 'toggle button', 'link', 'entry',
    'check menu item', 'menu item', 'radio menu item',
}


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


def handle_click(platform: str, x: int, y: int) -> Dict[str, Any]:
    """Click at specific screen coordinates.

    Strategy is platform-aware:
    - Gemini: AT-SPI do_action first (xdotool coordinate clicks unreliable)
    - Others: xdotool first (AT-SPI do_action lies on React)

    Returns what happened. Claude verifies by inspecting.
    """
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}

    # Gemini: AT-SPI do_action is more reliable than xdotool coordinates
    if platform == 'gemini':
        element = find_element_at(platform, x, y)
        if element and atspi_click(element):
            time.sleep(0.3)
            return {
                "platform": platform,
                "clicked_at": {"x": x, "y": y},
                "method": "atspi",
            }

        # Cache miss — fresh AT-SPI tree scan (still AT-SPI, not xdotool)
        logger.info(f"Gemini cache miss at ({x},{y}), doing fresh AT-SPI scan")
        element = _fresh_atspi_find(platform, x, y)
        if element and atspi_click(element):
            time.sleep(0.3)
            return {
                "platform": platform,
                "clicked_at": {"x": x, "y": y},
                "method": "atspi_fresh",
            }

        # xdotool last resort for Gemini
        logger.warning(f"Gemini fresh AT-SPI also missed at ({x},{y}), trying xdotool")
        if inp.click_at(x, y):
            time.sleep(0.3)
            return {
                "platform": platform,
                "clicked_at": {"x": x, "y": y},
                "method": "xdotool",
            }
        return {"error": f"Click at ({x}, {y}) failed via AT-SPI (cached+fresh) and xdotool"}

    # Other platforms: xdotool coordinate click is PRIMARY
    if inp.click_at(x, y):
        time.sleep(0.3)
        return {
            "platform": platform,
            "clicked_at": {"x": x, "y": y},
            "method": "xdotool",
        }

    # AT-SPI fallback for non-Gemini
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
