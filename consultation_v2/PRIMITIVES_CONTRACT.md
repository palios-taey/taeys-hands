# Shared primitive contract

Status: current operating authority for the shared mechanism layer.

## Ownership boundary

Shared code owns mechanisms only: canonical snapshot construction, exact element binding, AT-SPI focus/activate,
keyboard and clipboard input, YAML-declared hover, file-dialog focus, display locks, monitor registration, receipts,
and notification transport. It receives a platform only to load that platform's YAML and production display binding.

Each platform YAML owns every platform-specific URL, visible label, role, state, scope, structural locator, menu
operation, settle interval, validation signal, completion key, and extraction workflow. A shared module may not
carry a Chat-specific string or choose a different platform's behavior.

## Tree-selected actuation

Every target is selected from a fresh canonical AT-SPI tree by one exact YAML mapping. Zero or multiple matches,
a stale revision, a missing declared state, or an operation that contradicts YAML fails closed before mutation.

Click, focus, and activate use the bound AT-SPI object. Some real interfaces expose a hover-only
flyout or require pointer placement after the address bar has been selected exactly. A YAML-declared hover or mapped
navigation primitive may derive transient pointer placement from the already-bound node's live AT-SPI extents. Those
values are actuation payload only: they never discover, choose, disambiguate, persist, or rescue a target.

Raw/hardcoded coordinates, pixel or OCR discovery, screen-as-truth, substring/fuzzy matching, fallback targets,
fallback action strategies, hidden reads, and automatic action retries are outside the current production contract.

## Current manual surface

`drive_chat` composes the canonical snapshot and YAML-declared semantic operations one invocation at a time. Each
operation is preceded by a fresh scoped observation and followed by a fresh independent observation before Taey
chooses another operation. `focus_and_key_open` is one semantic `operate`: focus the exact bound ref, verify focus
once, then send the exact YAML open key. The runtime refuses a contradictory free verb and never retries the
operation.

`mapped_pointer_open` is one semantic `operate`: move to the fresh bound node's mapped AT-SPI extent and click the
primary pointer button exactly once. It has no coordinate input, alternate target, fallback strategy, or automatic
retry. Only a platform YAML declaration can authorize it, and the declared observation scope remains the immediate
postcondition oracle.

`consultation_v2/runtime.py::ConsultationRuntime` belongs to the retained Layer-3 engine. Its click and focus paths
are fail-closed AT-SPI operations. Promotion still requires proving one real platform transaction through the same
exact YAML/canonical-snapshot boundary.

## Fail-closed invariant

The shared layer never interprets absence as permission to try another mechanism. It records the exact mismatch and
stops the UI transaction. One YAML-owned settle followed by one fresh non-mutating observation may account for
AT-SPI refresh latency; it never repeats the action.
