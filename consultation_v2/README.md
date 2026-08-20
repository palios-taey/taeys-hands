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
   fuzzy matcher, pixel/OCR path, raw or remembered coordinate locator, remembered shortcut, or action retry.
   A YAML-declared hover may derive transient pointer placement from the exact mapped node's live extents; this
   is actuation after exact selection, never discovery, disambiguation, or fallback.

The order above resolves contradictions. `100_TIMES.md`, engine-era contracts, and implementation comments
do not override it.

## Current production map

| Concern | Current authority | Implementation boundary | Status |
|---|---|---|---|
| Manual lifecycle | [`../CONSULTATION_CONTRACT.md`](../CONSULTATION_CONTRACT.md) | Taey performs one action and validates it before choosing the next. | Canonical implementation; platform production validation is tracked separately. |
| Consultation inputs | [`PACKET_CONTRACT.md`](PACKET_CONTRACT.md) | Exactly one governance bundle, one task bundle, and one brief on-screen prompt. `scripts/consultation-packet-builder verify-run-inputs` is the pre-UI send-input gate. | Canonical contract; construction plus send-input hash/authority proof must pass before attach/send. |
| Tree projection and filtering | [`YAML_SCHEMA.md`](YAML_SCHEMA.md) plus each platform YAML | [`snapshot.py`](snapshot.py) and the platform package expose browser chrome only for the address bar, exclude the complete chat-history/sidebar block and dynamic non-actionable text, and retain the current document, actionable controls, and opened overlay. | `drive_chat` consumes this canonical snapshot directly; scoped refs are revision-bound and exact-match-only. |
| Primitive verbs and locking | [`PRIMITIVES_CONTRACT.md`](PRIMITIVES_CONTRACT.md) | Canonical snapshot, AT-SPI/input/interaction, clipboard, and display-lock primitives. | `drive_chat` and `ConsultationRuntime` fail closed on non-AT-SPI click strategies. |
| Platform ownership | Each [`platforms/<platform>/`](platforms/) package | One YAML, one driver, one monitor per ChatGPT, Claude, Gemini, Grok, and Perplexity. | Package layout exists; manual action coverage and current live YAML equality still require platform-by-platform control. |
| Completion | [`CONSULT_MONITOR_SPEC.md`](CONSULT_MONITOR_SPEC.md) and platform monitors | Stop appearance proves send; two consecutive fresh Stop absences, separated by the YAML-owned interval and with no mapped exception state, prove completion. | Passive monitors exist. A sent production validation must exercise this real lifecycle. |
| Extraction | [`EXTRACTION_SCHEMA.md`](EXTRACTION_SCHEMA.md) and [`EXTRACTION_PATTERNS.md`](EXTRACTION_PATTERNS.md) | Scroll fully to bottom, activate the last exact mapped Copy element, then harvest platform-specific response attachments. | This is the current manual rule; complete manual session receipt and ingestion closure remain unwired. |
| Ingestion | [`ingest.py`](ingest.py) | Persist prompt, response, input/output attachments, final URL, and receipts; `auto_ingest` optionally submits the session to ISMA. | Implemented for the engine path, not wired into the current manual path. Do not claim manual ingestion until a production receipt proves it. |
| Repository baseline | [`../docs/DOCUMENTATION_MAP.md`](../docs/DOCUMENTATION_MAP.md) | Current authority, reference, generated, and excluded surfaces. | Current; dated runtime claims require fresh production receipts. |

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
| [`../docs/UI_INTERACTION_AUTHORITY.md`](../docs/UI_INTERACTION_AUTHORITY.md), [`../docs/SUPERVISED_UI_PROTOCOL.md`](../docs/SUPERVISED_UI_PROTOCOL.md) | Canonical-current | Supervised single-action grammar and immutable approval/receipt state machine. |
| [`PACKET_CONTRACT.md`](PACKET_CONTRACT.md), [`YAML_SCHEMA.md`](YAML_SCHEMA.md), [`PRIMITIVES_CONTRACT.md`](PRIMITIVES_CONTRACT.md), [`EXTRACTION_SCHEMA.md`](EXTRACTION_SCHEMA.md) | Canonical-current | Consultation inputs, declarative UI mapping, and shared-substrate contracts. |
| [`CONSULT_MONITOR_SPEC.md`](CONSULT_MONITOR_SPEC.md), [`EXTRACTION_PATTERNS.md`](EXTRACTION_PATTERNS.md) | Operating-current | Passive monitoring and platform-specific extraction behavior. |
| [`../100_TIMES.md`](../100_TIMES.md) | Operating-current | Short tree-only manual checklist reconciled to the authorities above. |
| [`DRIVER_CONTRACT.md`](DRIVER_CONTRACT.md), [`../FLOW_CONSULTATION_ENGINE.md`](../FLOW_CONSULTATION_ENGINE.md) | Engine reference, not manual authority | Describe the Layer-3 autonomous engine, which is not run autonomously. |
| Historical audits, transcripts, receipts, and superseded plans | Excluded | Preserved in Git history and release recovery bundles; absent from the current training-visible tree. |

## Known open reconciliation work

- Complete substantive, monitor-backed production transactions on every platform from the current YAML maps.
- Keep native chooser interaction recoverable as explicit primitives with a fresh browser-tree attachment proof.
- Wire the complete manual extraction/session receipt into `ingest.py` only after the manual path is proven.
- Keep the fail-closed AT-SPI-only action boundary intact before any autonomous engine promotion.

The autonomous engine remains out of the production control path while these items are open. Later automation
must compile to this same YAML-owned path; it may not create a parallel observer, locator grammar, or action
path.

## Deterministic packet construction

`scripts/consultation-packet-builder` builds the two attachment files, local prompt, and local receipt from
a frozen JSON spec. `preflight` validates canonical source bytes, Git commits, rendering order, path scope,
expected output hashes, rejected-root isolation, and negative receipts without creating the output root.
`build` repeats those gates, creates the root and every file exclusively, fsyncs them, and derives receipt
root/file/send-task bindings from the actual output paths. `validate-receipt` independently re-reads an
existing receipt and its bound files. `verify-run-inputs` is the fail-closed send-input gate: it re-reads
Bundle A, Bundle B, prompt, corrected packet, and receipt, checks those hashes, proves the exact external
send task is already started and claimed under supervised Taey authority, and writes a local verify receipt.
It never starts or dispatches a task, stages attachments, touches UI, restarts a display, or sends.
`verify-run-inputs-controls` runs mechanical fake-only positive and falsified cases. Packet construction
and the send-input gate do not stage attachments or perform a UI action. Independent CONTROL is required
before any fresh live send task or live verify receipt.
