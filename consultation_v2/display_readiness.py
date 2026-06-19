"""Display readiness validation before a consultation touches a browser.

Validation only: this module reports what is wrong and, where known, how to
recover manually. It never closes windows, restarts displays, or mutates browser
state. It temporarily scopes process AT-SPI environment while reading one
display, then restores the caller's environment before returning.
"""
from __future__ import annotations

import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from consultation_v2.yaml_contract import load_platform_yaml


MACHINE_ENV = Path(os.environ.get('TAEY_MACHINE_ENV', '~/.taey/machine.env')).expanduser()
CHAT_PLATFORMS = {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}
AT_SPI_ENV_KEYS = ('DISPLAY', 'AT_SPI_BUS_ADDRESS', 'DBUS_SESSION_BUS_ADDRESS')


def _sh(cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _machine_display_records() -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    try:
        lines = MACHINE_ENV.read_text().splitlines()
    except FileNotFoundError:
        return records

    pattern = re.compile(r'^TAEY_DISPLAY_(\d+)\s*=\s*(.+)$')
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = pattern.match(line)
        if not match:
            continue
        display_num, raw_value = match.groups()
        value = _unquote(raw_value)
        parts = value.split(':', 2)
        if len(parts) < 2:
            continue
        platform = parts[0].strip()
        if not platform:
            continue
        records[platform] = {
            'display': f':{display_num}',
            'profile': parts[1].strip(),
            'launch_url': parts[2].strip() if len(parts) > 2 else '',
        }
    return records


def available_platforms() -> list[str]:
    return sorted(platform for platform in _machine_display_records() if platform in CHAT_PLATFORMS)


def _display_for_platform(platform: str) -> str | None:
    record = _machine_display_records().get(platform)
    return record['display'] if record else None


def _expected_host(platform: str) -> str | None:
    cfg = load_platform_yaml(platform)
    fresh = str((cfg.get('urls') or {}).get('fresh') or '').strip()
    if not fresh:
        return None
    parsed = urlparse(fresh)
    host = parsed.netloc or parsed.path.split('/', 1)[0]
    return host.split('@')[-1].split(':', 1)[0].lower() or None


def _host_matches(expected_host: str | None, url: str | None) -> bool:
    if not expected_host or not url:
        return False
    actual = urlparse(url).netloc.split('@')[-1].split(':', 1)[0].lower()
    expected = expected_host.lower()
    return actual == expected or actual.removeprefix('www.') == expected.removeprefix('www.')


def _live_bus(display: str) -> str | None:
    out = _sh(f'xprop -display {display} -root AT_SPI_BUS').stdout
    match = re.search(r'unix:[^"]+', out)
    return match.group(0) if match else None


@contextmanager
def _scoped_atspi_env(display: str, live_bus: str):
    saved = {key: os.environ.get(key) for key in AT_SPI_ENV_KEYS}
    os.environ['DISPLAY'] = display
    os.environ['AT_SPI_BUS_ADDRESS'] = live_bus
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = live_bus
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _viewable_windows(display: str) -> int:
    # Count only real visible windows: Firefox also keeps tiny internal windows
    # that may be IsViewable, so require real geometry as well.
    viewable = 0
    for window_id in _sh(f'DISPLAY={display} xdotool search --class firefox').stdout.split():
        info = _sh(f'DISPLAY={display} xwininfo -id {window_id}').stdout
        if 'IsViewable' not in info:
            continue
        width_match = re.search(r'Width:\s*(\d+)', info)
        height_match = re.search(r'Height:\s*(\d+)', info)
        if (
            width_match
            and height_match
            and int(width_match.group(1)) > 100
            and int(height_match.group(1)) > 100
        ):
            viewable += 1
    return viewable


def _count_tabs_and_url(platform: str) -> tuple[int, str | None, int]:
    """Return readable tree size, active URL, and real tab-strip page-tab count.

    Caller must scope DISPLAY/AT_SPI_BUS_ADDRESS/DBUS_SESSION_BUS_ADDRESS to the
    target display before calling.
    """
    from consultation_v2.runtime import ConsultationRuntime

    runtime = ConsultationRuntime(platform)
    runtime.switch()
    snapshot = runtime.snapshot()
    total = sum(len(v) for v in (snapshot.mapped or {}).values()) + len(snapshot.unknown or [])
    url = snapshot.url or runtime.current_url()

    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi

    desktop = Atspi.get_desktop(0)
    page_tabs = 0

    def walk(obj: Any, depth: int = 0) -> None:
        nonlocal page_tabs
        try:
            if obj.get_role_name() == 'page tab':
                page_tabs += 1
            if depth >= 25:
                return
            for index in range(obj.get_child_count()):
                child = obj.get_child_at_index(index)
                if child is not None:
                    walk(child, depth + 1)
        except Exception:
            pass

    for index in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(index)
        try:
            if 'firefox' in (app.get_name() or '').lower():
                walk(app)
        except Exception:
            pass
    return total, url, page_tabs


def _add_issue(issues: list[str], resolutions: list[str], issue: str, resolution: str | None = None) -> None:
    issues.append(issue)
    if resolution:
        resolutions.append(resolution)


def _display_num(display: str | None) -> str:
    return (display or '').lstrip(':')


def check(platform: str) -> dict[str, Any]:
    platform = platform.strip()
    display = _display_for_platform(platform)
    issues: list[str] = []
    resolutions: list[str] = []

    if not display:
        return {
            'platform': platform,
            'display': None,
            'ready': False,
            'layer_failed': 'L1',
            'issues': [f'L1: no TAEY_DISPLAY_N entry for {platform} in {MACHINE_ENV}'],
            'resolutions': [f'Add {platform}:profile:url to a TAEY_DISPLAY_N entry in {MACHINE_ENV}'],
            'windows': None,
            'tabs': None,
            'url': None,
            'expected_host': None,
            'tree': None,
        }

    if _sh(f'DISPLAY={display} xdotool getdisplaygeometry').returncode != 0:
        return {
            'platform': platform,
            'display': display,
            'ready': False,
            'layer_failed': 'L1',
            'issues': [f'L1: Xvfb display {display} not reachable'],
            'resolutions': [f'Restart display {display} with scripts/restart_display.sh {_display_num(display)} or the matching systemd unit'],
            'windows': None,
            'tabs': None,
            'url': None,
            'expected_host': _expected_host(platform),
            'tree': None,
        }

    live_bus = _live_bus(display)
    if not live_bus:
        _add_issue(
            issues,
            resolutions,
            'L1: no AT_SPI_BUS on display root',
            f'Restart display {display}; expected xprop -display {display} -root AT_SPI_BUS to expose a unix bus',
        )

    total = 0
    url = None
    tabs = None
    if live_bus:
        try:
            with _scoped_atspi_env(display, live_bus):
                total, url, tabs = _count_tabs_and_url(platform)
            if total < 5:
                _add_issue(
                    issues,
                    resolutions,
                    f'L1: tree near-empty ({total} elems), accessibility registration likely broken',
                    f'Restart display {display} and confirm /tmp/a11y_bus_{display} matches xprop AT_SPI_BUS',
                )
        except Exception as exc:
            return {
                'platform': platform,
                'display': display,
                'ready': False,
                'layer_failed': 'L1',
                'issues': [f'L1: cannot read tree ({type(exc).__name__}: {exc})'],
                'resolutions': [f'Restart display {display}; if it recurs, inspect Firefox/AT-SPI registration on that display'],
                'windows': None,
                'tabs': None,
                'url': None,
                'expected_host': _expected_host(platform),
                'tree': 0,
            }

    visible_windows = _viewable_windows(display)
    if visible_windows != 1:
        _add_issue(
            issues,
            resolutions,
            f'L2: {visible_windows} visible Firefox windows (want exactly 1)',
            f'Close extra visible Firefox windows on {display} or restart display {display}',
        )
    if tabs is not None and tabs != 1:
        _add_issue(
            issues,
            resolutions,
            f'L2: {tabs} tabs in tab-strip (want exactly 1)',
            f'Close extra Firefox tabs on {display} or restart display {display}',
        )

    expected_host = _expected_host(platform)
    if live_bus and not _host_matches(expected_host, url):
        _add_issue(
            issues,
            resolutions,
            f'L2: active tab url={url!r} is not the expected Chat host ({expected_host})',
            f'Navigate display {display} to the platform YAML urls.fresh host before running the consult',
        )

    return {
        'platform': platform,
        'display': display,
        'ready': len(issues) == 0,
        'layer_failed': ('L1' if any(item.startswith('L1') for item in issues) else ('L2' if issues else None)),
        'issues': issues,
        'resolutions': resolutions,
        'windows': visible_windows,
        'tabs': tabs,
        'url': url,
        'expected_host': expected_host,
        'tree': total,
    }
