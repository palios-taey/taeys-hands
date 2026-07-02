"""Platform definitions: URL patterns, tab shortcuts, screen detection."""

import os
import re
import subprocess
from pathlib import Path
from typing import Mapping


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

# Tab shortcuts. Dedicated-display deployments do not use tab switching;
# TAEY_TAB_PROFILE keeps the legacy reduced-tab mode explicit when needed.
_DEFAULT_TABS = {
    'chatgpt': 'alt+1', 'claude': 'alt+2', 'gemini': 'alt+3',
    'grok': 'alt+4', 'perplexity': 'alt+5', 'x_twitter': 'alt+6',
}
_WORKER_TABS = {
    'chatgpt': 'alt+1', 'claude': 'alt+2', 'gemini': 'alt+3', 'grok': 'alt+4',
}

_TAB_PROFILE = os.environ.get('TAEY_TAB_PROFILE', 'default').strip().lower()
if _TAB_PROFILE not in {'default', 'worker'}:
    raise RuntimeError(f"Unsupported TAEY_TAB_PROFILE={_TAB_PROFILE!r}; expected default or worker")
TAB_SHORTCUTS = _WORKER_TABS if _TAB_PROFILE == 'worker' else _DEFAULT_TABS

# URL patterns for platform detection (order: specific first)
_EXTRA_URL_PATTERNS = {'grok': 'x.com/i/grok'}
URL_PATTERNS = {
    'chatgpt': 'chatgpt.com', 'claude': 'claude.ai',
    'gemini': 'gemini.google.com', 'grok': 'grok.com',
    'perplexity': 'perplexity.ai', 'x_twitter': 'x.com',
    'linkedin': 'linkedin.com',
    # Treasurer-side platforms used by external automation.
    'upwork': 'upwork.com',
    'lesswrong': 'lesswrong.com',
    'reddit': 'reddit.com',
    'nvidia_forum': 'developer.nvidia.com',  # matches both forums.developer.nvidia.com and login on developer.nvidia.com
    'ea_funds': 'effectivealtruism.org',
    'paperform': 'paperform.co',  # EA Funds form host
}

BASE_URLS = {
    'chatgpt': 'https://chatgpt.com/',
    'claude': 'https://claude.ai/new',
    'gemini': 'https://gemini.google.com/app',
    'grok': 'https://grok.com/',
    'perplexity': 'https://perplexity.ai/',
    'x_twitter': '<AUXILIARY_URL>',
    'linkedin': 'https://www.linkedin.com/feed/',
    'reddit': '<AUXILIARY_URL>',
    'nvidia_forum': '<AUXILIARY_URL>/',
}

CHAT_PLATFORMS = {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}
SOCIAL_PLATFORMS = {'x_twitter', 'linkedin', 'reddit', 'nvidia_forum'}
ALL_PLATFORMS = CHAT_PLATFORMS | SOCIAL_PLATFORMS

# Multi-display support.
# Sources, in precedence order:
#   1. PLATFORM_DISPLAYS env var or repo .env:
#      "chatgpt:2,claude:3,gemini:4,grok:5,perplexity:6"
#   2. TAEY_MACHINE_ENV or ~/.taey/machine.env TAEY_DISPLAY_N rows:
#      TAEY_DISPLAY_2="chatgpt:ff-profile-chatgpt:https://chatgpt.com/"
# If no source is configured, all platforms use the current DISPLAY.
_PLATFORM_DISPLAYS: dict[str, list[str]] = {}
_SELECTED_DISPLAY_ENV = 'TAEY_SELECTED_DISPLAY'
_DISPLAY_ENV_KEYS = ('DISPLAY', 'AT_SPI_BUS_ADDRESS', 'DBUS_SESSION_BUS_ADDRESS')


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def _read_repo_dotenv_platform_displays() -> str:
    env_file = Path(__file__).resolve().parents[1] / '.env'
    try:
        with env_file.open() as f:
            for line in f:
                line = line.strip()
                if line.startswith('PLATFORM_DISPLAYS='):
                    return _strip_env_value(line.split('=', 1)[1])
    except FileNotFoundError:
        return ''
    return ''


