"""
taey_attach - File attachment workflow.

Multi-step process: click attach button, detect what appeared
(file dialog vs dropdown), handle accordingly. Claude stays
in the loop for dropdown decisions.
"""

import json
import os
import subprocess
import time
import logging
from typing import Any, Dict, List

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from core import atspi, input as inp, clipboard
from core.tree import find_elements, filter_useful_elements, detect_chrome_y, find_menu_items
from core.atspi_interact import extend_cache, strip_atspi_obj
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)


def _xdotool_env():
    """Get environment dict with DISPLAY set for xdotool."""
    return {**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':0')}


def _find_file_dialog_wid() -> str | None:
    """Find an open file dialog window via xdotool.

    Returns the window ID string, or None if no dialog found.
    Works for both embedded Firefox GTK dialogs and standalone dialogs.
    """
    for title in ['File Upload', 'Open', 'Open File']:
        try:
            result = subprocess.run(
                ['xdotool', 'search', '--name', title],
                capture_output=True, text=True, timeout=2,
                env=_xdotool_env(),
            )
            if result.stdout.strip():
                wids = result.stdout.strip().split('\n')
                return wids[-1]  # newest window
        except Exception:
            pass
    return None


def is_file_dialog_open_any(firefox) -> bool:
    """Check for open file dialog via AT-SPI and xdotool.

    AT-SPI is_file_dialog_open misses embedded Firefox GTK file dialogs
    (no 'file chooser' role). xdotool window name search catches those.
    """
    if atspi.is_file_dialog_open(firefox):
        return True
    return _find_file_dialog_wid() is not None


def _handle_file_dialog(platform: str, file_path: str,
                        redis_client) -> Dict[str, Any]:
    """Handle file picker — works with embedded Firefox GTK dialogs.

    Embedded Firefox file dialogs intercept Ctrl+L (goes to Firefox URL bar).
    Instead: focus dialog, click the filename entry at the bottom of the
    dialog (geometry-based), paste the path, press Enter.
    """
    try:
        time.sleep(0.3)

        # Find and focus the dialog window
        dialog_wid = _find_file_dialog_wid()
        if dialog_wid:
            subprocess.run(
                ['xdotool', 'windowactivate', '--sync', dialog_wid],
                capture_output=True, timeout=3, env=_xdotool_env(),
            )
            subprocess.run(
                ['xdotool', 'windowfocus', '--sync', dialog_wid],
                capture_output=True, timeout=3, env=_xdotool_env(),
            )
            time.sleep(0.5)
            logger.info(f"Focused file dialog window {dialog_wid}")

            # Get dialog geometry — filename entry is near the bottom
            geo_result = subprocess.run(
                ['xdotool', 'getwindowgeometry', '--shell', dialog_wid],
                capture_output=True, text=True, timeout=2, env=_xdotool_env(),
            )
            if geo_result.returncode == 0:
                geo = {}
                for line in geo_result.stdout.strip().split('\n'):
                    if '=' in line:
                        k, v = line.split('=', 1)
                        geo[k] = int(v)
                if 'X' in geo and 'Y' in geo and 'WIDTH' in geo and 'HEIGHT' in geo:
                    # Click the filename entry area (bottom of dialog, ~40px from bottom)
                    entry_x = geo['X'] + geo['WIDTH'] // 2
                    entry_y = geo['Y'] + geo['HEIGHT'] - 40
                    logger.info(f"Clicking filename entry at ({entry_x},{entry_y})")
                    inp.click_at(entry_x, entry_y)
                    time.sleep(0.3)
        else:
            logger.warning("File dialog window not found via xdotool")

        # Select all existing text and paste the file path
        inp.press_key('ctrl+a')
        time.sleep(0.1)
        inp.clipboard_paste(file_path)
        time.sleep(0.2)

        # Press Enter to confirm selection
        if not inp.press_key('Return'):
            return {"error": "Failed to press Return"}
        time.sleep(0.5)

        # Wait for dialog to close
        dialog_closed = False
        for _ in range(25):
            time.sleep(0.2)
            if not _find_file_dialog_wid():
                dialog_closed = True
                break

        if not dialog_closed:
            # Try a second Enter (some dialogs need navigate + confirm)
            inp.press_key('Return')
            time.sleep(0.3)
            for _ in range(15):
                time.sleep(0.2)
                if not _find_file_dialog_wid():
                    dialog_closed = True
                    break

        if not dialog_closed:
            return {"error": "File dialog did not close after selection"}

        time.sleep(0.5)

        # Update attachment checkpoint
        if redis_client:
            existing = redis_client.get(node_key(f"checkpoint:{platform}:attach"))
            if existing:
                try:
                    data = json.loads(existing)
                    count = data.get('attached_count', 0) + 1
                    files = data.get('attached_files', [])
                    files.append(file_path)
                except json.JSONDecodeError:
                    count, files = 1, [file_path]
            else:
                count, files = 1, [file_path]

            redis_client.set(node_key(f"checkpoint:{platform}:attach"), json.dumps({
                'attached_count': count,
                'attached_files': files,
                'last_file': file_path,
                'timestamp': time.time(),
            }))

        return {
            "status": "file_attached",
            "platform": platform,
            "file_path": file_path,
            "filename": os.path.basename(file_path),
            "info": "File chip may shift element positions - re-inspect before further clicks.",
        }

    except Exception as e:
        logger.error(f"File dialog handling failed: {e}")
        return {"error": f"File dialog handling failed: {e}"}

    finally:
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))


