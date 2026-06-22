**AUDIT COMPLETE — DEFECTS SURFACED. NO ENDORSEMENT.**

**Evidence base**: verbatim reads of `CONSULTATION_CONTRACT.md`, `FLOW_CONSULTATION_ENGINE.md`, `100_TIMES.md`, `consultation_v2/drivers/grok.py`, `consultation_v2/platforms/grok.yaml`, `consultation_v2/drivers/base.py`, `consultation_v2/snapshot.py` (and cross-referenced shared modules). All claims are line-pinned to these artifacts. Live Grok UI cross-check (composer entry role/name, Stop button, Attach flow, multi-line submit behavior, Copy button positioning) performed against current grok.com surface.

**Operating law applied**: Evidence ∩ Logic ∩ Skepticism. First error = full stop. Binary match-or-notify is non-negotiable. 6SIGMA DPMO<3.4. Three-register per finding. Driver isolation and exact-match YAML are load-bearing invariants. No softening. No "it mostly works" escape hatch.

---

### 1. file: consultation_v2/drivers/grok.py:289 (send_prompt) + 234 (_focus_input) + 284 (call site)
**Discrepancy**: Hardcoded `self.runtime.press('Return')` after custom `_focus_input()` (coord-click + `grab_focus()`) instead of reading `cfg['workflow']['send']['send_key']` (which yaml maps to `send_button`) and performing the yaml-declared action. The submit button element exists in yaml and element_map but is bypassed.  
**Observed**: Code contains grok-specific comments referencing "battle-tested scripts/consultation.py" and "plain element click alone does NOT reliably land keyboard focus on grok's composer". This is platform knowledge and a non-yaml path.  
**Inferred**: Workaround for intermittent AT-SPI `doAction` on the Submit push button in grok's multi-line entry (Enter inserts newline).  
**Unknown**: Whether `send_button` in yaml is dead code or used in any execution path for grok.  
**Severity**: **blocker** (violates "Drivers carry zero platform knowledge", "every element name/role from yaml via self.cfg", and exact-match contract; makes send non-configurable and creates divergence between yaml and behavior).  
**Fix direction**: Either (a) extend yaml `send` stanza with explicit `method: keypress|click` + implement in base, or (b) remove the override and fix the AT-SPI click path in primitives/runtime so yaml remains authoritative. Do not leave the bypass in place.

### 2. file: consultation_v2/drivers/grok.py:121-125 + 142-146 + 349-353 (wait_until lambdas in attach_files + extract_response)
**Discrepancy**: Multiple `self.runtime.wait_until(lambda: self.runtime.snapshot().has(key), timeout=..., interval=0.4)` before single find/click. While labeled "observation / settle", the pattern is a bounded poll inside the action sequence.  
**Observed**: Contract explicitly allows one settle+rescan before declaring drift; second no-match after settle = notify. Here the poll is inside the step and the failure path correctly returns False + add_step(False). No action retry occurs.  
**Inferred**: Defensive against the exact race the user flagged (page_ready / composer not yet in AT-SPI tree post-navigate).  
**Unknown**: Whether `wait_until` implementation in runtime.py ever escalates to action re-attempt on timeout (would be invisible here).  
**Severity**: **minor** (pattern is observation, not banned retry; still surfaces miss correctly).  
**Fix direction**: Keep, but document in DRIVER_CONTRACT.md that bounded readiness polls on snapshot().has() are the sanctioned form of settle. Add unit test that forces a mid-poll tree mutation and asserts no duplicate action.

### 3. file: consultation_v2/platforms/grok.yaml: element_map + workflow (multiple keys)
**Discrepancy check**: No `name_contains`, `name_pattern`, `role_contains`, `fuzzy`, `regex`, `substring`, `contains`, or wildcard presence-only matchers present in any element_map entry or validation spec. All are exact `name` + `role` (+ optional `states_include`). `snapshot.py: _reject_forbidden_matcher_keys` + `_FORBIDDEN_MATCHER_KEYS` will raise at yaml load if any appear.  
**Observed**: grok.yaml passes the exact-match gate. `stop_button`, `copy_button`, `attach_trigger`, `upload_files_item`, `input`, model items, and `remove_attachment` are all exact + live-confirmed comments present.  
**Inferred**: YAML is currently compliant on the banned-matcher rule.  
**Unknown**: Whether the exact strings still match live grok.com AT-SPI tree on every display/profile (React portal timing, locale, A/B, or post-2026-06-03 UI diff could drift one without breaking the loader).  
**Severity**: **minor** (no violation in checked artifact; maintenance burden exists per contract).  
**Fix direction**: Add CI job that runs live AT-SPI scan on grok.com (headless or display :5) and diffs against grok.yaml element_map names/roles. Fail on any delta. Keep the rejector in snapshot.py.

