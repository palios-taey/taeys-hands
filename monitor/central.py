#!/usr/bin/env python3
"""Central response monitor — one process per machine, cycles all active sessions.

Completion detection:
  1. Poll every 2s for stop-button visibility, send-button readiness, and content hash
  2. Persist sticky ever-seen-stop flag per monitor session in Redis
  3. PRIMARY COMPLETE when stop was seen and is now gone
  4. ENHANCED confidence when send is also ready at primary completion time
  5. Fallback COMPLETE when content hash is stable for 2 ticks and send is ready

URL navigation: verifies session URL matches current tab, navigates if mismatched.
NO fixed coordinates. Stop button found by AT-SPI name matching.
Uses core modules — no duplicated helpers.

Usage:
    python3 -m monitor.central
    python3 monitor/central.py --cycle-interval 2

Environment:
    DISPLAY             X11 display (auto-detected)
    REDIS_HOST          Redis host (default: 127.0.0.1)
    REDIS_PORT          Redis port (default: 6379)
    TAEY_NODE_ID        Node identifier (default: hostname)
    MONITOR_CYCLE_SEC   Seconds between full cycles (default: 2)
"""

import argparse
import json
import os
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
from core.extractor import ExtractorRegistry
from core.platforms import CHAT_PLATFORMS
from core.storage_pipeline import StoragePipeline
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

POLL_INTERVAL = 2.0
STABLE_TICKS = 2
DEFAULT_WORKER_TIMEOUT = 5.0


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [monitor] {msg}", flush=True)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        _log(f"Invalid float for {name}={value!r}; using {default}")
        return default


