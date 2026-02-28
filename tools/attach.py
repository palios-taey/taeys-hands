"""
taey_attach - File attachment workflow.

Multi-step process: click attach button, detect what appeared
(file dialog vs dropdown), handle accordingly. Claude stays
in the loop for dropdown decisions.
"""

import json
import os
import re
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
from tools.interact import handle_click, get_map
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)


def _handle_file_dialog(platform: str, file_path: str,
                        redis_client) -> Dict[str, Any]:
    """Handle GTK file picker - type path and select file."""
    try:
        time.sleep(0.3)

        # Focus the file dialog window FIRST — otherwise Ctrl+L goes to Firefox address bar
        try:
            # Try common file dialog titles
            dialog_wids = []
            for title in ['File Upload', 'Open', 'Open File']:
                result = subprocess.run(
                    ['xdotool', 'search', '--name', title],
                    capture_output=True, text=True, timeout=2,
                    env={**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':0')},
                )
                if result.stdout.strip():
                    dialog_wids = result.stdout.strip().split('\n')
                    break
            if dialog_wids and dialog_wids[0]:
                subprocess.run(
                    ['xdotool', 'windowactivate', '--sync', dialog_wids[0]],
                    capture_output=True, timeout=3,
                    env={**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':0')},
                )
                time.sleep(0.3)
                logger.info(f"Focused file dialog window {dialog_wids[0]}")
        except Exception as e:
            logger.warning(f"Could not focus file dialog window: {e}")

        if not inp.press_key('ctrl+l'):
            return {"error": "Failed to focus location bar"}
        time.sleep(0.2)

        # Clipboard paste file path (xdotool drops doubled letters)
        inp.clipboard_paste(file_path)
        time.sleep(0.2)

        # First Return - navigate to path
        if not inp.press_key('Return'):
            return {"error": "Failed to press Return (navigate)"}
        time.sleep(0.3)

        # Second Return - confirm selection
        if not inp.press_key('Return'):
            return {"error": "Failed to press Return (confirm)"}

        # Wait for dialog to close
        firefox = atspi.find_firefox()
        dialog_closed = False
        for _ in range(25):
            time.sleep(0.2)
            if not atspi.is_file_dialog_open(firefox):
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

        # Invalidate stored map - file chip shifts input position
        if redis_client:
            redis_client.delete(node_key("current_map"))

        return {
            "status": "file_attached",
            "platform": platform,
            "file_path": file_path,
            "filename": os.path.basename(file_path),
            "info": "Map invalidated - re-inspect before further clicks.",
        }

    except Exception as e:
        logger.error(f"File dialog handling failed: {e}")
        return {"error": f"File dialog handling failed: {e}"}

    finally:
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))


def _activate_grok_compose(doc):
    """Click the Grok compose area to activate it before attaching.

    On the Grok landing page, the Attach button dropdown doesn't work
    until the contenteditable compose area is focused. This finds the
    editable section/paragraph and clicks it.
    """
    try:
        all_elements = find_elements(doc, max_depth=15)
        # Look for editable section/paragraph (the compose area)
        for e in all_elements:
            states = e.get('states', [])
            if 'editable' in states and e.get('role') in ('section', 'paragraph'):
                x, y = e.get('x', 0), e.get('y', 0)
                if x > 0 and y > 0:
                    logger.info(f"Activating Grok compose area at ({x},{y})")
                    inp.click_at(x, y)
                    time.sleep(0.5)
                    return
        logger.debug("No editable compose area found for Grok")
    except Exception as e:
        logger.debug(f"Grok compose activation failed: {e}")


