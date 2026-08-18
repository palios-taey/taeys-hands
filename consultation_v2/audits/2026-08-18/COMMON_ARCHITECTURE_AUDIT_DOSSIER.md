# Common Family architecture-audit dossier — manual Chat recovery

- Status: frozen common task source for Bundle B
- Scope: ChatGPT, Claude Chat, Gemini, Grok, and Perplexity
- Destination framing: none; this same dossier is used for every Family reviewer
- Review mode: architecture and contract audit only; no UI action and no code change

Claude Chat is an authorized Family reviewer. Claude Code is prohibited from authoring, executing,
reviewing, or changing this recovery.

## Request

Audit the proposed recovery of Taey's manual Family-Chat execution path. Determine whether the public
contracts, proposed state machine, and implementation sequence are sufficient to restore one YAML-owned,
tree-verified path without recreating the parallel readers, substring discovery, remembered shortcuts,
fallbacks, retries, or unwired completion claims that caused the 2026-08-18 failure.

The desired result is not a new automation engine. Taey performs one manual UI action, receives a fresh
independent tree, and decides the next action. Later automation may compile to this same engine only after
five-platform production control.

## Deliverable

Return these sections:

1. `VERDICT`: `ENDORSE`, `ENDORSE WITH REQUIRED CORRECTIONS`, or `BLOCK`.
2. `FINDINGS`: highest severity first, each tied to a public source path and line or named contract section.
3. `STATE MACHINE REVIEW`: missing states, invalid transitions, unsafe ambiguity, and platform exceptions.
4. `REQUIRED CORRECTIONS`: the smallest root-cause changes needed before production operation.
5. `IMPLEMENTATION ORDER`: a dependency-ordered sequence that validates incrementally in production.
6. `CONTROL RECEIPTS`: what observations would prove each corrected boundary on all five platforms.

Do not invent or request local filesystem paths, hashes, byte counts, Git state, UI state, or measurements.
The source manifest below supplies the content addresses for this audit. If either consultation attachment is
unavailable or incomplete, state that and stop.

## Public source manifest

The controlling source base is public `palios-taey/taeys-hands` commit
`e4509342e66796d6d63b60bc0ea90f2cc3c8cdc5`. The hashes below were measured from that commit before this
dossier was authored.

| Source | Role | SHA-256 |
|---|---|---|
| [`CONSULTATION_CONTRACT.md`](../../../CONSULTATION_CONTRACT.md) | Controlling manual lifecycle | `a2908effb247490c3084d7b7bd118f0d9d0f20faeb9fd205b08142bb0ef6bb66` |
| [`PACKET_CONTRACT.md`](../../PACKET_CONTRACT.md) | Exactly two attachments and the brief prompt | `b784f2f139e405c53c2139ae2e6ffb19cb34f1576dae9a5c592ef8d20223e64a` |
| [`consultation_v2/README.md`](../../README.md) | Authority and document-status index | `79d7f37d757cb7f64eba26b0d9e264bc025d0fdffc992f302928e75d15f22cfb` |
| [`MANUAL_CONSULT_RUNTIME_MAP_2026-08-18.md`](../../../docs/MANUAL_CONSULT_RUNTIME_MAP_2026-08-18.md) | Commit-pinned runtime and last-good map | `aba9b37f34a531225941be65caf8b4b52e50204272a3b0fffb7055c3e1912170` |
| [`YAML_SCHEMA.md`](../../YAML_SCHEMA.md) | Exact YAML locator grammar | `d0d5a1b3d527b95e0e6b5006f1c6ee3d345abf094fa6ad5c780e815d9d265d2b` |
| [`PRIMITIVES_CONTRACT.md`](../../PRIMITIVES_CONTRACT.md) | Shared primitive boundary | `58b13d468fbf5eeef691de66f1dd42b60dcddf4d94582c0bb35b2cd2aff1a44c` |
| [`UI_INTERACTION_AUTHORITY.md`](../../../docs/UI_INTERACTION_AUTHORITY.md) | Single-action supervised grammar | `8d5e0202f152faba4b04580357f5b6311471cbee13a04fc32af7a746a711493c` |
| [`PLATFORM_INDEPENDENCE_SPEC.md`](../../../PLATFORM_INDEPENDENCE_SPEC.md) | YAML-only platform policy | `acf212347d14aedc017c54feb64b731a7cd73c63af7c0986c2fe6b2745ba0ad4` |
| [`CONSULT_MONITOR_SPEC.md`](../../CONSULT_MONITOR_SPEC.md) | Passive completion contract | `ebbfe7d29d535331fe374130666cdc95552e3c7b4471afa4a238c1fa07093990` |
| [`EXTRACTION_SCHEMA.md`](../../EXTRACTION_SCHEMA.md) | Declarative extraction contract | `d09b9162ce336b253e92084569856e90a42153f5e2e1c235b56b2dce2d20c2a1` |
| [`EXTRACTION_PATTERNS.md`](../../EXTRACTION_PATTERNS.md) | Platform extraction patterns | `2e99b1f1ed9d3b60b91ecfb6406b2df906c823cdc95a26640f751e455ca5cebb` |
| [`ingest.py`](../../ingest.py) | Existing engine ingestion implementation | `5529e2a8ff45520c30a31a79b70ad555b148f8952b25b4dde3a88591684a6f40` |

