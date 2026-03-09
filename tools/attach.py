from __future__ import annotations
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

import sys
IS_MACOS = sys.platform == 'darwin'

if not IS_MACOS:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
else:
    Atspi = None  # macOS uses AXUIElement API instead

from core import atspi, input as inp, clipboard
from core.tree import find_elements, filter_useful_elements, detect_chrome_y, find_menu_items
from core.atspi_interact import extend_cache, strip_atspi_obj, atspi_click, find_element_at
from tools.interact import handle_click
from storage.redis_pool import node_key

logger = logging.getLogger(__name__)

# Platforms where the dropdown is a React portal invisible to AT-SPI.
# These need xdotool click + keyboard nav (Down+Enter) instead of
# AT-SPI menu scanning. Validated across 63 commits of git history.
_KEYBOARD_NAV_PLATFORMS = {'chatgpt', 'grok'}

# Button names for attach/upload triggers across platforms.
# Used by both cache lookup and tree search.
_ATTACH_NAMES = [
    'open upload file menu',  # Gemini
    'attach',                 # Grok
    'add files and more',     # ChatGPT
    'add files or tools',     # Perplexity
    'toggle menu',            # Claude (attach trigger)
]

_XDOTOOL_ENV = None

# Gemini follow-up pages disable upload. Detect and auto-navigate to fresh page.
_GEMINI_DISABLED_PHRASES = {'menu actions are disabled', 'disabled for follow'}


def _xenv():
    """Subprocess env with DISPLAY set for xdotool/xsel calls."""
    global _XDOTOOL_ENV
    if _XDOTOOL_ENV is None:
        _XDOTOOL_ENV = {**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':0')}
    return _XDOTOOL_ENV


def _gemini_navigate_fresh():
    """Navigate Gemini tab to a fresh conversation page.

    On follow-up conversations, Gemini disables file upload ("Menu actions
    are disabled for follow ups"). This navigates to gemini.google.com/app
    to get a clean input state.

    Returns True if navigation was attempted.
    """
    return _navigate_fresh_chat('gemini')


def _is_gemini_dropdown_disabled(dropdown_items: list) -> bool:
    """Check if Gemini dropdown items indicate upload is disabled."""
    if not dropdown_items:
        return False
    for item in dropdown_items:
        name = (item.get('name') or '').lower()
        if any(phrase in name for phrase in _GEMINI_DISABLED_PHRASES):
            return True
    return False


def _is_attach_button_disabled(atspi_obj) -> bool:
    """Check if ChatGPT's 'Add files and more' button is disabled.

    On stale/streaming ChatGPT pages, the attach button exists in the
    AT-SPI tree but with ENABLED=False. Clicking it does nothing.
    """
    if IS_MACOS or not atspi_obj:
        return False
    try:
        state_set = atspi_obj.get_state_set()
        return not state_set.contains(Atspi.StateType.ENABLED)
    except Exception:
        return False


def _navigate_fresh_chat(platform: str) -> bool:
    """Navigate a chat platform tab to a fresh conversation page.

    On stale conversations or during streaming, attach buttons may be
    disabled or missing. Navigating to the platform's base URL gives
    a clean input state.

    Returns True if navigation was attempted.
    """
    from core.platforms import BASE_URLS
    url = BASE_URLS.get(platform)
    if not url:
        logger.error(f"No base URL for {platform}")
        return False
    # ChatGPT: use temporary-chat to avoid Developer Mode
    if platform == 'chatgpt':
        url = 'https://chatgpt.com/?temporary-chat=true'

    logger.info(f"{platform} attach recovery — navigating to fresh page: {url}")
    inp.press_key('Escape')
    time.sleep(0.3)
    inp.press_key('ctrl+l')
    time.sleep(0.5)
    if not inp.clipboard_paste(url):
        logger.error(f"Failed to paste {platform} URL")
        return False
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(4.0)
    return True


# =========================================================================
# Portal dialog detection (Nautilus / xdg-desktop-portal-gnome)
# =========================================================================

