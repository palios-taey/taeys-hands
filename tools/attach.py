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
from tools.interact import handle_click
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)

# Platforms where the dropdown is a React portal invisible to AT-SPI.
# These need xdotool click + keyboard nav (Down+Enter) instead of
# AT-SPI menu scanning. Validated across 63 commits of git history.
_KEYBOARD_NAV_PLATFORMS = {'chatgpt', 'grok'}

_XDOTOOL_ENV = None

def _xenv():
    """Subprocess env with DISPLAY set for xdotool/xsel calls."""
    global _XDOTOOL_ENV
    if _XDOTOOL_ENV is None:
        _XDOTOOL_ENV = {**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':0')}
    return _XDOTOOL_ENV


# =========================================================================
# Portal dialog detection (Nautilus / xdg-desktop-portal-gnome)
# =========================================================================

def _find_portal_dialog_wids() -> List[str]:
    """Find Nautilus file dialog windows via xdotool.

    ChatGPT and Perplexity use xdg-desktop-portal-gnome which opens a
    Nautilus window as a separate process. This is invisible to
    is_file_dialog_open() which only checks Firefox's AT-SPI tree.

    Returns list of window IDs (newest last).
    """
    try:
        result = subprocess.run(
            ['xdotool', 'search', '--class', 'Nautilus'],
            capture_output=True, text=True, timeout=3, env=_xenv(),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split('\n')
    except Exception as e:
        logger.debug(f"Nautilus search failed: {e}")
    return []


def _close_stale_file_dialogs():
    """Close orphaned Nautilus and GTK file dialog windows from previous attempts.

    Must be called BEFORE starting a new attach to prevent stale windows
    from intercepting keyboard input.
    """
    closed = 0

    # Close Nautilus portal dialogs
    for wid in _find_portal_dialog_wids():
        try:
            subprocess.run(
                ['xdotool', 'windowclose', wid],
                capture_output=True, timeout=3, env=_xenv(),
            )
            closed += 1
        except Exception:
            pass

    # Close GTK file dialogs embedded in Firefox
    for title in ['File Upload', 'Open', 'Open File']:
        try:
            result = subprocess.run(
                ['xdotool', 'search', '--name', title],
                capture_output=True, text=True, timeout=2, env=_xenv(),
            )
            if result.stdout.strip():
                for wid in result.stdout.strip().split('\n'):
                    subprocess.run(
                        ['xdotool', 'windowclose', wid],
                        capture_output=True, timeout=3, env=_xenv(),
                    )
                    closed += 1
        except Exception:
            pass

    if closed:
        logger.info(f"Closed {closed} stale file dialog window(s)")
        time.sleep(0.5)


def _handle_portal_dialog(platform: str, file_path: str,
                          redis_client) -> Dict[str, Any]:
    """Handle Nautilus portal file dialog (ChatGPT, Perplexity).

    Nautilus portal is a separate window (not in Firefox AT-SPI tree).
    Focus it, open location bar with Ctrl+L, paste path, Enter.
    """
    try:
        wids = _find_portal_dialog_wids()
        if not wids:
            return {"error": "Portal dialog detected but window not found"}

        # Use the newest Nautilus window (highest ID = most recently opened)
        wid = wids[-1]
        logger.info(f"Handling Nautilus portal dialog window {wid}")

        # Focus the Nautilus window
        subprocess.run(
            ['xdotool', 'windowactivate', '--sync', wid],
            capture_output=True, timeout=3, env=_xenv(),
        )
        time.sleep(0.5)

        # Open location bar (Ctrl+L in Nautilus)
        if not inp.press_key('ctrl+l'):
            return {"error": "Failed to open Nautilus location bar"}
        time.sleep(0.5)

        # Paste file path via clipboard
        inp.clipboard_paste(file_path)
        time.sleep(0.3)

        # Enter to navigate/select
        if not inp.press_key('Return'):
            return {"error": "Failed to press Return in Nautilus dialog"}
        time.sleep(1.0)

        # Check if dialog closed (Nautilus window gone)
        dialog_closed = False
        for _ in range(20):
            time.sleep(0.3)
            remaining = _find_portal_dialog_wids()
            if wid not in remaining:
                dialog_closed = True
                break

        if not dialog_closed:
            logger.warning("Nautilus dialog did not close — may need second Enter")
            inp.press_key('Return')
            time.sleep(1.0)
            remaining = _find_portal_dialog_wids()
            dialog_closed = wid not in remaining

        if not dialog_closed:
            return {"error": "Nautilus portal dialog did not close after file selection"}

        # Re-focus Firefox after Nautilus dialog closes
        inp.focus_firefox()
        time.sleep(0.5)

        # Update attachment checkpoint
        _update_checkpoint(platform, file_path, redis_client)

        return {
            "status": "file_attached",
            "platform": platform,
            "file_path": file_path,
            "filename": os.path.basename(file_path),
            "dialog_type": "nautilus_portal",
            "info": "File chip may shift element positions - re-inspect before further clicks.",
        }

    except Exception as e:
        logger.error(f"Portal dialog handling failed: {e}")
        return {"error": f"Portal dialog handling failed: {e}"}

    finally:
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))


