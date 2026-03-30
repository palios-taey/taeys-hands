"""AT-SPI desktop and Firefox discovery.

Multi-display mode: when PLATFORM_DISPLAYS is set (Mira), each platform
has its own display/D-Bus. Tree operations are routed through subprocess
scanning with the correct env. Returns _RemoteFirefox/_RemoteDocument
sentinels that callers detect via getattr(obj, '_remote', False).
"""

import json
import os
import logging
import subprocess
import sys

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from core.platforms import (URL_PATTERNS, _EXTRA_URL_PATTERNS,
                            get_platform_display, get_platform_bus,
                            get_platform_firefox_pid)

logger = logging.getLogger(__name__)

# Path to the subprocess scanner script
_SCANNER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_atspi_subprocess.py')


def detect_display() -> str:
    """Detect active X display: DISPLAY env > lock files > sockets.

    Scans :0 through :99 to support virtual displays (Xvfb on :5, :10, etc.)
    beyond the common :0/:1. Prefers the lowest-numbered available display.
    """
    display = os.environ.get('DISPLAY')
    if display:
        return display
    # Scan lock files for any active display (:0 through :99)
    for num in range(100):
        if os.path.exists(f'/tmp/.X{num}-lock'):
            return f':{num}'
    # Fallback: check X11 unix sockets
    for num in range(100):
        if os.path.exists(f'/tmp/.X11-unix/X{num}'):
            return f':{num}'
    raise RuntimeError("No X display detected — set DISPLAY env or start Xvfb")


def find_firefox(platform: str = None):
    """Find Firefox in AT-SPI desktop tree. Retries once with cache clear.
    If platform is given and multiple Firefox instances exist, returns the
    instance containing that platform's document (handles HMM bot profiles)."""
    for attempt in range(2):
        try:
            desktop = Atspi.get_desktop(0)
            if attempt > 0:
                try:
                    desktop.clear_cache_single()
                except Exception:
                    pass
            all_ff = []
            for i in range(desktop.get_child_count()):
                app = desktop.get_child_at_index(i)
                if app and 'firefox' in (app.get_name() or '').lower():
                    all_ff.append(app)
            if not all_ff:
                if attempt == 0:
                    continue
                return None
            if len(all_ff) == 1:
                return all_ff[0]
            # Multiple Firefox instances — need platform to disambiguate
            if platform:
                for ff in all_ff:
                    doc = get_platform_document(ff, platform)
                    if doc:
                        return ff
                logger.warning(f"No Firefox instance has {platform} document, returning first")
            return all_ff[0]
        except Exception as e:
            if attempt == 0:
                logger.warning(f"AT-SPI search failed, retrying: {e}")
                continue
            logger.error(f"AT-SPI search failed after retry: {e}")
    return None


def find_all_firefox(pid: int = None):
    """Find ALL Firefox apps in AT-SPI desktop tree.
    If pid is given, only return apps matching that process ID."""
    apps = []
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app and 'firefox' in (app.get_name() or '').lower():
                if pid is not None:
                    try:
                        if app.get_process_id() != pid:
                            continue
                    except Exception:
                        continue
                apps.append(app)
    except Exception as e:
        logger.error(f"AT-SPI search failed: {e}")
    return apps


def subprocess_scan(platform: str, cmd: str = 'find_firefox') -> dict | None:
    """Run AT-SPI scan as subprocess on the platform's dedicated display.

    Used in multi-display mode (Mira) where each platform runs on a
    separate Xvfb with its own D-Bus/AT-SPI bus.
    """
    display = get_platform_display(platform)
    if not display:
        return None
    bus = get_platform_bus(platform)
    env = {**os.environ, 'DISPLAY': display}
    if bus:
        env['AT_SPI_BUS_ADDRESS'] = bus
        env['DBUS_SESSION_BUS_ADDRESS'] = bus
    try:
        r = subprocess.run(
            [sys.executable, _SCANNER_SCRIPT, cmd, platform],
            env=env, capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout.strip())
        if r.stderr:
            logger.warning(f"Subprocess scanner stderr: {r.stderr[:200]}")
    except Exception as e:
        logger.error(f"Subprocess scan failed for {platform} on {display}: {e}")
    return None


