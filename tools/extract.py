"""taey_quick_extract, taey_extract_history - Response extraction via clipboard."""

import json
import os
import time
import logging
from typing import Any, Dict

from core import atspi, input as inp, clipboard
from core.tree import find_elements, find_copy_buttons
from core.interact import atspi_click
from core.platforms import SCREEN_HEIGHT
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)


def _filter_response_copy(copy_buttons: list) -> list:
    """Filter copy buttons to prefer response copy over user message / code copy."""
    _RESPONSE_NAMES = {'copy response', 'copy'}
    _EXCLUDE_NAMES = {'copy message', 'copy code', 'copy message to clipboard'}
    response_copy = [
        b for b in copy_buttons
        if (b.get('name') or '').strip().lower() in _RESPONSE_NAMES
        and (b.get('name') or '').strip().lower() not in _EXCLUDE_NAMES
    ]
    chatgpt_copy = [b for b in response_copy if (b.get('name') or '').strip().lower() == 'copy response']
    return chatgpt_copy or response_copy or copy_buttons


def _scroll_copy_into_view(platform: str, target_btn: dict,
                           original_buttons: list) -> tuple:
    """Scroll until copy button is in viewport (ChatGPT DOM virtualization)."""
    for _ in range(2):
        inp.press_key('End')
        time.sleep(0.3)
    time.sleep(0.3)

    firefox = atspi.find_firefox_for_platform(platform)
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    if not doc:
        return target_btn, target_btn['x'], target_btn['y']

    all_elements = find_elements(doc)
    copy_buttons = find_copy_buttons(all_elements)
    if not copy_buttons:
        return target_btn, target_btn['x'], target_btn['y']

    candidates = _filter_response_copy(copy_buttons)
    newest = candidates[-1]
    x, y = newest['x'], newest['y']

    if y <= SCREEN_HEIGHT:
        return newest, x, y

    for attempt in range(3):
        inp.press_key('Page_Up')
        time.sleep(0.3)
        firefox = atspi.find_firefox_for_platform(platform)
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        if not doc:
            break
        all_elements = find_elements(doc)
        copy_buttons = find_copy_buttons(all_elements)
        if not copy_buttons:
            continue
        visible = [b for b in _filter_response_copy(copy_buttons) if 0 < b.get('y', 0) <= SCREEN_HEIGHT]
        if visible:
            newest = visible[-1]
            return newest, newest['x'], newest['y']

    return newest, x, y


