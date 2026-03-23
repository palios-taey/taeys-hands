#!/usr/bin/env python3
"""sft_gen_bot.py — Send SFT/DPO generation prompts to all 5 platforms on Thor.

Uses tools/attach.py and tools/send.py directly (proven MCP tool functions).
One platform per display, sequential processing.

Usage:
    # SFT round (100 Q&A pairs per platform)
    python3 agents/sft_gen_bot.py --round sft

    # DPO round (50 preference pairs per platform)
    python3 agents/sft_gen_bot.py --round dpo
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [sft-gen] %(message)s')
log = logging.getLogger('sft-gen')

# Supported platforms — display comes from DISPLAY env var (set by launch_sft.sh)
SUPPORTED_PLATFORMS = ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity']

DBUS = 'unix:path=/run/user/1000/bus'
REDIS_HOST = os.environ.get('REDIS_HOST', '10.0.0.163')

SFT_PACKAGE = '/tmp/sft_package.md'
DPO_PACKAGE = '/tmp/dpo_package.md'
SFT_PROMPT = '/tmp/sft_generation_prompt.md'
DPO_PROMPT = '/tmp/dpo_generation_prompt.md'
SFT_OUTPUT_DIR = '/tmp/sft_output'
DPO_OUTPUT_DIR = '/tmp/dpo_output'


def set_display(display):
    """Set DISPLAY for AT-SPI operations."""
    os.environ['DISPLAY'] = display
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = DBUS
    from core.input import set_display as inp_set
    from core.clipboard import set_display as clip_set
    inp_set(display)
    clip_set(display)


def _get_firefox_pid_for_display(display):
    """Find Firefox PID running on a specific DISPLAY via /proc."""
    for pid_str in os.listdir('/proc'):
        if not pid_str.isdigit():
            continue
        try:
            with open(f'/proc/{pid_str}/environ', 'rb') as f:
                env = f.read().decode('utf-8', errors='replace')
            with open(f'/proc/{pid_str}/cmdline', 'rb') as f:
                cmdline = f.read().decode('utf-8', errors='replace')
            if 'firefox' not in cmdline:
                continue
            env_vars = dict(
                v.split('=', 1) for v in env.split('\0') if '=' in v
            )
            if env_vars.get('DISPLAY') == display:
                return int(pid_str)
        except (PermissionError, FileNotFoundError, ValueError):
            continue
    return None


def _patch_find_firefox(display):
    """Monkey-patch core.atspi.find_firefox to filter by display PID.

    With shared D-Bus, all Firefox instances are visible. This ensures
    we only return the one running on our display.
    """
    import core.atspi as atspi_mod
    target_pid = _get_firefox_pid_for_display(display)
    if not target_pid:
        log.warning(f"No Firefox PID found for {display}")
        return

    log.info(f"PID filter: Firefox on {display} = PID {target_pid}")
    original_find = atspi_mod.find_firefox_for_platform

    def filtered_find(platform_name=None, **kwargs):
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            try:
                if app.get_process_id() == target_pid:
                    return app
            except Exception:
                continue
        return original_find(platform_name)

    atspi_mod.find_firefox_for_platform = filtered_find
    # Also patch the bare find_firefox if it exists
    if hasattr(atspi_mod, 'find_firefox'):
        atspi_mod.find_firefox = filtered_find


_STOP_PATTERNS = {'stop generating', 'cancel', 'stop', 'stop response', 'cancel response'}


def _check_stop_button(firefox_app, platform):
    """Check if stop/cancel button is visible using our PID-filtered Firefox.

    Avoids importing from hmm_bot (which uses its own cached Firefox refs).
    """
    if not firefox_app:
        return False
    try:
        from core.tree import find_elements
        from core.atspi import get_platform_document
        doc = get_platform_document(firefox_app, platform) or firefox_app
        elements = find_elements(doc)
        for e in elements:
            name = (e.get('name') or '').strip().lower()
            if not name or len(name) > 50:
                continue
            if 'button' not in e.get('role', ''):
                continue
            if name in _STOP_PATTERNS:
                return True
        return False
    except Exception as ex:
        log.debug(f"Stop button check error: {ex}")
        return False


def process_platform(platform, package_path, prompt_path, output_dir):
    """Full cycle: attach → send → wait → extract → save."""
    display = os.environ.get('DISPLAY', ':0')

    log.info(f"[{platform}] Starting on {display}")
    set_display(display)
    _patch_find_firefox(display)

    # Import after setting display
    from core.atspi import find_firefox, get_platform_document
    from core.tree import find_elements, find_copy_buttons, filter_useful_elements
    from core.input import focus_firefox, click_at, clipboard_paste, press_key
    from tools.attach import handle_attach

    # Read prompt text
    with open(prompt_path) as f:
        prompt_text = f.read()

    # Step 1: Navigate to fresh session
    log.info(f"[{platform}] Navigating to fresh session")
    focus_firefox()
    time.sleep(0.5)
    press_key('ctrl+l')
    time.sleep(0.5)

    urls = {
        'chatgpt': 'https://chatgpt.com/?temporary-chat=true',
        'claude': 'https://claude.ai/new',
        'gemini': 'https://gemini.google.com/app',
        'grok': 'https://grok.com/',
        'perplexity': 'https://www.perplexity.ai/',
    }
    clipboard_paste(urls[platform])
    time.sleep(0.3)
    press_key('Return')
    time.sleep(8)

    # Step 2: Attach package
    log.info(f"[{platform}] Attaching {os.path.basename(package_path)}")
    result = handle_attach(platform, package_path, None)

    if result.get('status') == 'dropdown_open':
        # Click upload files item
        items = result.get('dropdown_items', [])
        for item in items:
            if 'upload' in item.get('name', '').lower():
                click_at(int(item['x']), int(item['y']))
                time.sleep(1)
                result = handle_attach(platform, package_path, None)
                break

    status = result.get('status', '')
    if status in ('file_attached', 'already_attached', 'unverified'):
        log.info(f"[{platform}] Attach status: {status} (proceeding)")
    else:
        log.error(f"[{platform}] Attach failed: {result}")
        return False

    log.info(f"[{platform}] File attached")
    time.sleep(2)

    # Step 3: Find input and send prompt
    log.info(f"[{platform}] Sending prompt ({len(prompt_text)} chars)")
    ff = find_firefox(platform)
    doc = get_platform_document(ff, platform) if ff else None
    if not doc:
        # Single-tab display: search entire Firefox app tree
        log.warning(f"[{platform}] No document by URL match — using full app tree")
        doc = ff
    if not doc:
        log.error(f"[{platform}] No Firefox found")
        return False

    elements = find_elements(doc)
    useful = filter_useful_elements(elements)

    # Find input — multiple strategies (ChatGPT ProseMirror doesn't expose editable)
    input_el = None
    # Priority 1: editable entry
    for e in useful:
        if e.get('role') == 'entry' and 'editable' in str(e.get('states', [])):
            input_el = e
            break
    # Priority 2: any editable
    if not input_el:
        for e in useful:
            if 'editable' in str(e.get('states', [])) and e.get('y', 0) > 100:
                input_el = e
                break
    # Priority 3: focusable section/paragraph (ChatGPT ProseMirror, Grok)
    if not input_el:
        for e in useful:
            if (e.get('role') in ('section', 'paragraph')
                    and 'focusable' in str(e.get('states', []))
                    and e.get('y', 0) > 100):
                input_el = e
                break

    if not input_el:
        log.error(f"[{platform}] No input field found in {len(useful)} elements")
        return False

    log.info(f"[{platform}] Input found: role={input_el.get('role')} at ({input_el['x']}, {input_el['y']})")
    click_at(input_el['x'], input_el['y'])
    time.sleep(0.3)
    # grab_focus for proper AT-SPI focus (essential on Xvfb)
    obj = input_el.get('atspi_obj')
    if obj:
        try:
            comp = obj.get_component_iface()
            if comp:
                comp.grab_focus()
        except Exception:
            pass
    time.sleep(0.3)

    # Paste prompt
    clipboard_paste(prompt_text)
    time.sleep(0.5)
    press_key('Return')
    log.info(f"[{platform}] Prompt sent")

    # Step 4: Wait for response (stop button polling)
    log.info(f"[{platform}] Waiting for response...")

    if platform == 'chatgpt':
        # ChatGPT AT-SPI tree hangs during generation — use fixed wait
        log.info(f"[{platform}] ChatGPT: fixed wait (300s) instead of stop-button polling")
        time.sleep(300)
    else:
        start = time.time()
        timeout = 600
        phase = 'waiting'

        while time.time() - start < timeout:
            has_stop = _check_stop_button(ff, platform)

            if phase == 'waiting':
                if has_stop:
                    log.info(f"[{platform}] Stop button appeared — generating")
                    phase = 'generating'
                elif time.time() - start > 120:
                    log.warning(f"[{platform}] No stop button after 120s")
                    return False
            elif phase == 'generating':
                if not has_stop:
                    log.info(f"[{platform}] Stop button gone — settling")
                    time.sleep(3)
                    if not _check_stop_button(ff, platform):
                        log.info(f"[{platform}] Response complete ({time.time()-start:.0f}s)")
                        break

            time.sleep(5)
        else:
            log.warning(f"[{platform}] Timeout after {timeout}s")
            return False

    time.sleep(2)

    # Step 5: Extract response
    log.info(f"[{platform}] Extracting response")
    press_key('End')
    time.sleep(1)

    ff = find_firefox(platform)
    doc = get_platform_document(ff, platform) if ff else None
    if not doc:
        doc = ff
    elements = find_elements(doc) if doc else []
    copy_buttons = find_copy_buttons(elements)

    if not copy_buttons:
        # Retry
        time.sleep(3)
        press_key('End')
        time.sleep(1)
        doc = get_platform_document(ff, platform) or ff
        elements = find_elements(doc) if doc else []
        copy_buttons = find_copy_buttons(elements)

    if not copy_buttons:
        log.error(f"[{platform}] No copy buttons found")
        return False

    # Kill xsel, click copy, read clipboard
    subprocess.run(['pkill', '-f', 'xsel.*clipboard'], capture_output=True, timeout=3)
    time.sleep(0.3)

    from core.interact import atspi_click
    target = copy_buttons[-1]
    if target.get('atspi_obj') and atspi_click(target):
        log.info(f"[{platform}] Clicked copy via AT-SPI")
    else:
        click_at(target['x'], target['y'])

    time.sleep(2)

    from core.clipboard import read as clip_read
    content = clip_read()
    if not content or len(content) < 100:
        log.error(f"[{platform}] Clipboard empty or too short")
        return False

    log.info(f"[{platform}] Extracted {len(content)} chars")

    # Step 6: Parse and save JSONL
    os.makedirs(output_dir, exist_ok=True)

    lines = content.strip().split('\n')
    valid = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('```'):
            continue
        try:
            obj = json.loads(line)
            valid.append(obj)
        except json.JSONDecodeError:
            continue

    round_name = 'sft' if 'sft' in output_dir.lower() else 'dpo'
    output_path = os.path.join(output_dir, f'{round_name}_{platform}.jsonl')

    with open(output_path, 'w') as f:
        for obj in valid:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n')

    log.info(f"[{platform}] Saved {len(valid)} items to {output_path}")

    # Also save raw response
    raw_path = os.path.join(output_dir, f'{round_name}_{platform}_raw.md')
    with open(raw_path, 'w') as f:
        f.write(content)

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--round', required=True, choices=['sft', 'dpo'])
    parser.add_argument('--platforms', nargs='+', default=SUPPORTED_PLATFORMS)
    args = parser.parse_args()

    if args.round == 'sft':
        package = SFT_PACKAGE
        prompt = SFT_PROMPT
        output_dir = SFT_OUTPUT_DIR
    else:
        package = DPO_PACKAGE
        prompt = DPO_PROMPT
        output_dir = DPO_OUTPUT_DIR

    log.info(f"Starting {args.round.upper()} generation on {args.platforms}")

    results = {}
    for platform in args.platforms:
        if platform not in SUPPORTED_PLATFORMS:
            log.error(f"Unknown platform: {platform}")
            continue

        try:
            ok = process_platform(platform, package, prompt, output_dir)
            results[platform] = 'OK' if ok else 'FAILED'
        except Exception as e:
            log.error(f"[{platform}] Exception: {e}")
            results[platform] = f'ERROR: {e}'

    log.info("=== Results ===")
    for p, r in results.items():
        log.info(f"  {p}: {r}")

    # Copy results to Mira
    log.info(f"Output in {output_dir}/")


if __name__ == '__main__':
    main()
