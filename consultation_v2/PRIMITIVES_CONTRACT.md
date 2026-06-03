# Shared-Primitive Contract — consultation_v2 (p0-primitives, LOCKED)

> **The contract:** the shared core contains ZERO platform knowledge. No platform
> name string (`chatgpt`/`claude`/`gemini`/`grok`/`perplexity`), no `if platform ==`,
> no platform→key/url/selector dict lives in a shared module. Platform is only ever a
> **parameter** used to load that platform's YAML; every platform-specific datum lives
> in the per-platform YAML and is reached through `load_platform_yaml(platform)`.
> A primitive takes an `ElementRef`, a raw string/key, or a match-argument — never a
> platform name to branch on.
>
> Grounded against live code at the commit that lands this file. File:line citations
> are real (verified by grep, not claimed). This is the reference p0-yaml-schema and
> every p1 driver are built against.

---

## 1. THE LOCKED PRIMITIVE SURFACE (platform-agnostic — these stay shared)

### `consultation_v2/types.py` — pure data, no logic
`ConsultationRequest`, `ConsultationResult`, `ElementRef`, `Snapshot`, `ExtractedArtifact`,
`StepRecord`. No platform strings. ✓ Already clean.

### `consultation_v2/runtime.py` — `ConsultationRuntime` interaction primitives
All operate on an `ElementRef`, a raw key/text, or a predicate — none branch on platform:
- `click(element, strategy=None)` — click an `ElementRef` (xdotool/atspi strategies)
- `press(key)`, `paste(text)`, `type_text(text, delay_ms)`, `read_clipboard()`, `write_clipboard(text)`
- `wait_until(predicate, timeout, interval)`, `wait_for_url_change(prev, ...)`
- `snapshot()` / `menu_snapshot()` — delegate to `build_snapshot(platform)` (platform is a param)
- `current_url()`, `navigate(url, verify_change)` — `navigate` reads `navigation_key` from cfg ✓ (YAML-driven, not hardcoded)
- `close_stale_dialogs()`, `focus_file_dialog()` — GTK dialog titles (`File Upload`/`Open`/`Open File`) are **toolkit-universal**, not platform-specific ✓
- `switch()` — delegates to `inp.switch_to_platform` + `atspi.find_firefox_for_platform` (see §2.D: the *mechanism* is primitive, the *datum* must move to YAML)

### `core/` low-level primitives (genuinely agnostic)
- `core/clipboard.py` — `read()`, `write()` ✓
- `core/input.py` — `press_key`, `type_text`, `click_at`, `clipboard_paste`, `focus_firefox` ✓ (`switch_to_platform` is the registry exception, §2.D)
- `core/interact.py` — `atspi_click(element_dict)` ✓
- `core/tree.py` — `find_elements`, `find_menu_items` — pure tree walkers ✓
- `core/atspi.py` — `find_firefox_for_platform`, `get_platform_document`, `get_document_url`: the **walk-windows / match-document / read-url MECHANISM** is primitive; the platform→URL **datum** it consumes is not (§2.D)

### `consultation_v2/snapshot.py` — classify mechanics
- `build_snapshot`, `build_menu_snapshot`, `_classify_elements`, `_to_ref`, `_is_excluded` — agnostic mechanics ✓
- `matches_spec()` — **the matcher. Surface stays shared; its BEHAVIOR must change in p0-yaml-schema** (see §3 — it currently accepts loose matchers, which is the leak).

### `consultation_v2/yaml_contract.py` — `load_platform_yaml(platform)` — agnostic loader ✓
### `consultation_v2/drivers/base.py` — `BaseConsultationDriver` (`find_first`, `find_last`, `validation_passes`, `serialize_artifacts`) — shared base; `validation_passes` BEHAVIOR must change in p0-yaml-schema (§3).

---

## 2. PLATFORM KNOWLEDGE THAT MUST LEAVE SHARED CODE (the leak inventory — real file:line)

> Each item is platform data or a platform branch sitting in a shared module. Per THE RULE
> it must move into the per-platform **YAML** (data) or the per-platform **driver** (behavior).

### A. `core/mode_select.py` (686 lines) — the shared-branch anti-pattern, dissolve entirely into drivers
- `:102` `if platform == 'grok' and target_mode_lower == 'heavy':` (skip-selector)
- `:144` `if platform == 'grok' and not trigger:`
- `:380-384` platform→selector-key dict (`chatgpt/claude/grok/perplexity`→`model_selector`, `gemini`→`mode_picker`)
- `:399` `if platform == 'claude' and element_key == 'model_selector':`
- `:411` `if platform == 'gemini' and element_key == 'mode_picker':`
- `:548` `if platform == 'chatgpt' and select_target == 'extended':`
→ **DESTINATION:** each driver's own `select_mode()` reading its own YAML `workflow.mode_targets`. No shared mode_select. (Removed at p2-delete-shared-branches once all p1 drivers exist.)