def handle_quick_extract(platform: str, redis_client,
                         neo4j_mod=None, complete: bool = False) -> Dict[str, Any]:
    """Extract latest response via clipboard (click Copy, read clipboard)."""
    if not inp.switch_to_platform(platform):
        return {"error": f"Could not switch to {platform} tab", "platform": platform}

    # Scroll to absolute bottom FIRST, then get doc and scan
    for _ in range(5):
        inp.press_key('End')
        time.sleep(0.3)
    time.sleep(0.5)

    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        return {"success": False, "error": "Firefox not found", "platform": platform}
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"success": False, "error": f"Could not find {platform} document", "platform": platform}
    url = atspi.get_document_url(doc)

    # Extra scroll if needed — press End until positions stabilize
    last_max_y = 0
    for _ in range(15):
        elements = find_elements(doc)
        if elements:
            cur_max_y = max(e.get('y', 0) for e in elements)
            if cur_max_y == last_max_y:
                break
            last_max_y = cur_max_y
        inp.press_key('End')
        time.sleep(0.4)
    time.sleep(0.3)

    # Re-fetch doc after scroll complete for fresh AT-SPI tree
    doc = atspi.get_platform_document(firefox, platform) or doc
    all_elements = find_elements(doc)
    copy_buttons = find_copy_buttons(all_elements)

    # Scroll to find copy buttons if none visible
    if not copy_buttons:
        for _ in range(5):
            inp.press_key('End')
            time.sleep(0.3)
        time.sleep(0.5)
        doc = atspi.get_platform_document(firefox, platform) if firefox else doc
        if doc:
            all_elements = find_elements(doc)
            copy_buttons = find_copy_buttons(all_elements)
        if not copy_buttons:
            for _ in range(8):
                inp.press_key('Page_Up')
                time.sleep(0.4)
                if doc:
                    all_elements = find_elements(doc)
                    copy_buttons = find_copy_buttons(all_elements)
                    if copy_buttons:
                        break

    if not copy_buttons:
        return {"success": False, "error": "No copy buttons found", "platform": platform,
                "hint": "Response may not be visible - try scrolling or waiting."}

    # Prefer response copy buttons over code/message copy buttons.
    # ChatGPT: "Copy response" (response) vs "Copy message" (user msg)
    # Claude/Grok: "Copy" (both user and response)
    _RESPONSE_NAMES = {'copy response', 'copy'}
    _EXCLUDE_NAMES = {'copy message', 'copy code', 'copy message to clipboard'}
    response_copy = [
        b for b in copy_buttons
        if (b.get('name') or '').strip().lower() in _RESPONSE_NAMES
        and (b.get('name') or '').strip().lower() not in _EXCLUDE_NAMES
    ]
    # If we have "Copy response" buttons (ChatGPT), prefer those over plain "Copy"
    chatgpt_copy = [b for b in response_copy if (b.get('name') or '').strip().lower() == 'copy response']
    candidates = chatgpt_copy or response_copy or copy_buttons
    # Pick the button with highest Y coordinate — bottom of page = AI response
    newest = max(candidates, key=lambda b: b.get('y', 0))
    x, y = newest['x'], newest['y']

    if y > SCREEN_HEIGHT:
        newest, x, y = _scroll_copy_into_view(platform, newest, copy_buttons)

    clipboard.clear()
    time.sleep(0.1)

    if newest.get('atspi_obj') and atspi_click(newest):
        pass
    else:
        inp.click_at(x, y)
    time.sleep(0.8)

    content = clipboard.read()

    # Detect if we copied user prompt instead of AI response.
    # Check against the actual pending_prompt stored by send_message.
    if content and redis_client:
        pending_json = redis_client.get(node_key(f"pending_prompt:{platform}"))
        if pending_json:
            try:
                pending = json.loads(pending_json)
                sent_text = pending.get('content', '').strip()
                if sent_text and content.strip() == sent_text:
                    # Copied the user message — try the second-to-last button
                    if len(candidates) >= 2:
                        prev = candidates[-2]
                        clipboard.clear()
                        time.sleep(0.1)
                        if prev.get('atspi_obj') and atspi_click(prev):
                            pass
                        else:
                            inp.click_at(prev['x'], prev['y'])
                        time.sleep(0.8)
                        retry = clipboard.read()
                        if retry and retry.strip() != sent_text:
                            content = retry
                    else:
                        content = None
            except (json.JSONDecodeError, TypeError):
                pass

    # Retry with focus+Enter then xdotool if clipboard empty
    if not content and newest.get('atspi_obj'):
        from core.interact import atspi_focus
        clipboard.clear()
        if atspi_focus(newest):
            inp.press_key('Return')
            time.sleep(0.8)
            content = clipboard.read()
        if not content:
            clipboard.clear()
            inp.click_at(x, y)
            time.sleep(0.8)
            content = clipboard.read()

    if not content:
        return {"success": False, "error": "No response in clipboard after Copy",
                "platform": platform, "copy_button_coords": {"x": x, "y": y},
                "copy_buttons_found": len(copy_buttons)}

    quality = _assess_extraction(content, platform, all_elements)

    # Store in Neo4j
    neo4j_stored = None
    if redis_client:
        pending_json = redis_client.get(node_key(f"pending_prompt:{platform}"))
        if pending_json:
            try:
                pending = json.loads(pending_json)
                sid = pending.get('session_id')
                uid = pending.get('message_id')
                if sid and neo4j_mod:
                    rid = neo4j_mod.add_message(sid, 'assistant', content)
                    if rid and uid:
                        _link_response(neo4j_mod, rid, uid)
                    neo4j_stored = {"session_id": sid, "response_id": rid, "user_message_id": uid}
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning(f"Neo4j store failed: {e}")

    # HMM webhook (non-blocking)
    if content and content.strip().startswith('{') and 'motif' in content.lower():
        try:
            import requests as _req
            url_hmm = os.environ.get('HMM_STORE_URL', 'http://localhost:8095/hmm/store-response')
            _req.post(url_hmm, json={"platform": platform, "content": content}, timeout=60)
        except Exception:
            pass

    # Completion cleanup
    plan_consumed = False
    save_path = None
    if complete and redis_client:
        redis_client.delete(node_key(f"pending_prompt:{platform}"))
        plan_consumed = redis_client.delete(node_key(f"plan:{platform}")) > 0
        for suffix in [f"plan:current:{platform}", f"checkpoint:{platform}:inspect",
                       f"checkpoint:{platform}:attach", f"response_reviewed:{platform}"]:
            redis_client.delete(node_key(suffix))
        # Clear DISPLAY-scoped plan lock
        display = os.environ.get('DISPLAY', ':0')
        redis_client.delete(f"taey:plan_active:{display}")
        # Clean up active monitor sessions for this platform
        set_key = node_key("active_session_ids")
        try:
            session_keys = redis_client.smembers(set_key)
            for skey in session_keys:
                try:
                    sdata = redis_client.get(skey)
                    if sdata:
                        sess = json.loads(sdata)
                        if sess.get('platform') == platform:
                            redis_client.delete(skey)
                            redis_client.srem(set_key, skey)
                    else:
                        # Key expired — remove from SET
                        redis_client.srem(set_key, skey)
                except Exception:
                    pass
        except Exception:
            pass
        if content:
            save_path = f"/tmp/hmm_response_{platform}.json"
            try:
                with open(save_path, 'w') as f:
                    f.write(content)
            except Exception:
                save_path = None

    return {
        "success": True, "platform": platform, "content": content,
        "length": len(content), "has_artifacts": '```' in content,
        "url": url, "copy_buttons_found": len(copy_buttons),
        "plan_consumed": plan_consumed, "neo4j": neo4j_stored,
        "save_path": save_path, "quality": quality,
    }


