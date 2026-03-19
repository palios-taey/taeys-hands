#!/usr/bin/env python3
"""unified_bot.py — Unified automation bot for PALIOS-TAEY.

Supersedes hmm_bot.py with:
  - Mode/model selection (YAML-driven, coordinate-free)
  - Orchestrator integration (task assignment, ISMA ingestion)
  - 6-sigma halt system (global halt on tool failure, platform halt on YAML drift)
  - YAML drift detection (structure_hash comparison)
  - Social platform extensibility (x_reply_bot pattern)

The flow:
  1. Check halt flags
  2. Poll orchestrator for tasks (or use local package builder)
  3. Navigate to fresh session
  4. Select model/mode per task requirements
  5. Attach package file
  6. Send prompt
  7. Wait for response
  8. Extract response
  9. Ingest into ISMA
  10. Report completion
  11. Store structure hash for drift detection
  12. Loop

Usage:
    # Standard mode (uses package builder)
    python3 agents/unified_bot.py --platforms chatgpt gemini grok

    # Orchestrator mode (polls for tasks)
    python3 agents/unified_bot.py --orchestrator --platforms chatgpt gemini grok

    # Single cycle test
    python3 agents/unified_bot.py --cycles 1 --platforms chatgpt

    # With mode override for testing
    python3 agents/unified_bot.py --cycles 1 --platforms gemini --mode deep_think

Environment:
    DISPLAY          — X11 display (default: :1)
    ORCH_URL         — Orchestrator URL (default: https://orch-api.taey.ai)
    ORCH_KEY         — Orchestrator API key
    AGENT_ID         — Agent identifier (default: taeys-hands)
    NODE_ID          — Machine identifier
    NOTIFY_TARGET    — Escalation target (default: weaver)
    BUILDER_PATH     — Path to hmm_package_builder.py
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import traceback

# Must set DISPLAY before importing AT-SPI modules
os.environ.setdefault('DISPLAY', ':1')

# Add taeys-hands root to path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
if os.path.expanduser('~/embedding-server') not in sys.path:
    sys.path.insert(0, os.path.expanduser('~/embedding-server'))

from core import atspi, input as inp
from core.tree import find_elements, find_copy_buttons, detect_chrome_y
from core.halt import halt_global, halt_platform, check_halt, clear_halt, clear_platform_halt
from core.drift import store_structure_hash, check_structure_drift, classify_unknown_elements
from core.mode_select import select_mode_model
from core import orchestrator

# Import hmm_bot functions we reuse (don't reinvent)
from agents.hmm_bot import (
    navigate_fresh_session, check_firefox_alive, restart_firefox,
    get_firefox, get_doc, invalidate_doc_cache, invalidate_all_cache,
    discover_firefox_pid, find_input_field_atspi,
    _find_elements_with_fence, _get_fence_after,
    scan_for_stop_button, count_copy_buttons,
    extract_response, wait_for_response,
    get_prompt, get_next_package, complete_package, fail_package, get_stats,
    notify, escalate, FRESH_URLS,
    _extracted_cache, _our_firefox_pid,
)
from tools.attach import handle_attach, _keyboard_nav_attach as keyboard_nav_attach
from tools.attach import _close_stale_file_dialogs as close_stale_file_dialogs

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('unified_bot')

# Redis for halt system
_redis_client = None


def _get_redis():
    """Lazy Redis connection."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            redis_url = os.environ.get('REDIS_URL', 'redis://10.0.0.68:6379')
            _redis_client = redis.from_url(redis_url, decode_responses=True)
            _redis_client.ping()
            logger.info(f"Redis connected: {redis_url}")
        except Exception as e:
            logger.warning(f"Redis not available: {e}")
            _redis_client = False  # Sentinel for "tried and failed"
    return _redis_client if _redis_client is not False else None


# ═══ CYCLE STATS ═══

class CycleStats:
    """Track success/failure per platform for 6-sigma monitoring."""
    def __init__(self):
        self.attempts = {}
        self.successes = {}
        self.failures = {}
        self.consecutive_failures = {}

    def record_success(self, platform: str):
        self.attempts[platform] = self.attempts.get(platform, 0) + 1
        self.successes[platform] = self.successes.get(platform, 0) + 1
        self.consecutive_failures[platform] = 0

    def record_failure(self, platform: str, reason: str):
        self.attempts[platform] = self.attempts.get(platform, 0) + 1
        self.failures[platform] = self.failures.get(platform, 0) + 1
        self.consecutive_failures[platform] = self.consecutive_failures.get(platform, 0) + 1

    def should_halt(self, platform: str, max_consecutive: int = 3) -> bool:
        """3 consecutive failures → halt platform."""
        return self.consecutive_failures.get(platform, 0) >= max_consecutive

    def summary(self) -> str:
        lines = []
        for p in sorted(set(list(self.attempts.keys()))):
            a = self.attempts.get(p, 0)
            s = self.successes.get(p, 0)
            f = self.failures.get(p, 0)
            rate = (s / a * 100) if a > 0 else 0
            lines.append(f"  {p}: {s}/{a} ({rate:.0f}%) — {f} failures")
        return "\n".join(lines) if lines else "  No cycles yet"


