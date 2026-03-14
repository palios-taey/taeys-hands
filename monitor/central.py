#!/usr/bin/env python3
"""Central response monitor — one process per machine, cycles all active sessions.

Simple state machine per session:
  1. Check: is stop button visible?
  2. If yes → mark stop_seen=True (AI is generating)
  3. If no AND stop_seen was True → COMPLETE, notify via Redis
  4. If no AND stop_seen was False → still waiting for generation to start

NO URL navigation. Only tab switching via keyboard shortcuts.
NO fixed coordinates. Stop button found by AT-SPI name matching.
Uses core modules — no duplicated helpers.

Usage:
    python3 -m monitor.central
    python3 monitor/central.py --cycle-interval 10

Environment:
    DISPLAY             X11 display (auto-detected)
    REDIS_HOST          Redis host (default: 127.0.0.1)
    REDIS_PORT          Redis port (default: 6379)
    TAEY_NODE_ID        Node identifier (default: hostname)
    MONITOR_CYCLE_SEC   Seconds between full cycles (default: 10)
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

# Ensure project root is on path so core/ imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# .env loading
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _val = _line.split('=', 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# Display detection (must happen before AT-SPI import)
from core.atspi import detect_display
DISPLAY = detect_display()
os.environ['DISPLAY'] = DISPLAY

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

# Use shared modules — no duplication
from core.atspi import find_firefox, get_platform_document, get_document_url
from core.input import press_key
from core.platforms import TAB_SHORTCUTS, CHAT_PLATFORMS
from storage.redis_pool import node_key, NODE_ID

# Redis
try:
    import redis as _redis_mod
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

CYCLE_TIMEOUT_SECONDS = 45


class CycleTimeout(Exception):
    pass


def _cycle_timeout_handler(signum, frame):
    raise CycleTimeout("Cycle timed out")


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [monitor] {msg}", flush=True)


def _load_stop_patterns() -> Dict[str, List[str]]:
    """Load stop patterns from platform YAML configs."""
    import yaml
    patterns = {}
    platforms_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')
    for platform in CHAT_PLATFORMS:
        try:
            with open(os.path.join(platforms_dir, f'{platform}.yaml')) as f:
                config = yaml.safe_load(f) or {}
            patterns[platform] = config.get('stop_patterns', ['stop'])
        except Exception:
            patterns[platform] = ['stop']
    return patterns


class CentralMonitor:
    """Single monitor process — cycles active sessions, detects completion."""

    def __init__(self, cycle_interval: int = 10):
        self.cycle_interval = cycle_interval
        self.rc = self._connect_redis()
        self.stop_patterns = _load_stop_patterns()
        if not self.rc:
            _log("WARNING: No Redis — monitor cannot track sessions")

    def _connect_redis(self):
        if not REDIS_AVAILABLE:
            return None
        try:
            c = _redis_mod.Redis(
                host=os.environ.get('REDIS_HOST', '127.0.0.1'),
                port=int(os.environ.get('REDIS_PORT', 6379)),
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
            c.ping()
            return c
        except Exception as e:
            _log(f"Redis connection failed: {e}")
            return None

    # ── Redis session registry ──────────────────────────────────────────

    def _get_sessions(self) -> List[Dict]:
        """Find ALL active sessions across ALL node_ids."""
        if not self.rc:
            return []
        sessions = []
        cursor = 0
        while True:
            cursor, keys = self.rc.scan(cursor, match="taey:*:active_session:*", count=100)
            for key in keys:
                try:
                    data = self.rc.get(key)
                    if data:
                        s = json.loads(data)
                        s['_redis_key'] = key
                        sessions.append(s)
                except Exception:
                    pass
            if cursor == 0:
                break
        return sessions

    def _update_session(self, session: Dict):
        if not self.rc:
            return
        key = session.get('_redis_key')
        if key:
            self.rc.setex(key, session.get('timeout', 3600), json.dumps(
                {k: v for k, v in session.items() if k != '_redis_key'}))

    def _remove_session(self, session: Dict):
        if not self.rc:
            return
        key = session.get('_redis_key')
        if key:
            self.rc.delete(key)

    def _plan_active(self) -> bool:
        """Check if any session has an active plan (global lock).
        When set, monitor must not cycle tabs."""
        if not self.rc:
            return False
        return bool(self.rc.exists("taey:plan_active"))

    # ── AT-SPI: stop button detection ───────────────────────────────

    def _is_stop_button(self, name: str, platform: str) -> bool:
        """Check if element name matches a stop pattern for this platform."""
        if not name or len(name) > 50:
            return False
        patterns = self.stop_patterns.get(platform, ['stop'])
        return any(p in name.lower().strip() for p in patterns)

    def _is_canvas_stop(self, stop_obj) -> bool:
        """Filter ChatGPT canvas Stop button (persistent alongside Update)."""
        try:
            comp = stop_obj.get_component_iface()
            if not comp:
                return False
            stop_y = comp.get_extents(0).y
            parent = stop_obj.get_parent()
            if not parent:
                return False
            for level in [parent, parent.get_parent()]:
                if not level:
                    continue
                for i in range(level.get_child_count()):
                    try:
                        sib = level.get_child_at_index(i)
                        if not sib:
                            continue
                        targets = [sib]
                        if level == parent.get_parent():
                            targets = [sib.get_child_at_index(j)
                                       for j in range(sib.get_child_count())
                                       if sib.get_child_at_index(j)]
                        for t in targets:
                            if not t:
                                continue
                            if 'button' in (t.get_role_name() or '') and \
                               'update' in (t.get_name() or '').lower():
                                tc = t.get_component_iface()
                                if tc and abs(tc.get_extents(0).y - stop_y) < 50:
                                    return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    def _scan_for_stop_button(self, doc, platform: str) -> bool:
        """Walk AT-SPI tree looking for stop button. Returns True if found."""
        candidates = []

        def scan(obj, depth=0):
            if depth > 25:
                return
            try:
                role = obj.get_role_name() or ''
                name = obj.get_name() or ''
                if role in ('push button', 'button', 'toggle button'):
                    if self._is_stop_button(name, platform):
                        candidates.append(obj)
                for i in range(obj.get_child_count()):
                    child = obj.get_child_at_index(i)
                    if child:
                        scan(child, depth + 1)
            except Exception:
                pass

        scan(doc)

        # Filter out canvas stop buttons (ChatGPT)
        for c in candidates:
            if not self._is_canvas_stop(c):
                return True
        return False

    # ── Session checking ────────────────────────────────────────────

    def _check_session(self, session: Dict, doc, firefox) -> bool:
        """Check one session for completion. Returns True if complete (remove it).

        Simple: stop button there = generating. Not there = complete.
        But AT-SPI cache is stale after tab switch — so if no stop found,
        wait 3s, get fresh document, scan again. Only declare complete if
        BOTH scans show no stop button.
        """
        platform = session['platform']
        monitor_id = session['monitor_id']

        # Force D-Bus refresh to get fresh state
        try:
            doc.clear_cache_single()
        except Exception:
            pass

        stop_found = self._scan_for_stop_button(doc, platform)
        started_ts = session.get('started_ts', time.time())
        timeout = session.get('timeout', 3600)
        elapsed = int(time.time() - started_ts)

        if stop_found:
            _log(f"[{platform}/{monitor_id}] stop=YES ({elapsed}s)")
        else:
            # No stop on first scan — AT-SPI may be stale after tab switch.
            # Wait and re-scan with fresh document before declaring complete.
            time.sleep(3)
            fresh_doc = get_platform_document(firefox, platform)
            if fresh_doc:
                try:
                    fresh_doc.clear_cache_single()
                except Exception:
                    pass
                stop_found_2 = self._scan_for_stop_button(fresh_doc, platform)
                if stop_found_2:
                    _log(f"[{platform}/{monitor_id}] stop=NO then YES — stale cache, still generating ({elapsed}s)")
                    return False
            _log(f"[{platform}/{monitor_id}] stop=NO (confirmed) → COMPLETE ({elapsed}s)")
            self._notify(session, "response_complete", "stop_button")
            return True

        # Timeout check
        if time.time() - started_ts > timeout:
            _log(f"[{platform}/{monitor_id}] Timeout after {timeout}s")
            self._notify(session, "timeout", "timeout")
            return True

        return False

    def _notify(self, session: Dict, status: str, detection: str):
        """Send notification via Redis for the orchestrator daemon to pick up."""
        target_node = session.get('tmux_session', NODE_ID)
        notification = {
            "monitor_id": session.get('monitor_id'),
            "platform": session.get('platform'),
            "node_id": target_node,
            "status": status,
            "message": f"{status} on {session.get('platform')}",
            "detection": detection,
            "timestamp": datetime.now().isoformat(),
            "session_id": session.get('session_id'),
            "tmux_session": target_node,
            "url": session.get('url'),
            "elapsed_seconds": int(time.time() - session.get('started_ts', time.time())),
            "requires_action": status in ("response_complete", "response_ready"),
        }
        nj = json.dumps(notification)
        notify_key = f"taey:{target_node}:notifications"
        if self.rc:
            try:
                self.rc.rpush(notify_key, nj)
                _log(f"[{session.get('platform')}/{session.get('monitor_id')}] "
                     f"Notified {target_node}: {status}")
            except Exception as e:
                _log(f"Redis notification error: {e}")
        else:
            _log(f"No Redis — notification for {session.get('monitor_id')} dropped")

    # ── Main cycle ──────────────────────────────────────────────────

    def run(self):
        _log(f"Central monitor started (node={NODE_ID}, display={DISPLAY}, "
             f"cycle={self.cycle_interval}s)")

        while True:
            old_handler = signal.signal(signal.SIGALRM, _cycle_timeout_handler)
            signal.alarm(CYCLE_TIMEOUT_SECONDS)
            try:
                self._cycle()
            except KeyboardInterrupt:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
                _log("Interrupted — exiting")
                break
            except CycleTimeout:
                _log("CYCLE TIMEOUT — AT-SPI or Redis hung, skipping")
            except Exception as e:
                _log(f"Cycle error: {e}")
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
            time.sleep(self.cycle_interval)

    def _cycle(self):
        # Reconnect Redis if needed
        if self.rc:
            try:
                self.rc.ping()
            except Exception:
                _log("Redis connection lost — reconnecting")
                self.rc = self._connect_redis()

        # Check plan lock — full stop
        if self._plan_active():
            _log("Plan active — skipping cycle")
            return

        sessions = self._get_sessions()
        if not sessions:
            return

        firefox = find_firefox()
        if not firefox:
            _log("Firefox not found")
            return

        # Group by platform
        by_platform: Dict[str, List[Dict]] = {}
        for s in sessions:
            by_platform.setdefault(s['platform'], []).append(s)

        _log(f"Cycle: {len(sessions)} session(s) on {set(by_platform.keys())}")

        completed = []

        for platform, platform_sessions in by_platform.items():
            if self._plan_active():
                break

            if platform not in TAB_SHORTCUTS:
                continue

            # Switch to platform tab
            press_key(TAB_SHORTCUTS[platform])
            time.sleep(1.5)

            # Get document for this platform
            doc = get_platform_document(firefox, platform)
            if not doc:
                _log(f"[{platform}] No document found, skipping")
                continue

            # Check all sessions on this platform
            for session in platform_sessions:
                if self._plan_active():
                    break
                if self._check_session(session, doc, firefox):
                    completed.append(session)
                time.sleep(0.5)

        # Remove completed sessions
        for s in completed:
            self._remove_session(s)


# ── __init__.py guard ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Central response monitor")
    parser.add_argument('--cycle-interval', type=int,
                        default=int(os.environ.get('MONITOR_CYCLE_SEC', '10')))
    args = parser.parse_args()

    CentralMonitor(cycle_interval=args.cycle_interval).run()


if __name__ == '__main__':
    main()
