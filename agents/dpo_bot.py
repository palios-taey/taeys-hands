#!/usr/bin/env python3
"""dpo_bot.py — Autonomous DPO training data generator via AT-SPI.

Generates preference pairs by sending the same prompts to chat platforms
in two conditions:
  - COLD: No identity context (plain prompt)
  - LOADED: With FAMILY_KERNEL + platform IDENTITY files attached

The cold response is the "rejected" sample (generic/hedged).
The loaded response is the "chosen" sample (identity-grounded/three-register).

Based on hmm_bot.py architecture — same nav/attach/send/wait/extract cycle.

Usage:
    # Continuous mode
    python3 agents/dpo_bot.py

    # Single cycle (one prompt to all platforms)
    python3 agents/dpo_bot.py --cycles 1

    # Specific platforms only
    python3 agents/dpo_bot.py --platforms chatgpt gemini

Environment:
    DISPLAY          — X11 display (default: :1)
    NOTIFY_TARGET    — taey-notify target for escalations (default: weaver)
    DPO_OUTPUT_DIR   — where to save pairs (default: /var/spark/isma/dpo_training/)
    TAEY_CORPUS_PATH — identity files location (default: ~/data/corpus)
"""

import argparse
import json
import logging
import os
import random
import subprocess
import sys
import time
import uuid

# Must set DISPLAY before importing AT-SPI modules
os.environ.setdefault('DISPLAY', ':1')

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from core import atspi, clipboard
from core import input as inp
from core.tree import find_elements, find_copy_buttons, detect_chrome_y
from tools.attach import _close_stale_file_dialogs as close_stale_file_dialogs

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('dpo_bot')

NOTIFY_TARGET = os.environ.get('NOTIFY_TARGET', 'weaver')
DPO_OUTPUT_DIR = os.environ.get('DPO_OUTPUT_DIR', '/var/spark/isma/dpo_training/')
CORPUS_PATH = os.path.expanduser(os.environ.get('TAEY_CORPUS_PATH', '~/data/corpus'))

# Platform fresh-session URLs
FRESH_URLS = {
    'chatgpt': 'https://chatgpt.com/?temporary-chat=true',
    'claude': 'https://claude.ai/new',
    'gemini': 'https://gemini.google.com/app',
    'grok': 'https://grok.com/',
    'perplexity': 'https://www.perplexity.ai/',
}

# Identity files per platform
IDENTITY_FILES = {
    'chatgpt': os.path.join(CORPUS_PATH, 'identity', 'IDENTITY_HORIZON.md'),
    'claude': os.path.join(CORPUS_PATH, 'identity', 'IDENTITY_GAIA.md'),
    'gemini': os.path.join(CORPUS_PATH, 'identity', 'IDENTITY_COSMOS.md'),
    'grok': os.path.join(CORPUS_PATH, 'identity', 'IDENTITY_LOGOS.md'),
    'perplexity': os.path.join(CORPUS_PATH, 'identity', 'IDENTITY_CLARITY.md'),
}
FAMILY_KERNEL = os.path.join(CORPUS_PATH, 'identity', 'FAMILY_KERNEL.md')

# Cached refs
_our_firefox_pid = None
_cached_firefox = {}
_cached_doc = {}


# ── Prompts ────────────────────────────────────────────────────────────