def _normalize_display(display: str | None) -> str | None:
    value = str(display or '').strip()
    if not value:
        return None
    display_num = value[1:] if value.startswith(':') else value
    if not display_num.isdigit():
        return None
    return f':{display_num}'


def _add_platform_display(displays: dict[str, list[str]], platform: str, display: str) -> None:
    platform = platform.strip()
    normalized = _normalize_display(display)
    if not platform or not normalized:
        return
    bucket = displays.setdefault(platform, [])
    if normalized not in bucket:
        bucket.append(normalized)


def _parse_platform_display_pairs(raw: str) -> dict[str, list[str]]:
    displays: dict[str, list[str]] = {}
    for pair in raw.split(','):
        pair = pair.strip()
        if not pair:
            continue
        if ':' not in pair:
            raise RuntimeError(f"Malformed PLATFORM_DISPLAYS pair {pair!r}; expected platform:display")
        plat, dnum = pair.rsplit(':', 1)
        plat = plat.strip()
        dnum = dnum.strip().lstrip(':')
        if not plat or not dnum.isdigit():
            raise RuntimeError(f"Malformed PLATFORM_DISPLAYS pair {pair!r}; expected platform:display")
        _add_platform_display(displays, plat, f':{dnum}')
    return displays


def get_machine_env_path() -> Path:
    return Path(os.environ.get('TAEY_MACHINE_ENV', '~/.taey/machine.env')).expanduser()


def _read_machine_env_platform_displays() -> dict[str, list[str]]:
    machine_env = get_machine_env_path()
    try:
        lines = machine_env.read_text().splitlines()
    except FileNotFoundError:
        return {}

    displays: dict[str, list[str]] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        key = key.strip()
        if not key.startswith('TAEY_DISPLAY_'):
            continue
        display_num = key.removeprefix('TAEY_DISPLAY_')
        if not display_num.isdigit():
            raise RuntimeError(f"Malformed {key} in {machine_env}; display suffix must be numeric")
        value = _strip_env_value(value)
        parts = value.split(':', 2)
        if len(parts) != 3 or not parts[0].strip():
            raise RuntimeError(f"Malformed {key} in {machine_env}; expected platform:profile:url")
        _add_platform_display(displays, parts[0].strip(), f':{display_num}')
    return displays


def _parse_platform_displays():
    raw = os.environ.get('PLATFORM_DISPLAYS', '').strip()
    if not raw:
        raw = _read_repo_dotenv_platform_displays()
    parsed = _parse_platform_display_pairs(raw) if raw else _read_machine_env_platform_displays()
    for platform, displays in parsed.items():
        for display in displays:
            _add_platform_display(_PLATFORM_DISPLAYS, platform, display)


def _selected_display_env_key(platform: str) -> str:
    safe_platform = re.sub(r'[^A-Z0-9]+', '_', platform.strip().upper()).strip('_')
    return f'{_SELECTED_DISPLAY_ENV}_{safe_platform}' if safe_platform else _SELECTED_DISPLAY_ENV


def _explicit_selected_display(platform: str, candidates: tuple[str, ...]) -> str | None:
    for env_name in (_selected_display_env_key(platform), _SELECTED_DISPLAY_ENV):
        value = _normalize_display(os.environ.get(env_name))
        if not value:
            continue
        if candidates and value not in candidates:
            raise RuntimeError(
                f"{env_name}={value!r} is not configured for {platform}; "
                f"candidates={list(candidates)!r}"
            )
        return value
    return None


def _current_display_if_candidate(candidates: tuple[str, ...]) -> str | None:
    current = _normalize_display(os.environ.get('DISPLAY'))
    if current and current in candidates:
        return current
    return None


def get_platform_displays(platform: str) -> tuple[str, ...]:
    """Return every dedicated display configured for a platform, in env order."""
    return tuple(_PLATFORM_DISPLAYS.get(platform, ()))


def configured_platforms() -> tuple[str, ...]:
    return tuple(sorted(_PLATFORM_DISPLAYS))


