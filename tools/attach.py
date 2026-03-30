"""taey_attach - File attachment via AT-SPI button discovery + file dialogs."""

import fnmatch
import json
import os
import subprocess
import time
import logging
from typing import Any, Dict, List, Optional

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from core import atspi, input as inp
from core.config import get_platform_config, get_attach_trigger_key, get_element_spec, get_attach_method
from core.tree import (find_elements, find_menu_items,
                       filter_useful_elements, detect_chrome_y)
from core.interact import (extend_cache, find_element_at, atspi_click,
                           strip_atspi_obj, _element_cache, is_defunct)
from tools.click import handle_click
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)

_KNOWN_PLATFORMS = {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}

_FILE_EXTENSIONS = ('.md', '.py', '.txt', '.pdf', '.png', '.jpg', '.jpeg',
                    '.csv', '.json', '.xml', '.html', '.zip', '.docx')
_ALLOWED_DIRS = [os.path.expanduser('~'), '/tmp', '/var/spark']


def _set_attach_checkpoint(platform: str, file_path: str, redis_client):
    """Write attach checkpoint to Redis so validate_send knows attach completed."""
    if not redis_client:
        return
    try:
        redis_client.setex(node_key(f"checkpoint:{platform}:attach"), 1800,
                           json.dumps({"attached_count": 1, "file": file_path,
                                       "timestamp": time.time()}))
    except Exception as e:
        logger.warning("Failed to set attach checkpoint: %s", e)


# --- Element matching (from inspect.py) ---

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


# --- Button discovery (YAML-driven) ---

def _find_attach_button(doc, platform: str = None):
    """Find attach button via YAML element spec, checking cache first then AT-SPI DFS."""
    # Get the element spec from YAML config
    spec = None
    if platform:
        trigger_key = get_attach_trigger_key(platform)
        if trigger_key:
            spec = get_element_spec(platform, trigger_key)

    # Check cache first
    if platform and spec:
        for e in _element_cache.get(platform, []):
            if _match_element(e, spec) and 'button' in e.get('role', ''):
                obj = e.get('atspi_obj')
                if obj and not is_defunct(e):
                    return obj

    def _spec_matches_obj(obj):
        """Check if an AT-SPI object matches the spec."""
        if not spec:
            return False
        try:
            role = obj.get_role_name() or ''
            name = (obj.get_name() or '').strip()
            element = {'name': name, 'role': role, 'states': []}
            # Get states
            ss = obj.get_state_set()
            if ss:
                for st in [Atspi.StateType.ENABLED, Atspi.StateType.VISIBLE,
                           Atspi.StateType.EDITABLE, Atspi.StateType.CHECKED]:
                    if ss.contains(st):
                        element['states'].append(st.value_nick)
            return _match_element(element, spec)
        except Exception:
            return False

    def search(obj, depth=0):
        if depth > 25:
            return None
        try:
            role = obj.get_role_name() or ''
            name = (obj.get_name() or '').strip()
            if 'button' in role and _spec_matches_obj(obj):
                comp = obj.get_component_iface()
                if comp:
                    ext = comp.get_extents(Atspi.CoordType.SCREEN)
                    if ext and ext.x >= 0 and ext.y >= 0:
                        return obj
            for i in range(min(obj.get_child_count(), 50)):
                child = obj.get_child_at_index(i)
                if child:
                    r = search(child, depth + 1)
                    if r:
                        return r
        except Exception:
            pass
        return None

    return search(doc) if doc else None


