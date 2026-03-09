from __future__ import annotations
"""
taey_inspect - Scan platform AT-SPI tree and return visible elements.

The foundation tool. Must be called before any other interaction.
Switches to the platform tab, scans AT-SPI tree, and returns all
visible elements for Claude to interpret.

Scroll behavior (controlled by `scroll` parameter):
- "bottom" (default): Scroll to bottom before scanning. Best for normal
  chat workflows where you want to see the latest messages.
- "top": Scroll to top before scanning. Useful for seeing page headers.
- "none": Pure scan — no tab switch, no scroll. Essential for mid-workflow
  inspection when a dropdown/menu is open, or during multi-step extraction
  of long content. Does NOT switch tabs or press any keys.

Works with OR without a plan:
- With plan: navigates to specific URL on first call, skips on subsequent
- Without plan: switches to platform tab, scans what's already visible

Structure change detection:
- Computes a structure_hash on each inspect (roles + layout grid, not names)
- Compares against last stored fingerprint in Redis
- Flags structure_changed: true if the platform UI layout has changed
- Stable across normal content changes (new messages, different text)
"""

import json
import os
import time
import logging
from typing import Any, Dict

import yaml

from core import atspi, input as inp, clipboard
from core.tree import (find_elements, filter_useful_elements, find_copy_buttons,
                       detect_chrome_y, compute_structure_hash)
from core.atspi_interact import cache_elements, strip_atspi_obj
from core.platforms import BASE_URLS, SCREEN_HEIGHT
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

# File extensions that indicate an attached file chip
_FILE_EXTENSIONS = ('.md', '.py', '.txt', '.pdf', '.png', '.jpg', '.jpeg',
                    '.csv', '.json', '.xml', '.html', '.zip', '.docx')


def _detect_attachments(elements: list, all_elements: list = None) -> dict | None:
    """Detect existing file attachments from element list.

    Looks for "Remove" / "Remove file" buttons and nearby file chip
    elements (headings/buttons with file-like names). Returns info
    about attached files so Claude knows what's already there.

    Also detects unnamed file chips (e.g. Perplexity) by looking for
    clusters of unnamed push buttons immediately above the input entry.
    """
    remove_buttons = []
    file_chips = []

    for e in elements:
        name = (e.get('name') or '').strip()
        role = e.get('role', '')

        # "Remove" or "Remove file ..." buttons indicate attached files
        if 'button' in role and name.lower().startswith('remove'):
            remove_buttons.append(e)

        # File chip: heading or button whose name looks like a filename
        if name and any(name.lower().endswith(ext) for ext in _FILE_EXTENSIONS):
            if role in ('heading', 'push button', 'toggle button', 'link'):
                file_chips.append(name)

    # Detect unnamed file chips (Perplexity pattern):
    # Unnamed push buttons clustered at the same Y, above the input entry
    if not remove_buttons and not file_chips and all_elements:
        entry_y = None
        for e in all_elements:
            if e.get('role') == 'entry' and 'editable' in e.get('states', []):
                entry_y = e.get('y', 0)
                break

        if entry_y:
            # Look for unnamed push buttons in the band 20-100px above entry
            unnamed_close_buttons = []
            for e in all_elements:
                if (e.get('role') == 'push button'
                        and not (e.get('name') or '').strip()
                        and entry_y - 100 < e.get('y', 0) < entry_y - 10):
                    unnamed_close_buttons.append(e)

            if unnamed_close_buttons:
                remove_buttons = unnamed_close_buttons

    if not remove_buttons and not file_chips:
        return None

    result = {
        'count': max(len(remove_buttons), len(file_chips)),
        'files': file_chips,
        'remove_buttons': [{'x': b['x'], 'y': b['y'], 'name': b.get('name', '')}
                           for b in remove_buttons],
        'WARNING': (
            f"{max(len(remove_buttons), len(file_chips))} file(s) already attached. "
            "Remove stale files before attaching new ones to avoid duplicates."
        ),
    }
    return result


def _check_structure_change(platform: str, elements: list,
                            redis_client) -> dict | None:
    """Compute structure fingerprint and compare against stored baseline.

    Returns a dict with change info if structure changed, None if stable
    or if no baseline exists yet (first run just stores the fingerprint).
    """
    if not redis_client:
        return None

    current_hash = compute_structure_hash(elements, screen_height=SCREEN_HEIGHT)
    fingerprint_key = node_key(f"structure_fingerprint:{platform}")

    stored = redis_client.get(fingerprint_key)

    # Always update the stored fingerprint (no expiry — baseline persists
    # across sessions so UI redesigns are detected even after downtime)
    redis_client.set(fingerprint_key, current_hash)

    if stored is None:
        # First time seeing this platform - baseline stored, no comparison
        logger.info(f"Structure fingerprint baseline stored for {platform}: {current_hash}")
        return None

    if stored == current_hash:
        return None

    # Structure changed - flag it
    logger.warning(
        f"Structure change detected on {platform}: {stored} -> {current_hash}"
    )
    return {
        'structure_changed': True,
        'previous_hash': stored,
        'current_hash': current_hash,
        'platform': platform,
        'WARNING': (
            f"Platform UI structure has changed since last inspect. "
            f"Element layout is different - buttons, controls, or page "
            f"structure may have moved. Verify before relying on cached positions."
        ),
    }


