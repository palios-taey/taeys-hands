#!/usr/bin/env python3
"""cycle_bot.py — Autonomous chat cycle bot for Research, Audit, and Dream.

Mechanical automation like hmm_bot: no LLM in the loop. Handles model/mode
selection per cycle type, file attachment, sending, response detection, and
extraction across all 5 chat platforms.

Calling AI just provides cycle_type + message + attachments. Bot does the rest.
Hard stops on every failure — no retries, no fallbacks.

Usage:
    # Single cycle on one platform
    python3 agents/cycle_bot.py --platform chatgpt --cycle-type audit \
        --message "Review this code" --attach /path/to/file.md

    # Multiple platforms
    python3 agents/cycle_bot.py --platform chatgpt gemini grok \
        --cycle-type dream --message-file /tmp/prompt.txt \
        --attach /tmp/package.md

    # Programmatic (from another script/AI)
    from agents.cycle_bot import run_cycle
    result = run_cycle('audit', 'chatgpt', 'Review this', ['/tmp/file.md'])
    if result['success']:
        print(result['response'])

Environment:
    DISPLAY          — X11 display (default: :0)
    NOTIFY_TARGET    — taey-notify target for escalations (default: weaver)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time

# Must set before AT-SPI imports
os.environ.setdefault('DISPLAY', ':0')

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import atspi, clipboard
from core import input as inp
from core.tree import (find_elements, find_copy_buttons, find_menu_items,
                       filter_useful_elements, detect_chrome_y)
from core.platforms import TAB_SHORTCUTS

import yaml as _yaml

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('cycle_bot')

NOTIFY_TARGET = os.environ.get('NOTIFY_TARGET', 'weaver')
PLATFORMS_DIR = os.path.join(_ROOT, 'platforms')

# ══════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════

FRESH_URLS = {
    'chatgpt': 'https://chatgpt.com/?temporary-chat=true',
    'claude': 'https://claude.ai/new',
    'gemini': 'https://gemini.google.com/app',
    'grok': 'https://grok.com/',
    'perplexity': 'https://www.perplexity.ai/',
}

# Cycle type → platform → required setup.
# 'model': dropdown position or name to select
# 'thinking_time': ChatGPT-specific sub-mode
# 'tool': tool to enable (Gemini Deep Think, Perplexity Deep Research)
# 'mode': mode picker selection (Gemini)
CYCLE_CONFIGS = {
    'research': {
        'chatgpt': {'model': 'auto'},
        'claude': {},  # default Sonnet
        'gemini': {'mode': 'fast'},
        'grok': {'model': 'auto'},
        'perplexity': {},  # default
    },
    'audit': {
        'chatgpt': {'model': 'pro', 'thinking_time': 'extended'},
        'claude': {'model': 'extended thinking'},
        'gemini': {'mode': 'pro', 'tool': 'deep think'},
        'grok': {'model': 'heavy'},
        'perplexity': {'tool': 'deep research'},
    },
    'dream': {
        'chatgpt': {'model': 'pro', 'thinking_time': 'extended'},
        'claude': {'model': 'extended thinking'},
        'gemini': {'mode': 'pro', 'tool': 'deep think'},
        'grok': {'model': 'heavy'},
        'perplexity': {'tool': 'deep research'},
    },
}

# Response timeouts per cycle type (seconds)
TIMEOUTS = {
    'research': 180,
    'audit': 600,
    'dream': 600,
}

# ══════════════════════════════════════════════════════════════════════
# AT-SPI helpers
# ══════════════════════════════════════════════════════════════════════

_platform_configs = {}
_cached_doc = {}
_cached_firefox = {}
_our_firefox_pid = None


def _load_platform_config(platform: str) -> dict:
    if platform not in _platform_configs:
        try:
            with open(os.path.join(PLATFORMS_DIR, f'{platform}.yaml')) as f:
                _platform_configs[platform] = _yaml.safe_load(f) or {}
        except Exception:
            _platform_configs[platform] = {}
    return _platform_configs[platform]


def _get_fence_after(platform: str) -> list:
    return _load_platform_config(platform).get('fence_after', [])


def _get_stop_patterns(platform: str) -> list:
    return _load_platform_config(platform).get('stop_patterns', ['stop'])


def _get_our_firefox_pid():
    """Get PID of Firefox on OUR display (filters cross-display contamination)."""
    global _our_firefox_pid
    if _our_firefox_pid:
        try:
            os.kill(_our_firefox_pid, 0)
            return _our_firefox_pid
        except OSError:
            _our_firefox_pid = None

    try:
        r = subprocess.run(
            ['xdotool', 'search', '--class', 'Firefox'],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            wid = r.stdout.strip().split('\n')[-1]
            r2 = subprocess.run(
                ['xdotool', 'getwindowpid', wid],
                capture_output=True, text=True, timeout=3,
            )
            if r2.returncode == 0 and r2.stdout.strip():
                _our_firefox_pid = int(r2.stdout.strip())
                return _our_firefox_pid
    except Exception:
        pass
    return None


def get_firefox(platform: str = None):
    """Get Firefox AT-SPI app, filtered to our display's PID."""
    pid = _get_our_firefox_pid()
    if pid:
        return atspi.find_firefox_by_pid(pid) if hasattr(atspi, 'find_firefox_by_pid') else atspi.find_firefox(platform)
    return atspi.find_firefox(platform)


