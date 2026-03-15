"""taey_select_dropdown, taey_prepare - Dropdown opening and capabilities."""

import json
import os
import time
import logging
from typing import Any, Dict, List, Optional

import yaml

from core import atspi, input as inp
from core.tree import find_elements, find_menu_items
from core.interact import extend_cache, atspi_click
from tools.click import handle_click
from storage.redis_pool import node_key

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

logger = logging.getLogger(__name__)


def _find_trigger_in_cache(trigger_name: str, platform: str) -> Optional[Dict]:
    """Find trigger button in element cache by exact name.

    Every platform has its buttons mapped in YAML element_map.
    Inspect populates the cache. We look up by exact name — if it's
    not there, the element doesn't exist or inspect wasn't called.
    """
    from core.interact import _element_cache, is_defunct
    trigger_lower = trigger_name.lower().strip()
    for e in _element_cache.get(platform, []):
        name = (e.get('name') or '').strip().lower()
        if name == trigger_lower and 'button' in e.get('role', ''):
            if e.get('atspi_obj') and not is_defunct(e):
                return e
    return None


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
        # NOTE: Substring matching is intentional — dropdown_name is the AT-SPI
        # button label (variable), not a target selection value. We're mapping
        # unknown labels to known YAML categories.
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
    target_lower = target_value.lower().strip()
    target_idx = None
    for i, item in enumerate(yaml_items):
        item_lower = str(item).lower().strip()
        if item_lower == target_lower:
            target_idx = i
            break
    if target_idx is None:
        return None

    # ChatGPT is the only keyboard_nav platform. Its dropdown opens with
    # nothing focused — first Down focuses the first item. No Up reset
    # needed (Up closes ChatGPT's React dropdown).
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

    NOTE: Substring matching is INTENTIONAL here — we're mapping unknown,
    variable-length AT-SPI labels to known category keywords. The labels
    change across platforms and updates, so exact matching would break.
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


_KNOWN_PLATFORMS = {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}


def _get_dropdown_method(platform: str) -> str:
    """Get dropdown method from platform YAML config.

    For known platforms, FileNotFoundError propagates (fail loud).
    For unknown/new platforms, falls back to 'atspi_enum'.
    """
    try:
        config = _load_platform_yaml(platform)
        return config.get('dropdown_method', 'atspi_enum')
    except (FileNotFoundError, ValueError):
        if platform in _KNOWN_PLATFORMS:
            logger.error("Platform YAML missing for known platform %s", platform)
            raise
        return 'atspi_enum'


def handle_select_dropdown(platform: str, dropdown: str,
                           target_value: str,
                           redis_client) -> Dict[str, Any]:
    """Open dropdown, select item. Keyboard nav for React portals, AT-SPI for others."""
    inp.press_key('Escape')
    time.sleep(0.2)

    if not inp.switch_to_platform(platform):
        return {"error": f"Failed to switch to {platform} tab"}

    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        return {"error": "Firefox not found"}
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document"}

    # Find trigger button in element cache (populated by inspect) — exact name match
    dropdown_method = _get_dropdown_method(platform)
    trigger = _find_trigger_in_cache(dropdown, platform)
    if not trigger:
        return {"error": f"Trigger button '{dropdown}' not found in element cache for {platform}.",
                "platform": platform,
                "hint": "Call taey_inspect first to populate the element cache."}

    # Click trigger — uses handle_click which respects platform click_strategy
    click_result = handle_click(platform, trigger['x'], trigger['y'])
    trigger_clicked = not click_result.get("error")

    if not trigger_clicked:
        return {"error": f"Failed to click trigger '{dropdown}' at ({trigger['x']},{trigger['y']})",
                "platform": platform}
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
    # Retry up to 5 times — React dropdowns take variable time to render in AT-SPI
    menu_items = []
    for attempt in range(5):
        firefox = atspi.find_firefox_for_platform(platform)
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        if doc:
            menu_items = find_menu_items(firefox, doc)
            if menu_items:
                break
        time.sleep(0.6)

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

    # Auto-select: find the matching item and click it
    if target_value:
        target_lower = target_value.lower().strip()
        matched_item = None
        matched_raw = None
        for raw_item, item_info in zip(menu_items, items):
            item_name = (item_info.get('name') or '').lower().strip()
            if item_name == target_lower:
                matched_item = item_info
                matched_raw = raw_item
                break

        if matched_item and matched_raw:
            # Try AT-SPI do_action first (most reliable for Gemini)
            clicked = False
            atspi_obj = matched_raw.get('atspi_obj')
            if atspi_obj:
                try:
                    action = atspi_obj.get_action_iface()
                    if action and action.get_n_actions() > 0:
                        action.do_action(0)
                        clicked = True
                        logger.info("atspi_enum: clicked '%s' via do_action", matched_item.get('name'))
                except Exception as e:
                    logger.debug("atspi_enum do_action failed: %s", e)

            # Fallback: coordinate click
            if not clicked and matched_item.get('x') and matched_item.get('y'):
                click_result = handle_click(platform, matched_item['x'], matched_item['y'])
                clicked = not click_result.get('error')
                if clicked:
                    logger.info("atspi_enum: clicked '%s' via coords (%d,%d)",
                                matched_item.get('name'), matched_item['x'], matched_item['y'])

            if clicked:
                time.sleep(0.5)
                return {
                    "platform": platform, "dropdown": dropdown,
                    "target_requested": target_value,
                    "selected_via": "atspi_enum",
                    "selected_item": matched_item.get('name', ''),
                    "selected_role": matched_item.get('role', ''),
                    "item_count": len(items),
                    "instruction": "Selected via AT-SPI enumeration. Call taey_inspect to verify.",
                }

    # No match or click failed — return the list for manual selection
    result = {
        "platform": platform, "dropdown": dropdown,
        "target_requested": target_value, "items": items,
        "item_count": len(items),
        "instruction": "Dropdown is OPEN. No exact match found for target. Review items, pick the correct one, click with taey_click.",
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