def _find_attach_button(doc):
    """Search AT-SPI tree for the attach/upload button by name.

    Bypasses element cache — does a fresh tree search. Returns the
    raw AT-SPI accessible object (with action interface) or None.
    """
    _ATTACH_NAMES = [
        'open upload file menu',  # Gemini
        'attach',                 # Grok
        'add files and more',     # ChatGPT
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

    if not remove_buttons and not file_names:
        return []

    return [{'file': fn, 'remove_buttons': remove_buttons} for fn in file_names] or \
           [{'file': '(unknown)', 'remove_buttons': remove_buttons}]


def handle_attach(platform: str, file_path: str,
                  redis_client) -> Dict[str, Any]:
    """Attach a file to the chat input.

    Multi-step with Claude in the loop:
    1. Check for existing attachments (prevent duplicates)
    2. Click attach button
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
            if atspi.is_file_dialog_open(firefox):
                return _handle_file_dialog(platform, file_path, redis_client)
            time.sleep(0.2)
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))
    elif atspi.is_file_dialog_open(firefox):
        return _handle_file_dialog(platform, file_path, redis_client)

    # Grok: activate compose area before clicking Attach.
    # On the Grok landing page, the Attach dropdown doesn't work until
    # the contenteditable compose area is focused/activated.
    if platform == 'grok' and doc:
        _activate_grok_compose(doc)

    # Click attach button (may fail if no stored map — fallbacks handle it)
    click_result = handle_click(platform, "attach", redis_client)
    click_failed = bool(click_result.get("error"))

    if not click_failed:
        time.sleep(1.0)

        # Check if file dialog opened
        if atspi.is_file_dialog_open(firefox):
            return _handle_file_dialog(platform, file_path, redis_client)

        # Dropdown appeared - find items (retry up to 3 times for slow renders)
        dropdown_items = []
        for attempt in range(3):
            firefox = atspi.find_firefox()
            doc = atspi.get_platform_document(firefox, platform) if firefox else None
            dropdown_items = find_menu_items(firefox, doc)
            if dropdown_items:
                break
            logger.info(f"Menu items not found (attempt {attempt + 1}/3), waiting...")
            time.sleep(0.5)

        # AT-SPI click succeeded but no dropdown appeared — retry with xdotool
        if not dropdown_items and click_result.get("method") == "atspi":
            logger.info("AT-SPI click didn't open dropdown, retrying with xdotool")
            map_data = get_map(platform, redis_client)
            if map_data:
                coord = map_data.get('controls', {}).get('attach', {})
                if coord:
                    inp.click_at(coord['x'], coord['y'])
                    time.sleep(1.0)
                    # Check file dialog first
                    if atspi.is_file_dialog_open(firefox):
                        return _handle_file_dialog(platform, file_path, redis_client)
                    for attempt in range(3):
                        firefox = atspi.find_firefox()
                        doc = atspi.get_platform_document(firefox, platform) if firefox else None
                        dropdown_items = find_menu_items(firefox, doc)
                        if dropdown_items:
                            break
                        time.sleep(0.5)
    else:
        logger.info(f"Map click failed ({click_result.get('error')}), skipping to AT-SPI tree search")
        dropdown_items = []

    # Fallback: Direct AT-SPI tree search for attach button (bypasses element cache)
    # Needed when find_element_at cache miss causes xdotool fallback on Gemini,
    # where xdotool coordinate clicks don't trigger React event handlers.
    if not dropdown_items and not atspi.is_file_dialog_open(firefox):
        logger.info("Trying direct AT-SPI tree search for attach button")
        firefox = atspi.find_firefox()
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        attach_btn = _find_attach_button(doc) if doc else None
        if attach_btn:
            # Escape first to dismiss any half-opened state
            inp.press_key('Escape')
            time.sleep(0.3)
            action_iface = attach_btn.get_action_iface()
            if action_iface and action_iface.get_n_actions() > 0:
                logger.info(f"Direct AT-SPI do_action on attach button")
                action_iface.do_action(0)
                time.sleep(1.5)
                # Check file dialog
                if atspi.is_file_dialog_open(firefox):
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
    # Grok/ChatGPT dropdowns render via React portals invisible to AT-SPI.
    # xdotool click opens the dropdown, Down selects first item, Enter activates.
    if not dropdown_items and not atspi.is_file_dialog_open(firefox):
        logger.info("Trying keyboard nav fallback: Down+Enter for invisible dropdown")
        # The dropdown should already be open from the initial click.
        # If not, re-click via xdotool to ensure it's open.
        map_data = get_map(platform, redis_client)
        if map_data:
            coord = map_data.get('controls', {}).get('attach', {})
            if coord:
                # Escape any stale state, then re-click via xdotool
                inp.press_key('Escape')
                time.sleep(0.3)
                inp.click_at(coord['x'], coord['y'])
                time.sleep(1.0)
                # Check file dialog (some platforms skip dropdown)
                if atspi.is_file_dialog_open(firefox):
                    return _handle_file_dialog(platform, file_path, redis_client)
                # Keyboard nav: Down selects first item, Enter activates
                inp.press_key('Down')
                time.sleep(0.2)
                inp.press_key('Return')
                time.sleep(1.5)
                # Check if file dialog opened
                if atspi.is_file_dialog_open(firefox):
                    return _handle_file_dialog(platform, file_path, redis_client)
                logger.warning("Keyboard nav fallback did not open file dialog")

    # Cache dropdown items so taey_click_at can use AT-SPI do_action
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
