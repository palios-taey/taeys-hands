"""
taey_set_map, taey_click, taey_click_at - Control map and clicking.

Stores interpreted control coordinates and provides click operations.
Uses AT-SPI do_action(0) as primary click method with xdotool fallback.
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

    Args:
        platform: Which platform these controls are for.
        controls: Dict of control names to {x, y} coordinates.
        redis_client: Redis client.

    Returns:
        Success/failure with stored control names.
    """
    if not redis_client:
        return {"error": "Redis not available", "success": False}

    for key, coord in controls.items():
        if 'x' not in coord or 'y' not in coord:
            return {"error": f"Control '{key}' missing x or y", "success": False}

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
        "success": True,
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

    Tries AT-SPI do_action(0) first via cached element lookup,
    falls back to xdotool coordinate click.

    Args:
        platform: Which platform.
        target: Control name (input, send, attach, model, mode, copy).
        redis_client: Redis client.

    Returns:
        Success/failure with click coordinates and method used.
    """
    map_data = get_map(platform, redis_client)
    if not map_data:
        return {
            "error": f"No current map for {platform}. Run taey_inspect + taey_set_map first.",
            "success": False,
        }

    controls = map_data.get('controls', {})
    if target not in controls:
        return {
            "error": f"Control '{target}' not found in {platform} map",
            "available": list(controls.keys()),
            "success": False,
        }

    coord = controls[target]
    x, y = coord['x'], coord['y']

    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab", "success": False}

    # Try AT-SPI click first via cached element lookup
    element = find_element_at(platform, x, y)
    if element:
        if atspi_click(element):
            time.sleep(0.2)
            return {
                "success": True,
                "platform": platform,
                "target": target,
                "clicked_at": {"x": x, "y": y},
                "method": "atspi",
            }

    # Fallback to xdotool coordinate click
    if not inp.click_at(x, y):
        return {"error": f"Click at ({x}, {y}) failed", "success": False}

    time.sleep(0.2)
    return {
        "success": True,
        "platform": platform,
        "target": target,
        "clicked_at": {"x": x, "y": y},
        "method": "xdotool",
    }


def handle_click_at(platform: str, x: int, y: int) -> Dict[str, Any]:
    """Click at specific screen coordinates.

    Tries AT-SPI do_action(0) first via cached element lookup,
    falls back to xdotool coordinate click.

    Args:
        platform: Which platform (for tab switching).
        x: X coordinate.
        y: Y coordinate.

    Returns:
        Success/failure with method used.
    """
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab", "success": False}

    # Try AT-SPI click first via cached element lookup
    element = find_element_at(platform, x, y)
    if element:
        if atspi_click(element):
            time.sleep(0.3)
            return {
                "success": True,
                "platform": platform,
                "clicked_at": {"x": x, "y": y},
                "method": "atspi",
            }

    # Fallback to xdotool coordinate click
    if not inp.click_at(x, y):
        return {"error": f"Click at ({x}, {y}) failed", "success": False}

    time.sleep(0.3)
    return {
        "success": True,
        "platform": platform,
        "clicked_at": {"x": x, "y": y},
        "method": "xdotool",
    }
