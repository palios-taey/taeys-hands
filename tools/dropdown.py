"""
taey_select_dropdown, taey_prepare - Dropdown opening and capabilities.

Opens dropdown menus and returns found items for Claude to pick from.
Claude is the intelligence - no matching logic in tool code.

Dropdown baseline tracking:
- First time a dropdown is opened: items become the baseline (stored in Redis)
- Subsequent opens: compares current items against baseline
- Flags new items (not in baseline) and missing items (in baseline but gone)
- Claude decides what the changes mean - no thresholds, no special cases
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
from tools.interact import handle_click
from storage.redis_pool import node_key

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


def _check_dropdown_baseline(platform: str, dropdown_name: str,
                             dropdown_items: List[Dict],
                             redis_client) -> Dict[str, Any] | None:
    """Compare dropdown items against stored baseline.

    First call for a platform+dropdown: stores current items as baseline
    in Redis (no comparison, returns None).

    Subsequent calls: compares current items against stored baseline.
    Flags new items and missing items.

    Returns a dict with comparison results, or None if this is the
    first time (baseline just stored) or no differences found.
    """
    if not redis_client:
        return None

    baseline_key = node_key(f"dropdown_baseline:{platform}:{dropdown_name}")

    # Get current item names
    current_names = set()
    current_name_original = {}  # lowercase -> original case
    for item in dropdown_items:
        name = item.get('name', '').strip()
        if name:
            lower = name.lower()
            current_names.add(lower)
            current_name_original[lower] = name

    # Load stored baseline
    stored_json = redis_client.get(baseline_key)

    if stored_json is None:
        # First time seeing this dropdown - store baseline, no comparison
        redis_client.set(baseline_key, json.dumps(sorted(current_names)))
        logger.info(
            f"Dropdown baseline stored for {platform}/{dropdown_name}: "
            f"{len(current_names)} items"
        )
        return None

    try:
        stored_names = set(json.loads(stored_json))
    except (json.JSONDecodeError, TypeError):
        return None

    # Compare
    new_items = [current_name_original[n] for n in sorted(current_names - stored_names)]
    missing_items = sorted(stored_names - current_names)

    if not new_items and not missing_items:
        return None

    result = {}
    if new_items:
        result['new_items'] = new_items
        result['new_count'] = len(new_items)
    if missing_items:
        result['missing_items'] = missing_items
        result['missing_count'] = len(missing_items)

    return result


def handle_select_dropdown(platform: str, dropdown: str,
                           target_value: str,
                           redis_client) -> Dict[str, Any]:
    """Open a dropdown and return found items for Claude to pick from.

    1. Find trigger button via AT-SPI tree search
    2. Click via handle_click (platform-aware: xdotool for non-Gemini,
       AT-SPI for Gemini)
    3. If handle_click fails, fall back to AT-SPI do_action by name
    4. Compare items against baseline (flag new/missing)
    5. Return all items with names, roles, coordinates, states

    NO matching logic. NO auto-clicking items. NO validation.
    Claude reads the items, picks the right one, clicks via taey_click.
    """
    # Dismiss any stale menus/popups before operating
    inp.press_key('Escape')
    time.sleep(0.2)

    # Find trigger button coordinates via AT-SPI tree
    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}

    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found"}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document"}

    # Strategy: AT-SPI do_action FIRST (most reliable for opening dropdowns),
    # then coordinate click via handle_click as fallback.
    # AT-SPI do_action triggers the element's default action via D-Bus,
    # bypassing X11 coordinate issues that cause Firefox context menus.
    menu_items = []

    # Primary: AT-SPI do_action directly on named button
    trigger_clicked = _click_trigger_via_atspi(doc, dropdown)
    if trigger_clicked:
        time.sleep(0.5)
        firefox = atspi.find_firefox()
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        if doc:
            menu_items = find_menu_items(firefox, doc)

    # Fallback: coordinate click via platform-aware handle_click
    if not menu_items:
        trigger_info = _get_trigger_coords(doc or atspi.get_platform_document(
            atspi.find_firefox(), platform), dropdown)
        if trigger_info:
            # Dismiss any stale menu from failed AT-SPI attempt
            if trigger_clicked:
                inp.press_key('Escape')
                time.sleep(0.3)
            click_result = handle_click(platform, trigger_info['x'], trigger_info['y'])
            if click_result.get("error"):
                logger.warning(f"handle_click also failed for {dropdown}: {click_result.get('error')}")
            else:
                time.sleep(0.5)
                firefox = atspi.find_firefox()
                doc = atspi.get_platform_document(firefox, platform) if firefox else None
                if doc:
                    menu_items = find_menu_items(firefox, doc)
        elif not trigger_clicked:
            return {
                "error": f"Failed to find dropdown trigger '{dropdown}' in AT-SPI tree.",
                "platform": platform,
                "hint": "The trigger button may not be visible. Try taey_inspect to verify screen state.",
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
        "item_count": len(items),
        "instruction": "Dropdown is OPEN. Review items, pick the correct one, click with taey_click.",
    }

    # Compare dropdown items against Redis baseline (flag new/missing)
    baseline_diff = _check_dropdown_baseline(platform, dropdown, items, redis_client)
    if baseline_diff:
        result['dropdown_changes'] = baseline_diff
        logger.warning(
            f"Dropdown changes on {platform}/{dropdown}: "
            f"new={baseline_diff.get('new_items', [])}, "
            f"missing={baseline_diff.get('missing_items', [])}"
        )

    # Compare dropdown items against YAML capabilities (flag stale config)
    yaml_diff = _check_yaml_mismatch(platform, dropdown, items)
    if yaml_diff:
        result['yaml_mismatch'] = yaml_diff
        # Make mismatch highly visible — override instruction to force attention
        live_only = yaml_diff.get('live_only', [])
        yaml_only = yaml_diff.get('yaml_only', [])
        mismatch_msg = (
            f"ACTION REQUIRED: Platform YAML is out of sync with live dropdown.\n"
            f"  Live items not in YAML: {live_only}\n"
            f"  YAML items not found live: {yaml_only}\n"
            f"  Update platforms/{platform}.yaml to match live state before proceeding."
        )
        result['instruction'] = mismatch_msg
        logger.warning(
            f"YAML mismatch on {platform}/{dropdown}: "
            f"live_only={live_only}, yaml_only={yaml_only}"
        )

    return result


def _check_yaml_mismatch(platform: str, dropdown_name: str,
                         dropdown_items: List[Dict]) -> Dict[str, Any] | None:
    """Compare live dropdown items against YAML capabilities.

    Uses case-insensitive substring matching since AT-SPI names
    may differ slightly from YAML (e.g. "Deep research New" vs
    "Deep research").

    Returns dict with live_only and yaml_only lists, or None if matched.
    """
    try:
        config = _load_platform_yaml(platform)
    except (FileNotFoundError, ValueError):
        return None

    caps = config.get('capabilities', {})

    # Map dropdown name to YAML capability key
    yaml_key_map = {
        'model': 'models',
        'models': 'models',
        'mode': 'modes',
        'modes': 'modes',
        'tool': 'tools',
        'tools': 'tools',
        'source': 'sources',
        'sources': 'sources',
    }
    yaml_key = yaml_key_map.get(dropdown_name.lower())
    if not yaml_key:
        # Check attach_menu
        if 'attach' in dropdown_name.lower():
            yaml_items = caps.get('attach_menu', [])
        # Check for tool-like dropdown names (e.g. "Add files or tools")
        elif 'tool' in dropdown_name.lower() or 'file' in dropdown_name.lower():
            yaml_items = caps.get('tools', [])
        else:
            return None
    else:
        yaml_items = caps.get(yaml_key, [])

    if not yaml_items:
        return None

    # Normalize: lowercase, strip whitespace
    live_names = set()
    for item in dropdown_items:
        name = item.get('name', '').strip().lower()
        if name:
            live_names.add(name)

    yaml_names = set()
    for item in yaml_items:
        name = str(item).strip().lower()
        if name:
            yaml_names.add(name)

    # Exact matching: drift must be explicit, not hidden by substring overlap
    matched = live_names & yaml_names
    live_only = sorted(live_names - matched)
    yaml_only = sorted(yaml_names - matched)

    if not live_only and not yaml_only:
        return None

    result = {}
    if live_only:
        result['live_only'] = live_only
        result['live_only_count'] = len(live_only)
    if yaml_only:
        result['yaml_only'] = yaml_only
        result['yaml_only_count'] = len(yaml_only)
    result['WARNING'] = (
        'Platform YAML is out of sync with live dropdown. '
        'Update platforms/*.yaml to match live state before selecting.'
    )
    return result


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
