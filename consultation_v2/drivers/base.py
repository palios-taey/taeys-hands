# THE RULE — enforced in every function in this file:
# 1. YAML = exact AT-SPI truth. Exact string, exact case. No .lower().
# 2. No name_contains. Period. Anywhere. EXACT MATCH ONLY.
# 3. Driver code = zero platform knowledge. No hardcoded element names or default keys.
# 4. YAML drives the driver, never the reverse.
# 5. Two scan scopes: snapshot() = document, menu_snapshot() = portals.
# 6. Validation targets persistent elements only.
# 7. No fallbacks, no broadening. Fail closed on missing config.

from __future__ import annotations

import json
import os
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from consultation_v2.identity import consolidate_attachments
from consultation_v2.runtime import ConsultationRuntime
from consultation_v2.snapshot import matches_spec
from consultation_v2.types import (
    ConsultationRequest,
    ConsultationResult,
    ElementRef,
    ExtractedArtifact,
    Snapshot,
)
from consultation_v2.yaml_contract import load_platform_yaml

try:
    from storage import neo4j_client
except Exception:  # pragma: no cover - optional dependency in runtime
    neo4j_client = None


class BaseConsultationDriver(ABC):
    platform: str

    def __init__(self) -> None:
        self.cfg = load_platform_yaml(self.platform)
        self.runtime = ConsultationRuntime(self.platform)

    def result(self, request: ConsultationRequest) -> ConsultationResult:
        return ConsultationResult(platform=self.platform, request=request)

    def find_first(self, snapshot: Snapshot, key: str) -> Optional[ElementRef]:
        return snapshot.first(key)

    def find_last(self, snapshot: Snapshot, key: str) -> Optional[ElementRef]:
        return snapshot.last(key)

    def validation_passes(
        self,
        snapshot: Snapshot,
        validation_key: str,
    ) -> bool:
        validation = dict(self.cfg.get("validation", {}).get(validation_key, {}))
        if not validation:
            return False


        indicators = validation.get("indicators") or []
        if indicators:
            all_elements: List[ElementRef] = []
            for items in snapshot.mapped.values():
                all_elements.extend(items)
            all_elements.extend(snapshot.unknown)
            all_elements.extend(snapshot.sidebar)

            found = False
            for indicator in indicators:
                if any(matches_spec(element, indicator) for element in all_elements):
                    found = True
                    break
            if not found:
                return False

        if validation.get("stop_absent"):
            stop_key = self.cfg.get("workflow", {}).get("monitor", {}).get("stop_key")
            if stop_key and snapshot.has(stop_key):
                return False
        return True

    def serialize_artifacts(self, artifacts: Iterable[ExtractedArtifact]) -> List[str]:
        return [json.dumps(artifact.serializable(), sort_keys=True) for artifact in artifacts]

    @abstractmethod
    def run(self, request: ConsultationRequest) -> ConsultationResult:
        raise NotImplementedError


