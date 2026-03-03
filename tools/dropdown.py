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
from storage.redis_pool import node_key

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

    # Always update baseline with current state
    redis_client.set(baseline_key, json.dumps(sorted(current_names)))

    if stored_json is None:
        # First time seeing this dropdown - baseline stored, no comparison
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

    1. Click dropdown trigger via AT-SPI tree search (primary)
    2. Scan AT-SPI tree for menu items
    3. Compare items against baseline (flag new/missing)
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

    # Compare dropdown items against baseline (first call stores, subsequent compare)
    baseline_diff = _check_dropdown_baseline(platform, dropdown, items, redis_client)
    if baseline_diff:
        result['dropdown_changes'] = baseline_diff
        logger.warning(
            f"Dropdown changes on {platform}/{dropdown}: "
            f"new={baseline_diff.get('new_items', [])}, "
            f"missing={baseline_diff.get('missing_items', [])}"
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