def _get_attach_button_coords(doc, platform: str = None) -> Optional[Dict]:
    """Find attach button and return center coordinates."""
    spec = None
    if platform:
        trigger_key = get_attach_trigger_key(platform)
        if trigger_key:
            spec = get_element_spec(platform, trigger_key)

    # Check cache first
    if platform and spec:
        for e in _element_cache.get(platform, []):
            if _match_element(e, spec) and 'button' in e.get('role', ''):
                obj = e.get('atspi_obj')
                if obj and not is_defunct(e):
                    return {'x': e.get('x', 0), 'y': e.get('y', 0), 'atspi_obj': obj}

    btn = _find_attach_button(doc, platform)
    if not btn:
        return None
    try:
        comp = btn.get_component_iface()
        if comp:
            ext = comp.get_extents(Atspi.CoordType.SCREEN)
            if ext and ext.x >= 0 and ext.y >= 0:
                return {'x': ext.x + (ext.width // 2 if ext.width else 0),
                        'y': ext.y + (ext.height // 2 if ext.height else 0),
                        'atspi_obj': btn}
    except Exception:
        pass
    return None


def _is_attach_button_disabled(atspi_obj) -> bool:
    if not atspi_obj:
        return False
    try:
        return not atspi_obj.get_state_set().contains(Atspi.StateType.ENABLED)
    except Exception:
        return False


# --- Upload item discovery ---

def _find_upload_item_in_elements(elements: List[Dict], platform: str) -> Optional[Dict]:
    """Find the upload file menu item from a list of elements using YAML spec.

    Tries the YAML upload_item_key spec first; falls back to name-based heuristics.
    """
    from core.config import get_upload_item_key
    upload_key = get_upload_item_key(platform)
    if upload_key:
        spec = get_element_spec(platform, upload_key)
        if spec:
            for e in elements:
                if _match_element(e, spec):
                    return e

    # Fallback heuristics — look for upload/file keywords in menu items
    upload_hints = ('upload', 'add photos', 'add files', 'add file', 'open file')
    for e in elements:
        role = e.get('role', '')
        name = (e.get('name') or '').strip().lower()
        if ('item' in role or 'button' in role) and any(h in name for h in upload_hints):
            return e
    return None


def _click_upload_item(item: Dict, firefox) -> bool:
    """Click a menu item via AT-SPI action or coordinates. Returns True if clicked."""
    atspi_obj = item.get('atspi_obj')
    if atspi_obj:
        try:
            ai = atspi_obj.get_action_iface()
            if ai and ai.get_n_actions() > 0:
                ai.do_action(0)
                return True
        except Exception:
            pass
    # Coordinate fallback
    x, y = item.get('x'), item.get('y')
    if x and y:
        inp.click_at(x, y)
        return True
    return False


# --- Chip detection ---

def _detect_existing_attachments(doc, platform: str = None) -> List[Dict]:
    """Scan AT-SPI tree for existing file attachment chips.

    Uses YAML validation.attach_success.indicators as primary signal;
    falls back to file extension matching.
    """
    if not doc:
        return []
    chrome_y = detect_chrome_y(doc)
    all_elements = find_elements(doc)
    elements = filter_useful_elements(all_elements, chrome_y=chrome_y)

    # Load YAML indicators if platform provided
    yaml_indicators = []
    if platform:
        config = get_platform_config(platform)
        yaml_indicators = (config.get('validation', {})
                               .get('attach_success', {})
                               .get('indicators', []))

    remove_buttons, file_names = [], []
    for e in elements:
        name = (e.get('name') or '').strip()
        role = e.get('role', '')

        # Primary: YAML indicators (e.g. "Remove" button)
        if yaml_indicators:
            for ind in yaml_indicators:
                if isinstance(ind, dict) and _match_element(e, ind):
                    if 'button' in role and name.lower().startswith('remove'):
                        remove_buttons.append({'x': e.get('x'), 'y': e.get('y'), 'name': name})
                    break
        else:
            # Fallback: hardcoded "remove" button detection
            if 'button' in role and name.lower().startswith('remove'):
                remove_buttons.append({'x': e.get('x'), 'y': e.get('y'), 'name': name})

        # File chip by name extension (secondary indicator)
        if name and any(name.lower().endswith(ext) for ext in _FILE_EXTENSIONS):
            if role in ('heading', 'push button', 'toggle button'):
                file_names.append(name)

    if remove_buttons:
        return [{'file': fn, 'remove_buttons': remove_buttons} for fn in file_names] or \
               [{'file': '(unknown)', 'remove_buttons': remove_buttons}]

    # Unnamed file chips (Grok/Perplexity): unnamed buttons above input
    entry_y = None
    for e in all_elements:
        if e.get('role') == 'entry' and 'editable' in (e.get('states') or []):
            entry_y = e.get('y', 0)
            break
    if entry_y:
        unnamed = [e for e in all_elements
                   if e.get('role') == 'push button'
                   and not (e.get('name') or '').strip()
                   and entry_y - 100 < e.get('y', 0) < entry_y - 10]
        if unnamed:
            return [{'file': '(unknown)', 'remove_buttons': [
                {'x': b.get('x'), 'y': b.get('y'), 'name': ''} for b in unnamed]}]
    return []


# --- File dialog helpers ---

def _xenv():
    return {**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':0')}


def _find_portal_wids() -> List[str]:
    try:
        r = subprocess.run(['xdotool', 'search', '--class', 'Nautilus'],
                          capture_output=True, text=True, timeout=3, env=_xenv())
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().split('\n')
    except Exception:
        pass
    return []


def _close_stale_file_dialogs():
    """Close orphaned Nautilus, GTK, xdg-desktop-portal-gtk, and zombie Firefox dialogs."""
    env = _xenv()
    closed = 0

    for wid in _find_portal_wids():
        try:
            subprocess.run(['xdotool', 'windowclose', wid],
                          capture_output=True, timeout=3, env=env)
            closed += 1
        except Exception:
            pass

    for title in ['File Upload', 'Open', 'Open File', 'xdg-desktop-portal-gtk']:
        try:
            r = subprocess.run(['xdotool', 'search', '--name', title],
                              capture_output=True, text=True, timeout=2, env=env)
            for wid in (r.stdout.strip().split('\n') if r.stdout.strip() else []):
                subprocess.run(['xdotool', 'windowclose', wid],
                              capture_output=True, timeout=3, env=env)
                closed += 1
        except Exception:
            pass

    # Zombie Firefox windows (named exactly 'Firefox', not 'Mozilla Firefox')
    try:
        r = subprocess.run(['xdotool', 'search', '--name', '^Firefox$'],
                          capture_output=True, text=True, timeout=2, env=env)
        if r.stdout.strip():
            firefox_pids, main_wids = set(), set()
            mr = subprocess.run(['xdotool', 'search', '--name', 'Mozilla Firefox'],
                               capture_output=True, text=True, timeout=2, env=env)
            for mwid in (mr.stdout.strip().split('\n') if mr.stdout.strip() else []):
                main_wids.add(mwid)
                try:
                    pr = subprocess.run(['xdotool', 'getwindowpid', mwid],
                                       capture_output=True, text=True, timeout=2, env=env)
                    if pr.stdout.strip():
                        firefox_pids.add(pr.stdout.strip())
                except Exception:
                    pass
            for wid in r.stdout.strip().split('\n'):
                if wid and wid not in main_wids:
                    try:
                        pr = subprocess.run(['xdotool', 'getwindowpid', wid],
                                           capture_output=True, text=True, timeout=2, env=env)
                        if pr.stdout.strip() in firefox_pids:
                            continue  # Firefox helper window, not zombie
                    except Exception:
                        pass
                    subprocess.run(['xdotool', 'windowclose', wid],
                                  capture_output=True, timeout=3, env=env)
                    closed += 1
    except Exception:
        pass

    if closed:
        logger.info(f"Closed {closed} stale file dialog(s)")
        time.sleep(1.0)


def _any_file_dialog_open(firefox) -> str:
    """Return 'gtk', 'portal', or '' depending on what dialog is open."""
    if atspi.is_file_dialog_open(firefox):
        return 'gtk'
    if _find_portal_wids():
        return 'portal'
    return ''


def _handle_file_dialog(platform: str, file_path: str,
                        redis_client) -> Dict[str, Any]:
    """Route to portal or GTK dialog handler."""
    firefox = atspi.find_firefox(platform)
    if _any_file_dialog_open(firefox) == 'portal':
        return _handle_portal_dialog(platform, file_path, redis_client)
    return _handle_gtk_dialog(platform, file_path, redis_client)


def _wait_for_chip(platform: str, timeout: float = 4.0) -> bool:
    """Wait for file chip to appear in AT-SPI tree, using YAML indicators."""
    firefox = atspi.find_firefox(platform)
    config = get_platform_config(platform)
    yaml_indicators = (config.get('validation', {})
                           .get('attach_success', {})
                           .get('indicators', []))

    for _ in range(int(timeout / 0.2)):
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        if doc:
            # Primary: scan using YAML indicators
            if yaml_indicators:
                chrome_y = detect_chrome_y(doc)
                all_elements = find_elements(doc)
                elements = filter_useful_elements(all_elements, chrome_y=chrome_y)
                for e in elements:
                    for ind in yaml_indicators:
                        if isinstance(ind, dict) and _match_element(e, ind):
                            return True
            # Fallback: existing attachment detection (includes file extension check)
            if _detect_existing_attachments(doc, platform):
                return True
        time.sleep(0.2)
    return False


def _handle_portal_dialog(platform: str, file_path: str,
                          redis_client) -> Dict[str, Any]:
    """Nautilus portal: focus window, Ctrl+L, paste path, Enter."""
    try:
        wids = _find_portal_wids()
        if not wids:
            return {"error": "Portal dialog detected but window not found"}
        wid = wids[-1]
        try:
            subprocess.run(['xdotool', 'windowactivate', wid],
                          capture_output=True, timeout=10, env=_xenv())
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.5)
        inp.press_key('ctrl+l')
        time.sleep(0.5)
        inp.clipboard_paste(file_path)
        time.sleep(0.3)
        inp.press_key('Return')
        time.sleep(1.0)

        dialog_closed = False
        for _ in range(20):
            time.sleep(0.3)
            if wid not in _find_portal_wids():
                dialog_closed = True
                break
        if not dialog_closed:
            inp.press_key('Return')
            time.sleep(1.0)
            dialog_closed = wid not in _find_portal_wids()
        if not dialog_closed:
            return {"error": "Portal dialog did not close after file selection"}

        inp.focus_firefox()
        time.sleep(0.5)
        chip_found = _wait_for_chip(platform)
        if chip_found:
            result = {"status": "file_attached", "platform": platform,
                      "file_path": file_path, "filename": os.path.basename(file_path),
                      "dialog_type": "nautilus_portal", "verified": True,
                      "info": "File chip verified in AT-SPI tree. Re-inspect before further clicks."}
        else:
            result = {"status": "unverified", "platform": platform,
                      "file_path": file_path, "filename": os.path.basename(file_path),
                      "dialog_type": "nautilus_portal", "verified": False,
                      "warning": "Dialog closed but file chip NOT found in AT-SPI tree. "
                                 "Call taey_inspect to check if file is actually attached."}
        _set_attach_checkpoint(platform, file_path, redis_client)
        return result
    except Exception as e:
        return {"error": f"Portal dialog handling failed: {e}"}
    finally:
        _close_stale_file_dialogs()
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))