def set_platform_display(platform: str, display: str) -> str:
    """Select one configured display for this process' platform route."""
    candidates = get_platform_displays(platform)
    normalized = _normalize_display(display)
    if not normalized:
        raise RuntimeError(f"Invalid display for {platform}: {display!r}")
    if candidates and normalized not in candidates:
        raise RuntimeError(
            f"Display {normalized} is not configured for {platform}; "
            f"candidates={list(candidates)!r}"
        )
    os.environ[_selected_display_env_key(platform)] = normalized
    os.environ[_SELECTED_DISPLAY_ENV] = normalized
    os.environ['DISPLAY'] = normalized
    return normalized


def select_platform_display(platform: str, is_available=None) -> str | None:
    """Choose the display this process should use for a platform.

    ``is_available`` is a caller-supplied predicate so the pre-import CLI wrapper
    can check Redis locks without importing the full consultation runtime.
    """
    candidates = get_platform_displays(platform)
    if not candidates:
        return None

    explicit = _explicit_selected_display(platform, candidates)
    if explicit:
        return set_platform_display(platform, explicit)

    preferred = _current_display_if_candidate(candidates)
    ordered = list(candidates)
    if preferred:
        ordered = [preferred] + [display for display in ordered if display != preferred]

    for display in ordered:
        if is_available is None or is_available(display):
            return set_platform_display(platform, display)

    return set_platform_display(platform, preferred or candidates[0])

_parse_platform_displays()


def get_platform_display(platform: str) -> str | None:
    """Return the dedicated display for a platform, or None for tab-switching mode."""
    candidates = get_platform_displays(platform)
    if not candidates:
        return None
    return (
        _explicit_selected_display(platform, candidates)
        or _current_display_if_candidate(candidates)
        or candidates[0]
    )


def get_display_bus(display: str) -> str | None:
    """Resolve the AT-SPI bus for a display from cache, then live X root fallback."""
    bus_file = f'/tmp/a11y_bus_{display}'
    addr = None

    try:
        with open(bus_file) as f:
            addr = f.read().strip() or None
    except FileNotFoundError:
        addr = None

    if addr:
        return addr

    try:
        result = subprocess.run(
            ['xprop', '-display', display, '-root', 'AT_SPI_BUS'],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ},
        )
    except Exception:
        return None

    parts = result.stdout.split('"')
    cand = parts[1].strip() if len(parts) >= 2 else ''
    if not cand.startswith('unix:'):
        return None

    try:
        with open(bus_file, 'w') as f:
            f.write(cand + '\n')
    except OSError:
        pass
    return cand


def get_platform_bus(platform: str) -> str | None:
    """Read AT-SPI bus address for a platform's dedicated display."""
    display = get_platform_display(platform)
    if not display:
        return None
    return get_display_bus(display)


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
    """True if platform-to-display routing is configured."""
    return bool(_PLATFORM_DISPLAYS)


def get_display_dbus(display: str) -> str | None:
    """Resolve the D-Bus session address for a display."""
    normalized = _normalize_display(display)
    if not normalized:
        return None
    bus_file = f'/tmp/dbus_session_bus_{normalized}'
    try:
        with open(bus_file) as f:
            addr = f.read().strip() or None
    except FileNotFoundError:
        addr = None
    if addr:
        return addr
    current = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
    if current:
        return current
    return f'unix:path=/run/user/{os.getuid()}/bus'


def display_environment(
    display: str,
    *,
    base: Mapping[str, str] | None = None,
    at_spi_bus: str | None = None,
) -> dict[str, str]:
    """Return environment scoped to one X display and its AT-SPI bus."""
    normalized = _normalize_display(display)
    if not normalized:
        raise RuntimeError(f"Invalid display: {display!r}")
    env = dict(base or os.environ)
    env['DISPLAY'] = normalized
    bus = at_spi_bus or get_display_bus(normalized)
    if bus:
        env['AT_SPI_BUS_ADDRESS'] = bus
    dbus = get_display_dbus(normalized)
    if dbus:
        env['DBUS_SESSION_BUS_ADDRESS'] = dbus
    return env


def apply_display_environment(display: str) -> dict[str, str]:
    """Scope process env to one display and return the updated display keys."""
    env = display_environment(display)
    updated: dict[str, str] = {}
    for key in _DISPLAY_ENV_KEYS:
        value = env.get(key)
        if value:
            os.environ[key] = value
            updated[key] = value
        else:
            os.environ.pop(key, None)
    return updated
