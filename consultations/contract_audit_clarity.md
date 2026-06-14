I now have all the technical context I need for a thorough adversarial audit. Let me compile the analysis.

***

# CONSULTATION_CONTRACT.md — Adversarial Spec Audit

The contract has strong bones — binary match-or-notify is the right architecture — but it has **15 concrete holes**, several of which are load-bearing failures. Below they are prioritized by severity.

***

## (A) GAPS — States the Contract Doesn't Cover

### **GAP-1 (Critical): Login/Auth Walls & Session Expiry** [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/78703942/6c2ed21f-ffdc-44f1-b651-ef70c1ff88f1/taey_package_perplexity_1781395215.md?AWSAccessKeyId=ASIA2F3EMEYES33VCRZK&Signature=vHruf9TzUIKip5Eww8eHLHf%2FmgE%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEHAaCXVzLWVhc3QtMSJIMEYCIQDdMzW90tNC%2FRW0dtGfcm7CYHyX6HyjbyJB0PRqDY0aewIhAJw6dn2xZ9MKxZmu8oXWEqSOrhOWlfTrzDwLlSQR50JuKvMECDkQARoMNjk5NzUzMzA5NzA1IgwdB6vixAvigvd5QQIq0ASFkskYY3hTq2OggeB7evhqh%2FBz9d9JHXyNZn2X1D7UFSchKuTbE8Uu7KqNtp2prUD7xqHzfVTELBP5htEWtMnll4VBGxZIo5TMO5ZaKtnFVXxbX3%2Be4erR3Ydbk%2BiBPrATeREHE%2BWwUy%2FH%2FP%2B1DftsQRAxVt2D%2F8EswRCAraAUZPEGJTTOu2NZ1oCJcMVM3U%2FKXz%2FvF37ziIrD9LdlDzbvz0IYmfpq5wIS3JUoV33gIk%2FOhzOjUke2e3Tk87BoFspoHelyMuz7%2FLFwHc8ezBlj%2FeYb4oTgf8kVk1QhOUEg0WEdgU9FrXdJK9FqDfqIbpZDYAohtVROpnhXPNXEvsB2VkKcFrw8JA12y0C5dyrbdRj%2FKLgi3OHVsBS0YKPOwkVc5annBW%2Bhm1RGrz%2Fgx0cWHkF%2BUZXZnAU5IkzTaalg4%2B3gWgmkPRjS%2BVaZcHpmnI%2Fk234TPpqave4zFUI81%2Bn5i6xaugbJtTE7%2BlpIXR3tYctNJ8D9oXOHXyPSQyICyED8nWMfsLbVDvGvtaODPMyJd3vodouVgwTSPmxyZcCu7OkcG%2BIGK70SLKb8kdf4s1F3e5HBT1e4MU99N6cmR%2BCImd7yAHcfLxne3jxxGOKBsA2JJEdweUC9teG0MfcYbAH80SINjgzfuAfyLXCm23JH2%2FhP8dIboIkPX3BeBvsnwuhCQ3Z60XHHuqiOIJZWIPaWVgxarvSfihn9Fip%2F%2BpnaEJVQQj2%2F5Jyob7Q%2FrbVjEQgjy5RuvN%2FmnVl%2BtG0BHnPufqLUY5lOeYgm3xzZrfsRMLvPt9EGOpcB%2BqrQc3Pl7pV7jIIFXG2RsHHP4%2B%2BNOpmU08rdzji1V9WqB27Zwv93Dus8dRyHSZPvEgVVzDZYhQXW%2FUkicPzTorIuAWQJXcctnvUQvylkL1s6Si6aNymfDFcNBKwmtpZ5n2tLmHqp7C19XXRZFFQL%2BnITlibIs9r6vPDX2TN0UdTgWhN2DvXqxdsjxNyI%2FDST3kRtuErUMg%3D%3D&Expires=1781396878)

The contract maps the *operating* screens but defines zero states for:
- The login page (username+password fields, OAuth/SSO redirect, 2FA prompt)
- The post-expiry re-login interstitial (which can look exactly like a login page or a modal overlay)
- Cookie consent banners that appear on first load or after a reset

