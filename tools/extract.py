"""
taey_quick_extract, taey_extract_history - Response extraction via clipboard.

Extracts AI responses by clicking Copy buttons and reading the clipboard.
History extraction scrolls through the entire conversation.
"""

import json
import os
import time
import logging
from typing import Any, Dict

from core import atspi, input as inp, clipboard
from core.tree import find_elements, find_copy_buttons
from core.atspi_interact import atspi_click
from core.platforms import SCREEN_HEIGHT
from storage.redis_pool import node_key

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
    # Switch to platform tab (handles focus, Alt+N, Ctrl+Tab fallback)
    if not inp.switch_to_platform(platform):
        return {"error": f"Could not switch to {platform} tab", "platform": platform}

    # Scroll to bottom (Firefox is already focused after tab switch)
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

    # Prefer response-level "Copy" buttons over code block "Copy code" buttons.
    # Response Copy buttons have name exactly "Copy"; code blocks have "Copy code".
    response_copy = [b for b in copy_buttons if (b.get('name') or '').strip().lower() == 'copy']
    if response_copy:
        # Use newest response-level Copy button (highest Y)
        newest = response_copy[-1]
    else:
        # Fall back to newest copy button of any kind
        newest = copy_buttons[-1]

    x, y = newest['x'], newest['y']

    clipboard.clear()
    time.sleep(0.1)

    # Try AT-SPI do_action first (works even off-screen), fall back to xdotool
    if newest.get('atspi_obj') and atspi_click(newest):
        logger.info(f"Copy clicked via AT-SPI do_action at ({x}, {y})")
    else:
        logger.info(f"Copy clicked via xdotool at ({x}, {y})")
        inp.click_at(x, y)
    time.sleep(0.8)

    content = clipboard.read()

    # ChatGPT toggle buttons: do_action(0) returns True but doesn't fire
    # the React onClick handler. Retry with grab_focus + Enter, then xdotool.
    if not content and newest.get('atspi_obj'):
        logger.info("Clipboard empty after do_action — retrying with focus+Enter")
        from core.atspi_interact import atspi_focus
        clipboard.clear()
        if atspi_focus(newest):
            inp.press_key('Return')
            time.sleep(0.8)
            content = clipboard.read()
        if not content:
            logger.info("Focus+Enter failed — retrying with xdotool click")
            clipboard.clear()
            inp.click_at(x, y)
            time.sleep(0.8)
            content = clipboard.read()

    if not content:
        return {
            "success": False,
            "error": "No response content in clipboard after clicking Copy",
            "platform": platform,
            "copy_button_coords": {"x": x, "y": y},
            "copy_buttons_found": len(copy_buttons),
            "hint": "Copy button may not be functional. Try scrolling to make the response fully visible.",
        }

    has_artifacts = '```' in content or 'artifact' in content.lower()

    # ── Quality assessment (Step 1 of 2-step extraction) ──
    # Caller MUST check these flags and take follow-up action if needed.
    quality = _assess_extraction(content, platform, all_elements)

    # ── Store response in Neo4j ──
    # Retrieve pending prompt to link response to the correct session/message.
    neo4j_stored = None
    if redis_client:
        pending_json = redis_client.get(node_key(f"pending_prompt:{platform}"))
        if pending_json:
            try:
                pending = json.loads(pending_json)
                session_id = pending.get('session_id')
                user_message_id = pending.get('message_id')
                if session_id and neo4j_mod:
                    response_id = neo4j_mod.add_message(
                        session_id, 'assistant', content
                    )
                    # Create RESPONDS_TO edge if both message IDs exist
                    if response_id and user_message_id:
                        _link_response(neo4j_mod, response_id, user_message_id)
                    neo4j_stored = {
                        "session_id": session_id,
                        "response_id": response_id,
                        "user_message_id": user_message_id,
                    }
                    logger.info(
                        f"Response stored in Neo4j: session={session_id}, "
                        f"response={response_id}"
                    )
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning(f"Failed to store response in Neo4j: {e}")

    # ── HMM Weaviate triple-write ──
    # If response looks like HMM enrichment JSON, forward to store endpoint.
    # This patches Weaviate tiles + creates Neo4j HMMTile + updates Redis index.
    # Non-blocking: extraction succeeds even if this fails.
    if content and content.strip().startswith('{') and 'motif' in content.lower():
        try:
            import requests as _req
            hmm_url = os.environ.get('HMM_STORE_URL', 'http://localhost:8095/hmm/store-response')
            hmm_resp = _req.post(
                hmm_url,
                json={"platform": platform, "content": content},
                timeout=60,
            )
            hmm_data = hmm_resp.json() if hmm_resp.ok else {}
            if hmm_data.get("success"):
                logger.info(f"HMM triple-write: stored {hmm_data.get('stored', 0)} items to Weaviate+Neo4j+Redis")
            else:
                logger.warning(f"HMM triple-write failed: {hmm_data.get('error', 'unknown')}")
        except Exception as e:
            logger.warning(f"HMM triple-write unavailable (response still in Neo4j): {e}")

    # Handle completion - only if caller explicitly says complete
    plan_consumed = False
    if complete and redis_client:
        redis_client.delete(node_key(f"pending_prompt:{platform}"))
        deleted = redis_client.delete(node_key(f"plan:{platform}"))
        redis_client.delete(node_key(f"plan:current:{platform}"))
        redis_client.delete(node_key(f"checkpoint:{platform}:inspect"))
        redis_client.delete(node_key(f"checkpoint:{platform}:attach"))
        redis_client.delete(node_key(f"response_reviewed:{platform}"))
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
        "neo4j": neo4j_stored,
        # Quality assessment - caller MUST check these
        "quality": quality,
    }


