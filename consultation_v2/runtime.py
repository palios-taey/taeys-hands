from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Callable, Iterable, Optional

from consultation_v2 import atspi, clipboard, input as inp
from consultation_v2.interact import atspi_click
from consultation_v2.platforms_runtime import get_platform_display
from consultation_v2.tree import find_elements
from .snapshot import build_menu_snapshot, build_snapshot
from .types import ElementRef, Snapshot
from .yaml_contract import load_platform_yaml

logger = logging.getLogger(__name__)

_POPUP_ROOT_ROLES = {'alert', 'banner', 'dialog'}
_POPUP_DISMISS_NAMES = {
    'close',
    'dismiss',
    'got it',
    'maybe later',
    'no thanks',
    'not now',
    'ok',
    'okay',
    'skip',
    'x',
    '×',
}
_FILE_DIALOG_TITLES = ("File Upload", "Open", "Open File")

class ConsultationRuntime:
    def __init__(self, platform: str):
        self.platform = platform
        self.cfg = load_platform_yaml(platform)
        self.click_strategy = str(
            self.cfg.get("click_strategy")
            or self.cfg.get("workflow", {}).get("click_strategy")
            or "xdotool_first"
        )

    def _dialog_env(self) -> dict:
        env = dict(os.environ)
        env.setdefault(
            "DISPLAY",
            get_platform_display(self.platform) or os.environ.get("DISPLAY", ":0"),
        )
        return env

    # ------------------------------------------------------------------
    # Stale file dialog cleanup
    # ------------------------------------------------------------------

    def close_stale_dialogs(self) -> int:
        """Close orphaned GTK, Nautilus, and xdg-desktop-portal-gtk file
        dialogs that interfere with subsequent AT-SPI operations.

        Searches for windows whose titles match known file-dialog patterns
        (``File Upload``, ``Open``, ``Open File``) using ``xdotool`` and
        closes each one with ``xdotool windowclose``.

        Returns the count of windows closed.

        .. warning::
            Do **not** close windows named exactly ``Firefox`` — those are
            normal IPC helper windows; closing them kills the browser.
            Do **not** close the ``xdg-desktop-portal-gtk`` *process* —
            only its named dialog windows are targeted here.
        """
        env = self._dialog_env()

        closed = 0
        for title in _FILE_DIALOG_TITLES:
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--name", title],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    env=env,
                )
                for wid in (r.stdout.strip().split() if r.stdout.strip() else []):
                    subprocess.run(
                        ["xdotool", "windowclose", wid],
                        capture_output=True,
                        timeout=3,
                        env=env,
                    )
                    closed += 1
            except Exception:
                pass

        if closed:
            logger.info(f"close_stale_dialogs: closed {closed} stale file dialog(s)")
            time.sleep(1.0)

        return closed

    def focus_file_dialog(self) -> bool:
        """Focus the GTK file dialog window before sending Ctrl+L.

        Without this, Ctrl+L targets Firefox's address bar instead of
        the dialog's location bar.  Mirrors V1's _handle_gtk_dialog
        approach (tools/attach.py).
        """
        env = self._dialog_env()
        deadline = time.monotonic() + self._file_dialog_focus_timeout_seconds()

        while time.monotonic() < deadline:
            found = self._file_dialog_window(env)
            if found is not None:
                wid, title = found
                subprocess.run(
                    ["xdotool", "windowactivate", wid],
                    capture_output=True,
                    timeout=5,
                    env=env,
                )
                logger.info("focus_file_dialog: activated window %s (%s)", wid, title)
                time.sleep(0.5)
                return True
            time.sleep(0.25)
        logger.warning("focus_file_dialog: no file dialog window found")
        return False

    def _file_dialog_window(self, env: dict) -> tuple[str, str] | None:
        for title in _FILE_DIALOG_TITLES:
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--name", title],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    env=env,
                )
            except Exception:
                continue
            if r.stdout.strip():
                return r.stdout.strip().split()[0], title
        return None

    def _file_dialog_focus_timeout_seconds(self) -> float:
        settle = self.cfg.get('settle') or {}
        value = settle.get('file_dialog_focus_ms', 5000) if isinstance(settle, dict) else 5000
        try:
            seconds = float(value) / 1000.0
        except (TypeError, ValueError):
            seconds = 5.0
        return min(max(seconds, 3.0), 5.0)

    # ------------------------------------------------------------------
    # Display / navigation helpers
    # ------------------------------------------------------------------

    def switch(self) -> bool:
        if inp.switch_to_platform(self.platform):
            return True
        # Fallback: if DISPLAY is already set correctly for this platform,
        # just verify Firefox is accessible on the current display
        firefox = atspi.find_firefox_for_platform(self.platform)
        if firefox:
            return True
        return False

    def _sync_platform_io_display(self) -> None:
        display = get_platform_display(self.platform)
        if not display:
            return
        inp.set_display(display)
        clipboard.set_display(display)

    def current_url(self) -> Optional[str]:
        # Read FRESH. The AT-SPI document URL is cached and stays STALE for a few
        # seconds after a page transition (e.g. grok.com/ -> /c/<thread> after
        # send), causing false-negative URL gates. Clear the caches before
        # reading — mirrors build_snapshot()'s pre-scan cache clear (desktop ->
        # firefox -> doc). Guarded: gi may be unavailable / objects may be dead.
        try:
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi as _Atspi
            _Atspi.get_desktop(0).clear_cache_single()
        except Exception:
            pass
        firefox = atspi.find_firefox_for_platform(self.platform)
        if firefox is not None:
            try:
                firefox.clear_cache_single()
            except Exception:
                pass
        doc = atspi.get_platform_document(firefox, self.platform) if firefox else None
        if doc is not None:
            try:
                doc.clear_cache_single()
            except Exception:
                pass
        return atspi.get_document_url(doc) if doc else None

    def snapshot(self) -> Snapshot:
        _, _, snapshot = build_snapshot(self.platform)
        return snapshot

    def wait_for_stable_snapshot(
        self,
        *,
        consecutive: int = 4,
        timeout: float = 8.0,
        interval: float = 0.5,
        anchor_key: str | None = None,
        require_non_empty: bool = False,
    ) -> Snapshot:
        return self._wait_for_stable_tree(
            self.snapshot,
            consecutive=consecutive,
            timeout=timeout,
            interval=interval,
            anchor_key=anchor_key,
            require_non_empty=require_non_empty,
        )

    def wait_for_stable_menu_snapshot(
        self,
        *,
        consecutive: int = 2,
        timeout: float = 2.0,
        interval: float = 0.25,
        anchor_key: str | None = None,
        require_non_empty: bool = False,
    ) -> Snapshot:
        return self._wait_for_stable_tree(
            self.menu_snapshot,
            consecutive=consecutive,
            timeout=timeout,
            interval=interval,
            anchor_key=anchor_key,
            require_non_empty=require_non_empty,
        )

    def _wait_for_stable_tree(
        self,
        snapshot_factory: Callable[[], Snapshot],
        *,
        consecutive: int,
        timeout: float,
        interval: float,
        anchor_key: str | None = None,
        require_non_empty: bool = False,
    ) -> Snapshot:
        required = max(1, int(consecutive))
        deadline = time.time() + timeout
        last_signature: tuple[tuple[str, str, str, tuple[str, ...]], ...] | None = None
        stable = 0
        last_snapshot: Snapshot | None = None

        while time.time() < deadline:
            last_snapshot = snapshot_factory()
            raw_count = int(last_snapshot.raw_count or 0)
            # Filtered count ignores excluded scan noise such as alerts/tooltips.
            stable_count = self._stable_tree_count(last_snapshot) if require_non_empty else raw_count
            signature = self._stable_tree_signature(last_snapshot)
            anchor_ready = anchor_key is None or last_snapshot.has(anchor_key)
            non_empty_ready = not require_non_empty or (raw_count > 0 and stable_count > 0)
            ready = anchor_ready and non_empty_ready
            if signature != last_signature:
                last_signature = signature
                stable = 1 if ready else 0
            elif ready:
                stable += 1
            else:
                stable = 0
            if ready and stable >= required:
                return last_snapshot
            time.sleep(interval)
        return last_snapshot or snapshot_factory()

    @staticmethod
    def _stable_tree_count(snapshot: Snapshot) -> int:
        mapped_count = sum(len(items) for items in (snapshot.mapped or {}).values())
        return (
            mapped_count
            + len(snapshot.sidebar or [])
            + len(snapshot.menu_items or [])
            + len(snapshot.unknown or [])
        )

    @staticmethod
    def _stable_tree_signature(snapshot: Snapshot) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
        rows: list[tuple[str, str, str, tuple[str, ...]]] = []
        for key, items in sorted((snapshot.mapped or {}).items()):
            for element in items:
                rows.append((
                    f'mapped:{key}',
                    element.role or '',
                    element.name or '',
                    tuple(sorted(str(state) for state in (element.states or []))),
                ))
        for bucket_name, items in (
            ('sidebar', snapshot.sidebar or []),
            ('menu', snapshot.menu_items or []),
            ('unknown', snapshot.unknown or []),
        ):
            for element in items:
                rows.append((
                    bucket_name,
                    element.role or '',
                    element.name or '',
                    tuple(sorted(str(state) for state in (element.states or []))),
                ))
        return tuple(sorted(rows))

    def menu_snapshot(self) -> Snapshot:
        _, _, snapshot = build_menu_snapshot(self.platform)
        return snapshot

    def close_all_popups(
        self,
        *,
        drift_controls: Optional[Iterable[ElementRef]] = None,
    ) -> int:
        self.focus_firefox()
        clicked = self._click_drift_dismiss_controls(drift_controls)
        inp.press_key('Escape')
        time.sleep(0.2)
        for _ in range(3):
            candidate = self._generic_popup_dismiss_control()
            if candidate is None:
                break
            if not atspi_click(candidate):
                break
            clicked += 1
            time.sleep(0.3)
        return clicked

    def _click_drift_dismiss_controls(
        self,
        drift_controls: Optional[Iterable[ElementRef]],
    ) -> int:
        clicked = 0
        for element in drift_controls or []:
            role = (element.role or '').strip().lower()
            name = (element.name or '').strip()
            if role not in {'push button', 'button'}:
                continue
            if not self._is_generic_popup_dismiss_name(name):
                continue
            if self.click(element, strategy='atspi_first'):
                clicked += 1
                time.sleep(0.3)
        return clicked

    def _generic_popup_dismiss_control(self) -> dict | None:
        firefox = atspi.find_firefox_for_platform(self.platform)
        if firefox is None:
            return None
        try:
            elements = find_elements(firefox, fence_after=[])
        except Exception:
            return None
        for element in elements:
            role = str(element.get('role') or '').strip().lower()
            name = str(element.get('name') or '').strip()
            if role not in {'push button', 'button', 'menu item'}:
                continue
            if not self._is_generic_popup_dismiss_name(name):
                continue
            obj = element.get('atspi_obj')
            if obj is not None and self._has_popup_ancestor(obj):
                return element
        return None

    @staticmethod
    def _is_generic_popup_dismiss_name(name: str) -> bool:
        normalized = ' '.join((name or '').strip().lower().split())
        return normalized in _POPUP_DISMISS_NAMES or normalized.startswith('close ')

    @staticmethod
    def _has_popup_ancestor(obj: Any) -> bool:
        current = obj
        for _ in range(20):
            try:
                role = str(current.get_role_name() or '').strip().lower()
                if role in _POPUP_ROOT_ROLES:
                    return True
                current = current.get_parent()
            except Exception:
                return False
            if current is None:
                return False
        return False

    # ------------------------------------------------------------------
    # Interaction primitives
    # ------------------------------------------------------------------

    def click(self, element: ElementRef, strategy: Optional[str] = None) -> bool:
        chosen = (strategy or self.click_strategy or "xdotool_first").lower()
        if chosen == "coordinate_only":
            return (
                element.x is not None
                and element.y is not None
                and bool(inp.click_at(int(element.x), int(element.y)))
            )
        if chosen == "atspi_only":
            return bool(
                atspi_click(
                    {"atspi_obj": element.atspi_obj, "name": element.name, "role": element.role}
                )
            )
        if chosen == "atspi_first":
            if atspi_click(
                {"atspi_obj": element.atspi_obj, "name": element.name, "role": element.role}
            ):
                return True
            return (
                element.x is not None
                and element.y is not None
                and bool(inp.click_at(int(element.x), int(element.y)))
            )
        # Default: xdotool_first
        if (
            element.x is not None
            and element.y is not None
            and inp.click_at(int(element.x), int(element.y))
        ):
            return True
        return bool(
            atspi_click(
                {"atspi_obj": element.atspi_obj, "name": element.name, "role": element.role}
            )
        )

    def hover(self, element: ElementRef, timeout: int = 5) -> bool:
        if element.x is None or element.y is None:
            return False
        return bool(inp.hover(int(element.x), int(element.y), timeout=timeout))

    def press(self, key: str) -> bool:
        return bool(inp.press_key(key))

    def scroll_to_bottom(
        self,
        anchor: Optional[Any] = None,
        clicks: int = 15,
        max_rounds: int = 12,
        settle: float = 0.4,
    ) -> bool:
        """Scroll the conversation to the ABSOLUTE BOTTOM so the latest turn's
        Copy button + full response are rendered into the AT-SPI tree before
        extract.

        RULE (Jesse, EVERY TIME): ALWAYS scroll to bottom before extracting —
        AT-SPI only reports on-screen elements, so a long answer's Copy button
        sits below the fold and is never found otherwise. A SINGLE fixed-size
        scroll burst is NOT enough for a long response (e.g. a 22k-char audit):
        the response's Copy stays below the fold, only the PROMPT's Copy is in
        the tree, and extract grabs the prompt echo. So scroll in repeated
        bursts until the rendered content stops growing (bottom reached), capped
        at `max_rounds`. Uses the mouse wheel over the conversation column
        (hover point derived from the `anchor` element — typically the composer
        input at bottom-centre — never a magic coordinate). ctrl+End is
        deliberately NOT used: on some platforms it focuses the empty composer
        and was measured to HIDE a Copy button.
        """
        if anchor is None or anchor.x is None or anchor.y is None:
            return False
        hover = (int(anchor.x), max(0, int(anchor.y) - 200))
        last_count = -1
        stable = 0
        ok = False
        for _ in range(max_rounds):
            ok = bool(inp.scroll_wheel('down', clicks=clicks, hover_point=hover))
            time.sleep(settle)
            try:
                snap = self.snapshot()
                count = sum(len(v) for v in snap.mapped.values()) + len(snap.unknown)
            except Exception:
                count = last_count  # snapshot hiccup — treat as no-change, keep scrolling
            if count == last_count:
                stable += 1
                if stable >= 2:  # content unchanged twice in a row = bottom reached
                    break
            else:
                stable = 0
                last_count = count
        return ok

    def scroll_document_to_bottom(
        self,
        *,
        clicks: int = 12,
        rounds: int = 3,
        settle: float = 0.5,
    ) -> bool:
        """Scroll the document/conversation surface, not the composer widget."""
        hover = self._document_scroll_point()
        self.focus_firefox()
        time.sleep(0.2)
        inp.press_key('Escape')
        time.sleep(0.1)
        inp.press_key('End')
        time.sleep(settle)
        ok = True
        for _ in range(max(1, rounds)):
            ok = bool(inp.scroll_wheel('down', clicks=clicks, hover_point=hover)) and ok
            time.sleep(settle)
        return ok

    def _document_scroll_point(self) -> tuple[int, int]:
        try:
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi as _Atspi

            firefox = atspi.find_firefox_for_platform(self.platform)
            doc = atspi.get_platform_document(firefox, self.platform) if firefox else None
            comp = doc.get_component_iface() if doc is not None else None
            rect = comp.get_extents(_Atspi.CoordType.SCREEN) if comp is not None else None
            if rect and rect.width > 0 and rect.height > 0:
                return (
                    int(rect.x + rect.width // 2),
                    int(rect.y + max(80, rect.height // 2)),
                )
        except Exception:
            pass
        try:
            from consultation_v2.platforms_runtime import get_screen_size
            width, height = get_screen_size()
            return int(width // 2), int(height // 2)
        except Exception:
            return 960, 540

    def scroll_element_into_view(self, element: Optional[Any] = None) -> bool:
        """Scroll a SPECIFIC element into view via its AT-SPI Component
        (ScrollType.ANYWHERE). Required before action-clicking a copy button
        that may be off-screen — Perplexity's DR 'Copy contents' / Copy returns
        an EMPTY clipboard when clicked while not scrolled into view. Unlike
        scroll_to_bottom (which scrolls the page), this targets the button
        itself, so it is safe for report-level controls that are not bottom-
        anchored."""
        if element is None or getattr(element, 'atspi_obj', None) is None:
            return False
        try:
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi as _Atspi
            comp = element.atspi_obj.get_component_iface()
            if comp is None:
                return False
            return bool(comp.scroll_to(_Atspi.ScrollType.ANYWHERE))
        except Exception:
            return False

    def focus_firefox(self) -> bool:
        """Activate the main Firefox window so subsequent keyboard input
        (paste / Return) reaches the page. After a GTK file dialog closes
        (attach), X input focus does not reliably return to Firefox on bare
        Xvfb, so a bare ``xdotool key`` lands nowhere — call this first."""
        return bool(inp.focus_firefox())

    def paste(self, text: str) -> bool:
        self._sync_platform_io_display()
        return bool(inp.clipboard_paste(text))

    def type_text(self, text: str, delay_ms: int = 5) -> bool:
        return bool(inp.type_text(text, delay_ms=delay_ms))

    def read_clipboard(self) -> str:
        self._sync_platform_io_display()
        return clipboard.read() or ""

    def write_clipboard(self, text: str) -> bool:
        self._sync_platform_io_display()
        return clipboard.write(text)

    # ------------------------------------------------------------------
    # Wait helpers
    # ------------------------------------------------------------------

    def wait_until(
        self,
        predicate: Callable[[], Any],
        timeout: float,
        interval: float = 0.5,
    ) -> Any:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = predicate()
            if last:
                return last
            time.sleep(interval)
        return last

    def wait_for_url_change(
        self,
        previous_url: Optional[str],
        timeout: float = 30.0,
        interval: float = 1.0,
    ) -> Optional[str]:
        previous = (previous_url or "").strip()

        def changed() -> Optional[str]:
            current = (self.current_url() or "").strip()
            if current and current != previous:
                return current
            return None

        return self.wait_until(changed, timeout=timeout, interval=interval)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _focused_composer_entry(self) -> ElementRef | None:
        element_map = ((self.cfg.get('tree') or {}).get('element_map') or {})
        if not isinstance(element_map, dict):
            return None
        candidate_keys: list[str] = []
        for key, spec in element_map.items():
            if not isinstance(spec, dict):
                continue
            role = str(spec.get('role') or '').strip().lower()
            scope = str(spec.get('scope') or '').strip().lower()
            if role != 'entry':
                continue
            if scope.startswith('base.composer') or str(key).startswith('input'):
                candidate_keys.append(str(key))
        if not candidate_keys:
            return None
        snapshot = self.snapshot()
        for key in candidate_keys:
            for element in snapshot.mapped.get(key) or []:
                states = {str(state).lower() for state in (element.states or [])}
                if 'focused' in states:
                    return element
        return None

    def navigate(self, url: str, verify_change: bool = False) -> bool:
        before = self.current_url()
        # Close stale GTK file dialogs FIRST — they intercept the address-bar
        # focus key (ctrl+l) and leave the composer focused, so the URL gets
        # typed/pasted into the chat input and sent as a message. (Proven path:
        # scripts/consultation.py::_navigate_browser_to_url.)
        self.close_stale_dialogs()
        inp.focus_firefox()
        time.sleep(0.3)
        inp.press_key("Escape")
        time.sleep(0.2)
        # Use the platform-configured address bar key; fail below if it leaves
        # the composer focused instead of the browser chrome.
        nav_key = str(self.cfg.get("navigation_key") or "ctrl+l")
        inp.press_key(nav_key)
        # Critical settle: on Xvfb the address bar is not focused the instant the
        # nav_key returns; ctrl+a/paste/Return that follow MUST land in the
        # location bar, not the (cold-home-page) focused composer. Was ~0.2s.
        time.sleep(0.3)
        if self._focused_composer_entry() is not None:
            logger.error(
                'navigate: composer still focused after address-bar key; refusing to paste URL'
            )
            return False
        inp.press_key("ctrl+a")
        time.sleep(0.1)
        if not self.paste(url):
            self.type_text(url, delay_ms=5)
        time.sleep(0.3)
        inp.press_key("Return")
        if not verify_change:
            time.sleep(2.0)
            return True
        # Wait for the URL to actually change, then confirm it became the target.
        self.wait_for_url_change(before, timeout=20.0, interval=1.0)
        current = (self.current_url() or "").strip()
        target = (url or "").strip()

        def _norm(u: str) -> str:
            return u.rstrip("/").lower()

        # Defense: if the nav did not land on the target (still a stale thread,
        # unchanged, or empty), return False so the driver STOPs instead of
        # sending into a polluted composer. Single check — no retry.
        if not current:
            return False
        cur_n, tgt_n = _norm(current), _norm(target)
        if cur_n == tgt_n:
            return True
        # A bare-domain target (e.g. https://grok.com) must land EXACTLY there —
        # a /c/<thread> URL shares the domain prefix but is NOT the home target,
        # so prefix-matching is only allowed when the target carries a real path.
        has_path = "/" in tgt_n.split("://", 1)[-1]
        return has_path and any(cur_n.startswith(tgt_n + sep) for sep in ("/", "?", "#"))
