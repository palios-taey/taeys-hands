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
                              decode_responses=True, socket_timeout=30)
    _redis.ping()
except Exception as e:
    log.warning(f"Redis not available: {e}")
    _redis = None


# Identity files for package consolidation (same as plan.py)
_CORPUS_PATH = os.path.expanduser(os.environ.get('TAEY_CORPUS_PATH', '~/data/corpus'))
_IDENTITY_DIR = os.path.join(_CORPUS_PATH, 'identity')
_FAMILY_KERNEL = os.path.join(_IDENTITY_DIR, 'FAMILY_KERNEL.md')
_PLATFORM_IDENTITY = {
    'chatgpt': os.path.join(_IDENTITY_DIR, 'IDENTITY_HORIZON.md'),
    'claude': os.path.join(_IDENTITY_DIR, 'IDENTITY_GAIA.md'),
    'gemini': os.path.join(_IDENTITY_DIR, 'IDENTITY_COSMOS.md'),
    'grok': os.path.join(_IDENTITY_DIR, 'IDENTITY_LOGOS.md'),
    'perplexity': os.path.join(_IDENTITY_DIR, 'IDENTITY_CLARITY.md'),
}


def _consolidate_package(platform: str, attachment: str = '') -> Optional[str]:
    """Build consolidated attachment: FAMILY_KERNEL + identity + user file.

    Matches plan.py consolidation but without Redis plan state.
    Returns path to consolidated file, or None if no files to attach.
    """
    files = []
    for path in [_FAMILY_KERNEL, _PLATFORM_IDENTITY.get(platform, '')]:
        if path and os.path.isfile(path):
            files.append(path)
    if attachment and os.path.isfile(attachment):
        files.append(attachment)

    if not files:
        return None
    if len(files) == 1:
        return files[0]

    # Consolidate into single .md
    sections = [f"# Package for {platform}\n\n**Files**: {len(files)}\n"]
    for path in files:
        try:
            content = open(path).read()
            sections.append(f"\n---\n\n## {os.path.basename(path)}\n\n`{path}`\n\n{content}\n")
        except Exception as e:
            log.warning(f"Could not read {path}: {e}")
    out_path = f"/tmp/conductor_package_{platform}_{int(time.time())}.md"
    with open(out_path, 'w') as f:
        f.write(''.join(sections))
    log.info(f"Consolidated {len(files)} files → {out_path}")
    return out_path


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

        # Patch core.atspi PID filter so ALL code paths find the right Firefox
        self._patch_pid_filter()

        log.info(f"ConductorBot initialized: platform={platform}, "
                 f"display={display}, queue={queue}")

    def _patch_pid_filter(self):
        """Patch core.atspi so find_firefox returns only our display's Firefox."""
        pid_file = f'/tmp/firefox_pid_{self.display}'
        try:
            with open(pid_file) as f:
                target_pid = int(f.read().strip())
        except (FileNotFoundError, ValueError):
            # Try /proc scan — look for firefox main process on our display
            for pid_str in os.listdir('/proc'):
                if not pid_str.isdigit():
                    continue
                try:
                    with open(f'/proc/{pid_str}/cmdline', 'rb') as f:
                        cmd = f.read().decode(errors='replace')
                    if 'firefox' not in cmd.lower():
                        continue
                    # Skip child processes (contentproc, crashhelper)
                    if '-contentproc' in cmd or 'crashhelper' in cmd:
                        continue
                    with open(f'/proc/{pid_str}/environ', 'rb') as f:
                        env = f.read().decode(errors='replace')
                    if f'DISPLAY={self.display}' in env.split('\0'):
                        target_pid = int(pid_str)
                        break
                except:
                    continue
            else:
                log.warning("Could not find Firefox PID — will use default find_firefox")
                return

        log.info(f"PID filter: Firefox on {self.display} = PID {target_pid}")

        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi

        import core.atspi as atspi_mod
        orig = atspi_mod.find_firefox_for_platform

        def filtered_find(platform_name=None, **kwargs):
            desktop = Atspi.get_desktop(0)
            for i in range(desktop.get_child_count()):
                app = desktop.get_child_at_index(i)
                try:
                    if app.get_process_id() == target_pid:
                        return app
                except:
                    continue
            return orig(platform_name)

        atspi_mod.find_firefox_for_platform = filtered_find
        if hasattr(atspi_mod, 'find_firefox'):
            atspi_mod.find_firefox = filtered_find

        # Also set hmm_bot PID
        try:
            import agents.hmm_bot as bot
            bot._our_firefox_pid = target_pid
            bot._cached_firefox.clear()
            bot._cached_doc.clear()
        except:
            pass

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
        """Execute a single task using hmm_bot's proven functions.

        Direct file consolidation (no MCP plan state / Redis locks).
        hmm_bot for: navigate, attach, send, wait, extract (proven 123K runs)

        Returns result dict with status, content, elapsed.
        """
        import agents.hmm_bot as bot
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

        # Step 1: Consolidate identity files + attachment (no Redis plan state)
        consolidated_file = _consolidate_package(self.platform, attachment)

        # Step 2: Navigate fresh session (hmm_bot — proven)
        log.info(f"Navigating to fresh session")
        if not bot.navigate_fresh_session(self.platform):
            return {"status": "error", "error": "Navigation failed",
                    "elapsed": time.time() - t0}

        # Step 3: Attach file (hmm_bot — proven)
        if consolidated_file and os.path.exists(consolidated_file):
            log.info(f"Attaching {os.path.basename(consolidated_file)}")
            if not bot.attach_file(self.platform, consolidated_file):
                return {"status": "error", "error": "Attach failed",
                        "elapsed": time.time() - t0}

        # Step 4: Send prompt (hmm_bot — proven)
        log.info(f"Sending prompt ({len(message)} chars)")
        if not bot.send_prompt(self.platform, message):
            return {"status": "error", "error": "Send failed",
                    "elapsed": time.time() - t0}

        # Verify send: click send button if still visible
        time.sleep(1)
        from core.tree import find_elements as _fe
        from core.interact import atspi_click as _ac
        ff = bot.get_firefox(self.platform)
        if ff:
            els = _fe(ff)
            for e in els:
                n = (e.get('name') or '').strip()
                if n in ('Send prompt', 'Send', 'Submit', 'Send message') and e.get('role') == 'push button':
                    log.info(f"Send button '{n}' still visible — clicking")
                    _ac(e) if e.get('atspi_obj') else inp.click_at(e['x'], e['y'])
                    time.sleep(1)
                    break

        log.info(f"Sent.")

        # Step 5: Wait for response (hmm_bot — proven)
        timeout = task.get("timeout", 600)
        response_ready = self._wait_for_response(timeout)

        if not response_ready:
            return {"status": "timeout", "error": f"No response after {timeout}s",
                    "elapsed": time.time() - t0}

        # Step 6: Extract response (hmm_bot — proven)
        # Extra scrolling for long responses
        for _ in range(5):
            inp.press_key('End')
            time.sleep(0.3)
        time.sleep(1)

        # Claude: click Scroll to bottom button
        if self.platform == 'claude':
            from core.tree import find_elements
            from core.interact import atspi_click
            ff = bot.get_firefox(self.platform)
            if ff:
                els = find_elements(ff)
                for e in els:
                    if (e.get('name') or '').strip() == 'Scroll to bottom':
                        atspi_click(e) if e.get('atspi_obj') else inp.click_at(e['x'], e['y'])
                        log.info("Clicked 'Scroll to bottom'")
                        time.sleep(2)
                        break

        content = bot.extract_response(self.platform)
        elapsed = time.time() - t0

        if not content or len(content) < 10:
            return {"status": "error", "error": f"Extract failed ({len(content) if content else 0} chars)",
                    "elapsed": elapsed}

        log.info(f"Extracted: {len(content)} chars in {elapsed:.1f}s")

        return {
            "status": "completed",
            "content": content,
            "url": "",
            "elapsed": elapsed,
            "word_count": len(content.split()),
        }

    def _wait_for_response(self, timeout: int = 600) -> bool:
        """Wait for response using hmm_bot's proven polling (123K enrichments)."""
        try:
            import agents.hmm_bot as bot
            # Set PID filter and clear caches for this display
            pid_file = f'/tmp/firefox_pid_{self.display}'
            try:
                with open(pid_file) as f:
                    bot._our_firefox_pid = int(f.read().strip())
            except (FileNotFoundError, ValueError):
                pass
            bot._cached_firefox.clear()
            bot._cached_doc.clear()
            return bot.wait_for_response(self.platform, timeout=timeout)
        except Exception as e:
            log.error(f"wait_for_response error: {e}")
            return False

    def _check_display_health(self) -> bool:
        """Verify display, Firefox, and AT-SPI bus are alive."""
        # Check Firefox process
        pid_file = f'/tmp/firefox_pid_{self.display}'
        try:
            with open(pid_file) as f:
                ff_pid = int(f.read().strip())
            os.kill(ff_pid, 0)  # Check process exists
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            log.error(f"Firefox not running on {self.display}")
            return False

        # Check AT-SPI bus file exists and is non-empty
        bus_file = f'/tmp/a11y_bus_{self.display}'
        try:
            with open(bus_file) as f:
                bus = f.read().strip()
            if not bus:
                log.error(f"AT-SPI bus file empty for {self.display}")
                return False
        except FileNotFoundError:
            pass  # Shared bus mode — no bus file is OK

        return True

    def run(self):
        """Main loop: pull tasks, execute, report. Runs until max_cycles or forever."""
        log.info(f"Starting ConductorBot: platform={self.platform}, "
                 f"display={self.display}, queue={self.queue}")

        consecutive_errors = 0

        while True:
            if self.max_cycles > 0 and self.cycle_count >= self.max_cycles:
                log.info(f"Reached max cycles ({self.max_cycles}). Stopping.")
                break

            # Health check before pulling tasks
            if consecutive_errors > 0 and not self._check_display_health():
                log.error("Display health check failed — halting.")
                self.report_error(
                    {"task_id": "health_check"},
                    f"Display {self.display} unhealthy (Firefox or AT-SPI bus dead)"
                )
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
