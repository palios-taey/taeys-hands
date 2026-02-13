"""
taey_inspect - Scan platform AT-SPI tree and return visible elements.

The foundation tool. Must be called before any other interaction.
Switches to the platform tab, navigates if needed, scrolls to bottom,
and returns all visible elements for Claude to interpret.
"""

import json
import time
import logging
from typing import Any, Dict

from core import atspi, input as inp, clipboard
from core.tree import find_elements, filter_useful_elements, find_copy_buttons
from core.platforms import BASE_URLS, SCREEN_HEIGHT

logger = logging.getLogger(__name__)


def handle_inspect(platform: str, redis_client, **kwargs) -> Dict[str, Any]:
    """Inspect a platform and return all visible elements.

    Flow:
    1. Get URL from plan (or base URL for "new")
    2. If not navigated: switch tab, navigate, wait, scroll
    3. If already navigated: just switch tab
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

    # Step 1: Get URL and navigation state from plan
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

    if not target_url:
        result['error'] = f"No plan found for {platform}. Create a plan first with taey_plan."
        return result

    # Step 2: Navigate only if first time for this plan
    if not already_navigated:
        if not inp.switch_to_platform(platform):
            result['error'] = f"Failed to switch to {platform} tab"
            return result

        # Escape to unfocus any element before Ctrl+L
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

        # Mark as navigated
        if plan and redis_client and plan_id:
            plan['navigated'] = True
            redis_client.set(f"taey:v4:plan:{plan_id}", json.dumps(plan))

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
    all_elements = find_elements(doc)
    elements = filter_useful_elements(all_elements)

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
    return result