stats = CycleStats()


# ═══ MAIN CYCLE ═══

def process_platform(platform: str, mode: str = None, model: str = None,
                     orchestrator_mode: bool = False,
                     ingest_after: bool = True) -> bool:
    """Execute one full cycle for a platform.

    Returns True on success, False on failure.
    """
    redis = _get_redis()

    # ── Step 0: Check halt ──
    halt = check_halt(platform, redis)
    if halt:
        logger.warning(f"[{platform}] HALTED: {halt.get('reason', 'unknown')}")
        return False

    # ── Step 1: Verify Firefox ──
    if not check_firefox_alive(platform):
        logger.error(f"[{platform}] Firefox not alive")
        halt_global(f"Firefox not alive on {os.environ.get('DISPLAY', ':?')}", redis, platform)
        return False

    # ── Step 2: Get task ──
    package_path = None
    prompt = None
    task_metadata = {}

    if orchestrator_mode:
        # Check orchestrator inbox for assigned tasks
        messages = orchestrator.check_inbox()
        for msg in messages:
            text = msg.get('text', '')
            try:
                task = json.loads(text)
                if task.get('platform') == platform:
                    mode = task.get('mode', mode)
                    model = task.get('model', model)
                    package_path = task.get('package_path')
                    prompt = task.get('prompt')
                    task_metadata = task
                    break
            except (json.JSONDecodeError, TypeError):
                pass

    if not package_path:
        # Fall back to package builder
        package_path = get_next_package(platform)
        if not package_path:
            logger.info(f"[{platform}] No packages available")
            return True  # Not a failure, just nothing to do

    if not prompt:
        prompt = get_prompt()

    logger.info(f"[{platform}] Starting cycle — mode={mode}, package={os.path.basename(package_path)}")

    # ── Step 3: Navigate to fresh session ──
    if not navigate_fresh_session(platform):
        logger.error(f"[{platform}] Navigation failed")
        stats.record_failure(platform, 'navigation')
        if stats.should_halt(platform):
            halt_platform(platform, f"3 consecutive navigation failures", redis)
        return False

    # ── Step 4: Select mode/model ──
    if mode or model:
        logger.info(f"[{platform}] Selecting mode={mode} model={model}")
        result = select_mode_model(platform, mode=mode, model=model)
        if not result.get('success'):
            error = result.get('error', 'unknown')
            logger.error(f"[{platform}] Mode selection failed: {error}")

            # Mode selection failure is YAML-level — halt this platform
            if 'not found' in error.lower() or 'no menu' in error.lower():
                halt_platform(platform, f"Mode selection failed: {error}", redis,
                              drift_data={'requested_mode': mode or model, 'error': error})
            stats.record_failure(platform, 'mode_selection')
            return False

        # Update timeout if mode_guidance specified one
        timeout = result.get('timeout', 1800)
        logger.info(f"[{platform}] Mode selected: {result.get('selected_mode', 'unknown')} (timeout={timeout}s)")

    # ── Step 5: Attach package ──
    logger.info(f"[{platform}] Attaching: {os.path.basename(package_path)}")
    close_stale_file_dialogs()

    doc = get_doc(platform, force_refresh=True)
    if doc:
        fences = _get_fence_after(platform)
        elements = _find_elements_with_fence(doc, platform)
        chrome_y = detect_chrome_y(doc)

        # Find attach trigger
        attach_element = None
        for e in elements:
            name = (e.get('name') or '').lower()
            if ('attach' in name or 'add files' in name or 'upload' in name) and 'button' in (e.get('role') or ''):
                attach_element = e
                break

        if attach_element:
            from core.interact import atspi_click
            x, y = int(attach_element.get('x', 0)), int(attach_element.get('y', 0))

            # Use platform click strategy
            import yaml
            config_path = os.path.join(_ROOT, 'platforms', f'{platform}.yaml')
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
            attach_method = config.get('attach_method', 'keyboard_nav')

            if attach_method == 'keyboard_nav':
                # ChatGPT/Grok: click trigger → Down+Enter → file dialog
                inp.click_at(x, y)
                time.sleep(0.8)
                inp.press_key('Down')
                time.sleep(0.15)
                inp.press_key('Return')
                time.sleep(1.5)
            else:
                # Gemini/Claude/Perplexity: AT-SPI menu
                if atspi_click(attach_element):
                    time.sleep(1.0)
                else:
                    inp.click_at(x, y)
                    time.sleep(1.0)

                # Find "Upload files" menu item
                firefox = get_firefox(platform)
                from core.tree import find_menu_items
                menu_items = find_menu_items(firefox, doc)
                upload_item = None
                for mi in menu_items:
                    mi_name = (mi.get('name') or '').lower()
                    if 'upload' in mi_name or 'add files' in mi_name:
                        upload_item = mi
                        break

                if upload_item:
                    if upload_item.get('atspi_obj'):
                        atspi_click(upload_item)
                    else:
                        inp.click_at(int(upload_item.get('x', 0)), int(upload_item.get('y', 0)))
                    time.sleep(1.5)

            # Handle file dialog
            time.sleep(1.0)
            inp.press_key('ctrl+l')
            time.sleep(0.5)
            inp.press_key('ctrl+a')
            time.sleep(0.1)
            inp.type_text(package_path, delay_ms=10)
            time.sleep(0.3)
            inp.press_key('Return')
            time.sleep(3)  # Wait for file upload

            logger.info(f"[{platform}] File attached: {os.path.basename(package_path)}")
        else:
            logger.warning(f"[{platform}] No attach button found — pasting prompt as text")

    # ── Step 6: Send prompt ──
    logger.info(f"[{platform}] Sending prompt ({len(prompt)} chars)")

    # Find and click input field
    input_field = find_input_field_atspi(platform)
    if input_field:
        inp.click_at(int(input_field['x']), int(input_field['y']))
        time.sleep(0.3)
    else:
        logger.warning(f"[{platform}] No input field found — trying Tab")
        inp.press_key('Tab')
        time.sleep(0.3)

    # Paste prompt
    from core import clipboard
    if not inp.clipboard_paste(prompt):
        logger.error(f"[{platform}] Paste failed")
        fail_package(platform, 'paste_failure')
        stats.record_failure(platform, 'paste')
        return False
    time.sleep(0.3)

    # Send
    inp.press_key('Return')
    time.sleep(2)

    logger.info(f"[{platform}] Prompt sent, waiting for response...")

    # ── Step 7: Wait for response ──
    if not wait_for_response(platform):
        logger.error(f"[{platform}] No response received")
        fail_package(platform, 'no_response')
        stats.record_failure(platform, 'no_response')
        if stats.should_halt(platform):
            halt_platform(platform, f"3 consecutive no-response failures", redis)
        return False

    # ── Step 8: Extract response ──
    # Check if wait_for_response already cached the content
    content = _extracted_cache.pop(platform, None)
    if not content:
        content = extract_response(platform)

    if not content or len(content) < 50:
        logger.error(f"[{platform}] Extraction failed or too short ({len(content or '')} chars)")
        fail_package(platform, 'extraction_failure')
        stats.record_failure(platform, 'extraction')
        return False

    logger.info(f"[{platform}] Response extracted: {len(content)} chars")

    # ── Step 9: Complete package ──
    response_file = f'/tmp/hmm_response_{platform}_{int(time.time())}.md'
    with open(response_file, 'w') as f:
        f.write(content)

    if not complete_package(platform, response_file):
        logger.warning(f"[{platform}] Package completion failed (non-fatal)")

    # ── Step 10: ISMA ingestion ──
    if ingest_after:
        metadata = {
            'batch_id': task_metadata.get('batch_id', 'local'),
            'tile_hash': task_metadata.get('tile_hash', os.path.basename(package_path)),
            'model': model or mode or 'default',
            'platform': platform,
        }
        ingest_result = orchestrator.ingest_transcript(
            platform=platform,
            response_content=content,
            package_metadata=metadata,
            prompt_content=prompt,
        )
        if ingest_result.get('success'):
            logger.info(f"[{platform}] ISMA ingestion accepted: {ingest_result.get('content_hash')}")
        else:
            logger.warning(f"[{platform}] ISMA ingestion failed: {ingest_result.get('error')}")

    # ── Step 11: Report completion ──
    if orchestrator_mode and task_metadata.get('task_id'):
        orchestrator.report_completion(
            task_id=task_metadata['task_id'],
            result=f"Extracted {len(content)} chars from {platform}",
            status='completed',
            metadata={'platform': platform, 'chars': len(content)},
        )

    # ── Step 12: Store structure hash for drift detection ──
    doc = get_doc(platform, force_refresh=True)
    if doc:
        elements = _find_elements_with_fence(doc, platform)
        drift = check_structure_drift(platform, elements, redis)
        if drift:
            logger.warning(f"[{platform}] DRIFT DETECTED: {drift.get('unknown_elements', [])}")
            # Don't halt on first drift — store new hash and log
            # Halt on second consecutive drift (different from first)
            prev_drift = redis.get(f'taey:drift:last:{platform}') if redis else None
            if prev_drift:
                halt_platform(platform, f"Consecutive UI drift detected", redis,
                              drift_data=drift)
            else:
                if redis:
                    redis.setex(f'taey:drift:last:{platform}', 3600,
                                json.dumps(drift, default=str))
                store_structure_hash(platform, elements, redis)
        else:
            # No drift — clear any previous drift marker
            if redis:
                redis.delete(f'taey:drift:last:{platform}')
            store_structure_hash(platform, elements, redis)

    stats.record_success(platform)
    logger.info(f"[{platform}] Cycle complete — SUCCESS")
    return True


