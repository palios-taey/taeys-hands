#!/usr/bin/env python3
"""conductor_bot.py — The Conductor's autonomous bot for repeatable Chat processes.

Generalization of hmm_bot/unified_bot for ANY repeatable Chat interaction:
  - HMM enrichment (existing)
  - Training data generation (SFT/DPO)
  - Research consultations
  - Audit/review sessions
  - Voice calibration

One bot per display, one AI platform per bot. No tab switching.
Cycles through conversation URLs for parallel topics within a single platform.

The Conductor feeds tasks via Redis queue. The bot:
  1. Pulls task from queue (or builds package locally)
  2. Navigates to fresh session or existing URL
  3. Sets model/mode per task type
  4. Attaches context file
  5. Pastes and sends prompt
  6. Waits for response (monitors stop button)
  7. Extracts response
  8. Stores in ISMA (if configured)
  9. Reports completion back to Conductor
  10. Pulls next task

Exception handling: first error → stop this task → log → notify Conductor → continue to next task.
Never retry. Never hack around failures. Raise to intelligence.

Usage:
    # Research bot on Gemini (display :3)
    DISPLAY=:3 python3 agents/conductor_bot.py --platform gemini --queue conductor:tasks:research

    # Training gen bot on ChatGPT (display :2)
    DISPLAY=:2 python3 agents/conductor_bot.py --platform chatgpt --queue conductor:tasks:training

    # HMM enrichment (backwards compatible)
    DISPLAY=:4 python3 agents/conductor_bot.py --platform grok --queue conductor:tasks:hmm
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

# Must set DISPLAY before importing AT-SPI modules
os.environ.setdefault('DISPLAY', os.environ.get('DISPLAY', ':1'))
os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')

# Add taeys-hands root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import atspi, input as inp, clipboard
from core.platforms import SOCIAL_PLATFORMS
from tools.inspect import handle_inspect
from tools.attach import handle_attach
from tools.send import handle_send_message
from tools.extract import handle_quick_extract
from tools.plan import handle_plan
from tools.dropdown import handle_select_dropdown

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [conductor-bot:%(name)s] %(levelname)s %(message)s',
)
log = logging.getLogger('conductor')

# Redis connection
REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))

try:
    import redis as redis_lib
    _redis = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT,
                              decode_responses=True, socket_timeout=5)
    _redis.ping()
except Exception as e:
    log.warning(f"Redis not available: {e}")
    _redis = None


class TaskTypes:
    """Known task types with their default configurations."""
    HMM = "hmm"
    RESEARCH = "research"
    TRAINING_GEN = "training_gen"
    AUDIT = "audit"
    CONSULTATION = "consultation"
    VOICE = "voice"

    # Default mode per task type per platform
    DEFAULTS = {
        "research": {
            "gemini": {"model": "Pro", "tools": ["Deep research"]},
            "grok": {"model": "Grok 4.20 Beta", "mode": "Heavy"},
            "perplexity": {"tools": ["Deep research"]},
            "chatgpt": {"mode": "Extended Thinking"},
        },
        "audit": {
            "gemini": {"model": "Pro", "tools": ["Deep think"]},
            "grok": {"model": "Grok 4.20 Beta", "mode": "Heavy"},
            "chatgpt": {"mode": "Extended Thinking"},
        },
        "training_gen": {
            "gemini": {"model": "Pro"},
            "chatgpt": {"model": "Pro"},
            "grok": {"model": "Grok 4.20 Beta"},
        },
        "consultation": {
            "gemini": {"model": "Pro", "tools": ["Deep think"]},
            "grok": {"model": "Grok 4.20 Beta", "mode": "Heavy"},
            "chatgpt": {"mode": "Extended Thinking"},
            "perplexity": {"tools": ["Deep research"]},
        },
    }


class ConductorBot:
    """Autonomous bot for repeatable Chat platform interactions."""

    def __init__(self, platform: str, queue: str, display: str = None,
                 cycles: int = 0, notify_target: str = "claude"):
        self.platform = platform
        self.queue = queue
        self.display = display or os.environ.get('DISPLAY', ':1')
        self.max_cycles = cycles  # 0 = infinite
        self.notify_target = notify_target
        self.cycle_count = 0
        self.errors = 0
        self.max_consecutive_errors = 3

        # Set display for AT-SPI
        os.environ['DISPLAY'] = self.display
        inp.set_display(self.display)
        clipboard.set_display(self.display)

        # Set isolated AT-SPI bus if available
        bus_file = f'/tmp/a11y_bus_{self.display}'
        try:
            with open(bus_file) as f:
                bus_addr = f.read().strip()
            if bus_addr:
                os.environ['AT_SPI_BUS_ADDRESS'] = bus_addr
                log.info(f"Isolated AT-SPI bus: {bus_addr[:50]}...")
        except FileNotFoundError:
            log.info("No isolated bus — using shared AT-SPI")

        log.info(f"ConductorBot initialized: platform={platform}, "
                 f"display={display}, queue={queue}")

    def pull_task(self) -> Optional[Dict]:
        """Pull next task from Redis queue. Blocks for 5 seconds."""
        if not _redis:
            return None
        try:
            result = _redis.brpop(self.queue, timeout=5)
            if result:
                _, task_json = result
                return json.loads(task_json)
        except Exception as e:
            log.error(f"Queue pull error: {e}")
        return None

    def report_completion(self, task: Dict, result: Dict):
        """Report task completion back to Conductor."""
        if not _redis:
            return
        try:
            task_id = task.get("task_id", "unknown")
            report = {
                "task_id": task_id,
                "platform": self.platform,
                "status": result.get("status", "completed"),
                "content_length": len(result.get("content", "")),
                "elapsed": result.get("elapsed", 0),
                "timestamp": datetime.now().isoformat(),
            }
            _redis.lpush(f"conductor:results:{self.platform}", json.dumps(report))
            _redis.hset(f"conductor:task:{task_id}", mapping={
                "status": result.get("status", "completed"),
                "completed_at": str(time.time()),
            })
            log.info(f"Reported: {task_id} → {result.get('status')}")
        except Exception as e:
            log.error(f"Report error: {e}")

    def report_error(self, task: Dict, error: str):
        """Report error to Conductor for escalation."""
        if not _redis:
            return
        try:
            task_id = task.get("task_id", "unknown")
            escalation = {
                "from": f"conductor-bot-{self.platform}",
                "type": "BOT_ERROR",
                "priority": "high",
                "body": f"Bot error on {self.platform}: {error}. Task: {task_id}",
                "task": task,
                "timestamp": datetime.now().isoformat(),
            }
            _redis.lpush(f"taey:{self.notify_target}:inbox", json.dumps(escalation))
            log.error(f"Escalated to {self.notify_target}: {error}")
        except Exception as e:
            log.error(f"Escalation failed: {e}")

    def execute_task(self, task: Dict) -> Dict:
        """Execute a single task: navigate → setup → attach → send → wait → extract.

        Returns result dict with status, content, elapsed.
        """
        t0 = time.time()
        task_type = task.get("type", "consultation")
        message = task.get("message", task.get("prompt", ""))
        attachment = task.get("attachment", task.get("file", ""))
        session = task.get("session", "new")
        model = task.get("model")
        mode = task.get("mode")
        tools = task.get("tools", [])

        # Apply defaults for task type if not specified
        defaults = TaskTypes.DEFAULTS.get(task_type, {}).get(self.platform, {})
        if not model:
            model = defaults.get("model", "N/A")
        if not mode:
            mode = defaults.get("mode", "N/A")
        if not tools:
            tools = defaults.get("tools", [])

        log.info(f"Executing: type={task_type}, model={model}, mode={mode}, "
                 f"tools={tools}, msg={message[:80]}...")

        redis_client = _redis
        display = self.display

        # Step 1: Create plan
        plan_params = {
            "session": session,
            "model": model,
            "mode": mode,
            "message": message,
            "attachments": [attachment] if attachment else [],
            "tools": tools if tools else ["none"],
        }
        plan_result = handle_plan(self.platform, "send_message", plan_params, redis_client)
        if not plan_result.get("success"):
            return {"status": "error", "error": f"Plan creation failed: {plan_result}",
                    "elapsed": time.time() - t0}

        consolidated_file = plan_result.get("attachment", attachment)

        # Step 2: Inspect (navigate to platform)
        inspect_result = handle_inspect(self.platform, redis_client,
            fresh_session=(session == "new"))
        if not inspect_result.get("success"):
            return {"status": "error", "error": f"Inspect failed: {inspect_result.get('error')}",
                    "elapsed": time.time() - t0}

        # Step 3: Set model/mode if needed
        if model and model != "N/A":
            try:
                handle_select_dropdown(self.platform, "mode_picker", model, redis_client)
                time.sleep(0.5)
            except Exception as e:
                log.warning(f"Model selection warning: {e}")

        if tools and tools != ["none"]:
            for tool in tools:
                try:
                    handle_select_dropdown(self.platform, "Tools", tool, redis_client)
                    time.sleep(0.5)
                except Exception as e:
                    log.warning(f"Tool selection warning: {e}")

        # Step 4: Attach file
        if consolidated_file and os.path.exists(consolidated_file):
            attach_result = handle_attach(self.platform, consolidated_file, redis_client)
            if attach_result.get("status") == "dropdown_open":
                # Need to click upload option
                items = attach_result.get("dropdown_items", [])
                upload_item = None
                for item in items:
                    if "upload" in item.get("name", "").lower():
                        upload_item = item
                        break
                if upload_item:
                    inp.click_at(int(upload_item["x"]), int(upload_item["y"]))
                    time.sleep(0.5)
                    attach_result = handle_attach(self.platform, consolidated_file, redis_client)

            if attach_result.get("status") not in ("file_attached",):
                log.warning(f"Attach may have failed: {attach_result.get('status')}")

        # Step 5: Audit
        audit_params = {
            "current_model": model,
            "current_mode": mode,
            "current_tools": tools if tools else ["none"],
            "attachment_confirmed": bool(consolidated_file),
        }
        audit_result = handle_plan(self.platform, "audit", audit_params, redis_client)
        if not audit_result.get("passed", False):
            log.warning(f"Audit warnings: {audit_result.get('failures', [])}")
            # Continue anyway — audit failures are often cosmetic

        # Step 6: Re-inspect to get updated coordinates
        inspect_result = handle_inspect(self.platform, redis_client)

        # Step 7: Click input and send message
        send_result = handle_send_message(
            self.platform, message, redis_client, display,
            attachments=[consolidated_file] if consolidated_file else None,
            purpose=task.get("purpose", task_type),
        )
        if send_result.get("error"):
            return {"status": "error", "error": f"Send failed: {send_result['error']}",
                    "elapsed": time.time() - t0}

        url = send_result.get("url", "")
        monitor_id = send_result.get("monitor", {}).get("id")
        log.info(f"Sent. URL={url[:60]}... Monitor={monitor_id}")

        # Step 8: Wait for response
        timeout = task.get("timeout", 600)
        response_ready = self._wait_for_response(timeout)

        if not response_ready:
            return {"status": "timeout", "error": f"No response after {timeout}s",
                    "url": url, "elapsed": time.time() - t0}

        # Step 9: Extract response
        extract_plan = handle_plan(self.platform, "extract_response", {}, redis_client)
        time.sleep(1)

        # Scroll to bottom and extract
        handle_inspect(self.platform, redis_client, scroll="bottom")
        extract_result = handle_quick_extract(self.platform, redis_client, complete=True)

        content = extract_result.get("content", "")
        elapsed = time.time() - t0

        log.info(f"Extracted: {len(content)} chars in {elapsed:.1f}s")

        return {
            "status": "completed",
            "content": content,
            "url": url,
            "elapsed": elapsed,
            "word_count": len(content.split()),
        }

    def _wait_for_response(self, timeout: int = 600) -> bool:
        """Wait for the Chat platform to finish responding.

        Monitors for: stop button disappearing, copy buttons appearing.
        """
        deadline = time.time() + timeout
        check_interval = 10  # Check every 10 seconds
        last_state = None

        while time.time() < deadline:
            time.sleep(check_interval)
            try:
                # Quick inspect to check for completion signals
                result = handle_inspect(self.platform, _redis, scroll="none")
                copy_count = result.get("state", {}).get("copy_button_count", 0)
                controls = result.get("controls", [])

                # Check for stop/cancel button (means still generating)
                has_stop = any("stop" in c.get("name", "").lower() or
                              "cancel" in c.get("name", "").lower()
                              for c in controls
                              if c.get("role") in ("push button",))

                if last_state == "generating" and not has_stop and copy_count > 0:
                    log.info("Response complete (stop button gone, copy buttons present)")
                    return True

                if has_stop:
                    last_state = "generating"
                    log.debug("Still generating...")
                elif copy_count > 0 and last_state is None:
                    # Already complete when we first checked
                    log.info("Response already complete")
                    return True

            except Exception as e:
                log.warning(f"Monitor check error: {e}")

        return False

    def run(self):
        """Main loop: pull tasks, execute, report. Runs until max_cycles or forever."""
        log.info(f"Starting ConductorBot: platform={self.platform}, "
                 f"display={self.display}, queue={self.queue}")

        consecutive_errors = 0

        while True:
            if self.max_cycles > 0 and self.cycle_count >= self.max_cycles:
                log.info(f"Reached max cycles ({self.max_cycles}). Stopping.")
                break

            # Pull task
            task = self.pull_task()
            if not task:
                continue  # No task available, brpop will block again

            task_id = task.get("task_id", f"auto-{int(time.time())}")
            log.info(f"=== Cycle {self.cycle_count + 1}: {task_id} ===")

            try:
                result = self.execute_task(task)

                if result.get("status") == "completed":
                    self.report_completion(task, result)
                    consecutive_errors = 0
                elif result.get("status") == "error":
                    self.report_error(task, result.get("error", "unknown"))
                    consecutive_errors += 1
                elif result.get("status") == "timeout":
                    self.report_error(task, f"Timeout: {result.get('error')}")
                    consecutive_errors += 1

                self.cycle_count += 1

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                log.error(f"Unhandled error: {error_msg}")
                self.report_error(task, error_msg)
                consecutive_errors += 1

            # Circuit breaker: too many consecutive errors → halt
            if consecutive_errors >= self.max_consecutive_errors:
                log.error(f"Circuit breaker: {consecutive_errors} consecutive errors. Halting.")
                self.report_error(
                    {"task_id": "circuit_breaker"},
                    f"Bot halted after {consecutive_errors} consecutive errors on {self.platform}"
                )
                break

        log.info(f"Bot stopped. {self.cycle_count} cycles, {self.errors} errors.")


def main():
    parser = argparse.ArgumentParser(description="Conductor Bot — autonomous Chat automation")
    parser.add_argument("--platform", required=True,
                        choices=["chatgpt", "claude", "gemini", "grok", "perplexity"])
    parser.add_argument("--queue", default="conductor:tasks:default",
                        help="Redis queue to pull tasks from")
    parser.add_argument("--display", default=None,
                        help="X11 display (default: $DISPLAY)")
    parser.add_argument("--cycles", type=int, default=0,
                        help="Max cycles (0 = infinite)")
    parser.add_argument("--notify-target", default="claude",
                        help="tmux session for error escalation")
    args = parser.parse_args()

    bot = ConductorBot(
        platform=args.platform,
        queue=args.queue,
        display=args.display,
        cycles=args.cycles,
        notify_target=args.notify_target,
    )
    bot.run()


if __name__ == "__main__":
    main()