**Why it breaks the binary:** The driver wakes up, scans the tree, finds no `Submit` button and no `Stop` button — it is neither the mapped *idle* state nor any *generating/complete* state. The contract says "notify + halt on mismatch," but without a mapped `AUTH_REQUIRED` screen, the notification payload contains candidates that look like a login form, and the operator has no guidance on what to do.

**Amendment:** Map a `state: auth_required` per platform YAML with the canonical element set for the login/session-expired screen (platform-specific: e.g., Grok uses a Twitter OAuth flow). Add to the contract: *"If the tree matches the auth_required map, emit `AUTH_REQUIRED` notification and halt — do not attempt any submission step."* This keeps the binary: it's either `auth_required` (mapped halt) or something new (drift halt).

***

### **GAP-2 (Critical): Rate-Limit, Quota, and Error Modals** [perspectiveai](https://perspectiveai.xyz/ai-pricing-guide-2026-every-plan-compared/)

Every platform pops modal overlays for rate limits, daily/weekly quota exhaustion, network errors, and content-policy refusals. These are `role=dialog` or `role=alertdialog` elements in the accessibility tree — they appear *on top of* the normal chat surface. The contract says "nothing is ever hidden," but with `aria-modal=true` (or `aria-hidden` applied to background), the AT-SPI tree often **hides the background nodes** while the modal is active. [medium](https://medium.com/@mdctleo/accessibility-and-modals-b8222ffc03)

**Why it breaks the binary:** The driver scans the tree mid-run. The input area it expects is present in the YAML but now has `ATK_STATE_INVISIBLE` or is excluded from the AT-SPI tree by `aria-hidden` applied to the parent. The settle+rescan loop fires, tree still looks the same, and the driver halts with "input box drifted" — which is *wrong*: the element exists, it's just eclipsed by a modal the YAML doesn't know about.

**Amendment:** Map a `state: modal_overlay` for each platform with a sentinel element that is exclusively present during any blocking modal (typically the modal's own close/dismiss button with its exact name+role). The driver must check for `modal_overlay` *before* validating the primary step map. If `modal_overlay` matches → emit `MODAL_BLOCKED` notification with modal text (name of the dialog element) and halt. This folds the case back into binary.

***

### **GAP-3 (Critical): Generating State Ambiguity — Network Stall vs. True Generation**

The contract defines: *Generating = Stop button present*. But a network stall between sending and server acknowledgment produces a window where the prompt was submitted (URL changed, new chat created) but the Stop button has not yet appeared in the AT-SPI tree. The contract correctly handles timing lag with settle+rescan — but the settle window is a **constant**, not bounded by the Stop button's appearance.

**Why it breaks the binary:** If generation takes >settle_window to begin (e.g., overloaded server), the driver enters a second no-match → halt. This is an incorrect halt — generation did start, the tree just hasn't caught up. The operator receives "Stop button not found" with no signal that the submission itself was confirmed.

**Amendment:** Split the `submit_succeeded` validation into two independent checks: (1) new URL present — this is fast and confirms submission; (2) Stop button present — this can have a longer settle window. Define a `state: awaiting_generation` = `(new_url == true) AND (stop_button == false)`. The driver polls stop_button independently with a separate (longer) settle window (per-platform constant). Only if stop_button is absent after the generation-settle window does it halt with `GENERATION_START_TIMEOUT`.

***

### **GAP-4 (High): "Regenerate," "Continue," and "Edit" Response States**

All five platforms have UI controls that appear *after* a completed response: regenerate, edit message, copy, thumbs up/down, "continue generating" (when output was cut). These are mapped as "completed screen" elements, but the contract says `Complete = Stop gone` without defining whether these secondary controls are part of the *completed* state map or are separate states.

**Amendment:** The completed screen YAML must explicitly list every post-response control. The "continue generating" button (or its platform equivalent) is a distinct `state: truncated_response` and must be mapped — if present, it means generation was not complete and the contract must define whether that is `Complete` or a new halt condition.

***

### **GAP-5 (High): Multi-Step Flyouts and Hover-to-Expand Submenus**

The contract states every menu/submenu is mapped exact. But hover-triggered submenus are **not always present in the AT-SPI tree until the hover occurs** — they are rendered dynamically into a React portal or a separate DOM subtree. AT-SPI bridges the browser's AX tree, and nodes that don't exist in the DOM don't appear in the tree. A flyout that requires a hover event to render its children will scan as empty under its parent. [aiopsgroup](https://aiopsgroup.com/the-screen-reader-matrix/)

**Amendment:** For every hover-triggered submenu, the YAML must include an explicit `trigger_action: hover` annotation, and the driver must issue an AT-SPI `action("hover")` on the parent element *before* snapshotting the submenu children. The settle window for hover flyouts must be a separate per-element constant, not the default settle. Contract must state: *"Submenus with `trigger_action: hover` are not present in the tree until triggered; scanning before trigger is always a false miss, not drift."*

***

### **GAP-6 (Medium): File-Upload Dialog — Focus Escape**

When a file-upload dialog (native OS dialog) is triggered, focus moves to the OS-level window, which is **outside** the browser's accessibility tree entirely. AT-SPI sees the browser nodes go stale (the whole browser may lose `ATK_STATE_ACTIVE`). The file dialog itself is in a separate AT-SPI application subtree (the file chooser daemon), not under the browser.

**Amendment:** Map `state: file_dialog_active` as a browser-side sentinel: a specific element that becomes visible/focused *while* the dialog is open (e.g., the attach button changing to a cancel state). File path injection must be handled via a separate AT-SPI walk of the OS file dialog application tree — this is a distinct driver primitive (`file_dialog_paste`) not covered by the current shared primitives. Contract must list this explicitly.

***

### **GAP-7 (Medium): Platform Surfaces with Zero AT-SPI Exposure**

Some canvas-rendered or WebGL UI elements (e.g., certain Gemini experimental features, or ChatGPT's voice/canvas mode) expose **nothing** to AT-SPI. If a platform rolls out a new UI surface rendered via canvas, the entire surface has `role: document` with no children. The contract says "if something isn't there, it's timing lag or YAML drift," but this is a third case: it's architecturally inaccessible. [aiopsgroup](https://aiopsgroup.com/the-screen-reader-matrix/)

**Amendment:** Add to the contract: *"A platform surface that exposes fewer than N named interactive elements (per-platform threshold in YAML) after the maximum settle window is classified as `state: AT_SPI_BLIND`. Emit `AT_SPI_BLIND` notification and halt. This is not drift — it is a hard architectural limit that requires manual operator action (disable that UI surface, revert to classic mode)."*

***

## (B) CONTRADICTIONS AND AMBIGUITIES

### **AMB-1 (Critical): "Match" Is Undefined for Disabled Elements** [gnome.pages.gitlab.gnome](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/enum.StateType.html)

The contract requires exact `name + role` match. But AT-SPI elements also carry a **state set** (enabled, disabled, grayed, sensitive). A button present with the correct name and role but `ATK_STATE_INSENSITIVE` (disabled) is a match by the contract's definition — yet clicking it does nothing. This is not drift; it's a valid UI state (e.g., the Send button before the user types).

**Amendment:** The contract must define: *"A match requires: name exact ∧ role exact ∧ state set includes `ATK_STATE_ENABLED` (or the element-specific required states listed in the YAML). An element that matches name+role but is disabled is `state: element_disabled`, not a match. Emit `ELEMENT_DISABLED` notification and halt."* Each mapped element's YAML entry must list its required state set.

***

### **AMB-2 (Critical): Duplicate Name+Role Elements**

The contract assumes the name+role combination is unique within the surface. But AI chat UIs routinely have multiple elements with the same name and role: e.g., multiple "Copy" buttons (one per message), multiple "Edit" buttons, or — during streaming — two consecutive user/assistant turns where the structural names collide. The contract's exact-match lookup returns an ambiguous set. [forum.uipath](https://forum.uipath.com/t/how-to-resolve-duplicate-elements-found-issue/569560)

**Amendment:** The YAML must add a `position` qualifier (e.g., `tree_path: root > main > article[-1] > footer > button[0]`) or an `index` field for any element that is not provably unique by name+role alone. The contract must state: *"If an exact name+role query returns N>1 candidates, and no YAML position qualifier is specified, this is a spec error — emit `AMBIGUOUS_MATCH` and halt (not proceed with first result)."*

***

### **AMB-3 (High): Two Rules Can Conflict — Submit Validation**

The contract says: *Submit succeeded = new URL AND Stop button appeared.* But the two signals are not atomic. Consider: new URL appears → driver checks Stop button → Stop button not yet in tree → settle+rescan → Stop button appears. That's fine. But what if: new URL appears → Stop button appears briefly → platform immediately completes a very short response → Stop button disappears *before* the rescan. The driver sees: new URL ✓, Stop button ✗ → second rule not met → HALT — but the run actually completed successfully.

**Amendment:** The completion detection must be stateful: once a new URL is confirmed, the driver enters a `monitoring` state where it polls for Stop button appearance. If Stop never appears within the generation-settle window *and* the response area is not populated, that's a failure. If the response area *is* populated and Stop is gone, that's a `fast_complete` — a valid terminal state. Map `state: fast_complete` explicitly.

***

### **AMB-4 (Medium): Role Changed, Name Stable**

The contract anchors on `name + role`. Platforms sometimes do silent A/B tests or refactors where an element keeps its accessible name but its ARIA role changes (e.g., a `button` becomes a `menuitem`). By the contract, this is drift (no match). But the notification says "live candidates" without specifying that the differing field is `role`. The operator updating the YAML might update only the name (unchanged) and not the role (changed) — patching the wrong field.

**Amendment:** The NOTIFY payload must explicitly call out *which field(s) differed* (name, role, state, path) so the operator's YAML patch targets the correct field. Contract must state: *"NOTIFY must include: expected_name, expected_role, live_name, live_role, diff=[name|role|state|path]."*

***

### **AMB-5 (Medium): Settle Window Is a Constant, But the Problem Is Probabilistic**

The contract states settle windows are "per-platform constants in the YAML, not guesses." But these constants were calibrated at mapping time under specific network/server conditions. A slow server or a heavily loaded morning session can push real settle times beyond the constant — making a legitimate element scan look like drift. The constant is a guess with a confidence interval, not a formal bound.

**Amendment:** The contract must acknowledge this explicitly and specify: *"The settle constant is the P95 settle time measured during YAML mapping. Exceeding it is treated as drift and results in NOTIFY+HALT — this is the correct behavior because it surfaces degraded platform performance. Operators must not increase the constant without re-measuring the P95."* This keeps the binary honest about what it's actually encoding.

***

## (C) CASES THE BINARY GENUINELY CAN'T EXPRESS — AND HOW TO FOLD THEM BACK

### **CASE-1: Partial/Lagged Tree Refresh (Stale Subtree)**

AT-SPI bridges the browser AX tree, but the browser doesn't guarantee atomic updates. A partial render (React reconciliation mid-flight) can produce a tree where some nodes are updated and others are stale. The settle+rescan catches the *total absence* case but not the *partial corruption* case — where the element name is present but its children (e.g., a menu's option list) are from the previous render.

**How to fold back:** Add a `tree_checksum` or `child_count` assertion to composite elements in the YAML. For any element where children matter (menus, model pickers), the YAML specifies the expected child count. If `actual_child_count ≠ expected_child_count` after settle, emit `PARTIAL_TREE` notification and halt. This makes partial stale trees a first-class named state.

***

### **CASE-2: "Generating" Screen Where Stop Exists But Response Isn't Streaming**

Stop is present (so the contract says "generating"), but the response area is empty and has been empty for more than a platform-specific timeout. This is a hung generation — the model started but is not streaming (network drop post-submit, or a server-side error that didn't close the connection). The binary treats this as still-generating forever.

**How to fold back:** Map `state: generation_stalled` = `(stop_present) AND (response_tokens_in_AT_SPI == 0) AND (elapsed > stall_timeout_constant)`. The response area in AT-SPI has a text child that gains characters as tokens stream. If that child remains empty past `stall_timeout_constant`, emit `GENERATION_STALLED` and halt. The "token counter" is an AT-SPI child node character count — deterministic, not inferred.

***

### **CASE-3: Model/Mode Selection Where the Current Selection Is Shown Mid-Flyout**

When the model picker flyout is open, the currently active model typically has a visual checkmark or `ATK_STATE_CHECKED`. Selecting a new model requires clicking an unchecked item. If the platform changes how it marks the current selection (e.g., `ATK_STATE_CHECKED` → `aria-selected=true` mapped to a different AT-SPI state), the driver cannot distinguish "this is the current model (already selected)" from "this is a model I haven't selected yet."

**How to fold back:** The YAML for each model option must specify a `current_selection_state` (the AT-SPI state set that indicates "already selected") and a `selectable_state` (the state set indicating "can be selected"). The driver checks: if the target option has `current_selection_state`, it's already set — skip the click, proceed. If it has `selectable_state`, click it. If it has neither, it's an unmapped state → halt.

***

### **CASE-4: Is a Fallback Ever Truly Unavoidable?**

**Argument for one genuine fallback:** The OS-level file dialog (GAP-6) is outside the browser's AT-SPI tree. Walking the OS file dialog subtree requires a second AT-SPI application lookup (by process name or bus name). This lookup can fail if the file dialog is from a non-standard GTK/Qt toolkit that doesn't register with the AT-SPI registry. In that case, there is no AT-SPI path at all.

**Counter-argument (fold-back preferred):** The file path can be injected via `xdotool type` at the X display level, which bypasses AT-SPI entirely and is deterministic given an isolated X display. This should be the mapped primitive: `file_inject_xdotool(path)`. If `xdotool` fails (returns non-zero), that is a clear binary failure — emit `FILE_INJECT_FAILED` and halt. No fallback; the X-level injection is itself a formal mapped action with a formal success condition. **Verdict: no fallback truly unavoidable.**

***

## (D) STICKINESS — Is the Enforcement Actually Regression-Proof?

The contract's four-layer enforcement (code-only paths, pre-commit lint, risky-path merge gate, canonical file) is strong but has five holes:

### **STICK-1 (Critical): The Lint Rule Is Only as Good as Its Pattern List**

The lint bans `name_contains`, `name_pattern`, substring matching, silent-proceed, and fallback/downgrade keywords. But a future editor can implement fuzzy logic under a *different name* — e.g., `find_element_by_similarity()` or `get_closest_match()` or wrapping the exact match in a try/except that catches `ElementNotFound` and "retries with broader scope." The lint catches syntactic patterns, not semantic violations.

**Amendment:** The lint must be augmented with an AST-level check: any function call that returns an element reference *without* calling the canonical `exact_match()` primitive must fail the build. Equivalently: the only legal way to obtain an element reference is through the single `match_or_halt()` function — all other element-lookup calls (including AT-SPI library direct calls) are banned in driver code.

***

### **STICK-2 (High): The Gatekeeper Can Be Socially Engineered**

The merge gate requires `audit/grok + audit/gatekeeper` execute-verify. But the Gatekeeper is an AI instance executing repro. If the PR description says "this is a cosmetic rename, not a session-driving surface change" and the diff *looks* innocuous, the Gatekeeper may approve without full repro if the repro test suite doesn't cover the specific drift scenario introduced by the change.

**Amendment:** The merge gate must require a *failing test that passes after the PR* for any YAML or driver change — i.e., no YAML update can merge without a test that demonstrates the old YAML produced a NOTIFY+HALT and the new YAML produces a MATCH. The Gatekeeper's execute-verify must run this specific regression, not just "the repro."

***

### **STICK-3 (High): The YAML Is the Map, But the Map Has No Schema Validator**

The contract specifies YAML as the element map but doesn't define a schema. A future YAML edit could introduce a new field (e.g., `name_fuzzy_fallback: true`) that the driver silently ignores or silently uses if a driver code path checks for it. Without a strict schema (and a lint/build-time schema validation step), the YAML is an unconstrained vector for introducing soft fallbacks.

**Amendment:** Define a JSON Schema or Pydantic model for the YAML. Build-time validation must reject any YAML key not in the schema. The schema must explicitly exclude keys like `fuzzy`, `fallback`, `approximate`, `pattern`, `regex`.

***

### **STICK-4 (Medium): Session-Driving Surface Definition Is Ambiguous**

The merge gate applies to "session-driving surfaces." But this classification lives in the contract prose, not in the code. A future editor who adds a new helper function that touches element lookup may not self-classify it as "session-driving" and therefore may not trigger the risky-path gate.

**Amendment:** The classification must be code-enforced: any file in the driver/dispatch layer is automatically in scope for the merge gate (enforced by file-path pattern in the CI config), not by human judgment on each PR.

***

### **STICK-5 (Low): Canonical File Can Drift From Runtime Behavior**

The contract says: *"This file is the canonical reference; skills point at it; stale trap-lists are subordinate to it."* But if a platform UI updates and the YAML is patched (via the NOTIFY+HALT → operator-update loop), but the CONSULTATION_CONTRACT.md prose is not updated to describe the new state, the contract and the YAML diverge. The contract becomes stale documentation while the YAML is the live truth.

**Amendment:** The contract must explicitly state that the YAML files *are* the canonical element maps — the contract prose defines the *rules*, not the element values. The prose should never enumerate specific element names; those live only in YAML. This prevents divergence between the two artifacts.

***

## Prioritized Closing List

| Priority | ID | Category | Amendment Summary |
|---|---|---|---|
| P0 | GAP-1 | Gap | Map `auth_required` state per platform; halt on auth wall, not on mismatch |
| P0 | GAP-2 | Gap | Map `modal_overlay` sentinel per platform; scan for it before primary map |
| P0 | AMB-1 | Ambiguity | Define match = name + role + required state set (enabled); disabled = halt |
| P0 | AMB-2 | Ambiguity | Add `position` qualifier to YAML; N>1 candidates = `AMBIGUOUS_MATCH` halt |
| P1 | GAP-3 | Gap | Split submit validation: URL-confirm fast, Stop-button on separate poll window |
| P1 | AMB-3 | Contradiction | Map `fast_complete` state; stateful monitoring after URL confirm |
| P1 | STICK-1 | Stickiness | Lint must be AST-level: only `match_or_halt()` may return element references |
| P1 | STICK-2 | Stickiness | Merge gate requires failing→passing test, not just Gatekeeper repro approval |
| P2 | GAP-4 | Gap | Map `truncated_response` state; "continue" button is not `complete` |
| P2 | GAP-5 | Gap | Annotate hover-flyouts in YAML; driver must trigger hover before snapshot |
| P2 | CASE-1 | Binary limit | Add `child_count` assertion to composite YAML elements; partial tree = halt |
| P2 | CASE-2 | Binary limit | Map `generation_stalled`; token-count monitor on response node |
| P2 | AMB-4 | Ambiguity | NOTIFY payload must diff expected vs. live on each field (name/role/state/path) |
| P3 | GAP-6 | Gap | Map `file_dialog_active` sentinel; file inject via `xdotool`, not AT-SPI walk |
| P3 | STICK-3 | Stickiness | Schema-validate YAML at build time; ban fuzzy/fallback keys by schema |
| P3 | GAP-7 | Gap | Map `AT_SPI_BLIND` state; N < threshold elements after max settle = architectural halt |
| P3 | CASE-3 | Binary limit | YAML model entries must declare `current_selection_state` vs. `selectable_state` |
| P3 | STICK-4 | Stickiness | File-path pattern in CI auto-classifies driver files as risky-path, no human judgment |
| P4 | AMB-5 | Ambiguity | Contract must declare settle constant = P95; exceeding = drift, not a tuning failure |
| P4 | STICK-5 | Stickiness | Prose contract must not enumerate element names; YAML is the element truth |

***

**Verdict:** The contract is not yet airtight enough to build a 100%-reliable engine on — the single most important fix is **GAP-2 + AMB-1 combined**: modals and disabled-state elements both cause the contract's "nothing is ever hidden" axiom to be false in production, which means the binary silently fires on the wrong diagnosis (drift when the correct diagnosis is `modal_blocked` or `element_disabled`), generating operator noise and masking real failures from synthetic ones.