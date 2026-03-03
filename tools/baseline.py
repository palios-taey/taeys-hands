"""
taey_baseline_map - Dedicated baseline mapping tool.

Visits a platform, maps all visible main-window elements (excluding
sidebar sessions), opens each known dropdown trigger, records contents,
and saves everything to a persistent YAML baseline file.

Baselines are stored in baselines/<platform>.yaml and are the canonical
source of truth for what a platform's UI looks like. On every subsequent
inspect or dropdown call, current state is compared against this baseline.

This is a one-time dedicated pass per platform. Re-run to refresh.
"""

import os
import time
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

import yaml

from core import atspi, input as inp
from core.tree import (find_elements, filter_useful_elements,
                       detect_chrome_y, find_menu_items,
                       compute_structure_hash)
from core.atspi_interact import cache_elements, strip_atspi_obj
from core.platforms import SCREEN_HEIGHT
from tools.dropdown import (_click_trigger_via_atspi,
                            _is_browser_context_menu,
                            _get_trigger_coords)

BASELINES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'baselines')

logger = logging.getLogger(__name__)

# Roles that represent sidebar session items — exclude from baseline
_SIDEBAR_ROLES = {'link', 'list item'}

# Names that indicate sidebar session entries (conversation titles)
# These are content-variable, not structural
_SIDEBAR_LANDMARKS = {'navigation', 'complementary'}


def _ensure_baselines_dir():
    """Create baselines directory if it doesn't exist."""
    os.makedirs(BASELINES_DIR, exist_ok=True)


def _filter_sidebar_elements(elements: List[Dict]) -> List[Dict]:
    """Filter out sidebar session elements from the element list.

    Sidebar sessions are links/list items in the left navigation area.
    We keep structural elements (buttons, dropdowns, textboxes) that
    are part of the UI, not conversation history.

    Claude decides what's sidebar and what's not based on the full
    element scan — this just removes the obvious noise of dozens of
    old conversation title links.
    """
    # Keep everything that's not a link or list item — those are structural
    # For links/list items: keep only if they look like UI controls
    # (have actionable states like 'pressed', 'checked', 'selected')
    _UI_STATES = {'pressed', 'checked', 'selected', 'expanded'}

    result = []
    for e in elements:
        role = e.get('role', '')
        if role not in _SIDEBAR_ROLES:
            result.append(e)
            continue

        # For links/list items: keep if they have UI-control states
        states = set(s.lower() for s in e.get('states', []))
        if states & _UI_STATES:
            result.append(e)
            # Also keep links that are clearly UI navigation (short names)
        elif role == 'link' and len(e.get('name', '')) <= 30:
            result.append(e)

    return result


def _map_main_window(platform: str) -> Dict[str, Any]:
    """Map all visible main-window elements for a platform.

    Switches to the platform tab, scans the AT-SPI tree, filters out
    sidebar sessions, and returns the structural element map.
    """
    if not inp.switch_to_platform(platform):
        return {'error': f'Failed to switch to {platform} tab'}

    time.sleep(1.0)

    # Scroll to bottom to see full UI (chat area + input area)
    inp.press_key('End')
    time.sleep(0.5)

    firefox = atspi.find_firefox()
    if not firefox:
        return {'error': 'Firefox not found'}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {'error': f'Could not find {platform} document'}

    url = atspi.get_document_url(doc)
    chrome_y = detect_chrome_y(doc)
    all_elements = find_elements(doc)
    elements = filter_useful_elements(all_elements, chrome_y=chrome_y)

    # Cache for subsequent operations
    cache_elements(platform, all_elements)

    # Strip D-Bus proxies for serialization
    elements_json = strip_atspi_obj(elements)

    # Filter out sidebar session noise
    main_elements = _filter_sidebar_elements(elements_json)

    # Compute structure hash
    structure_hash = compute_structure_hash(elements_json, screen_height=int(SCREEN_HEIGHT))

    return {
        'url': url,
        'element_count': len(main_elements),
        'total_before_filter': len(all_elements),
        'structure_hash': structure_hash,
        'elements': main_elements,
        'chrome_y': chrome_y,
    }


def _map_dropdown(platform: str, dropdown_name: str) -> Dict[str, Any]:
    """Open a dropdown and record its contents.

    Returns dict with items list, or error info.
    """
    firefox = atspi.find_firefox()
    if not firefox:
        return {'error': 'Firefox not found'}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {'error': f'Could not find {platform} document'}

    # Get trigger coordinates for fallback
    trigger_info = _get_trigger_coords(doc, dropdown_name)

    # Try AT-SPI click first
    clicked = _click_trigger_via_atspi(doc, dropdown_name)
    if not clicked:
        if trigger_info:
            # Try coordinate click as primary
            inp.click_at(trigger_info['x'], trigger_info['y'])
            clicked = True
        else:
            return {
                'error': f"Could not find dropdown trigger '{dropdown_name}'",
                'skipped': True,
            }

    time.sleep(0.5)

    # Re-scan for menu items
    firefox = atspi.find_firefox()
    if not firefox:
        return {'error': 'Firefox lost after click'}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {'error': f'Document lost after click'}

    menu_items = find_menu_items(firefox, doc)

    # Check for browser context menu
    if menu_items and _is_browser_context_menu(menu_items):
        logger.warning(f"Context menu detected for {platform}/{dropdown_name}, retrying with coords")
        inp.press_key('Escape')
        time.sleep(0.3)

        if trigger_info:
            inp.click_at(trigger_info['x'], trigger_info['y'])
            time.sleep(0.5)

            firefox = atspi.find_firefox()
            if firefox:
                doc = atspi.get_platform_document(firefox, platform)
                if doc:
                    menu_items = find_menu_items(firefox, doc)
                    if menu_items and _is_browser_context_menu(menu_items):
                        inp.press_key('Escape')
                        return {
                            'error': f"Context menu persists for '{dropdown_name}'",
                            'trigger_coords': trigger_info,
                        }

    # Dismiss the dropdown after recording
    items = []
    if menu_items:
        for e in menu_items:
            item = {
                'name': e.get('name', ''),
                'role': e.get('role', ''),
            }
            items.append(item)

    # Close dropdown
    inp.press_key('Escape')
    time.sleep(0.3)

    if not items:
        return {
            'error': f"No items found in '{dropdown_name}' dropdown",
            'trigger_coords': trigger_info,
        }

    return {
        'items': items,
        'count': len(items),
    }


