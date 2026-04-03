"""taey_quick_extract, taey_extract_history - Response extraction via clipboard."""

import json
import os
import subprocess
import time
import logging
from typing import Any, Dict, Optional, Tuple

from core import atspi, input as inp, clipboard
from core.config import get_platform_config
from core.tree import find_elements, find_copy_buttons
from core.interact import atspi_click
from core.platforms import SCREEN_HEIGHT
from core.ingest import auto_ingest
from storage.redis_pool import node_key
from storage import neo4j_client

logger = logging.getLogger(__name__)


def _iter_children(obj):
    try:
        count = obj.get_child_count()
    except Exception:
        return

    for i in range(count):
        try:
            child = obj.get_child_at_index(i)
        except Exception:
            child = None
        if child:
            yield child


def _walk_accessible(obj, depth: int = 0, max_depth: int = 25):
    if not obj or depth > max_depth:
        return
    yield obj, depth
    for child in _iter_children(obj):
        yield from _walk_accessible(child, depth + 1, max_depth=max_depth)


def _collect_object_attributes(obj) -> Dict[str, str]:
    attrs = {}
    raw = None
    for getter_name in ('get_attributes', 'get_attribute_set'):
        getter = getattr(obj, getter_name, None)
        if not getter:
            continue
        try:
            raw = getter()
            if raw is not None:
                break
        except Exception:
            continue

    if isinstance(raw, dict):
        return {str(k).lower(): str(v).lower() for k, v in raw.items()}

    if not raw:
        return attrs

    for item in raw:
        text = str(item)
        if ':' in text:
            key, value = text.split(':', 1)
        elif '=' in text:
            key, value = text.split('=', 1)
        else:
            continue
        attrs[key.strip().lower()] = value.strip().lower()
    return attrs


def _role_markers(obj) -> str:
    parts = [(obj.get_role_name() or '').lower()]
    for key, value in _collect_object_attributes(obj).items():
        if 'role' in key:
            parts.append(value)
    return ' '.join(part for part in parts if part)


def _node_signature(obj) -> str:
    name = (obj.get_name() or '').lower()
    role = (obj.get_role_name() or '').lower()
    attrs = _collect_object_attributes(obj)
    attr_text = ' '.join(f"{key} {value}" for key, value in attrs.items())
    return ' '.join(part for part in (name, role, attr_text) if part)


