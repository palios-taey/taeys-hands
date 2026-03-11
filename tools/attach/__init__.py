from __future__ import annotations
"""
taey_attach - File attachment workflow (decomposed).

Multi-step process: click attach button, detect what appeared
(file dialog vs dropdown), handle accordingly. Claude stays
in the loop for dropdown decisions.

Auto-recovery REMOVED: tools report structured errors, Claude decides
whether to navigate fresh and retry.
"""

import json
import os
import time
import logging
from typing import Any, Dict

from core import atspi, input as inp
from core.tree import find_menu_items
from core.atspi_interact import extend_cache, strip_atspi_obj, find_element_at, atspi_click
from storage.redis_pool import node_key
from tools.interact import handle_click

from tools.attach.buttons import get_attach_button_coords
from tools.attach.chips import detect_existing_attachments
from tools.attach.dialogs import (
    any_file_dialog_open, handle_file_dialog, close_stale_file_dialogs,
)
from tools.attach.keyboard_nav import keyboard_nav_attach

logger = logging.getLogger(__name__)

# Platforms where the dropdown is a React portal invisible to AT-SPI.
_KEYBOARD_NAV_PLATFORMS = {'chatgpt', 'grok'}


def handle_attach(platform: str, file_path: str,
                  redis_client) -> Dict[str, Any]:
    """Attach a file to the chat input.

    Platform-aware strategy:
    - ChatGPT/Grok: xdotool click → Down+Enter (React portal dropdown)
    - Others: AT-SPI menu scan with Claude-in-the-loop for dropdown selection

    Always cleans up stale file dialogs before starting.
    Detects both GTK embedded and Nautilus portal file dialogs.
    """
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}

    # Path sandboxing: prevent exfiltration of sensitive files
    real_path = os.path.realpath(file_path)
    _ALLOWED_DIRS = [
        os.path.expanduser('~'),
        '/tmp',
        '/var/spark',
    ]
    if not any(real_path.startswith(d) for d in _ALLOWED_DIRS):
        return {"error": f"Path not in allowed directories: {real_path}"}

    firefox = atspi.find_firefox()

    # Short-circuit: if a file dialog is ALREADY open, handle it immediately.
    dialog_type = any_file_dialog_open(firefox)
    if dialog_type:
        logger.info(f"File dialog already open ({dialog_type}) — handling directly")
        return handle_file_dialog(platform, file_path, redis_client)

    # Check for pending attach (continuing after dropdown click)
    pending = None
    if redis_client:
        pending_json = redis_client.get(node_key(f"attach:pending:{platform}"))
        if pending_json:
            try:
                pending = json.loads(pending_json)
            except json.JSONDecodeError:
                pass

    # Only clean up stale dialogs when there's NO pending attach
    if not pending:
        close_stale_file_dialogs()
        # Dismiss any open dropdown/popup before clicking attach button
        inp.press_key('Escape')
        time.sleep(0.3)

    # Pre-check: skip if this exact file is already attached
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    existing = detect_existing_attachments(doc)
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

    # If pending, wait for file dialog to appear (GTK or portal)
    if pending:
        for _ in range(15):
            dialog_type = any_file_dialog_open(firefox)
            if dialog_type:
                return handle_file_dialog(platform, file_path, redis_client)
            time.sleep(0.2)
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))
    else:
        dialog_type = any_file_dialog_open(firefox)
        if dialog_type:
            return handle_file_dialog(platform, file_path, redis_client)

    # =========================================================================
    # ChatGPT/Grok fast-path: keyboard nav (skip AT-SPI menu scanning)
    # =========================================================================
    if platform in _KEYBOARD_NAV_PLATFORMS:
        return keyboard_nav_attach(platform, file_path, redis_client)

    # =========================================================================
    # Other platforms: AT-SPI menu scan with Claude-in-the-loop
    # =========================================================================
    dropdown_items = []
    logger.info("Searching AT-SPI tree for attach button")
    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    btn_coords = get_attach_button_coords(doc, platform=platform) if doc else None

    if btn_coords:
        # Prefer direct AT-SPI do_action(0) — proven reliable on Gemini/Claude
        # where coordinate clicks fail to trigger React event handlers.
        atspi_obj = btn_coords.get('atspi_obj')
        click_result = None
        if atspi_obj:
            try:
                ai = atspi_obj.get_action_iface()
                if ai and ai.get_n_actions() > 0:
                    ai.do_action(0)
                    click_result = {"method": "atspi_direct", "platform": platform}
                    logger.info("Attach button clicked via direct do_action(0)")
            except Exception as e:
                logger.warning(f"Direct do_action failed: {e}")
        if not click_result:
            click_result = handle_click(platform, btn_coords['x'], btn_coords['y'])
        click_failed = bool(click_result.get("error"))

        if not click_failed:
            time.sleep(1.0)

            # Check if file dialog opened (GTK or portal)
            dialog_type = any_file_dialog_open(firefox)
            if dialog_type:
                return handle_file_dialog(platform, file_path, redis_client)

            # Scan for dropdown items (retry for slow renders)
            for attempt in range(3):
                firefox = atspi.find_firefox()
                doc = atspi.get_platform_document(firefox, platform) if firefox else None
                dropdown_items = find_menu_items(firefox, doc)
                if dropdown_items:
                    break
                time.sleep(0.5)

            # If AT-SPI click was used but no dropdown, retry with xdotool
            if not dropdown_items and click_result.get("method") in ("atspi", "atspi_direct"):
                logger.info("AT-SPI click didn't open dropdown, retrying with xdotool")
                inp.click_at(btn_coords['x'], btn_coords['y'])
                time.sleep(1.0)
                dialog_type = any_file_dialog_open(firefox)
                if dialog_type:
                    return handle_file_dialog(platform, file_path, redis_client)
                for attempt in range(3):
                    firefox = atspi.find_firefox()
                    doc = atspi.get_platform_document(firefox, platform) if firefox else None
                    dropdown_items = find_menu_items(firefox, doc)
                    if dropdown_items:
                        break
                    time.sleep(0.5)
    else:
        logger.info("Attach button not found via AT-SPI tree search")

    # Fallback: accessibility action directly (bypasses coordinate click)
    if not dropdown_items and not any_file_dialog_open(firefox):
        logger.info("Trying accessibility action fallback")
        btn_coords_fb = get_attach_button_coords(
            atspi.get_platform_document(atspi.find_firefox(), platform),
            platform=platform)
        if btn_coords_fb:
            inp.press_key('Escape')
            time.sleep(0.3)
            el = find_element_at(platform, btn_coords_fb['x'], btn_coords_fb['y'])
            if el and atspi_click(el):
                logger.info("Accessibility action on attach button")
                time.sleep(1.5)
                dialog_type = any_file_dialog_open(firefox)
                if dialog_type:
                    return handle_file_dialog(platform, file_path, redis_client)
                for attempt in range(3):
                    firefox = atspi.find_firefox()
                    doc = atspi.get_platform_document(firefox, platform) if firefox else None
                    dropdown_items = find_menu_items(firefox, doc)
                    if dropdown_items:
                        break
                    time.sleep(0.5)

    # Return dropdown items for Claude to pick from (no auto-recovery)
    if not dropdown_items and not any_file_dialog_open(firefox):
        return {"error": f"No dropdown items or file dialog found for {platform}",
                "action": "attach_button_failed"}

    # Cache dropdown items so taey_click can use AT-SPI do_action
    if dropdown_items:
        extend_cache(platform, dropdown_items)

    # Store pending state for when Claude clicks an item (120s TTL)
    if redis_client:
        redis_client.setex(node_key(f"attach:pending:{platform}"), 120, json.dumps({
            'file_path': file_path,
            'timestamp': time.time(),
        }))

    # Strip atspi_obj for JSON serialization
    serializable_items = strip_atspi_obj(dropdown_items) if dropdown_items else []

    return {
        "status": "dropdown_open",
        "message": "Dropdown opened. Select the file upload option with click_at, then call attach again.",
        "file_path": file_path,
        "dropdown_items": serializable_items,
    }