### B. `core/config.py:75-108` — platform→element-key dicts in shared code
- `:75-79` attach-trigger key per platform
- `:104-108` upload-item key per platform
→ **DESTINATION:** each YAML names its own attach/upload keys; driver reads them. No cross-platform dict.

### C. `scripts/consultation.py` — live-path platform branches (the path currently in production)
- `:439` `if platform == 'grok':` · `:568/:571` perplexity/gemini · `:918` chatgpt · `:926/:935` claude send · `:1603` perplexity mode
→ **DESTINATION:** dissolve into per-platform drivers; the live entrypoint dispatches to the driver (p2-make-live).

### D. `core/platforms.py:56-94` + `core/atspi.py:17,143-146` — window/document resolution registry
- `core/platforms.py`: `NAV_KEYS`/alt+N (`:56-60`), `_EXTRA_URL_PATTERNS={'grok':'x.com/i/grok'}` (`:67`), `URL_PATTERNS` domains (`:69-71`), `DEFAULT_URLS` (`:83-87`), `CHAT_PLATFORMS` (`:94`)
- `core/atspi.py:17` imports `URL_PATTERNS,_EXTRA_URL_PATTERNS`; `:143-146` loops them to pick the Firefox window/document
→ **THE NUANCE (cannot-lie):** finding "which Firefox is this platform's window" inescapably needs a platform→URL datum somewhere. RULE-compliant shape: the **datum is a `url_match:` field in each per-platform YAML**; the primitive becomes `find_firefox_by_url_match(url_match)` taking the string as an argument. Mechanism stays primitive, data moves to YAML. (No alt+N tab-switching at all under the per-supervisor/one-window model, p3 — `NAV_KEYS` becomes dead.)

### E. `core/ax_browser.py:423-425` — platform→search-token map (same class as D; legacy/MCP path)

### F. Two-config-tree trap (task #171) — `core/config.py:20` `PLATFORMS_DIR = <repo>/platforms`
Live path reads **root** `platforms/*.yaml`; v2 reads `consultation_v2/platforms/*.yaml`. The
isolated drivers must read ONE tree (`consultation_v2/platforms/`); the root tree is deleted at p2-make-live.

---

## 3. THE MATCHER LEAK (why the YAMLs are "full of name_contains") — fixed in p0-yaml-schema, noted here

The "isolated" matcher itself invites loose matchers, so the YAMLs filled with them:
- `consultation_v2/snapshot.py:35-54` `matches_spec()` accepts `name_contains`, `name_not_contains`,
  `name_contains_all`, `name_pattern` (fnmatch **wildcards**), `role_contains`.
- `consultation_v2/snapshot.py:75` `_is_excluded` accepts `name_contains` for the exclude set.
- `consultation_v2/drivers/base.py:35` `validation_passes` matches via `url_contains`; `:56-79`
  file-chip via substring `probe in name` (a contains, not a structural locator).

**p0-yaml-schema target shape (the lock this contract sets up):**
- `matches_spec` accepts ONLY: exact `name` (verbatim) + exact `role` + `states_include`.
- The single dynamic exception is a typed `structural:` locator — exact `role` + exact `parent`
  key + integer `index`/`ordinal` — for inherently-dynamic leaves (file chips with timestamped
  names, response text, generated ids). Only the leaf text varies; the locator is itself exact.
- Every other key (`name_contains`/`name_pattern`/`role_contains`/`url_contains`/`fuzzy`/…) is
  REJECTED at load (runtime assert) AND blocked at commit (`tools/lint_exact_match.py`, already
  wired into `.githooks/pre-commit`). The rule cannot regress.
- Validation is read from the live AT-SPI tree for an exact element+state — never a screenshot-as-truth,
  never a substring.

---

## 4. ACCEPTANCE OF p0-primitives
- [x] Locked primitive surface enumerated (§1) — every entry verified platform-agnostic against live code.
- [x] Every platform-knowledge leak in shared code inventoried with real file:line (§2 A–F) + destination.
- [x] The one unavoidable nuance (window/document resolution datum) stated honestly with its RULE-compliant shape (§2.D).
- [x] The matcher leak that the lint already guards is documented as the p0-yaml-schema handoff (§3).
- This is inventory+lock. No code moved here. Matcher rewrite = p0-yaml-schema; code relocation = p1 (per platform) + p2 (delete shared branches).
