Based on an adversarial audit of the `consultation_v2` engine against the binding `00_RULES_contract.md`, the platform implementations are riddled with structural compromises. The engine systematically disobeys exact-match constraints, swallows misses via silent downgrades, gates completion on banned positive markers, and defies your explicit rulings on generation races.

Internal `# lint-allow: known debt` comments do not exempt the engine from physical rules. Here is every finding, grounded directly in the contract.

---

### 1. YAML Element Name/Role NOT Matching the Live Tree Map

*Rule broken: "Exactly one node by {stable locator + role}... The map is finite, known, and complete."*

* **Perplexity: Toggle vs. Push Button Mismatch**
* **File:** `perplexity.yaml` (`deep_research_toggle`)
* **Finding:** Mapped as `role: push button`. The live AT-SPI scan explicitly captures this as a `toggle button`. A strict exact-match will fail.


* **Perplexity: Unmapped Driver Element**
* **File:** `perplexity.py` (`_dr_select_all_copy`)
* **Finding:** The driver searches for `self.find_first(snap, 'response_body')`. The key `response_body` is completely absent from `perplexity.yaml`. A driver cannot invent keys; it will systematically miss.


* **ChatGPT: Menu Item Roles**
* **File:** `chatgpt.yaml` (`model_instant` through `model_pro`)
* **Finding:** Mapped as `role: menu item`. The live `:2` scan explicitly defines these as `radio menu item`. Exact mapping will fail.


* **Gemini: Exact String Mismatch**
* **File:** `gemini.yaml` (`mode_fast` and `mode_thinking`)
* **Finding:** Mapped exactly as `name: 3.5 Flash` and `name: 3.5 Thinking`. The live scan states their true names are `3.5 Flash All-around help New` and `3.5 Thinking Solves complex problems`.



### 2. Fallback / Downgrade / Fuzzy Locators / Silent-Proceed

*Rule broken: "NEVER guess/downgrade/fuzzy/fallback/silent-proceed — a miss must notify+HALT... ELEMENT-DRIVEN only never coordinates."*

* **Fuzzy Locators in YAML (Engine-Wide)**
* **Files:** `chatgpt.yaml`, `gemini.yaml`, `perplexity.yaml`
* **Finding:** The engine is flooded with banned fuzzy locators: `name_contains: Stop`, `name_pattern: '*, click to remove'`, `name_pattern: "palios-taey/*"`, `url_contains: /computer/`. Banned outright.


* **Python Substring Matching in Core Validation**
* **File:** `base.py` (`validation_passes`)
* **Finding:** The `file_chip` logic executes `if any(probe and probe in name for probe in probes):`. Using Python's `in` operator to validate control locators violates the ban on substring matching.


* **Silent Downgrades on Unmapped Modes/Models**
* **Files:** `chatgpt.py`, `gemini.py`, `perplexity.py` (`select_model_mode_tools`)
* **Finding:** If a requested model or mode is unmapped or fails to match, all three drivers fall through to an `else:` block, log `"left unchanged/default"`, and **return `True**`. If the map drifts, the engine silently executes on the wrong model instead of halting.


* **Explicit "Proceed on Miss" in YAML (`best_effort`)**
* **File:** `chatgpt.yaml` (`validation: instant_active` / `thinking_active`)
* **Finding:** Explicitly applies `best_effort: true` to bypass halting if the indicator misses. Designing a proceed-on-miss loophole into the deterministic schema subverts the engine's core invariant.


* **Silent Proceed on Extraction Misses**
* **Files:** `gemini.py`, `perplexity.py` (`extract_additional`)
* **Finding:** Both drivers return `True` and proceed if `share_export` or `copy_contents_button` are missing, swallowing the drift instead of halting.


* **Banned Coordinate Driving**
* **Files:** `grok.yaml` (`imagine` block), `grok.py`
* **Finding:** Uses `coordinate_fallback: x: 960, y: 940` and executes a `strategy='coordinate_only'` click. The rules dictate if it is AT-SPI invisible, it is out of scope. Coordinates are strictly banned.



