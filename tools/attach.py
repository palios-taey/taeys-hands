"""
taey_attach - File attachment workflow.

Multi-step process: click attach button, detect what appeared
(file dialog vs dropdown), handle accordingly. Claude stays
in the loop for dropdown decisions.
"""

import json
import os
import time
import logging
from typing import Any, Dict

from core import atspi, input as inp, clipboard
from core.tree import find_elements, find_dropdown_menus
from tools.interact import handle_click

logger = logging.getLogger(__name__)


def _handle_file_dialog(platform: str, file_path: str,
                        redis_client) -> Dict[str, Any]:
    """Handle GTK file picker - type path and select file."""
    try:
        time.sleep(0.3)

        if not inp.press_key('ctrl+l'):
            return {"error": "Failed to focus location bar", "success": False}
        time.sleep(0.2)

        # Clipboard paste - xdotool type_text drops doubled letters
        clipboard.write_marker(file_path)
        time.sleep(0.1)
        if not inp.press_key('ctrl+v'):
            return {"error": "Failed to paste file path", "success": False}
        time.sleep(0.2)

        # First Return - navigate to path
        if not inp.press_key('Return'):
            return {"error": "Failed to press Return (navigate)", "success": False}
        time.sleep(0.3)

        # Second Return - confirm selection
        if not inp.press_key('Return'):
            return {"error": "Failed to press Return (confirm)", "success": False}

        # Wait for dialog to close
        firefox = atspi.find_firefox()
        dialog_closed = False
        for _ in range(25):
            time.sleep(0.2)
            if not atspi.is_file_dialog_open(firefox):
                dialog_closed = True
                break

        if not dialog_closed:
            return {"error": "File dialog did not close after selection", "success": False}

        time.sleep(0.5)

        # Update attachment checkpoint
        if redis_client:
            existing = redis_client.get(f"taey:checkpoint:{platform}:attach")
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

            redis_client.set(f"taey:checkpoint:{platform}:attach", json.dumps({
                'attached_count': count,
                'attached_files': files,
                'last_file': file_path,
                'timestamp': time.time(),
            }))

        # Invalidate stored map - file chip shifts input position
        if redis_client:
            redis_client.delete("taey:v4:current_map")

        return {
            "success": True,
            "status": "file_attached",
            "platform": platform,
            "file_path": file_path,
            "filename": os.path.basename(file_path),
            "info": "Map invalidated - re-inspect before further clicks.",
        }

    except Exception as e:
        logger.error(f"File dialog handling failed: {e}")
        return {"error": f"File dialog handling failed: {e}", "success": False}

    finally:
        if redis_client:
            redis_client.delete(f"taey:attach:pending:{platform}")


def handle_attach(platform: str, file_path: str,
                  redis_client) -> Dict[str, Any]:
    """Attach a file to the chat input.

    Multi-step with Claude in the loop:
    1. Click attach button
    2. If file dialog opened → handle selection
    3. If dropdown appeared → return items for Claude to decide

    Args:
        platform: Which platform.
        file_path: Absolute path to file.
        redis_client: Redis client.

    Returns:
        Either success (file attached) or dropdown items for Claude.
    """
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}", "success": False}

    firefox = atspi.find_firefox()

    # Check for pending attach (continuing after dropdown click)
    pending = None
    if redis_client:
        pending_json = redis_client.get(f"taey:attach:pending:{platform}")
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
            redis_client.delete(f"taey:attach:pending:{platform}")
    elif atspi.is_file_dialog_open(firefox):
        return _handle_file_dialog(platform, file_path, redis_client)

    # Click attach button
    click_result = handle_click(platform, "attach", redis_client)
    if not click_result.get("success"):
        return {"error": f"Failed to click attach: {click_result.get('error')}", "success": False}

    time.sleep(1.0)

    # Check if file dialog opened
    if atspi.is_file_dialog_open(firefox):
        return _handle_file_dialog(platform, file_path, redis_client)

    # Dropdown appeared - find items
    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    dropdown_items = find_dropdown_menus(firefox, doc)

    # Store pending state for when Claude clicks an item
    if redis_client:
        redis_client.setex(f"taey:attach:pending:{platform}", 30, json.dumps({
            'file_path': file_path,
            'timestamp': time.time(),
        }))

    return {
        "success": True,
        "status": "dropdown_open",
        "message": "Dropdown opened. Select the file upload option with click_at, then call attach again.",
        "file_path": file_path,
        "dropdown_items": dropdown_items,
    }