class _RemoteFirefox:
    """Sentinel for a Firefox on a different display. Carries PID and display
    info so that callers can route operations through subprocess scanning.

    Callers detect via: getattr(obj, '_remote', False)
    """
    def __init__(self, platform, pid, display, url=None):
        self._platform = platform
        self._pid = pid
        self._display = display
        self._url = url
        self._remote = True

    def get_name(self):
        return 'Firefox'

    def get_process_id(self):
        return self._pid

    def get_child_count(self):
        return 0

    def get_child_at_index(self, i):
        return None


class _RemoteDocument:
    """Sentinel for a document on a different display."""
    def __init__(self, platform, url, display):
        self._platform = platform
        self._url = url
        self._display = display
        self._remote = True

    def get_role_name(self):
        return 'document web'

    def get_name(self):
        return ''

    def get_state_set(self):
        return None

    def get_child_count(self):
        return 0

    def get_child_at_index(self, i):
        return None

    def get_component_iface(self):
        return None


def find_firefox_for_platform(platform: str, pid: int = None):
    """Find the Firefox instance that has a document matching the given platform.
    Handles multiple Firefox instances (parallel HMM mode).
    If pid is given, restricts search to that process only.
    Falls back to find_firefox() if only one instance exists.

    Multi-display mode: if PLATFORM_DISPLAYS maps this platform to a dedicated
    display, uses subprocess scanning on that display's AT-SPI bus."""
    # Multi-display mode: subprocess scan on the platform's display
    if pid is None and get_platform_display(platform):
        info = subprocess_scan(platform, 'find_firefox')
        if info and info.get('pid'):
            return _RemoteFirefox(platform, info['pid'],
                                 get_platform_display(platform),
                                 info.get('url'))
        elif info:
            logger.warning(f"Subprocess found no Firefox for {platform}: {info}")
        # Fall through to local scan

    all_ff = find_all_firefox(pid=pid)
    if not all_ff:
        return None
    if len(all_ff) == 1:
        return all_ff[0]
    # Multiple Firefox instances — find the one with our platform's document
    for ff in all_ff:
        doc = get_platform_document(ff, platform)
        if doc:
            return ff
    # None had the right document — fail, don't guess
    logger.error(f"No Firefox instance has {platform} document")
    return None


def get_document_url(doc) -> str | None:
    """Extract DocURL from a document element."""
    try:
        iface = doc.get_document_iface()
        if iface:
            return iface.get_document_attribute_value('DocURL')
    except Exception:
        pass
    return None


def detect_platform_from_url(url: str) -> str | None:
    """Detect platform from URL. Checks specific patterns first."""
    if not url:
        return None
    url_lower = url.lower()
    for platform, pattern in _EXTRA_URL_PATTERNS.items():
        if pattern in url_lower:
            return platform
    for platform, domain in URL_PATTERNS.items():
        if domain in url_lower:
            return platform
    return None


def get_platform_document(firefox, platform: str):
    """Find the document web element for a platform by URL matching."""
    if not firefox:
        return None

    candidates = []

    def search(obj, depth=0):
        if depth > 10:
            return
        try:
            if obj.get_role_name() == 'document web':
                candidates.append(obj)
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child:
                    search(child, depth + 1)
        except Exception:
            pass

    search(firefox)

    matches = [c for c in candidates if detect_platform_from_url(get_document_url(c)) == platform]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    # Prefer SHOWING (active tab)
    for m in matches:
        try:
            if m.get_state_set().contains(Atspi.StateType.SHOWING):
                return m
        except Exception:
            pass
    matches.sort(key=lambda m: m.get_child_count(), reverse=True)
    return matches[0]


def is_file_dialog_open(firefox) -> bool:
    """Check if a GTK file chooser dialog is open (Firefox process only)."""
    if not firefox:
        return False

    _DIALOG_NAMES = ('file', 'upload', 'open', 'choose', 'select')

    def search_dialog(obj, depth=0):
        if depth > 8:
            return False
        try:
            role = obj.get_role_name()
            if role == 'file chooser':
                return True
            if role == 'dialog':
                name = (obj.get_name() or '').lower()
                if any(t in name for t in _DIALOG_NAMES):
                    return True
            for j in range(min(obj.get_child_count(), 50)):
                child = obj.get_child_at_index(j)
                if child and search_dialog(child, depth + 1):
                    return True
        except Exception:
            pass
        return False

    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if not app:
                continue
            if 'firefox' not in (app.get_name() or '').lower():
                continue
            if search_dialog(app):
                return True
    except Exception as e:
        logger.error(f"File dialog check failed: {e}")
    return False
