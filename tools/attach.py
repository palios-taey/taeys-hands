"""
taey_attach - File attachment workflow.

Multi-step process: click attach button, detect what appeared
(file dialog vs dropdown), handle accordingly. Claude stays
in the loop for dropdown decisions.
"""

import json
import os
import re
import time
import logging
from typing import Any, Dict, List

from core import atspi, input as inp, clipboard
from core.tree import find_elements, filter_useful_elements, detect_chrome_y, find_menu_items
from core.atspi_interact import extend_cache, strip_atspi_obj
from tools.interact import handle_click
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)


def _handle_file_dialog(platform: str, file_path: str,
                        redis_client) -> Dict[str, Any]:
    """Handle GTK file picker - type path and select file."""
    try:
        time.sleep(0.3)

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

    # Pre-check: detect existing file attachments
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    existing = _detect_existing_attachments(doc)
    if existing:
        target_basename = os.path.basename(file_path)
        # If the target file is already attached, skip re-attaching
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
        # Other files attached - warn Claude to remove them first
        return {
            "status": "stale_attachments",
            "platform": platform,
            "file_path": file_path,
            "existing_attachments": existing,
            "WARNING": (
                f"Found {len(existing)} existing file(s) attached. "
                "Remove them first using the Remove button coordinates, "
                "then call taey_attach again."
            ),
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

    # Click attach button
    click_result = handle_click(platform, "attach", redis_client)
    if click_result.get("error"):
        return {"error": f"Failed to click attach: {click_result.get('error')}"}

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
