"""taey_select_dropdown, taey_prepare - Dropdown opening and capabilities."""

import json
import os
import time
import logging
from typing import Any, Dict, List

import yaml

from core import atspi, input as inp
from core.tree import find_elements, find_menu_items
from core.interact import extend_cache, atspi_click, find_element_at
from tools.click import handle_click
from storage.redis_pool import node_key

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

logger = logging.getLogger(__name__)


def _click_trigger_via_atspi(doc, trigger_name: str, platform: str = None) -> bool:
    """Find button by name in AT-SPI tree and click via do_action."""
    trigger_lower = trigger_name.lower()

    # Check element cache first
    from core.interact import _element_cache
    for e in _element_cache.get(platform, []) if platform else []:
        name = (e.get('name') or '').lower()
        if trigger_lower in name and 'button' in e.get('role', ''):
            if atspi_click(e):
                return True

    if not doc:
        return False

    def find_and_click(obj, depth=0):
        if depth > 25:
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


def _get_trigger_coords(doc, trigger_name: str, platform: str = None) -> Dict | None:
    """Find button by name and return center coordinates."""
    trigger_lower = trigger_name.lower()

    from core.interact import _element_cache
    for e in _element_cache.get(platform, []) if platform else []:
        name = (e.get('name') or '').lower()
        if trigger_lower in name and 'button' in e.get('role', ''):
            return {'x': e.get('x', 0), 'y': e.get('y', 0),
                    'name': e.get('name', ''), 'role': e.get('role', '')}

    if not doc:
        return None

    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi

    def find_button(obj, depth=0):
        if depth > 25:
            return None
        try:
            name = (obj.get_name() or '').lower()
            role = obj.get_role_name() or ''
            if trigger_lower in name and 'button' in role:
                comp = obj.get_component_iface()
                if comp:
                    rect = comp.get_extents(Atspi.CoordType.SCREEN)
                    if rect and rect.width > 0 and rect.height > 0:
                        return {'x': rect.x + rect.width // 2,
                                'y': rect.y + rect.height // 2,
                                'name': obj.get_name() or '', 'role': role}
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child:
                    r = find_button(child, depth + 1)
                    if r:
                        return r
        except Exception:
            pass
        return None

    return find_button(doc)


def _check_dropdown_baseline(platform: str, dropdown_name: str,
                             dropdown_items: List[Dict],
                             redis_client) -> Dict[str, Any] | None:
    """Compare dropdown items against stored baseline. First call stores baseline."""
    if not redis_client:
        return None

    baseline_key = node_key(f"dropdown_baseline:{platform}:{dropdown_name}")
    current_names = set()
    current_original = {}
    for item in dropdown_items:
        name = item.get('name', '').strip()
        if name:
            lower = name.lower()
            current_names.add(lower)
            current_original[lower] = name

    stored_json = redis_client.get(baseline_key)
    if stored_json is None:
        redis_client.set(baseline_key, json.dumps(sorted(current_names)))
        return None

    try:
        stored_names = set(json.loads(stored_json))
    except (json.JSONDecodeError, TypeError):
        return None

    new_items = [current_original[n] for n in sorted(current_names - stored_names)]
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


def _check_yaml_mismatch(platform: str, dropdown_name: str,
                         dropdown_items: List[Dict]) -> Dict[str, Any] | None:
    """Compare live dropdown items against YAML capabilities."""
    try:
        config = _load_platform_yaml(platform)
    except (FileNotFoundError, ValueError):
        return None

    caps = config.get('capabilities', {})
    yaml_key_map = {
        'model': 'models', 'models': 'models',
        'mode': 'modes', 'modes': 'modes',
        'tool': 'tools', 'tools': 'tools',
        'source': 'sources', 'sources': 'sources',
    }
    yaml_key = yaml_key_map.get(dropdown_name.lower())
    if not yaml_key:
        if 'attach' in dropdown_name.lower():
            yaml_items = caps.get('attach_menu', [])
        elif 'tool' in dropdown_name.lower() or 'file' in dropdown_name.lower():
            yaml_items = caps.get('tools', [])
        else:
            return None
    else:
        yaml_items = caps.get(yaml_key, [])

    if not yaml_items:
        return None

    live_names = {item.get('name', '').strip().lower() for item in dropdown_items
                  if item.get('name', '').strip()}
    yaml_names = {str(item).strip().lower() for item in yaml_items if str(item).strip()}

    matched = live_names & yaml_names
    live_only = sorted(live_names - matched)
    yaml_only = sorted(yaml_names - matched)

    if not live_only and not yaml_only:
        return None
    result = {}
    if live_only:
        result['live_only'] = live_only
    if yaml_only:
        result['yaml_only'] = yaml_only
    result['WARNING'] = 'Platform YAML out of sync with live dropdown. Update platforms/*.yaml.'
    return result


