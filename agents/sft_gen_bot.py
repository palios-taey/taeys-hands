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
    """Extract response using hmm_bot.extract_response for all platforms.
    Claude gets extra scroll-to-bottom handling."""
    import agents.hmm_bot as bot
    from core import input as inp

    # Scroll to bottom
    inp.focus_firefox()
    time.sleep(0.3)
    for _ in range(20):
        inp.press_key('End')
        time.sleep(0.3)
    time.sleep(2)

    if platform == 'claude':
        # Claude: Scroll to bottom → find last Copy button → click → read
        # hmm_bot.extract_response doesn't work for Claude because its
        # own End key press scrolls back up, hiding the Copy button
        from core.tree import find_elements
        from core.interact import atspi_click
        from core.clipboard import read as clip_read

        ff = bot.get_firefox(platform)
        if not ff:
            return ''

        subprocess.run(['pkill', '-9', 'xsel'], capture_output=True, timeout=3)
        time.sleep(0.3)

        # Click "Scroll to bottom" button
        els = find_elements(ff)
        for e in els:
            if (e.get('name') or '').strip() == 'Scroll to bottom':
                atspi_click(e) if e.get('atspi_obj') else inp.click_at(e['x'], e['y'])
                log.info("[claude] Clicked 'Scroll to bottom'")
                time.sleep(2)
                break

        # Find last Copy button and click it
        els = find_elements(ff)
        copies = [e for e in els if (e.get('name') or '').strip() == 'Copy'
                  and e.get('role') == 'push button']
        if copies:
            target = copies[-1]
            log.info(f"[claude] Clicking 'Copy' at y={target.get('y')} ({len(copies)} found)")
            subprocess.run(['pkill', '-9', 'xsel'], capture_output=True, timeout=3)
            time.sleep(0.3)
            atspi_click(target) if target.get('atspi_obj') else inp.click_at(target['x'], target['y'])
            time.sleep(2)
            return clip_read() or ''
        log.warning("[claude] No Copy button found after Scroll to bottom")
        return ''

    # All other platforms: hmm_bot.extract_response (proven)
    return bot.extract_response(platform) or ''


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
    # Patch core.atspi so ALL code paths use our PID-filtered Firefox
    import core.atspi as _atspi
    _orig_find = _atspi.find_firefox_for_platform
    def _pid_find(platform_name=None, **kwargs):
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
        return _orig_find(platform_name)
    _atspi.find_firefox_for_platform = _pid_find
    if hasattr(_atspi, 'find_firefox'):
        _atspi.find_firefox = _pid_find

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

    # Verify send: if a send/submit button is still visible, Return didn't
    # trigger send (common with file attachments). Click it directly.
    time.sleep(1)
    from core.tree import find_elements as _fe
    from core.interact import atspi_click as _ac2
    ff = bot.get_firefox(platform)
    if ff:
        els = _fe(ff)
        send_names = ['Send prompt', 'Send', 'Submit']
        for e in els:
            n = (e.get('name') or '').strip()
            if n in send_names and e.get('role') == 'push button':
                log.info(f"[{platform}] Send button '{n}' still visible — clicking")
                _ac2(e) if e.get('atspi_obj') else bot.inp.click_at(e['x'], e['y'])
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
    ts = time.strftime('%Y%m%d_%H%M%S')

    # Each run creates a new file: sft_{platform}_{timestamp}.jsonl
    # Training pipeline reads all files in the directory
    output_path = os.path.join(output_dir, f'{round_name}_{platform}_{ts}.jsonl')
    with open(output_path, 'w') as f:
        for obj in valid:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n')

    # Save raw response too
    raw_path = os.path.join(output_dir, f'{round_name}_{platform}_{ts}_raw.md')
    with open(raw_path, 'w') as f:
        f.write(content)

    log.info(f"[{platform}] Saved {len(valid)} items → {output_path}")

    # Sync to Mira — training pipeline reads from Mira's /var/spark/isma/training/sft/
    try:
        mira_dir = f"mira@10.0.0.163:{output_dir}/"
        subprocess.run(['scp', output_path, mira_dir], capture_output=True, timeout=30)
        log.info(f"[{platform}] Synced to Mira")
    except Exception as e:
        log.warning(f"[{platform}] Mira sync failed: {e}")

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

    # Notify via Redis on failures
    failures = {p: r for p, r in results.items() if r != 'OK'}
    if failures:
        try:
            import redis
            rc = redis.Redis(host=os.environ.get('REDIS_HOST', '10.0.0.163'),
                           port=6379, decode_responses=True, socket_timeout=2)
            display = os.environ.get('DISPLAY', ':?')
            notif = json.dumps({
                'type': 'sft_error',
                'display': display,
                'failures': failures,
                'message': f"SFT failures on {display}: {failures}",
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            })
            rc.rpush('taey:taeys-hands:notifications', notif)
        except Exception:
            pass


if __name__ == '__main__':
    main()
