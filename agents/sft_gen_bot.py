#!/usr/bin/env python3
"""sft_gen_bot.py — SFT/DPO training data generation via hmm_bot's proven functions.

Uses hmm_bot's navigate, attach, send, wait — the same code that ran
123K+ HMM enrichments successfully on virtual displays.

Platform-specific extraction:
  - ChatGPT: "Copy response" button (distinct from "Copy message")
  - Claude: "Scroll to bottom" → "Copy" button (appears after scroll)
  - Gemini/Grok/Perplexity: standard hmm_bot.extract_response

Usage:
    DISPLAY=:5 python3 agents/sft_gen_bot.py --round sft --platforms chatgpt
    DISPLAY=:6 python3 agents/sft_gen_bot.py --round dpo --platforms gemini
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

SUPPORTED_PLATFORMS = ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity']

SFT_PACKAGE = '/tmp/sft_package.md'
DPO_PACKAGE = '/tmp/dpo_package.md'
SFT_PROMPT = '/tmp/sft_generation_prompt.md'
DPO_PROMPT = '/tmp/dpo_generation_prompt.md'
SFT_OUTPUT_DIR = '/var/spark/isma/training/sft'
DPO_OUTPUT_DIR = '/var/spark/isma/training/dpo'


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


def _extract_response(platform):
    """Platform-specific extraction. Returns content string or empty."""
    import agents.hmm_bot as bot
    from core.tree import find_elements
    from core.interact import atspi_click
    from core import input as inp

    subprocess.run(['pkill', '-f', 'xsel.*clipboard'], capture_output=True, timeout=3)
    time.sleep(0.3)

    inp.focus_firefox()
    time.sleep(0.3)

    ff = bot.get_firefox(platform)
    if not ff:
        log.error(f"[{platform}] No Firefox found for extraction")
        return ''

    # Scroll to bottom aggressively
    for _ in range(15):
        inp.press_key('End')
        time.sleep(0.3)
    time.sleep(2)

    els = find_elements(ff)

    if platform == 'chatgpt':
        # ChatGPT: click "Copy response" (NOT "Copy message" which copies the prompt)
        # Button only appears on mouse hover — try multiple positions
        display = os.environ.get('DISPLAY', ':0')
        for attempt in range(3):
            for y in [300, 400, 500, 600]:
                subprocess.run(['xdotool', 'mousemove', '700', str(y)],
                             env={**os.environ, 'DISPLAY': display}, timeout=3)
                time.sleep(1)
                els_now = find_elements(ff)
                for e in els_now:
                    name = (e.get('name') or '').strip()
                    if 'Copy response' in name and e.get('role') == 'push button':
                        log.info(f"[{platform}] Clicking '{name}' (hover y={y})")
                        atspi_click(e) if e.get('atspi_obj') else inp.click_at(e['x'], e['y'])
                        time.sleep(2)
                        from core.clipboard import read as clip_read
                        return clip_read() or ''
            log.info(f"[{platform}] No Copy response on attempt {attempt+1} — scrolling more")
            for _ in range(10):
                inp.press_key('End')
                time.sleep(0.3)
            time.sleep(1)
        log.warning(f"[{platform}] No 'Copy response' button found after 3 attempts")

    elif platform == 'claude':
        # Claude: click "Scroll to bottom" → hover → retry to find Copy button
        for attempt in range(3):
            els_now = find_elements(ff)
            for e in els_now:
                name = (e.get('name') or '').strip()
                if name == 'Scroll to bottom' and e.get('role') == 'push button':
                    log.info(f"[{platform}] Clicking 'Scroll to bottom' (attempt {attempt+1})")
                    atspi_click(e) if e.get('atspi_obj') else inp.click_at(e['x'], e['y'])
                    break
            time.sleep(2)
            # Hover over response area to trigger Copy button
            subprocess.run(['xdotool', 'mousemove', '500', '500'],
                         env={**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':0')}, timeout=3)
            time.sleep(2)
            # Re-scan for Copy
            els2 = find_elements(ff)
            for e in els2:
                name = (e.get('name') or '').strip()
                if name == 'Copy' and e.get('role') == 'push button':
                    log.info(f"[{platform}] Clicking 'Copy' at y={e.get('y')}")
                    atspi_click(e) if e.get('atspi_obj') else inp.click_at(e['x'], e['y'])
                    time.sleep(2)
                    from core.clipboard import read as clip_read
                    return clip_read() or ''
            # Check for Download button (Claude attachment fallback)
            for e in els2:
                name = (e.get('name') or '').strip()
                if name == 'Download' and e.get('role') == 'push button':
                    log.info(f"[{platform}] Clicking 'Download' (attachment fallback)")
                    atspi_click(e) if e.get('atspi_obj') else inp.click_at(e['x'], e['y'])
                    time.sleep(3)
                    dl_dir = os.path.expanduser('~/Downloads')
                    if os.path.isdir(dl_dir):
                        files = sorted(
                            [f for f in os.listdir(dl_dir) if f.endswith('.jsonl')],
                            key=lambda f: os.path.getmtime(os.path.join(dl_dir, f)),
                            reverse=True,
                        )
                        if files:
                            path = os.path.join(dl_dir, files[0])
                            if time.time() - os.path.getmtime(path) < 30:
                                with open(path) as f:
                                    return f.read()
            log.info(f"[{platform}] Attempt {attempt+1}: no Copy/Download yet")
        log.warning(f"[{platform}] No Copy or Download button found after 3 attempts")

    else:
        # Gemini, Grok, Perplexity: standard hmm_bot extraction
        return bot.extract_response(platform) or ''

    return ''


def _parse_jsonl(content):
    """Parse JSONL content, handling Perplexity S3 URLs and markdown fences."""
    lines = content.strip().split('\n')
    valid = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('```'):
            continue
        # Perplexity appends S3 citation URLs after the JSON
        if line.startswith('{'):
            bracket_end = line.rfind(']}')
            if bracket_end > 0:
                line = line[:bracket_end + 2]
        try:
            obj = json.loads(line)
            valid.append(obj)
        except json.JSONDecodeError:
            continue
    return valid


def process_platform(platform, package_path, prompt_path, output_dir):
    """Full cycle using hmm_bot's proven functions."""
    display = os.environ.get('DISPLAY', ':0')
    dbus = os.environ.get('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')

    log.info(f"[{platform}] Starting on {display}")

    # Set display for core modules
    os.environ['DISPLAY'] = display
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = dbus
    from core.input import set_display as inp_set
    from core.clipboard import set_display as clip_set
    inp_set(display)
    clip_set(display)

    # Set hmm_bot's PID filter — this is what makes shared D-Bus work
    import agents.hmm_bot as bot
    target_pid = _get_firefox_pid_for_display(display)
    if not target_pid:
        log.error(f"[{platform}] No Firefox PID found for {display}")
        return False
    bot._our_firefox_pid = target_pid
    bot._cached_firefox.clear()
    bot._cached_doc.clear()
    log.info(f"[{platform}] PID filter set: {target_pid}")

    # Read prompt
    with open(prompt_path) as f:
        prompt_text = f.read()

    # Step 1: Navigate to fresh session
    log.info(f"[{platform}] Navigating to fresh session")
    if not bot.navigate_fresh_session(platform):
        log.error(f"[{platform}] Navigation failed")
        return False
    log.info(f"[{platform}] Navigation OK")

    # Step 2: Attach package
    log.info(f"[{platform}] Attaching {os.path.basename(package_path)}")
    if not bot.attach_file(platform, package_path):
        log.error(f"[{platform}] Attach failed")
        return False
    log.info(f"[{platform}] Attach OK")

    # Step 3: Send prompt
    log.info(f"[{platform}] Sending prompt ({len(prompt_text)} chars)")
    if not bot.send_prompt(platform, prompt_text):
        log.error(f"[{platform}] Send failed")
        return False
    log.info(f"[{platform}] Prompt sent")

    # ChatGPT: Return doesn't always send with file attachments.
    # Click "Send prompt" button as backup if it's still visible.
    if platform == 'chatgpt':
        time.sleep(1)
        from core.tree import find_elements
        from core.interact import atspi_click
        ff = bot.get_firefox(platform)
        if ff:
            els = find_elements(ff)
            for e in els:
                n = (e.get('name') or '').strip()
                if n == 'Send prompt' and e.get('role') == 'push button':
                    log.info(f"[{platform}] Send button still visible — clicking it")
                    atspi_click(e) if e.get('atspi_obj') else bot.inp.click_at(e['x'], e['y'])
                    time.sleep(1)
                    break

    # Step 4: Wait for response
    # Claude Opus takes 15-25 min for 100 JSONL items — needs longer timeout
    wait_timeout = 1800 if platform == 'claude' else 600
    log.info(f"[{platform}] Waiting for response (timeout={wait_timeout}s)...")
    if not bot.wait_for_response(platform, timeout=wait_timeout):
        log.warning(f"[{platform}] Wait timed out — trying extract anyway")

    # Step 5: Extract response (platform-specific)
    log.info(f"[{platform}] Extracting response")
    content = _extract_response(platform)
    if not content or len(content) < 100:
        log.error(f"[{platform}] Extract failed — got {len(content) if content else 0} chars")
        return False
    log.info(f"[{platform}] Extracted {len(content)} chars")

    # Step 6: Parse and save JSONL
    os.makedirs(output_dir, exist_ok=True)
    valid = _parse_jsonl(content)

    round_name = 'sft' if 'sft' in output_dir.lower() else 'dpo'
    # Append to cumulative file (never overwrite previous rounds)
    output_path = os.path.join(output_dir, f'{round_name}_{platform}.jsonl')
    with open(output_path, 'a') as f:
        for obj in valid:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n')

    # Also save this round's raw response with timestamp
    ts = time.strftime('%Y%m%d_%H%M%S')
    raw_path = os.path.join(output_dir, f'{round_name}_{platform}_{ts}_raw.md')
    with open(raw_path, 'w') as f:
        f.write(content)

    # Count total accumulated
    total = 0
    try:
        with open(output_path) as f:
            total = sum(1 for _ in f)
    except: pass

    log.info(f"[{platform}] Saved {len(valid)} items (total accumulated: {total}) → {output_path}")

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
            log.error(f"[{platform}] Exception: {e}", exc_info=True)
            results[platform] = f'ERROR: {e}'

    log.info("=== Results ===")
    for p, r in results.items():
        log.info(f"  {p}: {r}")
    log.info(f"Output in {output_dir}/")


if __name__ == '__main__':
    main()
