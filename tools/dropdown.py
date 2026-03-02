"""
taey_select_dropdown, taey_prepare - Dropdown opening and capabilities.

Opens dropdown menus and returns found items for Claude to pick from.
Claude is the intelligence - no matching logic in tool code.

Dropdown option tracking:
- When a dropdown is opened, compares found items against YAML capabilities
- Flags new items (in dropdown but not in YAML) and missing items
  (in YAML but not in dropdown)
- Gemini decides what the changes mean - no thresholds, no special cases
"""

import json
import os
import time
import logging
from typing import Any, Dict, List

import yaml

from core import atspi, input as inp
from core.tree import find_menu_items
from core.atspi_interact import extend_cache

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

logger = logging.getLogger(__name__)


def _click_trigger_via_atspi(doc, trigger_name: str, max_depth: int = 25) -> bool:
    """Find a button by name in AT-SPI tree and click via do_action(0).

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


def _compare_dropdown_to_yaml(platform: str,
                              dropdown_items: List[Dict]) -> Dict[str, Any] | None:
    """Compare dropdown items against YAML capabilities.

    Checks all capability lists (models, tools, modes, sources) to find
    items that exist in the dropdown but not in YAML (new) or in YAML
    but not in the dropdown (missing).

    Returns a dict with comparison results, or None if YAML can't be loaded
    or there are no differences.
    """
    try:
        config = _load_platform_yaml(platform)
    except (FileNotFoundError, ValueError) as e:
        logger.debug(f"Could not load YAML for comparison: {e}")
        return None

    caps = config.get('capabilities', {})

    # Build a set of all known capability names (lowercased for comparison)
    known_names = set()
    capability_lists = {}
    for cap_type in ('models', 'tools', 'modes', 'sources'):
        items = caps.get(cap_type, [])
        capability_lists[cap_type] = items
        for item in items:
            known_names.add(item.lower())

    # Get dropdown item names (lowercased for comparison)
    dropdown_names = set()
    dropdown_name_original = {}  # lowercase -> original case
    for item in dropdown_items:
        name = item.get('name', '').strip()
        if name:
            lower = name.lower()
            dropdown_names.add(lower)
            dropdown_name_original[lower] = name

    # Find items in dropdown that aren't in any YAML capability list
    new_items = []
    for lower_name in sorted(dropdown_names - known_names):
        original = dropdown_name_original.get(lower_name, lower_name)
        new_items.append(original)

    # Find items in YAML capabilities that aren't in the dropdown
    missing_items = []
    for lower_name in sorted(known_names - dropdown_names):
        # Find original-case name from capabilities
        for cap_type, items in capability_lists.items():
            for item in items:
                if item.lower() == lower_name:
                    missing_items.append(item)
                    break
            else:
                continue
            break

    if not new_items and not missing_items:
        return None

    result = {}
    if new_items:
        result['new_items'] = new_items
        result['new_count'] = len(new_items)
    if missing_items:
        result['missing_items'] = missing_items
        result['missing_count'] = len(missing_items)
    result['known_capabilities'] = {k: v for k, v in capability_lists.items() if v}

    return result


def handle_select_dropdown(platform: str, dropdown: str,
                           target_value: str,
                           redis_client) -> Dict[str, Any]:
    """Open a dropdown and return found items for Claude to pick from.

    1. Click dropdown trigger via AT-SPI tree search (primary)
    2. Scan AT-SPI tree for menu items
    3. Compare items against YAML capabilities (flag new/missing)
    4. Return all items with names, roles, coordinates, states

    NO matching logic. NO auto-clicking items. NO validation.
    Claude reads the items, picks the right one, clicks via taey_click.
    """
    # Switch to platform tab first
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}

    # Primary: AT-SPI tree search for dropdown trigger button
    trigger_clicked = False
    firefox = atspi.find_firefox()
    if firefox:
        doc = atspi.get_platform_document(firefox, platform)
        if doc:
            trigger_clicked = _click_trigger_via_atspi(doc, dropdown)

    if not trigger_clicked:
        return {
            "error": f"Failed to click dropdown trigger '{dropdown}' via AT-SPI tree search.",
            "platform": platform,
            "hint": "The trigger button may not be visible. Try taey_inspect to verify screen state.",
        }

    time.sleep(0.5)

    # Find dropdown items
    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found"}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document"}

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

    result = {
        "platform": platform,
        "dropdown": dropdown,
        "target_requested": target_value,
        "items": items,
        "instruction": "Dropdown is OPEN. Review items, pick the correct one, click with taey_click.",
    }

    # Compare dropdown items against YAML capabilities
    capability_diff = _compare_dropdown_to_yaml(platform, items)
    if capability_diff:
        result['capability_changes'] = capability_diff
        logger.warning(
            f"Dropdown capability changes on {platform}/{dropdown}: "
            f"new={capability_diff.get('new_items', [])}, "
            f"missing={capability_diff.get('missing_items', [])}"
        )

    return result


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
