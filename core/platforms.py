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

# ─── Multi-Display Support ──────────────────────────────────────────────
# Set PLATFORM_DISPLAYS env var: "chatgpt:2,claude:3,gemini:4,grok:5,perplexity:6"
# If not set, all platforms use the server's DISPLAY (tab-switching mode).
_PLATFORM_DISPLAYS: dict[str, str] = {}

def _parse_platform_displays():
    raw = os.environ.get('PLATFORM_DISPLAYS', '')
    if not raw:
        env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('PLATFORM_DISPLAYS='):
                        raw = line.split('=', 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    if not raw:
        return
    for pair in raw.split(','):
        pair = pair.strip()
        if ':' in pair:
            plat, dnum = pair.rsplit(':', 1)
            _PLATFORM_DISPLAYS[plat.strip()] = f':{dnum.strip()}'

_parse_platform_displays()


def get_platform_display(platform: str) -> str | None:
    """Return the dedicated display for a platform, or None for tab-switching mode."""
    return _PLATFORM_DISPLAYS.get(platform)


def get_platform_bus(platform: str) -> str | None:
    """Read AT-SPI bus address for a platform's dedicated display."""
    display = get_platform_display(platform)
    if not display:
        return None
    bus_file = f'/tmp/a11y_bus_{display}'
    try:
        with open(bus_file) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def get_platform_firefox_pid(platform: str) -> int | None:
    """Read Firefox PID for a platform's dedicated display."""
    display = get_platform_display(platform)
    if not display:
        return None
    pid_file = f'/tmp/firefox_pid_{display}'
    try:
        with open(pid_file) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def is_multi_display() -> bool:
    """True if PLATFORM_DISPLAYS is configured (Mira mode)."""
    return bool(_PLATFORM_DISPLAYS)
