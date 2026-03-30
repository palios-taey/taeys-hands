"""taey_inspect - Scan platform AT-SPI tree and return visible elements."""

import fnmatch
import json
import os
import time
import logging
from typing import Any, Dict, List, Tuple

import yaml

from core import atspi, input as inp, clipboard
from core.tree import (find_elements, filter_useful_elements, find_copy_buttons,
                       detect_chrome_y, compute_structure_hash)
from core.interact import cache_elements, strip_atspi_obj
from core.platforms import BASE_URLS, SCREEN_HEIGHT
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

_FILE_EXTENSIONS = ('.md', '.py', '.txt', '.pdf', '.png', '.jpg', '.jpeg',
                    '.csv', '.json', '.xml', '.html', '.zip', '.docx')


def _click_new_chat_gemini():
    """Click Gemini's 'New chat' button/link via AT-SPI after page load.

    Gemini's /app URL redirects to the last conversation. This function
    finds and clicks the 'New chat' element in the sidebar to guarantee
    a fresh session.
    """
    firefox = atspi.find_firefox_for_platform('gemini')
    if not firefox:
        logger.warning("Gemini fresh_session: Firefox not found for New chat click")
        return
    doc = atspi.get_platform_document(firefox, 'gemini')
    if not doc:
        logger.warning("Gemini fresh_session: document not found for New chat click")
        return

    from gi.repository import Atspi as _Atspi

    def _find_new_chat(obj, depth=0):
        if depth > 20:
            return None
        try:
            name = (obj.get_name() or '').strip().lower()
            role = obj.get_role_name() or ''
            if name == 'new chat' and role in ('link', 'push button'):
                return obj
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child:
                    found = _find_new_chat(child, depth + 1)
                    if found:
                        return found
        except Exception:
            pass
        return None

    new_chat = _find_new_chat(doc)
    if new_chat:
        try:
            action = new_chat.get_action_iface()
            if action and action.get_n_actions() > 0:
                action.do_action(0)
                logger.info("Gemini fresh_session: clicked 'New chat' via AT-SPI")
                time.sleep(3.0)
                return
        except Exception:
            pass
        # Fallback: coordinate click
        try:
            comp = new_chat.get_component_iface()
            if comp:
                rect = comp.get_extents(_Atspi.CoordType.SCREEN)
                if rect and rect.width > 0:
                    cx = rect.x + rect.width // 2
                    cy = rect.y + rect.height // 2
                    inp.click_at(cx, cy)
                    logger.info("Gemini fresh_session: clicked 'New chat' at (%d, %d)", cx, cy)
                    time.sleep(3.0)
                    return
        except Exception:
            pass
    logger.warning("Gemini fresh_session: 'New chat' element not found — may be on stale conversation")


def _detect_attachments(elements: list, all_elements: list = None) -> dict | None:
    """Detect existing file attachments from element list."""
    remove_buttons, file_chips = [], []
    for e in elements:
        name = (e.get('name') or '').strip()
        role = e.get('role', '')
        if 'button' in role and name.lower().startswith('remove'):
            remove_buttons.append(e)
        if name and any(name.lower().endswith(ext) for ext in _FILE_EXTENSIONS):
            if role in ('heading', 'push button', 'toggle button', 'link'):
                file_chips.append(name)

    # NOTE: Removed unnamed button fallback. Was causing false positives
    # (ChatGPT sidebar buttons misdetected as file chips).
    # Attachments are detected ONLY by named "Remove" buttons or file extension chips.

    if not remove_buttons and not file_chips:
        return None

    count = max(len(remove_buttons), len(file_chips))
    warning = (f"{count} file(s) already attached. "
               "Remove stale files before attaching new ones to avoid duplicates."
               if remove_buttons else
               f"{count} file(s) already attached (no remove button). "
               "Context BLEEDS between messages - start a FRESH session.")
    return {
        'count': count, 'files': file_chips,
        'remove_buttons': [{'x': b['x'], 'y': b['y'], 'name': b.get('name', '')}
                           for b in remove_buttons],
        'WARNING': warning,
    }


def _match_element(element: dict, criteria: dict) -> bool:
    """Check if element matches all criteria (name, name_contains, name_pattern, role, states)."""
    name = (element.get('name') or '').strip()
    name_lower = name.lower()
    role = element.get('role', '')
    states = set(s.lower() for s in element.get('states', []))

    if 'name' in criteria and name_lower != str(criteria['name']).lower():
        return False
    if 'name_contains' in criteria:
        pats = criteria['name_contains']
        if isinstance(pats, str):
            pats = [pats]
        if not any(str(p).lower() in name_lower for p in pats):
            return False
    if 'name_pattern' in criteria:
        pats = criteria['name_pattern']
        if isinstance(pats, str):
            pats = [pats]
        if not any(fnmatch.fnmatch(name_lower, str(p).lower()) for p in pats):
            return False
    if 'role' in criteria and role != criteria['role']:
        return False
    if 'role_contains' in criteria and str(criteria['role_contains']) not in role:
        return False
    if 'states_include' in criteria:
        if not set(s.lower() for s in criteria['states_include']).issubset(states):
            return False
    return True


