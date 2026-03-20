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
from core.tree import find_elements, find_copy_buttons, find_menu_items, filter_useful_elements, detect_chrome_y
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

# Load platform configs from YAMLs — fence_after, stop_patterns, etc.
import yaml as _yaml

PLATFORMS_DIR = os.path.join(_ROOT, 'platforms')
_platform_configs = {}


def _load_platform_config(platform: str) -> dict:
    """Load platform YAML config (cached)."""
    if platform not in _platform_configs:
        try:
            with open(os.path.join(PLATFORMS_DIR, f'{platform}.yaml')) as f:
                _platform_configs[platform] = _yaml.safe_load(f) or {}
        except Exception:
            _platform_configs[platform] = {}
    return _platform_configs[platform]


def _get_fence_after(platform: str) -> list:
    """Get fence_after config from platform YAML."""
    return _load_platform_config(platform).get('fence_after', [])


def _get_stop_patterns(platform: str) -> list:
    """Get stop_patterns from platform YAML."""
    cfg = _load_platform_config(platform)
    return cfg.get('stop_patterns', ['stop'])


# Platform fresh-session URLs (from YAML base_url)
FRESH_URLS = {
    'chatgpt': 'https://chatgpt.com/?temporary-chat=true',
    'gemini': 'https://gemini.google.com/app',
    'grok': 'https://grok.com/',
}

# Cached AT-SPI references — avoids repeated deep traversals that cause D-Bus contention
_cached_firefox = {}  # platform -> AT-SPI firefox app ref
_cached_doc = {}      # platform -> AT-SPI document ref
_extracted_cache = {}  # platform -> extracted content (ChatGPT fixed-wait pre-extracts)
_our_firefox_pid = None  # PID of Firefox on OUR display (filters out cross-display AT-SPI contamination)