def _any_file_dialog_open(firefox) -> str:
    """Check for ANY type of file dialog (GTK embedded or Nautilus portal).

    Returns:
        'gtk' if Firefox embedded GTK file chooser found,
        'portal' if Nautilus portal window found,
        '' if no dialog found.
    """
    if atspi.is_file_dialog_open(firefox):
        return 'gtk'
    if _find_portal_dialog_wids():
        return 'portal'
    return ''


# =========================================================================
# Shared helpers
# =========================================================================

def _update_checkpoint(platform: str, file_path: str, redis_client):
    """Update Redis attachment checkpoint after successful attach."""
    if not redis_client:
        return
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


def _handle_file_dialog(platform: str, file_path: str,
                        redis_client) -> Dict[str, Any]:
    """Handle file dialog — detects type (GTK embedded vs Nautilus portal) and routes."""
    firefox = atspi.find_firefox()
    dialog_type = _any_file_dialog_open(firefox)

    if dialog_type == 'portal':
        return _handle_portal_dialog(platform, file_path, redis_client)

    # GTK embedded file dialog (Gemini, Grok, sometimes Claude)
    return _handle_gtk_file_dialog(platform, file_path, redis_client)


def _handle_gtk_file_dialog(platform: str, file_path: str,
                            redis_client) -> Dict[str, Any]:
    """Handle GTK file picker embedded in Firefox — focus dialog, type path, select file."""
    try:
        time.sleep(0.3)

        # Focus the file dialog window FIRST — otherwise Ctrl+L goes to Firefox address bar
        try:
            dialog_wids = []
            for title in ['File Upload', 'Open', 'Open File']:
                result = subprocess.run(
                    ['xdotool', 'search', '--name', title],
                    capture_output=True, text=True, timeout=2, env=_xenv(),
                )
                if result.stdout.strip():
                    dialog_wids = result.stdout.strip().split('\n')
                    break
            if dialog_wids and dialog_wids[0]:
                subprocess.run(
                    ['xdotool', 'windowactivate', '--sync', dialog_wids[0]],
                    capture_output=True, timeout=3, env=_xenv(),
                )
                time.sleep(0.3)
                logger.info(f"Focused GTK file dialog window {dialog_wids[0]}")
        except Exception as e:
            logger.warning(f"Could not focus GTK file dialog window: {e}")

        # Use "/" to open GTK location entry — avoids Ctrl+L conflict
        # where Firefox intercepts Ctrl+L for its URL bar.
        # In GTK file choosers, typing "/" opens the path entry directly.
        inp.type_text('/')
        time.sleep(0.3)

        # Clipboard paste rest of path (without leading /)
        rest_of_path = file_path.lstrip('/')
        inp.clipboard_paste(rest_of_path)
        time.sleep(0.2)

        # Enter to navigate to file
        if not inp.press_key('Return'):
            return {"error": "Failed to press Return (navigate)"}
        time.sleep(0.3)

        # For directory paths, need a second Return to confirm.
        # For full file paths, this is harmless (confirms the selection).
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
            return {"error": "GTK file dialog did not close after selection"}

        time.sleep(0.5)
        _update_checkpoint(platform, file_path, redis_client)

        return {
            "status": "file_attached",
            "platform": platform,
            "file_path": file_path,
            "filename": os.path.basename(file_path),
            "dialog_type": "gtk_embedded",
            "info": "File chip may shift element positions - re-inspect before further clicks.",
        }

    except Exception as e:
        logger.error(f"GTK file dialog handling failed: {e}")
        return {"error": f"GTK file dialog handling failed: {e}"}

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


