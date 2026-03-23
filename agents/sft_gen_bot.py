#!/usr/bin/env python3
"""sft_gen_bot.py — SFT/DPO training data generation via hmm_bot's proven functions.

Uses hmm_bot's navigate, attach, send, wait, and extract — the same code
that ran 123K+ HMM enrichments successfully on virtual displays.

Usage:
    DISPLAY=:5 python3 agents/sft_gen_bot.py --round sft --platforms chatgpt
    DISPLAY=:6 python3 agents/sft_gen_bot.py --round dpo --platforms gemini
"""
import argparse
import json
import logging
import os
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
SFT_OUTPUT_DIR = '/tmp/sft_output'
DPO_OUTPUT_DIR = '/tmp/dpo_output'


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

    # Step 4: Wait for response
    log.info(f"[{platform}] Waiting for response...")
    if not bot.wait_for_response(platform, timeout=600):
        log.warning(f"[{platform}] Wait timed out — trying extract anyway")

    # Step 5: Extract response
    log.info(f"[{platform}] Extracting response")
    content = bot.extract_response(platform)
    if not content or len(content) < 100:
        log.error(f"[{platform}] Extract failed — got {len(content) if content else 0} chars")
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
        # Perplexity appends S3 citation URLs after the JSON — strip them
        # e.g. {"messages":[...]} [ppl-ai-file-upload.s3.amazonaws...]
        if line.startswith('{'):
            bracket_end = line.rfind(']}')
            if bracket_end > 0:
                line = line[:bracket_end + 2]
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

    log.info(f"[{platform}] Saved {len(valid)} JSONL items to {output_path}")

    # Save raw response too
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
            log.error(f"[{platform}] Exception: {e}", exc_info=True)
            results[platform] = f'ERROR: {e}'

    log.info("=== Results ===")
    for p, r in results.items():
        log.info(f"  {p}: {r}")
    log.info(f"Output in {output_dir}/")


if __name__ == '__main__':
    main()