def _find_dropdown_triggers(elements: List[Dict]) -> List[str]:
    """Find potential dropdown trigger buttons from element list.

    Returns list of button names that could be dropdown triggers.
    These are buttons that Claude should try opening.
    """
    triggers = []
    for e in elements:
        role = e.get('role', '')
        name = (e.get('name', '') or '').strip()
        states = set(s.lower() for s in e.get('states', []))

        # Buttons with 'expanded' state or combo boxes are dropdown triggers
        if 'button' in role and name:
            if 'expanded' in states or 'haspopup' in str(e.get('description', '')).lower():
                triggers.append(name)
            # Also include buttons that look like model/mode selectors
            # (Claude will determine which ones are actually dropdowns)

        if role == 'combo box' and name:
            triggers.append(name)

    return triggers


def handle_baseline_map(platform: str, redis_client,
                        dropdowns: List[str] = None) -> Dict[str, Any]:
    """Run a dedicated baseline mapping pass for a platform.

    Maps main window elements, opens each specified dropdown to record
    contents, and saves everything to baselines/<platform>.yaml.

    Args:
        platform: Which platform to map.
        redis_client: Redis client (for structure fingerprint storage).
        dropdowns: Optional list of dropdown names to open and record.
                   If not provided, attempts to auto-detect triggers.

    Returns:
        Dict with mapping results and path to saved baseline file.
    """
    _ensure_baselines_dir()

    result = {
        'platform': platform,
        'success': False,
    }

    # Step 1: Map main window
    logger.info(f"Baseline mapping: scanning {platform} main window")
    main_window = _map_main_window(platform)

    if main_window.get('error'):
        result['error'] = main_window['error']
        return result

    result['main_window'] = {
        'url': main_window['url'],
        'element_count': main_window['element_count'],
        'structure_hash': main_window['structure_hash'],
    }

    # Step 2: Map dropdowns
    dropdown_results = {}

    if dropdowns:
        for dd_name in dropdowns:
            logger.info(f"Baseline mapping: opening dropdown '{dd_name}' on {platform}")
            dd_result = _map_dropdown(platform, dd_name)
            dropdown_results[dd_name] = dd_result

            # Brief pause between dropdowns
            time.sleep(0.3)

    result['dropdowns_mapped'] = len(dropdown_results)
    result['dropdown_results'] = {
        name: {
            'count': dr.get('count', 0),
            'error': dr.get('error'),
        }
        for name, dr in dropdown_results.items()
    }

    # Step 3: Build and save baseline YAML
    baseline = {
        'platform': platform,
        'mapped_at': datetime.now(timezone.utc).isoformat(),
        'structure_hash': main_window['structure_hash'],
        'main_window': {
            'url': main_window['url'],
            'element_count': main_window['element_count'],
            'chrome_y': main_window['chrome_y'],
            'elements': main_window['elements'],
        },
        'dropdowns': {},
    }

    for dd_name, dd_result in dropdown_results.items():
        if dd_result.get('items'):
            baseline['dropdowns'][dd_name] = {
                'items': dd_result['items'],
                'count': dd_result['count'],
            }
        elif dd_result.get('error'):
            baseline['dropdowns'][dd_name] = {
                'error': dd_result['error'],
                'items': [],
                'count': 0,
            }

    # Save to disk
    baseline_path = os.path.join(BASELINES_DIR, f'{platform}.yaml')
    with open(baseline_path, 'w') as f:
        yaml.dump(baseline, f, default_flow_style=False, allow_unicode=True,
                  sort_keys=False, width=120)

    result['baseline_path'] = baseline_path
    result['success'] = True

    # Also store structure hash in Redis for runtime comparison
    if redis_client:
        from storage.redis_pool import node_key
        fingerprint_key = node_key(f"structure_fingerprint:{platform}")
        redis_client.set(fingerprint_key, main_window['structure_hash'])

    logger.info(
        f"Baseline saved for {platform}: {main_window['element_count']} elements, "
        f"{len([d for d in dropdown_results.values() if d.get('items')])} dropdowns"
    )

    # Return elements so Claude can see the full map
    result['elements'] = main_window['elements']

    return result