def handle_inspect(platform: str, redis_client, scroll: str = "bottom", **kwargs) -> Dict[str, Any]:
    """Inspect a platform and return all visible elements.

    Flow:
    1. If plan exists with URL and not yet navigated: navigate to URL
    2. Otherwise: just switch to platform tab (stateless mode)
    3. Scroll according to `scroll` parameter, scan AT-SPI tree
    4. Find all elements, filter to useful ones
    5. Check for structure changes (layout fingerprinting)
    6. Store in Redis

    Args:
        platform: Which platform to inspect.
        redis_client: Redis client for plan/state storage.
        scroll: Where to scroll before scanning. "bottom" (default),
                "top", or "none" (preserve current scroll position).

    Returns:
        Dict with success, url, state, controls, platform_context.
    """
    result = {
        'platform': platform,
        'success': False,
        'error': None,
        'url': None,
        'state': {},
        'controls': {},
    }

    # Step 1: Check if a plan exists (optional - inspect works without one)
    target_url = None
    already_navigated = False
    plan = None
    plan_id = None

    if redis_client:
        plan_id = redis_client.get(node_key(f"plan:current:{platform}"))
        if plan_id:
            plan_json = redis_client.get(node_key(f"plan:{plan_id}"))
            if plan_json:
                try:
                    plan = json.loads(plan_json)
                    current_state = plan.get('current_state', {}) or {}
                    session = current_state.get('session_url') or plan.get('session', '')
                    already_navigated = plan.get('navigated', False)
                    if session == 'new':
                        target_url = BASE_URLS.get(platform)
                    elif session.startswith('http'):
                        target_url = session
                except json.JSONDecodeError:
                    pass

    # Step 2: Navigate or just switch tab
    if target_url and not already_navigated:
        # Plan exists with URL - navigate to it
        if not inp.switch_to_platform(platform):
            result['error'] = f"Failed to switch to {platform} tab"
            return result

        inp.press_key('Escape')
        time.sleep(0.3)
        inp.press_key('ctrl+l')
        time.sleep(0.2)
        inp.press_key('ctrl+a')
        time.sleep(0.3)

        if not inp.clipboard_paste(target_url):
            result['error'] = f"URL paste failed for: {target_url}"
            return result

        time.sleep(0.1)
        inp.press_key('Return')
        time.sleep(10.0)  # Wait for page load

        # Scroll per parameter (navigation always needs some scroll for fresh page)
        if scroll == 'top':
            inp.press_key('Home')
        elif scroll != 'none':
            inp.scroll_to_bottom()
        time.sleep(1.0)

        # Mark as navigated in plan
        if plan and redis_client and plan_id:
            plan['navigated'] = True
            redis_client.set(node_key(f"plan:{plan_id}"), json.dumps(plan))
    else:
        # No plan or already navigated
        if scroll == 'none':
            # Pure scan: no tab switch, no scroll. Use when a dropdown/menu
            # is open or you're mid-workflow and don't want to disturb state.
            pass
        else:
            # Switch to platform tab
            if not inp.switch_to_platform(platform):
                result['error'] = f"Failed to switch to {platform} tab"
                return result
            time.sleep(0.5)

            if scroll == 'top':
                inp.press_key('Home')
                time.sleep(0.5)
            else:
                # Default: scroll to bottom to see latest content
                inp.press_key('End')
                time.sleep(0.5)

    # Step 3: Get Firefox and platform document
    firefox = atspi.find_firefox()
    if not firefox:
        result['error'] = "Firefox not found in AT-SPI tree"
        return result

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        result['error'] = f"Could not find {platform} document in AT-SPI tree"
        return result

    url = atspi.get_document_url(doc)
    result['url'] = url

    # Step 4: Find and filter elements
    chrome_y = detect_chrome_y(doc)
    all_elements = find_elements(doc)
    elements = filter_useful_elements(all_elements, chrome_y=chrome_y)

    # Cache elements WITH atspi_obj for AT-SPI-first interaction
    # (tools/interact.py, tools/dropdown.py look up elements by coordinates)
    cache_elements(platform, all_elements)

    # Strip atspi_obj for JSON serialization (D-Bus proxies can't serialize)
    elements_json = strip_atspi_obj(elements)

    # Truncate long element names to prevent output overflow
    # (Gemini sidebar items can have 200K+ char names from pasted content)
    MAX_NAME_LEN = 200
    for e in elements_json:
        name = e.get('name', '')
        if len(name) > MAX_NAME_LEN:
            e['name'] = name[:MAX_NAME_LEN] + '...'

    # Platform-specific noise filtering (configured in platforms/*.yaml)
    # Removes sidebar/footer elements that are never actionable (e.g. X/Twitter
    # trending topics, relevant people, footer links).
    try:
        yaml_path = os.path.join(PLATFORMS_DIR, f'{platform}.yaml')
        with open(yaml_path) as _f:
            _pcfg = yaml.safe_load(_f) or {}
        noise = _pcfg.get('inspect_noise', {})
        if noise:
            _excl_roles = set(noise.get('exclude_roles', []))
            _excl_names = set(noise.get('exclude_names', []))
            _excl_contains = noise.get('exclude_name_contains', [])
            _excl_x_max = noise.get('exclude_x_max')
            _excl_x_min = noise.get('exclude_x_min')
            def _is_noise(e):
                x = e.get('x', 0)
                if _excl_x_max and x <= _excl_x_max:
                    return True
                if _excl_x_min and x >= _excl_x_min:
                    return True
                if e.get('role', '') in _excl_roles:
                    return True
                n = e.get('name', '')
                if n in _excl_names:
                    return True
                return any(pat in n for pat in _excl_contains)
            elements_json = [e for e in elements_json if not _is_noise(e)]
    except Exception:
        pass  # YAML missing or malformed — proceed without noise filter

    copy_buttons = find_copy_buttons(all_elements)
    result['state']['copy_button_count'] = len(copy_buttons)
    result['state']['element_count'] = len(elements_json)
    result['state']['total_before_filter'] = len(all_elements)
    result['controls'] = elements_json

    # Detect existing file attachments (Remove buttons + file chips)
    # This prevents accidentally attaching multiple files
    # Pass all_elements (stripped) for unnamed chip detection (Perplexity)
    all_elements_json = strip_atspi_obj(all_elements)
    attached_files = _detect_attachments(elements_json, all_elements_json)
    if attached_files:
        result['attachments'] = attached_files

    # Step 5: Structure change detection
    # Compute layout fingerprint and compare to stored baseline.
    # Uses roles + Y-grid bands (not names/content) so it's stable
    # across normal usage but detects actual UI redesigns.
    structure_change = _check_structure_change(platform, elements_json, redis_client)
    if structure_change:
        result['structure_change'] = structure_change

    # Step 6: Store in Redis
    if redis_client:
        redis_client.set(node_key(f"inspect:{platform}"), json.dumps({
            'url': url,
            'state': result['state'],
            'controls': elements_json,
            'timestamp': time.time(),
        }))
        redis_client.setex(node_key(f"checkpoint:{platform}:inspect"), 1800, json.dumps({
            'url': url,
            'copy_button_count': len(copy_buttons),
            'element_count': len(elements),
            'timestamp': time.time(),
        }))

    result['success'] = True
    result['atspi_note'] = (
        "Menu items (Back, Forward, Reload, etc.) are always in AT-SPI tree "
        "- NOT blocking context menus. Ignore them."
    )

    # PLAN VALIDATION: If a plan exists, surface requirements so they can't be missed
    if plan and plan.get('required_state'):
        required = plan['required_state']
        current = plan.get('current_state')
        result['plan_requirements'] = {
            'plan_id': plan_id,
            'required_state': required,
            'current_state': current,
            'status': plan.get('status', 'unknown'),
        }
        if current is None:
            result['plan_requirements']['WARNING'] = (
                "PLAN EXISTS but current_state NOT SET. You MUST: "
                "1) Read these elements to determine current model/mode/tools, "
                "2) Call taey_plan(update) with current_state, "
                "3) Fix any mismatches BEFORE sending."
            )
        else:
            # Check for unmet requirements
            unmet = []
            req_model = required.get('model')
            cur_model = current.get('model')
            if req_model and req_model not in ('N/A', 'any') and req_model != cur_model:
                unmet.append(f"model: need '{req_model}', have '{cur_model}'")
            req_mode = required.get('mode')
            cur_mode = current.get('mode')
            if req_mode and req_mode not in ('N/A', 'any') and req_mode != cur_mode:
                unmet.append(f"mode: need '{req_mode}', have '{cur_mode}'")
            req_tools = set(required.get('tools', []))
            cur_tools = set(current.get('tools', []))
            if req_tools:
                missing = req_tools - cur_tools
                if missing:
                    unmet.append(f"tools: need {sorted(missing)}")
            if unmet:
                result['plan_requirements']['UNMET'] = unmet
            else:
                result['plan_requirements']['VALIDATED'] = "All requirements met"

    return result
