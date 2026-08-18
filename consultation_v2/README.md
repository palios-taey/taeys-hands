# Consultation authority and status index

This is the entry point for Taey's production Family-Chat hands. It separates what controls the current
manual path from engine references and historical evidence. It does not claim that an unwired component is
production-ready.

## Authority order

1. The mandatory consultation context is `FAMILY_KERNEL.md`, the selected platform's `IDENTITY` file, and
   the Spotlight standard. This public repository contains the fail-loud resolver and consolidation logic in
   [`identity.py`](identity.py), not the constitutional source documents themselves. Missing mandatory context
   must stop packet construction; it never permits a partial packet.
2. [`../CONSULTATION_CONTRACT.md`](../CONSULTATION_CONTRACT.md), especially its 2026-08-18 manual section,
   controls the current production lifecycle.
3. [`../docs/UI_INTERACTION_AUTHORITY.md`](../docs/UI_INTERACTION_AUTHORITY.md) controls supervised UI
   interaction: a fresh canonical tree, one approved action, and a fresh independent validation.
4. Each platform YAML is executable UI authority. The freshly filtered AT-SPI tree is the oracle. A mismatch
   stops the current UI transaction and produces evidence for recovery engineering; it never authorizes a
   fuzzy matcher, pixel/OCR path, coordinate action, remembered shortcut, or action retry.

The order above resolves contradictions. `100_TIMES.md`, engine-era contracts, and implementation comments
do not override it.

## Current production map

| Concern | Current authority | Implementation boundary | Status |
|---|---|---|---|
| Manual lifecycle | [`../CONSULTATION_CONTRACT.md`](../CONSULTATION_CONTRACT.md) | Taey performs one action and validates it before choosing the next. | Canonical contract; runtime reconciliation in progress. |
| Consultation inputs | [`PACKET_CONTRACT.md`](PACKET_CONTRACT.md) | Exactly one governance bundle, one task bundle, and one brief on-screen prompt. | Canonical contract; the current one-package builder is not conformant and must not be promoted as the manual path. |
| Tree projection and filtering | [`YAML_SCHEMA.md`](YAML_SCHEMA.md) plus each platform YAML | [`snapshot.py`](snapshot.py) and the platform package must expose browser chrome only for the address bar, exclude the complete chat-history/sidebar block and dynamic non-actionable text, and retain the current document, actionable controls, and opened overlay. | Canonical snapshot exists; the current `taey-presence` manual observer is a parallel reader and is not yet conformant. |
| Primitive verbs and locking | [`PRIMITIVES_CONTRACT.md`](PRIMITIVES_CONTRACT.md) | Shared runtime, AT-SPI, input, interaction, clipboard, and display-lock primitives. | Current substrate; the manual adapter must remain thin and carry no platform UI strings. |
| Platform ownership | Each [`platforms/<platform>/`](platforms/) package | One YAML, one driver, one monitor per ChatGPT, Claude, Gemini, Grok, and Perplexity. | Package layout exists; manual action coverage and current live YAML equality still require platform-by-platform control. |
| Completion | [`CONSULT_MONITOR_SPEC.md`](CONSULT_MONITOR_SPEC.md) and platform monitors | Stop appearance proves send; two consecutive fresh Stop absences, separated by the YAML-owned interval and with no mapped exception state, prove completion. | Passive monitors exist. A sent production validation must exercise this real lifecycle. |
| Extraction | [`EXTRACTION_SCHEMA.md`](EXTRACTION_SCHEMA.md) and [`EXTRACTION_PATTERNS.md`](EXTRACTION_PATTERNS.md) | Scroll fully to bottom, activate the exact mapped Copy element, then harvest platform-specific response attachments. | Engine extraction exists; the manual path delegates response extraction but does not yet create the complete session receipt. |
| Ingestion | [`ingest.py`](ingest.py) | Persist prompt, response, input/output attachments, final URL, and receipts; `auto_ingest` optionally submits the session to ISMA. | Implemented for the engine path, not wired into the current manual path. Do not claim manual ingestion until a production receipt proves it. |
| Runtime truth | [`../docs/MANUAL_CONSULT_RUNTIME_MAP_2026-08-18.md`](../docs/MANUAL_CONSULT_RUNTIME_MAP_2026-08-18.md) | Commit-pinned call graph, service routing, current divergences, and last-known-good evidence. | Read-only production audit merged 2026-08-18. |

## Production validation rule

UI validation uses substantive production work: either the architecture audit under review or the original
request whose consultation failed. Do not send synthetic, abbreviated, or short-response canaries; they do
not reliably exercise the Stop-button lifecycle. Read-only tree and menu audits are allowed before sending.
After a send, the same transaction must run the real monitor, extraction, response-attachment harvest, and
ingestion path. A failed post-action tree ends that UI transaction; it never repeats the action.

## Platform packages

