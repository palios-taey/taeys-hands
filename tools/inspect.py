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

    # Unnamed file chips (Perplexity): unnamed buttons clustered above input
    if not remove_buttons and not file_chips and all_elements:
        entry_y = None
        for e in all_elements:
            if e.get('role') == 'entry' and 'editable' in e.get('states', []):
                entry_y = e.get('y', 0)
                break
        if entry_y:
            unnamed = [e for e in all_elements
                       if e.get('role') == 'push button'
                       and not (e.get('name') or '').strip()
                       and entry_y - 100 < e.get('y', 0) < entry_y - 10]
            if unnamed:
                remove_buttons = unnamed

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
    """YAML-driven element filtering: exclude noise, label known controls, flag NEW."""
    ef = config.get('element_filter', {})
    emap = config.get('element_map', {})
    snav = config.get('sidebar_nav', [])
    exclude = ef.get('exclude', {})
    sidebar_hist = ef.get('sidebar_history', {})

    excl_names = set(n.lower() for n in exclude.get('names', []))
    excl_contains = [str(p).lower() for p in exclude.get('name_contains', [])]
    excl_roles = set(exclude.get('roles', []))
    hist_x_max = sidebar_hist.get('x_max', 400)
    hist_roles = set(sidebar_hist.get('history_roles', []))
    hist_text_contains = [str(p).lower() for p in sidebar_hist.get('history_text_contains', [])]
    hist_name_contains = [str(p).lower() for p in sidebar_hist.get('history_name_contains', [])]

    _IMP_STATES = {'editable', 'checked', 'selected', 'pressed', 'focused'}
    result, new_elements = [], []

    for e in elements:
        name = (e.get('name') or '').strip()
        name_lower = name.lower()
        role = e.get('role', '')
        x = e.get('x', 0)
        text = (e.get('text') or '').lower()
        states = set(s.lower() for s in e.get('states', []))

        # Exclude check
        if role in excl_roles or name_lower in excl_names:
            continue
        if any(p in name_lower for p in excl_contains):
            continue
        if not name and text and any(p in text for p in excl_contains):
            continue

        # Element map (known controls)
        matched_semantic = None
        for sem, criteria in emap.items():
            if isinstance(criteria, dict) and _match_element(e, criteria):
                matched_semantic = sem
                break
        if matched_semantic:
            e['semantic'] = matched_semantic
            result.append(e)
            continue

        # Sidebar handling
        in_sidebar = x < hist_x_max
        if in_sidebar:
            if name:
                if any(_match_element(e, nav) for nav in snav):
                    e['semantic'] = 'sidebar_nav'
                    result.append(e)
                    continue
            if role in hist_roles:
                continue
            if hist_text_contains and any(p in text for p in hist_text_contains):
                continue
            if hist_name_contains and any(p in name_lower for p in hist_name_contains):
                continue
            if name and role in ('link', 'push button', 'toggle button'):
                e['NEW'] = True
                result.append(e)
                new_elements.append(e)
            continue

        # Not matched - noise or NEW?
        if not name and not (states & _IMP_STATES):
            continue
        if role == 'heading' and not in_sidebar:
            continue
        e['NEW'] = True
        result.append(e)
        new_elements.append(e)

    # Cap copy buttons to last 3
    copy_idxs = [(e.get('y', 0), i) for i, e in enumerate(result) if 'copy' in e.get('semantic', '')]
    if len(copy_idxs) > 3:
        copy_idxs.sort(key=lambda t: t[0])
        drop = set(idx for _y, idx in copy_idxs[:-3])
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
    firefox = atspi.find_firefox()
    if not firefox:
        result['error'] = "Firefox not found in AT-SPI tree"
        return result
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        result['error'] = f"Could not find {platform} document"
        return result

    url = atspi.get_document_url(doc)
    result['url'] = url

    chrome_y = detect_chrome_y(doc)
    all_elements = find_elements(doc)
    elements = filter_useful_elements(all_elements, chrome_y=chrome_y)
    cache_elements(platform, all_elements)
    elements_json = strip_atspi_obj(elements)

    # Truncate long names
    for e in elements_json:
        name = e.get('name', '')
        if len(name) > 200:
            e['name'] = name[:200] + '...'

    # YAML filtering
    try:
        with open(os.path.join(PLATFORMS_DIR, f'{platform}.yaml')) as _f:
            _pcfg = yaml.safe_load(_f) or {}
    except Exception:
        _pcfg = {}

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
