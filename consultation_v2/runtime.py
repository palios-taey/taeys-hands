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
        self.click_strategy = str(self.cfg.get("click_strategy") or "")
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
        import re
        from core.platforms import get_platform_display
        from pathlib import Path
        env = dict(os.environ)
        plat_display = get_platform_display(self.platform)
        if plat_display:
            env['DISPLAY'] = plat_display
            # xdotool only needs DISPLAY; we don't use AT-SPI here. Still, set
            # the session bus if the file exists so subprocess env is coherent
            # with the other helpers. Missing file = log and continue (xdotool
            # doesn't need it), but never reuse the a11y bus as the session bus.
            try:
                env['DBUS_SESSION_BUS_ADDRESS'] = Path(f'/tmp/dbus_session_bus_{plat_display}').read_text().strip()
            except FileNotFoundError:
                logger.warning("close_stale_dialogs: session bus file missing for %s", plat_display)

        dialog_titles = self.cfg.get("tree", {}).get("dialog_titles", [])
        closed = 0
        for title in dialog_titles:
            # Anchor the search the same way consult.py does: start + word
            # boundary so "Open" doesn't match "OpenAI - ChatGPT". Real
            # dialog titles look like "File Upload - <app> — Mozilla Firefox".
            anchored = f'^{re.escape(title)}\\b'
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--name", anchored],
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
            except subprocess.TimeoutExpired as e:
                logger.warning("close_stale_dialogs: xdotool timeout on %r: %s", title, e)

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
        import re
        from core.platforms import get_platform_display
        from pathlib import Path
        env = dict(os.environ)
        plat_display = get_platform_display(self.platform)
        if plat_display:
            env['DISPLAY'] = plat_display
            try:
                env['DBUS_SESSION_BUS_ADDRESS'] = Path(f'/tmp/dbus_session_bus_{plat_display}').read_text().strip()
            except FileNotFoundError:
                logger.warning("focus_file_dialog: session bus file missing for %s", plat_display)

        dialog_titles = self.cfg.get("tree", {}).get("dialog_titles", [])
        for title in dialog_titles:
            anchored = f'^{re.escape(title)}\\b'
            try:
                r = subprocess.run(
                    ["xdotool", "search", "--name", anchored],
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
            except subprocess.TimeoutExpired as e:
                logger.warning("focus_file_dialog: xdotool timeout on %r: %s", title, e)
        logger.warning("focus_file_dialog: no file dialog window found")
        return False

    # ------------------------------------------------------------------
    # Display / navigation helpers
    # ------------------------------------------------------------------

    def switch(self) -> bool:
        return bool(inp.switch_to_platform(self.platform))

    def current_url(self) -> Optional[str]:
        try:
            snap = self.snapshot()
            return snap.url
        except Exception:
            return None

    def snapshot(self) -> Snapshot:
        _, _, snapshot = build_snapshot(self.platform)
        return snapshot

    def menu_snapshot(self) -> Snapshot:
        _, _, snapshot = build_menu_snapshot(self.platform)
        return snapshot

    # ------------------------------------------------------------------
    # Interaction primitives
    # ------------------------------------------------------------------

    def _subprocess_click(self, element: ElementRef) -> bool:
        """Click element via subprocess AT-SPI action (for multi-display mode)."""
        from core.platforms import get_platform_display, get_platform_bus
        from consultation_v2.yaml_contract import load_platform_yaml
        display = get_platform_display(self.platform)
        bus = get_platform_bus(self.platform)
        if not display or not bus:
            return False

        session_bus_file = f'/tmp/dbus_session_bus_{display}'
        try:
            session_bus = open(session_bus_file).read().strip()
        except FileNotFoundError:
            logger.error("Session bus file missing: %s. "
                         "Reusing the AT-SPI bus as the session bus is a "
                         "fallback — disabled. Click fails closed.",
                         session_bus_file)
            return False
        if not session_bus:
            logger.error("Session bus file empty: %s", session_bus_file)
            return False

        cfg = load_platform_yaml(self.platform)
        scan_root = cfg.get("tree", {}).get("scan_root", "document")

        env = dict(os.environ)
        env['DISPLAY'] = display
        env['AT_SPI_BUS_ADDRESS'] = bus
        env['DBUS_SESSION_BUS_ADDRESS'] = session_bus

        import sys, json
        _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [sys.executable, os.path.join(_PROJECT_ROOT, 'core', '_atspi_subprocess.py'),
             'click', self.platform, scan_root,
             element.name, element.role,
             str(element.x), str(element.y)],
            capture_output=True, text=True, timeout=10, env=env,
        )
        if result.returncode != 0:
            return False
        try:
            data = json.loads(result.stdout)
            return data.get('success', False)
        except Exception:
            return False

    def click(self, element: ElementRef, strategy: Optional[str] = None) -> bool:
        chosen = (strategy or self.click_strategy).strip()
        if chosen == "coordinate_only":
            return (
                element.x is not None
                and element.y is not None
                and bool(inp.click_at(int(element.x), int(element.y)))
            )
        if chosen == "atspi_only":
            if element.atspi_obj is not None:
                return bool(
                    atspi_click(
                        {"atspi_obj": element.atspi_obj, "name": element.name, "role": element.role}
                    )
                )
            # Subprocess mode — use AT-SPI action via subprocess
            if self._subprocess_click(element):
                return True
            # atspi_only demanded — fail closed if AT-SPI click not available
            return False
        raise RuntimeError(
            f"{self.platform}: unknown click_strategy {chosen!r}. "
            "YAML must declare 'atspi_only' or 'coordinate_only'."
        )

    def press(self, key: str) -> bool:
        return bool(inp.press_key(key))

    def paste(self, text: str) -> bool:
        return bool(inp.clipboard_paste(text))

    def read_element_text(self, name: str, role: str,
                           required_states: list | None = None) -> dict:
        """Read the AT-SPI Text interface of an element by (name, role, states).

        Returns {'text': str, 'char_count': int} on success, {'error': str}
        on failure. Used to prove pasted prompt text actually landed in the
        composer — without this, runtime.paste() returning True only proves
        the clipboard write + Ctrl+V subprocess succeeded, not that the text
        reached the intended input element.

        required_states: list of AT-SPI state names the matched element MUST
        have. Needed for inputs with name="" (Grok section, Perplexity entry)
        where the role alone is too broad. YAML element_map.states_include
        must be passed here verbatim.
        """
        from core.platforms import get_platform_display
        from pathlib import Path
        cfg = load_platform_yaml(self.platform)
        scan_root = cfg.get("tree", {}).get("scan_root", "document")

        display = get_platform_display(self.platform)
        if not display.startswith(":"):
            display = f":{display}"
        bus_path = f"/tmp/a11y_bus_{display}"
        session_bus_path = f"/tmp/dbus_session_bus_{display}"
        try:
            bus_raw = Path(bus_path).read_text().strip()
            session_bus = Path(session_bus_path).read_text().strip()
        except FileNotFoundError as e:
            return {'error': f'Bus file missing: {e}'}

        env = dict(os.environ)
        env['DISPLAY'] = display
        if bus_raw:
            env['AT_SPI_BUS_ADDRESS'] = bus_raw
        env['DBUS_SESSION_BUS_ADDRESS'] = session_bus

        import sys, json
        _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        states_arg = ','.join(required_states or [])
        r = subprocess.run(
            [sys.executable, os.path.join(_PROJECT_ROOT, 'core', '_atspi_subprocess.py'),
             'read_text', self.platform, scan_root, name, role, states_arg],
            capture_output=True, text=True, timeout=10, env=env,
        )
        if r.returncode != 0:
            return {'error': f'read_text exit {r.returncode}: {r.stderr.strip()[:200]}'}
        try:
            return json.loads(r.stdout)
        except Exception as e:
            return {'error': f'read_text invalid JSON: {e}'}

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
        # switch() already focused Firefox on the correct display.
        # Don't call focus_firefox() which uses in-process AT-SPI (wrong bus).
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
        return bool(self.wait_for_url_change(before, timeout=20.0, interval=1.0))
