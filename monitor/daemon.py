#!/usr/bin/env python3
"""Background monitor daemon — detects response completion via AT-SPI stop button polling."""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional, Dict

# .env loading (daemon runs as subprocess, doesn't inherit server's env)
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
from gi.repository import Atspi, GLib

# Redis (optional)
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Node ID: --tmux-session overrides auto-detect
_NODE_ID = os.environ.get('TAEY_NODE_ID', socket.gethostname())
_EFFECTIVE_NODE_ID = _NODE_ID

def _node_key(suffix: str) -> str:
    return f"taey:{_EFFECTIVE_NODE_ID}:{suffix}"

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
    'grok': 'alt+4', 'perplexity': 'alt+5', 'x_twitter': 'alt+6',
}
_WORKER_TAB_SHORTCUTS = {
    'chatgpt': 'alt+1', 'claude': 'alt+2', 'gemini': 'alt+3', 'grok': 'alt+4',
}
TAB_SHORTCUTS = (_WORKER_TAB_SHORTCUTS if socket.gethostname().lower() in _WORKER_HOSTNAMES
                 else _DEFAULT_TAB_SHORTCUTS)


class MonitorDaemon:
    """Stop button + copy count monitor. States: IDLE → GENERATING → COMPLETE."""

    def __init__(self, platform, monitor_id, baseline_copy_count,
                 session_id=None, user_message_id=None,
                 timeout_seconds=3600, tmux_session=None):
        self.platform = platform.lower()
        self.monitor_id = monitor_id
        self.baseline_copy_count = baseline_copy_count
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds

        self.state = "IDLE"
        self.start_time = time.time()
        self.stop_button_seen = False
        self.no_stop_warned = False
        self.verbose_logged = False
        self.generating_since = None
        self.last_tab_refresh = None

        self.redis_client = self._connect_redis()
        self.firefox_app = self._find_firefox()
        self.main_loop = GLib.MainLoop()

        if not self.firefox_app:
            self._log("ERROR: Firefox not found in AT-SPI tree")
            sys.exit(1)
        self._log(f"Initialized for {platform}, baseline={baseline_copy_count}")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{self.monitor_id}] {msg}", flush=True)

    def _connect_redis(self):
        if not REDIS_AVAILABLE:
            return None
        try:
            c = redis.Redis(host=os.environ.get('REDIS_HOST', '127.0.0.1'),
                           port=int(os.environ.get('REDIS_PORT', 6379)),
                           decode_responses=True)
            c.ping()
            return c
        except Exception as e:
            self._log(f"Redis failed: {e}")
            return None

    def _find_firefox(self):
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if 'firefox' in (app.get_name() or '').lower():
                return app
        return None

    def _find_platform_document(self):
        if not self.firefox_app:
            return None
        url_pat = URL_PATTERNS.get(self.platform, self.platform)

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

        return search(self.firefox_app)

    def _force_dbus_refresh(self, doc):
        """Clear AT-SPI client cache to force fresh D-Bus calls."""
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

    def _should_refresh_tab(self) -> bool:
        if self.state != "GENERATING" or not self.generating_since:
            return False
        now = time.time()
        if now - self.generating_since < 30:
            return False
        if self.last_tab_refresh and now - self.last_tab_refresh < 30:
            return False
        if self.redis_client:
            try:
                nid = _EFFECTIVE_NODE_ID
                if self.redis_client.exists(f"taey:{nid}:tool_running"):
                    return False
                last_str = self.redis_client.get(f"taey:{nid}:last_tool_activity")
                if last_str and now - float(last_str) < 15:
                    return False
            except Exception:
                return False
        return True

    def _refresh_tab(self):
        shortcut = TAB_SHORTCUTS.get(self.platform)
        if not shortcut:
            return
        try:
            subprocess.run(['xdotool', 'key', '--clearmodifiers', shortcut],
                          env={**os.environ, 'DISPLAY': DISPLAY},
                          capture_output=True, timeout=5)
            self.last_tab_refresh = time.time()
            self._log(f"Tab refresh: {self.platform} ({shortcut})")
        except Exception as e:
            self._log(f"Tab refresh failed: {e}")

    def _is_stop_button(self, name: str) -> bool:
        if not name or len(name) > 50:
            return False
        patterns = STOP_PATTERNS.get(self.platform, ['stop'])
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
                        # Check direct children
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

    def _notify(self, status: str, message: str, extra: Dict = None):
        """Write notification to Redis RPUSH."""
        notification = {
            "monitor_id": self.monitor_id, "platform": self.platform,
            "node_id": _NODE_ID, "status": status, "message": message,
            "timestamp": datetime.now().isoformat(), "session_id": self.session_id,
            "elapsed_seconds": int(time.time() - self.start_time),
        }
        if extra:
            notification.update(extra)
        nj = json.dumps(notification)
        if self.redis_client:
            try:
                self.redis_client.rpush(_node_key("notifications"), nj)
                self.redis_client.setex(_node_key(f"monitor:{self.monitor_id}"), 3600, nj)
                self._log(f"Notification: {status}")
            except Exception as e:
                self._log(f"Redis notification error: {e}")
        else:
            try:
                with open(f"/tmp/taey_monitor_{self.monitor_id}.json", 'w') as f:
                    f.write(nj)
            except Exception:
                pass

    def _on_first_poll(self) -> bool:
        self._log("Initial delay done, polling")
        self._on_poll()
        if self.state != "COMPLETE":
            GLib.timeout_add(3000, self._on_poll)
        return False

    def _on_poll(self) -> bool:
        try:
            return self._poll_inner()
        except Exception as e:
            self._log(f"Poll error (continuing): {e}")
            return True

    def _poll_inner(self) -> bool:
        elapsed = time.time() - self.start_time
        if elapsed > self.timeout_seconds:
            self._log(f"Timeout after {elapsed:.0f}s")
            self._notify("timeout", f"Timed out after {elapsed:.0f}s")
            self.main_loop.quit()
            return False

        if not self.stop_button_seen and not self.no_stop_warned and elapsed > 45:
            self._notify("warning", f"No stop button after {elapsed:.0f}s",
                        {"warning_type": "no_stop_button"})
            self.no_stop_warned = True

        doc = self._find_platform_document()
        if not doc:
            return True

        self._force_dbus_refresh(doc)
        if self._should_refresh_tab():
            self._refresh_tab()

        # Search for stop + copy buttons
        stop_candidates, copy_count, all_btns = [], 0, []

        def scan(obj, depth=0):
            nonlocal copy_count
            if depth > 25:
                return
            try:
                role = obj.get_role_name() or ''
                name = obj.get_name() or ''
                if role in ('push button', 'button'):
                    if name and not self.verbose_logged:
                        all_btns.append(name)
                    if self._is_stop_button(name):
                        stop_candidates.append(obj)
                    if 'copy' in name.lower():
                        copy_count += 1
                for i in range(obj.get_child_count()):
                    child = obj.get_child_at_index(i)
                    if child:
                        scan(child, depth + 1)
            except Exception:
                pass

        scan(doc)

        if all_btns and not self.verbose_logged:
            self._log(f"Buttons: {all_btns[:10]}")
            self.verbose_logged = True

        # Filter canvas stop
        stop_button = None
        for c in stop_candidates:
            if not self._is_canvas_stop(c):
                stop_button = c
                break

        if stop_button:
            if self.state == "IDLE":
                self.state = "GENERATING"
                self.stop_button_seen = True
                self.generating_since = time.time()
                self._log("Stop button appeared — generating")
        else:
            # Fast-response fallback: copy count increased without seeing stop button
            if self.state == "IDLE" and not self.stop_button_seen and copy_count > self.baseline_copy_count:
                self._log(f"Fast-response: copies {self.baseline_copy_count}→{copy_count}")
                self._notify("response_ready",
                            f"Response complete on {self.platform}",
                            {"detection": "copy_button_fallback", "requires_action": True})
                self.state = "COMPLETE"
                self.main_loop.quit()
                return False

            if self.stop_button_seen:
                self._log("Stop button gone — response complete")
                self._notify("response_ready",
                            f"Response complete on {self.platform}",
                            {"requires_action": True})
                self.state = "COMPLETE"
                self.main_loop.quit()
                return False

        return True

    def start(self):
        self._log(f"Starting monitor for {self.platform}")
        if self.redis_client:
            self.redis_client.setex(_node_key(f"monitor:{self.monitor_id}"),
                                   self.timeout_seconds, json.dumps({
                "status": "monitoring", "platform": self.platform,
                "node_id": _NODE_ID, "started": datetime.now().isoformat(),
                "baseline_copy_count": self.baseline_copy_count,
            }))
        GLib.timeout_add(3000, self._on_first_poll)
        try:
            self.main_loop.run()
        except KeyboardInterrupt:
            self._notify("interrupted", "Monitor stopped")
        finally:
            self._log("Exited")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', required=True)
    parser.add_argument('--monitor-id', required=True)
    parser.add_argument('--baseline-copy-count', type=int, required=True)
    parser.add_argument('--session-id')
    parser.add_argument('--user-message-id')
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--tmux-session')
    parser.add_argument('--settle-seconds', type=int, default=0)  # Accepted but ignored (v7)
    args = parser.parse_args()

    if args.tmux_session:
        global _EFFECTIVE_NODE_ID
        _EFFECTIVE_NODE_ID = args.tmux_session

    MonitorDaemon(
        platform=args.platform, monitor_id=args.monitor_id,
        baseline_copy_count=args.baseline_copy_count,
        session_id=args.session_id, user_message_id=args.user_message_id,
        timeout_seconds=args.timeout, tmux_session=args.tmux_session,
    ).start()


if __name__ == '__main__':
    main()
