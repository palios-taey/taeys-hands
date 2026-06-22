**NO ENDORSEMENT.**

FULL CODE AUDIT REPORT: The implementation profoundly violates the `CONSULTATION_CONTRACT.md` and `100_TIMES.md` strict determinism invariants. It contains banned fuzzy matchers, illegal fallback chains, single-shot race conditions, and massive abstraction leaks.

### 1. EXACT-MATCH YAML BANS

**Observed** — `consultation_v2/platforms/gemini.yaml:34` — Uses `name_contains` under `exclude: name_contains: [- Gemini Apps Activity, ...]`.

* **Severity**: BLOCKER
* **Fix Direction**: The contract categorically bans `name_contains`, substring, and fuzzy matching anywhere in the map. Remove it and map the exact names or structural exclusions.

**Observed** — `consultation_v2/platforms/gemini.yaml:44` — `input_alt` uses an empty string `name: ""` combined with `role: section` and `states_include: [editable]`.

* **Severity**: BLOCKER
* **Fix Direction**: This is a banned presence-only/wildcard matcher. Map the exact AT-SPI name/role.

**Observed** — `consultation_v2/platforms/gemini.yaml:49` and `gemini.yaml:253` — `mode_picker` and `pro_active` use the intrinsically dynamic visible name `name: "Open mode picker, currently Pro"`.

* **Severity**: BLOCKER
* **Fix Direction**: The contract states: "Locate by a STABLE key, not an intrinsically-dynamic visible name (the model-picker's name == the selected model)". Remap to a stable structural path or attribute.

**Observed** — `consultation_v2/platforms/gemini.yaml:157` — Declares an explicit `input_fallback: input_alt`.

* **Severity**: BLOCKER
* **Fix Direction**: The invariant is "Never guess, downgrade, or fall back." Remove the fallback key entirely.

**Unknown** — `consultation_v2/platforms/gemini.yaml:53` — `tools_button` mapped to `name: Upload & tools`.

* **Severity**: MAJOR
* **Fix Direction**: Live Gemini UI frequently replaces this text with a simple `+` icon or changes copy. Given exact-match rules, this has high likelihood of immediate drift.

### 2. MATCH-OR-NOTIFY (NO RETRIES/FALLBACKS)

**Observed** — `consultation_v2/drivers/gemini.py:111` — Executes an explicit retry on a miss: `retry_trigger = self.find_first(retry_snap, 'upload_menu') or trigger` -> `clicked = self.runtime.click(retry_trigger, strategy='coordinate_only')`.

* **Severity**: BLOCKER
* **Fix Direction**: `100_TIMES.md` §4a mandates: "A failed ACTION... is retried EXACTLY ZERO times." Remove the retry loop and the banned `coordinate_only` downgrade. Surface the miss.

**Observed** — `consultation_v2/drivers/gemini.py:146-149` — Implements a chained downgrade: `if not self.runtime.paste(abs_path): if not self.runtime.type_text(...)`.

* **Severity**: MAJOR
* **Fix Direction**: Try-then-fallback chains are banned. Commit to one deterministic method (paste or type_text) and return `False` if it fails.

**Observed** — `consultation_v2/drivers/gemini.py:303-306` — Silently proceeds on a miss in `extract_additional`: `if not copy_item: result.add_step(..., True, '... Copy Content item was not exposed'); return True`.

* **Severity**: BLOCKER
* **Fix Direction**: Contract: "No silent proceed on miss. A miss is surfaced, never swallowed." Return `False` to trigger a NOTIFY.

**Inferred** — `consultation_v2/drivers/gemini.py:141-143` — The driver presses `Ctrl+L` and immediately pastes without clearing the field.

* **Severity**: MAJOR
* **Fix Direction**: Per `100_TIMES.md` §8c, GTK's location-bar typeahead will auto-complete and select the wrong file if `Ctrl+A` is omitted before typing/pasting. Add `Ctrl+A`.