class YamlDrivenConsultationDriver(BaseConsultationDriver):
    """
    Generic consultation driver whose behavior is controlled by the platform YAML.

    The driver intentionally contains no platform-specific element names.
    Every lookup goes through tree.element_map and workflow mappings.
    """

    # ------------------------------------------------------------------
    # Identity file consolidation
    # ------------------------------------------------------------------

    def prepared_attachment_paths(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> Optional[List[str]]:
        """Consolidate user attachments with FAMILY_KERNEL + platform identity.

        Returns [] if no attachments, [consolidated_path] on success, None on failure.
        """
        if not request.attachments:
            return []
        try:
            consolidated = consolidate_attachments(self.platform, list(request.attachments))
        except Exception as exc:
            result.add_step('attach', False, f'{self.platform} identity consolidation failed: {exc}')
            return None
        if not consolidated:
            result.add_step('attach', False, f'{self.platform} identity consolidation returned no file')
            return None
        return [os.path.abspath(consolidated)]

    # ------------------------------------------------------------------
    # Top-level flow
    # ------------------------------------------------------------------

    def run(self, request: ConsultationRequest) -> ConsultationResult:
        result = self.result(request)
        urls = self.cfg.get("urls", {})
        target_url = request.session_url or urls.get("fresh")

        if not self.runtime.switch():
            result.add_step("navigate", False, f"Could not switch to {self.platform} tab")
            return result

        result.session_url_before = self.runtime.current_url()

        if target_url:
            navigated = self.runtime.navigate(
                target_url,
                verify_change=bool(urls.get("verify_navigation")),
            )
            self._sleep(urls.get("settle_delay", 3))
            snap = self.runtime.snapshot()
            result.add_step(
                "navigate",
                navigated,
                f"Navigated to {self.platform} session target",
                target_url=target_url,
                snapshot=snap.serializable(),
            )
            if not navigated:
                return result

        if not self.select_model_mode_tools(request, result):
            return result
        self._sleep(1)
        if request.connectors:
            if not self.toggle_connectors(request, result):
                return result
            self._sleep(1)
        if not self.attach_files(request, result):
            return result
        self._sleep(1)
        if not self.enter_prompt(request, result):
            return result
        self._sleep(1)
        if not self.send_prompt(request, result):
            return result
        self._sleep(2)
        if not self.monitor_generation(request, result):
            return result
        self._sleep(1)
        if not self.extract_primary(request, result):
            return result
        self._sleep(1)
        if not self.extract_additional(request, result):
            return result
        if not self.store_in_neo4j(request, result):
            return result

        result.ok = True
        return result

    # ------------------------------------------------------------------
    # Small YAML / state helpers
    # ------------------------------------------------------------------

    def _workflow(self) -> Dict[str, Any]:
        return dict(self.cfg.get("workflow") or {})

    def _defaults(self) -> Dict[str, Any]:
        return dict(self._workflow().get("defaults") or {})

    def _selection_cfg(self) -> Dict[str, Any]:
        return dict(self._workflow().get("selection") or {})

    def _connectors_cfg(self) -> Dict[str, Any]:
        return dict(self._workflow().get("connectors") or {})

    def _element_map(self) -> Dict[str, Any]:
        tree = dict(self.cfg.get("tree") or {})
        return dict(tree.get("element_map") or {})

    def _element_spec(self, key: str | None) -> Dict[str, Any]:
        if not key:
            return {}
        spec = self._element_map().get(key)
        return dict(spec or {})

    def _validation_cfg(self, key: str | None) -> Dict[str, Any]:
        if not key:
            return {}
        validation = dict(self.cfg.get("validation") or {})
        return dict(validation.get(key) or {})

    def _has_element_spec(self, key: str | None) -> bool:
        if not key:
            return False
        return bool(self._element_spec(key))

    def _normalize(self, value: str | None) -> str:
        """Return value as-is. Callers must use exact YAML key names. No normalization."""
        return value or ""

    def _snapshot(self, kind: str = "document") -> Snapshot:
        return self.runtime.menu_snapshot() if kind == "menu" else self.runtime.snapshot()

    def _sleep(self, seconds: float | int | None) -> None:
        if seconds:
            time.sleep(float(seconds))

    def _hover(self, element: ElementRef) -> bool:
        if element.x is None or element.y is None:
            return False
        env = dict(os.environ)
        env.setdefault("DISPLAY", os.environ.get("DISPLAY", ":0"))
        try:
            subprocess.run(
                ["xdotool", "mousemove", "--sync", str(int(element.x) + 4), str(int(element.y) + 4)],
                capture_output=True,
                timeout=5,
                env=env,
                check=False,
            )
            return True
        except Exception:
            return False

    def _act(
        self,
        element: ElementRef,
        action: str = "click",
        strategy: str | None = None,
    ) -> bool:
        if not action:
            raise RuntimeError(f"{self.platform}: action not specified for element {element.name!r}")
        if action == "hover":
            return self._hover(element)
        if action == "press":
            return self.runtime.press(element.name)
        if action == "click":
            return self.runtime.click(element, strategy=strategy)
        raise RuntimeError(f"{self.platform}: unknown action {action!r}. Must be click, hover, or press.")

    def _find_key_or_fail(
        self,
        snapshot: Snapshot,
        key: str,
        result: ConsultationResult,
        step_name: str,
        message: str,
    ) -> Optional[ElementRef]:
        element = self.find_first(snapshot, key)
        if element:
            return element
        result.add_step(step_name, False, message, snapshot=snapshot.serializable())
        return None

    def _validation_state(
        self,
        snapshot: Snapshot,
        validation_key: str | None,
    ) -> Tuple[bool, str]:
        if not validation_key:
            return False, "missing_config"
        cfg = self._validation_cfg(validation_key)
        if not cfg:
            return False, "missing_config"
        if cfg.get("pending"):
            return False, "not_implemented"
        if cfg.get("diff_validated") or cfg.get("pass_through"):
            # Validation handled by driver logic (snapshot diff or downstream gate).
            return True, "validated"
        if cfg.get("verified_by_checked_state"):
            # This validation is handled by checked-state verification during sequence execution.
            # It cannot be validated post-close because no persistent indicator exists.
            # The sequence step must have verified_by_checked_state: true to pass.
            return False, "requires_checked_state"
        passed = self.validation_passes(snapshot, validation_key)
        if passed:
            return True, "validated"
        return False, "failed"

    def _current_step_message(
        self,
        label: str,
        validation_status: str,
        *,
        already_checked: bool = False,
    ) -> str:
        if already_checked:
            if validation_status == "validated":
                return f"{label} already active"
            if validation_status == "not_implemented":
                return f"{label} FAILED: validation not yet implemented"
            return f"{label} already checked in menu"
        if validation_status == "validated":
            return f"{label} applied and validated"
        if validation_status == "not_implemented":
            return f"{label} FAILED: validation not yet implemented"
        return f"{label} applied"

    # ------------------------------------------------------------------
    # Generic sequence execution
    # ------------------------------------------------------------------

    def _execute_sequence(
        self,
        step_name: str,
        label: str,
        sequence: Sequence[Dict[str, Any]],
        result: ConsultationResult,
    ) -> bool:
        for index, raw_step in enumerate(sequence, start=1):
            step = dict(raw_step or {})
            trigger_key = step.get("trigger")
            trigger_snapshot_kind = step.get("trigger_snapshot", "document")
            trigger_action = step.get("trigger_action", "click")
            trigger_click_strategy = step.get("trigger_click_strategy")

            if trigger_key:
                trigger_snap = self._snapshot(trigger_snapshot_kind)
                trigger_el = self._find_key_or_fail(
                    trigger_snap,
                    trigger_key,
                    result,
                    f"{step_name}:{index}",
                    f"{self.platform} trigger {trigger_key!r} not found for {label}",
                )
                if not trigger_el:
                    return False
                if not self._act(trigger_el, action=trigger_action, strategy=trigger_click_strategy):
                    result.add_step(
                        f"{step_name}:{index}",
                        False,
                        f"{self.platform} trigger {trigger_key!r} interaction failed for {label}",
                        snapshot=trigger_snap.serializable(),
                    )
                    return False
                self._sleep(step.get("pause_after_trigger", 1.5))

            target_key = step.get("target")
            if not target_key:
                result.add_step(
                    f"{step_name}:{index}",
                    True,
                    f"{self.platform} sequence step completed for {label}",
                )
                continue

            target_snapshot_kind = step.get("snapshot", "document")
            target_snap = self._snapshot(target_snapshot_kind)
            target_el = self._find_key_or_fail(
                target_snap,
                target_key,
                result,
                f"{step_name}:{index}",
                f"{self.platform} target {target_key!r} not found for {label}",
            )
            if not target_el:
                return False

            checked = "checked" in {state for state in target_el.states}
            if step.get("skip_if_checked") and checked:
                if step.get("close_with_escape"):
                    self.runtime.press("Escape")
                    self._sleep(step.get("pause_after_close", 0.4))
                if step.get("verified_by_checked_state"):
                    result.add_step(
                        f"{step_name}:{index}",
                        True,
                        self._current_step_message(label, "validated", already_checked=True),
                        target=target_key,
                    )
                    continue
                verify_snapshot_kind = step.get("verify_snapshot", "document")
                verify_snap = self._snapshot(verify_snapshot_kind)
                ok, validation_status = self._validation_state(
                    verify_snap,
                    step.get("validation"),
                )
                result.add_step(
                    f"{step_name}:{index}",
                    ok,
                    self._current_step_message(label, validation_status, already_checked=True),
                    target=target_key,
                    snapshot=verify_snap.serializable(),
                )
                if not ok:
                    return False
                continue

            action = step.get("action", "click")
            click_strategy = step.get("click_strategy")
            acted = self._act(target_el, action=action, strategy=click_strategy)
            if not acted:
                result.add_step(
                    f"{step_name}:{index}",
                    False,
                    f"{self.platform} target {target_key!r} interaction failed for {label}",
                    snapshot=target_snap.serializable(),
                )
                return False

            self._sleep(step.get("pause_after_action", 1.5))

            # If this step uses checked-state verification, confirm checked now
            # (before dropdown closes and state is lost)
            if step.get("verified_by_checked_state"):
                recheck_snap = self._snapshot(target_snapshot_kind)
                recheck_el = self.find_first(recheck_snap, target_key)
                if not recheck_el or "checked" not in {s for s in recheck_el.states}:
                    result.add_step(
                        f"{step_name}:{index}",
                        False,
                        f"{self.platform} target {target_key!r} not in checked state after click for {label}",
                        snapshot=recheck_snap.serializable(),
                    )
                    return False

            if step.get("close_with_escape"):
                self.runtime.press("Escape")
                self._sleep(step.get("pause_after_close", 1.0))

            # If verified by checked state, we already confirmed above
            if step.get("verified_by_checked_state"):
                result.add_step(
                    f"{step_name}:{index}",
                    True,
                    self._current_step_message(label, "validated"),
                    target=target_key,
                )
                continue

            verify_snapshot_kind = step.get("verify_snapshot", "document")
            verify_snap = self._snapshot(verify_snapshot_kind)
            ok, validation_status = self._validation_state(
                verify_snap,
                step.get("validation"),
            )
            result.add_step(
                f"{step_name}:{index}",
                ok,
                self._current_step_message(label, validation_status),
                target=target_key,
                snapshot=verify_snap.serializable(),
            )
            if not ok:
                return False

        return True

    # ------------------------------------------------------------------
    # Model / mode / tool selection
    # ------------------------------------------------------------------

    def _apply_simple_target(
        self,
        group: str,
        normalized_target: str,
        result: ConsultationResult,
    ) -> bool:
        selection = self._selection_cfg()
        targets = dict(selection.get(f"{group}_targets") or {})
        if normalized_target not in targets:
            result.add_step(
                f"select_{group}",
                False,
                f"{self.platform} {group} target {normalized_target!r} is not mapped in YAML",
            )
            return False

        validations = dict(selection.get(f"{group}_validations") or {})
        validation_key = validations.get(normalized_target) or f"{normalized_target}_active"
        validation_cfg = self._validation_cfg(validation_key)
        if validation_cfg and not validation_cfg.get("pending") and not validation_cfg.get("verified_by_checked_state"):
            current_snap = self.runtime.snapshot()
            if self.validation_passes(current_snap, validation_key):
                result.add_step(
                    f"select_{group}",
                    True,
                    f"{self.platform} {group} {normalized_target} already active",
                    snapshot=current_snap.serializable(),
                )
                return True

        sequence = [
            {
                "trigger": selection.get(f"{group}_trigger"),
                "snapshot": selection.get(f"{group}_snapshot", "menu"),
                "target": targets[normalized_target],
                "action": selection.get(f"{group}_action", "click"),
                "click_strategy": selection.get(f"{group}_click_strategy"),
                "skip_if_checked": bool(selection.get(f"{group}_skip_if_checked")),
                "close_with_escape": bool(selection.get(f"{group}_close_with_escape")),
                "validation": validation_key,
                "verified_by_checked_state": bool(selection.get(f"{group}_verified_by_checked_state")),
            }
        ]
        return self._execute_sequence(f"select_{group}", normalized_target, sequence, result)

    def _apply_named_target(
        self,
        group: str,
        target_name: str | None,
        result: ConsultationResult,
    ) -> bool:
        normalized_target = self._normalize(target_name)
        if not normalized_target:
            result.add_step(
                f"select_{group}",
                True,
                f"No {group} selection requested for {self.platform}",
            )
            return True

        selection = self._selection_cfg()
        sequences = dict(selection.get("sequences") or {})
        if normalized_target in sequences:
            return self._execute_sequence(
                f"select_{group}",
                normalized_target,
                list(sequences[normalized_target] or []),
                result,
            )
        return self._apply_simple_target(group, normalized_target, result)

    def select_model_mode_tools(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        defaults = self._defaults()

        requested_model = request.model if request.model is not None else defaults.get("model")
        requested_mode = request.mode if request.mode is not None else defaults.get("mode")

        requested_tools = list(request.tools)
        if not requested_tools:
            requested_tools = list(defaults.get("tools") or [])

        if not self._apply_named_target("model", requested_model, result):
            return False
        if not self._apply_named_target("mode", requested_mode, result):
            return False

        if not requested_tools:
            result.add_step("select_tool", True, f"No tools requested for {self.platform}")
            return True

        for tool_name in requested_tools:
            if not self._apply_named_target("tool", tool_name, result):
                return False
        return True

    # ------------------------------------------------------------------
    # Connectors
    # ------------------------------------------------------------------

    def _clear_search_box(self, search_box: ElementRef) -> None:
        self.runtime.click(search_box)
        self._sleep(0.2)
        self.runtime.press("ctrl+a")
        self._sleep(0.1)
        self.runtime.press("Delete")
        self._sleep(0.2)

    def toggle_connectors(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        if not request.connectors:
            result.add_step("toggle_connectors", True, f"No connectors requested for {self.platform}")
            return True

        cfg = self._connectors_cfg()
        if not cfg:
            result.add_step(
                "toggle_connectors",
                False,
                f"{self.platform} has no workflow.connectors block in YAML",
            )
            return False

        targets = dict(cfg.get("source_targets") or {})
        normalized_requested = [self._normalize(name) for name in request.connectors]

        if cfg.get("search_input"):
            open_sequence = list(cfg.get("open_sequence") or [])
            if not open_sequence:
                result.add_step(
                    "toggle_connectors",
                    False,
                    f"{self.platform} connectors.search_input requires connectors.open_sequence",
                )
                return False
            if not self._execute_sequence("toggle_connectors", "open_connectors_panel", open_sequence, result):
                return False

            for raw_name, normalized_name in zip(request.connectors, normalized_requested):
                target_key = targets.get(normalized_name)
                if not target_key:
                    result.add_step(
                        "toggle_connectors",
                        False,
                        f"{self.platform} connector {raw_name!r} is not mapped in YAML",
                    )
                    return False

                panel_snap = self.runtime.menu_snapshot()
                search_box = self.find_first(panel_snap, cfg["search_input"])
                if not search_box:
                    result.add_step(
                        "toggle_connectors",
                        False,
                        f"{self.platform} connector panel search input not found",
                        snapshot=panel_snap.serializable(),
                    )
                    return False

                self._clear_search_box(search_box)
                # Get search term from YAML element spec name, not caller's raw string
                target_spec = self._element_spec(target_key)
                search_term = target_spec.get("name", "") if target_spec else ""
                if not search_term:
                    result.add_step("toggle_connectors", False, f"{self.platform} no name in element spec for {target_key!r}")
                    return False
                self.runtime.type_text(search_term, delay_ms=int(cfg.get("search_delay_ms", 40)))
                self._sleep(cfg.get("pause_after_search", 1.0))

                filtered_snap = self.runtime.menu_snapshot()
                item = self.find_first(filtered_snap, target_key)
                if not item:
                    result.add_step(
                        "toggle_connectors",
                        False,
                        f"{self.platform} connector target {target_key!r} not found after searching for {raw_name!r}",
                        snapshot=filtered_snap.serializable(),
                    )
                    return False

                checked = "checked" in {state for state in item.states}
                if not checked:
                    if not self.runtime.click(item, strategy=cfg.get("item_click_strategy")):
                        result.add_step(
                            "toggle_connectors",
                            False,
                            f"{self.platform} connector click failed for {raw_name!r}",
                            snapshot=filtered_snap.serializable(),
                        )
                        return False
                    self._sleep(cfg.get("pause_after_click", 0.5))

                verify_snap = self.runtime.menu_snapshot()
                verify_item = self.find_first(verify_snap, target_key)
                verify_ok = True
                if cfg.get("verify_checked", True):
                    verify_ok = bool(
                        verify_item
                        and "checked" in {state for state in verify_item.states}
                    )

                result.add_step(
                    "toggle_connectors",
                    verify_ok,
                    f"{self.platform} connector {raw_name!r} {'enabled' if verify_ok else 'NOT enabled'}",
                    snapshot=verify_snap.serializable(),
                )
                if not verify_ok:
                    return False

                search_box2 = self.find_first(verify_snap, cfg["search_input"])
                if search_box2:
                    self._clear_search_box(search_box2)

            if cfg.get("close_with_escape", True):
                self.runtime.press("Escape")
                self._sleep(0.4)
            return True

        trigger_key = cfg.get("trigger")
        if not trigger_key or not self._has_element_spec(trigger_key):
            result.add_step(
                "toggle_connectors",
                False,
                f"{self.platform} connectors.trigger is missing or not scan-backed",
            )
            return False

        snapshot_kind = cfg.get("snapshot", "menu")
        for raw_name, normalized_name in zip(request.connectors, normalized_requested):
            target_key = targets.get(normalized_name)
            if not target_key:
                result.add_step(
                    "toggle_connectors",
                    False,
                    f"{self.platform} connector {raw_name!r} is not mapped in YAML",
                )
                return False

            trigger_snap = self.runtime.snapshot()
            trigger = self.find_first(trigger_snap, trigger_key)
            if not trigger or not self.runtime.click(trigger, strategy=cfg.get("trigger_click_strategy")):
                result.add_step(
                    "toggle_connectors",
                    False,
                    f"{self.platform} connector trigger failed for {raw_name!r}",
                    snapshot=trigger_snap.serializable(),
                )
                return False
            self._sleep(cfg.get("pause_after_trigger", 0.7))

            menu_snap = self._snapshot(snapshot_kind)
            target = self.find_first(menu_snap, target_key)
            if not target:
                result.add_step(
                    "toggle_connectors",
                    False,
                    f"{self.platform} connector item {target_key!r} not found for {raw_name!r}",
                    snapshot=menu_snap.serializable(),
                )
                return False

            checked = "checked" in {state for state in target.states}
            if checked and cfg.get("skip_if_checked"):
                success = True
            else:
                success = bool(self.runtime.click(target, strategy=cfg.get("item_click_strategy")))

            result.add_step(
                "toggle_connectors",
                success,
                f"{self.platform} connector {raw_name!r} {'already active' if checked else 'clicked'}",
                snapshot=menu_snap.serializable(),
            )
            if not success:
                return False

        return True

    # ------------------------------------------------------------------
    # Attach files
    # ------------------------------------------------------------------

    def attach_files(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        attachment_paths = self.prepared_attachment_paths(request, result)
        if attachment_paths is None:
            return False
        if not attachment_paths:
            result.add_step("attach", True, f"No attachments requested for {self.platform}")
            return True

        self.runtime.close_stale_dialogs()
        attachment = dict(self._workflow().get("attachment") or {})
        if not attachment:
            result.add_step(
                "attach",
                False,
                f"{self.platform} workflow.attachment is missing from YAML",
            )
            return False

        keyboard_shortcut = attachment.get("keyboard_shortcut")
        prefer_keyboard_shortcut = bool(attachment.get("prefer_keyboard_shortcut"))
        validation_key = attachment.get("validation")

        for file_path in attachment_paths:
            abs_path = os.path.abspath(file_path)

            # Snapshot BEFORE attach — used for diff validation
            pre_attach_snap = self.runtime.snapshot()
            pre_attach_buttons = {
                el.name for items in pre_attach_snap.mapped.values() for el in items
                if el.role == "push button"
            }
            for el in pre_attach_snap.unknown:
                if el.role == "push button":
                    pre_attach_buttons.add(el.name)

            if prefer_keyboard_shortcut and keyboard_shortcut:
                opened = self.runtime.press(str(keyboard_shortcut))
                self._sleep(2)
            else:
                trigger_key = attachment.get("trigger")
                menu_target = attachment.get("menu_target")
                if not trigger_key or not menu_target:
                    result.add_step(
                        "attach",
                        False,
                        f"{self.platform} attachment trigger/menu_target missing for {abs_path}",
                    )
                    return False

                trigger_snap = self.runtime.snapshot()
                trigger = self.find_first(trigger_snap, trigger_key)
                if not trigger or not self.runtime.click(trigger, strategy=attachment.get("trigger_click_strategy")):
                    result.add_step(
                        "attach",
                        False,
                        f"{self.platform} attach trigger failed for {abs_path}",
                        snapshot=trigger_snap.serializable(),
                    )
                    return False
                self._sleep(attachment.get("pause_after_trigger", 1.5))

                menu_snap = self._snapshot(attachment.get("snapshot", "menu"))
                upload_item = self.find_first(menu_snap, menu_target)
                if not upload_item or not self.runtime.click(upload_item, strategy=attachment.get("item_click_strategy")):
                    result.add_step(
                        "attach",
                        False,
                        f"{self.platform} upload item failed for {abs_path}",
                        snapshot=menu_snap.serializable(),
                    )
                    return False
                opened = True

            if not opened:
                result.add_step("attach", False, f"{self.platform} failed to open file dialog for {abs_path}")
                return False

            self._sleep(attachment.get("pause_before_dialog_focus", 2.0))
            if not self.runtime.focus_file_dialog():
                result.add_step("attach", False, f"{self.platform} file dialog did not appear for {abs_path}")
                return False

            dialog_shortcut = attachment.get("dialog_location_shortcut")
            if not dialog_shortcut:
                result.add_step("attach", False, f"{self.platform} workflow.attachment.dialog_location_shortcut not configured")
                return False
            self.runtime.press(str(dialog_shortcut))
            self._sleep(0.5)
            pasted = self.runtime.paste(abs_path)
            if not pasted:
                result.add_step("attach", False, f"{self.platform} failed to paste attachment path for {abs_path}")
                return False
            self._sleep(0.5)
            self.runtime.press("Return")
            self._sleep(attachment.get("pause_after_dialog_submit", 2.0))

            verify_snap = self.runtime.snapshot()

            # Diff-based attach validation: a new push button (file chip) must appear
            post_attach_buttons = {
                el.name for items in verify_snap.mapped.values() for el in items
                if el.role == "push button"
            }
            for el in verify_snap.unknown:
                if el.role == "push button":
                    post_attach_buttons.add(el.name)

            new_buttons = post_attach_buttons - pre_attach_buttons
            # Filter out empty names and browser chrome
            new_buttons = {n for n in new_buttons if n and not n.startswith("Open context")}

            if new_buttons:
                result.add_step(
                    "attach",
                    True,
                    f"attached {os.path.basename(abs_path)}; file chip: {next(iter(new_buttons))!r}",
                    file=abs_path,
                    new_elements=list(new_buttons),
                    snapshot=verify_snap.serializable(),
                )
            else:
                result.add_step(
                    "attach",
                    False,
                    f"{self.platform} no file chip appeared after attaching {os.path.basename(abs_path)}",
                    file=abs_path,
                    snapshot=verify_snap.serializable(),
                )
                return False

        return True

    # ------------------------------------------------------------------
    # Prompt entry
    # ------------------------------------------------------------------

    def enter_prompt(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        prompt_cfg = dict(self._workflow().get("prompt") or {})
        input_key = prompt_cfg.get("input")
        if not input_key:
            result.add_step("prompt", False, f"{self.platform} workflow.prompt.input not configured in YAML")
            return False
        snap = self.runtime.snapshot()
        input_el = self.find_first(snap, input_key)
        if not input_el:
            result.add_step(
                "prompt",
                False,
                f"{self.platform} input field {input_key!r} not found",
                snapshot=snap.serializable(),
            )
            return False

        if not self.runtime.click(input_el, strategy=prompt_cfg.get("click_strategy")):
            result.add_step(
                "prompt",
                False,
                f"{self.platform} input focus click failed",
                snapshot=snap.serializable(),
            )
            return False

        self._sleep(prompt_cfg.get("pause_before_paste", 0.5))
        if not self.runtime.paste(request.message):
            result.add_step("prompt", False, f"{self.platform} clipboard paste failed")
            return False

        self._sleep(prompt_cfg.get("pause_after_paste", 1.0))
        verify_snap = self.runtime.snapshot()
        ok, validation_status = self._validation_state(
            verify_snap,
            prompt_cfg.get("validation"),
        )
        result.add_step(
            "prompt",
            ok,
            self._current_step_message("prompt entered", validation_status),
            snapshot=verify_snap.serializable(),
        )
        return ok

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_prompt(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        send_cfg = dict(self._workflow().get("send") or {})
        trigger_key = send_cfg.get("trigger")
        submit_via_return = bool(send_cfg.get("submit_via_return"))
        submit_key = send_cfg.get("keypress")
        before = result.session_url_before or self.runtime.current_url() or ""

        sent = False
        send_method = None

        if trigger_key and self._has_element_spec(trigger_key):
            snap = self.runtime.snapshot()
            trigger = self.find_first(snap, trigger_key)
            if trigger and self.runtime.click(trigger, strategy=send_cfg.get("click_strategy")):
                sent = True
                send_method = trigger_key
            else:
                result.add_step(
                    "send",
                    False,
                    f"{self.platform} send trigger {trigger_key!r} not found or not clickable",
                    snapshot=snap.serializable(),
                )
                return False
        elif submit_via_return:
            sent = bool(self.runtime.press(submit_key))
            send_method = f"keypress:{submit_key}"
        else:
            result.add_step(
                "send",
                False,
                f"{self.platform} no send path configured",
            )
            return False

        confirmation_key = send_cfg.get("confirmation_key")
        has_confirmation = bool(confirmation_key and self._has_element_spec(confirmation_key))
        require_new_url = bool(send_cfg.get("require_new_url")) and not bool(request.session_url)

        confirmed = False
        confirmation_timeout = float(send_cfg.get("confirmation_timeout") or 30)

        if has_confirmation:
            def _confirm() -> bool:
                snap = self.runtime.snapshot()
                if snap.has(str(confirmation_key)):
                    return True
                if require_new_url:
                    current = self.runtime.current_url() or ""
                    if current and current != before:
                        return True
                return False

            confirmed = bool(self.runtime.wait_until(_confirm, timeout=confirmation_timeout, interval=0.7))
        elif require_new_url:
            confirmed = bool(self.runtime.wait_for_url_change(before, timeout=20.0, interval=1.0))

        result.session_url_after = self.runtime.current_url() or before
        verify_snap = self.runtime.snapshot()
        validation_ok, validation_status = self._validation_state(
            verify_snap,
            send_cfg.get("validation"),
        )

        ok = bool(sent and (confirmed or validation_ok))

        message = self._current_step_message("prompt sent", validation_status)
        if send_method:
            message += f" via {send_method}"
        result.add_step(
            "send",
            ok,
            message,
            url_before=before,
            url_after=result.session_url_after,
            snapshot=verify_snap.serializable(),
        )
        return ok

    # ------------------------------------------------------------------
    # Monitor
    # ------------------------------------------------------------------

    def monitor_generation(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        monitor_cfg = dict(self._workflow().get("monitor") or {})
        stop_key = monitor_cfg.get("stop_key")

        if not (stop_key and self._has_element_spec(stop_key)):
            result.add_step(
                "monitor",
                False,
                f"{self.platform} {stop_key!r} is SCAN PENDING; monitor step cannot run fail-closed",
            )
            return False

        seen_stop = False

        def _poll() -> bool:
            nonlocal seen_stop
            snap = self.runtime.snapshot()
            if snap.has(str(stop_key)):
                seen_stop = True
                return False
            return bool(seen_stop)

        completed = bool(self.runtime.wait_until(
            _poll,
            timeout=float(request.timeout),
            interval=float(monitor_cfg.get("poll_interval") or 1.0),
        ))
        verify_snap = self.runtime.snapshot()
        result.add_step(
            "monitor",
            completed,
            f"{self.platform} response completed by stop-button disappearance",
            stop_seen=seen_stop,
            snapshot=verify_snap.serializable(),
        )
        return completed

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _click_and_read_clipboard(
        self,
        snap: Snapshot,
        key: str,
        extract_cfg: Dict[str, Any],
        step_label: str,
        result: ConsultationResult,
    ) -> Optional[str]:
        """Find element by key in snapshot, click it, read clipboard. Returns text or None."""
        strategy_name = extract_cfg.get("strategy", "last_by_y")
        if strategy_name == "last_by_y":
            target = self.find_last(snap, key)
        elif strategy_name == "first":
            target = self.find_first(snap, key)
        else:
            result.add_step(step_label, False, f"{self.platform} unknown extract strategy {strategy_name!r}")
            return None

        if not target:
            return None

        click_strategy = extract_cfg.get("click_strategy")
        self.runtime.write_clipboard("")
        self._sleep(0.2)
        if not self.runtime.click(target, strategy=click_strategy):
            result.add_step(
                step_label, False,
                f"{self.platform} extraction click failed for {key!r}",
                snapshot=snap.serializable(),
            )
            return None

        self._sleep(extract_cfg.get("pause_after_click", 1.0))
        content = self.runtime.read_clipboard().strip()
        return content if content else None

    def extract_primary(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        extract_cfg = dict(self._workflow().get("extract") or {})
        primary_key = extract_cfg.get("primary_key")
        fallback_key = extract_cfg.get("fallback_key")

        # At least one extraction key must be configured and mapped
        keys_to_try = []
        if primary_key and self._has_element_spec(primary_key):
            keys_to_try.append(primary_key)
        if fallback_key and self._has_element_spec(fallback_key):
            keys_to_try.append(fallback_key)

        if not keys_to_try:
            result.add_step(
                "extract_primary",
                False,
                f"{self.platform} no extraction keys configured (primary={primary_key!r}, fallback={fallback_key!r})",
            )
            return False

        # Scroll to bottom before extraction — brings copy buttons into view
        scroll_action = extract_cfg.get("scroll_before_extract")
        if scroll_action:
            self.runtime.press(str(scroll_action))
            self._sleep(2.0)

        # Kill stale xsel processes that block clipboard writes
        try:
            subprocess.run(["pkill", "-f", "xsel.*clipboard"], capture_output=True, timeout=3)
        except Exception:
            pass

        self._sleep(extract_cfg.get("pause_before_extract", 1.0))
        snap = self.runtime.snapshot()

        # Try each key in order — use the first one that produces content
        for key in keys_to_try:
            content = self._click_and_read_clipboard(snap, key, extract_cfg, "extract_primary", result)
            if content:
                result.response_text = content
                result.add_step(
                    "extract_primary",
                    True,
                    f"{self.platform} response copied via {key!r} ({len(content)} chars)",
                    characters=len(content),
                    key_used=key,
                    preview=content[:200],
                )
                return True

        # All keys tried, none produced content
        result.add_step(
            "extract_primary",
            False,
            f"{self.platform} clipboard empty after trying keys: {keys_to_try}",
            snapshot=snap.serializable(),
        )
        return False

    def extract_additional(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        extra_cfg = dict(self._workflow().get("extra_extract") or {})
        strategy = extra_cfg.get("strategy")
        if strategy in {"", "none"}:
            result.add_step(
                "extract_additional",
                True,
                f"No additional extraction configured for {self.platform}",
                artifacts=[],
            )
            return True

        result.add_step(
            "extract_additional",
            False,
            f"{self.platform} extra_extract strategy {strategy!r} is not implemented in the generic driver",
        )
        return False

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def store_in_neo4j(
        self,
        request: ConsultationRequest,
        result: ConsultationResult,
    ) -> bool:
        if request.no_neo4j or neo4j_client is None:
            result.storage = {"skipped": True, "reason": "Neo4j disabled or unavailable"}
            result.add_step(
                "store",
                True,
                f"{self.platform} Neo4j storage skipped",
                storage=result.storage,
            )
            return True

        try:
            session_url = (
                result.session_url_after
                or result.session_url_before
                or self.runtime.current_url()
                or ""
            )
            session_id = neo4j_client.get_or_create_session(self.platform, session_url)
            user_message_id = neo4j_client.add_message(
                session_id,
                "user",
                request.message,
                request.attachments,
            )
            assistant_message_id = neo4j_client.add_message(
                session_id,
                "assistant",
                result.response_text,
                self.serialize_artifacts(result.extractions),
            )
            result.storage = {
                "session_id": session_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "url": session_url,
            }
            result.add_step(
                "store",
                True,
                f"{self.platform} response stored in Neo4j",
                storage=result.storage,
            )
            return True
        except Exception as exc:  # pragma: no cover - runtime dependent
            result.add_step("store", False, f"{self.platform} Neo4j storage failed: {exc}")
            return False
