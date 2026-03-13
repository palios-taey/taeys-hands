#!/usr/bin/env python3
"""hmm_bot.py — Autonomous HMM enrichment bot via AT-SPI.

Pure mechanical automation: no LLM in the loop. Uses AT-SPI to attach
packages, send prompts, detect response completion, extract, and process.

Usage:
    # Continuous mode (default)
    python3 agents/hmm_bot.py

    # Single cycle
    python3 agents/hmm_bot.py --cycles 1

    # Specific platforms only
    python3 agents/hmm_bot.py --platforms chatgpt gemini

Environment:
    DISPLAY          — X11 display (default: :1)
    NOTIFY_TARGET    — taey-notify target for escalations (default: weaver)
    BUILDER_PATH     — path to hmm_package_builder.py
    PYTHONPATH       — must include embedding-server root
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time

# Must set DISPLAY before importing AT-SPI modules
os.environ.setdefault('DISPLAY', ':1')

# Add taeys-hands and embedding-server to path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
if os.path.expanduser('~/embedding-server') not in sys.path:
    sys.path.insert(0, os.path.expanduser('~/embedding-server'))

from core import atspi, clipboard
from core import input as inp
from core.tree import find_elements, find_copy_buttons, filter_useful_elements, detect_chrome_y
from tools.attach import handle_attach, _keyboard_nav_attach as keyboard_nav_attach, _close_stale_file_dialogs as close_stale_file_dialogs

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('hmm_bot')

NOTIFY_TARGET = os.environ.get('NOTIFY_TARGET', 'weaver')
BUILDER_PATH = os.environ.get(
    'BUILDER_PATH',
    os.path.expanduser('~/embedding-server/isma/scripts/hmm_package_builder.py'),
)

# Stop button patterns (from monitor/central.py)
STOP_PATTERNS = {
    'chatgpt': ['stop', 'stop generating'],
    'gemini': ['stop', 'cancel'],
    'grok': ['stop', 'stop generating'],
}

# Platform fresh-session URLs
FRESH_URLS = {
    'chatgpt': 'https://chatgpt.com/?temporary-chat=true',
    'gemini': 'https://gemini.google.com/app',
    'grok': 'https://grok.com/',
}

# Cached AT-SPI references — avoids repeated deep traversals that cause D-Bus contention
_cached_firefox = {}  # platform -> AT-SPI firefox app ref
_cached_doc = {}      # platform -> AT-SPI document ref


def get_firefox(platform: str):
    """Get Firefox AT-SPI ref with caching. Avoids D-Bus contention in parallel mode."""
    cached = _cached_firefox.get(platform)
    if cached:
        try:
            # Quick check: can we still access it?
            cached.get_name()
            return cached
        except Exception:
            _cached_firefox.pop(platform, None)
    # Full discovery (expensive — only on first call or after stale)
    ff = atspi.find_firefox_for_platform(platform)
    if ff:
        _cached_firefox[platform] = ff
    return ff


def get_doc(platform: str, force_refresh: bool = False):
    """Get platform document with caching. force_refresh after navigation."""
    if not force_refresh:
        cached = _cached_doc.get(platform)
        if cached:
            try:
                cached.get_name()
                return cached
            except Exception:
                _cached_doc.pop(platform, None)
    ff = get_firefox(platform)
    doc = atspi.get_platform_document(ff, platform) if ff else None
    if doc:
        _cached_doc[platform] = doc
    return doc


def invalidate_cache(platform: str):
    """Clear cached refs after Firefox restart or navigation."""
    _cached_firefox.pop(platform, None)
    _cached_doc.pop(platform, None)


def restart_firefox(platforms: list) -> bool:
    """Kill and restart Firefox on current DISPLAY only. Parallel-safe."""
    logger.warning("Restarting Firefox...")
    env = os.environ.copy()
    display = env.get('DISPLAY', ':1')
    xenv = {**env, 'DISPLAY': display}

    # Find Firefox window PIDs on THIS display only (parallel-safe)
    pids_to_kill = set()
    try:
        r = subprocess.run(
            ['xdotool', 'search', '--name', 'Mozilla Firefox'],
            capture_output=True, text=True, timeout=5, env=xenv,
        )
        for wid in (r.stdout.strip().split('\n') if r.stdout.strip() else []):
            try:
                p = subprocess.run(
                    ['xdotool', 'getwindowpid', wid],
                    capture_output=True, text=True, timeout=3, env=xenv,
                )
                if p.returncode == 0 and p.stdout.strip():
                    pids_to_kill.add(p.stdout.strip())
            except Exception:
                pass
    except Exception:
        pass

    if pids_to_kill:
        for pid in pids_to_kill:
            subprocess.run(['kill', '-9', pid], capture_output=True)
        logger.info(f"Killed Firefox PIDs on {display}: {pids_to_kill}")
    else:
        # Fallback: no window found, kill all (single-instance mode)
        subprocess.run(['pkill', '-9', '-f', 'firefox'], capture_output=True)

    subprocess.run(['pkill', '-9', '-f', 'crashreporter'], capture_output=True)
    for _ in range(10):
        time.sleep(1)
        # Check if our display is clear
        try:
            r = subprocess.run(
                ['xdotool', 'search', '--name', 'Mozilla Firefox'],
                capture_output=True, text=True, timeout=3, env=xenv,
            )
            if r.returncode != 0 or not r.stdout.strip():
                break
        except Exception:
            break
    time.sleep(1)

    # Close zombie windows on this display
    try:
        for pattern in ['Firefox', 'File Upload', 'Open', 'Nautilus',
                        'xdg-desktop-portal-gtk']:
            r = subprocess.run(
                ['xdotool', 'search', '--name', pattern],
                capture_output=True, text=True, timeout=3, env=xenv,
            )
            for wid in (r.stdout.strip().split('\n') if r.stdout.strip() else []):
                subprocess.run(['xdotool', 'windowclose', wid],
                               capture_output=True, timeout=2, env=xenv)
        time.sleep(0.5)
    except Exception as e:
        logger.debug(f"Zombie window cleanup: {e}")

    # Determine profile to use
    # Parallel mode: /tmp/ff-profile-<platform> (created by setup_parallel_hmm.sh)
    # Single mode: default profile
    profile_arg = []
    platform_name = platforms[0] if len(platforms) == 1 else None
    if platform_name:
        parallel_profile = f'/tmp/ff-profile-{platform_name}'
        if os.path.isdir(parallel_profile):
            # Clean locks from profile copy
            for lock in [f'{parallel_profile}/lock', f'{parallel_profile}/.parentlock']:
                try:
                    os.remove(lock)
                except FileNotFoundError:
                    pass
            # Remove session restore to prevent old tab restoration
            import glob as _glob
            import shutil
            for pattern in ['sessionstore*', 'sessionstore-backups']:
                for path in _glob.glob(f'{parallel_profile}/{pattern}'):
                    try:
                        if os.path.isdir(path):
                            shutil.rmtree(path)
                        else:
                            os.remove(path)
                    except Exception:
                        pass
            profile_arg = ['--profile', parallel_profile, '--no-remote']
            logger.info(f"Using parallel profile: {parallel_profile}")

    if not profile_arg:
        # Single-instance mode: clean default profile locks
        import glob as _glob
        import shutil
        for profile_dir in ['~/.config/mozilla/firefox', '~/.mozilla/firefox']:
            for lock in _glob.glob(os.path.expanduser(f'{profile_dir}/*/.parentlock')):
                try:
                    os.remove(lock)
                except Exception:
                    pass
            for pattern in ['*/sessionstore*', '*/sessionstore-backups']:
                for path in _glob.glob(os.path.expanduser(f'{profile_dir}/{pattern}')):
                    try:
                        if os.path.isdir(path):
                            shutil.rmtree(path)
                        else:
                            os.remove(path)
                    except Exception:
                        pass

    urls = ['about:blank']

    firefox_env = {
        **env,
        'DISPLAY': display,
        'MOZ_DISABLE_CONTENT_SANDBOX': '1',
        'LIBGL_ALWAYS_SOFTWARE': '1',
        'MOZ_ACCELERATED': '0',
    }
    uid = os.getuid()
    dbus_path = f'/run/user/{uid}/bus'
    if os.path.exists(dbus_path):
        firefox_env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path={dbus_path}'

    subprocess.Popen(
        ['firefox'] + profile_arg + urls,
        env=firefox_env,
        stdout=open(f'/tmp/firefox_{platform_name or "main"}.log', 'w'),
        stderr=subprocess.STDOUT,
    )

    for i in range(15):
        time.sleep(2)
        if check_firefox_alive():
            logger.info(f"Firefox restarted successfully ({(i+1)*2}s)")
            _cached_firefox.clear()
            _cached_doc.clear()
            return True

    logger.error("Firefox failed to start after 30s")
    return False


def notify(message: str):
    """Send notification via taey-notify."""
    try:
        subprocess.run(
            ['taey-notify', NOTIFY_TARGET, message, '--type', 'notification'],
            capture_output=True, timeout=5,
        )
    except Exception:
        logger.warning(f"Notify failed: {message}")


def escalate(message: str):
    """Send escalation via taey-notify."""
    try:
        subprocess.run(
            ['taey-notify', NOTIFY_TARGET, message, '--type', 'escalation'],
            capture_output=True, timeout=5,
        )
    except Exception:
        logger.error(f"Escalate failed: {message}")


def builder_cmd(*args) -> subprocess.CompletedProcess:
    """Run hmm_package_builder.py with given args."""
    cmd = ['python3', BUILDER_PATH] + list(args)
    env = {**os.environ}
    # Ensure embedding-server is in PYTHONPATH for the subprocess
    emb_root = os.path.expanduser('~/embedding-server')
    existing = env.get('PYTHONPATH', '')
    if emb_root not in existing:
        env['PYTHONPATH'] = f"{emb_root}:{existing}" if existing else emb_root
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)


def get_prompt() -> str:
    """Get HMM analysis prompt from builder."""
    result = builder_cmd('prompt')
    if result.returncode != 0:
        logger.error(f"Failed to get prompt: {result.stderr}")
        return ''
    return result.stdout.strip()


def get_next_package(platform: str) -> str:
    """Get next package for platform. Returns file path or empty string."""
    result = builder_cmd('next', '--platform', platform)
    if result.returncode != 0 or 'No items available' in result.stdout:
        return ''
    # Parse file path from output (last non-empty line)
    for line in reversed(result.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith('/') and line.endswith('.md'):
            return line
    # Try to find it in /tmp/hmm_packages/
    for line in result.stdout.strip().splitlines():
        if '/tmp/hmm_packages/' in line:
            # Extract path
            idx = line.find('/tmp/hmm_packages/')
            if idx >= 0:
                path = line[idx:].split()[0]
                if os.path.isfile(path):
                    return path
    logger.warning(f"Could not parse package path from builder output:\n{result.stdout[:200]}")
    return ''


def complete_package(platform: str, response_file: str) -> bool:
    """Mark package complete with response. Returns True on success."""
    result = builder_cmd('complete', '--platform', platform,
                         '--response-file', response_file)
    if result.returncode != 0:
        logger.error(f"Complete failed for {platform}: {result.stderr[:200]}")
        return False
    logger.info(f"Package completed for {platform}")
    return True


def fail_package(platform: str, reason: str = 'bot_failure'):
    """Mark package as failed (requeues it)."""
    builder_cmd('fail', '--platform', platform, reason)
    logger.info(f"Package failed/requeued for {platform}: {reason}")


def get_stats() -> str:
    """Get builder stats."""
    result = builder_cmd('stats')
    return result.stdout.strip() if result.returncode == 0 else 'stats unavailable'


def navigate_fresh_session(platform: str) -> bool:
    """Navigate to a fresh session URL for the platform.

    Does NOT depend on tab order — just focuses Firefox and navigates
    the current tab to the platform URL via Ctrl+L.
    """
    url = FRESH_URLS.get(platform)
    if not url:
        return False

    # Close any stale file dialogs that would capture keyboard input
    close_stale_file_dialogs()

    if not inp.focus_firefox():
        logger.warning("Could not focus Firefox")
        return False

    time.sleep(0.3)
    inp.press_key('Escape')
    time.sleep(0.2)
    inp.press_key('ctrl+l')
    time.sleep(0.3)
    # Use xdotool type for URLs — clipboard paste (xsel + Ctrl+V) fails on
    # some Xvfb setups. URLs are short so xdotool type is reliable here.
    inp.press_key('ctrl+a')
    time.sleep(0.1)
    inp.type_text(url, delay_ms=10)
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(8)  # Wait for page load (needs more time on fresh restart)

    # Invalidate cache — page changed, old refs are stale
    invalidate_cache(platform)

    # Verification is best-effort — D-Bus contention in parallel mode can
    # make AT-SPI verification fail even when page loaded fine. Trust the
    # navigation and let attach_file discover the document.
    doc = get_doc(platform, force_refresh=True)
    if not doc:
        logger.info(f"[{platform}] AT-SPI doc not found yet (D-Bus lag) — continuing anyway")

    return True


def check_firefox_alive(platform: str = None, retries: int = 3) -> bool:
    """Check if Firefox is running via xdotool (DISPLAY-scoped).

    Uses xdotool instead of AT-SPI to avoid D-Bus contention when
    multiple bots query simultaneously on shared D-Bus session.
    """
    for attempt in range(retries):
        try:
            r = subprocess.run(
                ['xdotool', 'search', '--name', 'Mozilla Firefox'],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                return True
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(2)
    return False


def scan_for_stop_button(platform: str) -> bool:
    """Check if a stop/cancel button is visible (AI is generating)."""
    firefox = get_firefox(platform)
    doc = get_doc(platform)
    if not doc:
        return False

    elements = find_elements(doc)
    patterns = STOP_PATTERNS.get(platform, ['stop'])

    for e in elements:
        name = (e.get('name') or '').strip()
        if not name or len(name) > 50:
            continue
        if 'button' not in e.get('role', ''):
            continue
        name_lower = name.lower()
        if any(p in name_lower for p in patterns):
            return True
    return False


def count_copy_buttons(platform: str) -> int:
    """Count visible copy buttons on the platform."""
    firefox = get_firefox(platform)
    doc = get_doc(platform)
    if not doc:
        return 0

    elements = find_elements(doc)
    return len(find_copy_buttons(elements))


def find_input_field_atspi(platform: str):
    """Find the chat input field via AT-SPI. Returns element dict or None.

    Returns dict with 'x', 'y', 'atspi_obj' keys (same as find_elements output).
    With taeys-hands v7, AT-SPI ALWAYS exposes the input field.
    If this returns None, it's a real bug — callers must fail loud.
    """
    firefox = get_firefox(platform)
    doc = get_doc(platform)
    if not doc:
        return None

    elements = find_elements(doc)
    chrome_y = detect_chrome_y(doc)

    # Priority 1: role=entry with editable
    for e in elements:
        if (e.get('role') == 'entry'
                and 'editable' in e.get('states', [])
                and e.get('y', 0) > chrome_y
                and e.get('x', 0) > 0):
            return e

    # Priority 2: any element with editable state in page area
    for e in elements:
        if ('editable' in e.get('states', [])
                and e.get('y', 0) > chrome_y
                and e.get('x', 0) > 0):
            logger.info(f"[{platform}] Found editable: role={e.get('role')} at ({e['x']}, {e['y']})")
            return e

    # Priority 3: Grok uses role=section for input — sometimes lacks editable state.
    # Also match ChatGPT ProseMirror (role=section). Look for section/paragraph
    # in the lower portion of the page (input area) that is focusable.
    for e in elements:
        if (e.get('role') in ('section', 'paragraph')
                and 'focusable' in e.get('states', [])
                and e.get('y', 0) > chrome_y
                and e.get('x', 0) > 0):
            logger.info(f"[{platform}] Found focusable {e.get('role')} at ({e['x']}, {e['y']})")
            return e

    return None


def wait_for_response(platform: str, timeout: int = 600) -> bool:
    """Wait for AI response to complete.

    Strategy:
    1. Poll for stop button to appear (AI started generating)
    2. Then poll for stop button to disappear (AI finished)
    3. Fallback: if no stop button seen within 30s but copy count increased, done

    Returns True if response detected, False on timeout.
    """
    start = time.time()
    initial_copy_count = count_copy_buttons(platform)
    stop_seen = False
    phase = 'waiting_for_start'

    while time.time() - start < timeout:
        if not check_firefox_alive(platform):
            logger.error(f"[{platform}] Firefox died during response wait")
            return False

        has_stop = scan_for_stop_button(platform)

        if phase == 'waiting_for_start':
            if has_stop:
                logger.info(f"[{platform}] Stop button appeared — AI generating")
                stop_seen = True
                phase = 'generating'
            elif time.time() - start > 30:
                # Fallback: check if copy count increased (fast response)
                current_copy = count_copy_buttons(platform)
                if current_copy > initial_copy_count:
                    logger.info(f"[{platform}] Copy count increased {initial_copy_count}->{current_copy} (fast response)")
                    return True
                elif time.time() - start > 60:
                    logger.warning(f"[{platform}] No stop button after 60s — possible send failure")
                    return False
            time.sleep(3)

        elif phase == 'generating':
            if not has_stop:
                # Stop button disappeared — wait a bit to confirm
                logger.info(f"[{platform}] Stop button gone — settling...")
                time.sleep(2)
                if not scan_for_stop_button(platform):
                    logger.info(f"[{platform}] Response complete ({time.time()-start:.0f}s)")
                    return True
                else:
                    logger.info(f"[{platform}] Stop button reappeared — still generating")
            time.sleep(3)

    logger.warning(f"[{platform}] Timeout after {timeout}s")
    return False


def extract_response(platform: str) -> str:
    """Extract latest response via copy button. Returns content or empty string."""
    inp.focus_firefox()
    time.sleep(0.3)

    # Scroll to bottom
    inp.press_key('End')
    time.sleep(0.5)

    firefox = get_firefox(platform)
    doc = get_doc(platform)
    if not doc:
        return ''

    elements = find_elements(doc)
    copy_buttons = find_copy_buttons(elements)

    # Retry: copy buttons may not be in AT-SPI yet after scroll (render lag)
    if not copy_buttons:
        for retry in range(3):
            time.sleep(2)
            inp.press_key('End')
            time.sleep(1)
            doc = get_doc(platform, force_refresh=True)
            if not doc:
                break
            elements = find_elements(doc)
            copy_buttons = find_copy_buttons(elements)
            if copy_buttons:
                logger.info(f"[{platform}] Copy buttons found on retry {retry+1}")
                break

    if not copy_buttons:
        logger.error(f"[{platform}] No copy buttons found after scroll to bottom")
        return ''

    # Prefer response-level "Copy" over "Copy code"
    response_copy = [b for b in copy_buttons
                     if (b.get('name') or '').strip().lower() == 'copy']
    target = (response_copy or copy_buttons)[-1]

    # Click copy button — use marker instead of clear to avoid X11 clipboard
    # ownership issues on Xvfb (clear claims ownership, blocking JS writes)
    _MARKER = '__HMM_CLIP_MARKER__'
    clipboard.write_marker(_MARKER)
    time.sleep(0.2)

    from core.interact import atspi_click
    if target.get('atspi_obj') and atspi_click(target):
        logger.info(f"[{platform}] Copy via AT-SPI at ({target['x']}, {target['y']})")
    else:
        inp.click_at(target['x'], target['y'])
        logger.info(f"[{platform}] Copy via xdotool at ({target['x']}, {target['y']})")

    # Poll clipboard until it changes from marker (up to 3s)
    content = None
    for _ in range(6):
        time.sleep(0.5)
        raw = clipboard.read()
        if raw and raw != _MARKER:
            content = raw
            break

    if not content:
        logger.error(f"[{platform}] Copy button clicked but clipboard unchanged after 3s")
        return ''

    # Check if we got the prompt instead of the response
    if content:
        start_text = content.strip()[:200].lower()
        prompt_markers = ['analyze the following', 'package analysis request',
                          'you are analyzing', 'respond only with minified json',
                          'critical: echo back', 'analyze all', 'for each item provide']
        if any(m in start_text for m in prompt_markers):
            if len(response_copy) >= 2:
                logger.warning(f"[{platform}] Got prompt text, trying previous copy button")
                prev = response_copy[-2]
                clipboard.clear()
                time.sleep(0.1)
                if prev.get('atspi_obj') and atspi_click(prev):
                    pass
                else:
                    inp.click_at(prev['x'], prev['y'])
                time.sleep(0.8)
                alt = clipboard.read()
                if alt and alt != content:
                    content = alt
            else:
                logger.warning(f"[{platform}] Only 1 copy button — got prompt, no response yet")
                content = ''

    return content or ''


def _find_dialog_wid() -> str:
    """Find GTK file dialog window ID. Returns wid or empty string."""
    xenv = {**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':1')}
    for title in ['File Upload', 'Open', 'Open File']:
        try:
            r = subprocess.run(
                ['xdotool', 'search', '--name', title],
                capture_output=True, text=True, timeout=2, env=xenv,
            )
            if r.stdout.strip():
                return r.stdout.strip().split('\n')[-1]
        except Exception:
            pass
    return ''


def _handle_dialog_direct(file_path: str) -> bool:
    """Handle GTK file dialog: focus → open path bar → enter path → confirm.

    Tries multiple approaches for entering the path since GTK file dialogs
    vary across environments:
    1. Ctrl+L to open location bar + clipboard paste
    2. Type '/' to trigger GTK path-bar + xdotool type
    """
    xenv = {**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':1')}
    wid = _find_dialog_wid()
    if not wid:
        logger.warning("No file dialog window found")
        return False

    def _dialog_gone() -> bool:
        return not _find_dialog_wid()

    # Focus the dialog window
    subprocess.run(
        ['xdotool', 'windowactivate', '--sync', wid],
        capture_output=True, timeout=3, env=xenv,
    )
    time.sleep(0.5)

    # Ctrl+L opens location bar, Ctrl+A clears, type path, Enter confirms
    logger.info(f"Dialog: Ctrl+L + type path: {file_path}")
    inp.press_key('ctrl+l')
    time.sleep(0.5)
    inp.press_key('ctrl+a')
    time.sleep(0.1)
    inp.type_text(file_path, delay_ms=10)
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(1.5)

    if _dialog_gone():
        logger.info("File dialog closed successfully")
        return True

    # GTK sometimes navigates to directory on first Enter — second Enter selects file
    inp.press_key('Return')
    time.sleep(1.0)
    if _dialog_gone():
        logger.info("File dialog closed after directory navigation + file select")
        return True

    logger.error(f"File dialog did NOT close after path entry. Dialog wid: {_find_dialog_wid()}")
    return False


def attach_file(platform: str, file_path: str) -> bool:
    """Attach a file: click button → open dialog → type path → confirm.

    Handles everything directly instead of using handle_attach(), because
    the standard clipboard paste doesn't reliably select files on Xvfb.
    """
    from tools.attach import _get_attach_button_coords as get_attach_button_coords, _any_file_dialog_open as any_file_dialog_open, _close_stale_file_dialogs as close_stale_file_dialogs
    from core.interact import atspi_click

    firefox = get_firefox(platform)
    doc = get_doc(platform)
    if not doc:
        logger.warning(f"[{platform}] No document found for attach")
        return False

    # Stale dialog from previous run = bug. Clean it up and fail.
    if _find_dialog_wid():
        logger.error(f"[{platform}] Stale file dialog found — cleaning up")
        close_stale_file_dialogs()
        return False

    # Find attach button — retry up to 5 times (AT-SPI tree lags after navigation)
    btn = None
    for attempt in range(5):
        doc = get_doc(platform, force_refresh=True)
        if doc:
            btn = get_attach_button_coords(doc, platform=platform)
        if btn:
            break
        logger.info(f"[{platform}] Attach button not found, retry {attempt+1}/5...")
        time.sleep(3)
    if not btn:
        logger.error(f"[{platform}] Attach button not found after 5 retries")
        return False

    # Dismiss any stale popups
    inp.press_key('Escape')
    time.sleep(0.3)

    # Click attach button — Grok/ChatGPT need xdotool (AT-SPI doesn't trigger React),
    # Gemini works with AT-SPI
    if platform in ('chatgpt', 'grok'):
        inp.click_at(btn['x'], btn['y'])
        logger.info(f"[{platform}] Clicked attach button via xdotool")
    elif btn.get('atspi_obj') and atspi_click(btn):
        logger.info(f"[{platform}] Clicked attach button via AT-SPI")
    else:
        inp.click_at(btn['x'], btn['y'])
        logger.info(f"[{platform}] Clicked attach button via xdotool")
    time.sleep(1.5)

    # ChatGPT/Grok: dropdown → Down+Enter for "Upload a file"
    if platform in ('chatgpt', 'grok'):
        if not _find_dialog_wid():
            inp.press_key('Down')
            time.sleep(0.5)
            inp.press_key_split('Return')
            time.sleep(2.5)

    # Gemini: menu items ARE visible in AT-SPI — click "Upload files" directly
    elif platform == 'gemini':
        time.sleep(2.0)  # Gemini dropdown needs time to render
        doc2 = get_doc(platform, force_refresh=True)
        if doc2:
            elems2 = find_elements(doc2)
            for e in elems2:
                name = (e.get('name') or '').strip().lower()
                if 'upload file' in name and 'menu item' in e.get('role', ''):
                    if e.get('atspi_obj') and atspi_click(e):
                        logger.info(f"[{platform}] Clicked '{e.get('name')}' via AT-SPI")
                    else:
                        inp.click_at(e['x'], e['y'])
                        logger.info(f"[{platform}] Clicked '{e.get('name')}' via xdotool")
                    time.sleep(2.0)
                    break
            else:
                logger.error(f"[{platform}] 'Upload files' menu item not found")
                inp.press_key('Escape')
                return False

    # Wait for file dialog to appear
    dialog_found = False
    for _ in range(15):
        if _find_dialog_wid():
            dialog_found = True
            break
        time.sleep(0.5)

    if not dialog_found:
        logger.warning(f"[{platform}] No file dialog appeared after button click")
        close_stale_file_dialogs()
        return False

    # Handle dialog with xdotool type (reliable on Xvfb)
    if _handle_dialog_direct(file_path):
        logger.info(f"[{platform}] File attached: {os.path.basename(file_path)}")
        # Re-focus Firefox after dialog closes
        inp.focus_firefox()
        time.sleep(0.5)
        return True

    close_stale_file_dialogs()
    return False


def send_prompt(platform: str, prompt: str) -> bool:
    """Focus input, paste prompt, press Enter. Fails loud if input not found."""
    inp.focus_firefox()
    time.sleep(0.3)

    # Dismiss any open dropdown menus (Grok attach leaves dropdown open)
    inp.press_key('Escape')
    time.sleep(0.3)

    # Find input via AT-SPI — retry up to 5 times (AT-SPI tree may lag
    # after file dialog close or page navigation)
    input_elem = None
    for attempt in range(5):
        input_elem = find_input_field_atspi(platform)
        if input_elem:
            break
        logger.info(f"[{platform}] Input not found, retry {attempt+1}/5...")
        time.sleep(2)

    if not input_elem:
        logger.error(f"[{platform}] Input field not found after 5 retries — aborting send")
        return False

    logger.info(f"[{platform}] Found input via AT-SPI at ({input_elem['x']}, {input_elem['y']})")

    # Click to position cursor, then grab_focus for proper AT-SPI focus
    # (grab_focus is essential on Xvfb — click_at alone doesn't give
    # focus that clipboard paste needs, especially on Gemini)
    inp.click_at(input_elem['x'], input_elem['y'])
    time.sleep(0.3)
    obj = input_elem.get('atspi_obj')
    if obj:
        try:
            comp = obj.get_component_iface()
            if comp:
                comp.grab_focus()
        except Exception:
            pass
    time.sleep(0.3)

    # Paste prompt via clipboard + Enter to send
    inp.clipboard_paste(prompt)
    time.sleep(0.5)
    inp.press_key('Return')
    time.sleep(1.0)

    logger.info(f"[{platform}] Prompt sent ({len(prompt)} chars)")
    return True


def process_platform(platform: str, prompt: str) -> dict:
    """Full cycle for one platform: package → attach → send → wait → extract → complete.

    Returns result dict with status and details.
    """
    result = {'platform': platform, 'success': False, 'error': None}

    # Step 0: Clean up stale state BEFORE anything else
    # Kill stale xsel processes (clipboard writes that hung on Xvfb)
    try:
        subprocess.run(['pkill', '-f', 'xsel --clipboard --input'],
                       capture_output=True, timeout=3)
    except Exception:
        pass
    # Close stale dialogs (leftover dialogs capture keyboard input)
    close_stale_file_dialogs()

    # Step 1: Get next package
    logger.info(f"[{platform}] Getting next package...")
    pkg_path = get_next_package(platform)
    if not pkg_path:
        result['error'] = 'no_items'
        logger.info(f"[{platform}] No items available — skipping")
        return result

    logger.info(f"[{platform}] Package: {os.path.basename(pkg_path)}")

    # Step 2: Navigate to fresh session
    logger.info(f"[{platform}] Navigating to fresh session...")
    if not navigate_fresh_session(platform):
        result['error'] = 'nav_failed'
        fail_package(platform, 'navigation_failed')
        return result

    # Step 4: Attach package file
    logger.info(f"[{platform}] Attaching package...")
    if not attach_file(platform, pkg_path):
        result['error'] = 'attach_failed'
        fail_package(platform, 'attach_failed')
        return result

    time.sleep(5)  # Wait for file upload to process before sending

    # Step 5: Send prompt
    logger.info(f"[{platform}] Sending prompt...")
    if not send_prompt(platform, prompt):
        result['error'] = 'send_failed'
        fail_package(platform, 'send_failed')
        return result

    # Step 6: Wait for response
    logger.info(f"[{platform}] Waiting for response...")
    if not wait_for_response(platform, timeout=1200):
        result['error'] = 'response_timeout'
        fail_package(platform, 'response_timeout')
        return result

    time.sleep(2)  # Let response fully render

    # Step 7: Extract response
    logger.info(f"[{platform}] Extracting response...")
    content = extract_response(platform)
    if not content:
        result['error'] = 'extract_failed'
        fail_package(platform, 'extract_failed')
        return result

    logger.info(f"[{platform}] Extracted {len(content)} chars")

    # Step 8: Save response to file
    response_file = f"/tmp/hmm_response_{platform}.json"
    try:
        with open(response_file, 'w') as f:
            f.write(content)
    except Exception as e:
        result['error'] = f'save_failed: {e}'
        fail_package(platform, 'save_failed')
        return result

    # Step 9: Process with builder
    logger.info(f"[{platform}] Processing response...")
    if not complete_package(platform, response_file):
        result['error'] = 'complete_failed'
        # Don't fail_package here — complete already handles requeue on error
        return result

    result['success'] = True
    result['content_length'] = len(content)
    logger.info(f"[{platform}] === CYCLE COMPLETE === ({len(content)} chars)")
    return result


def run_cycle(platforms: list, prompt: str) -> dict:
    """Run one full enrichment cycle across all platforms.

    Processes platforms sequentially (one at a time per CLAUDE.md rules).
    Returns summary dict.
    """
    results = {}

    for platform in platforms:
        if not check_firefox_alive(platform):
            logger.warning(f"[{platform}] Firefox died — auto-restarting...")
            if not restart_firefox(platforms):
                escalate(f"ESCALATION from hmm_bot: Firefox restart failed during {platform}")
                break
            time.sleep(15)  # Extra settle time after restart for pages to load

        try:
            results[platform] = process_platform(platform, prompt)
        except Exception as e:
            logger.error(f"[{platform}] Unhandled error: {e}")
            results[platform] = {'platform': platform, 'success': False,
                                 'error': f'exception: {e}'}
            fail_package(platform, f'exception: {e}')

    return results


def main():
    parser = argparse.ArgumentParser(description='HMM enrichment bot')
    parser.add_argument('--platforms', nargs='+', default=['chatgpt', 'gemini'],
                        help='Platforms to use (default: chatgpt gemini)')
    parser.add_argument('--cycles', type=int, default=0,
                        help='Number of cycles (0=infinite)')
    parser.add_argument('--pause', type=int, default=10,
                        help='Seconds between cycles (default: 10)')
    args = parser.parse_args()

    logger.info(f"HMM Bot starting — platforms: {args.platforms}, "
                f"cycles: {'infinite' if args.cycles == 0 else args.cycles}")

    # Get the prompt once (reused for all cycles)
    prompt = get_prompt()
    if not prompt:
        logger.error("Failed to get HMM prompt — exiting")
        escalate("ESCALATION from hmm_bot: failed to get HMM prompt")
        sys.exit(1)

    logger.info(f"Prompt loaded ({len(prompt)} chars)")

    # Verify Firefox is alive — auto-restart if not
    if not check_firefox_alive():
        logger.warning("Firefox not found at startup — starting it...")
        if not restart_firefox(args.platforms):
            escalate("ESCALATION from hmm_bot: Firefox failed to start")
            sys.exit(1)
        time.sleep(10)  # Let pages load after startup

    cycle = 0
    successes = 0
    failures = 0

    try:
        while True:
            cycle += 1
            if args.cycles > 0 and cycle > args.cycles:
                break

            logger.info(f"\n{'='*60}")
            logger.info(f"  CYCLE {cycle} — {successes} ok, {failures} fail")
            logger.info(f"{'='*60}")

            results = run_cycle(args.platforms, prompt)

            for platform, r in results.items():
                if r.get('success'):
                    successes += 1
                else:
                    failures += 1

            # Only notify on failures or milestones (every 50 cycles)
            if not results or any(not r.get('success') for r in results.values()):
                # Get the error type
                errs = [r.get('error', '?') for r in results.values() if not r.get('success')]
                if errs:
                    notify(f"FAIL cycle {cycle}: {', '.join(errs)} "
                           f"(total: {successes} ok, {failures} fail)")
            elif cycle % 50 == 0:
                notify(f"MILESTONE cycle {cycle}: {successes} ok, {failures} fail")

            # Check stats periodically
            if cycle % 5 == 0:
                logger.info(f"Builder stats:\n{get_stats()}")

            # Pause between cycles
            if args.cycles == 0 or cycle < args.cycles:
                time.sleep(args.pause)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        escalate(f"ESCALATION from hmm_bot: fatal error: {e}")
        raise

    logger.info(f"\nHMM Bot finished — {cycle} cycles, {successes} ok, {failures} fail")
    logger.info(f"Stats:\n{get_stats()}")


if __name__ == '__main__':
    main()
