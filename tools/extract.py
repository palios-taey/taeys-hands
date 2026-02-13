"""
taey_quick_extract, taey_extract_history - Response extraction via clipboard.

Extracts AI responses by clicking Copy buttons and reading the clipboard.
History extraction scrolls through the entire conversation.
"""

import json
import time
import logging
from typing import Any, Dict

from core import atspi, input as inp, clipboard
from core.tree import find_elements, find_copy_buttons
from core.platforms import SCREEN_HEIGHT

logger = logging.getLogger(__name__)


def handle_quick_extract(platform: str, redis_client,
                         neo4j_mod=None,
                         complete: bool = False) -> Dict[str, Any]:
    """Extract the latest response from a chat platform via clipboard.

    Workflow:
    1. Switch to platform, scroll to bottom
    2. Find newest Copy button (highest Y)
    3. Clear clipboard, click Copy, read clipboard
    4. Optionally clean up Redis state if complete=True

    Args:
        platform: Which platform to extract from.
        redis_client: Redis client.
        neo4j_mod: neo4j_client module (optional).
        complete: If True, clean up Redis plan state.

    Returns:
        Dict with content, length, has_artifacts, etc.
    """
    # Focus Firefox and switch to platform
    inp.focus_firefox()
    time.sleep(0.3)

    from core.platforms import TAB_SHORTCUTS
    shortcut = TAB_SHORTCUTS.get(platform)
    if shortcut:
        inp.press_key(shortcut)
        time.sleep(0.3)

    # Click in content area and scroll to bottom
    inp.click_at(900, 600)
    time.sleep(0.1)
    inp.press_key('End')
    time.sleep(0.5)

    # Find platform document
    firefox = atspi.find_firefox()
    if not firefox:
        return {"success": False, "error": "Firefox not found", "platform": platform}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {
            "success": False,
            "error": f"Could not find {platform} document",
            "platform": platform,
        }

    url = atspi.get_document_url(doc)

    # Find copy buttons
    all_elements = find_elements(doc)
    copy_buttons = find_copy_buttons(all_elements)

    if not copy_buttons:
        return {
            "success": False,
            "error": "No copy buttons found on page",
            "platform": platform,
            "hint": "Response may not be visible - try scrolling or waiting.",
        }

    # Click newest (highest Y) copy button
    newest = copy_buttons[-1]
    x, y = newest['x'], newest['y']

    clipboard.clear()
    inp.click_at(x, y)
    time.sleep(0.5)

    content = clipboard.read()
    if not content:
        return {
            "success": False,
            "error": "No response content in clipboard after clicking Copy",
            "platform": platform,
        }

    has_artifacts = '```' in content or 'artifact' in content.lower()

    # Handle completion
    plan_consumed = False
    if complete and redis_client:
        redis_client.delete(f"taey:pending_prompt:{platform}")
        deleted = redis_client.delete(f"taey:plan:{platform}")
        redis_client.delete(f"taey:v4:plan:current:{platform}")
        redis_client.delete(f"taey:checkpoint:{platform}:inspect")
        redis_client.delete(f"taey:checkpoint:{platform}:set_map")
        redis_client.delete(f"taey:checkpoint:{platform}:attach")
        redis_client.delete(f"taey:response_reviewed:{platform}")
        plan_consumed = deleted > 0

    return {
        "success": True,
        "platform": platform,
        "content": content,
        "length": len(content),
        "has_artifacts": has_artifacts,
        "url": url,
        "copy_buttons_found": len(copy_buttons),
        "plan_consumed": plan_consumed,
    }


def handle_extract_history(platform: str, redis_client,
                           max_messages: int = 500) -> Dict[str, Any]:
    """Extract full conversation history from a chat platform.

    Scrolls to top, iterates through all Copy buttons chronologically,
    scrolls down to reveal more, repeats until exhausted.

    Args:
        platform: Which platform.
        redis_client: Redis client.
        max_messages: Safety limit.

    Returns:
        Dict with extracted messages and metadata.
    """
    messages = []
    seen_hashes = set()
    scroll_iterations = 0
    max_scroll = 100
    consecutive_no_new = 0

    # Focus and switch
    inp.focus_firefox()
    time.sleep(0.3)
    from core.platforms import TAB_SHORTCUTS
    shortcut = TAB_SHORTCUTS.get(platform)
    if shortcut:
        inp.press_key(shortcut)
        time.sleep(0.3)

    inp.scroll_to_top()
    time.sleep(1.0)

    firefox = atspi.find_firefox()
    if not firefox:
        return {"success": False, "error": "Firefox not found", "platform": platform}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"success": False, "error": f"Could not find {platform} document", "platform": platform}

    url = atspi.get_document_url(doc)

    while scroll_iterations < max_scroll and len(messages) < max_messages:
        scroll_iterations += 1

        firefox = atspi.find_firefox()
        doc = atspi.get_platform_document(firefox, platform)
        if not doc:
            break

        all_elements = find_elements(doc)
        copy_buttons = [
            e for e in find_copy_buttons(all_elements)
            if 0 <= e.get('y', 0) <= SCREEN_HEIGHT
        ]

        if not copy_buttons:
            inp.scroll_page_down()
            time.sleep(0.5)
            consecutive_no_new += 1
            if consecutive_no_new >= 3:
                break
            continue

        new_count = 0
        for btn in copy_buttons:
            if len(messages) >= max_messages:
                break

            marker = f"__MARKER_{scroll_iterations}_{len(messages)}__"
            clipboard.write_marker(marker)

            inp.click_at(btn['x'], btn['y'])
            time.sleep(0.3)

            content = clipboard.read()
            if content and not content.startswith("__MARKER_"):
                content_hash = hash(content)
                if content_hash not in seen_hashes:
                    seen_hashes.add(content_hash)
                    messages.append({
                        'content': content,
                        'y_position': btn['y'],
                        'sequence': len(messages),
                    })
                    new_count += 1

        if new_count > 0:
            consecutive_no_new = 0
        else:
            consecutive_no_new += 1
            if consecutive_no_new >= 3:
                break

        inp.scroll_page_down()
        time.sleep(0.3)

    return {
        "success": True,
        "platform": platform,
        "url": url,
        "messages_extracted": len(messages),
        "scroll_iterations": scroll_iterations,
        "messages": messages[:10] if len(messages) > 10 else messages,
    }