def run_bot(platforms: list, max_cycles: int = 0, mode: str = None,
            model: str = None, orchestrator_mode: bool = False,
            ingest_after: bool = True, cycle_delay: int = 30):
    """Main bot loop.

    Args:
        platforms: List of platform names
        max_cycles: 0 = infinite
        mode: Default mode for all platforms (can be overridden by orchestrator tasks)
        model: Default model for all platforms
        orchestrator_mode: Poll orchestrator for tasks
        ingest_after: Ingest responses into ISMA
        cycle_delay: Seconds between cycles
    """
    redis = _get_redis()

    # Send initial heartbeat
    orchestrator.heartbeat(
        status='active',
        capabilities={
            'platforms': platforms,
            'mode_selection': True,
            'isma_ingestion': True,
            'halt_system': True,
        },
    )

    # Discover Firefox PID (for multi-instance filtering)
    discover_firefox_pid()

    cycle = 0
    try:
        while max_cycles == 0 or cycle < max_cycles:
            cycle += 1
            logger.info(f"\n{'='*60}")
            logger.info(f"  CYCLE {cycle} — {', '.join(platforms)}")
            logger.info(f"{'='*60}")

            # Check global halt before any platform
            halt = check_halt('_global', redis) if redis else None
            if halt:
                logger.critical(f"GLOBAL HALT active: {halt.get('reason')}")
                break

            for platform in platforms:
                try:
                    process_platform(
                        platform,
                        mode=mode,
                        model=model,
                        orchestrator_mode=orchestrator_mode,
                        ingest_after=ingest_after,
                    )
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.error(f"[{platform}] Unhandled exception: {e}")
                    logger.error(traceback.format_exc())
                    stats.record_failure(platform, f'exception: {str(e)[:100]}')

                    # Unhandled exceptions are tool-level failures
                    if 'dbus' in str(e).lower() or 'atspi' in str(e).lower():
                        halt_global(f"AT-SPI/D-Bus exception: {e}", redis, platform)
                        break

            # Heartbeat after each cycle
            orchestrator.heartbeat(status='active', current_task=f"cycle_{cycle}")

            # Log stats
            if cycle % 5 == 0:
                logger.info(f"\n--- Stats after {cycle} cycles ---\n{stats.summary()}")

            if max_cycles == 0 or cycle < max_cycles:
                logger.info(f"Sleeping {cycle_delay}s before next cycle...")
                time.sleep(cycle_delay)

    except KeyboardInterrupt:
        logger.info("\nShutdown requested")
    finally:
        logger.info(f"\n--- Final Stats ---\n{stats.summary()}")
        orchestrator.heartbeat(status='idle')


def main():
    parser = argparse.ArgumentParser(description='Unified PALIOS-TAEY automation bot')
    parser.add_argument('--platforms', nargs='+',
                        default=['chatgpt', 'gemini', 'grok'],
                        help='Platforms to operate on')
    parser.add_argument('--cycles', type=int, default=0,
                        help='Number of cycles (0=infinite)')
    parser.add_argument('--mode', type=str, default=None,
                        help='Default mode for all platforms')
    parser.add_argument('--model', type=str, default=None,
                        help='Default model for all platforms')
    parser.add_argument('--orchestrator', action='store_true',
                        help='Poll orchestrator for tasks')
    parser.add_argument('--no-ingest', action='store_true',
                        help='Skip ISMA ingestion')
    parser.add_argument('--delay', type=int, default=30,
                        help='Seconds between cycles')
    args = parser.parse_args()

    run_bot(
        platforms=args.platforms,
        max_cycles=args.cycles,
        mode=args.mode,
        model=args.model,
        orchestrator_mode=args.orchestrator,
        ingest_after=not args.no_ingest,
        cycle_delay=args.delay,
    )


if __name__ == '__main__':
    main()
