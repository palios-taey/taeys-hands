# Grok Package Residue Audit

Pinned implementation commit: `81d3d921`.

Cannot-lie summary: this branch completes Grok package isolation and moves Grok driver, monitor, and YAML ownership. It does not fully decommission every conditionally-leaf routing residue listed in PLATFORM_INDEPENDENCE_SPEC Section 4. The table below distinguishes reclassified shared primitives from unresolved residue.

| Module | Observed residue / classification | Evidence | Disposition in this slice |
| --- | --- | --- | --- |
| `consultation_v2/input.py` | Still conditionally leaf: `switch_to_platform(platform)` branches through platform display, URL, PID, and shortcut routing. | `consultation_v2/input.py:186`, `consultation_v2/input.py:269` | Unresolved; retained through `ConsultationRuntime.switch_to_platform`. Follow-up split or orchestrator-owned routing decision required. |
| `consultation_v2/atspi.py` | Still conditionally leaf: URL detection maps URLs back to platform names and `get_platform_document` filters by platform. | `consultation_v2/atspi.py:138`, `consultation_v2/atspi.py:152`, `consultation_v2/atspi.py:174` | Unresolved; retained as shared AT-SPI discovery until routing ownership is split. |
| `consultation_v2/platforms_runtime.py` | Platform/display configuration and allocation are fleet orchestration concerns. | `consultation_v2/platforms_runtime.py:264`, `consultation_v2/orchestrator.py:48` | Reclassified as orchestrator-owned runtime. Grok package does not import it directly. |
| `consultation_v2/runtime.py` | Shared browser-runtime operations parameterized by `self.platform`; it still calls `input` and `atspi` routing helpers. | `consultation_v2/runtime.py:36`, `consultation_v2/runtime.py:155`, `consultation_v2/runtime.py:184` | Retained as mechanical runtime primitive for this slice; upstream routing residue remains named. |
| `consultation_v2/snapshot.py` | Shared snapshot builder loads platform YAML and uses shared AT-SPI document lookup. | `consultation_v2/snapshot.py:621`, `consultation_v2/snapshot.py:640`, `consultation_v2/snapshot.py:647` | Retained as mechanical snapshot primitive; not Grok-specific. |
| `consultation_v2/planner.py` | YAML-data-driven selection planning, keyed by request platform. | `consultation_v2/planner.py:32`, `consultation_v2/planner.py:57` | Reclassified as shared YAML planner; no hard-coded Grok behavior observed. |
| `consultation_v2/interact.py` | Element cache keyed by platform but does not branch on specific platform names. | `consultation_v2/interact.py:19`, `consultation_v2/interact.py:45` | Reclassified as shared interaction primitive. |
| `consultation_v2/primitives.py` | Source documents platform as opaque data and platform lock contention unit. | `consultation_v2/primitives.py:33`, `consultation_v2/primitives.py:381` | Reclassified as shared primitive module. |

Control implication: if Section 4 requires full deletion/splitting of `input.py` and `atspi.py` residue in the Grok PR, this branch is not complete. If the Grok slice gate is package isolation plus honest residue classification, this branch is ready for parent review.
