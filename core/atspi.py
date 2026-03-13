"""AT-SPI desktop and Firefox discovery."""

import os
import logging

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from core.platforms import URL_PATTERNS, _EXTRA_URL_PATTERNS

logger = logging.getLogger(__name__)


def detect_display() -> str:
    """Detect active X display: DISPLAY env > lock files > sockets."""
    display = os.environ.get('DISPLAY')
    if display:
        return display
    for d in [':0', ':1']:
        if os.path.exists(f'/tmp/.X{d[1:]}-lock'):
            return d
    for d in [':0', ':1']:
        if os.path.exists(f'/tmp/.X11-unix/X{d[1:]}'):
            return d
    raise RuntimeError("No X display detected")


def find_firefox():
    """Find Firefox in AT-SPI desktop tree. Retries once with cache clear."""
    for attempt in range(2):
        try:
            desktop = Atspi.get_desktop(0)
            if attempt > 0:
                try:
                    desktop.clear_cache_single()
                except Exception:
                    pass
            for i in range(desktop.get_child_count()):
                app = desktop.get_child_at_index(i)
                if app and 'firefox' in (app.get_name() or '').lower():
                    return app
        except Exception as e:
            if attempt == 0:
                logger.warning(f"AT-SPI search failed, retrying: {e}")
                continue
            logger.error(f"AT-SPI search failed after retry: {e}")
    return None


def find_all_firefox():
    """Find ALL Firefox apps in AT-SPI desktop tree."""
    apps = []
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app and 'firefox' in (app.get_name() or '').lower():
                apps.append(app)
    except Exception as e:
        logger.error(f"AT-SPI search failed: {e}")
    return apps


def find_firefox_for_platform(platform: str):
    """Find the Firefox instance that has a document matching the given platform.
    Handles multiple Firefox instances (parallel HMM mode).
    Falls back to find_firefox() if only one instance exists."""
    all_ff = find_all_firefox()
    if not all_ff:
        return None
    if len(all_ff) == 1:
        return all_ff[0]
    # Multiple Firefox instances — find the one with our platform's document
    for ff in all_ff:
        doc = get_platform_document(ff, platform)
        if doc:
            return ff
    # None had the right document — return first as fallback
    logger.warning(f"No Firefox instance has {platform} document, using first")
    return all_ff[0]


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