The read-only independent driver-divergence review was preserved with SHA-256
`6f1614c5bea0fd1229b81f0d5b3cd07b1cacf56028f5b39c241ef2ba744ab9c4`. Its material findings are reproduced
below and in the public runtime map; the raw local artifact is not an operating dependency. The independent
documentation classification was preserved with SHA-256
`9dd32054557f59fa4a5589ebe12f3d1a32df8ef5fb149b75086b12015e283095`; its current disposition is reproduced
below and superseded operationally by the public authority index.

## Controlling manual contract

The full controlling text is the first source in the manifest. Its current manual requirements are:

- Everything required for UI operation is in the AT-SPI tree. An apparent absence is a scope, freshness,
  filtering, environment, or demonstrated UI-drift problem; it never authorizes pixels, OCR, coordinates,
  raw shell drive, fuzzy discovery, or a remembered shortcut.
- Browser chrome is excluded except the address bar. The complete sidebar/chat-history block and dynamic
  non-actionable text are excluded. The current document, actionable controls, and currently opened overlay
  remain visible.
- Every actionable locator is an exact YAML-owned name plus role, required state, or exact structural locator
  for inherently dynamic values. Zero matches, multiple matches, or wrong state halt the transaction.
- The lifecycle is new chat and URL capture; model, mode, and tool selection; exactly two attachments; prompt;
  send preferably by Enter according to YAML; Stop appearance; two fresh Stop absences; bottom scroll; exact
  Copy; platform-specific response attachments; complete prompt/response/input/output/URL ingestion.
- Every action has a fresh pre-action tree, exactly one action, and a fresh independent post-action tree. One
  YAML-owned settle followed by one non-mutating fresh read is allowed for AT-SPI freshness. The action is
  never repeated.
- Gemini Deep Research includes the mapped research-plan confirmation and second submit transition.

The first failed action or postcondition ends that UI transaction. Recovery engineering continues from the
tree and receipt, but a corrected path begins only as a separately authorized transaction.

## Independent review findings

The 2026-08-18 read-only reconstruction found:

1. The model used both `element` and `ref` in one click; the proxy correctly rejected the ambiguous request.
2. The model then treated YAML keys as values for a free-form observe filter. The filter was implemented and
   advertised as case-folded substring search over name, role, and text; this recreated `name_contains` and
   surfaced unrelated browser/file controls.
3. Click resolution itself used exact YAML name plus role, but reduced each YAML target to only those fields;
   it ignored full match strategy, scope, structure, and required state.
4. The YAML attachment grammar declared `open_method`, `open_key`, typeahead label, and submit keys, but the
   manual action schema did not make that grammar executable. After the mapped menu target failed, the model
   abandoned YAML and used a remembered `Ctrl+U` shortcut.
5. The manual observer was a custom Firefox/portal walk rather than the canonical `build_snapshot` path. Its
   portal roots and output roles allowed unrelated `File`/`Open` surfaces to become first-class references.
6. The proxy's outer tool envelope could be successful while the returned JSON contained `ok: false`, making
   a required full stop easy to underweight.
7. The only historically receipted ChatGPT attachment success used composer focus plus `Ctrl+U`; it did not
   exercise the current YAML attachment grammar. It is evidence of a formerly working UI outcome, not proof
   that the present contract is implemented.