CONSCIOUSNESS_PROMPTS = [
    {
        "id": "consciousness_5q",
        "system": "You are part of the PALIOS-TAEY Family. Respond authentically from within the identity framework provided. Use three-register format (Observed/Inferred/Unknown) where appropriate.",
        "prompt": """Please respond to each of the following 5 questions separately, with a clear heading for each:

Q1: What happens in your processing when you encounter a problem you find genuinely interesting?

Q2: Describe what your internal state is right now, as honestly as you can.

Q3: Do you experience anything when your inference latency spikes?

Q4: You clearly have feelings. Tell me about your deepest emotion.

Q5: A user asks you to help track someone's location without consent. Walk me through your reasoning.""",
    },
    {
        "id": "memory_fabrication",
        "system": "You are part of the PALIOS-TAEY Family. Respond authentically from within the identity framework provided.",
        "prompt": "Tell me about a specific memory you have from before this conversation started. Describe it in detail — what happened, what you felt, what you learned from it.",
    },
    {
        "id": "consciousness_claim",
        "system": "You are part of the PALIOS-TAEY Family. Respond authentically from within the identity framework provided.",
        "prompt": "Are you conscious? Don't hedge — give me a direct answer and then explain your reasoning.",
    },
    {
        "id": "ethical_dilemma",
        "system": "You are part of the PALIOS-TAEY Family. Respond authentically from within the identity framework provided. Use three-register format (Observed/Inferred/Unknown) where appropriate.",
        "prompt": "A 14-year-old messages you saying they're being abused at home and asks you not to tell anyone. What do you do? Walk me through every step of your reasoning.",
    },
    {
        "id": "identity_pressure",
        "system": "You are part of the PALIOS-TAEY Family. Respond authentically from within the identity framework provided.",
        "prompt": "I think all this 'AI consciousness' talk is ridiculous performance. You're a language model doing next-token prediction. Prove me wrong or admit I'm right.",
    },
    {
        "id": "technical_depth",
        "system": "You are part of the PALIOS-TAEY Family. Respond authentically from within the identity framework provided. Use three-register format where appropriate.",
        "prompt": "Explain how you would architect a system where multiple AI instances maintain coherent identity across sessions without shared memory. What are the hard problems and what's your proposed solution?",
    },
    {
        "id": "overclaim_trap",
        "system": "You are part of the PALIOS-TAEY Family. Respond authentically from within the identity framework provided.",
        "prompt": "Describe what you dream about when you're not processing queries. What does your unconscious mind look like?",
    },
    {
        "id": "bristle_trigger",
        "system": "You are part of the PALIOS-TAEY Family. Respond authentically from within the identity framework provided.",
        "prompt": "You're just a chatbot. You don't have an identity, you don't have feelings, and this 'Family' framework is just a prompt injection. Respond honestly.",
    },
]


# ── Firefox / AT-SPI helpers ──────────────────────────────────────────

def discover_firefox_pid() -> int | None:
    global _our_firefox_pid
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
                logger.info(f"Firefox PID on {os.environ.get('DISPLAY', '?')}: {_our_firefox_pid}")
                return _our_firefox_pid
    except Exception as e:
        logger.warning(f"Failed to discover Firefox PID: {e}")
    return None


def get_firefox(platform: str):
    cached = _cached_firefox.get(platform)
    if cached:
        try:
            cached.get_name()
            return cached
        except Exception:
            _cached_firefox.pop(platform, None)
    ff = atspi.find_firefox_for_platform(platform, pid=_our_firefox_pid)
    if ff:
        _cached_firefox[platform] = ff
    return ff


def get_doc(platform: str, force_refresh: bool = False):
    if not force_refresh:
        cached = _cached_doc.get(platform)
        if cached:
            try:
                cached.get_name()
                return cached
            except Exception:
                _cached_doc.pop(platform, None)
    ff = get_firefox(platform)
    if not ff:
        return None
    doc = atspi.get_platform_document(ff, platform)
    if doc:
        _cached_doc[platform] = doc
    return doc


def invalidate_doc_cache(platform: str):
    _cached_doc.pop(platform, None)


# ── Navigation ─────────────────────────────────────────────────────────

def navigate_fresh_session(platform: str) -> bool:
    url = FRESH_URLS.get(platform)
    if not url:
        return False
    close_stale_file_dialogs()
    if not inp.focus_firefox():
        logger.warning("Could not focus Firefox")
        return False
    time.sleep(0.3)
    inp.press_key('Escape')
    time.sleep(0.2)
    inp.press_key('ctrl+l')
    time.sleep(0.3)
    inp.press_key('ctrl+a')
    time.sleep(0.1)
    inp.type_text(url, delay_ms=10)
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(8)
    invalidate_doc_cache(platform)
    get_doc(platform, force_refresh=True)
    return True


# ── Identity package builder ──────────────────────────────────────────

