"""
taey_select_dropdown, taey_prepare - Dropdown selection and capabilities.

Handles model/mode selection via dropdown menus and returns
platform capabilities for planning.
"""

import json
import time
import logging
from typing import Any, Dict

from core import atspi, input as inp
from core.tree import find_elements
from tools.interact import handle_click

logger = logging.getLogger(__name__)


def handle_select_dropdown(platform: str, dropdown: str,
                           target_value: str,
                           redis_client) -> Dict[str, Any]:
    """Select an item from a dropdown menu.

    1. Click dropdown trigger (model, mode, etc.)
    2. Re-inspect to find dropdown items
    3. Click target option
    4. Re-inspect to validate selection

    Args:
        platform: Which platform.
        dropdown: Which dropdown to open (from map).
        target_value: Value to select.
        redis_client: Redis client.

    Returns:
        Success/failure with validation info.
    """
    # Click dropdown trigger
    click_result = handle_click(platform, dropdown, redis_client)
    if not click_result.get("success"):
        return {"error": f"Failed to click {dropdown}: {click_result.get('error')}", "success": False}

    time.sleep(0.5)

    # Find dropdown items
    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found", "success": False}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document", "success": False}

    elements = find_elements(doc)

    # Search for target
    target_lower = target_value.lower()
    target_option = None
    candidates = []

    actionable_roles = ('menu item', 'radio button', 'push button', 'toggle button', 'check menu item')
    for e in elements:
        name = (e.get('name') or '').lower()
        role = e.get('role', '')
        if role in actionable_roles:
            candidates.append(e)
            if target_lower in name or name in target_lower:
                target_option = e
                break

    if not target_option:
        return {
            "error": f"Could not find '{target_value}' in dropdown",
            "available_options": [{"name": e.get('name'), "role": e.get('role')} for e in candidates[:15]],
            "success": False,
        }

    # Click target
    x, y = target_option['x'], target_option['y']
    if not inp.click_at(x, y):
        return {"error": "Failed to click option", "success": False}

    time.sleep(0.5)

    # Validate selection
    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    validated = False

    if doc:
        validation_elements = find_elements(doc)
        for e in validation_elements:
            name = e.get('name', '')
            states = e.get('states', [])
            if target_lower in name.lower():
                if any(s in states for s in ['selected', 'checked', 'pressed']):
                    validated = True
                elif e.get('role') in ('push button', 'toggle button'):
                    validated = True

    return {
        "success": True,
        "platform": platform,
        "dropdown": dropdown,
        "selected": target_value,
        "selection_validated": validated,
        "clicked_at": {"x": x, "y": y},
    }


def handle_prepare(platform: str, redis_client) -> Dict[str, Any]:
    """Get available options for a platform before creating a plan.

    Returns models, modes, tools, and sources available on the platform.

    Args:
        platform: Which platform.
        redis_client: Redis client (capabilities stored here).

    Returns:
        Available options for the platform.
    """
    caps = {}
    if redis_client:
        caps_json = redis_client.get(f"taey:v4:capabilities:{platform}")
        if caps_json:
            try:
                caps = json.loads(caps_json)
            except json.JSONDecodeError:
                pass

    return {
        "success": True,
        "platform": platform,
        "models": caps.get('models', []),
        "modes": caps.get('modes', []),
        "tools": caps.get('tools', []),
        "sources": caps.get('sources', []),
    }
