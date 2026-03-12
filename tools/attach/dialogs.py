from __future__ import annotations
"""File dialog handlers: GTK embedded, Nautilus portal, macOS native."""

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
    Atspi = None

from core import atspi, input as inp
from storage.redis_pool import node_key
from tools.attach.checkpoint import update_checkpoint
from tools.attach.chips import detect_existing_attachments

logger = logging.getLogger(__name__)

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

def find_portal_dialog_wids() -> List[str]:
    """Find Nautilus file dialog windows via xdotool.

    Returns list of window IDs (newest last).
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


def close_stale_file_dialogs():
    """Close orphaned Nautilus, GTK, and zombie Firefox dialog windows.

    Must be called BEFORE starting a new attach to prevent stale windows
    from intercepting keyboard input.

    Zombie Firefox windows: When a file dialog opens but handling fails,
    Firefox sometimes leaves a ghost window named just 'Firefox' (no page
    title). These block subsequent dialog opens. Detected by searching for
    windows named exactly 'Firefox' (real tab windows have titles like
    'ChatGPT - Mozilla Firefox').
    """
    if IS_MACOS:
        return

    closed = 0

    # Close Nautilus portal dialogs
    for wid in find_portal_dialog_wids():
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

    # Close xdg-desktop-portal-gtk dialogs (Xvfb / headless environments)
    try:
        result = subprocess.run(
            ['xdotool', 'search', '--name', 'xdg-desktop-portal-gtk'],
            capture_output=True, text=True, timeout=2, env=_xenv(),
        )
        if result.stdout.strip():
            for wid in result.stdout.strip().split('\n'):
                subprocess.run(
                    ['xdotool', 'windowclose', wid],
                    capture_output=True, timeout=3, env=_xenv(),
                )
                logger.info(f"Closed xdg-desktop-portal-gtk dialog {wid}")
                closed += 1
    except Exception as e:
        logger.debug(f"xdg-desktop-portal-gtk search failed: {e}")

    # Close zombie Firefox dialog windows (named exactly 'Firefox' with
    # no page title). Real browser windows have titles like
    # 'ChatGPT - Mozilla Firefox'. These zombies are leftover from failed
    # file dialog handling — they prevent new dialogs from opening.
    # NOTE: Firefox creates a helper/IPC window named exactly 'Firefox'
    # that is part of the running process — skip windows owned by Firefox PIDs.
    try:
        result = subprocess.run(
            ['xdotool', 'search', '--name', '^Firefox$'],
            capture_output=True, text=True, timeout=2, env=_xenv(),
        )
        if result.stdout.strip():
            # Get Firefox PIDs to skip their helper windows
            firefox_pids = set()
            main_result = subprocess.run(
                ['xdotool', 'search', '--name', 'Mozilla Firefox'],
                capture_output=True, text=True, timeout=2, env=_xenv(),
            )
            main_wids = set()
            if main_result.stdout.strip():
                for mwid in main_result.stdout.strip().split('\n'):
                    main_wids.add(mwid)
                    try:
                        pid_r = subprocess.run(
                            ['xdotool', 'getwindowpid', mwid],
                            capture_output=True, text=True, timeout=2, env=_xenv(),
                        )
                        if pid_r.stdout.strip():
                            firefox_pids.add(pid_r.stdout.strip())
                    except Exception:
                        pass

            for wid in result.stdout.strip().split('\n'):
                if wid and wid not in main_wids:
                    # Check if this window belongs to a running Firefox
                    try:
                        pid_r = subprocess.run(
                            ['xdotool', 'getwindowpid', wid],
                            capture_output=True, text=True, timeout=2, env=_xenv(),
                        )
                        if pid_r.stdout.strip() in firefox_pids:
                            continue  # Skip — Firefox helper window, not zombie
                    except Exception:
                        pass
                    subprocess.run(
                        ['xdotool', 'windowclose', wid],
                        capture_output=True, timeout=3, env=_xenv(),
                    )
                    logger.info(f"Closed zombie Firefox dialog window {wid}")
                    closed += 1
    except Exception as e:
        logger.debug(f"Zombie Firefox search failed: {e}")

    if closed:
        logger.info(f"Closed {closed} stale file dialog window(s)")
        time.sleep(1.0)  # Longer delay after cleanup — Firefox needs time to recover


def any_file_dialog_open(firefox) -> str:
    """Check for ANY type of file dialog (GTK embedded or Nautilus portal).

    Returns:
        'gtk' if Firefox embedded GTK file chooser found,
        'portal' if Nautilus portal window found,
        '' if no dialog found.
    """
    if atspi.is_file_dialog_open(firefox):
        return 'gtk'
    if find_portal_dialog_wids():
        return 'portal'
    return ''


# =========================================================================
# Dialog type router
# =========================================================================

def handle_file_dialog(platform: str, file_path: str,
                       redis_client) -> Dict[str, Any]:
    """Handle file dialog — detects type and routes to platform-specific handler."""
    if IS_MACOS:
        return _handle_mac_file_dialog(platform, file_path, redis_client)

    firefox = atspi.find_firefox()
    dialog_type = any_file_dialog_open(firefox)

    if dialog_type == 'portal':
        return _handle_portal_dialog(platform, file_path, redis_client)

    # GTK embedded file dialog (Gemini, Grok, sometimes Claude)
    return _handle_gtk_file_dialog(platform, file_path, redis_client)


# =========================================================================
# Portal (Nautilus) dialog handler
# =========================================================================

def _handle_portal_dialog(platform: str, file_path: str,
                          redis_client) -> Dict[str, Any]:
    """Handle Nautilus portal file dialog (ChatGPT, Perplexity).

    Nautilus portal is a separate window (not in Firefox AT-SPI tree).
    Focus it, open location bar with Ctrl+L, paste path, Enter.
    """
    if IS_MACOS:
        return {"error": "Portal dialog handling not supported on macOS"}
    try:
        wids = find_portal_dialog_wids()
        if not wids:
            return {"error": "Portal dialog detected but window not found"}

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
            remaining = find_portal_dialog_wids()
            if wid not in remaining:
                dialog_closed = True
                break

        if not dialog_closed:
            logger.warning("Nautilus dialog did not close — may need second Enter")
            inp.press_key('Return')
            time.sleep(1.0)
            remaining = find_portal_dialog_wids()
            dialog_closed = wid not in remaining

        if not dialog_closed:
            return {"error": "Nautilus portal dialog did not close after file selection"}

        # Re-focus Firefox after Nautilus dialog closes
        inp.focus_firefox()
        time.sleep(0.5)

        # Verify file chip appeared in AT-SPI tree (up to 4s)
        chip_found = False
        firefox_check = atspi.find_firefox()
        for _ in range(20):
            doc_check = atspi.get_platform_document(firefox_check, platform) if firefox_check else None
            if doc_check and detect_existing_attachments(doc_check):
                chip_found = True
                break
            time.sleep(0.2)

        update_checkpoint(platform, file_path, redis_client)

        result = {
            "status": "file_attached",
            "platform": platform,
            "file_path": file_path,
            "filename": os.path.basename(file_path),
            "dialog_type": "nautilus_portal",
            "info": "File chip may shift element positions - re-inspect before further clicks.",
        }
        if not chip_found:
            result["warning"] = "Dialog closed but NO file chip detected in AT-SPI tree. File may not have attached — re-inspect to verify."
        return result

    except Exception as e:
        logger.error(f"Portal dialog handling failed: {e}")
        return {"error": f"Portal dialog handling failed: {e}"}

    finally:
        try:
            close_stale_file_dialogs()
        except Exception:
            pass
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))


# =========================================================================
# GTK embedded dialog handler
# =========================================================================

def _handle_gtk_file_dialog(platform: str, file_path: str,
                            redis_client) -> Dict[str, Any]:
    """Handle GTK file picker embedded in Firefox — focus dialog, type path, select file."""
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

        # Ctrl+L opens the location bar which accepts a full absolute path
        inp.press_key('ctrl+l')
        time.sleep(0.5)
        inp.clipboard_paste(file_path)
        time.sleep(0.3)

        # Enter to navigate to file
        if not inp.press_key('Return'):
            return {"error": "Failed to press Return (navigate)"}

        # Wait briefly, then check if dialog is still open.
        # For full file paths, the first Return selects the file and closes
        # the dialog. A premature second Return would hit Firefox's chat
        # input instead, disrupting the upload.
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

        # Wait for file chip to appear in AT-SPI tree (up to 4s)
        chip_found = False
        firefox = atspi.find_firefox()
        for _ in range(20):
            doc_check = atspi.get_platform_document(firefox, platform) if firefox else None
            if doc_check and detect_existing_attachments(doc_check):
                chip_found = True
                break
            time.sleep(0.2)

        update_checkpoint(platform, file_path, redis_client)

        result = {
            "status": "file_attached",
            "platform": platform,
            "file_path": file_path,
            "filename": os.path.basename(file_path),
            "dialog_type": "gtk_embedded",
            "info": "File chip may shift element positions - re-inspect before further clicks.",
        }
        if not chip_found:
            result["warning"] = "Dialog closed but NO file chip detected in AT-SPI tree. File may not have attached — re-inspect to verify."
        return result

    except Exception as e:
        logger.error(f"GTK file dialog handling failed: {e}")
        return {"error": f"GTK file dialog handling failed: {e}"}

    finally:
        try:
            close_stale_file_dialogs()
        except Exception:
            pass
        if redis_client:
            redis_client.delete(node_key(f"attach:pending:{platform}"))


# =========================================================================
# macOS native dialog handler
# =========================================================================

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

        # Check if dialog closed
        browser = atspi.find_firefox()
        dialog_closed = False
        for _ in range(20):
            time.sleep(0.3)
            if not atspi.is_file_dialog_open(browser):
                dialog_closed = True
                break

        if not dialog_closed:
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
        update_checkpoint(platform, file_path, redis_client)

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