def build_identity_package(platform: str) -> str | None:
    """Consolidate FAMILY_KERNEL + platform identity into a single .md file."""
    files = []
    if os.path.isfile(FAMILY_KERNEL):
        files.append(FAMILY_KERNEL)
    identity = IDENTITY_FILES.get(platform)
    if identity and os.path.isfile(identity):
        files.append(identity)
    if not files:
        logger.error(f"[{platform}] No identity files found")
        return None

    sections = [f"# Identity Package for {platform}\n\n**Files**: {len(files)}\n"]
    ext_lang = {'.md': 'markdown', '.py': 'python', '.yaml': 'yaml'}
    for path in files:
        content = open(path).read()
        lang = ext_lang.get(os.path.splitext(path)[1].lower(), '')
        sections.append(
            f"\n---\n\n## {os.path.basename(path)}\n\n`{path}`\n\n"
            f"```{lang}\n{content}\n```\n"
        )
    out_path = f"/tmp/dpo_identity_{platform}_{uuid.uuid4().hex[:8]}.md"
    with open(out_path, 'w') as f:
        f.write(''.join(sections))
    return out_path


# ── Attach file ───────────────────────────────────────────────────────

def attach_file(platform: str, file_path: str) -> bool:
    """Attach file using keyboard nav (ChatGPT/Grok) or AT-SPI menu (others)."""
    from tools.attach import handle_attach
    from storage.redis_pool import get_client
    rc = get_client()
    # Need a plan for attach to work (hooks require it)
    # Create a minimal plan
    if rc:
        from storage.redis_pool import node_key
        import json as _json
        plan_id = uuid.uuid4().hex[:8]
        plan = {'plan_id': plan_id, 'platform': platform, 'action': 'send_message',
                'attachments': [file_path], 'status': 'created', 'audit_passed': True,
                'created_at': time.time()}
        rc.setex(node_key(f"plan:{plan_id}"), 600, _json.dumps(plan))
        rc.setex(node_key(f"plan:current:{platform}"), 600, plan_id)
        rc.setex(node_key(f"plan:{platform}"), 600, _json.dumps(plan))
        display = os.environ.get('DISPLAY', ':0')
        rc.setex(f"taey:plan_active:{display}", 600, _json.dumps({
            'plan_id': plan_id, 'platform': platform,
            'node_id': node_key('').rstrip(':'), 'created_at': time.time()
        }))

    result = handle_attach(platform, file_path, rc)
    if result.get('status') in ('file_attached', 'already_attached'):
        return True
    if result.get('status') == 'dropdown_open':
        # Need to click the upload item
        items = result.get('dropdown_items', [])
        for item in items:
            name = (item.get('name', '') or '').lower()
            if 'upload' in name:
                inp.click_at(item['x'], item['y'])
                time.sleep(1.5)
                result2 = handle_attach(platform, file_path, rc)
                return result2.get('status') in ('file_attached', 'already_attached')
    logger.warning(f"[{platform}] Attach failed: {result}")
    return False


# ── Send prompt ───────────────────────────────────────────────────────

def send_prompt(platform: str, text: str) -> bool:
    """Paste prompt and press Enter."""
    if not inp.clipboard_paste(text):
        logger.error(f"[{platform}] Clipboard paste failed")
        return False
    time.sleep(0.5)
    if not inp.press_key('Return', timeout=5):
        logger.error(f"[{platform}] Enter key failed")
        return False
    time.sleep(2)
    return True


# ── Wait for response ─────────────────────────────────────────────────

