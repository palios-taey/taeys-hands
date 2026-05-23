#!/usr/bin/env python3
"""AT-SPI posting helpers for taeys-hands element dictionaries."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable

from core import input as inp

logger = logging.getLogger(__name__)


Element = dict
ScanFunc = Callable[[], list[Element]]
Predicate = Callable[[Element], bool]


def scroll_into_band(scan_func: ScanFunc, predicate: Predicate,
                     band: tuple[int, int] = (150, 850),
                     max_iters: int = 40, clicks_per_iter: int = 3,
                     settle: float = 0.4,
                     hover_point: tuple[int, int] = (700, 500)) -> Element | None:
    """Scroll until a predicate-matched element's center y is inside band."""
    lo, hi = band
    if not inp.hover(*hover_point):
        logger.error("scroll_into_band failed: initial hover failed at %s", hover_point)
        return None

    for i in range(max_iters):
        elements = scan_func()
        elem = next((e for e in elements if predicate(e)), None)
        if elem and lo <= elem.get('y', -1) <= hi:
            return elem

        direction = 'down' if elem is None or elem.get('y', hi + 1) > hi else 'up'
        if not inp.scroll_wheel(direction, clicks=clicks_per_iter):
            logger.error(
                "scroll_into_band failed: wheel %s failed at iter %s; elem=%s",
                direction, i + 1, _element_summary(elem),
            )
            return None
        time.sleep(settle)

    elements = scan_func()
    elem = next((e for e in elements if predicate(e)), None)
    if elem and lo <= elem.get('y', -1) <= hi:
        return elem
    logger.error(
        "scroll_into_band failed: no in-band element after %s iterations; elem=%s band=%s",
        max_iters, _element_summary(elem), band,
    )
    return None


def focus_clear_paste(elem: Element, text: str, settle: float = 0.4) -> bool:
    """Click an element, clear stale React draft text, then paste text."""
    if not elem:
        logger.error("focus_clear_paste failed: missing element")
        return False
    if 'x' not in elem or 'y' not in elem:
        logger.error("focus_clear_paste failed: element lacks center coords: %s", elem)
        return False

    if not inp.click_at(elem['x'], elem['y']):
        logger.error("focus_clear_paste failed: click_at failed at (%s,%s)", elem['x'], elem['y'])
        return False
    time.sleep(settle)
    if not inp.press_key('ctrl+a'):
        logger.error("focus_clear_paste failed: ctrl+a failed")
        return False
    time.sleep(0.2)
    if not inp.press_key('Delete'):
        logger.error("focus_clear_paste failed: Delete failed")
        return False
    time.sleep(0.2)
    if not inp.clipboard_paste(text):
        logger.error("focus_clear_paste failed: clipboard paste failed")
        return False
    time.sleep(settle)
    return True


def text_landed_externally(scan_func: ScanFunc, *fragments: str) -> dict | None:
    """Scan elements below the composer for author/text fragments."""
    normalized = [_norm(f) for f in fragments if _norm(f)]
    if not normalized:
        logger.error("text_landed_externally failed: no fragments supplied")
        return None

    after_composer = False
    for elem in scan_func():
        if _is_reply_composer(elem):
            after_composer = True
            continue
        if not after_composer:
            continue
        haystack = _norm(' '.join(
            str(elem.get(k) or '') for k in ('name', 'text', 'description')
        ))
        if not haystack:
            continue
        for fragment in normalized:
            short = fragment[:25]
            if fragment in haystack or (len(short) >= 20 and short in haystack):
                return {
                    'fragment': fragment,
                    'context': haystack[:300],
                    'element': {
                        'role': elem.get('role'),
                        'name': elem.get('name'),
                        'x': elem.get('x'),
                        'y': elem.get('y'),
                    },
                }
    return None


def any_fragment_landed(scan_func: ScanFunc, fragments: Iterable[str]) -> dict | None:
    """Convenience wrapper for dynamic fragment lists."""
    return text_landed_externally(scan_func, *list(fragments))


def _norm(value: str) -> str:
    return re.sub(r'\s+', ' ', value or '').strip().lower()


def _is_reply_composer(elem: Element) -> bool:
    return (elem.get('role') == 'entry'
            and elem.get('name') == 'Post text'
            and 'editable' in elem.get('states', []))


def _element_summary(elem: Element | None) -> dict | None:
    if not elem:
        return None
    return {
        'role': elem.get('role'),
        'name': elem.get('name'),
        'x': elem.get('x'),
        'y': elem.get('y'),
        'states': elem.get('states'),
    }