def _find_portal_dialog_wids() -> List[str]:
    """Find Nautilus file dialog windows via xdotool.

    ChatGPT and Perplexity use xdg-desktop-portal-gnome which opens a
    Nautilus window as a separate process. This is invisible to
    is_file_dialog_open() which only checks Firefox's AT-SPI tree.

    Returns list of window IDs (newest last).
    On macOS, returns empty (no Nautilus/xdotool).
    """
    if IS_MACOS:
        return []
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
    On macOS, this is a no-op (native file dialogs are modal sheets).
    """
    if IS_MACOS:
        return

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
    Not used on macOS (Chrome uses native NSOpenPanel sheets).
    """
    if IS_MACOS:
        return {"error": "Portal dialog handling not supported on macOS"}
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
    """Update Redis attachment checkpoint after successful attach.

    Deduplicates: if this exact file_path is already in the checkpoint,
    don't increment the count or append again. This prevents the
    double-count bug when taey_attach is called multiple times for the
    same file (e.g., dropdown_open → click item → file_dialog).
    """
    if not redis_client:
        return
    existing = redis_client.get(node_key(f"checkpoint:{platform}:attach"))
    if existing:
        try:
            data = json.loads(existing)
            files = data.get('attached_files', [])
            # Deduplicate: skip if this file is already recorded
            if file_path in files:
                logger.debug(f"Checkpoint already has {file_path}, skipping duplicate")
                return
            files.append(file_path)
            count = len(files)
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
    """Handle file dialog — detects type and routes to platform-specific handler."""
    if IS_MACOS:
        return _handle_mac_file_dialog(platform, file_path, redis_client)

    firefox = atspi.find_firefox()
    dialog_type = _any_file_dialog_open(firefox)

    if dialog_type == 'portal':
        return _handle_portal_dialog(platform, file_path, redis_client)

    # GTK embedded file dialog (Gemini, Grok, sometimes Claude)
    return _handle_gtk_file_dialog(platform, file_path, redis_client)


def _handle_mac_file_dialog(platform: str, file_path: str,
                            redis_client) -> Dict[str, Any]:
    """Handle macOS native file dialog (NSOpenPanel / Chrome sheet).

    Uses Cmd+Shift+G to open Go to Folder, pastes path, confirms.
    """
    try:
        time.sleep(0.5)

        # Cmd+Shift+G opens "Go to Folder" in macOS file dialogs
        inp.press_key('cmd+shift+g')
        time.sleep(0.5)

        # Paste the directory path
        dir_path = os.path.dirname(file_path)
        inp.clipboard_paste(dir_path)
        time.sleep(0.3)

        # Enter to navigate to directory
        inp.press_key('Return')
        time.sleep(1.0)

        # Type the filename to select it
        filename = os.path.basename(file_path)
        inp.clipboard_paste(filename)
        time.sleep(0.3)

        # Enter to confirm selection
        inp.press_key('Return')
        time.sleep(1.0)

        # Check if dialog closed by verifying file dialog state
        browser = atspi.find_firefox()
        dialog_closed = False
        for _ in range(20):
            time.sleep(0.3)
            if not atspi.is_file_dialog_open(browser):
                dialog_closed = True
                break

        if not dialog_closed:
            # Try Enter again (some dialogs need Open button click)
            inp.press_key('Return')
            time.sleep(1.0)
            browser = atspi.find_firefox()
            for _ in range(10):
                time.sleep(0.3)
                if not atspi.is_file_dialog_open(browser):
                    dialog_closed = True
                    break

        if not dialog_closed:
            return {"error": "macOS file dialog did not close after selection"}

        time.sleep(0.5)
        _update_checkpoint(platform, file_path, redis_client)

        return {
            "status": "file_attached",
            "platform": platform,
            "file_path": file_path,
            "filename": filename,
            "dialog_type": "macos_native",
            "info": "File chip may shift element positions - re-inspect before further clicks.",
        }

    except Exception as e:
        logger.error(f"macOS file dialog handling failed: {e}")
        return {"error": f"macOS file dialog handling failed: {e}"}

    finally:
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))


def _handle_gtk_file_dialog(platform: str, file_path: str,
                            redis_client) -> Dict[str, Any]:
    """Handle GTK file picker embedded in Firefox — focus dialog, type path, select file.

    Linux only. On macOS, use _handle_mac_file_dialog instead.
    """
    if IS_MACOS:
        return _handle_mac_file_dialog(platform, file_path, redis_client)

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

        # Wait briefly, then check if dialog is still open.
        # For full file paths, the first Return selects the file and closes
        # the dialog. A premature second Return would hit Firefox's chat
        # input instead, disrupting the upload (GitHub issue #24).
        time.sleep(0.8)
        firefox = atspi.find_firefox()
        dialog_still_open = atspi.is_file_dialog_open(firefox)

        if dialog_still_open:
            # Directory path or dialog needs confirmation — press Return again
            if not inp.press_key('Return'):
                return {"error": "Failed to press Return (confirm)"}

        # Wait for dialog to close
        dialog_closed = not dialog_still_open or False
        if not dialog_closed:
            for _ in range(25):
                time.sleep(0.2)
                if not atspi.is_file_dialog_open(firefox):
                    dialog_closed = True
                    break
        else:
            # Dialog already closed after first Return — wait for upload to process
            time.sleep(0.3)
            dialog_closed = True
            # Re-check to be sure
            if atspi.is_file_dialog_open(firefox):
                dialog_closed = False
                for _ in range(25):
                    time.sleep(0.2)
                    if not atspi.is_file_dialog_open(firefox):
                        dialog_closed = True
                        break

        if not dialog_closed:
            return {"error": "GTK file dialog did not close after selection"}

        time.sleep(0.5)

        # Wait for file chip to appear in AT-SPI tree (up to 2s).
        # Chip renders asynchronously after dialog closes — polling here
        # ensures _detect_existing_attachments() blocks a retry on return.
        firefox = atspi.find_firefox()
        for _ in range(10):
            doc_check = atspi.get_platform_document(firefox, platform) if firefox else None
            if doc_check and _detect_existing_attachments(doc_check):
                break
            time.sleep(0.2)

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


