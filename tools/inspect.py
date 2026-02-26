"""
taey_inspect - Scan platform AT-SPI tree and return visible elements.

The foundation tool. Must be called before any other interaction.
Switches to the platform tab, scans AT-SPI tree, scrolls to bottom,
and returns all visible elements for Claude to interpret.

Works with OR without a plan:
- With plan: navigates to specific URL on first call, skips on subsequent
- Without plan: switches to platform tab, scans what's already visible
"""

import json
import time
import logging
from typing import Any, Dict

from core import atspi, input as inp, clipboard
from core.tree import find_elements, filter_useful_elements, find_copy_buttons, detect_chrome_y
from core.platforms import BASE_URLS, SCREEN_HEIGHT

logger = logging.getLogger(__name__)


def handle_inspect(platform: str, redis_client, **kwargs) -> Dict[str, Any]:
    """Inspect a platform and return all visible elements.

    Flow:
    1. If plan exists with URL and not yet navigated: navigate to URL
    2. Otherwise: just switch to platform tab (stateless mode)
    3. Scroll to bottom, scan AT-SPI tree
    4. Find all elements, filter to useful ones
    5. Store in Redis

    Args:
        platform: Which platform to inspect.
        redis_client: Redis client for plan/state storage.

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
        plan_id = redis_client.get(f"taey:v4:plan:current:{platform}")
        if plan_id:
            plan_json = redis_client.get(f"taey:v4:plan:{plan_id}")
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

        if not inp.type_text(target_url, timeout=30):
            result['error'] = f"URL typing timed out for: {target_url}"
            return result

        time.sleep(0.1)
        inp.press_key('Return')
        time.sleep(10.0)  # Wait for page load

        inp.scroll_to_bottom()
        time.sleep(1.0)

        # Mark as navigated in plan
        if plan and redis_client and plan_id:
            plan['navigated'] = True
            redis_client.set(f"taey:v4:plan:{plan_id}", json.dumps(plan))
    else:
        # No plan or already navigated - just switch to platform tab
        if not inp.switch_to_platform(platform):
            result['error'] = f"Failed to switch to {platform} tab"
            return result
        time.sleep(0.5)

        # Scroll to bottom to see latest content
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

    # Truncate long element names to prevent output overflow
    # (Gemini sidebar items can have 200K+ char names from pasted content)
    MAX_NAME_LEN = 200
    for e in elements:
        name = e.get('name', '')
        if len(name) > MAX_NAME_LEN:
            e['name'] = name[:MAX_NAME_LEN] + '...'

    copy_buttons = find_copy_buttons(all_elements)
    result['state']['copy_button_count'] = len(copy_buttons)
    result['state']['element_count'] = len(elements)
    result['state']['total_before_filter'] = len(all_elements)
    result['controls'] = elements

    # Step 5: Store in Redis
    if redis_client:
        redis_client.set(f"taey:v4:inspect:{platform}", json.dumps({
            'url': url,
            'state': result['state'],
            'controls': elements,
            'timestamp': time.time(),
        }))
        redis_client.setex(f"taey:checkpoint:{platform}:inspect", 1800, json.dumps({
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