### 3. COMPLETION = STOP-BUTTON ONLY

**Observed** — `consultation_v2/platforms/gemini.yaml:182` — Defines `complete_key: copy_button` in the `monitor` block.

* **Severity**: BLOCKER
* **Fix Direction**: Contract: "COMPLETION = stop-button disappearance ONLY (no positive marker)." Delete `complete_key`.

**Observed** — `consultation_v2/drivers/gemini.py:196-218` — The `send_prompt` method injects a 180-second `wait_until` polling loop waiting for the `start_research` button.

* **Severity**: BLOCKER
* **Fix Direction**: `send_prompt` holds the cross-session dispatch lock (FLOW §10). Blocking for 3 minutes for a positive UI marker kills concurrency and evades the generation monitor's Stop-button watchdog. This multi-step flow belongs in the unlocked extraction/monitor phase, driven by the Stop button signal.

### 4. ROBUSTNESS — SINGLE-SHOT CHECKS

**Observed** — `consultation_v2/drivers/gemini.py:238` — In `extract_primary`, fires an immediate snapshot: `snap = self.runtime.snapshot(); share = self.find_first(snap, 'share_export')` the millisecond `monitor_generation` unlocks.

* **Severity**: BLOCKER
* **Fix Direction**: Races the Deep Research canvas render. Add a settle window and rescan.

**Observed** — `consultation_v2/drivers/gemini.py:283` — In `extract_additional`, fires an immediate single-shot check `share_export = self.find_first(snap, 'share_export')` with zero settle time.

* **Severity**: BLOCKER
* **Fix Direction**: Same race condition. Settle and rescan.

**Inferred** — `consultation_v2/drivers/gemini.py:161` — `enter_prompt` executes a single-shot check for the `input` field right after `attach_files` yields.

* **Severity**: BLOCKER
* **Fix Direction**: `attach_files` ends by hitting Enter to close a GTK modal. Polling the AT-SPI tree instantly races the window manager refocus. Needs a `wait_for_key` or settle.

### 5. DRIVER ISOLATION

**Observed** — `consultation_v2/drivers/gemini.py:11` — Direct cross-boundary import: `from storage import neo4j_client`. Implemented via `store_in_neo4j` (lines 316-339).

* **Severity**: BLOCKER
* **Fix Direction**: Contract: "Drivers carry zero platform knowledge; they call shared primitives only." Strip graph storage from the UI driver; the engine/runtime must handle persistence.

**Observed** — `consultation_v2/drivers/gemini.py:196, 236, 280` — The Python driver is infested with hardcoded strings: `if str(request.selection_value('mode'...)) == 'deep_research':`, executing custom click workflows.

* **Severity**: BLOCKER
* **Fix Direction**: The driver acts with explicit platform knowledge, bypassing the declarative `extraction: research_report` state machine already defined in `gemini.yaml:283-291`. Remove the python branching and rely strictly on the generic YAML extraction execution engine.

### 6. CONTRACT / PRECONDITIONS

**Observed** — `consultation_v2/drivers/gemini.py:255` — Extraction executes `copy_button = self.find_last(snap, 'copy_button')`.

* **Severity**: MAJOR
* **Fix Direction**: `100_TIMES.md` §2 strictly mandates taking the lowest button geometrically: "Take max(copy_btns, key=y)". `find_last` blindly trusts AT-SPI tree order. The YAML already defines `strategy: last_by_y` (`gemini.yaml:186`); the Python driver overrides and ignores it. Implement spatial sorting.

**Observed** — `consultation_v2/platforms/gemini.yaml:202` — `attach_success` validation verifies only `file_chip: roles: [section]`.

* **Severity**: BLOCKER
* **Fix Direction**: `100_TIMES.md` §8c mandates validating the exact attached filename to prevent the GTK wrong-file trap. A generic role check fails this invariant. Map the actual filename property.