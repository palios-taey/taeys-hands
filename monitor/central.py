#!/usr/bin/env python3
"""Central response monitor — one process per machine, cycles all active sessions.

Simple state machine per session:
  1. Check: is stop button visible?
  2. If yes → mark stop_seen=True (AI is generating)
  3. If no AND stop_seen was True → COMPLETE, notify via Redis
  4. If no AND stop_seen was False → still waiting for generation to start

URL navigation: verifies session URL matches current tab, navigates if mismatched.
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

# Display detection
DISPLAY = os.environ.get('DISPLAY', ':0')

# Shared modules — only what workers-based monitoring needs
from core.platforms import CHAT_PLATFORMS
from storage.redis_pool import node_key, NODE_ID

# Verify node ID matches expectations — mismatch breaks monitor notifications
if NODE_ID and '-d' in NODE_ID and not os.environ.get('TAEY_NODE_ID'):
    import warnings
    warnings.warn(
        f"monitor using auto-detected node ID '{NODE_ID}'. "
        f"Set TAEY_NODE_ID in .env or environment to match MCP server.",
        RuntimeWarning, stacklevel=1,
    )

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
        """Find ALL active sessions across ALL node_ids.

        Two discovery paths (backward compatible):
          1. SET-based: read from taey:*:active_session_ids SETs (new MCP servers)
          2. SCAN-based: find taey:*:active_session:* keys (old MCP servers)

        Sessions found via SCAN are migrated into the appropriate SET so
        future cycles find them instantly.
        """
        if not self.rc:
            return []

        seen_keys = set()
        sessions = []

        # --- Path 1: SET-based (new MCP servers) ---
        set_keys = []
        cursor = 0
        while True:
            cursor, keys = self.rc.scan(cursor, match="taey:*:active_session_ids", count=100)
            set_keys.extend(keys)
            if cursor == 0:
                break
        for set_key in set_keys:
            try:
                session_keys = self.rc.smembers(set_key)
            except Exception:
                continue
            for key in session_keys:
                if key in seen_keys:
                    continue
                try:
                    data = self.rc.get(key)
                    if data:
                        s = json.loads(data)
                        s['_redis_key'] = key
                        s['_set_key'] = set_key
                        sessions.append(s)
                        seen_keys.add(key)
                    else:
                        # Session expired — remove from SET
                        self.rc.srem(set_key, key)
                except Exception:
                    pass

        # --- Path 2: SCAN for plain session keys (old MCP servers) ---
        cursor = 0
        while True:
            cursor, keys = self.rc.scan(cursor, match="taey:*:active_session:*", count=100)
            for key in keys:
                if key in seen_keys:
                    continue
                try:
                    data = self.rc.get(key)
                    if not data:
                        continue
                    s = json.loads(data)
                    # Derive the SET key: taey:claude:active_session:xyz → taey:claude:active_session_ids
                    # Key format: taey:{node_id}:active_session:{monitor_id}
                    parts = key.rsplit(':active_session:', 1)
                    if len(parts) == 2:
                        set_key = parts[0] + ':active_session_ids'
                    else:
                        set_key = None
                    # Migrate into SET for future cycles
                    if set_key:
                        self.rc.sadd(set_key, key)
                    s['_redis_key'] = key
                    s['_set_key'] = set_key
                    sessions.append(s)
                    seen_keys.add(key)
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
            self.rc.setex(key, session.get('timeout', 7200), json.dumps(
                {k: v for k, v in session.items() if k not in ('_redis_key', '_set_key')}))

    def _remove_session(self, session: Dict):
        if not self.rc:
            return
        key = session.get('_redis_key')
        if key:
            self.rc.delete(key)
            # Remove from deterministic SET
            set_key = session.get('_set_key')
            if set_key:
                self.rc.srem(set_key, key)
            else:
                # Fallback: try all known SET keys
                cursor = 0
                while True:
                    cursor, skeys = self.rc.scan(cursor, match="taey:*:active_session_ids", count=100)
                    for sk in skeys:
                        self.rc.srem(sk, key)
                    if cursor == 0:
                        break

    def _plan_active(self) -> bool:
        """Check if any session has an active plan (DISPLAY-scoped lock).
        When set, monitor must not cycle tabs."""
        if not self.rc:
            return False
        display = os.environ.get('DISPLAY', ':0')
        return bool(self.rc.exists(f"taey:plan_active:{display}"))


    # ── Session checking (worker-based only) ─────────────────────
    # Direct AT-SPI methods removed: _is_landing_url, _navigate_to_url,
    # _is_stop_button, _is_canvas_stop, _scan_for_stop_button, _check_session.
    # All monitoring goes through workers. Monitor never touches DISPLAY :0.

    def _check_session_with_stop(self, session: Dict, stop_found: bool) -> bool:
        """Check session completion using worker-provided stop-button state.

        Same 4-state machine as _check_session but without direct AT-SPI.
        """
        platform = session['platform']
        monitor_id = session['monitor_id']
        started_ts = session.get('started_ts', time.time())
        timeout = session.get('timeout', 7200)
        elapsed = int(time.time() - started_ts)
        stop_seen = session.get('stop_seen', False)

        if stop_found and not stop_seen:
            session['stop_seen'] = True
            session['generating_since'] = time.time()
            self._update_session(session)
            _log(f"[{platform}/{monitor_id}] stop=YES (generation started, {elapsed}s)")
            return False

        if stop_found and stop_seen:
            _log(f"[{platform}/{monitor_id}] stop=YES (still generating, {elapsed}s)")
            return False

        if not stop_found and stop_seen:
            _log(f"[{platform}/{monitor_id}] stop=NO, stop_seen=True → COMPLETE ({elapsed}s)")
            self._notify(session, "response_complete", "stop_button")
            return True

        _log(f"[{platform}/{monitor_id}] stop=NO, waiting ({elapsed}s)")
        if time.time() - started_ts > timeout:
            _log(f"[{platform}/{monitor_id}] Timeout after {timeout}s")
            self._notify(session, "timeout", "timeout")
            return True

        return False

    def run(self):
        """Main loop — poll workers for stop-button state every cycle."""
        _log(f"Central monitor started (node={NODE_ID}, cycle={self.cycle_interval}s)")
        while True:
            try:
                self._cycle()
            except KeyboardInterrupt:
                _log("Interrupted — exiting")
                break
            except Exception as e:
                _log(f"Cycle error: {e}")
            time.sleep(self.cycle_interval)

    def _cycle(self):
        """One monitor cycle: find sessions, poll workers, check completion."""
        if self.rc:
            try:
                self.rc.ping()
            except Exception:
                _log("Redis connection lost — reconnecting")
                self.rc = self._connect_redis()

        if self._plan_active():
            return

        sessions = self._get_sessions()
        if not sessions:
            return

        from workers.manager import send_to_worker
        from core.platforms import get_platform_display

        by_platform: Dict[str, List[Dict]] = {}
        for s in sessions:
            by_platform.setdefault(s['platform'], []).append(s)

        _log(f"Cycle: {len(sessions)} session(s) on {set(by_platform.keys())}")

        completed = []
        for platform, platform_sessions in by_platform.items():
            if not get_platform_display(platform):
                continue
            try:
                result = send_to_worker(platform, {'cmd': 'check_stop'}, timeout=10.0)
                stop_found = result.get('stop_found', False)
            except Exception as e:
                _log(f"[{platform}] Worker check_stop failed: {e}")
                continue

            for session in platform_sessions:
                if self._check_session_with_stop(session, stop_found):
                    completed.append(session)

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
