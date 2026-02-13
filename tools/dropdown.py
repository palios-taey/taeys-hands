"""
taey_select_dropdown, taey_prepare - Dropdown selection and capabilities.

Handles model/mode selection via dropdown menus and returns
platform capabilities for planning.
"""

import json
import os
import time
import logging
from typing import Any, Dict

import yaml

from core import atspi, input as inp
from core.tree import find_elements, find_dropdown_menus
from tools.interact import handle_click

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

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

    # Find dropdown items - search for MENU elements specifically,
    # not all page elements (which returns marketing text, page content, etc.)
    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found", "success": False}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document", "success": False}

    # Primary: find active menu elements (dropdowns render as separate AT-SPI menus)
    menu_items = find_dropdown_menus(firefox, doc)

    # Fallback: scan document for actionable elements if no menu found
    if not menu_items:
        elements = find_elements(doc)
        actionable_roles = ('menu item', 'radio button', 'radio menu item',
                            'push button', 'toggle button', 'check menu item')
        menu_items = [e for e in elements if e.get('role', '') in actionable_roles]

    # Search for target in menu items
    target_lower = target_value.lower()
    target_option = None
    candidates = []

    for e in menu_items:
        name = (e.get('name') or '').lower()
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


def _load_platform_yaml(platform: str) -> Dict:
    """Load platform YAML config. Returns empty dict on failure."""
    yaml_path = os.path.join(PLATFORMS_DIR, f'{platform}.yaml')
    if not os.path.exists(yaml_path):
        return {}
    try:
        with open(yaml_path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load {yaml_path}: {e}")
        return {}


def handle_prepare(platform: str, redis_client) -> Dict[str, Any]:
    """Get available options for a platform before creating a plan.

    Reads from platform YAML config files (source of truth for capabilities).
    These are manually maintained with accurate, current model/mode/tool names.

    Args:
        platform: Which platform.
        redis_client: Redis client.

    Returns:
        Available options including models, modes, tools, quirks, and mode guidance.
    """
    config = _load_platform_yaml(platform)
    caps = config.get('capabilities', {})
    guidance = config.get('mode_guidance', {})

    return {
        "success": True,
        "platform": platform,
        "models": caps.get('models', []),
        "modes": caps.get('modes', []),
        "tools": caps.get('tools', []),
        "sources": caps.get('sources', []),
        "quirks": config.get('quirks', []),
        "mode_guidance": guidance,
        "element_hints": config.get('element_hints', {}),
        "note": "These are from platform YAML configs. Use EXACTLY these names when selecting models/modes.",
    }