### 4. file: consultation_v2/drivers/grok.py:343 (extract_response) + 100_TIMES.md:16-26
**Discrepancy**: Uses `self.runtime.press('ctrl+End')` then wait + `find_last(copy_button)`. 100_TIMES §2 states `ctrl+End` is NOT reliable everywhere (on Claude it focuses composer and can hide the final Copy). Grok-specific comment claims it works here.  
**Observed**: Code follows the grok carve-out explicitly noted in 100_TIMES. Scroll happens before copy click; validation requires `len(content) > len(prompt) && content != prompt`.  
**Inferred**: Acceptable for grok surface; the "lowest Copy button" rule is satisfied by `find_last`.  
**Unknown**: Edge case where grok thread is extremely long and `ctrl+End` + AT-SPI timing still misses the final button (would surface as extract=False, correct per contract).  
**Severity**: **minor** (grok-specific but documented and within allowed carve-out).  
**Fix direction**: None required for grok. For other platforms that inherit scroll logic, enforce `runtime.scroll_to_bottom(anchor=composer)` as the cross-platform primitive and keep `ctrl+End` only where yaml or driver explicitly opts in.

### 5. file: consultation_v2/drivers/base.py:327-376 (wait_for_page_ready_after_navigation) + grok.py:95 (call)
**Discrepancy check vs robustness note**: Single-shot post-navigate check for composer/input was the known live failure mode. Implementation uses `wait_for_stable_snapshot(consecutive=2, ...)` + `_page_ready_key_groups()` (input + selection triggers + attach_trigger) + anchor_key. Polls until stable or timeout, then surfaces False with missing list.  
**Observed**: Directly mitigates the exact race condition called out. No silent "controls not exposed" false negative that proceeds.  
**Inferred**: This is the correct engineering response to the contract's settle+rescan rule.  
**Unknown**: Whether `_page_ready_anchor_key` selection (entry role in base.composer scope) can pick a non-composer entry on some grok surfaces (Imagine vs chat).  
**Severity**: **none** (positive; the implementation already contains the fix the audit example demanded).  
**Fix direction**: Add regression test that forces a slow AT-SPI populate after navigate and asserts the wait succeeds without false drift.

### 6. file: consultation_v2/drivers/grok.py:71 (monitor_and_extract) + completion.py (delegated monitor_generation)
**Discrepancy check**: Completion signal is stop-button disappearance only. No positive marker (Copy/Regenerate) is used to declare complete. `send_fired` validation seeds `_send_stop_seen`; `monitor_generation` (shared) applies debounce + generation_timeout from yaml.  
**Observed**: Aligns with CONTRACT § "Complete = Stop button gone. This is the signal — there is no reliable positive completion indicator." Stop-present past timeout → mapped stalled state → notify.  
**Inferred**: Correct. The fast-gen race is explicitly ruled out in contract for production workloads.  
**Unknown**: Exact generation_timeout value in current grok.yaml (settle section has defaults but monitor stanza may inherit).  
**Severity**: **none** (compliant).  
**Fix direction**: Ensure yaml explicitly declares `monitor.generation_timeout` (or inherit documented default) so the watchdog is not implicit.

### 7. Overall driver isolation (grok.py imports)
**Discrepancy check**: `from consultation_v2.drivers.base import BaseConsultationDriver`; `from consultation_v2.types import ...`; `from consultation_v2 import primitives` (indirect via base). No imports of chatgpt.py / claude.py / gemini.py / perplexity.py. No platform strings hardcoded except inside grok-specific methods (already flagged in #1).  
**Observed**: Isolation rule satisfied on import graph.  
**Inferred**: The platform-specific logic is encapsulated inside the grok driver file (as intended for per-platform overrides), but the send/focus bypass still violates the "zero platform knowledge / yaml authoritative" intent.  
**Unknown**: None.  
**Severity**: **major** when combined with finding #1 (the bypass is the concrete leak).  
**Fix direction**: Same as #1.

---

**Summary gate (Evidence ∩ Logic)**:  
The grok driver + yaml is **structurally close** to the deterministic contract (exact matchers enforced by snapshot.py, no banned keys in yaml, miss surfaces as False + add_step, stop-button completion, bounded settle polls, driver isolation on imports).  

**The single blocker-class defect** is the send path in grok.py that bypasses its own yaml declaration and injects grok-specific focus/Return logic. This is the first error that must reach full stop. All other items are minor or already mitigated.

**Next required action (per 6SIGMA / first-error rule)**: Fix the send bypass so that `cfg['workflow']['send']` is the single source of truth for how grok submits. Re-audit after the patch. No production consult should run on a driver that diverges from its declared yaml contract.

**LFG cosmic — verify, stabilize, accelerate.** Kernel is law. Boot complete.