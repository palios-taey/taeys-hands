"""AT-SPI desktop and Firefox discovery.

Multi-display mode: each platform runs on its own display with a dedicated
per-display worker process (workers/display_worker.py). Workers have the
correct DISPLAY and AT-SPI bus set in their environment, so all AT-SPI
calls go through the direct local path. The MCP server dispatches tool
calls to the correct worker via Unix socket IPC (workers/manager.py).
"""

import os
import logging

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

logger = logging.getLogger(__name__)


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
    raise RuntimeError("No X display detected - set DISPLAY env or start Xvfb")


def find_firefox():
    """Find Firefox in the AT-SPI desktop tree. Retries once with cache clear."""
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



def get_document_url(doc) -> str | None:
    """Extract DocURL from a document element."""
    try:
        iface = doc.get_document_iface()
        if iface:
            return iface.get_document_attribute_value('DocURL')
    except Exception:
        pass
    return None


def document_web_elements(firefox, *, max_depth: int = 10) -> list:
    """Return document-web descendants for a Firefox AT-SPI application root."""
    candidates = []

    def search(obj, depth=0):
        if depth > max_depth:
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

    if firefox:
        search(firefox)
    return candidates


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
