"""Mapped scroll and extraction reads for the supervised ``drive_chat`` lane.

Import this module only after the caller has bound ``DISPLAY`` and the AT-SPI
bus.  The caller continues to own display locking, flat observation, actions,
and JSON serialization.
"""

from __future__ import annotations

from typing import Any

from .platforms.routing import find_firefox_for_platform
from .runtime import ConsultationRuntime
from .snapshot import matches_spec
from .tree import find_elements


_SCROLL_CLICKS = 14
_SCROLL_ROUNDS = 3
_SCROLL_SETTLE_SECONDS = 0.5


class DriveChatAdapterError(RuntimeError):
    pass


def _scroll(runtime: ConsultationRuntime) -> None:
    if not runtime.scroll_document_to_bottom(
        clicks=_SCROLL_CLICKS,
        rounds=_SCROLL_ROUNDS,
        settle=_SCROLL_SETTLE_SECONDS,
    ):
        raise DriveChatAdapterError(
            f'{runtime.platform}: scroll_document_to_bottom returned false'
        )


def scroll(platform: str) -> dict[str, Any]:
    runtime = ConsultationRuntime(platform)
    _scroll(runtime)
    return {
        'platform': platform,
        'scrolled': True,
        'clicks': _SCROLL_CLICKS,
        'rounds': _SCROLL_ROUNDS,
        'settle_seconds': _SCROLL_SETTLE_SECONDS,
    }


def extract(platform: str) -> dict[str, Any]:
    runtime = ConsultationRuntime(platform)
    extract_cfg = runtime.cfg.get('workflow', {}).get('extract') or {}
    element_key = extract_cfg.get('primary_key')
    strategy = extract_cfg.get('strategy')
    element_map = runtime.cfg.get('tree', {}).get('element_map') or {}
    spec = element_map.get(element_key) if element_key else None

    if not element_key or not isinstance(spec, dict):
        raise DriveChatAdapterError(
            f'{platform}: workflow.extract.primary_key does not resolve to an element_map entry'
        )
    if strategy != 'last_by_y':
        raise DriveChatAdapterError(
            f'{platform}: unsupported workflow.extract.strategy {strategy!r}'
        )
    if 'structural' in spec:
        raise DriveChatAdapterError(
            f'{platform}: extraction control {element_key!r} requires structural resolution'
        )

    _scroll(runtime)
    firefox = find_firefox_for_platform(platform)
    if firefox is None:
        raise DriveChatAdapterError(f'{platform}: Firefox not found after scroll')
    try:
        firefox.clear_cache_single()
    except Exception:
        pass

    elements = find_elements(firefox, fence_after=[])
    candidates = [
        element
        for element in elements
        if element.get('y') is not None and matches_spec(element, spec)
    ]
    if not candidates:
        raise DriveChatAdapterError(
            f'{platform}: mapped extraction control {element_key!r} not found after scroll'
        )

    target = dict(max(candidates, key=lambda item: (item.get('y') or 0, item.get('x') or 0)))
    target.setdefault('states', [])
    target.setdefault('text', '')
    target['element_key'] = element_key
    target['match_count'] = len(candidates)
    target['selection'] = strategy
    target['scroll_ok'] = True
    return target


__all__ = ['DriveChatAdapterError', 'extract', 'scroll']