def _apply_element_filter(elements: list, config: dict) -> Tuple[list, list]:
    """YAML-driven element filtering: exclude noise, label known controls, flag NEW.

    NO coordinate-based filtering. Every element is matched by exact name/role
    from YAML. Anything not matched is flagged NEW and surfaced.
    """
    ef = config.get('element_filter', {})
    emap = config.get('element_map', {})
    snav = config.get('sidebar_nav', [])
    exclude = ef.get('exclude', {})

    excl_names = set(n.lower() for n in exclude.get('names', []))
    excl_contains = [str(p).lower() for p in exclude.get('name_contains', [])]
    excl_roles = set(exclude.get('roles', []))

    _IMP_STATES = {'editable', 'checked', 'selected', 'pressed', 'focused'}
    result, new_elements = [], []

    for e in elements:
        name = (e.get('name') or '').strip()
        name_lower = name.lower()
        role = e.get('role', '')
        text = (e.get('text') or '').lower()
        states = set(s.lower() for s in e.get('states', []))

        # Known controls FIRST — element_map and sidebar_nav survive role exclusion
        matched_semantic = None
        for sem, criteria in emap.items():
            if isinstance(criteria, dict) and _match_element(e, criteria):
                matched_semantic = sem
                break
        if matched_semantic:
            e['semantic'] = matched_semantic
            result.append(e)
            continue

        if name and any(_match_element(e, nav) for nav in snav):
            e['semantic'] = 'sidebar_nav'
            result.append(e)
            continue

        # Exclude check (exact name, substring, role — all YAML-driven)
        # Runs AFTER known control matching so sidebar_nav/element_map survive
        if role in excl_roles or name_lower in excl_names:
            continue
        if any(p in name_lower for p in excl_contains):
            continue
        if not name and text and any(p in text for p in excl_contains):
            continue

        # Not matched — noise or NEW?
        # Unnamed elements without important states are noise
        if not name and not (states & _IMP_STATES):
            continue
        e['NEW'] = True
        result.append(e)
        new_elements.append(e)

    # Cap copy buttons to last 3 (by list order — BFS traversal is top-to-bottom)
    copy_idxs = [i for i, e in enumerate(result) if 'copy' in e.get('semantic', '')]
    if len(copy_idxs) > 3:
        drop = set(copy_idxs[:-3])
        result = [e for i, e in enumerate(result) if i not in drop]

    return result, new_elements


def _check_structure_change(platform: str, elements: list, redis_client) -> dict | None:
    if not redis_client:
        return None
    current_hash = compute_structure_hash(elements, screen_height=SCREEN_HEIGHT)
    key = node_key(f"structure_fingerprint:{platform}")
    stored = redis_client.get(key)
    redis_client.set(key, current_hash)
    if stored is None or stored == current_hash:
        return None
    return {
        'structure_changed': True, 'previous_hash': stored, 'current_hash': current_hash,
        'WARNING': "Platform UI structure has changed. Verify element positions.",
    }