def _handle_gtk_dialog(platform: str, file_path: str,
                       redis_client) -> Dict[str, Any]:
    """GTK embedded file dialog: focus, Ctrl+L, paste path, Enter."""
    try:
        time.sleep(0.3)
        env = _xenv()
        for title in ['File Upload', 'Open', 'Open File']:
            try:
                r = subprocess.run(['xdotool', 'search', '--name', title],
                                  capture_output=True, text=True, timeout=2, env=env)
                if r.stdout.strip():
                    wid = r.stdout.strip().split('\n')[0]
                    subprocess.run(['xdotool', 'windowactivate', wid],
                                  capture_output=True, timeout=5, env=env)
                    time.sleep(0.5)
                    logger.info(f"Focused file dialog window {wid}")
                    break
            except Exception as e:
                logger.warning(f"Could not focus file dialog: {e}")

        inp.press_key('ctrl+l')
        time.sleep(0.5)
        inp.clipboard_paste(file_path)
        time.sleep(0.3)
        inp.press_key('Return')
        time.sleep(0.8)

        firefox = atspi.find_firefox(platform)
        if atspi.is_file_dialog_open(firefox):
            inp.press_key('Return')

        dialog_closed = False
        for _ in range(25):
            time.sleep(0.2)
            if not atspi.is_file_dialog_open(firefox):
                dialog_closed = True
                break
        if not dialog_closed:
            return {"error": "GTK file dialog did not close after selection"}

        time.sleep(0.5)
        chip_found = _wait_for_chip(platform)
        if chip_found:
            result = {"status": "file_attached", "platform": platform,
                      "file_path": file_path, "filename": os.path.basename(file_path),
                      "dialog_type": "gtk_embedded", "verified": True,
                      "info": "File chip verified in AT-SPI tree. Re-inspect before further clicks."}
        else:
            result = {"status": "unverified", "platform": platform,
                      "file_path": file_path, "filename": os.path.basename(file_path),
                      "dialog_type": "gtk_embedded", "verified": False,
                      "warning": "Dialog closed but file chip NOT found in AT-SPI tree. "
                                 "Call taey_inspect to check if file is actually attached."}
        _set_attach_checkpoint(platform, file_path, redis_client)
        return result
    except Exception as e:
        return {"error": f"GTK dialog handling failed: {e}"}
    finally:
        _close_stale_file_dialogs()
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))