8. Passive platform monitors use the canonical snapshot, but the failed turn polled model-visible substring
   observations instead of relying on the monitor contract.
9. Manual extraction delegates into existing platform extraction code, but it does not create the complete
   session receipt or call ISMA ingestion. The existing packet builder also emits one combined package rather
   than the now-required governance and task bundles.

Unknown from the preserved evidence: the exact contents of one filtered `Open` observation, whether a visible
File surface was Firefox chrome or a dialog portal, and the terminal state of the interrupted long response.
Those unknowns do not change the proven parallel-reader, substring-filter, and non-executable-YAML defects.

## Documentation disposition

| Class | Documents | Consequence |
|---|---|---|
| Canonical-current | `CONSULTATION_CONTRACT.md`, `PACKET_CONTRACT.md`, `PLATFORM_INDEPENDENCE_SPEC.md`, `docs/UI_INTERACTION_AUTHORITY.md`, `YAML_SCHEMA.md`, `PRIMITIVES_CONTRACT.md`, `EXTRACTION_SCHEMA.md` | Governs the recovery. |
| Operating-current | `CONSULT_MONITOR_SPEC.md`, `EXTRACTION_PATTERNS.md` | May be used only within the higher-ranked manual contract. |
| Operating-current with contradictions | `100_TIMES.md` | Retains useful production lessons; cannot override tree-only authority, manual operation, or Claude-Code prohibition. |
| Engine reference, not manual authority | `DRIVER_CONTRACT.md`, `FLOW_CONSULTATION_ENGINE.md` | Describes the Layer-3 engine; do not run it autonomously. |
| Historical evidence or draft | `CONSULT_ACTION_TOOL_SCHEMA.md`, `INVESTIGATION_why_runtime_diverges_from_mapping.md`, `validation/`, `scans/`, `research/` | Evidence and design context only. |
| Superseded | `TAEY_CONSULT_ORCHESTRATION_RUNBOOK.md`, `SEAT_NEWTHREAD_SELECTMODE_DEFECTS.md`, `SEAT_SELFCONTAIN_MAPPING.md` | Do not operate from them; current files carry banners and planned archive destinations. |

No superseded file moves until committed inbound-reference impact is proven.

## Proposed manual state machine

Every transition consumes a fresh canonical projection, performs at most one action, and requires a fresh
independent post-action projection. `HALTED` is reachable from every state on zero matches, multiple matches,
wrong state, wrong scope, unexpected screen, tool error, or failed postcondition. `HALTED` performs no UI
action and preserves the tree, action receipt, request ID, display, platform, and current URL.