def _element_from_obj(obj) -> dict:
    name = obj.get_name() or ''
    role = obj.get_role_name() or ''
    element = {'name': name, 'role': role, 'atspi_obj': obj}
    try:
        comp = obj.get_component_iface()
        if comp:
            rect = comp.get_extents(Atspi.CoordType.SCREEN)
            if rect:
                element['x'] = rect.x + (rect.width // 2 if rect.width else 0)
                element['y'] = rect.y + (rect.height // 2 if rect.height else 0)
    except Exception:
        pass
    return element


def _find_conversation_container(doc):
    markers = ('conversation', 'transcript', 'chat history', 'message list', 'messages')
    best = None
    for obj, depth in _walk_accessible(doc, max_depth=12):
        signature = _node_signature(obj)
        if any(marker in signature for marker in markers):
            best = obj
    return best or doc


def _find_copy_button_in_scope(scope) -> Optional[dict]:
    buttons = [
        element for element in find_elements(scope, max_depth=10)
        if 'button' in element.get('role', '')
    ]
    if not buttons:
        return None

    preferred = []
    fallback = []
    for button in buttons:
        name = (button.get('name') or '').strip().lower()
        if not name:
            fallback.append(button)
            continue
        if 'copy' not in name:
            continue
        if name in {'copy response', 'copy', 'copy contents'}:
            preferred.append(button)
        elif name not in {'copy code', 'copy message', 'copy message to clipboard'}:
            fallback.append(button)

    candidates = preferred or fallback
    if not candidates:
        return None
    candidates.sort(key=lambda button: button.get('y', 0))
    return candidates[-1]


def _select_chatgpt_last_assistant_copy_button(doc) -> Tuple[Optional[dict], Dict[str, Any]]:
    conversation = _find_conversation_container(doc)
    assistant_groups = []

    for obj, depth in _walk_accessible(conversation, max_depth=18):
        markers = _role_markers(obj)
        if 'assistant' not in markers and 'presentation' not in markers:
            continue
        button = _find_copy_button_in_scope(obj)
        if not button:
            continue
        group = _element_from_obj(obj)
        group['depth'] = depth
        group['copy_button'] = button
        assistant_groups.append(group)

    if not assistant_groups:
        return None, {
            "conversation_found": conversation is not doc,
            "assistant_groups_found": 0,
        }

    assistant_groups.sort(key=lambda group: (group.get('y', 0), group.get('depth', 0)))
    last_group = assistant_groups[-1]
    return last_group['copy_button'], {
        "conversation_found": conversation is not doc,
        "assistant_groups_found": len(assistant_groups),
        "assistant_group_role": last_group.get('role'),
        "assistant_group_name": last_group.get('name'),
    }


def _clipboard_env(display: Optional[str] = None) -> Dict[str, str]:
    env = {**os.environ}
    if display:
        env['DISPLAY'] = display
    return env


def _read_clipboard(display: Optional[str] = None) -> Tuple[Optional[str], str]:
    env = _clipboard_env(display)
    try:
        result = subprocess.run(
            ['xclip', '-selection', 'clipboard', '-o'],
            capture_output=True,
            text=True,
            timeout=5.0,
            env=env,
        )
    except FileNotFoundError:
        logger.warning("xclip not installed for clipboard read")
        return None, 'xclip'
    except Exception as exc:
        logger.warning("xclip clipboard read failed: %s", exc)
        return None, 'xclip'

    if result.returncode != 0:
        logger.warning("xclip clipboard read failed: %s", result.stderr.strip())
        return None, 'xclip'
    return (result.stdout or None), 'xclip'


def _match_element(element: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
    name = (element.get('name') or '').strip().lower()
    role = element.get('role', '')

    if 'name' in criteria and name != str(criteria['name']).lower():
        return False
    if 'name_contains' in criteria:
        pats = criteria['name_contains']
        if isinstance(pats, str):
            pats = [pats]
        if not any(str(p).lower() in name for p in pats):
            return False
    if 'role' in criteria and role != criteria['role']:
        return False
    if 'role_contains' in criteria and str(criteria['role_contains']) not in role:
        return False
    return True


def _click_button(button: Dict[str, Any]) -> bool:
    if button.get('atspi_obj') and atspi_click(button):
        return True
    return inp.click_at(int(button['x']), int(button['y']))


def _scroll_to_bottom_for_extract(platform: str, doc) -> str:
    config = get_platform_config(platform)
    scroll_spec = config.get('scroll_to_bottom')
    if not scroll_spec:
        scroll_spec = config.get('element_map', {}).get('scroll_to_bottom')

    if isinstance(scroll_spec, dict) and doc:
        elements = find_elements(doc)
        matches = [
            element for element in elements
            if 'button' in element.get('role', '') and _match_element(element, scroll_spec)
        ]
        if matches:
            _click_button(matches[-1])
            return 'yaml_button'

    key = scroll_spec if isinstance(scroll_spec, str) and scroll_spec else 'ctrl+End'
    inp.press_key(key)
    return key


def _find_copy_buttons_by_name(doc, needle: str) -> Tuple[list, list]:
    elements = find_elements(doc)
    buttons = [
        element for element in elements
        if 'button' in element.get('role', '')
        and needle in (element.get('name') or '').lower()
    ]
    buttons.sort(key=lambda element: (element.get('y', 0), element.get('x', 0)))
    return buttons, elements


def _click_and_read_clipboard(button: dict, display: Optional[str] = None,
                              initial_wait: float = 0.5) -> Tuple[Optional[str], str]:
    click_method = 'atspi' if _click_button(button) else 'xdotool'
    time.sleep(initial_wait)
    content, read_method = _read_clipboard(display)
    return content, f"{click_method}+{read_method}"


def _try_gemini_deep_research_extract(platform, firefox, doc, display: Optional[str] = None):
    """Gemini Deep Research: extract via Share & Export → Copy Content.

    Deep Research responses live in an immersive view. The regular Copy
    button only gets the completion message. The full report requires:
    1. Click "Share & Export" button
    2. Click "Copy Content" in the dropdown
    3. Read clipboard

    Returns content string or None if not a Deep Research response.
    """
    if platform != 'gemini':
        return None, 'not_applicable'

    elements = find_elements(doc)
    share_export = [e for e in elements
                    if 'share' in (e.get('name') or '').lower()
                    and 'export' in (e.get('name') or '').lower()
                    and 'button' in e.get('role', '')]
    if not share_export:
        return None, 'not_applicable'

    logger.info("Gemini Deep Research detected — using Share & Export extraction")

    # Kill stale xsel (blocks Firefox clipboard writes)
    subprocess.run(['pkill', '-f', 'xsel.*clipboard'], capture_output=True, timeout=3)
    time.sleep(0.3)

    # Click Share & Export
    btn = share_export[0]
    if btn.get('atspi_obj') and atspi_click(btn):
        logger.info("Clicked Share & Export via AT-SPI")
    else:
        inp.click_at(int(btn['x']), int(btn['y']))
    time.sleep(1.0)

    # Find and click Copy Content
    doc2 = atspi.get_platform_document(firefox, platform) or doc
    elems2 = find_elements(doc2)
    copy_content = [e for e in elems2
                    if 'copy' in (e.get('name') or '').lower()
                    and 'content' in (e.get('name') or '').lower()]
    if not copy_content:
        logger.warning("Share & Export opened but 'Copy Content' not found")
        inp.press_key('Escape')
        return None, 'share_export_no_copy_content'

    cc = copy_content[0]
    content, strategy = _click_and_read_clipboard(cc, display=display)
    if content and len(content) > 200:
        logger.info("Gemini Deep Research extracted via %s: %d chars", strategy, len(content))
        return content, strategy

    logger.warning("Copy Content clicked but clipboard empty")
    return None, strategy


def _try_claude_artifact_extract(platform, firefox, doc, display: Optional[str] = None):
    """Claude artifact extraction: use artifact panel Copy button for full content.

    Claude artifacts have a side panel with its own Copy button that copies
    the FULL artifact content (~34K chars). The conversation Copy button
    only gets a summary (~2K chars).

    Detection: look for a heading containing a file extension indicator
    (e.g., '... . MD', '... . PY') which marks the artifact panel header.
    The artifact Copy button is nearby at high x coordinates (right side panel).

    Returns full artifact content, or None if no artifact detected.
    """
    if platform != 'claude':
        return None, 'not_applicable'

    elements = find_elements(doc)

    # Detect artifact panel: heading with file extension suffix
    _ARTIFACT_SUFFIXES = (' . MD', ' . PY', ' . JS', ' . TS', ' . HTML',
                          ' . CSS', ' . JSON', ' . YAML', ' . YML',
                          ' . SH', ' . TXT', ' . CSV', ' . XML',
                          ' . md', ' . py', ' . js', ' . ts', ' . html')
    artifact_heading = None
    for e in elements:
        if e.get('role') == 'heading':
            name = e.get('name', '')
            # Check for "title . EXT" pattern (Unicode middot)
            if '\u00b7' in name or any(name.upper().endswith(s.upper()) for s in _ARTIFACT_SUFFIXES):
                artifact_heading = e
                break

    if not artifact_heading:
        return None, 'not_applicable'

    logger.info("Claude artifact detected: %r", artifact_heading.get('name', '')[:80])

    # Find the artifact panel Copy button: push button named 'Copy' at high x
    # (right side panel, x > 800). The conversation Copy is at low x (~400).
    artifact_copy = None
    heading_y = artifact_heading.get('y', 0)
    for e in elements:
        if e.get('role') in ('push button', 'toggle button') and \
           (e.get('name') or '').strip().lower() == 'copy':
            ex = e.get('x', 0)
            ey = e.get('y', 0)
            # Artifact panel Copy: high x (right side), near the heading y
            if ex > 800 and abs(ey - heading_y) < 100:
                artifact_copy = e
                break

    if not artifact_copy:
        # Fallback: any Copy button with x > 1000 (deep in artifact panel)
        for e in elements:
            if e.get('role') in ('push button', 'toggle button') and \
               (e.get('name') or '').strip().lower() == 'copy' and \
               e.get('x', 0) > 1000:
                artifact_copy = e
                break

    if not artifact_copy:
        logger.warning("Artifact heading found but no artifact Copy button")
        return None, 'artifact_copy_not_found'

    logger.info("Clicking artifact Copy at (%s, %s)",
                artifact_copy.get('x'), artifact_copy.get('y'))

    # Kill stale xsel
    subprocess.run(['pkill', '-f', 'xsel.*clipboard'], capture_output=True, timeout=3)
    time.sleep(0.3)
    content, strategy = _click_and_read_clipboard(artifact_copy, display=display)
    if content and len(content) > 500:
        logger.info("Claude artifact extracted via %s: %d chars", strategy, len(content))
        return content, strategy

    logger.warning("Artifact Copy clicked but clipboard empty or too short")
    return None, strategy


def _try_perplexity_deep_research_extract(platform, firefox, doc, display: Optional[str] = None):
    """Perplexity Deep Research: prefer 'Copy contents' when present."""
    if platform != 'perplexity':
        return None, 'not_applicable'

    copy_contents, _ = _find_copy_buttons_by_name(doc, 'copy contents')
    if not copy_contents:
        return None, 'not_applicable'

    logger.info("Perplexity Deep Research detected — using last 'Copy contents' button")
    btn = copy_contents[-1]
    content, strategy = _click_and_read_clipboard(btn, display=display)
    if content:
        logger.info("Perplexity Deep Research extracted via %s: %d chars", strategy, len(content))
        return content, strategy

    logger.warning("'Copy contents' clicked but clipboard empty")
    return None, strategy


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
                         neo4j_mod=None, complete: bool = False,
                         display: Optional[str] = None) -> Dict[str, Any]:
    """Extract latest response via clipboard (click Copy, read clipboard)."""
    if not inp.switch_to_platform(platform):
        return {"error": f"Could not switch to {platform} tab", "platform": platform}

    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        return {"success": False, "error": "Firefox not found", "platform": platform}
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"success": False, "error": f"Could not find {platform} document", "platform": platform}
    _scroll_to_bottom_for_extract(platform, doc)
    time.sleep(0.5)

    doc = atspi.get_platform_document(firefox, platform) or doc
    url = atspi.get_document_url(doc)

    claude_art, claude_strategy = _try_claude_artifact_extract(platform, firefox, doc, display=display)
    if claude_art:
        quality = _assess_extraction(claude_art, platform,
                                      find_elements(atspi.get_platform_document(firefox, platform) or doc))
        result = {
            "success": True, "platform": platform, "content": claude_art,
            "length": len(claude_art), "has_artifacts": True, "url": url,
            "extraction_method": "claude_artifact_panel_copy",
            "copy_buttons_found": 0, "quality": quality,
        }
        if complete and redis_client:
            redis_client.delete(node_key(f"pending_prompt:{platform}"))
            redis_client.delete(node_key(f"plan:{platform}"))
            for suffix in [f"plan:current:{platform}", f"checkpoint:{platform}:inspect",
                           f"checkpoint:{platform}:attach", f"response_reviewed:{platform}"]:
                redis_client.delete(node_key(suffix))
            display = os.environ.get('DISPLAY', ':0')
            redis_client.delete(f"taey:plan_active:{display}")
            try:
                save_path = f"/tmp/hmm_response_{platform}.json"
                with open(save_path, 'w') as f:
                    f.write(claude_art)
                result["save_path"] = save_path
            except Exception:
                pass
        if neo4j_mod and url:
            try:
                sid = mid = None
                pending_json = redis_client.get(node_key(f"pending_prompt:{platform}")) if redis_client else None
                if pending_json:
                    pending = json.loads(pending_json)
                    sid = pending.get('session_id')
                    mid = pending.get('message_id')
                if not sid:
                    sid = neo4j_client.get_or_create_session(platform, url)
                if sid:
                    rid = neo4j_mod.add_message(sid, 'assistant', claude_art[:5000])
                    result["neo4j"] = {"session_id": sid, "response_id": rid, "user_message_id": mid}
            except Exception as e:
                logger.warning("Neo4j store failed (Claude artifact): %s", e)
        try:
            ingest = auto_ingest(platform, claude_art, url=url,
                                 session_id=result.get('neo4j', {}).get('session_id'),
                                 metadata={"extraction_method": "claude_artifact"})
            result["ingest"] = ingest
        except Exception as e:
            logger.warning("Auto-ingest failed (Claude artifact): %s", e)
        return result

    content = None
    extraction_method = "last_copy_button"
    copy_buttons = []
    all_elements = find_elements(doc)

    ppl_dr_content, _ = _try_perplexity_deep_research_extract(platform, firefox, doc, display=display)
    if ppl_dr_content:
        content = ppl_dr_content
        extraction_method = "perplexity_copy_contents"
        copy_buttons, all_elements = _find_copy_buttons_by_name(doc, 'copy contents')
    else:
        copy_buttons, all_elements = _find_copy_buttons_by_name(doc, 'copy')
        if not copy_buttons:
            return {
                "success": False,
                "error": "No copy buttons found",
                "platform": platform,
                "content": "",
            }
        content, _ = _click_and_read_clipboard(copy_buttons[-1], display=display)

    if not content:
        return {
            "success": False,
            "error": "No response in clipboard after Copy",
            "platform": platform,
            "copy_buttons_found": len(copy_buttons),
            "content": "",
        }

    quality = _assess_extraction(content, platform, all_elements)

    # Store in Neo4j
    neo4j_stored = None
    if neo4j_mod:
        try:
            sid = uid = None
            pending_json = redis_client.get(node_key(f"pending_prompt:{platform}")) if redis_client else None
            if pending_json:
                pending = json.loads(pending_json)
                sid = pending.get('session_id')
                uid = pending.get('message_id')
            # Fallback: create/find session from URL if pending_prompt expired or missing
            if not sid and url:
                sid = neo4j_client.get_or_create_session(platform, url)
                logger.info("Neo4j session from URL fallback: %s", sid)
            if sid:
                rid = neo4j_mod.add_message(sid, 'assistant', content)
                if rid and uid:
                    _link_response(neo4j_mod, rid, uid)
                neo4j_stored = {"session_id": sid, "response_id": rid, "user_message_id": uid}
        except (json.JSONDecodeError, TypeError, KeyError, Exception) as e:
            logger.warning("Neo4j store failed: %s", e)

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
        # Two paths: SET-based (new) and SCAN-based (old) — same as monitor
        set_key = node_key("active_session_ids")
        keys_to_check = set()
        try:
            keys_to_check.update(redis_client.smembers(set_key))
        except Exception:
            pass
        # Also SCAN for plain session keys (backward compat with old MCP servers)
        try:
            cursor = 0
            while True:
                cursor, found = redis_client.scan(cursor, match="taey:*:active_session:*", count=100)
                keys_to_check.update(found)
                if cursor == 0:
                    break
        except Exception:
            pass
        for skey in keys_to_check:
            try:
                sdata = redis_client.get(skey)
                if sdata:
                    sess = json.loads(sdata)
                    if sess.get('platform') == platform:
                        redis_client.delete(skey)
                        redis_client.srem(set_key, skey)
                else:
                    redis_client.srem(set_key, skey)
            except Exception:
                pass
        if content:
            save_path = f"/tmp/hmm_response_{platform}.json"
            try:
                with open(save_path, 'w') as f:
                    f.write(content)
            except Exception:
                save_path = None

    # Auto-ingest: save to corpus + trigger ISMA pipeline
    ingest_result = None
    if content:
        try:
            ingest_result = auto_ingest(
                platform, content, url=url,
                session_id=neo4j_stored.get('session_id') if neo4j_stored else None,
                metadata={"extraction_method": extraction_method})
        except Exception as e:
            logger.warning("Auto-ingest failed: %s", e)

    return {
        "success": True, "platform": platform, "content": content,
        "length": len(content), "has_artifacts": '```' in content,
        "url": url, "copy_buttons_found": len(copy_buttons),
        "plan_consumed": plan_consumed, "neo4j": neo4j_stored,
        "save_path": save_path, "quality": quality,
        "ingest": ingest_result, "extraction_method": extraction_method,
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
