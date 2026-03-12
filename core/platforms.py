"""Platform definitions: URL patterns, tab shortcuts, screen detection."""

import os
import socket
import subprocess


def _detect_screen_size() -> tuple:
    """Detect screen dimensions via xdpyinfo."""
    try:
        result = subprocess.run(
            ['xdpyinfo'], capture_output=True, text=True, timeout=5,
            env={**os.environ},
        )
        for line in result.stdout.splitlines():
            if 'dimensions:' in line:
                w, h = line.strip().split()[1].split('x')
                return int(w), int(h)
    except Exception as e:
        raise RuntimeError(f"Screen size detection failed: {e}")
    raise RuntimeError("No 'dimensions:' line in xdpyinfo output")


_screen_size = None


def get_screen_size() -> tuple:
    """Get (width, height), detecting on first call."""
    global _screen_size
    if _screen_size is None:
        _screen_size = _detect_screen_size()
    return _screen_size


# Lazy accessors for SCREEN_WIDTH / SCREEN_HEIGHT
class _LazyDim:
    def __init__(self, idx):
        self._idx = idx
    def __int__(self):
        return get_screen_size()[self._idx]
    def __eq__(self, o):  return int(self) == o
    def __lt__(self, o):  return int(self) < o
    def __le__(self, o):  return int(self) <= o
    def __gt__(self, o):  return int(self) > o
    def __ge__(self, o):  return int(self) >= o
    def __floordiv__(self, o): return int(self) // o
    def __repr__(self): return str(int(self))


SCREEN_WIDTH = _LazyDim(0)
SCREEN_HEIGHT = _LazyDim(1)

# Tab shortcuts — workers have fewer tabs
_WORKER_HOSTNAMES = {'jetson', 'thor'}
_DEFAULT_TABS = {
    'chatgpt': 'alt+1', 'claude': 'alt+2', 'gemini': 'alt+3',
    'grok': 'alt+4', 'perplexity': 'alt+5', 'x_twitter': 'alt+6',
}
_WORKER_TABS = {
    'chatgpt': 'alt+1', 'claude': 'alt+2', 'gemini': 'alt+3', 'grok': 'alt+4',
}

_hostname = socket.gethostname().lower()
TAB_SHORTCUTS = _WORKER_TABS if _hostname in _WORKER_HOSTNAMES else _DEFAULT_TABS

# URL patterns for platform detection (order: specific first)
_EXTRA_URL_PATTERNS = {'grok': 'x.com/i/grok'}
URL_PATTERNS = {
    'chatgpt': 'chatgpt.com', 'claude': 'claude.ai',
    'gemini': 'gemini.google.com', 'grok': 'grok.com',
    'perplexity': 'perplexity.ai', 'x_twitter': 'x.com',
    'linkedin': 'linkedin.com',
}

BASE_URLS = {
    'chatgpt': 'https://chatgpt.com/',
    'claude': 'https://claude.ai/new',
    'gemini': 'https://gemini.google.com/app',
    'grok': 'https://grok.com/',
    'perplexity': 'https://perplexity.ai/',
    'x_twitter': 'https://x.com/home',
    'linkedin': 'https://www.linkedin.com/feed/',
}

CHAT_PLATFORMS = {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}
SOCIAL_PLATFORMS = {'x_twitter', 'linkedin'}
ALL_PLATFORMS = CHAT_PLATFORMS | SOCIAL_PLATFORMS