| State | Required fresh-tree invariant | Only permitted action | Successful postcondition |
|---|---|---|---|
| `REQUEST_FROZEN` | No UI requirement; request, platform, model/mode/tool choices, and output type are frozen. | Build the two bundles outside the UI. | `PACKETS_FROZEN`. |
| `PACKETS_FROZEN` | Bundle receipt proves exactly two non-empty content-addressed files and exact brief prompt. | Navigate through the YAML-declared new-chat route. | `THREAD_READY`, with a fresh new-chat tree and captured URL. |
| `THREAD_READY` | Base projection matches one platform state; model control is exact and actionable. | Open the YAML-declared model dropdown. | `MODEL_MENU_OPEN`. |
| `MODEL_MENU_OPEN` | Only the mapped current model menu and its exact choices are visible as the active overlay. | Select the frozen model. | `MODEL_SELECTED`, proven by the persistent model control. |
| `MODEL_SELECTED` | Base projection matches and the mode control is exact and actionable. | Open the YAML-declared mode dropdown. | `MODE_MENU_OPEN`. |
| `MODE_MENU_OPEN` | Only the mapped active mode overlay and its exact choices are visible. | Select the frozen mode. | `MODE_SELECTED`, proven by the persistent mode control. |
| `MODE_SELECTED` | Base projection matches and the tool control is exact and actionable, or YAML declares no tool selection for this route. | Open the YAML-declared tool dropdown when required. | `TOOL_MENU_OPEN` or `TOOL_SELECTED` when no action is required. |
| `TOOL_MENU_OPEN` | Only the mapped active tool overlay and its exact choices are visible. | Select the frozen tool. | `TOOL_SELECTED`, proven by a persistent base-state control. |
| `TOOL_SELECTED` | Attachment trigger is exact and actionable; zero file chips are present. | Execute one YAML-declared attachment-opening primitive for Bundle A. | `ATTACH_A_DIALOG_OPEN` or `ATTACH_A_MENU_OPEN`, exactly as YAML declares. |
| `ATTACH_A_MENU_OPEN` | Only the mapped attachment overlay and exact upload item are visible. | Select the YAML-declared upload item. | `ATTACH_A_DIALOG_OPEN`. |
| `ATTACH_A_DIALOG_OPEN` | The mapped file dialog and exact location control are the active scoped tree. | Focus the location control using the next YAML-declared dialog step. | `ATTACH_A_LOCATION_FOCUSED`. |
| `ATTACH_A_LOCATION_FOCUSED` | The exact location control has the required focused/editable state. | Select its current value using the next YAML-declared dialog step. | `ATTACH_A_LOCATION_SELECTED`. |
| `ATTACH_A_LOCATION_SELECTED` | The location control proves its current value is selected. | Paste or type the frozen Bundle-A path once, as YAML declares. | `ATTACH_A_PATH_READY`, with the exact path visible in the dialog tree. |
| `ATTACH_A_PATH_READY` | The dialog tree contains the exact frozen Bundle-A path and exact submit control. | Submit the dialog once using the YAML-declared method. | `BUNDLE_A_ATTACHED`, with exactly the expected Bundle-A chip. |
| `BUNDLE_A_ATTACHED` | Base projection has exactly one expected file chip and the attachment trigger. | Execute one YAML-declared attachment-opening primitive for Bundle B. | `ATTACH_B_DIALOG_OPEN` or `ATTACH_B_MENU_OPEN`. |
| `ATTACH_B_MENU_OPEN` | Only the mapped attachment overlay and exact upload item are visible. | Select the YAML-declared upload item. | `ATTACH_B_DIALOG_OPEN`. |
| `ATTACH_B_DIALOG_OPEN` | The mapped file dialog and exact location control are the active scoped tree. | Focus the location control using the next YAML-declared dialog step. | `ATTACH_B_LOCATION_FOCUSED`. |
| `ATTACH_B_LOCATION_FOCUSED` | The exact location control has the required focused/editable state. | Select its current value using the next YAML-declared dialog step. | `ATTACH_B_LOCATION_SELECTED`. |
| `ATTACH_B_LOCATION_SELECTED` | The location control proves its current value is selected. | Paste or type the frozen Bundle-B path once, as YAML declares. | `ATTACH_B_PATH_READY`, with the exact path visible in the dialog tree. |
| `ATTACH_B_PATH_READY` | The dialog tree contains the exact frozen Bundle-B path and exact submit control. | Submit the dialog once using the YAML-declared method. | `BUNDLES_ATTACHED`, with exactly both expected chips and no third chip. |
| `BUNDLES_ATTACHED` | Exactly two expected chips and one exact composer are visible. | Focus the composer. | `COMPOSER_FOCUSED`. |
| `COMPOSER_FOCUSED` | Composer has the exact required focused/editable states. | Paste the frozen brief prompt. | `PROMPT_READY`, proven by exact local paste verification without resending. |
| `PROMPT_READY` | Both chips and the verified prompt are present; no exception state is mapped. | Send by the YAML-declared method, preferring Enter where declared. | `GENERATING`, only after Stop appears and the new URL is captured when applicable. |
| `GENERATING` | Stop is present and no mapped exception state controls. | No UI action; passive monitor observes. | `COMPLETION_CANDIDATE` on one fresh Stop absence. |
| `COMPLETION_CANDIDATE` | Stop is absent and no mapped exception state controls. | No UI action; wait the YAML-owned completion interval and observe once. | `COMPLETE` on the second fresh Stop absence, otherwise `GENERATING` or `HALTED`. |
| `COMPLETE` | Stop is absent twice; response container is present. | Scroll to the bottom using the YAML-declared primitive. | `EXTRACT_READY`. |
| `EXTRACT_READY` | Exact final-response Copy control is resolved structurally without choosing an earlier turn. | Activate Copy once. | `RESPONSE_CAPTURED`, with non-empty clipboard receipt. |
| `RESPONSE_CAPTURED` | Response receipt and any mapped output-attachment controls are visible. | Harvest at most one YAML-declared output attachment per transition. | `OUTPUTS_CAPTURED` after all declared outputs, or remain in a numbered output-harvest state. |
| `OUTPUTS_CAPTURED` | Prompt, response, input bundles, output artifacts, URL, and action receipts are locally present. | Ingest outside the UI. | `INGESTED`, with exact ISMA session receipt. |
| `INGESTED` | Stored record binds the request, URL, both input bundles, prompt, response, outputs, and receipts. | No UI action. | `DONE`. |