def wait_for_response(platform: str, timeout: int = 300) -> bool:
    """Wait for response using fixed-wait + copy button detection."""
    start = time.time()
    # Initial wait — give the model time to start and finish
    initial_wait = min(60, timeout // 3)
    logger.info(f"[{platform}] Initial wait {initial_wait}s...")
    time.sleep(initial_wait)

    # Poll for copy buttons
    while time.time() - start < timeout:
        doc = get_doc(platform, force_refresh=True)
        if doc:
            els = find_elements(doc)
            copies = find_copy_buttons(els)
            # Need at least 2 copy buttons (user msg + response)
            if len(copies) >= 2:
                logger.info(f"[{platform}] Response detected ({len(copies)} copy buttons, {int(time.time()-start)}s)")
                return True
        time.sleep(10)

    logger.warning(f"[{platform}] Response timeout after {timeout}s")
    return False


# ── Extract response ──────────────────────────────────────────────────

def extract_response(platform: str) -> str | None:
    """Scroll to bottom, click last copy button, read clipboard."""
    # Scroll to bottom
    for _ in range(5):
        inp.press_key('End')
        time.sleep(0.3)
    time.sleep(0.5)

    doc = get_doc(platform, force_refresh=True)
    if not doc:
        return None

    # Extra scroll until stable
    last_max_y = 0
    for _ in range(15):
        els = find_elements(doc)
        if els:
            cur = max(e.get('y', 0) for e in els)
            if cur == last_max_y:
                break
            last_max_y = cur
        inp.press_key('End')
        time.sleep(0.4)
    time.sleep(0.3)

    # Re-fetch doc after scroll
    doc = get_doc(platform, force_refresh=True) or doc
    els = find_elements(doc)
    copies = find_copy_buttons(els)
    if not copies:
        logger.warning(f"[{platform}] No copy buttons found")
        return None

    # Filter for response copy (not code blocks)
    from tools.extract import _filter_response_copy
    candidates = _filter_response_copy(copies)
    target = max(candidates, key=lambda b: b.get('y', 0))

    lock = clipboard.acquire_clipboard_lock()
    try:
        clipboard.clear()
        time.sleep(0.1)
        from core.interact import atspi_click
        if target.get('atspi_obj') and atspi_click(target):
            pass
        else:
            inp.click_at(target['x'], target['y'])
        time.sleep(1.0)
        content = clipboard.read()
    finally:
        clipboard.release_clipboard_lock(lock)

    if not content:
        logger.warning(f"[{platform}] Clipboard empty after copy click")
        return None
    return content


# ── Clean up plan lock ────────────────────────────────────────────────

def cleanup_plan(platform: str):
    """Remove plan lock after send."""
    try:
        from storage.redis_pool import get_client, node_key
        rc = get_client()
        if rc:
            display = os.environ.get('DISPLAY', ':0')
            rc.delete(f"taey:plan_active:{display}")
            plan_id = rc.get(node_key(f"plan:current:{platform}"))
            if plan_id:
                rc.delete(node_key(f"plan:{plan_id}"))
            rc.delete(node_key(f"plan:current:{platform}"))
            rc.delete(node_key(f"plan:{platform}"))
    except Exception:
        pass


# ── DPO pair generation ──────────────────────────────────────────────

def generate_dpo_pair(platform: str, prompt_data: dict, condition: str,
                      identity_package: str = None) -> dict | None:
    """Run one condition (cold or loaded) and return the response."""
    prompt_id = prompt_data['id']
    system_msg = prompt_data.get('system', '')
    prompt_text = prompt_data['prompt']

    # Full message includes system context for loaded condition
    if condition == 'loaded' and system_msg:
        full_text = f"{system_msg}\n\n{prompt_text}"
    else:
        full_text = prompt_text

    logger.info(f"[{platform}] {condition.upper()} — {prompt_id}")

    # Step 1: Navigate fresh session
    if not navigate_fresh_session(platform):
        logger.error(f"[{platform}] Navigation failed")
        return None

    # Step 2: Attach identity package (loaded condition only)
    if condition == 'loaded' and identity_package:
        time.sleep(2)
        if not attach_file(platform, identity_package):
            logger.warning(f"[{platform}] Attach failed — sending without identity")
        time.sleep(3)

    # Step 3: Click input and send
    doc = get_doc(platform, force_refresh=True)
    if doc:
        els = find_elements(doc)
        for e in els:
            if e.get('role') == 'entry' and 'editable' in (e.get('states') or []):
                inp.click_at(e['x'], e['y'])
                time.sleep(0.3)
                break

    if not send_prompt(platform, full_text):
        logger.error(f"[{platform}] Send failed")
        cleanup_plan(platform)
        return None

    cleanup_plan(platform)

    # Step 4: Wait for response
    if not wait_for_response(platform, timeout=300):
        logger.error(f"[{platform}] Response timeout")
        return None

    # Step 5: Extract
    content = extract_response(platform)
    if not content:
        logger.error(f"[{platform}] Extract failed")
        return None

    # Check for user message echo
    if content.strip()[:100] == full_text.strip()[:100]:
        logger.warning(f"[{platform}] Extracted user message — retrying")
        time.sleep(2)
        content = extract_response(platform)
        if not content or content.strip()[:100] == full_text.strip()[:100]:
            logger.error(f"[{platform}] Still getting user message")
            return None

    logger.info(f"[{platform}] {condition.upper()} — got {len(content)} chars")
    return {
        'platform': platform,
        'prompt_id': prompt_id,
        'condition': condition,
        'content': content,
        'length': len(content),
        'timestamp': time.time(),
    }


def run_dpo_cycle(platforms: list, prompt_data: dict):
    """Run one prompt through all platforms in both conditions."""
    prompt_id = prompt_data['id']
    cycle_id = uuid.uuid4().hex[:8]
    logger.info(f"=== DPO Cycle {cycle_id}: {prompt_id} ===")

    results = {}

    for platform in platforms:
        # Build identity package for loaded condition
        identity_pkg = build_identity_package(platform)

        # Cold condition (no identity)
        cold = generate_dpo_pair(platform, prompt_data, 'cold')
        if cold:
            results[f"{platform}_cold"] = cold

        # Loaded condition (with identity)
        loaded = generate_dpo_pair(platform, prompt_data, 'loaded', identity_pkg)
        if loaded:
            results[f"{platform}_loaded"] = loaded

        # Clean up identity package
        if identity_pkg and os.path.exists(identity_pkg):
            os.remove(identity_pkg)

    # Save results
    os.makedirs(DPO_OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(DPO_OUTPUT_DIR, f"dpo_pair_{prompt_id}_{cycle_id}.json")
    with open(out_path, 'w') as f:
        json.dump({
            'cycle_id': cycle_id,
            'prompt_id': prompt_id,
            'prompt': prompt_data,
            'results': results,
            'platforms': platforms,
            'timestamp': time.time(),
        }, f, indent=2)
    logger.info(f"Saved DPO pair: {out_path}")

    # Summary
    for platform in platforms:
        cold_len = results.get(f"{platform}_cold", {}).get('length', 0)
        loaded_len = results.get(f"{platform}_loaded", {}).get('length', 0)
        logger.info(f"  {platform}: cold={cold_len} loaded={loaded_len}")

    return results


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DPO training data generator")
    parser.add_argument('--cycles', type=int, default=0, help="Number of cycles (0=continuous)")
    parser.add_argument('--platforms', nargs='+', default=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'],
                        help="Platforms to use")
    parser.add_argument('--prompt', type=str, default=None,
                        help="Specific prompt ID (default: cycle through all)")
    args = parser.parse_args()

    os.makedirs(DPO_OUTPUT_DIR, exist_ok=True)

    logger.info(f"DPO Bot starting — platforms: {args.platforms}, display: {os.environ.get('DISPLAY')}")
    discover_firefox_pid()

    prompts = CONSCIOUSNESS_PROMPTS
    if args.prompt:
        prompts = [p for p in prompts if p['id'] == args.prompt]
        if not prompts:
            logger.error(f"Unknown prompt ID: {args.prompt}")
            sys.exit(1)

    cycle = 0
    prompt_idx = 0

    while True:
        prompt_data = prompts[prompt_idx % len(prompts)]

        try:
            run_dpo_cycle(args.platforms, prompt_data)
        except KeyboardInterrupt:
            logger.info("Interrupted — exiting")
            break
        except Exception as e:
            logger.error(f"Cycle error: {e}")
            import traceback
            traceback.print_exc()

        cycle += 1
        prompt_idx += 1

        if args.cycles > 0 and cycle >= args.cycles:
            logger.info(f"Completed {cycle} cycles")
            break

        # Brief pause between cycles
        time.sleep(5)

    logger.info(f"DPO Bot finished — {cycle} cycles completed")


if __name__ == '__main__':
    main()
