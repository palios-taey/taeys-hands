"""
taey_select_dropdown, taey_prepare - Dropdown opening and capabilities.

Opens dropdown menus and returns found items for Claude to pick from.
Claude is the intelligence - no matching logic in tool code.
"""

import os
import time
import logging
from typing import Any, Dict

import yaml

from core import atspi, input as inp
from core.tree import find_menu_items
from core.atspi_interact import extend_cache

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


def _get_trigger_coords(doc, trigger_name: str, max_depth: int = 25) -> Dict | None:
    """Find a button by name in AT-SPI tree and return its center coordinates.

    Returns dict with x, y, name, role if found, None otherwise.
    Used as coordinate click fallback when do_action doesn't open the dropdown.
    """
    trigger_lower = trigger_name.lower()

    def find_button(obj, depth=0):
        if depth > max_depth:
            return None
        try:
            name = (obj.get_name() or '').lower()
            role = obj.get_role_name() or ''
            if trigger_lower in name and 'button' in role:
                comp = obj.get_component_iface()
                if comp:
                    import gi
                    gi.require_version('Atspi', '2.0')
                    from gi.repository import Atspi as _Atspi
                    rect = comp.get_extents(_Atspi.CoordType.SCREEN)
                    if rect and rect.width > 0 and rect.height > 0:
                        return {
                            'x': rect.x + rect.width // 2,
                            'y': rect.y + rect.height // 2,
                            'name': obj.get_name() or '',
                            'role': role,
                        }
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child:
                    result = find_button(child, depth + 1)
                    if result:
                        return result
        except Exception:
            pass
        return None

    return find_button(doc)


def handle_select_dropdown(platform: str, dropdown: str,
                           target_value: str,
                           redis_client) -> Dict[str, Any]:
    """Open a dropdown and return found items for Claude to pick from.

    1. Switch to platform tab
    2. Click dropdown trigger via AT-SPI do_action (primary)
    3. If no items found, fall back to coordinate click
    4. Return all items with names, roles, coordinates, states

    NO matching logic. NO auto-clicking items. NO validation.
    Claude reads the items, picks the right one, clicks via taey_click.
    """
    # Switch to platform tab first
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}

    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found"}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document"}

    # Get trigger coordinates (needed for fallback)
    trigger_info = _get_trigger_coords(doc, dropdown)

    # Primary: AT-SPI do_action(0) on trigger button
    trigger_clicked = _click_trigger_via_atspi(doc, dropdown)

    if not trigger_clicked and not trigger_info:
        return {
            "error": f"Failed to find dropdown trigger '{dropdown}' in AT-SPI tree.",
            "platform": platform,
            "hint": "The trigger button may not be visible. Try taey_inspect to verify screen state.",
        }

    if trigger_clicked:
        time.sleep(0.5)

    # Scan for menu items
    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found after click"}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document after click"}

    menu_items = find_menu_items(firefox, doc)

    # Fallback: coordinate click if do_action didn't open anything
    if not menu_items and trigger_info:
        logger.info(f"AT-SPI do_action found no items, falling back to coordinate click")
        inp.click_at(trigger_info['x'], trigger_info['y'])
        time.sleep(0.5)

        firefox = atspi.find_firefox()
        if firefox:
            doc = atspi.get_platform_document(firefox, platform)
            if doc:
                menu_items = find_menu_items(firefox, doc)

    # Cache menu items so taey_click can use AT-SPI do_action
    if menu_items:
        extend_cache(platform, menu_items)

    if not menu_items:
        return {
            "error": f"Dropdown '{dropdown}' did not open - no menu items found after clicking trigger.",
            "platform": platform,
            "hint": "The trigger click may not have worked. Try taey_inspect to verify screen state.",
        }

    # Return items - strip atspi_obj (D-Bus proxies can't serialize)
    items = []
    for e in menu_items:
        items.append({
            'name': e.get('name', ''),
            'role': e.get('role', ''),
            'x': e.get('x'),
            'y': e.get('y'),
            'states': e.get('states', []),
        })

    return {
        "platform": platform,
        "dropdown": dropdown,
        "target_requested": target_value,
        "items": items,
        "item_count": len(items),
        "instruction": "Dropdown is OPEN. Review items, pick the correct one, click with taey_click.",
    }


def _load_platform_yaml(platform: str) -> Dict:
    """Load platform YAML config."""
    yaml_path = os.path.join(PLATFORMS_DIR, f'{platform}.yaml')
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"Platform YAML not found: {yaml_path}")
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    if not data:
        raise ValueError(f"Platform YAML is empty: {yaml_path}")
    return data


def handle_prepare(platform: str, redis_client) -> Dict[str, Any]:
    """Get available options for a platform before creating a plan.

    Reads from platform YAML config files (source of truth for capabilities).
    """
    try:
        config = _load_platform_yaml(platform)
    except (FileNotFoundError, ValueError) as e:
        return {"error": str(e), "platform": platform}
    caps = config.get('capabilities', {})
    guidance = config.get('mode_guidance', {})

    return {
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