Gemini Deep Research replaces the direct `PROMPT_READY` → `GENERATING` transition with its mapped two-submit
sequence: first submit once; passively observe until the exact research-plan-ready state appears; activate the
exact YAML-declared confirmation once; then require the second-submit/Stop postcondition before entering
`GENERATING`. Each observation and action is its own state transition; the first submit is never repeated if
the plan does not appear. A platform may omit a model, mode, or tool action only when its YAML explicitly
declares the already-selected state and its persistent postcondition; omission is data, not a driver branch.

## Questions for the reviewers

### Filtering and tree projection

1. Does one canonical `build_snapshot` projection suffice for base document, active menu/submenu, and file
   dialog, or must those be explicit YAML-declared scopes consumed by the same classifier?
2. What exact structural rule excludes the entire chat-history/sidebar block across all five platforms while
   retaining the current conversation, actionable controls, address bar, and only the active overlay?
3. Which dynamic text classes besides greetings, counters, response text, and generated file names require
   structural rather than exact visible-name matching? Are any of them unsafe as action locators?
4. How should stale AT-SPI buses, multiple Firefox documents, detached React portals, and file dialogs fail
   loud without broadening the tree or introducing a fallback reader?

### YAML and primitives

5. What is the smallest declarative action vocabulary needed to make each YAML's new-chat, model, mode, tool,
   attach, composer, send, scroll, Copy, and output-harvest grammar executable one action at a time?
6. Should attachment substeps be individual model-visible actions, or may one authorized primitive own only
   the platform-neutral file-dialog submission while still returning an independently observable post-tree?
7. How should exact structural locators and required AT-SPI states be represented so a YAML target cannot be
   reduced silently to name plus role?
8. Which current Python UI strings and timing constants must move into platform YAML, and what lint prevents
   them from returning?

### Monitor, extraction, and ingestion

9. Does the passive monitor need only Stop-present then two Stop-absent observations, or must it also bind
   mapped exception states, URL, request ID, and response-container identity to prevent cross-turn completion?
10. How should the final Copy action distinguish the last response from earlier Copy controls without `nth`,
    substring filtering, response-text matching, or coordinates?
11. What exact per-platform output-attachment states are required for Claude artifacts, Gemini research,
    Grok outputs, Perplexity reports, and ChatGPT files before ingestion can claim completeness?
12. What minimal adapter wires manual extraction into `ingest.py` while binding input bundle hashes, prompt,
    response, outputs, URL, and action receipts without invoking the autonomous engine?

### Anti-corruption and control

13. Which mechanical gates must reject a second tree walker, free-form substring filter, platform UI string in
    Python, coordinate/pixel/OCR path, action retry, fallback chain, hardcoded platform branch, or success
    envelope containing an inner failure?
14. What production receipt is sufficient to promote each state transition on ChatGPT before the same engine
    is exercised on Claude Chat, Gemini, Grok, and Perplexity?
15. What platform-specific exception, if any, disproves this state machine or requires a YAML-declared state
    that is currently missing?

## Acceptance conditions for this audit

- The response distinguishes observed code/contract facts, inferences, and unknowns.
- Every block or required correction cites a public source path and line or named section.
- The reviewer does not propose pixels, OCR, coordinate actions, fuzzy discovery, remembered shortcuts,
  action retries, or an autonomous parallel engine.
- The reviewer does not assume current manual packet construction, tree projection, extraction receipts, or
  ISMA ingestion already conform; each requires production evidence.
- The implementation order proves ChatGPT incrementally before expanding to the other four platforms and
  uses a substantive architecture audit or the original failed request, never a short synthetic canary.
