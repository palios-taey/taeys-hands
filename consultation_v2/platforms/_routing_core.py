"""Mechanical helpers used by package-owned platform routing modules."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from consultation_v2 import atspi, clipboard, input as input_core
from consultation_v2.platforms_runtime import (
    get_display_bus,
    get_platform_display,
    get_platform_firefox_pid,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteSpec:
    platform: str
    url_patterns: tuple[str, ...]
    extra_url_patterns: tuple[str, ...] = ()
    default_tab_shortcut: str | None = None
    worker_tab_shortcut: str | None = None


def url_matches(spec: RouteSpec, url: str | None) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    for pattern in spec.extra_url_patterns:
        if pattern.lower() in url_lower:
            return True
    for pattern in spec.url_patterns:
        if pattern.lower() in url_lower:
            return True
    return False


def get_document(spec: RouteSpec, firefox):
    if not firefox:
        return None
    matches = [
        candidate
        for candidate in atspi.document_web_elements(firefox)
        if url_matches(spec, atspi.get_document_url(candidate))
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    for match in matches:
        try:
            if match.get_state_set().contains(atspi.Atspi.StateType.SHOWING):
                return match
        except Exception:
            pass
    matches.sort(key=lambda match: match.get_child_count(), reverse=True)
    return matches[0]


def _normalize_display(display: str | None) -> str | None:
    value = str(display or '').strip()
    if not value:
        return None
    display_num = value[1:] if value.startswith(':') else value
    if not display_num.isdigit():
        return value
    return f':{display_num}'


def _assert_route_os_binding(spec: RouteSpec) -> None:
    expected_display = _normalize_display(get_platform_display(spec.platform))
    if not expected_display:
        return

    actual_display = _normalize_display(os.environ.get('DISPLAY'))
    if actual_display != expected_display:
        raise RuntimeError(
            f"{spec.platform} route binding mismatch: expected DISPLAY "
            f"{expected_display!r}, got {actual_display!r}"
        )

    expected_bus = get_display_bus(expected_display)
    if not expected_bus:
        raise RuntimeError(
            f"{spec.platform} route binding mismatch: no AT-SPI bus for "
            f"DISPLAY {expected_display!r}"
        )

    actual_bus = os.environ.get('AT_SPI_BUS_ADDRESS')
    if actual_bus != expected_bus:
        raise RuntimeError(
            f"{spec.platform} route binding mismatch on DISPLAY "
            f"{expected_display!r}: expected AT_SPI_BUS_ADDRESS "
            f"{expected_bus!r}, got {actual_bus!r}"
        )


def _assert_firefox_process_binding(spec: RouteSpec, firefox, *, pid: int | None):
    if firefox is None or pid is None:
        return firefox
    try:
        actual_pid = firefox.get_process_id()
    except Exception as exc:
        raise RuntimeError(
            f"{spec.platform} route binding mismatch: could not read Firefox PID"
        ) from exc
    if actual_pid != pid:
        raise RuntimeError(
            f"{spec.platform} route binding mismatch: expected Firefox PID "
            f"{pid}, got {actual_pid}"
        )
    return firefox


def find_firefox(spec: RouteSpec, *, pid: int | None = None):
    _assert_route_os_binding(spec)
    all_firefox = atspi.find_all_firefox(pid=pid)
    if not all_firefox:
        return None
    if len(all_firefox) == 1:
        return _assert_firefox_process_binding(spec, all_firefox[0], pid=pid)
    for firefox in all_firefox:
        if get_document(spec, firefox):
            return _assert_firefox_process_binding(spec, firefox, pid=pid)
    logger.error("No Firefox instance has %s document", spec.platform)
    return None


def tab_shortcut(spec: RouteSpec) -> str | None:
    profile = os.environ.get('TAEY_TAB_PROFILE', 'default').strip().lower()
    if profile == 'worker':
        return spec.worker_tab_shortcut
    if profile != 'default':
        raise RuntimeError(f"Unsupported TAEY_TAB_PROFILE={profile!r}; expected default or worker")
    return spec.default_tab_shortcut


def _document_showing(spec: RouteSpec, *, display: str | None, pid: int | None) -> bool:
    if display:
        input_core.set_display(display)
    firefox = find_firefox(spec, pid=pid)
    if not firefox:
        return False
    doc = get_document(spec, firefox)
    if not doc:
        return False
    try:
        return doc.get_state_set().contains(atspi.Atspi.StateType.SHOWING)
    except Exception:
        return False


def switch_to_platform(spec: RouteSpec) -> bool:
    display = get_platform_display(spec.platform)
    if display:
        input_core.set_display(display)
        clipboard.set_display(display)

        firefox_pid = get_platform_firefox_pid(spec.platform)
        if firefox_pid:
            if input_core.focus_firefox_pid(firefox_pid) and _document_showing(
                spec, display=display, pid=firefox_pid,
            ):
                return True
        else:
            logger.warning(
                "No Firefox PID file for %s; falling back to AT-SPI discovery",
                spec.platform,
            )

        discovered_firefox = find_firefox(spec)
        discovered_pid = None
        if discovered_firefox:
            try:
                discovered_pid = discovered_firefox.get_process_id()
            except Exception:
                discovered_pid = None

            if discovered_pid and discovered_pid != firefox_pid:
                logger.warning(
                    "Stale Firefox PID %s for %s; AT-SPI discovered PID %s",
                    firefox_pid,
                    spec.platform,
                    discovered_pid,
                )

            if input_core.focus_firefox_pid(discovered_pid) and _document_showing(
                spec, display=display, pid=discovered_pid,
            ):
                return True
            if input_core.focus_firefox() and _document_showing(
                spec, display=display, pid=discovered_pid,
            ):
                return True

        shortcut = tab_shortcut(spec)
        if shortcut:
            input_core.press_key(shortcut)
            time.sleep(0.5)
            if _document_showing(spec, display=display, pid=discovered_pid or firefox_pid):
                return True
        logger.warning("Could not switch to %s on dedicated display %s", spec.platform, display)
        return _document_showing(spec, display=display, pid=discovered_pid or firefox_pid)

    if not input_core.focus_firefox():
        return False
    if _document_showing(spec, display=None, pid=None):
        return True

    shortcut = tab_shortcut(spec)
    if shortcut:
        input_core.press_key(shortcut)
        time.sleep(0.5)
        return True

    for _ in range(8):
        input_core.press_key('ctrl+Tab')
        time.sleep(0.4)
        if _document_showing(spec, display=None, pid=None):
            return True
    logger.warning("Could not switch to %s", spec.platform)
    return False
