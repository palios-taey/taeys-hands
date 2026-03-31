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
from core.ingest import auto_ingest
from storage.redis_pool import node_key
from storage import neo4j_client

logger = logging.getLogger(__name__)


def _try_gemini_deep_research_extract(platform, firefox, doc):
    """Gemini Deep Research: extract via Share & Export → Copy Content.

    Deep Research responses live in an immersive view. The regular Copy
    button only gets the completion message. The full report requires:
    1. Click "Share & Export" button
    2. Click "Copy Content" in the dropdown
    3. Read clipboard

    Returns content string or None if not a Deep Research response.
    """
    if platform != 'gemini':
        return None

    elements = find_elements(doc)
    share_export = [e for e in elements
                    if 'share' in (e.get('name') or '').lower()
                    and 'export' in (e.get('name') or '').lower()
                    and 'button' in e.get('role', '')]
    if not share_export:
        return None

    logger.info("Gemini Deep Research detected — using Share & Export extraction")

    # Kill stale xsel (blocks Firefox clipboard writes)
    import subprocess
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
        return None

    clipboard.clear()
    time.sleep(0.1)
    cc = copy_content[0]
    if cc.get('atspi_obj') and atspi_click(cc):
        logger.info("Clicked Copy Content via AT-SPI")
    else:
        inp.click_at(int(cc['x']), int(cc['y']))
    time.sleep(2.0)

    content = clipboard.read()
    if content and len(content) > 200:
        logger.info("Gemini Deep Research extracted: %d chars", len(content))
        return content

    # AT-SPI click may not trigger clipboard — retry with xdotool
    clipboard.clear()
    inp.click_at(int(cc['x']), int(cc['y']))
    time.sleep(2.0)
    content = clipboard.read()
    if content and len(content) > 200:
        logger.info("Gemini Deep Research extracted (xdotool retry): %d chars", len(content))
        return content

    logger.warning("Copy Content clicked but clipboard empty")
    return None


def _try_claude_artifact_extract(platform, firefox, doc):
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
        return None

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
        return None

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
        return None

    logger.info("Clicking artifact Copy at (%s, %s)",
                artifact_copy.get('x'), artifact_copy.get('y'))

    # Kill stale xsel
    import subprocess
    subprocess.run(['pkill', '-f', 'xsel.*clipboard'], capture_output=True, timeout=3)
    time.sleep(0.3)

    clipboard.clear()
    time.sleep(0.1)

    if artifact_copy.get('atspi_obj') and atspi_click(artifact_copy):
        logger.info("Clicked artifact Copy via AT-SPI")
    else:
        inp.click_at(int(artifact_copy['x']), int(artifact_copy['y']))
        logger.info("Clicked artifact Copy via xdotool")
    time.sleep(2.0)

    content = clipboard.read()
    if content and len(content) > 500:
        logger.info("Claude artifact extracted: %d chars", len(content))
        return content

    # Retry with xdotool
    clipboard.clear()
    inp.click_at(int(artifact_copy['x']), int(artifact_copy['y']))
    time.sleep(2.0)
    content = clipboard.read()
    if content and len(content) > 500:
        logger.info("Claude artifact extracted (xdotool retry): %d chars", len(content))
        return content

    logger.warning("Artifact Copy clicked but clipboard empty or too short")
    return None