def _get_attach_button_coords(doc) -> Dict | None:
    """Find attach button and return its center coordinates.

    Returns dict with x, y if found, None otherwise.
    """
    btn = _find_attach_button(doc)
    if not btn:
        return None
    try:
        comp = btn.get_component_iface()
        if comp:
            ext = comp.get_extents(Atspi.CoordType.SCREEN)
            if ext.width > 0 and ext.height > 0:
                return {
                    'x': ext.x + ext.width // 2,
                    'y': ext.y + ext.height // 2,
                    'atspi_obj': btn,
                }
    except Exception:
        pass
    return None


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
    if remove_buttons:
        return [{'file': fn, 'remove_buttons': remove_buttons} for fn in file_names] or \
               [{'file': '(unknown)', 'remove_buttons': remove_buttons}]

    # Detect unnamed file chips (Grok/Perplexity pattern):
    # Unnamed push buttons clustered just above the input entry field.
    entry_y = None
    for e in all_elements:
        if e.get('role') == 'entry' and 'editable' in (e.get('states') or []):
            entry_y = e.get('y', 0)
            break

    if entry_y:
        unnamed_chips = [
            e for e in all_elements
            if (e.get('role') == 'push button'
                and not (e.get('name') or '').strip()
                and entry_y - 100 < e.get('y', 0) < entry_y - 10)
        ]
        if unnamed_chips:
            return [{'file': '(unknown)', 'remove_buttons': [
                {'x': b.get('x'), 'y': b.get('y'), 'name': ''} for b in unnamed_chips
            ]}]

    return []


def _keyboard_nav_attach(platform: str, file_path: str,
                         redis_client) -> Dict[str, Any]:
    """ChatGPT/Grok fast-path: xdotool click → Down+Enter → handle portal dialog.

    These platforms render dropdown menus via React portals that are invisible
    to AT-SPI. Skips all AT-SPI menu scanning (which wastes 5+ seconds and
    never finds anything). Goes straight to keyboard navigation.

    Validated as the ONLY working approach across 63 commits of git history.
    """
    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    btn_coords = _get_attach_button_coords(doc) if doc else None

    if not btn_coords:
        return {"error": f"Attach button not found for {platform}"}

    # Dismiss any stale dropdown/popup
    inp.press_key('Escape')
    time.sleep(0.3)

    # xdotool click gives X11 keyboard focus (required for Down+Enter to hit the dropdown)
    logger.info(f"Keyboard nav attach for {platform}: clicking button at ({btn_coords['x']}, {btn_coords['y']})")
    inp.click_at(btn_coords['x'], btn_coords['y'])
    time.sleep(0.8)

    # Check if a file dialog already opened directly (some states skip dropdown)
    dialog_type = _any_file_dialog_open(firefox)
    if dialog_type:
        return _handle_file_dialog(platform, file_path, redis_client)

    # Keyboard nav: Down selects first dropdown item, Enter activates it
    inp.press_key('Down')
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(2.0)

    # Check for file dialog (either GTK embedded or Nautilus portal)
    for _ in range(10):
        dialog_type = _any_file_dialog_open(firefox)
        if dialog_type:
            return _handle_file_dialog(platform, file_path, redis_client)
        time.sleep(0.3)

    return {"error": f"Keyboard nav attach failed for {platform}: no file dialog appeared after Down+Enter"}