def _find_attach_button(doc):
    """Search AT-SPI tree for the attach/upload button by name.

    Bypasses element cache — does a fresh tree search. Returns the
    raw AT-SPI accessible object (with action interface) or None.
    """
    _ATTACH_NAMES = [
        'open upload file menu',  # Gemini
        'attach',                 # Grok
        'add files and more',     # ChatGPT
        'add files or tools',     # Perplexity
        'toggle menu',            # Claude (attach trigger)
    ]

    def search(obj, depth=0, max_depth=15):
        if depth > max_depth:
            return None
        try:
            role = obj.get_role_name() or ''
            name = (obj.get_name() or '').strip().lower()
            if 'button' in role and name in _ATTACH_NAMES:
                comp = obj.get_component_iface()
                if comp:
                    ext = comp.get_extents(Atspi.CoordType.SCREEN)
                    if ext.width > 0 and ext.height > 0:
                        return obj
            for i in range(min(obj.get_child_count(), 50)):
                child = obj.get_child_at_index(i)
                if child:
                    result = search(child, depth + 1)
                    if result:
                        return result
        except Exception:
            pass
        return None

    return search(doc)


def _detect_existing_attachments(doc) -> List[Dict]:
    """Scan AT-SPI tree for existing file attachment chips.

    Returns list of dicts with file name and Remove button coordinates.
    This prevents accidentally adding multiple files.
    """
    if not doc:
        return []

    chrome_y = detect_chrome_y(doc)
    all_elements = find_elements(doc)
    elements = filter_useful_elements(all_elements, chrome_y=chrome_y)

    _FILE_EXTENSIONS = ('.md', '.py', '.txt', '.pdf', '.png', '.jpg',
                        '.jpeg', '.csv', '.json', '.xml', '.html', '.zip', '.docx')

    remove_buttons = []
    file_names = []
    for e in elements:
        name = (e.get('name') or '').strip()
        role = e.get('role', '')
        if 'button' in role and name.lower().startswith('remove'):
            remove_buttons.append({'x': e.get('x'), 'y': e.get('y'), 'name': name})
        if name and any(name.lower().endswith(ext) for ext in _FILE_EXTENSIONS):
            if role in ('heading', 'push button', 'toggle button'):
                file_names.append(name)

    # Require remove buttons to confirm real attachments.
    # Sidebar history items match file extensions but never have Remove buttons.
    if not remove_buttons:
        return []

    return [{'file': fn, 'remove_buttons': remove_buttons} for fn in file_names] or \
           [{'file': '(unknown)', 'remove_buttons': remove_buttons}]