def _link_response(neo4j_mod, response_id: str, user_message_id: str):
    """Create RESPONDS_TO edge between assistant response and user message.

    Uses the neo4j driver directly since storage/ is FROZEN and doesn't
    have this method. This is the only place we need graph edges from tools/.
    """
    try:
        driver = neo4j_mod.get_driver()
        if driver:
            with driver.session() as s:
                s.run("""
                    MATCH (resp:Message {message_id: $response_id})
                    MATCH (user:Message {message_id: $user_message_id})
                    MERGE (resp)-[:RESPONDS_TO]->(user)
                """, response_id=response_id, user_message_id=user_message_id)
            logger.info(f"RESPONDS_TO edge: {response_id} -> {user_message_id}")
    except Exception as e:
        logger.warning(f"Failed to create RESPONDS_TO edge: {e}")


def _assess_extraction(content: str, platform: str, elements: list) -> Dict[str, Any]:
    """Assess extraction quality with platform-agnostic signals.

    Returns raw signals for Claude to interpret. No platform-specific
    logic — Claude sees the signals and decides what action to take.
    """
    word_count = len(content.split())

    # Scan for actionable buttons that might indicate incomplete response
    _ACTION_KEYWORDS = ['continue', 'show more', 'expand', 'export', 'download', 'load more']
    action_buttons = []
    for e in elements:
        name = (e.get('name') or '').strip().lower()
        role = e.get('role', '')
        if not name or 'button' not in role and role != 'link':
            continue
        if any(kw in name for kw in _ACTION_KEYWORDS):
            action_buttons.append({
                'name': e.get('name', '').strip(),
                'role': role,
                'x': e.get('x'),
                'y': e.get('y'),
            })

    return {
        "word_count": word_count,
        "action_buttons": action_buttons,
        "likely_complete": len(action_buttons) == 0 and word_count >= 20,
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

    # Switch to platform tab (handles focus, Alt+N, Ctrl+Tab fallback)
    if not inp.switch_to_platform(platform):
        return {"error": f"Could not switch to {platform} tab", "platform": platform}

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

            # AT-SPI do_action first (works off-screen), fall back to xdotool
            if btn.get('atspi_obj') and atspi_click(btn):
                pass
            else:
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