class CentralMonitor:
    """Single monitor process — cycles active sessions, detects completion."""

    def __init__(self, cycle_interval: float = POLL_INTERVAL):
        self.cycle_interval = cycle_interval
        self.rc = self._connect_redis()
        if not self.rc:
            _log("WARNING: No Redis — monitor cannot track sessions")

    def _worker_timeout(self, platform: str, operation: Optional[str] = None) -> float:
        op = operation.upper() if operation else None
        platform_key = platform.upper()
        env_names = []
        if op:
            env_names.extend([
                f"MONITOR_{op}_TIMEOUT_{platform_key}_SEC",
                f"MONITOR_{op}_TIMEOUT_SEC",
            ])
        env_names.extend([
            f"MONITOR_WORKER_TIMEOUT_{platform_key}_SEC",
            "MONITOR_WORKER_TIMEOUT_SEC",
        ])

        timeout = DEFAULT_WORKER_TIMEOUT
        for env_name in reversed(env_names):
            timeout = _env_float(env_name, timeout)
        return timeout

    def _call_worker(self, platform: str, cmd: Dict, operation: Optional[str] = None) -> Optional[Dict]:
        from workers.manager import send_to_worker

        timeout = self._worker_timeout(platform, operation)
        started = time.monotonic()
        try:
            result = send_to_worker(platform, cmd, timeout=timeout)
        except Exception as e:
            elapsed = time.monotonic() - started
            _log(
                f"[{platform}] Worker call failed for {cmd.get('cmd')} "
                f"after {elapsed:.2f}s (timeout={timeout:.2f}s): {e}"
            )
            return None

        elapsed = time.monotonic() - started
        if elapsed > timeout:
            _log(
                f"[{platform}] Worker call for {cmd.get('cmd')} exceeded "
                f"timeout budget ({elapsed:.2f}s > {timeout:.2f}s)"
            )
        return result

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
        self._clear_monitor_state(session.get('monitor_id'))
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

    def _monitor_key(self, monitor_id: str, suffix: str) -> str:
        return f"taey:monitor:{monitor_id}:{suffix}"

    def _clear_monitor_state(self, monitor_id: str):
        if not self.rc or not monitor_id:
            return
        self.rc.delete(
            self._monitor_key(monitor_id, "ever_seen_stop"),
            self._monitor_key(monitor_id, "content_hash"),
            self._monitor_key(monitor_id, "content_stable_ticks"),
        )

    def _detect_completion(self, session: Dict, worker_state: Dict) -> bool:
        """Check session completion using sticky stop visibility and content stability."""
        platform = session['platform']
        monitor_id = session['monitor_id']
        started_ts = session.get('started_ts', time.time())
        timeout = session.get('timeout', 7200)
        elapsed = int(time.time() - started_ts)
        stop_found = bool(worker_state.get('stop_found'))
        send_visible = bool(worker_state.get('send_visible'))
        content_hash = worker_state.get('content_hash') or ""
        state_ttl = timeout

        ever_seen_key = self._monitor_key(monitor_id, "ever_seen_stop")
        hash_key = self._monitor_key(monitor_id, "content_hash")
        stable_key = self._monitor_key(monitor_id, "content_stable_ticks")

        ever_seen_stop = self.rc.get(ever_seen_key) == "1"

        if stop_found:
            self.rc.setex(ever_seen_key, state_ttl, "1")
            self.rc.setex(hash_key, state_ttl, content_hash)
            self.rc.setex(stable_key, state_ttl, "0")
            _log(f"[{platform}/{monitor_id}] stop=YES send={'YES' if send_visible else 'NO'} ({elapsed}s)")
            return False

        if ever_seen_stop:
            confidence = "high" if send_visible else "normal"
            _log(
                f"[{platform}/{monitor_id}] stop=NO send={'YES' if send_visible else 'NO'} "
                f"ever_seen=YES → COMPLETE confidence={confidence} ({elapsed}s)"
            )
            self._notify(session, "response_complete", "stop_button")
            return True

        if time.time() - started_ts > timeout:
            _log(f"[{platform}/{monitor_id}] Timeout after {timeout}s")
            self._notify(session, "timeout", "timeout")
            return True

        last_hash = self.rc.get(hash_key) or ""
        stable_ticks = int(self.rc.get(stable_key) or "0")

        if content_hash and content_hash == last_hash:
            stable_ticks += 1
        else:
            stable_ticks = 0

        self.rc.setex(hash_key, state_ttl, content_hash)
        self.rc.setex(stable_key, state_ttl, str(stable_ticks))

        if stable_ticks >= STABLE_TICKS and send_visible:
            _log(
                f"[{platform}/{monitor_id}] stop=NO send=YES stable_ticks={stable_ticks} "
                f"→ COMPLETE ({elapsed}s)"
            )
            self._notify(session, "response_complete", "content_stable")
            return True

        _log(
            f"[{platform}/{monitor_id}] stop=NO send={'YES' if send_visible else 'NO'} "
            f"ever_seen={'YES' if ever_seen_stop else 'NO'} stable_ticks={stable_ticks} ({elapsed}s)"
        )
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

        if status == "response_complete":
            self._extract_and_store(session)

    def _extract_and_store(self, session: Dict):
        """Best-effort extraction and storage after completion notification."""
        platform = session.get('platform')
        session_id = session.get('session_id')
        monitor_id = session.get('monitor_id')

        if not platform:
            _log(f"[{monitor_id}] Extraction skipped: missing platform")
            return

        try:
            extractor = ExtractorRegistry()
            result = extractor.extract(
                platform,
                lambda cmd: self._call_worker(platform, cmd, operation="extract"),
            )
            if not result:
                _log(f"[{platform}/{monitor_id}] Extraction failed: empty worker result")
                return

            if result.get("error"):
                _log(f"[{platform}/{monitor_id}] Extraction failed: {result['error']}")
                return

            content = result.get("content")
            if not result.get("success") or not content:
                _log(
                    f"[{platform}/{monitor_id}] Extraction failed: "
                    f"success={result.get('success', False)} content_present={bool(content)}"
                )
                return

            content_hash = StoragePipeline().store(
                platform,
                content,
                session_id,
                monitor_id,
                self.rc,
                source="monitor",
            )
            if content_hash:
                _log(
                    f"[{platform}/{monitor_id}] Extracted {len(content)} chars "
                    f"from {platform}, stored as {content_hash}"
                )
            else:
                _log(f"[{platform}/{monitor_id}] Extraction skipped: storage returned no content hash")
        except Exception as e:
            _log(f"[{platform}/{monitor_id}] Extraction failed: {e}")

    def run(self):
        """Main loop — poll workers for completion state every cycle."""
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

        from core.platforms import get_platform_display

        by_platform: Dict[str, List[Dict]] = {}
        for s in sessions:
            by_platform.setdefault(s['platform'], []).append(s)

        _log(f"Cycle: {len(sessions)} session(s) on {set(by_platform.keys())}")

        completed = []
        for platform, platform_sessions in by_platform.items():
            if not get_platform_display(platform):
                continue
            stop_result = self._call_worker(platform, {'cmd': 'check_stop'}, operation="poll")
            send_result = self._call_worker(platform, {'cmd': 'get_send_button_state'}, operation="poll")
            hash_result = self._call_worker(platform, {'cmd': 'get_content_hash'}, operation="poll")
            if not (stop_result and send_result and hash_result):
                _log(f"[{platform}] Worker monitor state incomplete; skipping platform this cycle")
                continue
            worker_state = {
                'stop_found': stop_result.get('stop_found', False),
                'send_visible': send_result.get('send_visible', False),
                'content_hash': hash_result.get('content_hash', ''),
            }

            for session in platform_sessions:
                if self._detect_completion(session, worker_state):
                    completed.append(session)

        for s in completed:
            self._remove_session(s)


# ── __init__.py guard ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Central response monitor")
    parser.add_argument('--cycle-interval', type=float,
                        default=float(os.environ.get('MONITOR_CYCLE_SEC', str(POLL_INTERVAL))))
    args = parser.parse_args()

    CentralMonitor(cycle_interval=args.cycle_interval).run()


if __name__ == '__main__':
    main()