def _try_perplexity_deep_research_extract(platform, firefox, doc):
    """Perplexity Deep Research: extract full report via 'Copy contents' button.

    Deep Research responses have TWO copy buttons:
    - 'Copy' (summary only, ~2-7K chars) in the bottom action bar
    - 'Copy contents' (full report, ~17K+ chars) at the TOP of the report

    The 'Copy contents' button may not be visible without scrolling to top.
    If neither button is found, returns None (caller uses normal copy path).

    Historical note: commit 6759cbe first implemented this. The code was
    lost in a rebuild. This re-implements the same approach.
    """
    if platform != 'perplexity':
        return None

    elements = find_elements(doc)

    # Look for 'Copy contents' button (Deep Research indicator)
    copy_contents = [e for e in elements
                     if (e.get('name') or '').strip().lower() == 'copy contents'
                     and 'button' in e.get('role', '')]

    if not copy_contents:
        # Scroll to top — button is at top of report section
        inp.press_key('Home')
        time.sleep(1)
        doc = atspi.get_platform_document(firefox, platform) or doc
        elements = find_elements(doc)
        copy_contents = [e for e in elements
                         if (e.get('name') or '').strip().lower() == 'copy contents'
                         and 'button' in e.get('role', '')]

    if not copy_contents:
        # Not a Deep Research response (no 'Copy contents' button)
        return None

    logger.info("Perplexity Deep Research detected — using 'Copy contents' extraction")

    # Kill stale xsel
    import subprocess
    subprocess.run(['pkill', '-f', 'xsel.*clipboard'], capture_output=True, timeout=3)
    time.sleep(0.3)

    btn = copy_contents[0]
    clipboard.clear()
    time.sleep(0.1)

    if btn.get('atspi_obj') and atspi_click(btn):
        logger.info("Clicked 'Copy contents' via AT-SPI")
    else:
        inp.click_at(int(btn['x']), int(btn['y']))
        logger.info("Clicked 'Copy contents' via xdotool at (%s, %s)", btn['x'], btn['y'])
    time.sleep(2.0)

    content = clipboard.read()
    if content and len(content) > 500:
        logger.info("Perplexity Deep Research extracted: %d chars", len(content))
        return content

    # Retry with xdotool if AT-SPI click didn't trigger clipboard
    clipboard.clear()
    inp.click_at(int(btn['x']), int(btn['y']))
    time.sleep(2.0)
    content = clipboard.read()
    if content and len(content) > 500:
        logger.info("Perplexity Deep Research extracted (xdotool retry): %d chars", len(content))
        return content

    logger.warning("'Copy contents' clicked but clipboard empty or too short")
    return None


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

    # Scroll to absolute bottom FIRST, then get doc and scan.
    # Use Ctrl+End (not bare End) to guarantee absolute bottom —
    # bare End only scrolls within the focused element's context.
    # This is critical on Grok where the response copy button
    # is below the viewport after send (hmm_bot uses Ctrl+End).
    inp.press_key('ctrl+End')
    time.sleep(0.5)
    for _ in range(3):
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

    # Gemini Deep Research: extract via Share & Export → Copy Content
    dr_content = _try_gemini_deep_research_extract(platform, firefox, doc)
    if dr_content:
        quality = _assess_extraction(dr_content, platform,
                                      find_elements(atspi.get_platform_document(firefox, platform) or doc))
        result = {
            "success": True, "platform": platform, "content": dr_content,
            "length": len(dr_content), "has_artifacts": False, "url": url,
            "extraction_method": "gemini_deep_research_share_export",
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
                    f.write(dr_content)
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
                # Fallback: create/find session from URL if pending_prompt expired or missing
                if not sid:
                    sid = neo4j_client.get_or_create_session(platform, url)
                    logger.info("Neo4j session from URL fallback: %s", sid)
                if sid:
                    rid = neo4j_mod.add_message(sid, 'assistant', dr_content[:5000])
                    result["neo4j"] = {"session_id": sid, "response_id": rid, "user_message_id": mid}
            except Exception as e:
                logger.warning("Neo4j store failed (Deep Research): %s", e)
        # Auto-ingest: save to corpus + trigger ISMA pipeline
        try:
            ingest = auto_ingest(platform, dr_content, url=url,
                                 session_id=result.get('neo4j', {}).get('session_id'),
                                 metadata={"extraction_method": "gemini_deep_research"})
            result["ingest"] = ingest
        except Exception as e:
            logger.warning("Auto-ingest failed (Deep Research): %s", e)
        return result

    # Perplexity Deep Research: extract via 'Copy contents' button (full report)
    ppl_dr_content = _try_perplexity_deep_research_extract(platform, firefox, doc)
    if ppl_dr_content:
        quality = _assess_extraction(ppl_dr_content, platform,
                                      find_elements(atspi.get_platform_document(firefox, platform) or doc))
        result = {
            "success": True, "platform": platform, "content": ppl_dr_content,
            "length": len(ppl_dr_content), "has_artifacts": False, "url": url,
            "extraction_method": "perplexity_deep_research_copy_contents",
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
                    f.write(ppl_dr_content)
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
                    rid = neo4j_mod.add_message(sid, 'assistant', ppl_dr_content[:5000])
                    result["neo4j"] = {"session_id": sid, "response_id": rid, "user_message_id": mid}
            except Exception as e:
                logger.warning("Neo4j store failed (Perplexity Deep Research): %s", e)
        try:
            ingest = auto_ingest(platform, ppl_dr_content, url=url,
                                 session_id=result.get('neo4j', {}).get('session_id'),
                                 metadata={"extraction_method": "perplexity_deep_research"})
            result["ingest"] = ingest
        except Exception as e:
            logger.warning("Auto-ingest failed (Perplexity Deep Research): %s", e)
        return result

    # Claude artifact extraction: artifact panel Copy for full content
    claude_art = _try_claude_artifact_extract(platform, firefox, doc)
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

    # Extra scroll if needed — press Ctrl+End then End until positions stabilize
    inp.press_key('ctrl+End')
    time.sleep(0.3)
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
        inp.press_key('ctrl+End')
        time.sleep(0.3)
        for _ in range(3):
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
                metadata={"extraction_method": "clipboard_copy"})
        except Exception as e:
            logger.warning("Auto-ingest failed: %s", e)

    return {
        "success": True, "platform": platform, "content": content,
        "length": len(content), "has_artifacts": '```' in content,
        "url": url, "copy_buttons_found": len(copy_buttons),
        "plan_consumed": plan_consumed, "neo4j": neo4j_stored,
        "save_path": save_path, "quality": quality,
        "ingest": ingest_result,
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
