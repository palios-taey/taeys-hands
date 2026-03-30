from __future__ import annotations
"""ChatGPT/Grok keyboard navigation attach path.

These platforms render dropdown menus via React portals that are invisible
to AT-SPI. Uses xdotool click → Down+Enter → handle file dialog.
Validated as the ONLY working approach across 63 commits of git history.
"""

import sys
import time
import logging
from typing import Any, Dict

IS_MACOS = sys.platform == 'darwin'

if not IS_MACOS:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
else:
    Atspi = None

from core import atspi, input as inp
from core.atspi_interact import find_element_at, atspi_click
from core.tree import find_elements
from tools.attach.buttons import get_attach_button_coords, is_attach_button_disabled
from tools.attach.dialogs import any_file_dialog_open, handle_file_dialog, close_stale_file_dialogs

logger = logging.getLogger(__name__)


def click_editable_input(doc, platform: str):
    """Click the editable input field to activate non-functional buttons.

    On some platforms (Grok fresh homepage), UI elements like the Attach
    button have 0 AT-SPI actions until the input field is focused.
    """
    # Check element cache first (populated by taey_inspect)
    from core.atspi_interact import _element_cache
    for e in _element_cache.get(platform, []):
        if e.get('role') == 'entry' and 'editable' in (e.get('states') or []):
            x, y = e.get('x'), e.get('y')
            if x and y:
                logger.info(f"Clicking editable input from cache at ({x}, {y})")
                inp.click_at(x, y)
                return

    # Fallback: search accessibility tree for editable entry
    if not doc:
        return

    if IS_MACOS:
        all_elements = find_elements(doc)
        for e in all_elements:
            if e.get('role') == 'entry' and 'editable' in (e.get('states') or []):
                x, y = e.get('x'), e.get('y')
                if x and y:
                    logger.info(f"Clicking editable input from AX tree at ({x}, {y})")
                    inp.click_at(x, y)
                    return
        return

    # Linux: DFS through raw AT-SPI tree
    def find_entry(obj, depth=0):
        if depth > 15:
            return None
        try:
            role = obj.get_role_name() or ''
            if role == 'entry':
                state_set = obj.get_state_set()
                if state_set and state_set.contains(Atspi.StateType.EDITABLE):
                    comp = obj.get_component_iface()
                    if comp:
                        ext = comp.get_extents(Atspi.CoordType.SCREEN)
                        if ext and ext.x >= 0 and ext.y >= 0:
                            return (ext.x + ext.width // 2, ext.y + ext.height // 2)
            for i in range(min(obj.get_child_count(), 50)):
                child = obj.get_child_at_index(i)
                if child:
                    result = find_entry(child, depth + 1)
                    if result:
                        return result
        except Exception:
            pass
        return None

    coords = find_entry(doc)
    if coords:
        logger.info(f"Clicking editable input from tree at ({coords[0]}, {coords[1]})")
        inp.click_at(coords[0], coords[1])


def keyboard_nav_attach(platform: str, file_path: str,
                        redis_client) -> Dict[str, Any]:
    """ChatGPT/Grok fast-path: xdotool click → Down+Enter → handle portal dialog.

    Skips all AT-SPI menu scanning (which wastes 5+ seconds and never
    finds anything on React portal platforms).

    Auto-recovery REMOVED: returns structured errors for Claude to decide.
    """
    # Short-circuit: if a file dialog is ALREADY open, handle it immediately.
    firefox = atspi.find_firefox()
    dialog_type = any_file_dialog_open(firefox)
    if dialog_type:
        logger.info(f"File dialog already open ({dialog_type}) in keyboard nav — handling directly")
        return handle_file_dialog(platform, file_path, redis_client)

    # Ensure the platform tab is actually focused in Firefox before clicking.
    if not inp.switch_to_platform(platform):
        logger.warning(f"Tab switch to {platform} may have failed")
    time.sleep(0.5)

    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    btn_coords = get_attach_button_coords(doc, platform=platform) if doc else None

    if not btn_coords:
        return {"error": f"Attach button not found for {platform}",
                "action": "button_not_found"}

    # Check if button is disabled — report to Claude, don't auto-recover
    atspi_obj = btn_coords.get('atspi_obj')
    if not IS_MACOS and is_attach_button_disabled(atspi_obj):
        return {"error": f"{platform} attach button is disabled",
                "button_state": "disabled",
                "action": "navigate_fresh_page"}

    # Dismiss any stale dropdown/popup
    inp.press_key('Escape')
    time.sleep(0.3)

    # Grok fresh homepage: Attach button exists but has 0 actions until
    # the input field is clicked/focused. Click the editable input first
    # to activate the button, then re-fetch coordinates.
    if not IS_MACOS and atspi_obj:
        try:
            action_iface = atspi_obj.get_action_iface()
            if not action_iface or action_iface.get_n_actions() == 0:
                logger.info(f"Attach button has 0 actions on {platform} — clicking input to activate")
                click_editable_input(doc, platform)
                time.sleep(1.0)
                doc = atspi.get_platform_document(firefox, platform) if firefox else doc
                btn_coords = get_attach_button_coords(doc, platform=platform) if doc else btn_coords
        except Exception as e:
            logger.debug(f"Attach button action check failed: {e}")

    # Try accessibility action first — AT-SPI do_action on Linux, AXPress on macOS
    element_for_click = find_element_at(platform, btn_coords['x'], btn_coords['y'])
    if element_for_click:
        logger.info(f"Keyboard nav attach for {platform}: accessibility action on button at ({btn_coords['x']}, {btn_coords['y']})")
        if atspi_click(element_for_click):
            time.sleep(1.5)

            dialog_type = any_file_dialog_open(firefox)
            if dialog_type:
                return handle_file_dialog(platform, file_path, redis_client)

            # Accessibility action may have opened dropdown — try Down+Enter
            inp.press_key('Down')
            time.sleep(0.5)
            inp.press_key('Return')
            time.sleep(2.5)

            for _ in range(10):
                dialog_type = any_file_dialog_open(firefox)
                if dialog_type:
                    return handle_file_dialog(platform, file_path, redis_client)
                time.sleep(0.3)

            logger.info("Accessibility action didn't produce file dialog, falling back to coordinate click")

    # Fallback: xdotool click (gives X11 keyboard focus for Down+Enter)
    logger.info(f"Keyboard nav attach for {platform}: xdotool click at ({btn_coords['x']}, {btn_coords['y']})")
    inp.click_at(btn_coords['x'], btn_coords['y'])
    time.sleep(1.5)

    dialog_type = any_file_dialog_open(firefox)
    if dialog_type:
        return handle_file_dialog(platform, file_path, redis_client)

    # Keyboard nav: Down selects first dropdown item, Enter activates it
    inp.press_key('Down')
    time.sleep(0.5)
    inp.press_key('Return')
    time.sleep(2.5)

    for _ in range(10):
        dialog_type = any_file_dialog_open(firefox)
        if dialog_type:
            return handle_file_dialog(platform, file_path, redis_client)
        time.sleep(0.3)

    # Clean up any orphaned dialogs before returning error
    try:
        close_stale_file_dialogs()
    except Exception:
        pass
    return {"error": f"Keyboard nav attach failed for {platform}: no file dialog appeared after Down+Enter"}
