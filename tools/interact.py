"""
taey_set_map, taey_click, taey_click_at - Control map and clicking.

Stores interpreted control coordinates and provides click operations.
Uses xdotool coordinate click as primary (generates real pointer events)
with AT-SPI do_action(0) as fallback for specific platforms (Gemini).

CRITICAL: AT-SPI do_action(0) returns True on ChatGPT/Grok buttons
without actually triggering the React event handlers. Only real pointer
events (xdotool mousemove+click) reliably open dropdowns on these platforms.
"""

import json
import time
import logging
from typing import Any, Dict, Optional

from core import input as inp
from core.atspi_interact import find_element_at, atspi_click

logger = logging.getLogger(__name__)


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

    redis_client.setex("taey:v4:current_map", 1800, json.dumps({
        'platform': platform,
        'controls': controls,
        'timestamp': time.time(),
    }))

    redis_client.setex(f"taey:checkpoint:{platform}:set_map", 1800, json.dumps({
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
    data = redis_client.get("taey:v4:current_map")
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

    xdotool coordinate click is primary. AT-SPI do_action is fallback
    (useful for Gemini where xdotool sometimes fails).

    Returns what happened. Claude verifies by inspecting.
    """
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}

    # xdotool coordinate click is PRIMARY
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