def _link_response(neo4j_mod, response_id: str, user_message_id: str):
    try:
        driver = neo4j_mod.get_driver()
        if driver:
            with driver.session() as s:
                s.run("""
                    MATCH (resp:Message {message_id: $response_id})
                    MATCH (user:Message {message_id: $user_message_id})
                    MERGE (resp)-[:RESPONDS_TO]->(user)
                """, response_id=response_id, user_message_id=user_message_id)
    except Exception as e:
        logger.warning(f"RESPONDS_TO edge failed: {e}")


def _assess_extraction(content: str, platform: str, elements: list) -> Dict[str, Any]:
    """Raw quality signals for Claude to interpret."""
    word_count = len(content.split())
    _KEYWORDS = ['continue', 'show more', 'expand', 'export', 'download', 'load more']
    action_buttons = []
    for e in elements:
        name = (e.get('name') or '').strip().lower()
        role = e.get('role', '')
        if name and ('button' in role or role == 'link'):
            if any(kw in name for kw in _KEYWORDS):
                action_buttons.append({'name': e.get('name', '').strip(), 'role': role,
                                       'x': e.get('x'), 'y': e.get('y')})
    return {"word_count": word_count, "action_buttons": action_buttons,
            "likely_complete": not action_buttons and word_count >= 20}


def handle_extract_history(platform: str, redis_client,
                           max_messages: int = 500) -> Dict[str, Any]:
    """Extract full conversation history by scrolling through all Copy buttons."""
    messages, seen_hashes = [], set()
    scroll_iterations, consecutive_no_new = 0, 0

    if not inp.switch_to_platform(platform):
        return {"error": f"Could not switch to {platform} tab", "platform": platform}

    inp.scroll_to_top()
    time.sleep(1.0)

    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        return {"success": False, "error": "Firefox not found", "platform": platform}
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"success": False, "error": f"Could not find {platform} document", "platform": platform}
    url = atspi.get_document_url(doc)

    while scroll_iterations < 100 and len(messages) < max_messages:
        scroll_iterations += 1
        firefox = atspi.find_firefox_for_platform(platform)
        doc = atspi.get_platform_document(firefox, platform)
        if not doc:
            break

        all_elements = find_elements(doc)
        copy_buttons = [e for e in find_copy_buttons(all_elements) if 0 <= e.get('y', 0) <= SCREEN_HEIGHT]

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
            if btn.get('atspi_obj') and atspi_click(btn):
                pass
            else:
                inp.click_at(btn['x'], btn['y'])
            time.sleep(0.3)
            content = clipboard.read()
            if content and not content.startswith("__MARKER_"):
                h = hash(content)
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    messages.append({'content': content, 'y_position': btn['y'],
                                     'sequence': len(messages)})
                    new_count += 1

        consecutive_no_new = 0 if new_count else consecutive_no_new + 1
        if consecutive_no_new >= 3:
            break
        inp.scroll_page_down()
        time.sleep(0.3)

    return {"success": True, "platform": platform, "url": url,
            "messages_extracted": len(messages), "scroll_iterations": scroll_iterations,
            "messages": messages[:10] if len(messages) > 10 else messages}
