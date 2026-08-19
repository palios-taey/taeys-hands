from __future__ import annotations

import time
from typing import Any

from consultation_v2 import atspi, clipboard, input as inp
from consultation_v2.interact import atspi_activate, atspi_click, atspi_focus
from consultation_v2.tree import node_label, prune_inactive_document
from consultation_v2.types import ElementRef, Snapshot


class SeatActions:
    def __init__(self, display: str, runtime: Any) -> None:
        self.display = str(display)
        self.runtime = runtime
        self._bind_display(None)

    def _bind_display(self, display: str | None) -> None:
        selected = str(display or self.display)
        if selected != self.display:
            raise ValueError(
                f'seat action display {selected!r} does not match {self.display!r}'
            )
        inp.set_display(self.display)
        clipboard.set_display(self.display)

    @staticmethod
    def _snapshot_elements(snapshot: Snapshot) -> list[ElementRef]:
        elements: list[ElementRef] = []
        seen: set[object] = set()
        buckets = [
            *(snapshot.mapped or {}).values(),
            snapshot.unknown or [],
            snapshot.sidebar or [],
            snapshot.menu_items or [],
        ]
        for bucket in buckets:
            for element in bucket:
                obj = element.atspi_obj
                identity: object = (
                    id(obj)
                    if obj is not None
                    else (
                        element.name,
                        element.role,
                        element.x,
                        element.y,
                    )
                )
                if identity in seen:
                    continue
                seen.add(identity)
                elements.append(element)
        return elements

    def _matching_element(
        self,
        snapshot: Snapshot,
        name: str,
        role: str | None,
        contains: bool,
        require_showing: bool,
    ) -> ElementRef | None:
        for element in self._snapshot_elements(snapshot):
            candidate = element.name or self.node_label(element.atspi_obj)
            if role and element.role != role:
                continue
            if require_showing and 'showing' not in {
                str(state).lower() for state in element.states
            }:
                continue
            if (name in candidate) if contains else (candidate == name):
                return element
        return None

    def _find_element(
        self,
        name: str,
        role: str | None,
        contains: bool,
        require_showing: bool,
    ) -> ElementRef | None:
        snapshot = self.runtime.snapshot()
        element = self._matching_element(
            snapshot,
            name,
            role,
            contains,
            require_showing,
        )
        if element is not None:
            return element
        menu_snapshot = self.runtime.menu_snapshot()
        return self._matching_element(
            menu_snapshot,
            name,
            role,
            contains,
            require_showing,
        )

    @staticmethod
    def _element_dict(element: ElementRef) -> dict[str, object]:
        return {
            'node': element.atspi_obj,
            'name': element.name,
            'role': element.role,
            'x': element.x,
            'y': element.y,
            'states': set(element.states or []),
        }

    def find(
        self,
        name: str,
        role: str | None = None,
        display: str | None = None,
        max_depth: int = 45,
        contains: bool = False,
        must_show: bool = True,
        scroll: bool = True,
    ) -> dict[str, object] | None:
        del max_depth
        self._bind_display(display)
        element = self._find_element(
            name,
            role,
            contains,
            require_showing=must_show and not scroll,
        )
        if element is None:
            return None
        if (
            scroll
            and element.y is not None
            and not 180 <= int(element.y) <= 820
        ):
            self.runtime.scroll_element_into_view(element)
            time.sleep(0.35)
            refreshed = self._find_element(
                name,
                role,
                contains,
                require_showing=False,
            )
            if refreshed is not None:
                element = refreshed
        return self._element_dict(element)

    def click(
        self,
        name: str,
        role: str | None = None,
        display: str | None = None,
        contains: bool = False,
        post_delay: float = 0.8,
    ) -> bool:
        found = self.find(name, role, display, contains=contains)
        if found is None:
            return False
        return bool(atspi_click(found, timeout=post_delay))

    def do(
        self,
        name: str,
        role: str | None = None,
        display: str | None = None,
        contains: bool = False,
        post_delay: float = 0.8,
    ) -> bool:
        found = self.find(name, role, display, contains=contains)
        if found is None or not atspi_activate(found):
            return False
        time.sleep(post_delay)
        return True

    def key(
        self,
        keyname: str,
        display: str | None = None,
        post_delay: float = 0.5,
    ) -> bool:
        self._bind_display(display)
        normalized = str(keyname or '').strip()
        if not normalized or ' ' in normalized or not inp.press_key(normalized):
            return False
        time.sleep(post_delay)
        return True

    def paste_into(
        self,
        name: str,
        text: str,
        role: str | None = None,
        display: str | None = None,
        contains: bool = False,
        clear: bool = True,
        verify: bool = False,
        post_delay: float = 0.8,
    ) -> bool:
        found = self.find(name, role, display, contains=contains)
        if found is None:
            return False
        if not atspi_focus(found):
            return False
        if clear:
            if not inp.press_key('ctrl+a'):
                return False
            time.sleep(0.15)
            if not inp.press_key('Delete'):
                return False
            time.sleep(0.2)
        if not clipboard.write(text) or not inp.press_key('ctrl+v'):
            return False
        time.sleep(post_delay)
        if not verify:
            return True
        if not inp.press_key('ctrl+a') or not inp.press_key('ctrl+c'):
            return False
        time.sleep(0.3)
        copied = (clipboard.read() or '').strip()
        expected = text.strip()
        return bool(copied) and copied[:40] == expected[:40] and copied[-30:] == expected[-30:]

    @staticmethod
    def node_label(node: Any) -> str:
        return node_label(node)

    def firefox_app(self) -> Any | None:
        self._bind_display(None)
        return atspi.find_firefox()

    @staticmethod
    def prune_inactive_document(role: str, node: Any) -> bool:
        return prune_inactive_document(role, node)