def _find_attach_button(doc, platform: str = None):
    """Search for the attach/upload button by name.

    Checks element cache first (populated by taey_inspect), which has
    no child-per-node limit and reliably finds buttons even on pages
    with extensive conversation history. Falls back to fresh DFS if
    cache miss.

    Returns the raw AT-SPI accessible object (with action interface) or None.
    """
    # Check element cache first — inspect already found this button
    if platform:
        from core.atspi_interact import _element_cache, is_defunct
        for e in _element_cache.get(platform, []):
            name = (e.get('name') or '').strip().lower()
            role = e.get('role', '')
            if 'button' in role and name in _ATTACH_NAMES:
                obj = e.get('atspi_obj')
                if obj and not is_defunct(e):
                    logger.info(f"Found attach button in cache: '{e.get('name')}' at ({e.get('x')}, {e.get('y')})")
                    return obj

    # Fall back to fresh tree search
    if IS_MACOS:
        # macOS: search element list from AX tree (doc is a dict, not traversable)
        all_elements = find_elements(doc)
        for e in all_elements:
            name = (e.get('name') or '').strip().lower()
            role = e.get('role', '')
            if 'button' in role and name in _ATTACH_NAMES:
                obj = e.get('atspi_obj') or e.get('ax_ref')
                if obj:
                    logger.info(f"Found attach button in AX tree: '{e.get('name')}' at ({e.get('x')}, {e.get('y')})")
                    return obj
        return None

    # Linux: DFS through raw AT-SPI tree (50-child limit may miss on large pages)
    def search(obj, depth=0, max_depth=25):
        if depth > max_depth:
            return None
        try:
            role = obj.get_role_name() or ''
            name = (obj.get_name() or '').strip().lower()
            if 'button' in role and name in _ATTACH_NAMES:
                comp = obj.get_component_iface()
                if comp:
                    ext = comp.get_extents(Atspi.CoordType.SCREEN)
                    # Accept buttons with valid position (width/height
                    # may be 0 on some AT-SPI implementations)
                    if ext and ext.x >= 0 and ext.y >= 0:
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