def get_doc(platform: str, force_refresh: bool = False):
    """Get AT-SPI document for platform."""
    if force_refresh:
        _cached_doc.pop(platform, None)
    if platform in _cached_doc:
        try:
            _cached_doc[platform].get_name()
            return _cached_doc[platform]
        except Exception:
            _cached_doc.pop(platform, None)

    firefox = get_firefox(platform)
    if not firefox:
        return None
    doc = atspi.get_platform_document(firefox, platform)
    if doc:
        _cached_doc[platform] = doc
    return doc


def invalidate_doc_cache(platform: str):
    _cached_doc.pop(platform, None)


def scan_elements(platform: str, timeout_sec: int = 15) -> list:
    """find_elements with fence_after + thread timeout."""
    import threading
    doc = get_doc(platform)
    if not doc:
        return []
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
        logger.warning(f"[{platform}] AT-SPI scan timed out after {timeout_sec}s")
        return []
    if error[0]:
        logger.warning(f"[{platform}] scan error: {error[0]}")
        return []
    return result


def check_firefox_alive() -> bool:
    try:
        r = subprocess.run(
            ['xdotool', 'search', '--class', 'Firefox'],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def escalate(msg: str):
    """Send escalation via taey-notify."""
    logger.error(msg)
    try:
        subprocess.run(
            ['taey-notify', NOTIFY_TARGET, msg, '--type', 'escalation'],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# Navigation
# ══════════════════════════════════════════════════════════════════════

def navigate_fresh(platform: str) -> bool:
    """Navigate to fresh session URL."""
    from tools.attach import _close_stale_file_dialogs as close_stale_dialogs
    url = FRESH_URLS.get(platform)
    if not url:
        logger.error(f"[{platform}] No fresh URL configured")
        return False

    close_stale_dialogs()
    if not inp.focus_firefox():
        logger.error(f"[{platform}] Cannot focus Firefox")
        return False

    time.sleep(0.3)
    inp.press_key('Escape')
    time.sleep(0.2)
    inp.press_key('ctrl+l')
    time.sleep(0.3)
    inp.type_into_ui(url)
    time.sleep(0.1)
    inp.press_key('Return')
    time.sleep(8)

    invalidate_doc_cache(platform)
    doc = get_doc(platform, force_refresh=True)
    if not doc:
        logger.warning(f"[{platform}] AT-SPI doc not found after nav — may be D-Bus lag")
    return True


# ══════════════════════════════════════════════════════════════════════
# Model / Mode / Tool selection
# ══════════════════════════════════════════════════════════════════════

def _find_button(elements: list, name_contains: str, chrome_y: int = 0) -> dict:
    """Find a button element whose name contains the given text (case-insensitive)."""
    target = name_contains.lower()
    for e in elements:
        if 'button' not in e.get('role', ''):
            continue
        name = (e.get('name') or '').strip().lower()
        if target in name and e.get('y', 0) > chrome_y:
            return e
    return None


def _click_element(elem: dict) -> bool:
    """Click an element via AT-SPI do_action, falling back to xdotool."""
    from core.interact import atspi_click
    if elem.get('atspi_obj') and atspi_click(elem):
        return True
    if elem.get('x') and elem.get('y'):
        return inp.click_at(elem['x'], elem['y'])
    return False


def _find_and_click_menu_item(platform: str, item_name: str, partial: bool = True) -> bool:
    """Open the most recently clicked dropdown and find+click a menu item.

    Args:
        platform: Platform name.
        item_name: Item to find (case-insensitive).
        partial: If True, match substring. If False, exact match.
    """
    target = item_name.lower()
    firefox = get_firefox(platform)
    doc = get_doc(platform, force_refresh=True)

    for attempt in range(5):
        items = find_menu_items(firefox, doc)
        if items:
            for item in items:
                name = (item.get('name') or '').strip().lower()
                match = (target in name) if partial else (name == target)
                if match:
                    if _click_element(item):
                        logger.info(f"[{platform}] Selected '{item.get('name')}'")
                        return True
            names = [f"'{i.get('name', '')}'" for i in items[:8]]
            logger.warning(f"[{platform}] Menu items found but no '{item_name}': {names}")
            return False
        time.sleep(0.6)

    logger.error(f"[{platform}] No menu items found after 5 attempts")
    return False


def setup_chatgpt(cycle_type: str) -> bool:
    """Set ChatGPT model and thinking time for cycle type."""
    config = CYCLE_CONFIGS.get(cycle_type, {}).get('chatgpt', {})
    target_model = config.get('model', 'auto')

    elements = scan_elements('chatgpt')
    chrome_y = detect_chrome_y(get_doc('chatgpt')) if get_doc('chatgpt') else 0

    # Find model selector
    selector = None
    current_model = ''
    for e in elements:
        name = (e.get('name') or '').strip()
        if name.startswith('Model selector, current model is') and 'button' in e.get('role', ''):
            selector = e
            current_model = name.split('is ')[-1].strip().lower() if 'is ' in name else ''
            break

    if not selector:
        logger.error("[chatgpt] Model selector button not found")
        return False

    # Check if already on target
    model_positions = {'auto': 0, 'instant': 1, 'thinking': 2, 'pro': 3, 'legacy': 4}
    target_pos = model_positions.get(target_model)
    if target_pos is None:
        logger.error(f"[chatgpt] Unknown model: {target_model}")
        return False

    if target_model in current_model:
        logger.info(f"[chatgpt] Already on {target_model}")
    else:
        logger.info(f"[chatgpt] Switching from '{current_model}' to '{target_model}'")
        inp.click_at(selector['x'], selector['y'])
        time.sleep(1.5)
        for _ in range(5):
            inp.press_key('Up')
            time.sleep(0.15)
        for _ in range(target_pos):
            inp.press_key('Down')
            time.sleep(0.3)
        inp.press_key('Return')
        time.sleep(1.5)

        # Verify
        invalidate_doc_cache('chatgpt')
        elements = scan_elements('chatgpt')
        verified = False
        for e in elements:
            name = (e.get('name') or '').strip()
            if name.startswith('Model selector, current model is'):
                new_model = name.split('is ')[-1].strip().lower()
                if target_model in new_model:
                    verified = True
                    logger.info(f"[chatgpt] Model verified: {new_model}")
                else:
                    logger.error(f"[chatgpt] Model switch FAILED: wanted '{target_model}', got '{new_model}'")
                    return False
                break
        if not verified:
            logger.warning("[chatgpt] Could not verify model switch — proceeding")

    # Extended thinking (only for Pro model)
    thinking_time = config.get('thinking_time')
    if thinking_time and target_model == 'pro':
        time.sleep(1.0)
        elements = scan_elements('chatgpt')
        # Look for Extended Pro / Extended thinking button near input
        for e in elements:
            name = (e.get('name') or '').strip().lower()
            if 'button' in e.get('role', '') and 'extended' in name:
                _click_element(e)
                logger.info(f"[chatgpt] Enabled Extended Thinking: '{e.get('name')}'")
                break
        else:
            logger.warning("[chatgpt] Extended Thinking button not found — may already be active")

    return True


def setup_claude(cycle_type: str) -> bool:
    """Set Claude model for cycle type."""
    config = CYCLE_CONFIGS.get(cycle_type, {}).get('claude', {})
    target_model = config.get('model')
    if not target_model:
        logger.info("[claude] Using default model (no change)")
        return True

    elements = scan_elements('claude')

    # Find model selector button — Claude shows current model on a button
    # Look for buttons with model names
    selector = None
    for e in elements:
        name = (e.get('name') or '').strip().lower()
        if 'button' not in e.get('role', ''):
            continue
        # Claude model button typically has the model name or "Choose model"
        if any(kw in name for kw in ['sonnet', 'opus', 'haiku', 'extended', 'model', 'claude']):
            selector = e
            if target_model.lower() in name:
                logger.info(f"[claude] Already on target model: '{e.get('name')}'")
                return True
            break

    if not selector:
        # Try finding by looking at dropdown triggers
        for e in elements:
            name = (e.get('name') or '').strip().lower()
            if 'button' in e.get('role', '') and e.get('y', 0) > 0:
                if 'model' in name or 'selector' in name:
                    selector = e
                    break

    if not selector:
        logger.error("[claude] Model selector not found in elements")
        return False

    # Click to open model dropdown
    logger.info(f"[claude] Clicking model selector: '{selector.get('name')}'")
    _click_element(selector)
    time.sleep(1.5)

    # Find and click target model in dropdown
    if not _find_and_click_menu_item('claude', target_model):
        logger.error(f"[claude] Could not find '{target_model}' in dropdown")
        inp.press_key('Escape')
        return False

    time.sleep(1.0)
    logger.info(f"[claude] Model set to: {target_model}")
    return True


def setup_gemini(cycle_type: str) -> bool:
    """Set Gemini mode and enable Deep Think tool if needed."""
    config = CYCLE_CONFIGS.get(cycle_type, {}).get('gemini', {})
    target_mode = config.get('mode')
    target_tool = config.get('tool')

    # Mode selection (Fast/Thinking/Pro)
    if target_mode:
        elements = scan_elements('gemini')
        # Gemini mode picker is a button group, look for mode buttons
        mode_btn = None
        for e in elements:
            name = (e.get('name') or '').strip().lower()
            if 'button' not in e.get('role', ''):
                continue
            if any(kw in name for kw in ['fast', 'thinking', 'pro']):
                if target_mode.lower() in name:
                    # Check if already selected (check for 'pressed' state)
                    states = e.get('states', [])
                    if 'pressed' in states or 'checked' in states:
                        logger.info(f"[gemini] Mode already set: '{e.get('name')}'")
                    else:
                        _click_element(e)
                        logger.info(f"[gemini] Selected mode: '{e.get('name')}'")
                        time.sleep(1.0)
                    mode_btn = e
                    break

        if not mode_btn:
            logger.error(f"[gemini] Mode button for '{target_mode}' not found")
            return False

    # Tool selection (Deep Think)
    if target_tool:
        time.sleep(0.5)
        elements = scan_elements('gemini')

        # Find "Tools" button
        tools_btn = _find_button(elements, 'tools')
        if not tools_btn:
            # Try "tool" in case name varies
            tools_btn = _find_button(elements, 'tool')
        if not tools_btn:
            logger.error("[gemini] Tools button not found")
            return False

        _click_element(tools_btn)
        logger.info(f"[gemini] Clicked Tools button: '{tools_btn.get('name')}'")
        time.sleep(1.5)

        # Find Deep Think check menu item
        firefox = get_firefox('gemini')
        doc = get_doc('gemini', force_refresh=True)
        items = find_menu_items(firefox, doc)

        found_tool = False
        for item in (items or []):
            name = (item.get('name') or '').strip().lower()
            if target_tool.lower() in name:
                # Check if already enabled
                states = item.get('states', [])
                if 'checked' in states:
                    logger.info(f"[gemini] Tool already enabled: '{item.get('name')}'")
                else:
                    _click_element(item)
                    logger.info(f"[gemini] Enabled tool: '{item.get('name')}'")
                found_tool = True
                break

        if not found_tool:
            tool_names = [f"'{i.get('name', '')}'" for i in (items or [])[:8]]
            logger.error(f"[gemini] Tool '{target_tool}' not found. Available: {tool_names}")
            inp.press_key('Escape')
            return False

        # Close tools dropdown
        inp.press_key('Escape')
        time.sleep(0.5)

    return True


def setup_grok(cycle_type: str) -> bool:
    """Set Grok model for cycle type."""
    config = CYCLE_CONFIGS.get(cycle_type, {}).get('grok', {})
    target_model = config.get('model', 'auto')

    elements = scan_elements('grok')

    # Find model button — Grok has "Model select" or shows current model
    selector = None
    current = ''
    for e in elements:
        name = (e.get('name') or '').strip().lower()
        if 'button' not in e.get('role', ''):
            continue
        if any(kw in name for kw in ['model select', 'auto', 'fast', 'expert', 'heavy', 'grok']):
            selector = e
            current = name
            break

    if not selector:
        logger.error("[grok] Model selector not found")
        return False

    if target_model.lower() in current:
        logger.info(f"[grok] Already on target: '{selector.get('name')}'")
        return True

    # "Model select" without specific model name = default (auto)
    if current == 'model select' and target_model == 'auto':
        logger.info("[grok] 'Model select' = auto (default)")
        return True

    # Click model selector to open dropdown
    logger.info(f"[grok] Current: '{current}', switching to '{target_model}'")
    _click_element(selector)
    time.sleep(1.5)

    # Find target in dropdown via AT-SPI enum
    if not _find_and_click_menu_item('grok', target_model):
        # Keyboard nav fallback: model positions
        model_positions = {'auto': 0, 'fast': 1, 'expert': 2, 'heavy': 3}
        target_pos = model_positions.get(target_model.lower())
        if target_pos is not None:
            for _ in range(5):
                inp.press_key('Up')
                time.sleep(0.15)
            for _ in range(target_pos):
                inp.press_key('Down')
                time.sleep(0.3)
            inp.press_key('Return')
            time.sleep(1.0)
            logger.info(f"[grok] Selected '{target_model}' via keyboard nav")
        else:
            logger.error(f"[grok] Could not select '{target_model}'")
            inp.press_key('Escape')
            return False

    time.sleep(1.0)
    return True


def setup_perplexity(cycle_type: str) -> bool:
    """Set Perplexity tools (Deep Research) for cycle type."""
    config = CYCLE_CONFIGS.get(cycle_type, {}).get('perplexity', {})
    target_tool = config.get('tool')
    if not target_tool:
        logger.info("[perplexity] No tool changes needed")
        return True

    elements = scan_elements('perplexity')

    # Find "Add files or tools" button (the + button)
    tools_btn = _find_button(elements, 'add files or tools')
    if not tools_btn:
        tools_btn = _find_button(elements, 'add files')
    if not tools_btn:
        # Try any + button
        for e in elements:
            name = (e.get('name') or '').strip()
            if 'button' in e.get('role', '') and name in ('+', 'Add'):
                tools_btn = e
                break
    if not tools_btn:
        logger.error("[perplexity] 'Add files or tools' button not found")
        return False

    _click_element(tools_btn)
    logger.info(f"[perplexity] Clicked tools button: '{tools_btn.get('name')}'")
    time.sleep(1.5)

    # Find Deep Research radio item
    firefox = get_firefox('perplexity')
    doc = get_doc('perplexity', force_refresh=True)
    items = find_menu_items(firefox, doc)

    found = False
    for item in (items or []):
        name = (item.get('name') or '').strip().lower()
        if 'deep research' in name:
            states = item.get('states', [])
            if 'checked' in states:
                logger.info(f"[perplexity] Deep Research already enabled")
            else:
                _click_element(item)
                logger.info(f"[perplexity] Enabled Deep Research: '{item.get('name')}'")
            found = True
            break

    if not found:
        tool_names = [f"'{i.get('name', '')}'" for i in (items or [])[:8]]
        logger.error(f"[perplexity] 'Deep Research' not found. Available: {tool_names}")
        inp.press_key('Escape')
        return False

    # Close dropdown
    inp.press_key('Escape')
    time.sleep(0.5)
    return True


def setup_platform(platform: str, cycle_type: str) -> bool:
    """Dispatch to platform-specific setup. Returns False = HARD STOP."""
    dispatchers = {
        'chatgpt': setup_chatgpt,
        'claude': setup_claude,
        'gemini': setup_gemini,
        'grok': setup_grok,
        'perplexity': setup_perplexity,
    }
    fn = dispatchers.get(platform)
    if not fn:
        logger.error(f"Unknown platform: {platform}")
        return False
    return fn(cycle_type)


# ══════════════════════════════════════════════════════════════════════
# File attachment (reuses Xvfb-compatible approach from hmm_bot)
# ══════════════════════════════════════════════════════════════════════

def _find_dialog_wid() -> str:
    """Find GTK file dialog window ID."""
    for title in ['File Upload', 'Open', 'Open File']:
        try:
            r = subprocess.run(
                ['xdotool', 'search', '--name', title],
                capture_output=True, text=True, timeout=2,
            )
            if r.stdout.strip():
                return r.stdout.strip().split('\n')[-1]
        except Exception:
            pass
    return ''


def _handle_dialog(file_path: str) -> bool:
    """Handle GTK file dialog: focus → Ctrl+L → type path → Enter."""
    wid = _find_dialog_wid()
    if not wid:
        return False

    subprocess.run(['xdotool', 'windowactivate', '--sync', wid],
                   capture_output=True, timeout=3)
    time.sleep(0.5)
    inp.press_key('ctrl+l')
    time.sleep(0.5)
    inp.type_into_ui(file_path)
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(1.5)

    if not _find_dialog_wid():
        return True
    # GTK sometimes navigates to dir first
    inp.press_key('Return')
    time.sleep(1.0)
    return not _find_dialog_wid()


def attach_file(platform: str, file_path: str) -> bool:
    """Attach a file to the current conversation."""
    from tools.attach import (_close_stale_file_dialogs as close_stale,
                              _get_attach_button_coords as get_attach_btn)
    from core.interact import atspi_click

    if not os.path.exists(file_path):
        logger.error(f"[{platform}] File not found: {file_path}")
        return False

    close_stale()
    inp.press_key('Escape')
    time.sleep(0.3)

    # ChatGPT: Ctrl+U shortcut
    if platform == 'chatgpt':
        inp.focus_firefox()
        time.sleep(0.3)
        inp.click_at(960, 540)
        time.sleep(0.5)
        inp.press_key('ctrl+u')
        time.sleep(1.5)

    # Gemini: AT-SPI button → dropdown → "Upload files"
    elif platform == 'gemini':
        doc = get_doc(platform, force_refresh=True)
        if not doc:
            logger.error(f"[{platform}] No doc for attach")
            return False
        btn = get_attach_btn(doc, platform=platform)
        if not btn:
            logger.error(f"[{platform}] Attach button not found")
            return False
        _click_element(btn)
        time.sleep(1.5)
        if not _find_dialog_wid():
            _find_and_click_menu_item(platform, 'upload file')
            time.sleep(2.0)

    # Others: find attach button → keyboard nav
    else:
        doc = get_doc(platform, force_refresh=True)
        if not doc:
            # Try clicking input first to activate page
            input_el = find_input_field(platform)
            if input_el:
                inp.click_at(input_el['x'], input_el['y'])
                time.sleep(1.0)
                inp.press_key('Escape')
                time.sleep(0.3)
            doc = get_doc(platform, force_refresh=True)

        btn = get_attach_btn(doc, platform=platform) if doc else None
        if not btn:
            logger.error(f"[{platform}] Attach button not found")
            return False

        _click_element(btn)
        time.sleep(1.5)
        if not _find_dialog_wid():
            inp.press_key('Down')
            time.sleep(0.5)
            inp.press_key_split('Return')
            time.sleep(2.5)

    # Wait for dialog
    for _ in range(15):
        if _find_dialog_wid():
            break
        time.sleep(0.5)
    else:
        logger.error(f"[{platform}] File dialog never appeared")
        close_stale()
        return False

    # Handle dialog
    if _handle_dialog(file_path):
        logger.info(f"[{platform}] Attached: {os.path.basename(file_path)}")
        inp.focus_firefox()
        time.sleep(0.5)
        return True

    logger.error(f"[{platform}] File dialog did not close")
    close_stale()
    return False


# ══════════════════════════════════════════════════════════════════════
# Send message
# ══════════════════════════════════════════════════════════════════════

def find_input_field(platform: str) -> dict:
    """Find chat input field via AT-SPI."""
    doc = get_doc(platform)
    if not doc:
        return None
    elements = scan_elements(platform)
    chrome_y = detect_chrome_y(doc)

    for e in elements:
        if (e.get('role') == 'entry'
                and 'editable' in e.get('states', [])
                and e.get('y', 0) > chrome_y):
            return e

    for e in elements:
        if ('editable' in e.get('states', [])
                and e.get('y', 0) > chrome_y):
            return e

    for e in elements:
        if (e.get('role') in ('section', 'paragraph')
                and 'focusable' in e.get('states', [])
                and e.get('y', 0) > chrome_y):
            return e

    return None


def send_message(platform: str, message: str) -> bool:
    """Focus input → paste message → Enter. HARD STOP if input not found."""
    inp.focus_firefox()
    time.sleep(0.3)
    inp.press_key('Escape')
    time.sleep(0.3)

    input_el = None
    for attempt in range(5):
        input_el = find_input_field(platform)
        if input_el:
            break
        logger.info(f"[{platform}] Input not found, retry {attempt+1}/5...")
        time.sleep(2)

    if not input_el:
        logger.error(f"[{platform}] Input field NOT FOUND — aborting send")
        return False

    # Click + grab_focus (essential on Xvfb)
    inp.click_at(input_el['x'], input_el['y'])
    time.sleep(0.3)
    obj = input_el.get('atspi_obj')
    if obj:
        try:
            comp = obj.get_component_iface()
            if comp:
                comp.grab_focus()
        except Exception:
            pass
    time.sleep(0.3)

    inp.clipboard_paste(message)
    time.sleep(0.5)
    inp.press_key('Return')
    time.sleep(1.0)

    # Store for selection-based extraction (Xvfb fallback)
    _last_sent_message[platform] = message

    logger.info(f"[{platform}] Sent ({len(message)} chars)")
    return True


# ══════════════════════════════════════════════════════════════════════
# Response detection + extraction
# ══════════════════════════════════════════════════════════════════════

def wait_for_response(platform: str, timeout: int = 300) -> bool:
    """Wait for response using fixed-wait + extract probing.

    More reliable than stop-button polling on Xvfb where AT-SPI tree
    updates are inconsistent for background tabs.
    """
    start = time.time()
    # Audit/Dream cycles (Pro, Deep Think, Heavy) need longer initial wait
    initial_wait = min(60, timeout // 3)
    logger.info(f"[{platform}] Waiting {initial_wait}s for initial generation...")
    time.sleep(initial_wait)

    attempt = 0
    while time.time() - start < timeout:
        attempt += 1
        if not check_firefox_alive():
            logger.error(f"[{platform}] Firefox died")
            return False

        content = extract_response(platform)
        if content and len(content) > 10:
            logger.info(f"[{platform}] Response detected ({len(content)} chars, "
                        f"{time.time()-start:.0f}s)")
            return True

        logger.info(f"[{platform}] Attempt {attempt}, {time.time()-start:.0f}s elapsed...")
        time.sleep(15)

    logger.error(f"[{platform}] No response after {timeout}s")
    return False


def _extract_via_copy_button(platform: str) -> str:
    """Extract via Copy button click (works on physical displays)."""
    elements = scan_elements(platform)
    copy_buttons = find_copy_buttons(elements)

    if not copy_buttons:
        for _ in range(3):
            time.sleep(2)
            inp.press_key('End')
            time.sleep(1)
            elements = scan_elements(platform)
            copy_buttons = find_copy_buttons(elements)
            if copy_buttons:
                break

    if not copy_buttons:
        return ''

    response_copy = [b for b in copy_buttons
                     if (b.get('name') or '').strip().lower() == 'copy']
    target = (response_copy or copy_buttons)[-1]

    clipboard.write_marker('')
    time.sleep(0.1)
    subprocess.run(['pkill', '-f', 'xsel.*clipboard'], capture_output=True, timeout=3)
    time.sleep(0.1)

    from core.interact import atspi_click
    if target.get('atspi_obj') and atspi_click(target):
        logger.info(f"[{platform}] Copy via AT-SPI at ({target['x']}, {target['y']})")
    else:
        inp.click_at(target['x'], target['y'])
        logger.info(f"[{platform}] Copy via xdotool at ({target['x']}, {target['y']})")

    for _ in range(6):
        time.sleep(0.5)
        content = clipboard.read()
        if content:
            return content

    return ''


def _extract_via_selection(platform: str, sent_message: str = '') -> str:
    """Fallback: Ctrl+A + Ctrl+C, then parse response from full page content.

    Used on Xvfb where Copy button's navigator.clipboard.writeText() fails.
    NOTE: Do NOT kill xsel before Ctrl+C — xsel must be alive as clipboard
    owner for X11 selection to work. Ctrl+C overwrites xsel's content.
    """
    # Must re-focus Firefox — copy button attempts may have shifted focus
    inp.focus_firefox()
    time.sleep(0.5)
    # Click page content to ensure web content has focus (not browser chrome)
    inp.click_at(960, 600)
    time.sleep(0.3)

    # Write a marker so we can detect when Ctrl+C overwrites it
    clipboard.write_marker('__MARKER__')
    time.sleep(0.2)

    inp.press_key('ctrl+a')
    time.sleep(0.5)
    inp.press_key('ctrl+c')
    time.sleep(1.5)

    content = clipboard.read()
    if not content or content == '__MARKER__':
        logger.warning(f"[{platform}] Ctrl+A+C failed to capture page content")
        return ''

    # Click to deselect
    inp.click_at(960, 600)
    time.sleep(0.2)

    # Parse: find response section after user message
    # Full page content has: [UI elements] [user message] [response] [footer]
    if sent_message:
        # Find the user message in the content
        msg_short = sent_message.strip()[:100]
        idx = content.find(msg_short)
        if idx >= 0:
            after_msg = content[idx + len(msg_short):].strip()
            # Strip common footer patterns
            for footer in ['\nUpgrade to', '\nNew conversation', '\nStart a new',
                           '\nGrok can make mistakes', '\nChatGPT can make mistakes',
                           '\nClaude can make mistakes', '\nPerplexity',
                           '\nSign up', '\nLog in', '\nTerms']:
                fi = after_msg.find(footer)
                if fi > 0:
                    after_msg = after_msg[:fi]
            # Strip timing info (e.g. "1.4s\n" at the end)
            import re
            after_msg = re.sub(r'\n\d+\.?\d*s\s*$', '', after_msg.strip())
            if after_msg:
                logger.info(f"[{platform}] Extracted via selection ({len(after_msg)} chars)")
                return after_msg.strip()

    # If parsing failed, return raw content (caller can try to use it)
    logger.warning(f"[{platform}] Could not parse response from selection ({len(content)} chars)")
    return ''


# Store sent message for selection-based extraction
_last_sent_message = {}


def extract_response(platform: str) -> str:
    """Extract latest response. Tries Copy button first, falls back to selection on Xvfb."""
    inp.focus_firefox()
    time.sleep(0.3)
    inp.press_key('End')
    time.sleep(0.5)

    doc = get_doc(platform, force_refresh=True)
    if not doc:
        return ''

    # Method 1: Copy button (works on physical displays)
    content = _extract_via_copy_button(platform)
    if content:
        return content

    # Method 2: Ctrl+A + Ctrl+C selection (Xvfb fallback)
    logger.info(f"[{platform}] Copy button failed — trying Ctrl+A+C selection")
    sent_msg = _last_sent_message.get(platform, '')
    return _extract_via_selection(platform, sent_msg)


# ══════════════════════════════════════════════════════════════════════
# Main cycle
# ══════════════════════════════════════════════════════════════════════

def run_cycle(cycle_type: str, platform: str, message: str,
              attachments: list = None, timeout: int = None) -> dict:
    """Run a complete cycle: navigate → setup → attach → send → wait → extract.

    Returns dict with 'success', 'response', 'error', 'elapsed'.
    HARD STOP on any failure — no retries.
    """
    if cycle_type not in CYCLE_CONFIGS:
        return {'success': False, 'error': f"Unknown cycle type: {cycle_type}",
                'platform': platform}

    if platform not in FRESH_URLS:
        return {'success': False, 'error': f"Unknown platform: {platform}",
                'platform': platform}

    if timeout is None:
        timeout = TIMEOUTS.get(cycle_type, 300)

    start = time.time()
    result = {'success': False, 'platform': platform, 'cycle_type': cycle_type,
              'error': None, 'response': None}

    # Step 0: Cleanup
    clipboard.kill_stale_xsel()
    from tools.attach import _close_stale_file_dialogs as close_stale
    close_stale()

    # Step 1: Navigate to fresh session
    logger.info(f"[{platform}] === {cycle_type.upper()} CYCLE START ===")
    if not navigate_fresh(platform):
        result['error'] = 'navigate_failed'
        return result

    # Step 2: Setup model/mode for cycle type — HARD STOP on failure
    logger.info(f"[{platform}] Setting up for {cycle_type}...")
    if not setup_platform(platform, cycle_type):
        result['error'] = 'setup_failed'
        return result

    # Step 3: Attach files — HARD STOP on failure
    for path in (attachments or []):
        logger.info(f"[{platform}] Attaching: {os.path.basename(path)}")
        if not attach_file(platform, path):
            result['error'] = f'attach_failed: {path}'
            return result
        time.sleep(3)

    # Step 4: Send message — HARD STOP on failure
    logger.info(f"[{platform}] Sending message...")
    if not send_message(platform, message):
        result['error'] = 'send_failed'
        return result

    # Step 5: Wait for response — HARD STOP on timeout
    logger.info(f"[{platform}] Waiting for response (timeout: {timeout}s)...")
    if not wait_for_response(platform, timeout):
        result['error'] = 'response_timeout'
        return result

    # Step 6: Extract response
    time.sleep(2)
    response = extract_response(platform)
    if not response:
        result['error'] = 'extract_failed'
        return result

    elapsed = int(time.time() - start)
    result['success'] = True
    result['response'] = response
    result['elapsed'] = elapsed
    result['response_length'] = len(response)

    logger.info(f"[{platform}] === {cycle_type.upper()} CYCLE COMPLETE === "
                f"({len(response)} chars, {elapsed}s)")
    return result


def run_multi(cycle_type: str, platforms: list, message: str,
              attachments: list = None, timeout: int = None) -> dict:
    """Run cycle across multiple platforms sequentially."""
    results = {}
    for platform in platforms:
        if not check_firefox_alive():
            escalate(f"Firefox died during {cycle_type} cycle on {platform}")
            break
        try:
            results[platform] = run_cycle(cycle_type, platform, message,
                                          attachments, timeout)
        except Exception as e:
            logger.error(f"[{platform}] Unhandled error: {e}")
            results[platform] = {'success': False, 'platform': platform,
                                 'error': f'exception: {e}'}
    return results


def main():
    parser = argparse.ArgumentParser(description='Chat cycle bot')
    parser.add_argument('--platform', nargs='+', required=True,
                        choices=list(FRESH_URLS.keys()),
                        help='Platform(s) to run on')
    parser.add_argument('--cycle-type', required=True,
                        choices=list(CYCLE_CONFIGS.keys()),
                        help='Cycle type')
    parser.add_argument('--message', help='Message to send')
    parser.add_argument('--message-file', help='Read message from file')
    parser.add_argument('--attach', nargs='+', help='File(s) to attach')
    parser.add_argument('--timeout', type=int, help='Response timeout seconds')
    parser.add_argument('--output', help='Save responses to this directory')
    args = parser.parse_args()

    # Get message
    if args.message_file:
        with open(args.message_file) as f:
            message = f.read()
    elif args.message:
        message = args.message
    else:
        logger.error("Must provide --message or --message-file")
        sys.exit(1)

    logger.info(f"Cycle bot starting — type={args.cycle_type}, "
                f"platforms={args.platform}, msg={len(message)} chars")

    if not check_firefox_alive():
        logger.error("Firefox not running — cannot proceed")
        escalate("cycle_bot: Firefox not running at startup")
        sys.exit(1)

    results = run_multi(args.cycle_type, args.platform, message,
                        args.attach, args.timeout)

    # Save results
    if args.output:
        os.makedirs(args.output, exist_ok=True)
        for platform, result in results.items():
            path = os.path.join(args.output, f"{platform}_{args.cycle_type}.json")
            with open(path, 'w') as f:
                json.dump(result, f, indent=2)
            if result.get('response'):
                txt_path = os.path.join(args.output, f"{platform}_{args.cycle_type}.txt")
                with open(txt_path, 'w') as f:
                    f.write(result['response'])

    # Summary
    for platform, result in results.items():
        status = 'OK' if result['success'] else f"FAIL: {result.get('error')}"
        chars = result.get('response_length', 0)
        elapsed = result.get('elapsed', 0)
        logger.info(f"[{platform}] {status} ({chars} chars, {elapsed}s)")

    # Exit code: 0 if all succeeded
    if all(r['success'] for r in results.values()):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