### 3. Completion Gated on a Positive Marker Instead of Stop-Gone

*Rule broken: "There is no reliable positive completion indicator... The completion SIGNAL stays Stop-gone."*

* **Gating Send Confirmations on Positive Markers**
* **Files:** `chatgpt.py`, `perplexity.py` (`_send_confirmed`)
* **Finding:** Both drivers gate send success on `snap.has('stop_button') or snap.has('copy_button')`. Gemini gates on `or snap.has('start_research')`. Accepting positive markers illegally overrides the absolute stop-gone transition.


* **Missing Exception State Validation**
* **File:** `base.py` (`validation_passes` for `stop_absent`)
* **Finding:** It simply returns `True` if the stop button vanishes. It executes zero checks for mapped error screens (`auth_wall`, `rate_limited`, `content_filter`). A rate-limit modal that vanishes the Stop button will silently register as a successful completion.


* **Missing Generation Watchdog (Silent Infinite Stall)**
* **Files:** All YAMLs and Driver `monitor_generation` blocks.
* **Finding:** The contract explicitly requires a YAML-defined `generation_timeout` and a mapped `generation_stalled` state. None of the YAMLs declare this. The drivers wait on the global `request.timeout`, guaranteeing a silent infinite stall if generation hangs natively.



### 4. Path Where Drift Could MIS-ACT (Send-Without-Confirm)

*Rule broken: "Submit succeeded = new URL on a new chat AND the Stop button appeared... If the Stop button is not detected after a send, that is a real failure to INVESTIGATE."*

* **Defying the "AND" Rule for Fast-Replies**
* **Files:** `chatgpt.py` (Line 275), `grok.py` (Line 269)
* **Finding:** Both drivers evaluate new session sends via an `OR` condition (`url_changed or stop_seen`). Grok explicitly defies the Jesse ruling in its comments: *"the stop button is a bonus signal... fast replies clear it early."* The rule strictly demands `AND`. An `OR` risks mis-acting by hallucinating a successful send based purely on background URL drift.


* **Automatic Post-Send Clicks**
* **File:** `gemini.py` (`send_prompt`)
* **Finding:** If the engine sees a `start_research` button instead of a Stop button after sending, it automatically executes `self.runtime.click(start_button)`. If the UI drifted and this button is actually a Terms of Service or billing warning, the engine irreversibly clicks it without fleet confirmation.


* **Unacked Fleet-Notify**
* **File:** `notify.py` (`push_notification`)
* **Finding:** Blindly fires `r.rpush` and returns `True`, swallowing exceptions. The contract states: "An unacked notify into the void is a silently-swallowed miss at the single chokepoint — forbidden."



### 5. Path Reaching SEND with No Halt-able Checkpoint

*Rule broken: "Any path reaching SEND with no halt-able checkpoint."*

* **Dead Validation Logic Permitting Send-Without-Confirm**
* **Files:** `grok.yaml` (Line 103), `base.py` (Line 47)
* **Finding:** `grok.yaml` relies on `send_fired: stop_present: stop_button` to validate that a prompt was successfully sent. However, `validation_passes` in `base.py` **only implements `stop_absent**`. It completely ignores the `stop_present` key. The check falls through and returns `True`, allowing the driver to reach the monitor phase even if the send action completely failed to trigger the generation state.


* **Ignored Prompt-Ready Checks**
* **Files:** `perplexity.py` (Line 746), `grok.py` (Line 238)
* **Finding:** Both drivers' `enter_prompt` functions unconditionally return `bool(pasted)` or `True` immediately after pasting text. They completely ignore evaluating the `validation_passes(verify_snap, 'prompt_ready')` check mapped in their YAMLs. If the UI is stalled or the text didn't land, they dive straight into `send_prompt` with no halt-able checkpoint.