def handle_attach(platform: str, file_path: str,
                  redis_client) -> Dict[str, Any]:
    """Attach a file to the chat input.

    Multi-step with Claude in the loop:
    1. Check for existing attachments (prevent duplicates)
    2. Click attach button via AT-SPI tree search (primary), xdotool fallback
    3. If file dialog opened -> handle selection
    4. If dropdown appeared -> return items for Claude to decide
    """
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}

    firefox = atspi.find_firefox()

    # Pre-check: skip if this exact file is already attached
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    existing = _detect_existing_attachments(doc)
    if existing:
        target_basename = os.path.basename(file_path)
        already_has_target = any(target_basename in f.get('file', '') for f in existing)
        if already_has_target:
            return {
                "status": "already_attached",
                "platform": platform,
                "file_path": file_path,
                "filename": target_basename,
                "existing_attachments": existing,
                "info": f"{target_basename} is already attached. No action needed.",
            }

    # Check for pending attach (continuing after dropdown click)
    pending = None
    if redis_client:
        pending_json = redis_client.get(node_key(f"attach:pending:{platform}"))
        if pending_json:
            try:
                pending = json.loads(pending_json)
            except json.JSONDecodeError:
                pass

    # If pending, wait for file dialog to appear
    if pending:
        for _ in range(15):
            if is_file_dialog_open_any(firefox):
                return _handle_file_dialog(platform, file_path, redis_client)
            time.sleep(0.2)
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))
    elif is_file_dialog_open_any(firefox):
        return _handle_file_dialog(platform, file_path, redis_client)

    # Find attach button via AT-SPI tree search
    dropdown_items = []
    logger.info("Searching AT-SPI tree for attach button")
    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    attach_btn = _find_attach_button(doc) if doc else None

    if attach_btn:
        # Primary: xdotool coordinate click (real mouse event).
        # Real X11 mouse events make Firefox register React portals in AT-SPI.
        # AT-SPI do_action does not — portal items stay invisible.
        clicked = False
        comp = attach_btn.get_component_iface()
        if comp:
            ext = comp.get_extents(Atspi.CoordType.SCREEN)
            if ext.width > 0 and ext.height > 0:
                cx = ext.x + ext.width // 2
                cy = ext.y + ext.height // 2
                logger.info(f"Coordinate click on attach button at ({cx},{cy})")
                inp.click_at(cx, cy)
                clicked = True

        # Fallback: AT-SPI do_action (when coordinates unavailable)
        if not clicked:
            action_iface = attach_btn.get_action_iface()
            if action_iface and action_iface.get_n_actions() > 0:
                logger.info("AT-SPI do_action on attach button (no coordinates)")
                action_iface.do_action(0)
                clicked = True

        if clicked:
            time.sleep(1.5)
            if is_file_dialog_open_any(firefox):
                return _handle_file_dialog(platform, file_path, redis_client)
            # Scan for dropdown items
            for attempt in range(3):
                firefox = atspi.find_firefox()
                doc = atspi.get_platform_document(firefox, platform) if firefox else None
                dropdown_items = find_menu_items(firefox, doc)
                if dropdown_items:
                    break
                time.sleep(0.5)

    # Fallback: Keyboard navigation (Down+Enter) for AT-SPI-invisible dropdowns
    if not dropdown_items and not is_file_dialog_open_any(firefox):
        logger.info("Trying keyboard nav fallback: Down+Enter for invisible dropdown")
        firefox = atspi.find_firefox()
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        attach_btn = _find_attach_button(doc) if doc else None
        if attach_btn:
            comp = attach_btn.get_component_iface()
            if comp:
                ext = comp.get_extents(Atspi.CoordType.SCREEN)
                cx = ext.x + ext.width // 2
                cy = ext.y + ext.height // 2
                inp.press_key('Escape')
                time.sleep(0.3)
                inp.click_at(cx, cy)
                time.sleep(1.0)
                if is_file_dialog_open_any(firefox):
                    return _handle_file_dialog(platform, file_path, redis_client)
                inp.press_key('Down')
                time.sleep(0.2)
                inp.press_key('Return')
                time.sleep(1.5)
                if is_file_dialog_open_any(firefox):
                    return _handle_file_dialog(platform, file_path, redis_client)
                logger.warning("Keyboard nav fallback did not open file dialog")

    # Cache dropdown items so taey_click can use AT-SPI do_action
    if dropdown_items:
        extend_cache(platform, dropdown_items)

    # Store pending state for when Claude clicks an item (120s TTL)
    if redis_client:
        redis_client.setex(node_key(f"attach:pending:{platform}"), 120, json.dumps({
            'file_path': file_path,
            'timestamp': time.time(),
        }))

    # Strip atspi_obj for JSON serialization (D-Bus proxies can't serialize)
    serializable_items = strip_atspi_obj(dropdown_items) if dropdown_items else []

    return {
        "status": "dropdown_open",
        "message": "Dropdown opened. Select the file upload option with click_at, then call attach again.",
        "file_path": file_path,
        "dropdown_items": serializable_items,
    }
