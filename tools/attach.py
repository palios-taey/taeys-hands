"""
taey_attach - File attachment workflow.

Fully automated: click attach button, handle dropdown if it appears,
navigate file dialog, attach file. ONE call does everything.
"""

import json
import os
import time
import logging
from typing import Any, Dict

from core import atspi, input as inp
from core.tree import find_elements, find_dropdown_menus

logger = logging.getLogger(__name__)

# Known upload option names per platform (what appears in the dropdown)
UPLOAD_OPTION_NAMES = {
    "chatgpt": ["add photos", "add files", "upload"],
    "claude": ["add files", "upload"],
    "gemini": ["upload file", "upload"],
    "grok": ["upload a file", "upload"],
    "perplexity": ["upload file", "upload"],
}

# Attach button names - what to click to open the dropdown/dialog
ATTACH_BUTTON_NAMES = {
    "chatgpt": ["add files and more", "add files or tools", "attach"],
    "claude": ["toggle menu"],
    "gemini": ["open upload file menu"],
    "grok": ["attach"],
    "perplexity": ["add files or tools", "attach"],
}


def _click_via_atspi(doc, button_name: str, max_depth: int = 25) -> bool:
    """Click a button by name using AT-SPI do_action(0).

    More reliable than xdotool for Gemini and other React-based UIs.
    """
    target_lower = button_name.lower()

    def find_and_click(obj, depth=0):
        if depth > max_depth:
            return False
        try:
            name = (obj.get_name() or '').lower()
            role = obj.get_role_name() or ''
            if target_lower in name and role in ('push button', 'toggle button', 'button'):
                action = obj.get_action_iface()
                if action and action.get_n_actions() > 0:
                    action.do_action(0)
                    return True
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child and find_and_click(child, depth + 1):
                    return True
        except Exception:
            pass
        return False

    return find_and_click(doc)


def _find_upload_option(dropdown_items, platform: str) -> Dict | None:
    """Find the file upload option in dropdown items."""
    patterns = UPLOAD_OPTION_NAMES.get(platform, ["upload"])
    for item in dropdown_items:
        name = (item.get('name') or '').lower()
        for pattern in patterns:
            if pattern in name:
                return item
    return None


def _handle_file_dialog(platform: str, file_path: str,
                        redis_client) -> Dict[str, Any]:
    """Handle GTK file picker - type path and select file."""
    try:
        time.sleep(0.3)

        if not inp.press_key('ctrl+l'):
            return {"error": "Failed to focus location bar", "success": False}
        time.sleep(0.2)

        if not inp.type_text(file_path, timeout=15):
            return {"error": "Failed to type file path", "success": False}
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

        return {
            "success": True,
            "status": "file_attached",
            "platform": platform,
            "file_path": file_path,
            "filename": os.path.basename(file_path),
        }

    except Exception as e:
        logger.error(f"File dialog handling failed: {e}")
        return {"error": f"File dialog handling failed: {e}", "success": False}

    finally:
        if redis_client:
            redis_client.delete(f"taey:attach:pending:{platform}")


def _click_attach_button(platform: str, doc, redis_client) -> bool:
    """Click the attach button using AT-SPI first, xdotool fallback."""
    # Try AT-SPI do_action first (works reliably on Gemini and others)
    button_names = ATTACH_BUTTON_NAMES.get(platform, ["attach"])
    for name in button_names:
        if _click_via_atspi(doc, name):
            logger.info(f"Clicked attach via AT-SPI: {name}")
            return True

    # Fallback to stored map coordinates (xdotool click)
    from tools.interact import handle_click
    click_result = handle_click(platform, "attach", redis_client)
    if click_result.get("success"):
        logger.info("Clicked attach via stored map coordinates")
        return True

    return False


def handle_attach(platform: str, file_path: str,
                  redis_client) -> Dict[str, Any]:
    """Attach a file to the chat input.

    Fully automated single-call flow:
    1. Click attach button (AT-SPI first, xdotool fallback)
    2. If file dialog opens → handle it
    3. If dropdown opens → find upload option → click it → handle file dialog

    Args:
        platform: Which platform.
        file_path: Absolute path to file.
        redis_client: Redis client.

    Returns:
        Success or failure with details.
    """
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}", "success": False}

    firefox = atspi.find_firefox()
    if not firefox:
        return {"error": "Firefox not found", "success": False}

    # If file dialog is already open, handle it directly
    if atspi.is_file_dialog_open(firefox):
        return _handle_file_dialog(platform, file_path, redis_client)

    # Get platform document for AT-SPI operations
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {"error": f"Could not find {platform} document", "success": False}

    # Step 1: Click the attach button
    if not _click_attach_button(platform, doc, redis_client):
        return {"error": "Failed to click attach button", "success": False}

    time.sleep(1.0)

    # Step 2: Check if file dialog opened directly (some platforms skip dropdown)
    firefox = atspi.find_firefox()
    if atspi.is_file_dialog_open(firefox):
        return _handle_file_dialog(platform, file_path, redis_client)

    # Step 3: Dropdown must have appeared - find and click the upload option
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    dropdown_items = find_dropdown_menus(firefox, doc)

    if not dropdown_items:
        # Brief wait and retry - dropdown might be rendering
        time.sleep(0.5)
        dropdown_items = find_dropdown_menus(firefox, doc)

    if not dropdown_items:
        return {
            "error": "No dropdown or file dialog appeared after clicking attach",
            "success": False,
            "hint": "The attach button click may not have triggered. Try taey_inspect to verify.",
        }

    # Find the upload/file option in the dropdown
    upload_option = _find_upload_option(dropdown_items, platform)

    if not upload_option:
        return {
            "error": "Could not find upload option in dropdown",
            "success": False,
            "dropdown_items": dropdown_items,
            "hint": "Dropdown opened but no upload option matched. Check dropdown items above.",
        }

    # Click the upload option
    x, y = upload_option['x'], upload_option['y']
    logger.info(f"Clicking upload option '{upload_option.get('name')}' at ({x}, {y})")
    inp.click_at(x, y)

    # Step 4: Wait for file dialog to appear
    firefox = atspi.find_firefox()
    dialog_found = False
    for _ in range(20):
        time.sleep(0.3)
        if atspi.is_file_dialog_open(firefox):
            dialog_found = True
            break

    if not dialog_found:
        return {
            "error": "File dialog did not open after clicking upload option",
            "success": False,
            "clicked_option": upload_option.get('name'),
            "hint": "Upload option was clicked but no file dialog appeared.",
        }

    # Step 5: Handle file dialog
    return _handle_file_dialog(platform, file_path, redis_client)
