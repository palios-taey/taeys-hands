from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Callable, Optional

from core import atspi, clipboard, input as inp
from core.interact import atspi_click
from core.platforms import get_platform_display
from .snapshot import build_menu_snapshot, build_snapshot
from .types import ElementRef, Snapshot
from .yaml_contract import load_platform_yaml

logger = logging.getLogger(__name__)


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
        for title in ("File Upload", "Open", "Open File"):
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

        for title in ("File Upload", "Open", "Open File"):
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--name", title],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    env=env,
                )
                if r.stdout.strip():
                    wid = r.stdout.strip().split("\n")[0]
                    subprocess.run(
                        ["xdotool", "windowactivate", wid],
                        capture_output=True,
                        timeout=5,
                        env=env,
                    )
                    logger.info("focus_file_dialog: activated window %s (%s)", wid, title)
                    time.sleep(0.5)
                    return True
            except Exception:
                pass
        logger.warning("focus_file_dialog: no file dialog window found")
        return False

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

    def menu_snapshot(self) -> Snapshot:
        _, _, snapshot = build_menu_snapshot(self.platform)
        return snapshot

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

    def scroll_to_bottom(self, anchor: Optional[Any] = None, clicks: int = 25) -> bool:
        """Scroll the conversation to the BOTTOM so the latest turn's Copy
        button + full response are rendered into the AT-SPI tree before extract.

        RULE (Jesse): ALWAYS scroll to bottom before extracting a response —
        AT-SPI only reports on-screen elements, so a long answer's Copy button
        sits below the fold and is never found otherwise. Uses the mouse wheel
        over the conversation column (hover point derived from the `anchor`
        element — typically the composer input at bottom-centre — never a magic
        coordinate). ctrl+End is deliberately NOT used: on some platforms it
        focuses the empty composer and was measured to HIDE a Copy button.
        """
        if anchor is None or anchor.x is None or anchor.y is None:
            return False
        return bool(inp.scroll_wheel(
            'down', clicks=clicks,
            hover_point=(int(anchor.x), max(0, int(anchor.y) - 200)),
        ))

    def focus_firefox(self) -> bool:
        """Activate the main Firefox window so subsequent keyboard input
        (paste / Return) reaches the page. After a GTK file dialog closes
        (attach), X input focus does not reliably return to Firefox on bare
        Xvfb, so a bare ``xdotool key`` lands nowhere — call this first."""
        return bool(inp.focus_firefox())

    def paste(self, text: str) -> bool:
        return bool(inp.clipboard_paste(text))

    def type_text(self, text: str, delay_ms: int = 5) -> bool:
        return bool(inp.type_text(text, delay_ms=delay_ms))

    def read_clipboard(self) -> str:
        return clipboard.read() or ""

    def write_clipboard(self, text: str) -> bool:
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
        # Use platform-configured address bar key (F6 for Claude which intercepts Ctrl+L)
        nav_key = str(self.cfg.get("navigation_key") or "ctrl+l")
        inp.press_key(nav_key)
        # Critical settle: on Xvfb the address bar is not focused the instant the
        # nav_key returns; ctrl+a/paste/Return that follow MUST land in the
        # location bar, not the (cold-home-page) focused composer. Was ~0.2s.
        time.sleep(0.3)
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