def handle_attach(platform: str, file_path: str,
                  redis_client) -> Dict[str, Any]:
    """Attach a file to the chat input.

    Platform-aware strategy:
    - ChatGPT/Grok: xdotool click → Down+Enter (React portal dropdown invisible to AT-SPI)
    - Others: AT-SPI menu scan with Claude-in-the-loop for dropdown selection

    Always cleans up stale file dialogs before starting.
    Detects both GTK embedded and Nautilus portal file dialogs.
    """
    if not os.path.isfile(file_path):
        return {"error": f"File not found: {file_path}"}

    firefox = atspi.find_firefox()

    # Check for pending attach FIRST (continuing after dropdown click)
    # A pending attach means a dialog should be opening — don't close it!
    pending = None
    if redis_client:
        pending_json = redis_client.get(node_key(f"attach:pending:{platform}"))
        if pending_json:
            try:
                pending = json.loads(pending_json)
            except json.JSONDecodeError:
                pass

    # Only clean up stale dialogs when there's NO pending attach
    # (pending means we just triggered a dialog and need it open)
    if not pending:
        _close_stale_file_dialogs()

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

    # If pending, wait for file dialog to appear (GTK or portal)
    if pending:
        for _ in range(15):
            dialog_type = _any_file_dialog_open(firefox)
            if dialog_type:
                return _handle_file_dialog(platform, file_path, redis_client)
            time.sleep(0.2)
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))
    else:
        dialog_type = _any_file_dialog_open(firefox)
        if dialog_type:
            return _handle_file_dialog(platform, file_path, redis_client)

    # =========================================================================
    # ChatGPT/Grok fast-path: keyboard nav (skip AT-SPI menu scanning)
    # React portal dropdowns are invisible to AT-SPI. Scanning wastes time.
    # =========================================================================
    if platform in _KEYBOARD_NAV_PLATFORMS:
        return _keyboard_nav_attach(platform, file_path, redis_client)

    # =========================================================================
    # Other platforms: AT-SPI menu scan with Claude-in-the-loop
    # =========================================================================
    dropdown_items = []
    logger.info("Searching AT-SPI tree for attach button")
    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    btn_coords = _get_attach_button_coords(doc) if doc else None

    if btn_coords:
        # Click via platform-aware handle_click (xdotool for non-Gemini,
        # AT-SPI for Gemini)
        click_result = handle_click(platform, btn_coords['x'], btn_coords['y'])
        click_failed = bool(click_result.get("error"))

        if not click_failed:
            time.sleep(1.0)

            # Check if file dialog opened (GTK or portal)
            dialog_type = _any_file_dialog_open(firefox)
            if dialog_type:
                return _handle_file_dialog(platform, file_path, redis_client)

            # Scan for dropdown items (retry for slow renders)
            for attempt in range(3):
                firefox = atspi.find_firefox()
                doc = atspi.get_platform_document(firefox, platform) if firefox else None
                dropdown_items = find_menu_items(firefox, doc)
                if dropdown_items:
                    break
                time.sleep(0.5)

            # If AT-SPI click was used but no dropdown, retry with xdotool
            if not dropdown_items and click_result.get("method") == "atspi":
                logger.info("AT-SPI click didn't open dropdown, retrying with xdotool")
                inp.click_at(btn_coords['x'], btn_coords['y'])
                time.sleep(1.0)
                dialog_type = _any_file_dialog_open(firefox)
                if dialog_type:
                    return _handle_file_dialog(platform, file_path, redis_client)
                for attempt in range(3):
                    firefox = atspi.find_firefox()
                    doc = atspi.get_platform_document(firefox, platform) if firefox else None
                    dropdown_items = find_menu_items(firefox, doc)
                    if dropdown_items:
                        break
                    time.sleep(0.5)
    else:
        logger.info("Attach button not found via AT-SPI tree search")

    # Fallback: AT-SPI do_action directly (bypasses coordinate click)
    if not dropdown_items and not _any_file_dialog_open(firefox):
        logger.info("Trying AT-SPI do_action fallback")
        firefox = atspi.find_firefox()
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        attach_btn = _find_attach_button(doc) if doc else None
        if attach_btn:
            inp.press_key('Escape')
            time.sleep(0.3)
            action_iface = attach_btn.get_action_iface()
            if action_iface and action_iface.get_n_actions() > 0:
                logger.info("AT-SPI do_action on attach button")
                action_iface.do_action(0)
                time.sleep(1.5)
                dialog_type = _any_file_dialog_open(firefox)
                if dialog_type:
                    return _handle_file_dialog(platform, file_path, redis_client)
                for attempt in range(3):
                    firefox = atspi.find_firefox()
                    doc = atspi.get_platform_document(firefox, platform) if firefox else None
                    dropdown_items = find_menu_items(firefox, doc)
                    if dropdown_items:
                        break
                    time.sleep(0.5)

    # Fallback: Keyboard navigation (Down+Enter) for AT-SPI-invisible dropdowns
    if not dropdown_items and not _any_file_dialog_open(firefox):
        logger.info("Trying keyboard nav fallback: Down+Enter for invisible dropdown")
        firefox = atspi.find_firefox()
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        btn_coords = _get_attach_button_coords(doc) if doc else None
        if btn_coords:
            inp.press_key('Escape')
            time.sleep(0.3)
            inp.click_at(btn_coords['x'], btn_coords['y'])
            time.sleep(1.0)
            dialog_type = _any_file_dialog_open(firefox)
            if dialog_type:
                return _handle_file_dialog(platform, file_path, redis_client)
            inp.press_key('Down')
            time.sleep(0.2)
            inp.press_key('Return')
            time.sleep(1.5)
            # Check for both dialog types
            for _ in range(5):
                dialog_type = _any_file_dialog_open(firefox)
                if dialog_type:
                    return _handle_file_dialog(platform, file_path, redis_client)
                time.sleep(0.3)
            logger.warning("Keyboard nav fallback did not open any file dialog")

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
