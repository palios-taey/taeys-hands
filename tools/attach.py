"""taey_attach - File attachment via AT-SPI button discovery + file dialogs."""

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
from core.tree import (find_elements, find_menu_items,
                       filter_useful_elements, detect_chrome_y)
from core.interact import (extend_cache, find_element_at, atspi_click,
                           strip_atspi_obj, _element_cache, is_defunct)
from tools.click import handle_click
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)

ATTACH_NAMES = [
    'open upload file menu', 'attach', 'add files and more',
    'add files or tools', 'toggle menu',
]
def _get_attach_method(platform: str) -> str:
    """Get attach method from platform YAML config."""
    try:
        import yaml
        yaml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms', f'{platform}.yaml')
        with open(yaml_path) as f:
            config = yaml.safe_load(f) or {}
        return config.get('attach_method', 'atspi_menu')
    except (FileNotFoundError, Exception):
        return 'atspi_menu'
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


# --- Button discovery ---

def _find_attach_button(doc, platform: str = None):
    """Find attach button in cache then raw AT-SPI DFS."""
    if platform:
        for e in _element_cache.get(platform, []):
            name = (e.get('name') or '').strip().lower()
            if 'button' in e.get('role', '') and name in ATTACH_NAMES:
                obj = e.get('atspi_obj')
                if obj and not is_defunct(e):
                    return obj

    def search(obj, depth=0):
        if depth > 25:
            return None
        try:
            role = obj.get_role_name() or ''
            name = (obj.get_name() or '').strip().lower()
            if 'button' in role and name in ATTACH_NAMES:
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
    if platform:
        for e in _element_cache.get(platform, []):
            name = (e.get('name') or '').strip().lower()
            if 'button' in e.get('role', '') and name in ATTACH_NAMES:
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


# --- Chip detection ---

def _detect_existing_attachments(doc) -> List[Dict]:
    """Scan AT-SPI tree for existing file attachment chips."""
    if not doc:
        return []
    chrome_y = detect_chrome_y(doc)
    all_elements = find_elements(doc)
    elements = filter_useful_elements(all_elements, chrome_y=chrome_y)

    remove_buttons, file_names = [], []
    for e in elements:
        name = (e.get('name') or '').strip()
        role = e.get('role', '')
        if 'button' in role and name.lower().startswith('remove'):
            remove_buttons.append({'x': e.get('x'), 'y': e.get('y'), 'name': name})
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
    firefox = atspi.find_firefox()
    if _any_file_dialog_open(firefox) == 'portal':
        return _handle_portal_dialog(platform, file_path, redis_client)
    return _handle_gtk_dialog(platform, file_path, redis_client)


def _wait_for_chip(platform: str, timeout: float = 4.0) -> bool:
    """Wait for file chip to appear in AT-SPI tree."""
    firefox = atspi.find_firefox()
    for _ in range(int(timeout / 0.2)):
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        if doc and _detect_existing_attachments(doc):
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
        subprocess.run(['xdotool', 'windowactivate', '--sync', wid],
                      capture_output=True, timeout=3, env=_xenv())
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
        result = {"status": "file_attached", "platform": platform,
                  "file_path": file_path, "filename": os.path.basename(file_path),
                  "dialog_type": "nautilus_portal",
                  "info": "File chip may shift element positions - re-inspect before further clicks."}
        if not chip_found:
            result["warning"] = "Dialog closed but no file chip detected — re-inspect to verify."
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
                    subprocess.run(['xdotool', 'windowactivate', '--sync',
                                   r.stdout.strip().split('\n')[0]],
                                  capture_output=True, timeout=3, env=env)
                    time.sleep(0.3)
                    break
            except Exception:
                pass

        inp.press_key('ctrl+l')
        time.sleep(0.5)
        inp.clipboard_paste(file_path)
        time.sleep(0.3)
        inp.press_key('Return')
        time.sleep(0.8)

        firefox = atspi.find_firefox()
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
        result = {"status": "file_attached", "platform": platform,
                  "file_path": file_path, "filename": os.path.basename(file_path),
                  "dialog_type": "gtk_embedded",
                  "info": "File chip may shift element positions - re-inspect before further clicks."}
        if not chip_found:
            result["warning"] = "Dialog closed but no file chip detected — re-inspect to verify."
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
    """Click attach button, check for dialog, try Down+Enter keyboard nav."""
    if use_atspi and btn_coords.get('atspi_obj'):
        if not atspi_click(btn_coords):
            return None
    else:
        inp.click_at(btn_coords['x'], btn_coords['y'])
    time.sleep(1.5)

    dt = _any_file_dialog_open(firefox)
    if dt:
        return _handle_file_dialog(platform, file_path, redis_client)

    # Dropdown opened — keyboard nav to first item
    inp.press_key('Down')
    time.sleep(0.5)
    inp.press_key_split('Return')
    time.sleep(2.5)

    for _ in range(10):
        dt = _any_file_dialog_open(firefox)
        if dt:
            return _handle_file_dialog(platform, file_path, redis_client)
        time.sleep(0.3)
    return None


def _keyboard_nav_attach(platform: str, file_path: str,
                         redis_client) -> Dict[str, Any]:
    """ChatGPT/Grok: click attach → Down+Enter → handle file dialog."""
    firefox = atspi.find_firefox()
    dt = _any_file_dialog_open(firefox)
    if dt:
        return _handle_file_dialog(platform, file_path, redis_client)

    if not inp.switch_to_platform(platform):
        logger.warning(f"Tab switch to {platform} may have failed")
    time.sleep(0.5)

    firefox = atspi.find_firefox()
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

    # Try AT-SPI action first, then xdotool fallback
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


# --- Main handler ---

def handle_attach(platform: str, file_path: str,
                  redis_client) -> Dict[str, Any]:
    """Attach a file to chat input."""
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}
    real_path = os.path.realpath(file_path)
    if not any(real_path == d or real_path.startswith(d + os.sep) for d in _ALLOWED_DIRS):
        return {"error": f"Path not in allowed directories: {real_path}"}

    firefox = atspi.find_firefox()

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
    existing = _detect_existing_attachments(doc)
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
    attach_method = _get_attach_method(platform)
    if attach_method == 'keyboard_nav':
        return _keyboard_nav_attach(platform, file_path, redis_client)
    elif attach_method == 'none':
        return {"error": f"{platform} does not support file attachments"}

    # AT-SPI menu platforms: click trigger, scan for menu items or dialog
    firefox = atspi.find_firefox()
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
        return _handle_file_dialog(platform, file_path, redis_client)

    # Wait for dropdown menu items
    dropdown_items = []
    for _ in range(5):
        firefox = atspi.find_firefox()
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

    if redis_client:
        redis_client.setex(node_key(f"attach:pending:{platform}"), 120, json.dumps({
            'file_path': file_path, 'timestamp': time.time()}))

    return {
        "status": "dropdown_open",
        "message": "Dropdown opened. Select the file upload option with click_at, then call attach again.",
        "file_path": file_path,
        "dropdown_items": strip_atspi_obj(dropdown_items) if dropdown_items else [],
    }