def discover_firefox_pid() -> int | None:
    """Discover the Firefox PID on our DISPLAY via xdotool.
    All Firefox instances share D-Bus, so AT-SPI sees them all.
    This PID lets us filter to only OUR display's Firefox."""
    global _our_firefox_pid
    try:
        r = subprocess.run(
            ['xdotool', 'search', '--class', 'Firefox'],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            wid = r.stdout.strip().split('\n')[-1]  # Last = real window (not mutter decorator)
            r2 = subprocess.run(
                ['xdotool', 'getwindowpid', wid],
                capture_output=True, text=True, timeout=3,
            )
            if r2.returncode == 0 and r2.stdout.strip():
                _our_firefox_pid = int(r2.stdout.strip())
                logger.info(f"Firefox PID on {os.environ.get('DISPLAY', '?')}: {_our_firefox_pid}")
                return _our_firefox_pid
    except Exception as e:
        logger.warning(f"Failed to discover Firefox PID: {e}")
    return None


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
    ff = atspi.find_firefox_for_platform(platform, pid=_our_firefox_pid)
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


def invalidate_doc_cache(platform: str):
    """Clear cached document ref after navigation (Firefox ref stays valid)."""
    _cached_doc.pop(platform, None)


def invalidate_all_cache():
    """Clear ALL cached refs after Firefox restart."""
    _cached_firefox.clear()
    _cached_doc.clear()


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
            ['xdotool', 'search', '--class', 'Firefox'],
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
        # No window found — DON'T pkill all Firefox (kills other displays' bots).
        # Just log and proceed to start a new instance.
        logger.info(f"No Firefox windows found on {display} — starting fresh")

    subprocess.run(['pkill', '-9', '-f', 'crashreporter'], capture_output=True)
    for _ in range(10):
        time.sleep(1)
        # Check if our display is clear
        try:
            r = subprocess.run(
                ['xdotool', 'search', '--class', 'Firefox'],
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
            # NOTE: sessionstore files are preserved — they contain session
            # cookies needed for login. Old tab restoration is harmless since
            # the bot navigates to fresh URLs via Ctrl+L.
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
            # sessionstore preserved — contains session cookies for login

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
            # On bare Xvfb (no window manager), Firefox may create oversized
            # windows. Force 1920×1080 at (0,0) so AT-SPI coords stay on-screen.
            try:
                r = subprocess.run(
                    ['xdotool', 'search', '--class', 'Firefox'],
                    capture_output=True, text=True, timeout=5, env=firefox_env,
                )
                for wid in r.stdout.strip().split('\n'):
                    if wid:
                        subprocess.run(['xdotool', 'windowmap', wid], env=firefox_env, timeout=3, capture_output=True)
                        subprocess.run(['xdotool', 'windowsize', wid, '1920', '1080'], env=firefox_env, timeout=3, capture_output=True)
                        subprocess.run(['xdotool', 'windowmove', wid, '0', '0'], env=firefox_env, timeout=3, capture_output=True)
            except Exception as e:
                logger.debug(f"Window positioning: {e}")
            logger.info(f"Firefox restarted successfully ({(i+1)*2}s)")
            invalidate_all_cache()
            discover_firefox_pid()
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
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)


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

    # Invalidate doc cache — page changed but Firefox ref stays valid
    invalidate_doc_cache(platform)

    # Verification is best-effort — D-Bus contention in parallel mode can
    # make AT-SPI verification fail even when page loaded fine. Trust the
    # navigation and let attach_file discover the document.
    doc = get_doc(platform, force_refresh=True)
    if not doc:
        logger.info(f"[{platform}] AT-SPI doc not found yet (D-Bus lag) — continuing anyway")

    return True


def check_firefox_alive(platform: str = None, retries: int = 3) -> bool:
    """Check if Firefox is running via xdotool (DISPLAY-scoped).

    Uses --class Firefox instead of --name 'Mozilla Firefox' because
    page navigation changes the window title (e.g. to 'ChatGPT').
    Class name stays 'Firefox' regardless of page content.
    """
    for attempt in range(retries):
        try:
            r = subprocess.run(
                ['xdotool', 'search', '--class', 'Firefox'],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                return True
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(2)
    return False


def _find_elements_with_fence(doc, platform: str, timeout_sec: int = 15):
    """find_elements with fence_after from YAML + thread-based timeout.

    Uses a daemon thread so the main thread can kill it if AT-SPI hangs
    in a C extension (SIGALRM can't interrupt C-level D-Bus calls).
    """
    import threading
    fences = _get_fence_after(platform)
    result = []
    error = [None]

    def _worker():
        try:
            result.extend(find_elements(doc, fence_after=fences))
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive():
        logger.warning(f"[{platform}] AT-SPI find_elements timed out after {timeout_sec}s")
        # Thread is daemon — will be killed when main process exits or on next GC
        return []
    if error[0]:
        logger.warning(f"[{platform}] find_elements error: {error[0]}")
        return []
    return result


def scan_for_stop_button(platform: str) -> bool:
    """Check if a stop/cancel button is visible (AI is generating)."""
    doc = get_doc(platform)
    if not doc:
        return False

    elements = _find_elements_with_fence(doc, platform)
    patterns = set(_get_stop_patterns(platform))

    for e in elements:
        name = (e.get('name') or '').strip()
        if not name or len(name) > 50:
            continue
        if 'button' not in e.get('role', ''):
            continue
        name_lower = name.lower().strip()
        if any(p in name_lower for p in patterns):
            return True
    return False


def count_copy_buttons(platform: str) -> int:
    """Count visible copy buttons on the platform."""
    doc = get_doc(platform)
    if not doc:
        return 0

    elements = _find_elements_with_fence(doc, platform)
    return len(find_copy_buttons(elements))


def find_input_field_atspi(platform: str):
    """Find the chat input field via AT-SPI. Returns element dict or None.

    Returns dict with 'x', 'y', 'atspi_obj' keys (same as find_elements output).
    With taeys-hands v7, AT-SPI ALWAYS exposes the input field.
    If this returns None, it's a real bug — callers must fail loud.
    """
    doc = get_doc(platform)
    if not doc:
        return None

    elements = _find_elements_with_fence(doc, platform)
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


def _scan_with_thread_timeout(platform: str, timeout_sec: int = 15):
    """scan_for_stop_button with thread timeout (Gemini/Grok only).

    Works reliably for Gemini/Grok where AT-SPI doesn't hang.
    Do NOT use for ChatGPT — its AT-SPI tree hangs and blocks the GIL.

    Returns: True (stop found), False (no stop), None (timed out).
    """
    import threading
    result = [None]

    def _worker():
        result[0] = scan_for_stop_button(platform)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)

    if t.is_alive():
        logger.warning(f"[{platform}] scan timed out after {timeout_sec}s")
        return None
    return result[0]


def wait_for_response(platform: str, timeout: int = 600) -> bool:
    """Wait for AI response to complete via stop-button polling."""
    return _wait_atspi_polling(platform, timeout)


def _wait_fixed_then_extract(platform: str, timeout: int = 300) -> bool:
    """ChatGPT/Gemini: wait fixed intervals, try extract to detect completion.

    Stop button not reliably exposed in AT-SPI on these platforms.
    Instead: wait, then try to extract. If extract gets content, done.
    """
    start = time.time()
    # With 75K token packages, AIs need more time. Gemini 120s, others 90s.
    initial_wait = 120 if platform == 'gemini' else 90

    logger.info(f"[{platform}] Fixed wait {initial_wait}s...")
    time.sleep(initial_wait)

    # Try extract every 15s until timeout
    attempt = 0
    while time.time() - start < timeout:
        attempt += 1
        if not check_firefox_alive(platform):
            logger.error(f"[{platform}] Firefox died during wait")
            return False

        logger.info(f"[{platform}] Extract attempt {attempt} ({time.time()-start:.0f}s elapsed)...")

        # Try to get response content
        content = extract_response(platform)
        if content and len(content) > 100:
            # Verify it's not the prompt
            start_text = content.strip()[:200].lower()
            prompt_markers = ['analyze the following', 'package analysis request',
                              'you are analyzing', 'respond only with minified json',
                              'critical: echo back', 'analyze all', 'for each item provide']
            if not any(m in start_text for m in prompt_markers):
                logger.info(f"[{platform}] Response detected ({len(content)} chars, {time.time()-start:.0f}s)")
                # Store content for process_platform to use (avoid double-extract)
                _extracted_cache[platform] = content
                return True
            else:
                logger.info(f"[{platform}] Got prompt text, not response yet")

        time.sleep(15)

    logger.warning(f"[{platform}] No response after {timeout}s")
    return False


def _wait_atspi_polling(platform: str, timeout: int = 600) -> bool:
    """Gemini/Grok: poll AT-SPI stop button for response detection.

    Reliable on these platforms — AT-SPI doesn't hang like ChatGPT.
    """
    start = time.time()
    initial_copy_count = count_copy_buttons(platform)
    phase = 'waiting_for_start'
    poll_count = 0

    while time.time() - start < timeout:
        if not check_firefox_alive(platform):
            logger.error(f"[{platform}] Firefox died during response wait")
            return False

        has_stop = _scan_with_thread_timeout(platform)
        poll_count += 1

        if phase == 'waiting_for_start':
            if has_stop is None:
                if poll_count % 3 == 0:
                    logger.info(f"[{platform}] Scan timeout ({poll_count} polls, {time.time()-start:.0f}s)")
            elif has_stop:
                logger.info(f"[{platform}] Stop button appeared — AI generating")
                phase = 'generating'
            elif time.time() - start > 30:
                current_copy = count_copy_buttons(platform)
                if current_copy > initial_copy_count:
                    # 0→1 could be just the prompt's copy button appearing (Grok).
                    # Require +2 from zero, or +1 from non-zero (prompt already counted).
                    if initial_copy_count == 0 and current_copy == 1:
                        logger.info(f"[{platform}] Copy 0->1 (may be prompt button, waiting for response...)")
                        # Update baseline so next check detects 1→2
                        initial_copy_count = 1
                    else:
                        logger.info(f"[{platform}] Copy count increased {initial_copy_count}->{current_copy} (fast response)")
                        return True
                elif time.time() - start > 120:
                    logger.warning(f"[{platform}] No stop button after 120s — possible send failure")
                    return False
            time.sleep(5)

        elif phase == 'generating':
            if has_stop is None:
                if poll_count % 3 == 0:
                    logger.info(f"[{platform}] Still generating ({poll_count} polls, {time.time()-start:.0f}s)")
            elif not has_stop:
                logger.info(f"[{platform}] Stop button gone — settling...")
                time.sleep(2)
                confirm = _scan_with_thread_timeout(platform)
                if confirm is None:
                    logger.info(f"[{platform}] Confirm scan timed out — assuming still generating")
                elif not confirm:
                    logger.info(f"[{platform}] Response complete ({time.time()-start:.0f}s)")
                    return True
                else:
                    logger.info(f"[{platform}] Stop button reappeared — still generating")
            time.sleep(5)

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

    elements = _find_elements_with_fence(doc, platform)
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
            elements = _find_elements_with_fence(doc, platform)
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

    # Release clipboard ownership before clicking Copy.
    # xsel --input stays resident as clipboard owner on Xvfb, blocking
    # Firefox's navigator.clipboard.writeText() from taking ownership.
    # Kill any lingering xsel input processes so Firefox JS can write.
    clipboard.write_marker('')  # ensure xsel is the owner (not some stale process)
    time.sleep(0.1)
    subprocess.run(['pkill', '-f', 'xsel.*clipboard'], capture_output=True, timeout=3)
    time.sleep(0.1)

    from core.interact import atspi_click
    if target.get('atspi_obj') and atspi_click(target):
        logger.info(f"[{platform}] Copy via AT-SPI at ({target['x']}, {target['y']})")
    else:
        inp.click_at(target['x'], target['y'])
        logger.info(f"[{platform}] Copy via xdotool at ({target['x']}, {target['y']})")

    # Poll clipboard until Firefox writes content (up to 3s)
    content = None
    for _ in range(6):
        time.sleep(0.5)
        raw = clipboard.read()
        if raw:
            content = raw
            break

    if not content:
        logger.error(f"[{platform}] Copy button clicked but clipboard unchanged after 3s")
        return ''

    # Check if we got the prompt instead of the response
    # Use specific markers only — generic ones like 'analyze all' false-positive
    # on Grok/ChatGPT responses that reference the prompt instructions
    if content:
        start_text = content.strip()[:200].lower()
        prompt_markers = ['analyze the following', 'package analysis request',
                          'respond only with minified json',
                          'critical: echo back', 'analyze all all items']
        if any(m in start_text for m in prompt_markers):
            # Got prompt text — try ALL other copy buttons (Grok's response button
            # often has zero extents → Y=0 → sorts first, so [-1] picks prompt's)
            alternatives = [b for b in copy_buttons if b is not target]
            found_alt = False
            for alt_btn in alternatives:
                subprocess.run(['pkill', '-f', 'xsel.*clipboard'], capture_output=True, timeout=3)
                time.sleep(0.1)
                if alt_btn.get('atspi_obj') and atspi_click(alt_btn):
                    logger.info(f"[{platform}] Trying alt copy button at ({alt_btn['x']}, {alt_btn['y']})")
                else:
                    inp.click_at(alt_btn['x'], alt_btn['y'])
                    logger.info(f"[{platform}] Trying alt copy button (xdotool) at ({alt_btn['x']}, {alt_btn['y']})")
                time.sleep(0.8)
                alt = clipboard.read()
                if alt and alt != content:
                    content = alt
                    found_alt = True
                    logger.info(f"[{platform}] Got response from alt copy button ({len(alt)} chars)")
                    break
            if not found_alt:
                logger.warning(f"[{platform}] All {len(copy_buttons)} copy buttons returned prompt text")

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
    """Attach a file: open file dialog → type path → confirm.

    Handles everything directly instead of using handle_attach(), because
    the standard clipboard paste doesn't reliably select files on Xvfb.
    """
    from tools.attach import _get_attach_button_coords as get_attach_button_coords, _any_file_dialog_open as any_file_dialog_open, _close_stale_file_dialogs as close_stale_file_dialogs
    from core.interact import atspi_click

    firefox = get_firefox(platform)

    # Stale dialog from previous run = bug. Clean it up and fail.
    if _find_dialog_wid():
        logger.error(f"[{platform}] Stale file dialog found — cleaning up")
        close_stale_file_dialogs()
        return False

    # Dismiss any stale popups
    inp.press_key('Escape')
    time.sleep(0.3)

    # ChatGPT: AT-SPI button click + dropdown walk (same as tools/attach.py).
    # Ctrl+U no longer works — ChatGPT removed the keyboard shortcut.
    # "Add files and more" opens a React dropdown invisible to AT-SPI.
    # We click the button, then iterate Down+Enter through dropdown items
    # until a file dialog appears. Handles menu reordering gracefully.
    if platform == 'chatgpt':
        btn = None
        for attempt in range(8):
            doc = get_doc(platform, force_refresh=True)
            if not doc:
                logger.info(f"[{platform}] AT-SPI doc not ready, retry {attempt+1}/8...")
                time.sleep(3)
                continue
            from tools.attach import _get_attach_button_coords as get_attach_button_coords
            btn = get_attach_button_coords(doc, platform=platform)
            if btn:
                break
            logger.info(f"[{platform}] Attach button not found, retry {attempt+1}/8...")
            time.sleep(3)
        if not btn:
            logger.error(f"[{platform}] Attach button not found after 8 retries")
            return False

        # Click attach button and walk dropdown items looking for file dialog
        from core.interact import atspi_click
        for pass_num, use_atspi in enumerate([True, False]):
            if use_atspi:
                btn_obj = btn.get('atspi_obj')
                if btn_obj:
                    try:
                        ai = btn_obj.get_action_iface()
                        if ai and ai.get_n_actions() > 0:
                            ai.do_action(0)
                            logger.info(f"[{platform}] Pass {pass_num+1}: AT-SPI click attach")
                        else:
                            continue
                    except Exception:
                        continue
                else:
                    continue
            else:
                inp.click_at(btn['x'], btn['y'])
                logger.info(f"[{platform}] Pass {pass_num+1}: xdotool click attach at ({btn['x']}, {btn['y']})")
            time.sleep(1.5)

            # Check if click directly opened file dialog
            if _find_dialog_wid():
                break

            # Walk dropdown items: Down+Enter, check for dialog after each
            for item_idx in range(8):
                inp.press_key('Down')
                time.sleep(0.3)
                inp.press_key_split('Return')
                time.sleep(2.0)

                for _ in range(5):
                    if _find_dialog_wid():
                        logger.info(f"[{platform}] File dialog opened after dropdown item {item_idx + 1}")
                        break
                    time.sleep(0.3)
                if _find_dialog_wid():
                    break

                # Not the upload item — escape and reopen dropdown
                inp.press_key('Escape')
                time.sleep(0.5)
                if item_idx < 7:
                    inp.click_at(btn['x'], btn['y'])
                    time.sleep(1.0)

            if _find_dialog_wid():
                break
    elif platform == 'gemini':
        # Gemini: AT-SPI button click → dropdown → "Upload files" menu item
        btn = None
        for attempt in range(8):
            doc = get_doc(platform, force_refresh=True)
            if not doc:
                logger.info(f"[{platform}] AT-SPI doc not ready, retry {attempt+1}/8...")
                time.sleep(3)
                continue
            btn = get_attach_button_coords(doc, platform=platform)
            if btn:
                break
            logger.info(f"[{platform}] Attach button not found, retry {attempt+1}/8...")
            time.sleep(3)
        if not btn:
            logger.error(f"[{platform}] Attach button not found after 8 retries")
            return False

        btn_obj = btn.get('atspi_obj')
        atspi_clicked = False
        if btn_obj:
            try:
                ai = btn_obj.get_action_iface()
                if ai and ai.get_n_actions() > 0:
                    ai.do_action(0)
                    atspi_clicked = True
                    logger.info(f"[{platform}] Clicked attach button via AT-SPI at ({btn['x']}, {btn['y']})")
            except Exception as e:
                logger.debug(f"[{platform}] AT-SPI do_action failed: {e}")
        if not atspi_clicked:
            inp.click_at(btn['x'], btn['y'])
            logger.info(f"[{platform}] Clicked attach button via xdotool at ({btn['x']}, {btn['y']})")
        time.sleep(1.5)

        # Gemini: click "Upload files" in dropdown.
        # Use find_menu_items() — same 4-pass strategy as main MCP implementation.
        # Searches doc scope first, then Firefox root (catches React portal menus).
        if not _find_dialog_wid():
            time.sleep(1.5)
            clicked_upload = False
            firefox = get_firefox(platform)
            doc2 = get_doc(platform, force_refresh=True)
            menu_items = find_menu_items(firefox, doc2)
            if menu_items:
                for item in menu_items:
                    name = (item.get('name') or '').strip().lower()
                    if name.startswith('upload file'):
                        if item.get('atspi_obj') and atspi_click(item):
                            logger.info(f"[{platform}] Clicked '{item.get('name')}' via AT-SPI")
                        else:
                            inp.click_at(item['x'], item['y'])
                            logger.info(f"[{platform}] Clicked '{item.get('name')}' via xdotool")
                        clicked_upload = True
                        time.sleep(2.0)
                        break
                if not clicked_upload:
                    # Menu items found but none match "Upload files" — log what we see
                    names = [f"'{i.get('name','')}'" for i in menu_items[:5]]
                    logger.warning(f"[{platform}] Menu items found but no 'Upload files': {names}")
            else:
                logger.warning(f"[{platform}] find_menu_items returned empty — trying keyboard nav")
            # Keyboard nav fallback: dropdown should be open, Down+Enter selects first item (Upload files)
            if not clicked_upload and not _find_dialog_wid():
                logger.info(f"[{platform}] Keyboard nav fallback: Down+Enter")
                inp.press_key('Down')
                time.sleep(0.5)
                inp.press_key_split('Return')
                time.sleep(2.0)
    else:
        # Grok and others: click input first to activate page (homepage mode
        # has dormant buttons + "Connect X" popup blocks dropdowns), then
        # find button and use two-pass click strategy.
        input_el = find_input_field_atspi(platform)
        if input_el:
            inp.click_at(input_el['x'], input_el['y'])
            logger.info(f"[{platform}] Clicked input to activate page at ({input_el['x']}, {input_el['y']})")
            time.sleep(1.0)
            inp.press_key('Escape')  # Dismiss any popup that appeared
            time.sleep(0.3)
        btn = None
        for attempt in range(8):
            doc = get_doc(platform, force_refresh=True)
            if not doc:
                logger.info(f"[{platform}] AT-SPI doc not ready, retry {attempt+1}/8...")
                time.sleep(3)
                continue
            btn = get_attach_button_coords(doc, platform=platform)
            if btn:
                break
            logger.info(f"[{platform}] Attach button not found, retry {attempt+1}/8...")
            time.sleep(3)
        if not btn:
            logger.error(f"[{platform}] Attach button not found after 8 retries")
            return False

        # Two-pass attach: matches tools/attach.py _try_click_then_dialog()
        # Pass 1: AT-SPI do_action + keyboard nav
        # Pass 2: xdotool click + keyboard nav (fallback)
        def _click_and_nav(use_atspi):
            if use_atspi:
                btn_obj = btn.get('atspi_obj')
                if btn_obj:
                    try:
                        ai = btn_obj.get_action_iface()
                        if ai and ai.get_n_actions() > 0:
                            ai.do_action(0)
                            logger.info(f"[{platform}] Clicked attach button via AT-SPI at ({btn['x']}, {btn['y']})")
                        else:
                            return False
                    except Exception:
                        return False
                else:
                    return False
            else:
                inp.click_at(btn['x'], btn['y'])
                logger.info(f"[{platform}] Clicked attach button via xdotool at ({btn['x']}, {btn['y']})")
            time.sleep(1.5)
            if _find_dialog_wid():
                return True
            inp.press_key('Down')
            time.sleep(0.5)
            inp.press_key_split('Return')
            time.sleep(2.5)
            for _ in range(10):
                if _find_dialog_wid():
                    return True
                time.sleep(0.3)
            return False

        if not _click_and_nav(use_atspi=True):
            if not _click_and_nav(use_atspi=False):
                pass  # Falls through to dialog_found check below

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


def select_model(platform: str, model_name: str) -> bool:
    """Select a model on the platform (e.g., 'Instant' for ChatGPT).

    Only ChatGPT is supported currently. Uses xdotool click (React portal
    dropdown is invisible to AT-SPI) + keyboard navigation.
    """
    if platform != 'chatgpt':
        logger.info(f"[{platform}] Model selection not implemented — skipping")
        return True

    doc = get_doc(platform)
    if not doc:
        logger.warning(f"[{platform}] No document for model selection")
        return False

    elements = _find_elements_with_fence(doc, platform)

    # Find model selector button: "Model selector, current model is ..."
    selector = None
    current_model = None
    for e in elements:
        name = (e.get('name') or '').strip()
        if name.startswith('Model selector, current model is') and 'button' in e.get('role', ''):
            selector = e
            current_model = name.split('is ')[-1].strip() if 'is ' in name else ''
            break

    if not selector:
        logger.warning(f"[{platform}] Model selector button not found")
        return False

    if current_model and current_model.lower() == model_name.lower():
        logger.info(f"[{platform}] Already on {model_name} — no change needed")
        return True

    logger.info(f"[{platform}] Current model: {current_model}, switching to {model_name}")

    # Click model selector with xdotool (AT-SPI do_action opens browser context menu)
    inp.click_at(selector['x'], selector['y'])
    time.sleep(1.5)

    # React dropdown focus position is unpredictable. Navigate from known position:
    # Press Home/Up 5x to guarantee we're at the top, then Down to target.
    # Models in order: Auto(0), Instant(1), Thinking(2), Pro(3), Legacy(4)
    model_positions = {'auto': 0, 'instant': 1, 'thinking': 2, 'pro': 3, 'legacy': 4}
    target_pos = model_positions.get(model_name.lower())
    if target_pos is None:
        logger.error(f"[{platform}] Unknown model: {model_name}")
        inp.press_key('Escape')
        return False

    # Go to top of list
    for _ in range(5):
        inp.press_key('Up')
        time.sleep(0.15)

    # Navigate down to target
    for _ in range(target_pos):
        inp.press_key('Down')
        time.sleep(0.3)

    inp.press_key('Return')
    time.sleep(1.0)

    # Verify switch by re-inspecting
    invalidate_doc_cache(platform)
    time.sleep(1.0)
    doc2 = get_doc(platform, force_refresh=True)
    if doc2:
        elems2 = _find_elements_with_fence(doc2, platform)
        for e in elems2:
            name = (e.get('name') or '').strip()
            if name.startswith('Model selector, current model is'):
                new_model = name.split('is ')[-1].strip()
                logger.info(f"[{platform}] Model after switch: {new_model}")
                break

    logger.info(f"[{platform}] Model switched to {model_name}")
    return True


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


def dismiss_browser_popups(platform: str) -> None:
    """Dismiss native Firefox permission popups (e.g. persistent storage).

    These popups block all page interaction. Uses AT-SPI do_action on
    Block/Deny buttons (xdotool clicks don't reach native Firefox UI).
    """
    doc = get_doc(platform, force_refresh=True)
    if not doc:
        return

    # Walk up to the frame (popups are siblings of the document, not children)
    try:
        frame = doc.get_parent()
        while frame and frame.get_role_name() != 'frame':
            frame = frame.get_parent()
    except Exception:
        return

    if not frame:
        return

    # BFS the frame for Block/Deny/Dismiss buttons in the popup area (y < 250)
    queue = [frame]
    count = 0
    dismissed = False
    while queue and count < 200:
        node = queue.pop(0)
        count += 1
        try:
            role = node.get_role_name()
            name = (node.get_name() or '').strip()
            if role == 'push button' and name in ('Block', 'Deny', 'Not now', 'Not Now', 'Dismiss'):
                ext = node.get_extents(0)
                if ext.y < 300:  # Popup area is at top of window
                    ai = node.get_action_iface()
                    if ai and ai.get_n_actions() > 0:
                        ai.do_action(0)
                        logger.info(f"[{platform}] Dismissed browser popup: clicked '{name}'")
                        dismissed = True
                        break
            for k in range(min(node.get_child_count(), 30)):
                queue.append(node.get_child_at_index(k))
        except Exception:
            pass

    if dismissed:
        time.sleep(1.0)


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

    # Step 2.5: Dismiss any browser permission popups
    dismiss_browser_popups(platform)

    # Step 3: Select model if configured
    # ChatGPT: use "auto" — "instant" can't process file attachments
    if platform == 'chatgpt':
        select_model(platform, 'auto')

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
    # ChatGPT/Gemini: 5min (fixed-wait extraction, no stop button).
    # Grok: 10min (AT-SPI stop button polling, generation can be slow).
    resp_timeout = 600 if platform == 'grok' else 300
    if not wait_for_response(platform, timeout=resp_timeout):
        result['error'] = 'response_timeout'
        fail_package(platform, 'response_timeout')
        return result

    time.sleep(2)  # Let response fully render

    # Step 7: Extract response (ChatGPT may have pre-extracted in wait phase)
    content = _extracted_cache.pop(platform, None)
    if content:
        logger.info(f"[{platform}] Using pre-extracted response ({len(content)} chars)")
    else:
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
    else:
        # Firefox already running — discover its PID for AT-SPI filtering
        discover_firefox_pid()

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

            # Pause between cycles (with jitter to stagger parallel bots)
            if args.cycles == 0 or cycle < args.cycles:
                import random
                jitter = random.uniform(0, 10)
                time.sleep(args.pause + jitter)

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
