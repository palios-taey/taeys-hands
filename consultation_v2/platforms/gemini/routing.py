from __future__ import annotations

from consultation_v2.platforms._routing_core import (
    RouteSpec,
    find_firefox as _find_firefox,
    get_document as _get_document,
    route_display as _route_display,
    switch_to_platform as _switch_to_platform,
    url_matches as _url_matches,
)

_SPEC = RouteSpec(
    platform='gemini',
    url_patterns=('gemini.google.com',),
    displays=(':4', ':22'),
    default_tab_shortcut='alt+3',
    worker_tab_shortcut='alt+3',
)


def url_matches(url: str | None) -> bool:
    return _url_matches(_SPEC, url)


def get_document(firefox):
    return _get_document(_SPEC, firefox)


def route_display() -> str | None:
    return _route_display(_SPEC)


def find_firefox(*, pid: int | None = None):
    return _find_firefox(_SPEC, pid=pid)


def switch_to_platform() -> bool:
    return _switch_to_platform(_SPEC)
