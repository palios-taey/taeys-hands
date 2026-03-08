"""
Platform definitions: URL patterns, tab shortcuts, capabilities.

Central registry for all supported platforms (chat AI and social).
Cross-platform: works on both Linux (xdpyinfo) and macOS (system_profiler).
"""

import os
import sys
import subprocess


def _detect_screen_size_linux() -> tuple:
    """Detect screen dimensions from X display via xdpyinfo."""
    try:
        result = subprocess.run(
            ['xdpyinfo'], capture_output=True, text=True, timeout=5,
            env={**os.environ},
        )
        for line in result.stdout.splitlines():
            if 'dimensions:' in line:
                parts = line.strip().split()
                w, h = parts[1].split('x')
                return int(w), int(h)
    except Exception as e:
        raise RuntimeError(f"Screen size detection failed (xdpyinfo error): {e}")
    raise RuntimeError("Screen size detection failed: no 'dimensions:' line in xdpyinfo output")


def _detect_screen_size_macos() -> tuple:
    """Detect screen dimensions on macOS via Quartz."""
    try:
        import Quartz
        main = Quartz.CGMainDisplayID()
        w = Quartz.CGDisplayPixelsWide(main)
        h = Quartz.CGDisplayPixelsHigh(main)
        return int(w), int(h)
    except ImportError:
        pass
    # Fallback: system_profiler
    try:
        result = subprocess.run(
            ['system_profiler', 'SPDisplaysDataType'],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if 'Resolution' in line:
                # "Resolution: 1512 x 982 Retina"
                parts = line.split(':')[1].strip().split()
                w = int(parts[0])
                h = int(parts[2])
                return w, h
    except Exception as e:
        raise RuntimeError(f"Screen size detection failed (system_profiler): {e}")
    raise RuntimeError("Screen size detection failed on macOS")


def _detect_screen_size() -> tuple:
    """Detect screen dimensions (cross-platform)."""
    if sys.platform == 'darwin':
        return _detect_screen_size_macos()
    return _detect_screen_size_linux()


# Tab shortcuts (Alt+N) configured in Firefox
TAB_SHORTCUTS = {
    'chatgpt': 'alt+1',
    'claude': 'alt+2',
    'gemini': 'alt+3',
    'grok': 'alt+4',
    'perplexity': 'alt+5',
    # Social platforms
    'x_twitter': 'alt+6',
    # 'linkedin': 'alt+7',
}

# URL patterns for platform detection via AT-SPI DocURL
URL_PATTERNS = {
    'chatgpt': 'chatgpt.com',
    'claude': 'claude.ai',
    'gemini': 'gemini.google.com',
    'grok': 'grok.com',
    'perplexity': 'perplexity.ai',
    'x_twitter': 'x.com',
    'linkedin': 'linkedin.com',
}

# Base URLs for new sessions
BASE_URLS = {
    'chatgpt': 'https://chatgpt.com/',
    'claude': 'https://claude.ai/new',
    'gemini': 'https://gemini.google.com/app',
    'grok': 'https://grok.com/',
    'perplexity': 'https://perplexity.ai/',
    'x_twitter': 'https://x.com/home',
    'linkedin': 'https://www.linkedin.com/feed/',
}

# Chat AI platforms (have copy buttons, response detection)
CHAT_PLATFORMS = {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}

# Social platforms (posting, replying, searching)
SOCIAL_PLATFORMS = {'x_twitter', 'linkedin'}

# All platforms
ALL_PLATFORMS = CHAT_PLATFORMS | SOCIAL_PLATFORMS

# Screen bounds (lazy-detected from X display on first access)
_screen_size = None


def get_screen_size() -> tuple:
    """Get screen dimensions, detecting on first call.

    Returns:
        (width, height) tuple.

    Raises:
        RuntimeError: If screen size cannot be detected.
    """
    global _screen_size
    if _screen_size is None:
        _screen_size = _detect_screen_size()
    return _screen_size


# Module-level aliases for backward compat - these are properties
# that raise on access if DISPLAY is unavailable.
class _LazyScreenDim:
    def __init__(self, index):
        self._index = index

    def __int__(self):
        return get_screen_size()[self._index]

    def __eq__(self, other):
        return int(self) == other

    def __lt__(self, other):
        return int(self) < other

    def __le__(self, other):
        return int(self) <= other

    def __gt__(self, other):
        return int(self) > other

    def __ge__(self, other):
        return int(self) >= other

    def __floordiv__(self, other):
        return int(self) // other

    def __repr__(self):
        return str(int(self))


SCREEN_WIDTH = _LazyScreenDim(0)
SCREEN_HEIGHT = _LazyScreenDim(1)