def _get_attach_button_coords(doc, platform: str = None) -> Dict | None:
    """Find attach button and return its center coordinates.

    Returns dict with x, y, atspi_obj if found, None otherwise.
    On macOS, coordinates come from the element cache (already center coords).
    """
    # Check element cache first — has coords directly (works on both platforms)
    if platform:
        from core.atspi_interact import _element_cache, is_defunct
        for e in _element_cache.get(platform, []):
            name = (e.get('name') or '').strip().lower()
            role = e.get('role', '')
            if 'button' in role and name in _ATTACH_NAMES:
                obj = e.get('atspi_obj') or e.get('ax_ref')
                if obj and not is_defunct(e):
                    return {
                        'x': e.get('x', 0),
                        'y': e.get('y', 0),
                        'atspi_obj': obj,
                    }

    btn = _find_attach_button(doc, platform=platform)
    if not btn:
        return None

    if IS_MACOS:
        # On macOS, button found via AX tree scan — coords were in element dict.
        # _find_attach_button returns the raw AXUIElement ref.
        # Search through the tree elements for matching ref to get coords.
        all_elements = find_elements(doc)
        for e in all_elements:
            ref = e.get('atspi_obj') or e.get('ax_ref')
            if ref is btn:
                return {'x': e.get('x', 0), 'y': e.get('y', 0), 'atspi_obj': btn}
        return None

    # Linux: get extents from raw AT-SPI component interface
    try:
        comp = btn.get_component_iface()
        if comp:
            ext = comp.get_extents(Atspi.CoordType.SCREEN)
            if ext and ext.x >= 0 and ext.y >= 0:
                return {
                    'x': ext.x + (ext.width // 2 if ext.width else 0),
                    'y': ext.y + (ext.height // 2 if ext.height else 0),
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


def _click_editable_input(doc, platform: str):
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
        # macOS: search AX element list
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


def _keyboard_nav_attach(platform: str, file_path: str,
                         redis_client) -> Dict[str, Any]:
    """ChatGPT/Grok fast-path: xdotool click → Down+Enter → handle portal dialog.

    These platforms render dropdown menus via React portals that are invisible
    to AT-SPI. Skips all AT-SPI menu scanning (which wastes 5+ seconds and
    never finds anything). Goes straight to keyboard navigation.

    Validated as the ONLY working approach across 63 commits of git history.
    """
    # Ensure the platform tab is actually focused in Firefox before clicking.
    # Without this, xdotool clicks land on whichever tab is currently visible.
    if not inp.switch_to_platform(platform):
        logger.warning(f"Tab switch to {platform} may have failed")
    time.sleep(0.5)

    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None
    btn_coords = _get_attach_button_coords(doc, platform=platform) if doc else None

    # ChatGPT/Grok: button not found → navigate to fresh page and retry
    if not btn_coords and platform in _KEYBOARD_NAV_PLATFORMS and not IS_MACOS:
        logger.info(f"{platform} attach button not found — trying fresh page")
        if _navigate_fresh_chat(platform):
            firefox = atspi.find_firefox()
            doc = atspi.get_platform_document(firefox, platform) if firefox else None
            btn_coords = _get_attach_button_coords(doc, platform=platform) if doc else None

    if not btn_coords:
        return {"error": f"Attach button not found for {platform}"}

    # ChatGPT/Grok: disabled attach button → navigate to fresh page
    if platform in _KEYBOARD_NAV_PLATFORMS and not IS_MACOS:
        atspi_obj = btn_coords.get('atspi_obj')
        if _is_attach_button_disabled(atspi_obj):
            if _navigate_fresh_chat(platform):
                firefox = atspi.find_firefox()
                doc = atspi.get_platform_document(firefox, platform) if firefox else None
                btn_coords = _get_attach_button_coords(doc, platform=platform) if doc else None
                if not btn_coords:
                    return {"error": f"{platform} attach button not found after fresh page navigation"}
                new_obj = btn_coords.get('atspi_obj')
                if _is_attach_button_disabled(new_obj):
                    return {"error": f"{platform} attach button still disabled after fresh page navigation"}
            else:
                return {"error": f"Failed to navigate {platform} to fresh page"}

    # Dismiss any stale dropdown/popup
    inp.press_key('Escape')
    time.sleep(0.3)

    # Grok fresh homepage: Attach button exists but has 0 actions until
    # the input field is clicked/focused. Click the editable input first
    # to activate the button, then re-fetch coordinates.
    if not IS_MACOS:
        atspi_obj = btn_coords.get('atspi_obj')
        if atspi_obj:
            try:
                action_iface = atspi_obj.get_action_iface()
                if not action_iface or action_iface.get_n_actions() == 0:
                    logger.info(f"Attach button has 0 actions on {platform} — clicking input to activate")
                    _click_editable_input(doc, platform)
                    time.sleep(1.0)
                    doc = atspi.get_platform_document(firefox, platform) if firefox else doc
                    btn_coords = _get_attach_button_coords(doc, platform=platform) if doc else btn_coords
            except Exception as e:
                logger.debug(f"Attach button action check failed: {e}")

    # Try accessibility action first — AT-SPI do_action on Linux, AXPress on macOS
    element_for_click = find_element_at(platform, btn_coords['x'], btn_coords['y'])
    if element_for_click:
        logger.info(f"Keyboard nav attach for {platform}: accessibility action on button at ({btn_coords['x']}, {btn_coords['y']})")
        if atspi_click(element_for_click):
            time.sleep(1.5)

            # Check if file dialog opened directly
            dialog_type = _any_file_dialog_open(firefox)
            if dialog_type:
                return _handle_file_dialog(platform, file_path, redis_client)

            # Accessibility action may have opened dropdown — try Down+Enter
            inp.press_key('Down')
            time.sleep(0.5)
            inp.press_key('Return')
            time.sleep(2.5)

            for _ in range(10):
                dialog_type = _any_file_dialog_open(firefox)
                if dialog_type:
                    return _handle_file_dialog(platform, file_path, redis_client)
                time.sleep(0.3)

            logger.info("Accessibility action didn't produce file dialog, falling back to coordinate click")

    # Fallback: xdotool click (gives X11 keyboard focus for Down+Enter)
    logger.info(f"Keyboard nav attach for {platform}: xdotool click at ({btn_coords['x']}, {btn_coords['y']})")
    inp.click_at(btn_coords['x'], btn_coords['y'])
    time.sleep(1.5)

    # Check if a file dialog already opened directly (some states skip dropdown)
    dialog_type = _any_file_dialog_open(firefox)
    if dialog_type:
        return _handle_file_dialog(platform, file_path, redis_client)

    # Keyboard nav: Down selects first dropdown item, Enter activates it
    inp.press_key('Down')
    time.sleep(0.5)
    inp.press_key('Return')
    time.sleep(2.5)

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
    btn_coords = _get_attach_button_coords(doc, platform=platform) if doc else None

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

    # Fallback: accessibility action directly (bypasses coordinate click)
    if not dropdown_items and not _any_file_dialog_open(firefox):
        logger.info("Trying accessibility action fallback")
        btn_coords_fb = _get_attach_button_coords(
            atspi.get_platform_document(atspi.find_firefox(), platform),
            platform=platform)
        if btn_coords_fb:
            inp.press_key('Escape')
            time.sleep(0.3)
            # Use the interact module's click (works on both platforms)
            el = find_element_at(platform, btn_coords_fb['x'], btn_coords_fb['y'])
            if el and atspi_click(el):
                logger.info("Accessibility action on attach button")
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

    # =========================================================================
    # Gemini follow-up recovery: disabled dropdown → navigate to fresh page
    # =========================================================================
    if platform == 'gemini' and _is_gemini_dropdown_disabled(dropdown_items):
        inp.press_key('Escape')
        time.sleep(0.3)
        if _gemini_navigate_fresh():
            # Wait for fresh page, then retry attach from scratch (one attempt)
            time.sleep(2.0)
            firefox = atspi.find_firefox()
            doc = atspi.get_platform_document(firefox, platform) if firefox else None
            btn_coords = _get_attach_button_coords(doc, platform=platform) if doc else None
            if btn_coords:
                click_result = handle_click(platform, btn_coords['x'], btn_coords['y'])
                if not click_result.get("error"):
                    time.sleep(1.0)
                    dialog_type = _any_file_dialog_open(firefox)
                    if dialog_type:
                        return _handle_file_dialog(platform, file_path, redis_client)
                    # Scan for dropdown items on fresh page
                    for attempt in range(3):
                        firefox = atspi.find_firefox()
                        doc = atspi.get_platform_document(firefox, platform) if firefox else None
                        dropdown_items = find_menu_items(firefox, doc)
                        if dropdown_items and not _is_gemini_dropdown_disabled(dropdown_items):
                            break
                        dropdown_items = []
                        time.sleep(0.5)

    # Gemini no-items recovery: empty dropdown on fresh page → navigate fresh
    if platform == 'gemini' and not dropdown_items and not _any_file_dialog_open(firefox):
        logger.info("Gemini dropdown empty — trying fresh page navigation")
        inp.press_key('Escape')
        time.sleep(0.3)
        if _gemini_navigate_fresh():
            time.sleep(2.0)
            firefox = atspi.find_firefox()
            doc = atspi.get_platform_document(firefox, platform) if firefox else None
            btn_coords = _get_attach_button_coords(doc, platform=platform) if doc else None
            if btn_coords:
                click_result = handle_click(platform, btn_coords['x'], btn_coords['y'])
                if not click_result.get("error"):
                    time.sleep(1.0)
                    dialog_type = _any_file_dialog_open(firefox)
                    if dialog_type:
                        return _handle_file_dialog(platform, file_path, redis_client)
                    for attempt in range(3):
                        firefox = atspi.find_firefox()
                        doc = atspi.get_platform_document(firefox, platform) if firefox else None
                        dropdown_items = find_menu_items(firefox, doc)
                        if dropdown_items and not _is_gemini_dropdown_disabled(dropdown_items):
                            break
                        dropdown_items = []
                        time.sleep(0.5)

    # Fallback: Keyboard navigation (Down+Enter) for AT-SPI-invisible dropdowns
    if not dropdown_items and not _any_file_dialog_open(firefox):
        logger.info("Trying keyboard nav fallback: Down+Enter for invisible dropdown")
        firefox = atspi.find_firefox()
        doc = atspi.get_platform_document(firefox, platform) if firefox else None
        btn_coords = _get_attach_button_coords(doc, platform=platform) if doc else None
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