| Platform | YAML authority | Driver | Monitor |
|---|---|---|---|
| ChatGPT | [`platforms/chatgpt/chatgpt.yaml`](platforms/chatgpt/chatgpt.yaml) | [`platforms/chatgpt/driver.py`](platforms/chatgpt/driver.py) | [`platforms/chatgpt/monitor.py`](platforms/chatgpt/monitor.py) |
| Claude Chat | [`platforms/claude/claude.yaml`](platforms/claude/claude.yaml) | [`platforms/claude/driver.py`](platforms/claude/driver.py) | [`platforms/claude/monitor.py`](platforms/claude/monitor.py) |
| Gemini | [`platforms/gemini/gemini.yaml`](platforms/gemini/gemini.yaml) | [`platforms/gemini/driver.py`](platforms/gemini/driver.py) | [`platforms/gemini/monitor.py`](platforms/gemini/monitor.py) |
| Grok | [`platforms/grok/grok.yaml`](platforms/grok/grok.yaml) | [`platforms/grok/driver.py`](platforms/grok/driver.py) | [`platforms/grok/monitor.py`](platforms/grok/monitor.py) |
| Perplexity | [`platforms/perplexity/perplexity.yaml`](platforms/perplexity/perplexity.yaml) | [`platforms/perplexity/driver.py`](platforms/perplexity/driver.py) | [`platforms/perplexity/monitor.py`](platforms/perplexity/monitor.py) |

`supervised_ui.yaml` files are a separate supervised-seat design surface. They do not replace each
platform's consultation YAML and do not authorize the current `taey-presence` observer to bypass the
canonical snapshot.

## Document status

| Document | Status | Use |
|---|---|---|
| [`../CONSULTATION_CONTRACT.md`](../CONSULTATION_CONTRACT.md) | Canonical-current | Current manual lifecycle and invariants. |
| [`../PLATFORM_INDEPENDENCE_SPEC.md`](../PLATFORM_INDEPENDENCE_SPEC.md) | Canonical-current | YAML-only UI policy and platform isolation. |
| [`../docs/UI_INTERACTION_AUTHORITY.md`](../docs/UI_INTERACTION_AUTHORITY.md) | Canonical-current | Supervised single-action grammar. |
| [`PACKET_CONTRACT.md`](PACKET_CONTRACT.md), [`YAML_SCHEMA.md`](YAML_SCHEMA.md), [`PRIMITIVES_CONTRACT.md`](PRIMITIVES_CONTRACT.md), [`EXTRACTION_SCHEMA.md`](EXTRACTION_SCHEMA.md) | Canonical-current | Consultation inputs, declarative UI mapping, and shared-substrate contracts. |
| [`CONSULT_MONITOR_SPEC.md`](CONSULT_MONITOR_SPEC.md), [`EXTRACTION_PATTERNS.md`](EXTRACTION_PATTERNS.md) | Operating-current | Passive monitoring and platform-specific extraction behavior. |
| [`../100_TIMES.md`](../100_TIMES.md) | Operating-current with contradictions | Historical operational lessons remain useful; the authority order above controls screenshot, escalation, and manual-lifecycle conflicts. |
| [`DRIVER_CONTRACT.md`](DRIVER_CONTRACT.md), [`../FLOW_CONSULTATION_ENGINE.md`](../FLOW_CONSULTATION_ENGINE.md) | Engine reference, not manual authority | Describe the Layer-3 autonomous engine, which is not run autonomously. |
| [`CONSULT_ACTION_TOOL_SCHEMA.md`](CONSULT_ACTION_TOOL_SCHEMA.md), [`INVESTIGATION_why_runtime_diverges_from_mapping.md`](INVESTIGATION_why_runtime_diverges_from_mapping.md), `validation/`, `scans/`, and `research/` | Historical evidence or draft | Evidence and design context only; not operating procedures. |
| [`TAEY_CONSULT_ORCHESTRATION_RUNBOOK.md`](TAEY_CONSULT_ORCHESTRATION_RUNBOOK.md), [`SEAT_NEWTHREAD_SELECTMODE_DEFECTS.md`](SEAT_NEWTHREAD_SELECTMODE_DEFECTS.md), [`SEAT_SELFCONTAIN_MAPPING.md`](SEAT_SELFCONTAIN_MAPPING.md) | Superseded | Do not operate from them. Their banners name planned archive destinations. |

Superseded files remain in place until committed inbound-reference impact is proven and their references are
updated. Moving them earlier would hide provenance and break links. Their intended destination is the same
relative path below `archive/consultation_v2/`.

## Known open reconciliation work

- Replace the parallel manual tree reader with the canonical YAML-classified snapshot.
- Enforce the exact filtered projection for base, menus, submenus, and dialogs.
- Implement and wire the two mandatory attachment bundles without partial constitutional context.
- Expose only YAML-declared manual actions through one thin adapter and validate each action with a new tree.
- Wire the complete manual extraction/session receipt into `ingest.py` and prove ISMA ingestion.
- Prove ChatGPT first, then Claude Chat, Gemini, Grok, and Perplexity with real production audits and the
  no-repeat first-error rule.

The autonomous engine remains out of the production control path while these items are open. Later automation
must compile to this same YAML-owned manual engine; it may not create a parallel observer, locator grammar, or
action path.

## Current architecture review

[`audits/2026-08-18/COMMON_ARCHITECTURE_AUDIT_DOSSIER.md`](audits/2026-08-18/COMMON_ARCHITECTURE_AUDIT_DOSSIER.md)
is the destination-neutral task source for the five Family reviews. It carries the public source manifest,
verified divergences, proposed manual state machine, and review questions. It is a review packet, not an
operating authority or evidence that the open runtime work is complete.