def _load_platform_yaml(platform: str) -> Dict:
    yaml_path = os.path.join(PLATFORMS_DIR, f'{platform}.yaml')
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    if not data:
        raise ValueError(f"Platform YAML is empty: {yaml_path}")
    return data


def handle_select_dropdown(platform: str, dropdown: str,
                           target_value: str,
                           redis_client) -> Dict[str, Any]:
    """Open dropdown, return items for Claude to pick from. No auto-selection."""
    inp.press_key('Escape')
    time.sleep(0.2)

    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}

    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found"}
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document"}

    # Primary: AT-SPI do_action on named button
    menu_items = []
    trigger_clicked = _click_trigger_via_atspi(doc, dropdown, platform=platform)
    if trigger_clicked:
        time.sleep(1.0)
        firefox = atspi.find_firefox()
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        if doc:
            menu_items = find_menu_items(firefox, doc)

    # Fallback: coordinate click
    if not menu_items:
        trigger_info = _get_trigger_coords(
            doc or atspi.get_platform_document(atspi.find_firefox(), platform),
            dropdown, platform=platform)
        if trigger_info:
            if trigger_clicked:
                inp.press_key('Escape')
                time.sleep(0.3)
            click_result = handle_click(platform, trigger_info['x'], trigger_info['y'])
            if not click_result.get("error"):
                time.sleep(1.0)
                firefox = atspi.find_firefox()
                doc = atspi.get_platform_document(firefox, platform) if firefox else None
                if doc:
                    menu_items = find_menu_items(firefox, doc)
        elif not trigger_clicked:
            return {"error": f"Failed to find dropdown trigger '{dropdown}' in AT-SPI tree.",
                    "platform": platform,
                    "hint": "Try taey_inspect to verify screen state."}

    if menu_items:
        extend_cache(platform, menu_items)

    if not menu_items:
        return {"error": f"Dropdown '{dropdown}' did not open - no menu items found.",
                "platform": platform,
                "hint": "Try taey_inspect to verify screen state."}

    items = [{'name': e.get('name', ''), 'role': e.get('role', ''),
              'x': e.get('x'), 'y': e.get('y'), 'states': e.get('states', [])}
             for e in menu_items]

    result = {
        "platform": platform, "dropdown": dropdown,
        "target_requested": target_value, "items": items,
        "item_count": len(items),
        "instruction": "Dropdown is OPEN. Review items, pick the correct one, click with taey_click.",
    }

    baseline_diff = _check_dropdown_baseline(platform, dropdown, items, redis_client)
    if baseline_diff:
        result['dropdown_changes'] = baseline_diff

    yaml_diff = _check_yaml_mismatch(platform, dropdown, items)
    if yaml_diff:
        result['yaml_mismatch'] = yaml_diff
        result['instruction'] = (
            f"ACTION REQUIRED: Platform YAML out of sync.\n"
            f"  Live only: {yaml_diff.get('live_only', [])}\n"
            f"  YAML only: {yaml_diff.get('yaml_only', [])}\n"
            f"  Update platforms/{platform}.yaml before proceeding."
        )

    return result


def handle_prepare(platform: str, redis_client) -> Dict[str, Any]:
    """Get available options for a platform from YAML config."""
    try:
        config = _load_platform_yaml(platform)
    except (FileNotFoundError, ValueError) as e:
        return {"error": str(e), "platform": platform}

    caps = config.get('capabilities', {})
    return {
        "platform": platform,
        "models": caps.get('models', []),
        "modes": caps.get('modes', []),
        "tools": caps.get('tools', []),
        "sources": caps.get('sources', []),
        "quirks": config.get('quirks', []),
        "mode_guidance": config.get('mode_guidance', {}),
        "element_hints": config.get('element_hints', {}),
        "note": "These are from platform YAML configs. Use EXACTLY these names when selecting.",
    }
