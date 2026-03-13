#!/usr/bin/env python3
"""Central response monitor — one process per machine, cycles all active sessions.

Replaces per-send daemon subprocesses. Reads session registry from Redis,
cycles through platform tabs and session URLs, detects response completion
via AT-SPI stop button polling + copy count fallback.

ALL tab/URL switching stops when a plan is being executed (plan_active key).

Usage:
    python3 -m monitor.central
    python3 monitor/central.py --cycle-interval 30

Environment:
    DISPLAY             X11 display (auto-detected)
    REDIS_HOST          Redis host (default: 127.0.0.1)
    REDIS_PORT          Redis port (default: 6379)
    TAEY_NODE_ID        Node identifier (default: hostname)
    MONITOR_CYCLE_SEC   Seconds between full cycles (default: 30)
    MONITOR_DWELL_SEC   Seconds to dwell on each session (default: 5)
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

# .env loading
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _val = _line.split('=', 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# DISPLAY detection
def _detect_display() -> str:
    env = os.environ.get('DISPLAY')
    if env:
        return env
    for d in [':0', ':1']:
        if os.path.exists(f'/tmp/.X{d[1:]}-lock') or os.path.exists(f'/tmp/.X11-unix/X{d[1:]}'):
            return d
    return ':0'

DISPLAY = _detect_display()
os.environ['DISPLAY'] = DISPLAY

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

# Redis
try:
    import redis as _redis_mod
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Import node_key from redis_pool — single source of truth for key prefixing.
# Eliminates NODE_ID mismatch between monitor and MCP server.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from storage.redis_pool import node_key as _node_key, NODE_ID

# Platform patterns
STOP_PATTERNS = {
    'chatgpt': ['stop', 'stop generating'], 'claude': ['stop', 'stop response'],
    'gemini': ['stop', 'cancel'], 'grok': ['stop', 'stop generating'],
    'perplexity': ['stop', 'cancel'],
}
URL_PATTERNS = {
    'chatgpt': 'chatgpt.com', 'claude': 'claude.ai', 'gemini': 'gemini.google.com',
    'grok': 'grok.com', 'perplexity': 'perplexity.ai',
}
_WORKER_HOSTNAMES = {'jetson', 'thor'}
_DEFAULT_TAB_SHORTCUTS = {
    'chatgpt': 'alt+1', 'claude': 'alt+2', 'gemini': 'alt+3',
    'grok': 'alt+4', 'perplexity': 'alt+5',
}
_WORKER_TAB_SHORTCUTS = {
    'chatgpt': 'alt+1', 'claude': 'alt+2', 'gemini': 'alt+3', 'grok': 'alt+4',
}
TAB_SHORTCUTS = (_WORKER_TAB_SHORTCUTS if socket.gethostname().lower() in _WORKER_HOSTNAMES
                 else _DEFAULT_TAB_SHORTCUTS)


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [monitor] {msg}", flush=True)


def _xdotool(*args):
    try:
        subprocess.run(
            ['xdotool', *args],
            env={**os.environ, 'DISPLAY': DISPLAY},
            capture_output=True, timeout=5,
        )
    except Exception as e:
        _log(f"xdotool {args[0]} failed: {e}")


class CentralMonitor:
    """Single monitor process — cycles active sessions, detects completion."""

    def __init__(self, cycle_interval: int = 30, dwell_seconds: int = 5):
        self.cycle_interval = cycle_interval
        self.dwell_seconds = dwell_seconds
        self.rc = self._connect_redis()
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
            )
            c.ping()
            return c
        except Exception as e:
            _log(f"Redis connection failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Redis session registry
    # ------------------------------------------------------------------

    def _get_sessions(self) -> List[Dict]:
        """Find ALL active sessions across ALL node_ids on this machine.

        Each MCP server registers sessions under its own node_id (tmux session
        name). The monitor must find them all: taey:*:active_session:*
        """
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

        One Firefox, one active tab. When ANY session is executing a plan,
        the monitor must not cycle tabs.
        """
        if not self.rc:
            return False
        return bool(self.rc.exists("taey:plan_active"))

    # ------------------------------------------------------------------
    # AT-SPI helpers
    # ------------------------------------------------------------------

    def _find_firefox(self):
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if 'firefox' in (app.get_name() or '').lower():
                return app
        return None

    def _find_document(self, firefox, platform: str):
        url_pat = URL_PATTERNS.get(platform, platform)

        def search(obj, depth=0):
            if depth > 10:
                return None
            try:
                if (obj.get_role_name() or '') == 'document web':
                    iface = obj.get_document_iface()
                    if iface:
                        url = iface.get_document_attribute_value('DocURL')
                        if url and url_pat in url.lower():
                            return obj
                for i in range(obj.get_child_count()):
                    child = obj.get_child_at_index(i)
                    if child:
                        r = search(child, depth + 1)
                        if r:
                            return r
            except Exception:
                pass
            return None

        return search(firefox)

    def _get_document_url(self, doc) -> Optional[str]:
        try:
            iface = doc.get_document_iface()
            if iface:
                return iface.get_document_attribute_value('DocURL')
        except Exception:
            pass
        return None

    def _force_dbus_refresh(self, doc):
        try:
            doc.clear_cache_single()
            for i in range(min(doc.get_child_count(), 5)):
                child = doc.get_child_at_index(i)
                if child:
                    try:
                        child.clear_cache_single()
                    except Exception:
                        pass
        except Exception:
            pass

    def _is_stop_button(self, name: str, platform: str) -> bool:
        if not name or len(name) > 50:
            return False
        patterns = STOP_PATTERNS.get(platform, ['stop'])
        return any(p in name.lower().strip() for p in patterns)

    def _is_canvas_stop(self, stop_obj) -> bool:
        """Filter ChatGPT canvas Stop (persistent alongside Update button)."""
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
                            if 'button' in (t.get_role_name() or '') and 'update' in (t.get_name() or '').lower():
                                tc = t.get_component_iface()
                                if tc and abs(tc.get_extents(0).y - stop_y) < 50:
                                    return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    def _scan_buttons(self, doc, platform: str) -> bool:
        """Scan document for stop button. Returns stop_found."""
        stop_candidates = []

        def scan(obj, depth=0):
            if depth > 25:
                return
            try:
                role = obj.get_role_name() or ''
                name = obj.get_name() or ''
                if role in ('push button', 'button'):
                    if self._is_stop_button(name, platform):
                        stop_candidates.append(obj)
                for i in range(obj.get_child_count()):
                    child = obj.get_child_at_index(i)
                    if child:
                        scan(child, depth + 1)
            except Exception:
                pass

        scan(doc)

        for c in stop_candidates:
            if not self._is_canvas_stop(c):
                return True
        return False

    # ------------------------------------------------------------------
    # Tab / URL navigation
    # ------------------------------------------------------------------

    _LANDING_PAGES = [
        'chatgpt.com/', 'chatgpt.com/?', 'claude.ai/new',
        'gemini.google.com/app', 'grok.com/', 'grok.com/?',
        'perplexity.ai/', 'perplexity.ai/?',
    ]

    def _is_landing_page(self, url: str) -> bool:
        """Check if URL is a landing/new-chat page that redirects after send."""
        if not url:
            return True
        url_lower = url.lower().rstrip('/')
        for pat in self._LANDING_PAGES:
            pat_clean = pat.rstrip('/')
            if url_lower.endswith(pat_clean):
                return True
        return False

    def _switch_tab(self, platform: str):
        shortcut = TAB_SHORTCUTS.get(platform)
        if shortcut:
            _xdotool('key', '--clearmodifiers', shortcut)

    def _navigate_url(self, url: str):
        """Navigate Firefox to URL via Ctrl+L + clipboard paste."""
        _xdotool('key', '--clearmodifiers', 'ctrl+l')
        time.sleep(0.3)
        try:
            subprocess.run(
                ['xsel', '--clipboard', '--input'],
                input=url, text=True, timeout=5,
                env={**os.environ, 'DISPLAY': DISPLAY},
            )
            _xdotool('key', '--clearmodifiers', 'ctrl+v')
            time.sleep(0.2)
            _xdotool('key', '--clearmodifiers', 'Return')
        except Exception as e:
            _log(f"URL navigation failed: {e}")

    # ------------------------------------------------------------------
    # Session checking
    # ------------------------------------------------------------------

    def _check_session(self, session: Dict, doc) -> bool:
        """Check one session. Returns True if session completed (remove it)."""
        platform = session['platform']
        monitor_id = session['monitor_id']

        # URL verification — only skip if we're sure this is wrong session.
        # Landing pages redirect after send, so don't skip on mismatch
        # with landing URLs. Always check if this is the only session.
        expected_url = session.get('url', '')
        current_url = self._get_document_url(doc) or ''
        if expected_url and not self._is_landing_page(expected_url):
            if expected_url not in current_url and current_url not in expected_url:
                _log(f"[{platform}/{monitor_id}] URL mismatch, skipping "
                     f"(expected={expected_url[:50]}, got={current_url[:50]})")
                return False

        self._force_dbus_refresh(doc)
        stop_found = self._scan_buttons(doc, platform)
        _log(f"[{platform}/{monitor_id}] scan: stop={stop_found}, "
             f"stop_seen={session.get('stop_seen')}, url={current_url[:60]}")

        stop_seen = session.get('stop_seen', False)
        started_ts = session.get('started_ts', time.time())
        timeout = session.get('timeout', 3600)

        # State machine: stop button appears → generating. Disappears → complete.
        if stop_found:
            if not stop_seen:
                session['stop_seen'] = True
                session['generating_since'] = time.time()
                self._update_session(session)
                _log(f"[{platform}/{monitor_id}] Stop button — generating")
        elif stop_seen:
            _log(f"[{platform}/{monitor_id}] Stop gone — complete")
            self._notify(session, "response_ready", "stop_button")
            return True

        # Timeout check
        if time.time() - started_ts > timeout:
            _log(f"[{platform}/{monitor_id}] Timeout after {timeout}s")
            self._notify(session, "timeout", "timeout")
            return True

        return False

    def _notify(self, session: Dict, status: str, detection: str):
        """Send notification to the session that registered this monitor session.

        Routes to taey:{tmux_session}:notifications — the tmux_session field
        was set by the MCP server that called send_message (its NODE_ID).
        """
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
            "requires_action": status == "response_ready",
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
            try:
                path = f"/tmp/taey_monitor_{session.get('monitor_id')}.json"
                with open(path, 'w') as f:
                    f.write(nj)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run(self):
        _log(f"Central monitor started (node={NODE_ID}, display={DISPLAY}, "
             f"cycle={self.cycle_interval}s, dwell={self.dwell_seconds}s)")

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
        # Check plan lock — full stop
        if self._plan_active():
            _log("Plan active — skipping cycle")
            return

        sessions = self._get_sessions()
        if not sessions:
            return

        firefox = self._find_firefox()
        if not firefox:
            _log("Firefox not found")
            return

        platforms = {s['platform'] for s in sessions}
        _log(f"Cycle: {len(sessions)} session(s) on {platforms}")

        # Group by platform
        by_platform: Dict[str, List[Dict]] = {}
        for s in sessions:
            by_platform.setdefault(s['platform'], []).append(s)

        completed = []

        for platform, platform_sessions in by_platform.items():
            if self._plan_active():
                break

            if platform not in TAB_SHORTCUTS:
                continue

            self._switch_tab(platform)
            time.sleep(1)

            for session in platform_sessions:
                if self._plan_active():
                    break

                doc = self._find_document(firefox, platform)

                # Navigate to session URL only for multi-session disambiguation.
                # Skip navigation for landing pages — they redirect after send.
                if doc and session.get('url') and len(platform_sessions) > 1:
                    current_url = self._get_document_url(doc) or ''
                    if not self._is_landing_page(session['url']) and \
                       session['url'] not in current_url:
                        self._navigate_url(session['url'])
                        time.sleep(3)
                        firefox = self._find_firefox()
                        if firefox:
                            doc = self._find_document(firefox, platform)

                if not doc:
                    continue

                if self._check_session(session, doc):
                    completed.append(session)

                time.sleep(self.dwell_seconds)

        # Remove completed sessions
        for s in completed:
            self._remove_session(s)


def main():
    parser = argparse.ArgumentParser(description="Central response monitor")
    parser.add_argument('--cycle-interval', type=int,
                        default=int(os.environ.get('MONITOR_CYCLE_SEC', '30')))
    parser.add_argument('--dwell-seconds', type=int,
                        default=int(os.environ.get('MONITOR_DWELL_SEC', '5')))
    args = parser.parse_args()

    CentralMonitor(
        cycle_interval=args.cycle_interval,
        dwell_seconds=args.dwell_seconds,
    ).run()


if __name__ == '__main__':
    main()
