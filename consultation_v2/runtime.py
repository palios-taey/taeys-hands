from __future__ import annotations

# THE RULE — enforced in every function in this file:
# 1. YAML = exact AT-SPI truth. Exact string, exact case. No .lower().
# 2. No name_contains. Period. Anywhere. EXACT MATCH ONLY.
# 3. Driver code = zero platform knowledge.
# 4. YAML drives the driver, never the reverse.
# 5. Two scan scopes: snapshot() = document, menu_snapshot() = portals.
# 6. Validation targets persistent elements only.
# 7. No fallbacks, no broadening. Fail closed on missing config.

import logging
import os
import subprocess
import time
from typing import Any, Callable, Optional

from core import atspi, clipboard, input as inp
from core.interact import atspi_click
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
            or ""
        )
        if not self.click_strategy:
            raise RuntimeError(f"{platform}: click_strategy not configured in YAML")

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
        env = dict(os.environ)
        env.setdefault("DISPLAY", os.environ.get("DISPLAY", ":0"))

        dialog_titles = self.cfg.get("tree", {}).get("dialog_titles", [])
        closed = 0
        for title in dialog_titles:
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
        env = dict(os.environ)
        env.setdefault("DISPLAY", os.environ.get("DISPLAY", ":0"))

        dialog_titles = self.cfg.get("tree", {}).get("dialog_titles", [])
        for title in dialog_titles:
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
        return bool(inp.switch_to_platform(self.platform))

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

    # ------------------------------------------------------------------
    # Interaction primitives
    # ------------------------------------------------------------------

    def click(self, element: ElementRef, strategy: Optional[str] = None) -> bool:
        chosen = (strategy or self.click_strategy).strip()
        if chosen == "coordinate_only":
            return (
                element.x is not None
                and element.y is not None
                and bool(inp.click_at(int(element.x), int(element.y)))
            )
        if chosen == "atspi_only":
            # In subprocess scan mode, atspi_obj is None — use coordinates
            if element.atspi_obj is not None:
                return bool(
                    atspi_click(
                        {"atspi_obj": element.atspi_obj, "name": element.name, "role": element.role}
                    )
                )
            return (
                element.x is not None
                and element.y is not None
                and bool(inp.click_at(int(element.x), int(element.y)))
            )
        raise RuntimeError(
            f"{self.platform}: unknown click_strategy {chosen!r}. "
            "YAML must declare 'atspi_only' or 'coordinate_only'."
        )

    def press(self, key: str) -> bool:
        return bool(inp.press_key(key))

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
        inp.focus_firefox()
        time.sleep(0.2)
        inp.press_key("Escape")
        time.sleep(0.1)
        nav_key = self.cfg.get("navigation_key")
        if not nav_key:
            raise RuntimeError(f"{self.platform}: navigation_key not configured in YAML")
        inp.press_key(nav_key)
        time.sleep(0.2)
        inp.press_key("ctrl+a")
        time.sleep(0.1)
        if not self.paste(url):
            return False
        time.sleep(0.2)
        inp.press_key("Return")
        if not verify_change:
            time.sleep(2.0)
            return True
        return bool(
            self.wait_for_url_change(before, timeout=20.0, interval=1.0)
            or self.current_url()
        )
