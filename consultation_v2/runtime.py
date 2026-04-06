from __future__ import annotations

import time
from typing import Any, Callable, Optional

from core import atspi, clipboard, input as inp
from core.interact import atspi_click

from .snapshot import build_menu_snapshot, build_snapshot
from .types import ElementRef, Snapshot
from .yaml_contract import load_platform_yaml


class ConsultationRuntime:
    def __init__(self, platform: str):
        self.platform = platform
        self.cfg = load_platform_yaml(platform)
        self.click_strategy = str(self.cfg.get('click_strategy') or self.cfg.get('workflow', {}).get('click_strategy') or 'xdotool_first')

    def switch(self) -> bool:
        # Try standard switch (works when PLATFORM_DISPLAYS env is set)
        if inp.switch_to_platform(self.platform):
            return True
        # Fallback: if DISPLAY is already set correctly for this platform,
        # just verify Firefox is accessible on current display
        firefox = atspi.find_firefox_for_platform(self.platform)
        if firefox:
            return True
        return False

    def current_url(self) -> Optional[str]:
        firefox = atspi.find_firefox_for_platform(self.platform)
        doc = atspi.get_platform_document(firefox, self.platform) if firefox else None
        return atspi.get_document_url(doc) if doc else None

    def snapshot(self) -> Snapshot:
        _, _, snapshot = build_snapshot(self.platform)
        return snapshot

    def menu_snapshot(self) -> Snapshot:
        _, _, snapshot = build_menu_snapshot(self.platform)
        return snapshot

    def click(self, element: ElementRef, strategy: Optional[str] = None) -> bool:
        chosen = (strategy or self.click_strategy or 'xdotool_first').lower()
        if chosen == 'coordinate_only':
            return element.x is not None and element.y is not None and bool(inp.click_at(int(element.x), int(element.y)))
        if chosen == 'atspi_only':
            return bool(atspi_click({'atspi_obj': element.atspi_obj, 'name': element.name, 'role': element.role}))
        if chosen == 'atspi_first':
            if atspi_click({'atspi_obj': element.atspi_obj, 'name': element.name, 'role': element.role}):
                return True
            return element.x is not None and element.y is not None and bool(inp.click_at(int(element.x), int(element.y)))
        if element.x is not None and element.y is not None and inp.click_at(int(element.x), int(element.y)):
            return True
        return bool(atspi_click({'atspi_obj': element.atspi_obj, 'name': element.name, 'role': element.role}))

    def press(self, key: str) -> bool:
        return bool(inp.press_key(key))

    def paste(self, text: str) -> bool:
        return bool(inp.clipboard_paste(text))

    def type_text(self, text: str, delay_ms: int = 5) -> bool:
        return bool(inp.type_text(text, delay_ms=delay_ms))

    def read_clipboard(self) -> str:
        return clipboard.read() or ''

    def wait_until(self, predicate: Callable[[], Any], timeout: float, interval: float = 0.5) -> Any:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = predicate()
            if last:
                return last
            time.sleep(interval)
        return last

    def wait_for_url_change(self, previous_url: Optional[str], timeout: float = 30.0, interval: float = 1.0) -> Optional[str]:
        previous = (previous_url or '').strip()
        def _changed() -> Optional[str]:
            current = (self.current_url() or '').strip()
            if current and current != previous:
                return current
            return None
        return self.wait_until(_changed, timeout=timeout, interval=interval)

    def navigate(self, url: str, verify_change: bool = False) -> bool:
        before = self.current_url()
        inp.focus_firefox()
        time.sleep(0.2)
        inp.press_key('Escape')
        time.sleep(0.1)
        inp.press_key('ctrl+l')
        time.sleep(0.2)
        inp.press_key('ctrl+a')
        time.sleep(0.1)
        if not self.paste(url):
            self.type_text(url, delay_ms=5)
        time.sleep(0.2)
        inp.press_key('Return')
        if not verify_change:
            time.sleep(2.0)
            return True
        return bool(self.wait_for_url_change(before, timeout=20.0, interval=1.0) or self.current_url())
