"""taey_select_dropdown, taey_prepare - Dropdown opening and capabilities."""

import json
import os
import time
import logging
from typing import Any, Dict, List

import yaml

from core import atspi, input as inp
from core.tree import find_elements, find_menu_items
from core.interact import extend_cache
from tools.click import handle_click
from storage.redis_pool import node_key

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

logger = logging.getLogger(__name__)


def _click_trigger_via_atspi(doc, trigger_name: str, platform: str = None) -> bool:
    """Find button by name in AT-SPI tree and click via do_action.

    Always uses fresh DFS from live doc — never cache. Cached AT-SPI refs
    can be stale (D-Bus proxy alive but widget gone) causing silent no-ops.
    """
    if not doc:
        return False
    trigger_lower = trigger_name.lower()

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
    """Find button by name and return center coordinates.

    Always uses fresh DFS from live doc — never cache.
    """
    if not doc:
        return None
    trigger_lower = trigger_name.lower()

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


def _keyboard_nav_select(platform: str, dropdown: str, target_value: str,
                         yaml_items: List) -> Dict[str, Any] | None:
    """For platforms with React portal dropdowns (Grok, ChatGPT), use keyboard nav.

    Matches target_value against YAML items list to determine arrow-down count,
    then navigates: Down * N + Enter.
    """
    if not yaml_items:
        return None
    target_lower = target_value.lower()
    target_idx = None
    for i, item in enumerate(yaml_items):
        if target_lower in str(item).lower():
            target_idx = i
            break
    if target_idx is None:
        return None

    for _ in range(target_idx + 1):
        inp.press_key('Down')
        time.sleep(0.15)
    inp.press_key('Return')
    time.sleep(0.5)

    return {
        "platform": platform, "dropdown": dropdown,
        "target_requested": target_value,
        "selected_via": "keyboard_nav",
        "selected_index": target_idx,
        "selected_item": str(yaml_items[target_idx]),
        "instruction": "Selected via keyboard navigation. Call taey_inspect to verify.",
    }


def _normalize_dropdown_key(dropdown: str) -> str:
    """Map AT-SPI button label → YAML capability key.

    The dropdown parameter is whatever name the button has in the tree
    (e.g. "Model selector, current model is 5.4 Pro"). We need to map
    that to a YAML key like "models".
    """
    s = (dropdown or '').strip().lower()
    if 'model' in s:
        return 'models'
    if 'mode' in s or 'thinking' in s or 'picker' in s:
        return 'modes'
    if 'tool' in s or 'search' in s or 'deep think' in s or 'canvas' in s:
        return 'tools'
    if 'attach' in s or 'upload' in s or 'file' in s:
        return 'attach_menu'
    if 'source' in s:
        return 'sources'
    # Exact keyword fallback
    _EXACT = {'model': 'models', 'models': 'models', 'mode': 'modes',
              'modes': 'modes', 'tool': 'tools', 'tools': 'tools',
              'attach': 'attach_menu'}
    return _EXACT.get(s, '')


def _get_dropdown_method(platform: str) -> str:
    """Get dropdown method from platform YAML config."""
    try:
        config = _load_platform_yaml(platform)
        return config.get('dropdown_method', 'atspi_enum')
    except (FileNotFoundError, ValueError):
        return 'atspi_enum'


def handle_select_dropdown(platform: str, dropdown: str,
                           target_value: str,
                           redis_client) -> Dict[str, Any]:
    """Open dropdown, select item. Keyboard nav for React portals, AT-SPI for others."""
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

    # Open dropdown trigger
    trigger_clicked = _click_trigger_via_atspi(doc, dropdown, platform=platform)
    if not trigger_clicked:
        trigger_info = _get_trigger_coords(doc, dropdown, platform=platform)
        if trigger_info:
            click_result = handle_click(platform, trigger_info['x'], trigger_info['y'])
            trigger_clicked = not click_result.get("error")
        if not trigger_clicked:
            return {"error": f"Failed to find dropdown trigger '{dropdown}' in AT-SPI tree.",
                    "platform": platform,
                    "hint": "Try taey_inspect to verify screen state."}
    time.sleep(1.0)

    # For React portal platforms, use keyboard nav with YAML item order
    if _get_dropdown_method(platform) == 'keyboard_nav':
        try:
            config = _load_platform_yaml(platform)
            caps = config.get('capabilities', {})
            # Normalize dropdown button label → YAML capability key
            yaml_key = _normalize_dropdown_key(dropdown)
            yaml_items = caps.get(yaml_key, []) if yaml_key else []
            if yaml_items:
                result = _keyboard_nav_select(platform, dropdown, target_value, yaml_items)
                if result:
                    return result
        except Exception as e:
            logger.warning("Keyboard nav failed for %s: %s", platform, e)
        # Fall through to AT-SPI enumeration if keyboard nav fails

    # AT-SPI item enumeration (works for Claude, Gemini, Perplexity)
    menu_items = []
    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    if doc:
        menu_items = find_menu_items(firefox, doc)

    if menu_items:
        extend_cache(platform, menu_items)

    if not menu_items:
        return {"error": f"Dropdown '{dropdown}' opened but no menu items found via AT-SPI.",
                "platform": platform,
                "hint": "For Grok/ChatGPT, check YAML item order and retry. "
                        "For others, try taey_inspect to verify screen state."}

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
