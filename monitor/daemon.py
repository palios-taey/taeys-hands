#!/usr/bin/env python3
"""
Background Monitor Daemon for Taey's Hands.

Monitors chat platform responses using AT-SPI events.
Runs as an independent subprocess, spawned by send_message.

Usage:
    python3 monitor/daemon.py --platform gemini --monitor-id abc123 \
        --baseline-copy-count 5 --session-id uuid --user-message-id uuid

Detection strategy:
    Stop button appears = AI generating (GENERATING state)
    Stop button disappears = response complete (COMPLETE state)
    This is more reliable than copy button counting (scroll-dependent).
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any

# Instance-scoped key prefix (must match storage/redis_pool.py logic)
def _detect_node_id() -> str:
    """Auto-detect instance ID: TAEY_NODE_ID > tmux session > hostname."""
    explicit = os.environ.get('TAEY_NODE_ID')
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ['tmux', 'display-message', '-p', '#S'],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return socket.gethostname()

_NODE_ID = _detect_node_id()


def _node_key(suffix: str) -> str:
    """Instance-scoped Redis key (matches storage.redis_pool.node_key)."""
    return f"taey:{_NODE_ID}:{suffix}"

# =========================================================================
# Load .env (daemon runs as subprocess, doesn't inherit server's env loading)
# =========================================================================
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _val = _line.split('=', 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# =========================================================================
# Set DISPLAY before AT-SPI import
# =========================================================================


def _detect_display() -> str:
    """Detect active X display.

    Checks DISPLAY env var first (set by spawner for multi-instance isolation),
    then falls back to lock file detection.
    """
    env_display = os.environ.get('DISPLAY')
    if env_display:
        return env_display
    for d in [':0', ':1']:
        if os.path.exists(f'/tmp/.X{d[1:]}-lock'):
            return d
    for d in [':0', ':1']:
        if os.path.exists(f'/tmp/.X11-unix/X{d[1:]}'):
            return d
    return ':0'


DISPLAY = _detect_display()
os.environ['DISPLAY'] = DISPLAY

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi, GLib

# Optional dependencies
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False


# =========================================================================
# Platform patterns
# =========================================================================

STOP_PATTERNS = {
    'chatgpt': ['stop', 'stop generating'],
    'claude': ['stop', 'stop response'],
    'gemini': ['stop', 'cancel'],
    'grok': ['stop', 'stop generating'],
    'perplexity': ['stop', 'cancel'],
}

URL_PATTERNS = {
    'chatgpt': 'chatgpt.com',
    'claude': 'claude.ai',
    'gemini': 'gemini.google.com',
    'grok': 'grok.com',
    'perplexity': 'perplexity.ai',
}


# =========================================================================
# Monitor daemon
# =========================================================================

class MonitorDaemon:
    """Event-driven AT-SPI monitor for chat platform responses.

    State machine:
        IDLE -> GENERATING (stop button appears)
        GENERATING -> SETTLING (stop disappears, settle > 0, cycle 1)
        SETTLING -> GENERATING (new stop button appears during settle)
        SETTLING -> COMPLETE (settle expires, no new stop button)
        GENERATING -> COMPLETE (stop disappears, final cycle or settle == 0)
    """

    def __init__(self, platform: str, monitor_id: str,
                 baseline_copy_count: int,
                 session_id: Optional[str] = None,
                 user_message_id: Optional[str] = None,
                 timeout_seconds: int = 3600,
                 tmux_session: Optional[str] = None,
                 settle_seconds: int = 0):
        self.platform = platform.lower()
        self.monitor_id = monitor_id
        self.baseline_copy_count = baseline_copy_count
        self.session_id = session_id
        self.user_message_id = user_message_id
        self.timeout_seconds = timeout_seconds
        self.tmux_session = tmux_session
        self.settle_seconds = settle_seconds

        self.state = "IDLE"
        self.start_time = time.time()
        self.stop_button_seen = False
        self.cycle_count = 0
        self.settle_start = None

        self.poll_interval_ms = 3000
        self.initial_delay_ms = 3000  # Reduced from 10s - fast responses missed at 10s
        self.no_stop_warning_seconds = 45  # Increased to account for slower initial load
        self.no_stop_warned = False
        self.verbose_logged = False

        self.main_loop = GLib.MainLoop()

        # Connect services
        self.redis_client = self._connect_redis()
        self.neo4j_driver = self._connect_neo4j()
        self.firefox_app = self._find_firefox()

        if not self.firefox_app:
            self._log("ERROR: Firefox not found in AT-SPI tree")
            sys.exit(1)

        self._log(f"Initialized for {platform}, baseline={baseline_copy_count}")

    def _log(self, message: str):
        """Log with timestamp."""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{self.monitor_id}] {message}", flush=True)

    def _connect_redis(self):
        """Connect to Redis for notifications."""
        if not REDIS_AVAILABLE:
            return None
        try:
            client = redis.Redis(
                host=os.environ.get('REDIS_HOST', '192.168.x.10'),
                port=int(os.environ.get('REDIS_PORT', 6379)),
                decode_responses=True,
            )
            client.ping()
            self._log("Redis connected")
            return client
        except Exception as e:
            self._log(f"Redis connection failed: {e}")
            return None

    def _connect_neo4j(self):
        """Connect to Neo4j for message storage."""
        if not NEO4J_AVAILABLE:
            return None
        try:
            uri = os.environ.get('NEO4J_URI', 'bolt://192.168.x.10:7689')
            driver = GraphDatabase.driver(uri, auth=None)
            driver.verify_connectivity()
            self._log("Neo4j connected")
            return driver
        except Exception as e:
            self._log(f"Neo4j connection failed: {e}")
            return None

    def _find_firefox(self):
        """Find Firefox in AT-SPI desktop tree."""
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if 'firefox' in (app.get_name() or '').lower():
                return app
        return None

    def _find_platform_document(self):
        """Find the document element for this platform's tab."""
        if not self.firefox_app:
            return None

        url_pattern = URL_PATTERNS.get(self.platform, self.platform)

        def search(obj, depth=0):
            if depth > 10:
                return None
            try:
                if (obj.get_role_name() or '') == 'document web':
                    iface = obj.get_document_iface()
                    if iface:
                        url = iface.get_document_attribute_value('DocURL')
                        if url and url_pattern in url.lower():
                            return obj

                for i in range(obj.get_child_count()):
                    child = obj.get_child_at_index(i)
                    if child:
                        result = search(child, depth + 1)
                        if result:
                            return result
            except Exception:
                pass
            return None

        return search(self.firefox_app)

    def _is_stop_button(self, name: str) -> bool:
        """Check if button name matches stop patterns.

        Real stop buttons have short names like "Stop" or "Stop generating".
        Content buttons (e.g. Perplexity Deep Research) can have 19K+ char
        names containing "stop" as a regular word. Filter by length.
        """
        if not name or len(name) > 50:
            return False
        name_lower = name.lower().strip()
        patterns = STOP_PATTERNS.get(self.platform, ['stop'])
        return any(p in name_lower for p in patterns)

    def _is_canvas_stop(self, stop_obj) -> bool:
        """Check if a stop button is ChatGPT's canvas stop (not generation stop).

        Canvas has a persistent "Stop" + "Update" button pair. The generation
        stop button is standalone. We detect canvas stop by checking if an
        "Update" button exists at the same Y position (within 50px).
        """
        if self.platform != 'chatgpt':
            return False

        try:
            stop_comp = stop_obj.get_component_iface()
            if not stop_comp:
                return False
            stop_ext = stop_comp.get_extents(0)  # 0 = ATSPI_COORD_TYPE_SCREEN
            stop_y = stop_ext.y

            # Walk siblings looking for "Update" button at same Y
            parent = stop_obj.get_parent()
            if not parent:
                return False

            for i in range(parent.get_child_count()):
                try:
                    sibling = parent.get_child_at_index(i)
                    if not sibling:
                        continue
                    sib_role = sibling.get_role_name() or ''
                    sib_name = (sibling.get_name() or '').lower()
                    if sib_role in ('push button', 'button') and 'update' in sib_name:
                        sib_comp = sibling.get_component_iface()
                        if sib_comp:
                            sib_ext = sib_comp.get_extents(0)
                            if abs(sib_ext.y - stop_y) < 50:
                                self._log(f"Canvas stop filtered: Stop@y={stop_y} near Update@y={sib_ext.y}")
                                return True
                except Exception:
                    continue

            # Also check grandparent (button groups may be wrapped)
            grandparent = parent.get_parent()
            if grandparent:
                for i in range(grandparent.get_child_count()):
                    try:
                        uncle = grandparent.get_child_at_index(i)
                        if not uncle:
                            continue
                        # Check uncle's children for Update
                        for j in range(uncle.get_child_count()):
                            child = uncle.get_child_at_index(j)
                            if not child:
                                continue
                            ch_role = child.get_role_name() or ''
                            ch_name = (child.get_name() or '').lower()
                            if ch_role in ('push button', 'button') and 'update' in ch_name:
                                ch_comp = child.get_component_iface()
                                if ch_comp:
                                    ch_ext = ch_comp.get_extents(0)
                                    if abs(ch_ext.y - stop_y) < 50:
                                        self._log(f"Canvas stop filtered (grandparent): Stop@y={stop_y} near Update@y={ch_ext.y}")
                                        return True
                    except Exception:
                        continue

        except Exception as e:
            self._log(f"Canvas stop check error: {e}")

        return False

    def _notify_tmux(self, platform: str):
        """Send notification to the spawning Claude session via tmux send-keys.

        Uses the tmux session name passed by send_message (--tmux-session).
        Falls back to hostname-based guessing if not provided.

        Claude Code uses Ink (React TUI) which intercepts Enter via
        autocomplete. The Escape-Enter pattern dismisses autocomplete
        first, allowing Enter to trigger submit:
          1. send-keys text    (text appears in input)
          2. sleep 0.3s        (autocomplete engages)
          3. send-keys Escape  (dismiss autocomplete)
          4. sleep 0.1s
          5. send-keys Enter   (now triggers submit)
        See: github.com/anthropics/claude-code/issues/15553
        """
        msg = f"Response ready on {platform}. Extract it now with taey_quick_extract('{platform}')"

        # Use explicit session from spawner (correct instance isolation)
        if self.tmux_session:
            sessions_to_try = [self.tmux_session]
        else:
            # Legacy fallback: guess session name
            sessions_to_try = ['jetson-claude', 'thor-claude', 'taeys-hands', 'claude', 'main']

        for session in sessions_to_try:
            try:
                # Step 1: Send text
                result = subprocess.run(
                    ['tmux', 'send-keys', '-t', session, '--', msg],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode != 0:
                    continue
                # Step 2: Wait for autocomplete to engage
                time.sleep(0.3)
                # Step 3: Escape dismisses autocomplete
                subprocess.run(
                    ['tmux', 'send-keys', '-t', session, 'Escape'],
                    capture_output=True, text=True, timeout=5,
                )
                # Step 4: Brief pause
                time.sleep(0.1)
                # Step 5: Enter now triggers submit (not swallowed by autocomplete)
                subprocess.run(
                    ['tmux', 'send-keys', '-t', session, 'Enter'],
                    capture_output=True, text=True, timeout=5,
                )
                self._log(f"tmux notification sent to session '{session}'")
                return
            except Exception:
                continue
        self._log("tmux notification failed: no session found")

    def _notify_agent(self, status: str, message: str, extra: Dict = None):
        """Write notification to Redis for agent injection."""
        notification = {
            "monitor_id": self.monitor_id,
            "platform": self.platform,
            "node_id": _NODE_ID,
            "status": status,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "elapsed_seconds": int(time.time() - self.start_time),
        }
        if extra:
            notification.update(extra)

        notification_json = json.dumps(notification)

        # tmux notification for response_ready (works even when Claude Code is idle)
        if status == "response_ready":
            self._notify_tmux(self.platform)

        if self.redis_client:
            try:
                self.redis_client.rpush(_node_key("notifications"), notification_json)
                self.redis_client.setex(
                    _node_key(f"monitor:{self.monitor_id}"),
                    3600,
                    notification_json,
                )
                self._log(f"Notification sent: {status}")
            except Exception as e:
                self._log(f"Redis notification error: {e}")
        else:
            path = f"/tmp/taey_monitor_{self.monitor_id}.json"
            try:
                with open(path, 'w') as f:
                    json.dump(notification, f)
                self._log(f"Notification written to {path}")
            except Exception as e:
                self._log(f"File notification failed: {e}")

    def _on_first_poll(self) -> bool:
        """First poll after initial delay."""
        self._log("Initial delay complete, starting regular polling")
        self._on_poll_check()
        if self.state != "COMPLETE":
            GLib.timeout_add(self.poll_interval_ms, self._on_poll_check)
        return False

    def _on_poll_check(self) -> bool:
        """Periodic check for response completion."""
        elapsed = time.time() - self.start_time

        # Timeout
        if elapsed > self.timeout_seconds:
            self._log(f"Timeout after {elapsed:.0f}s")
            self._notify_agent("timeout", f"Timed out after {elapsed:.0f}s")
            self.main_loop.quit()
            return False

        # Early warning: no stop button detected
        if (not self.stop_button_seen and not self.no_stop_warned
                and elapsed > self.no_stop_warning_seconds):
            self._log("WARNING: No stop button detected - possible submission error")
            self._notify_agent(
                "warning",
                f"No stop button detected after {elapsed:.0f}s - message may not have been sent",
                {"warning_type": "no_stop_button"},
            )
            self.no_stop_warned = True

        # Find platform document
        platform_doc = self._find_platform_document()
        if not platform_doc:
            self._log("WARNING: Platform document not found, skipping poll")
            return True

        # Search for stop button in document
        all_buttons = []
        stop_candidates = []

        def find_stops(obj, depth=0):
            if depth > 25:
                return
            try:
                role = obj.get_role_name() or ''
                name = obj.get_name() or ''

                if role in ('push button', 'button'):
                    if name and not self.verbose_logged:
                        all_buttons.append(name)
                    if self._is_stop_button(name):
                        stop_candidates.append(obj)

                for i in range(obj.get_child_count()):
                    child = obj.get_child_at_index(i)
                    if child:
                        find_stops(child, depth + 1)
            except Exception:
                pass

        find_stops(platform_doc)

        # Filter out canvas stop buttons (ChatGPT-specific)
        stop_button = None
        for candidate in stop_candidates:
            if not self._is_canvas_stop(candidate):
                stop_button = candidate
                break

        # Log buttons once for debugging
        if all_buttons and not self.verbose_logged:
            self._log(f"Buttons in doc (sample): {all_buttons[:10]}")
            self.verbose_logged = True

        # Handle SETTLING state: waiting between cycles for new stop button
        if self.state == "SETTLING":
            if stop_button:
                self._log("Stop button reappeared during settle - new generation cycle")
                self.state = "GENERATING"
                self.stop_button_seen = True
                self.settle_start = None
                return True
            settle_elapsed = time.time() - self.settle_start
            if settle_elapsed > self.settle_seconds:
                self._log(f"Settle period expired ({settle_elapsed:.1f}s). Final completion.")
                self.state = "NOTIFYING"
                self._notify_agent(
                    "response_ready",
                    f"Response complete on {self.platform} - switch to tab and extract",
                    {"cycle": self.cycle_count, "requires_action": True},
                )
                self.state = "COMPLETE"
                self.main_loop.quit()
                return False
            return True  # Keep polling during settle

        if stop_button:
            if self.state == "IDLE":
                self.state = "GENERATING"
                self.stop_button_seen = True
                self._log("Stop button appeared - response generating")
        else:
            if self.stop_button_seen:
                self.cycle_count += 1

                if self.settle_seconds > 0 and self.cycle_count == 1:
                    # First cycle done, enter settling period for possible second cycle
                    self._log(f"Cycle {self.cycle_count} complete. Settling for {self.settle_seconds}s...")
                    self.state = "SETTLING"
                    self.settle_start = time.time()
                    self.stop_button_seen = False  # Reset for next cycle
                    self._notify_agent(
                        "intermediate_ready",
                        f"Intermediate response on {self.platform} (cycle {self.cycle_count}). Daemon still monitoring.",
                        {"cycle": self.cycle_count, "requires_action": True},
                    )
                    return True  # Keep polling

                # Final cycle (or no settling configured)
                self._log(f"Completion detected (cycle {self.cycle_count}): stop button disappeared")
                self.state = "NOTIFYING"
                self._notify_agent(
                    "response_ready",
                    f"Response complete on {self.platform} - switch to tab and extract",
                    {"cycle": self.cycle_count, "requires_action": True},
                )
                self.state = "COMPLETE"
                self.main_loop.quit()
                return False

        return True

    def start(self):
        """Start the monitoring loop."""
        self._log(f"Starting monitor for {self.platform}")

        if self.redis_client:
            self.redis_client.setex(
                _node_key(f"monitor:{self.monitor_id}"),
                self.timeout_seconds,
                json.dumps({
                    "status": "monitoring",
                    "platform": self.platform,
                    "node_id": _NODE_ID,
                    "started": datetime.now().isoformat(),
                    "baseline_copy_count": self.baseline_copy_count,
                }),
            )

        self._log(f"Waiting {self.initial_delay_ms / 1000:.0f}s before first poll...")
        GLib.timeout_add(self.initial_delay_ms, self._on_first_poll)

        try:
            self.main_loop.run()
        except KeyboardInterrupt:
            self._log("Interrupted by user")
            self._notify_agent("interrupted", "Monitor stopped by user")
        finally:
            if self.neo4j_driver:
                self.neo4j_driver.close()
            self._log("Monitor exited")


# =========================================================================
# CLI entry point
# =========================================================================

def main():
    parser = argparse.ArgumentParser(description='Background monitor daemon')
    parser.add_argument('--platform', required=True)
    parser.add_argument('--monitor-id', required=True)
    parser.add_argument('--baseline-copy-count', type=int, required=True)
    parser.add_argument('--session-id')
    parser.add_argument('--user-message-id')
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--tmux-session', help='tmux session to notify on completion')
    parser.add_argument('--settle-seconds', type=int, default=0,
                        help='Seconds to wait after first cycle before exiting. '
                             'If new stop button appears during settle, monitors second cycle.')

    args = parser.parse_args()

    daemon = MonitorDaemon(
        platform=args.platform,
        monitor_id=args.monitor_id,
        baseline_copy_count=args.baseline_copy_count,
        session_id=args.session_id,
        user_message_id=args.user_message_id,
        timeout_seconds=args.timeout,
        tmux_session=args.tmux_session,
        settle_seconds=args.settle_seconds,
    )
    daemon.start()


if __name__ == '__main__':
    main()
