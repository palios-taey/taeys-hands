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
from core.atspi_interact import atspi_click
from tools.interact import handle_click

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

logger = logging.getLogger(__name__)


def _click_trigger_via_atspi(doc, trigger_name: str, max_depth: int = 25) -> bool:
    """Find a button by name in AT-SPI tree and click via do_action(0).

    More reliable than xdotool coordinates for platforms like Gemini.
    Returns True if the action was performed.
    """
    trigger_lower = trigger_name.lower()

    def find_and_click(obj, depth=0):
        if depth > max_depth:
            return False
        try:
            name = (obj.get_name() or '').lower()
            role = obj.get_role_name() or ''
            if trigger_lower in name and 'button' in role:
                action = obj.get_action_iface()
                if action and action.get_n_actions() > 0:
                    action.do_action(0)
                    return True
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child and find_and_click(child, depth + 1):
                    return True
        except Exception:
            pass
        return False

    return find_and_click(doc)


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
    # Click dropdown trigger - prefer AT-SPI do_action(0) over xdotool coordinates
    # (Gemini and others may not respond to xdotool clicks on their buttons)
    trigger_clicked = False
    firefox = atspi.find_firefox()
    if firefox:
        doc = atspi.get_platform_document(firefox, platform)
        if doc:
            trigger_clicked = _click_trigger_via_atspi(doc, dropdown)

    if not trigger_clicked:
        # Fallback to coordinate click from stored map
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

    # Click target - AT-SPI do_action first, xdotool fallback
    x, y = target_option['x'], target_option['y']
    click_method = 'xdotool'

    if target_option.get('atspi_obj'):
        if atspi_click(target_option):
            click_method = 'atspi'
        else:
            # AT-SPI failed, fall back to xdotool
            if not inp.click_at(x, y):
                return {"error": "Failed to click option", "success": False}
    else:
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

    if not validated:
        # Re-inspect to provide current state for debugging
        current_state = None
        if doc:
            for e in validation_elements:
                name = e.get('name', '')
                states = e.get('states', [])
                if any(s in states for s in ['selected', 'checked', 'pressed', 'focused']):
                    current_state = name
                    break

        return {
            "success": True,  # Click succeeded
            "platform": platform,
            "dropdown": dropdown,
            "selected": target_value,
            "selection_validated": False,
            "clicked_at": {"x": x, "y": y},
            "click_method": click_method,
            "warning": (
                f"Could not validate that '{target_value}' is now active. "
                f"Current detected state: {current_state}. "
                "CALLER MUST re-inspect to verify before proceeding."
            ),
        }

    return {
        "success": True,
        "platform": platform,
        "dropdown": dropdown,
        "selected": target_value,
        "selection_validated": True,
        "clicked_at": {"x": x, "y": y},
        "click_method": click_method,
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
