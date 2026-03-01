"""
taey_set_map, taey_click, taey_click_at - Control map and clicking.

Stores interpreted control coordinates and provides click operations.
Click strategy is platform-aware:
- Gemini: AT-SPI do_action first (xdotool coordinate clicks unreliable)
- ChatGPT/Grok: xdotool first (AT-SPI do_action lies - returns True
  without actually triggering React event handlers)
- Others: xdotool first, AT-SPI fallback
"""

import json
import time
import logging
from typing import Any, Dict, Optional

from core import atspi, input as inp
from core.atspi_interact import find_element_at, atspi_click, cache_elements
from core.tree import find_elements
from storage.redis_pool import node_key

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


def handle_set_map(platform: str, controls: Dict[str, Dict],
                   redis_client) -> Dict[str, Any]:
    """Store interpreted control coordinates for a platform.

    Maps are ephemeral - only ONE map exists at a time.
    TTL of 30 minutes as safety net.
    """
    if not redis_client:
        return {"error": "Redis not available"}

    for key, coord in controls.items():
        if 'x' not in coord or 'y' not in coord:
            return {"error": f"Control '{key}' missing x or y"}

    redis_client.setex(node_key("current_map"), 1800, json.dumps({
        'platform': platform,
        'controls': controls,
        'timestamp': time.time(),
    }))

    redis_client.setex(node_key(f"checkpoint:{platform}:set_map"), 1800, json.dumps({
        'controls': list(controls.keys()),
        'timestamp': time.time(),
    }))

    return {
        "platform": platform,
        "controls_stored": list(controls.keys()),
    }


def get_map(platform: str, redis_client) -> Optional[Dict]:
    """Get stored control map, validating it matches the requested platform."""
    if not redis_client:
        return None
    data = redis_client.get(node_key("current_map"))
    if data:
        map_data = json.loads(data)
        if map_data.get('platform') == platform:
            return map_data
    return None


def handle_click(platform: str, target: str,
                 redis_client) -> Dict[str, Any]:
    """Click a named control using stored map coordinates.

    Looks up coordinates from map, delegates to handle_click_at.
    """
    map_data = get_map(platform, redis_client)
    if not map_data:
        return {
            "error": f"No current map for {platform}. Run taey_inspect + taey_set_map first.",
        }

    controls = map_data.get('controls', {})
    if target not in controls:
        return {
            "error": f"Control '{target}' not found in {platform} map",
            "available": list(controls.keys()),
        }

    coord = controls[target]
    result = handle_click_at(platform, coord['x'], coord['y'])
    result['target'] = target
    return result


def handle_click_at(platform: str, x: int, y: int) -> Dict[str, Any]:
    """Click at specific screen coordinates.

    Strategy is platform-aware:
    - Gemini: AT-SPI do_action first (xdotool coordinate clicks unreliable)
    - ChatGPT/Grok: xdotool first (AT-SPI do_action lies on React)
    - Others: xdotool first, AT-SPI fallback

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

        # Cache miss — stale D-Bus proxies. Do fresh AT-SPI tree scan
        # instead of falling back to xdotool (which is unreliable on Gemini).
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
