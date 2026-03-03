"""
taey_select_dropdown, taey_prepare - Dropdown opening and capabilities.

Opens dropdown menus and returns found items for Claude to pick from.
Claude is the intelligence - no matching logic in tool code.

Dropdown option tracking:
- When a dropdown is opened, compares found items against baseline
- Flags new items (in dropdown but not in baseline) and missing items
  (in baseline but not in dropdown)
- Claude decides what the changes mean - no thresholds, no special cases

Context menu detection:
- After AT-SPI do_action(0), checks if the resulting menu is a browser
  context menu (Undo/Redo/Cut/Copy/Paste) instead of the actual dropdown
- If detected, dismisses it and falls back to coordinate click on the
  trigger button's position
"""

import json
import os
import time
import logging
from typing import Any, Dict, List, Optional

import yaml

from core import atspi, input as inp
from core.tree import find_menu_items
from core.atspi_interact import extend_cache

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')
BASELINES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'baselines')

logger = logging.getLogger(__name__)

# Items that indicate the browser's native context menu, not a platform dropdown
_CONTEXT_MENU_ITEMS = {'undo', 'redo', 'cut', 'copy', 'paste', 'delete',
                       'select all', 'select_all'}


def _is_browser_context_menu(menu_items: List[Dict]) -> bool:
    """Check if found menu items are the browser context menu.

    The browser context menu has items like Undo, Redo, Cut, Copy, Paste.
    If a majority of found items match these, it's a context menu, not
    a platform dropdown.

    Returns True if the menu appears to be the browser context menu.
    """
    if not menu_items:
        return False

    context_count = 0
    for item in menu_items:
        name = (item.get('name', '') or '').strip().lower()
        if name in _CONTEXT_MENU_ITEMS:
            context_count += 1

    # If more than half the items are context menu items, it's a context menu
    return context_count > len(menu_items) / 2