# --- Keyboard navigation (ChatGPT/Grok) ---

def _click_editable_input(doc, platform: str):
    """Click editable input to activate dormant buttons (Grok fresh homepage)."""
    for e in _element_cache.get(platform, []):
        if e.get('role') == 'entry' and 'editable' in (e.get('states') or []):
            x, y = e.get('x'), e.get('y')
            if x and y:
                inp.click_at(x, y)
                return
    if not doc:
        return

    def find_entry(obj, depth=0):
        if depth > 15:
            return None
        try:
            if (obj.get_role_name() or '') == 'entry':
                ss = obj.get_state_set()
                if ss and ss.contains(Atspi.StateType.EDITABLE):
                    comp = obj.get_component_iface()
                    if comp:
                        ext = comp.get_extents(Atspi.CoordType.SCREEN)
                        if ext and ext.x >= 0 and ext.y >= 0:
                            return (ext.x + ext.width // 2, ext.y + ext.height // 2)
            for i in range(min(obj.get_child_count(), 50)):
                child = obj.get_child_at_index(i)
                if child:
                    r = find_entry(child, depth + 1)
                    if r:
                        return r
        except Exception:
            pass
        return None

    coords = find_entry(doc)
    if coords:
        inp.click_at(coords[0], coords[1])


def _try_click_then_dialog(firefox, btn_coords, platform, file_path, redis_client,
                           use_atspi=True):
    """Click attach button, scan AT-SPI for menu items, click upload item directly.

    Strategy (in order):
    1. Click the attach trigger button.
    2. If a file dialog opens immediately, handle it.
    3. Scan the AT-SPI tree for menu items.
    4. If menu items found, look for the upload item by YAML spec and click it directly.
    5. Only if AT-SPI scan finds nothing AND attach_method == 'keyboard_nav', fall back
       to keyboard nav (Down+Enter), capped at 3 iterations with a warning logged.
    """
    if use_atspi and btn_coords.get('atspi_obj'):
        if not atspi_click(btn_coords):
            return None
    else:
        inp.click_at(btn_coords['x'], btn_coords['y'])
    time.sleep(1.5)

    dt = _any_file_dialog_open(firefox)
    if dt:
        return _handle_file_dialog(platform, file_path, redis_client)

    # Scan AT-SPI tree for menu items
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    menu_items = find_menu_items(firefox, doc)

    if menu_items:
        logger.info(f"AT-SPI found {len(menu_items)} menu item(s) after attach trigger click")
        upload_item = _find_upload_item_in_elements(menu_items, platform)
        if upload_item:
            logger.info(f"Clicking upload item: {upload_item.get('name', '(unnamed)')!r}")
            _click_upload_item(upload_item, firefox)
            time.sleep(1.5)
            # Check for file dialog
            for _ in range(8):
                dt = _any_file_dialog_open(firefox)
                if dt:
                    return _handle_file_dialog(platform, file_path, redis_client)
                time.sleep(0.3)
        else:
            logger.warning("AT-SPI menu items found but no upload item matched — "
                           "items: %s", [e.get('name') for e in menu_items])
        # Dismiss whatever is still open
        inp.press_key('Escape')
        time.sleep(0.3)
        return None

    # No AT-SPI menu items found. For keyboard_nav platforms, fall back to Down+Enter.
    attach_method = get_attach_method(platform)
    if attach_method == 'keyboard_nav':
        logger.warning(
            "%s: AT-SPI menu scan found no items after attach trigger click. "
            "Falling back to keyboard nav (Down+Enter) — max 3 attempts.", platform
        )
        MAX_ITEMS = 3
        for item_idx in range(MAX_ITEMS):
            inp.press_key('Down')
            time.sleep(0.3)
            inp.press_key_split('Return')
            time.sleep(2.0)

            for _ in range(5):
                dt = _any_file_dialog_open(firefox)
                if dt:
                    logger.info(f"File dialog appeared after keyboard nav item {item_idx + 1}")
                    return _handle_file_dialog(platform, file_path, redis_client)
                time.sleep(0.3)

            # This item wasn't "Upload a file" — dismiss and try next
            inp.press_key('Escape')
            time.sleep(0.5)

            if item_idx < MAX_ITEMS - 1:
                if use_atspi and btn_coords.get('atspi_obj'):
                    if not atspi_click(btn_coords):
                        inp.click_at(btn_coords['x'], btn_coords['y'])
                else:
                    inp.click_at(btn_coords['x'], btn_coords['y'])
                time.sleep(1.0)

                dt = _any_file_dialog_open(firefox)
                if dt:
                    return _handle_file_dialog(platform, file_path, redis_client)

    return None


def _keyboard_nav_attach(platform: str, file_path: str,
                         redis_client) -> Dict[str, Any]:
    """ChatGPT/Grok: click attach → try AT-SPI menu scan → keyboard nav fallback."""
    firefox = atspi.find_firefox(platform)
    dt = _any_file_dialog_open(firefox)
    if dt:
        return _handle_file_dialog(platform, file_path, redis_client)

    if not inp.switch_to_platform(platform):
        logger.warning(f"Tab switch to {platform} may have failed")
    time.sleep(0.5)

    firefox = atspi.find_firefox(platform)
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    btn_coords = _get_attach_button_coords(doc, platform) if doc else None
    if not btn_coords:
        return {"error": f"Attach button not found for {platform}",
                "action": "button_not_found"}

    if _is_attach_button_disabled(btn_coords.get('atspi_obj')):
        return {"error": f"{platform} attach button is disabled",
                "button_state": "disabled", "action": "navigate_fresh_page"}

    inp.press_key('Escape')
    time.sleep(0.3)

    # Grok: activate dormant button by clicking input first
    atspi_obj = btn_coords.get('atspi_obj')
    if atspi_obj:
        try:
            ai = atspi_obj.get_action_iface()
            if not ai or ai.get_n_actions() == 0:
                _click_editable_input(doc, platform)
                time.sleep(1.0)
                doc = atspi.get_platform_document(firefox, platform) if firefox else doc
                btn_coords = _get_attach_button_coords(doc, platform) if doc else btn_coords
        except Exception:
            pass

    # Try AT-SPI click first, then xdotool fallback
    result = _try_click_then_dialog(firefox, btn_coords, platform, file_path,
                                     redis_client, use_atspi=True)
    if result:
        return result

    result = _try_click_then_dialog(firefox, btn_coords, platform, file_path,
                                     redis_client, use_atspi=False)
    if result:
        return result

    _close_stale_file_dialogs()
    return {"error": f"Keyboard nav attach failed for {platform}: no file dialog appeared"}


# --- Post-attach YAML validation ---

def _verify_attach_success(platform: str, firefox, doc) -> bool:
    """Verify attachment using YAML validation indicators.

    Scans the AT-SPI tree and checks for indicators defined in
    validation.attach_success.indicators in the platform YAML.
    Returns True if any indicator is matched.
    """
    if not doc:
        return False
    config = get_platform_config(platform)
    indicators = (config.get('validation', {})
                      .get('attach_success', {})
                      .get('indicators', []))
    if not indicators:
        # No YAML indicators — fall back to chip detection
        return bool(_detect_existing_attachments(doc, platform))

    chrome_y = detect_chrome_y(doc)
    all_elements = find_elements(doc)
    elements = filter_useful_elements(all_elements, chrome_y=chrome_y)

    for e in elements:
        for ind in indicators:
            if isinstance(ind, dict) and _match_element(e, ind):
                return True
    # Also check file chips as secondary signal
    return bool(_detect_existing_attachments(doc, platform))


# --- Main handler ---

def handle_attach(platform: str, file_path: str,
                  redis_client) -> Dict[str, Any]:
    """Attach a file to chat input."""
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}
    real_path = os.path.realpath(file_path)
    if not any(real_path == d or real_path.startswith(d + os.sep) for d in _ALLOWED_DIRS):
        return {"error": f"Path not in allowed directories: {real_path}"}

    firefox = atspi.find_firefox(platform)

    # Short-circuit if dialog already open
    dt = _any_file_dialog_open(firefox)
    if dt:
        return _handle_file_dialog(platform, file_path, redis_client)

    # Check pending attach (continuing after dropdown click)
    pending = None
    if redis_client:
        pj = redis_client.get(node_key(f"attach:pending:{platform}"))
        if pj:
            try:
                pending = json.loads(pj)
            except json.JSONDecodeError:
                pass

    if not pending:
        _close_stale_file_dialogs()
        inp.press_key('Escape')
        time.sleep(0.3)

    # Skip if exact file already attached
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    existing = _detect_existing_attachments(doc, platform)
    if existing:
        basename = os.path.basename(file_path)
        if any(basename in f.get('file', '') for f in existing):
            _set_attach_checkpoint(platform, file_path, redis_client)
            return {"status": "already_attached", "platform": platform,
                    "file_path": file_path, "filename": basename,
                    "existing_attachments": existing,
                    "info": f"{basename} is already attached."}

    # Wait for pending dialog
    if pending:
        for _ in range(15):
            dt = _any_file_dialog_open(firefox)
            if dt:
                return _handle_file_dialog(platform, file_path, redis_client)
            time.sleep(0.2)
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))
    else:
        dt = _any_file_dialog_open(firefox)
        if dt:
            return _handle_file_dialog(platform, file_path, redis_client)

    # Dispatch based on YAML attach_method
    attach_method = get_attach_method(platform)
    if attach_method == 'keyboard_nav':
        result = _keyboard_nav_attach(platform, file_path, redis_client)
        # Post-attach verification using YAML indicators
        if result.get('status') in ('file_attached', 'unverified'):
            firefox = atspi.find_firefox(platform)
            doc = atspi.get_platform_document(firefox, platform) if firefox else None
            verified = _verify_attach_success(platform, firefox, doc)
            result['verified'] = verified
            if verified and result.get('status') == 'unverified':
                result['status'] = 'file_attached'
                result['info'] = ("File chip verified via YAML indicators. "
                                  "Re-inspect before further clicks.")
        return result
    elif attach_method == 'none':
        return {"error": f"{platform} does not support file attachments"}

    # AT-SPI menu platforms: click trigger, scan for menu items or dialog
    firefox = atspi.find_firefox(platform)
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    btn_coords = _get_attach_button_coords(doc, platform) if doc else None

    if not btn_coords:
        return {"error": f"Attach button not found for {platform}",
                "action": "button_not_found"}

    click_result = handle_click(platform, btn_coords['x'], btn_coords['y'])
    if click_result.get("error"):
        return {"error": f"Failed to click attach button: {click_result['error']}",
                "action": "click_failed"}

    time.sleep(1.0)
    dt = _any_file_dialog_open(firefox)
    if dt:
        result = _handle_file_dialog(platform, file_path, redis_client)
        # Verify with YAML indicators
        if result.get('status') in ('file_attached', 'unverified'):
            firefox = atspi.find_firefox(platform)
            doc = atspi.get_platform_document(firefox, platform) if firefox else None
            verified = _verify_attach_success(platform, firefox, doc)
            result['verified'] = verified
        return result

    # Wait for dropdown menu items
    dropdown_items = []
    for _ in range(5):
        firefox = atspi.find_firefox(platform)
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        dropdown_items = find_menu_items(firefox, doc)
        if dropdown_items:
            break
        time.sleep(0.6)

    if not dropdown_items and not _any_file_dialog_open(firefox):
        return {"error": f"No dropdown items or file dialog found for {platform}",
                "action": "attach_button_failed"}

    if dropdown_items:
        extend_cache(platform, dropdown_items)

    # Try to find and click the upload item directly
    if dropdown_items:
        upload_item = _find_upload_item_in_elements(dropdown_items, platform)
        if upload_item:
            logger.info(f"Clicking upload item directly: {upload_item.get('name', '(unnamed)')!r}")
            _click_upload_item(upload_item, firefox)
            time.sleep(1.5)
            dt = _any_file_dialog_open(firefox)
            if dt:
                result = _handle_file_dialog(platform, file_path, redis_client)
                # Post-attach YAML verification
                if result.get('status') in ('file_attached', 'unverified'):
                    firefox = atspi.find_firefox(platform)
                    doc = atspi.get_platform_document(firefox, platform) if firefox else None
                    verified = _verify_attach_success(platform, firefox, doc)
                    result['verified'] = verified
                    if verified and result.get('status') == 'unverified':
                        result['status'] = 'file_attached'
                        result['info'] = ("File chip verified via YAML indicators. "
                                          "Re-inspect before further clicks.")
                return result
            # Check a bit longer
            for _ in range(5):
                time.sleep(0.3)
                dt = _any_file_dialog_open(firefox)
                if dt:
                    result = _handle_file_dialog(platform, file_path, redis_client)
                    if result.get('status') in ('file_attached', 'unverified'):
                        firefox = atspi.find_firefox(platform)
                        doc = atspi.get_platform_document(firefox, platform) if firefox else None
                        verified = _verify_attach_success(platform, firefox, doc)
                        result['verified'] = verified
                    return result
            # No dialog after clicking upload item — dismiss and fall through to dropdown report
            inp.press_key('Escape')
            time.sleep(0.3)

    if redis_client:
        redis_client.setex(node_key(f"attach:pending:{platform}"), 120, json.dumps(
            {'file_path': file_path, 'timestamp': time.time()}))

    return {
        "status": "dropdown_open",
        "message": "Dropdown opened. Select the file upload option with click_at, then call attach again.",
        "file_path": file_path,
        "dropdown_items": strip_atspi_obj(dropdown_items) if dropdown_items else [],
    }
