"""
AT-SPI desktop and Firefox discovery.

Finds Firefox in the Linux accessibility tree and locates
platform documents by URL pattern matching.

FROZEN once working - do not modify without approval.
"""

import os
import logging

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from core.platforms import URL_PATTERNS

logger = logging.getLogger(__name__)


def detect_display() -> str:
    """Detect active X display by checking lock files and sockets.

    Raises:
        RuntimeError: If no X display can be detected.
    """
    for d in [':0', ':1']:
        if os.path.exists(f'/tmp/.X{d[1:]}-lock'):
            return d
    for d in [':0', ':1']:
        if os.path.exists(f'/tmp/.X11-unix/X{d[1:]}'):
            return d
    display = os.environ.get('DISPLAY')
    if display:
        return display
    raise RuntimeError("No X display detected: no lock files, no sockets, DISPLAY not set")


def find_firefox():
    """Find Firefox application in the AT-SPI desktop tree.

    Returns:
        Atspi.Accessible for Firefox, or None if not found.
    """
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            name = app.get_name() if app else None
            if name and 'firefox' in name.lower():
                return app
    except Exception as e:
        logger.error(f"AT-SPI desktop search failed: {e}")
    return None


def get_document_url(doc) -> str | None:
    """Extract DocURL from a document element.

    Args:
        doc: AT-SPI document web element.

    Returns:
        URL string or None.
    """
    try:
        iface = doc.get_document_iface()
        if iface:
            return iface.get_document_attribute_value('DocURL')
    except Exception:
        pass
    return None


def detect_platform_from_url(url: str) -> str | None:
    """Detect which platform a URL belongs to.

    Args:
        url: Page URL to check.

    Returns:
        Platform name (e.g., 'claude') or None.
    """
    if not url:
        return None
    url_lower = url.lower()
    for platform, domain in URL_PATTERNS.items():
        if domain in url_lower:
            return platform
    return None


def get_platform_document(firefox, platform: str):
    """Find the document web element for a specific platform.

    Searches Firefox's AT-SPI tree for 'document web' elements
    and matches by URL pattern.

    Args:
        firefox: Firefox AT-SPI accessible (from find_firefox).
        platform: Platform name (e.g., 'claude').

    Returns:
        Atspi.Accessible for the document, or None.
    """
    if not firefox:
        return None

    candidates = []

    def search(obj, depth=0, max_depth=10):
        if depth > max_depth:
            return
        try:
            if obj.get_role_name() == 'document web':
                candidates.append(obj)
            for i in range(obj.get_child_count()):
                child = obj.get_child_at_index(i)
                if child:
                    search(child, depth + 1, max_depth)
        except Exception:
            pass

    search(firefox)

    for candidate in candidates:
        url = get_document_url(candidate)
        if detect_platform_from_url(url) == platform:
            return candidate

    return None


def is_file_dialog_open(firefox) -> bool:
    """Check if a GTK file chooser dialog is open in Firefox.

    Only searches the Firefox process (not entire desktop) to
    avoid blocking on other applications' AT-SPI trees.

    Args:
        firefox: Firefox AT-SPI accessible.

    Returns:
        True if a file chooser is open.
    """
    if not firefox:
        return False

    def search_for_dialog(obj, depth=0):
        if depth > 3:
            return False
        try:
            if obj.get_role_name() == 'file chooser':
                return True
            for j in range(min(obj.get_child_count(), 20)):
                child = obj.get_child_at_index(j)
                if child and search_for_dialog(child, depth + 1):
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
            app_name = (app.get_name() or '').lower()
            if 'firefox' not in app_name:
                continue
            if search_for_dialog(app):
                return True
    except Exception as e:
        logger.error(f"File dialog check failed: {e}")

    return False
