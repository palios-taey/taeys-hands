#!/usr/bin/env python3
"""Central response monitor — one process per machine, cycles all active sessions.

Completion detection:
  1. Poll every 2s for stop-button visibility, send-button readiness, and content hash
  2. Persist sticky ever-seen-stop flag per monitor session in Redis
  3. COMPLETE only when stop was seen and is now gone
  4. Extended modes require two stop-gone cycles before completion
  5. If stop remains visible while content stays frozen for a long time, emit
     hang_suspected for operator review without auto-completing

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
HANG_TICKS = 30
DEFAULT_WORKER_TIMEOUT = 5.0
EXTRACT_HARD_TIMEOUT_SEC = 5
PLATFORM_FAILURE_THRESHOLD = 3
PLATFORM_RETRY_DELAY_SEC = 60.0


class ExtractTimeout(Exception):
    """Raised when the hard extraction timeout fires."""


def _timeout_handler(signum, frame):
    raise ExtractTimeout()


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
        self._platform_failure_counts: Dict[str, int] = {}
        self._platform_retry_after: Dict[str, float] = {}
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
            self.rc.set(key, json.dumps(
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
            self._monitor_key(monitor_id, "stop_visible"),
            self._monitor_key(monitor_id, "stop_cycles"),
            self._monitor_key(monitor_id, "content_hash"),
            self._monitor_key(monitor_id, "content_frozen_ticks"),
            self._monitor_key(monitor_id, "hang_notified"),
        )

    def _detect_completion(self, session: Dict, worker_state: Dict) -> bool:
        """Check session completion using sticky stop visibility only."""
        platform = session['platform']
        monitor_id = session['monitor_id']
        mode = (session.get('mode') or "").strip().lower()
        started_ts = session.get('started_ts', time.time())
        timeout = session.get('timeout', 7200)
        elapsed = int(time.time() - started_ts)
        stop_found = bool(worker_state.get('stop_found'))
        send_visible = bool(worker_state.get('send_visible'))
        content_hash = worker_state.get('content_hash') or ""
        state_ttl = timeout
        required_stop_cycles = 2 if mode in {"deep_research", "deep_think", "pro_extended", "extended_thinking", "heavy"} else 1

        ever_seen_key = self._monitor_key(monitor_id, "ever_seen_stop")
        stop_visible_key = self._monitor_key(monitor_id, "stop_visible")
        stop_cycles_key = self._monitor_key(monitor_id, "stop_cycles")
        hash_key = self._monitor_key(monitor_id, "content_hash")
        frozen_key = self._monitor_key(monitor_id, "content_frozen_ticks")
        hang_notified_key = self._monitor_key(monitor_id, "hang_notified")

        ever_seen_stop = self.rc.get(ever_seen_key) == "1"
        stop_was_visible = self.rc.get(stop_visible_key) == "1"
        stop_cycles = int(self.rc.get(stop_cycles_key) or "0")
        last_hash = self.rc.get(hash_key) or ""
        frozen_ticks = int(self.rc.get(frozen_key) or "0")
        hang_notified = self.rc.get(hang_notified_key) == "1"

        if stop_found:
            self.rc.setex(ever_seen_key, state_ttl, "1")
            self.rc.setex(stop_visible_key, state_ttl, "1")
            if content_hash and content_hash == last_hash:
                frozen_ticks += 1
            else:
                frozen_ticks = 0
                hang_notified = False
            self.rc.setex(hash_key, state_ttl, content_hash)
            self.rc.setex(frozen_key, state_ttl, str(frozen_ticks))
            self.rc.setex(hang_notified_key, state_ttl, "1" if hang_notified else "0")
            _log(
                f"[{platform}/{monitor_id}] stop=YES send={'YES' if send_visible else 'NO'} "
                f"mode={mode or 'default'} cycles={stop_cycles}/{required_stop_cycles} "
                f"frozen_ticks={frozen_ticks}/{HANG_TICKS} ({elapsed}s)"
            )

            if ever_seen_stop and content_hash and frozen_ticks >= HANG_TICKS and not hang_notified:
                self.rc.setex(hang_notified_key, state_ttl, "1")
                _log(
                    f"[{platform}/{monitor_id}] stop=YES mode={mode or 'default'} "
                    f"content frozen for {frozen_ticks} ticks → HANG SUSPECTED ({elapsed}s)"
                )
                self._notify(session, "hang_suspected", "stop_present_content_frozen")
            return False

        if ever_seen_stop and stop_was_visible:
            stop_cycles += 1
            self.rc.setex(stop_cycles_key, state_ttl, str(stop_cycles))
            self.rc.setex(stop_visible_key, state_ttl, "0")

            if stop_cycles >= required_stop_cycles:
                confidence = "high" if send_visible else "normal"
                _log(
                    f"[{platform}/{monitor_id}] stop=NO send={'YES' if send_visible else 'NO'} "
                    f"mode={mode or 'default'} cycles={stop_cycles}/{required_stop_cycles} "
                    f"→ COMPLETE confidence={confidence} ({elapsed}s)"
                )
                self._notify(session, "response_complete", "stop_button")
                return True

            _log(
                f"[{platform}/{monitor_id}] stop=NO send={'YES' if send_visible else 'NO'} "
                f"mode={mode or 'default'} cycles={stop_cycles}/{required_stop_cycles} "
                f"→ waiting for next stop cycle ({elapsed}s)"
            )
            return False

        if ever_seen_stop:
            self.rc.setex(stop_visible_key, state_ttl, "0")
            confidence = "high" if send_visible else "normal"
            _log(
                f"[{platform}/{monitor_id}] stop=NO send={'YES' if send_visible else 'NO'} "
                f"mode={mode or 'default'} cycles={stop_cycles}/{required_stop_cycles} "
                f"ever_seen=YES no-transition confidence={confidence} ({elapsed}s)"
            )

        # Generation-start timeout: if stop button never seen after 90s, send likely failed
        generation_start_timeout = 90
        if not ever_seen_stop and elapsed > generation_start_timeout:
            _log(
                f"[{platform}/{monitor_id}] GENERATION NEVER STARTED — no stop button after "
                f"{elapsed}s. Send likely failed. Declaring send_failure. ({elapsed}s)"
            )
            self._notify(session, "send_failure", "no_stop_button")
            return True

        if time.time() - started_ts > timeout:
            _log(f"[{platform}/{monitor_id}] Timeout after {timeout}s")
            self._notify(session, "timeout", "timeout")
            return True

        self.rc.setex(hash_key, state_ttl, content_hash)
        self.rc.setex(frozen_key, state_ttl, "0")
        self.rc.setex(hang_notified_key, state_ttl, "0")

        _log(
            f"[{platform}/{monitor_id}] stop=NO send={'YES' if send_visible else 'NO'} "
            f"mode={mode or 'default'} ever_seen={'YES' if ever_seen_stop else 'NO'} "
            f"cycles={stop_cycles}/{required_stop_cycles} frozen_ticks=0/{HANG_TICKS} ({elapsed}s)"
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
            "requires_action": status in ("response_complete", "response_ready", "hang_suspected"),
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
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(EXTRACT_HARD_TIMEOUT_SEC)
        except Exception:
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
        except ExtractTimeout:
            _log(
                f"[{platform}/{monitor_id}] WARN: Extract timed out after "
                f"{EXTRACT_HARD_TIMEOUT_SEC}s; skipping"
            )
        except Exception as e:
            _log(f"[{platform}/{monitor_id}] WARN: Extract failed: {e}; skipping")
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

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
            retry_after = self._platform_retry_after.get(platform, 0.0)
            now = time.monotonic()
            if retry_after > now:
                _log(
                    f"[{platform}] Skipping platform until retry window opens "
                    f"in {retry_after - now:.1f}s"
                )
                continue
            stop_result = self._call_worker(platform, {'cmd': 'check_stop'}, operation="poll")
            send_result = self._call_worker(platform, {'cmd': 'get_send_button_state'}, operation="poll")
            hash_result = self._call_worker(platform, {'cmd': 'get_content_hash'}, operation="poll")
            if not (stop_result and send_result and hash_result):
                failures = self._platform_failure_counts.get(platform, 0) + 1
                self._platform_failure_counts[platform] = failures
                if failures >= PLATFORM_FAILURE_THRESHOLD:
                    self._platform_failure_counts[platform] = 0
                    self._platform_retry_after[platform] = now + PLATFORM_RETRY_DELAY_SEC
                    _log(
                        f"[{platform}] Worker failed {failures} consecutive cycle(s); "
                        f"backing off for {PLATFORM_RETRY_DELAY_SEC:.0f}s"
                    )
                _log(f"[{platform}] Worker monitor state incomplete; skipping platform this cycle")
                continue
            self._platform_failure_counts.pop(platform, None)
            self._platform_retry_after.pop(platform, None)
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