def _get_trigger_coords(doc, trigger_name: str, max_depth: int = 25) -> Optional[Dict]:
    """Find a button by name in AT-SPI tree and return its coordinates.

    Returns dict with x, y, name, role if found, None otherwise.
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


def _load_baseline(platform: str) -> Optional[Dict]:
    """Load baseline YAML for a platform.

    Returns the baseline dict, or None if no baseline exists.
    """
    baseline_path = os.path.join(BASELINES_DIR, f'{platform}.yaml')
    if not os.path.exists(baseline_path):
        return None
    try:
        with open(baseline_path) as f:
            data = yaml.safe_load(f)
        return data if data else None
    except Exception as e:
        logger.debug(f"Could not load baseline for {platform}: {e}")
        return None


def _compare_dropdown_to_baseline(platform: str, dropdown_name: str,
                                  dropdown_items: List[Dict]) -> Dict[str, Any] | None:
    """Compare dropdown items against baseline.

    Checks the baseline's stored dropdown contents for this specific
    dropdown. Flags new items and missing items.

    Falls back to comparing against platform YAML capabilities if
    no baseline exists yet.

    Returns a dict with comparison results, or None if no differences.
    """
    baseline = _load_baseline(platform)

    if baseline:
        # Compare against baseline dropdown contents
        stored_dropdowns = baseline.get('dropdowns', {})
        stored_items = stored_dropdowns.get(dropdown_name, {}).get('items', [])

        if stored_items:
            stored_names = set()
            for item in stored_items:
                name = item if isinstance(item, str) else item.get('name', '')
                if name:
                    stored_names.add(name.lower())

            dropdown_names = set()
            dropdown_name_original = {}
            for item in dropdown_items:
                name = item.get('name', '').strip()
                if name:
                    lower = name.lower()
                    dropdown_names.add(lower)
                    dropdown_name_original[lower] = name

            new_items = [dropdown_name_original[n] for n in sorted(dropdown_names - stored_names)]
            missing_items = [n for n in sorted(stored_names - dropdown_names)]

            if not new_items and not missing_items:
                return None

            result = {'baseline_source': 'baseline_yaml'}
            if new_items:
                result['new_items'] = new_items
                result['new_count'] = len(new_items)
            if missing_items:
                result['missing_items'] = missing_items
                result['missing_count'] = len(missing_items)
            return result

    # Fallback: compare against platform YAML capabilities
    try:
        config = _load_platform_yaml(platform)
    except (FileNotFoundError, ValueError) as e:
        logger.debug(f"Could not load YAML for comparison: {e}")
        return None

    caps = config.get('capabilities', {})
    known_names = set()
    capability_lists = {}
    for cap_type in ('models', 'tools', 'modes', 'sources'):
        items = caps.get(cap_type, [])
        capability_lists[cap_type] = items
        for item in items:
            known_names.add(item.lower())

    dropdown_names = set()
    dropdown_name_original = {}
    for item in dropdown_items:
        name = item.get('name', '').strip()
        if name:
            lower = name.lower()
            dropdown_names.add(lower)
            dropdown_name_original[lower] = name

    new_items = [dropdown_name_original[n] for n in sorted(dropdown_names - known_names)]
    missing_items = []
    for lower_name in sorted(known_names - dropdown_names):
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

    result = {'baseline_source': 'platform_yaml_capabilities'}
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
    2. Detect if browser context menu appeared instead of dropdown
    3. If context menu: dismiss, fall back to coordinate click
    4. Scan AT-SPI tree for menu items
    5. Compare items against baseline (flag new/missing)
    6. Return all items with names, roles, coordinates, states

    NO matching logic. NO auto-clicking items. NO validation.
    Claude reads the items, picks the right one, clicks via taey_click.
    """
    # Switch to platform tab first
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}

    # Find dropdown trigger and get its coordinates (needed for fallback)
    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found"}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document"}

    # Get trigger coordinates before clicking (needed for fallback)
    trigger_info = _get_trigger_coords(doc, dropdown)

    # Primary: AT-SPI do_action(0) on trigger button
    trigger_clicked = _click_trigger_via_atspi(doc, dropdown)

    if not trigger_clicked:
        return {
            "error": f"Failed to click dropdown trigger '{dropdown}' via AT-SPI tree search.",
            "platform": platform,
            "hint": "The trigger button may not be visible. Try taey_inspect to verify screen state.",
        }

    time.sleep(0.5)

    # Check if we got a browser context menu instead of the dropdown
    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found after click"}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document after click"}

    menu_items = find_menu_items(firefox, doc)

    if menu_items and _is_browser_context_menu(menu_items):
        # Browser context menu opened instead of dropdown — dismiss and retry
        logger.warning(
            f"Browser context menu detected on {platform}/{dropdown}, "
            f"dismissing and falling back to coordinate click"
        )
        inp.press_key('Escape')
        time.sleep(0.3)

        # Fall back to coordinate click on the trigger button
        if trigger_info:
            inp.click_at(trigger_info['x'], trigger_info['y'])
            time.sleep(0.5)

            # Re-scan for menu items
            firefox = atspi.find_firefox()
            if firefox:
                doc = atspi.get_platform_document(firefox, platform)
                if doc:
                    menu_items = find_menu_items(firefox, doc)

                    # Check again — if still context menu, give up
                    if menu_items and _is_browser_context_menu(menu_items):
                        inp.press_key('Escape')
                        return {
                            "error": f"Dropdown '{dropdown}' opens browser context menu even with coordinate click.",
                            "platform": platform,
                            "trigger_coords": trigger_info,
                            "hint": "The trigger may need a different interaction method. Try taey_inspect.",
                        }
        else:
            return {
                "error": f"Browser context menu detected for '{dropdown}' and no trigger coordinates for fallback.",
                "platform": platform,
                "hint": "Try taey_inspect to find the trigger button coordinates, then use taey_click.",
            }

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

    # Compare dropdown items against baseline
    capability_diff = _compare_dropdown_to_baseline(platform, dropdown, items)
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