def handle_inspect(platform: str, redis_client, scroll: str = "bottom",
                    fresh_session: bool = False, **kwargs) -> Dict[str, Any]:
    """Inspect a platform: switch tab, scan AT-SPI, return elements."""
    result = {'platform': platform, 'success': False, 'error': None,
              'url': None, 'state': {}, 'controls': {}}

    # Fresh session: navigate to base URL
    if fresh_session:
        base_url = BASE_URLS.get(platform)
        if not base_url:
            result['error'] = f"No base URL for {platform}"
            return result
        if not inp.switch_to_platform(platform):
            result['error'] = f"Failed to switch to {platform} tab"
            return result
        inp.press_key('Escape')
        time.sleep(0.3)
        inp.press_key('ctrl+l')
        time.sleep(0.2)
        inp.press_key('ctrl+a')
        time.sleep(0.3)
        if not inp.clipboard_paste(base_url):
            result['error'] = f"URL paste failed for: {base_url}"
            return result
        time.sleep(0.1)
        inp.press_key('Return')
        time.sleep(8.0)

        # Gemini redirects /app to the last conversation. Click "New chat"
        # via AT-SPI after page load to guarantee a fresh session.
        if platform == 'gemini':
            _click_new_chat_gemini()

        # Grok SPA: pushState navigation doesn't update AT-SPI DocURL.
        # If we navigated to grok.com but the AT-SPI document still shows
        # a conversation path (/c/...), force F5 reload to reset the tree.
        if platform == 'grok':
            _ff = atspi.find_firefox_for_platform(platform)
            if _ff:
                _doc = atspi.get_platform_document(_ff, platform)
                if _doc:
                    _url = atspi.get_document_url(_doc) or ''
                    if '/c/' in _url:
                        logger.info(f"Grok SPA stale tree: {_url} — forcing F5 reload")
                        inp.press_key('F5')
                        time.sleep(3.0)

        inp.press_key('End')
        time.sleep(1.0)
        result['fresh_session'] = True
        result['navigated_to'] = base_url

    # Plan-based navigation
    target_url = None
    already_navigated = fresh_session
    plan = plan_id = None

    if redis_client:
        plan_id = redis_client.get(node_key(f"plan:current:{platform}"))
        if plan_id:
            plan_json = redis_client.get(node_key(f"plan:{plan_id}"))
            if plan_json:
                try:
                    plan = json.loads(plan_json)
                    cs = plan.get('current_state', {}) or {}
                    session = cs.get('session_url') or plan.get('session', '')
                    already_navigated = already_navigated or plan.get('navigated', False)
                    if session == 'new':
                        target_url = BASE_URLS.get(platform)
                    elif session.startswith('http'):
                        target_url = session
                except json.JSONDecodeError:
                    pass

    # Navigate or switch tab
    if target_url and not already_navigated and scroll != 'none':
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
            result['error'] = f"URL paste failed"
            return result
        time.sleep(0.1)
        inp.press_key('Return')
        time.sleep(10.0)
        if scroll == 'top':
            inp.press_key('Home')
        elif scroll != 'none':
            inp.scroll_to_bottom()
        time.sleep(1.0)
        if plan and redis_client and plan_id:
            plan['navigated'] = True
            redis_client.set(node_key(f"plan:{plan_id}"), json.dumps(plan))
    elif scroll == 'none':
        pass  # Pure scan: no tab switch, no scroll
    else:
        if not inp.switch_to_platform(platform):
            result['error'] = f"Failed to switch to {platform} tab"
            return result
        time.sleep(0.5)
        if scroll == 'top':
            inp.press_key('Home')
            time.sleep(0.5)
        else:
            inp.press_key('End')
            time.sleep(0.5)

    # AT-SPI scan
    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        result['error'] = "Firefox not found in AT-SPI tree"
        return result

    # Load YAML config early — needed for both local and remote scanning
    try:
        with open(os.path.join(PLATFORMS_DIR, f'{platform}.yaml')) as _f:
            _pcfg = yaml.safe_load(_f) or {}
    except Exception:
        _pcfg = {}

    # Remote Firefox (multi-display mode): use subprocess scanner
    if getattr(firefox, '_remote', False):
        scan_result = atspi._subprocess_scan(platform, 'scan')
        if not scan_result or scan_result.get('error'):
            result['error'] = scan_result.get('error', 'Subprocess scan failed') if scan_result else 'Subprocess scan failed'
            return result

        url = scan_result.get('url')
        result['url'] = url
        elements_json = scan_result.get('elements', [])

        # Truncate long names
        for e in elements_json:
            name = e.get('name', '')
            if len(name) > 200:
                e['name'] = name[:200] + '...'

        pre_filter = len(elements_json)
        noise_removed = 0
        if _pcfg.get('element_filter') or _pcfg.get('element_map'):
            elements_json, new_elements = _apply_element_filter(elements_json, _pcfg)
            noise_removed = pre_filter - len(elements_json)
            if new_elements:
                result['new_elements'] = [{'name': e.get('name', ''), 'role': e.get('role', ''),
                                           'x': e.get('x'), 'y': e.get('y')} for e in new_elements]
        else:
            noise = _pcfg.get('inspect_noise', {})
            if noise:
                _excl = noise.get('exclude_name_contains', [])
                elements_json = [e for e in elements_json if not any(p in e.get('name', '') for p in _excl)]
            noise_removed = pre_filter - len(elements_json)

        copy_count = scan_result.get('copy_button_count', 0)
        result['state']['copy_button_count'] = copy_count
        result['state']['element_count'] = len(elements_json)
        result['state']['total_before_filter'] = scan_result.get('total', pre_filter)
        if noise_removed:
            result['state']['noise_removed'] = noise_removed
        result['controls'] = elements_json

        # Attachment detection (from elements_json directly)
        attached = _detect_attachments(elements_json, elements_json)
        if attached:
            result['attachments'] = attached

        # Structure change detection
        sc = _check_structure_change(platform, elements_json, redis_client)
        if sc:
            result['structure_change'] = sc

        # Store in Redis
        if redis_client:
            redis_client.set(node_key(f"inspect:{platform}"), json.dumps({
                'url': url, 'state': result['state'],
                'controls': elements_json, 'timestamp': time.time(),
            }))
            copy_btn_count = result.get('state', {}).get('copy_button_count', 0)
            elem_count = result.get('state', {}).get('element_count', 0)
            redis_client.setex(node_key(f"checkpoint:{platform}:inspect"), 1800, json.dumps({
                'url': url, 'copy_button_count': copy_btn_count,
                'element_count': elem_count, 'timestamp': time.time(),
            }))

        result['multi_display'] = True
        result['display'] = firefox._display
        result['success'] = True
        result['atspi_note'] = "Menu items (Back, Forward, Reload) are browser chrome - ignore them."

        # Plan validation
        if plan and plan.get('required_state'):
            req = plan['required_state']
            cur = plan.get('current_state')
            pr = {'plan_id': plan_id, 'required_state': req,
                  'current_state': cur, 'status': plan.get('status', 'unknown')}
            if cur is None:
                pr['WARNING'] = "PLAN EXISTS but current_state NOT SET. Read elements, call taey_plan(update)."
            result['plan_requirements'] = pr

        return result

    # Local Firefox (same display): use direct AT-SPI
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        result['error'] = f"Could not find {platform} document"
        return result

    url = atspi.get_document_url(doc)
    result['url'] = url

    chrome_y = detect_chrome_y(doc)
    fences = _pcfg.get('fence_after', [])
    all_elements = find_elements(doc, fence_after=fences)
    elements = filter_useful_elements(all_elements, chrome_y=chrome_y)
    cache_elements(platform, all_elements)
    elements_json = strip_atspi_obj(elements)

    # Truncate long names
    for e in elements_json:
        name = e.get('name', '')
        if len(name) > 200:
            e['name'] = name[:200] + '...'

    pre_filter = len(elements_json)
    noise_removed = 0
    if _pcfg.get('element_filter') or _pcfg.get('element_map'):
        elements_json, new_elements = _apply_element_filter(elements_json, _pcfg)
        noise_removed = pre_filter - len(elements_json)
        if new_elements:
            result['new_elements'] = [{'name': e.get('name', ''), 'role': e.get('role', ''),
                                       'x': e.get('x'), 'y': e.get('y')} for e in new_elements]
    else:
        noise = _pcfg.get('inspect_noise', {})
        if noise:
            _excl = noise.get('exclude_name_contains', [])
            elements_json = [e for e in elements_json if not any(p in e.get('name', '') for p in _excl)]
        noise_removed = pre_filter - len(elements_json)

    copy_buttons = find_copy_buttons(all_elements)
    result['state']['copy_button_count'] = len(copy_buttons)
    result['state']['element_count'] = len(elements_json)
    result['state']['total_before_filter'] = len(all_elements)
    if noise_removed:
        result['state']['noise_removed'] = noise_removed
    result['controls'] = elements_json

    # Attachment detection
    all_json = strip_atspi_obj(all_elements)
    attached = _detect_attachments(elements_json, all_json)
    if attached:
        result['attachments'] = attached

    # Structure change detection
    sc = _check_structure_change(platform, elements_json, redis_client)
    if sc:
        result['structure_change'] = sc

    # Store in Redis
    if redis_client:
        redis_client.set(node_key(f"inspect:{platform}"), json.dumps({
            'url': url, 'state': result['state'],
            'controls': elements_json, 'timestamp': time.time(),
        }))
        redis_client.setex(node_key(f"checkpoint:{platform}:inspect"), 1800, json.dumps({
            'url': url, 'copy_button_count': len(copy_buttons),
            'element_count': len(elements), 'timestamp': time.time(),
        }))

    result['success'] = True
    result['atspi_note'] = "Menu items (Back, Forward, Reload) are browser chrome - ignore them."

    # Plan validation
    if plan and plan.get('required_state'):
        req = plan['required_state']
        cur = plan.get('current_state')
        pr = {'plan_id': plan_id, 'required_state': req,
              'current_state': cur, 'status': plan.get('status', 'unknown')}
        if cur is None:
            pr['WARNING'] = "PLAN EXISTS but current_state NOT SET. Read elements, call taey_plan(update)."
        else:
            unmet = []
            for field in ['model', 'mode']:
                rv = req.get(field)
                cv = (cur or {}).get(field)
                if rv and rv not in ('N/A', 'any') and rv != cv:
                    unmet.append(f"{field}: need '{rv}', have '{cv}'")
            req_tools = set(req.get('tools', []))
            cur_tools = set((cur or {}).get('tools', []))
            missing = req_tools - cur_tools
            if missing:
                unmet.append(f"tools: need {sorted(missing)}")
            pr['VALIDATED' if not unmet else 'UNMET'] = "All requirements met" if not unmet else unmet
        result['plan_requirements'] = pr

    return result
