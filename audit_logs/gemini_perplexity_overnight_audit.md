# OVERNIGHT AUDIT REPORT: GEMINI & PERPLEXITY CONSULT ENGINES

* **Date**: Thursday, June 18, 2026
* **Session/Author**: Cosmos (Gemini CLI fleet peer `taeys-hands-gemini`)
* **Branch**: `peer/taeys-hands-codex-chatgpt-nested-models`
* **Commit**: `d51e0e5` (ChatGPT gold-standard)
* **Status**: STATIC AUDIT COMPLETE (Rebuild Worklist Generated)

---

## 3-REGISTER TRUTH DESIGNATION

* **OBSERVED**: Direct facts verified by static line-by-line inspection of files within `<OPERATOR_HOME>/.peer-worktrees/taeys-hands-gemini/`.
* **INFERRED**: Deductions made from architectural patterns in `yaml_contract.py` and the reference implementation of `chatgpt.yaml` / `chatgpt.py`.
* **UNKNOWN**: Gaps where live AT-SPI properties or runtime UI element changes could not be verified without executing the active interface.

---

## SECTION 1: GEMINI REBUILD WORKLIST

### 1. Forbidden Constructs

#### A. Platform YAML (`consultation_v2/platforms/gemini.yaml`)
* **`name_contains` in Exclusions [OBSERVED]**
  - **Line 13**: `name_contains:` is used inside the `tree.exclude` filter block:
    ```yaml
    name_contains: # lint-allow: known p1 debt; sidebar/noise exclusions still rely on substring until exact live map rewrite
    - Gemini Apps Activity
    - Manage extensions
    - ', Google Account'
    - tap to use tool
    ```
    *Strict schema violation*: Under `identity_v1`, substring filtering via `name_contains` is entirely forbidden. Exclusions must be mapped exactly or pruned structurally.
* **`names_any_of` in Element Map [OBSERVED]**
  - **Line 131**: Mapped under `mode_pro` in the `element_map`:
    ```yaml
    mode_pro:
      names_any_of:
        - "3.1 Pro Advanced math and code"
        - "Selected 3.1 Pro Advanced math and code"
      role: menu item
    ```
    *Strict schema violation*: `names_any_of` is forbidden for elements in `element_map` under `identity_v1`. Selection targets must use exact static names with active status verified live via the element's `active_state` recognition rule.
* **`states_include` in Element Map [OBSERVED]**
  - **Line 41**: Under `input`:
    ```yaml
    states_include:
    - editable
    ```
  - **Line 46**: Under `input_alt`:
    ```yaml
    states_include:
    - editable
    - focusable
    ```
    *Strict schema violation*: Element map mappings under `identity_v1` are limited to `name`, `role`, `scope`, and `active_state`. The use of `states_include` is forbidden.
* **`# lint-allow` Debt Comments [OBSERVED]**
  - **Line 13**: `# lint-allow: known p1 debt; sidebar/noise exclusions still rely on substring until exact live map rewrite`
  - **Line 50**: `# lint-allow: known p5 debt; dynamic-name mode picker needs structural/stable locator remap`
  - **Line 244**: `# lint-allow: known p5 debt; dynamic-name active-state validation needs structural/stable locator remap`
    *Strict schema violation*: All `# lint-allow` escape hatches are strictly forbidden under the `identity_v1` schema loader and will trigger build failures.
* **The Entire `validation:` Section [OBSERVED]**
  - **Lines 208–264**: The entire `validation:` block is mapped:
    ```yaml
    validation:
      attach_success: ...
      prompt_ready: ...
      send_success: ...
      response_complete: ...
      fast_active: ...
      thinking_active: ...
      pro_active: ...
      deep_think_active: ...
      deep_research_active: ...
      canvas_active: ...
    ```
    *Strict schema violation*: Under `identity_v1`, the `validation:` block is completely deleted. All validation shifts to live checked-state and accessibility property queries.

#### B. Driver validations (`consultation_v2/drivers/gemini.py`)
* **Named Validation Calls [OBSERVED]**
  - The driver contains **16 matches** of `wait_for_validation` and `validation_passes` across the following lines:
    - **Line 135 & 141**: Verifying requested model via `{requested_model}_active`.
    - **Line 158**: Checking if `{requested_mode}_active` is already true.
    - **Line 202 & 207**: Waiting and validating mode active key.
    - **Line 217 & 223**: Waiting and validating mode active key inside tools portal.
    - **Line 276 & 277**: Waiting and validating tool activation key.
    - **Line 287**: Pre-checking if validation key is already active.
    - **Line 355 & 361**: Verifying file attachment success via `attach_success`.
    - **Line 387 & 392**: Verifying prompt-ready via `prompt_ready`.
    - **Line 448 & 449**: Verifying generation start via `send_success` Stop-button check.
    *Strict schema violation*: Drivers in the `identity_v1` paradigm must read the live AT-SPI checked or pressed states of elements mapped with an `active_state` recognition rule, completely bypassing dynamic validation queries.

---

### 2. Deviations from ChatGPT Gold-Standard (States-Live, Identities-Only)
* **No `schema: identity_v1` Specification [OBSERVED]**
  - `gemini.yaml` is missing the `schema: identity_v1` header and `tree: schema: identity_v1` mapping, rendering it legacy.
* **Absence of `active_state` Mappings [OBSERVED]**
  - Mapped elements (like `mode_fast`, `mode_thinking`, `mode_pro`, and all tools) are completely missing the `active_state: checked` property (such as used in `chatgpt.yaml` for active indicator detection).
* **Hardcoded Menu-Expansion Logic [INFERRED]**
  - The traversal of the "More tools" flyout submenu in `gemini.py` (Lines 178–185) is hardcoded procedurally rather than using the standard YAML-declarative `via` / `via_action` navigation workflow used in `chatgpt.yaml`.

---

### 3. Structural Gaps
* **Unmapped Nested Menu Traversal [OBSERVED]**
  - "Deep Think" and "Guided learning" live inside the "More tools" secondary expandable flyout under the "Upload & tools" menu. This nested layout is procedurally hacked around instead of mapped structurally.
* **Unmapped Workspace/Sharing Integrations [INFERRED]**
  - The "Share & Export" popover contains Workspace-integrated menu items like "Export to Docs" and "Draft in Gmail." These are completely unmapped in `gemini.yaml`.
* **Unmapped Sidebar Context Actions [INFERRED]**
  - Actions like "Rename chat", "Delete chat" inside the sidebar context menus are missing.
* **Unmapped Project Creation & Workspace Management [INFERRED]**
  - The "Projects" trigger on the sidebar is mapped, but all inner page controls for managing/creating project canvases are unmapped.

---
---

## SECTION 2: PERPLEXITY REBUILD WORKLIST

### 1. Forbidden Constructs

#### A. Platform YAML (`consultation_v2/platforms/perplexity.yaml`)
* **`name_contains` in Exclusions [OBSERVED]**
  - **Line 13**: `name_contains:` is used inside the `tree.exclude` filter block:
    ```yaml
    name_contains: # lint-allow: known p1 debt; sidebar/noise exclusions still rely on substring until exact live map rewrite
    - Upgrade to Pro
    - ', open profile menu'
    - User avatar Jesse
    ```
    *Strict schema violation*: Substring filtering via `name_contains` is forbidden under `identity_v1`. Exclusions must be exact or pruned structurally.
* **`names_any_of` in Element Map & Validators [OBSERVED]**
  - **Line 221**: Mapped under `stop_button` in the `element_map`:
    ```yaml
    stop_button:
      names_any_of:
      - Stop response (Esc)
      - Stop response
      role: push button
    ```
  - **Line 340**: Mapped under `send_success.indicators` in the `validation` section:
    ```yaml
    - names_any_of:
      - Stop response (Esc)
      - Stop response
    ```
    *Strict schema violation*: `names_any_of` is forbidden inside elements/validators under `identity_v1`. Elements must map to exact static names with active status verified live via the element's `active_state` recognition rule.
* **`states_include` in Element Map [OBSERVED]**
  - **Line 44**: Under `input`:
    ```yaml
    states_include: [editable]
    ```
  - **Line 49**: Under `input_message`:
    ```yaml
    states_include: [editable]
    ```
  - **Line 92**: Under `deep_research_toggle`:
    ```yaml
    states_include: [pressed]
    ```
  - **Line 97**: Under `search_mode_trigger`:
    ```yaml
    states_include: [pressed]
    ```
  - **Line 156**: Under `search_sources`:
    ```yaml
    states_include: [editable]
    ```
    *Strict schema violation*: Element map mappings under `identity_v1` are limited to `name`, `role`, `scope`, and `active_state`. The use of `states_include` is forbidden.
* **`# lint-allow` Debt Comments [OBSERVED]**
  - **Line 13**: `# lint-allow: known p1 debt; sidebar/noise exclusions still rely on substring until exact live map rewrite`
  - **Line 348**: `# lint-allow: known p1 debt; URL gate still reflects the live /computer/ area until exact route key lands`
    *Strict schema violation*: All `# lint-allow` comments are forbidden under `identity_v1` and will trigger build failures.
* **`url_contains` under `computer_active` Validator [OBSERVED]**
  - **Line 348**: `url_contains` is a forbidden matcher key under the strict `identity_v1` schema. URL gates are not valid tree validators.
* **The Entire `validation:` Section [OBSERVED]**
  - **Lines 322–365**: The entire `validation:` block is mapped:
    ```yaml
    validation:
      attach_success: ...
      prompt_ready: ...
      send_success: ...
      response_complete: ...
      computer_active: ...
      deep_research_active: ...
      model_council_active: ...
      create_files_and_apps_active: ...
      learn_step_by_step_active: ...
    ```
    *Strict schema violation*: Under `identity_v1`, the `validation:` block is completely deleted. All validation shifts to live checked-state and accessibility property queries.

#### B. Driver validations (`consultation_v2/drivers/perplexity.py`)
* **Named Validation Calls [OBSERVED]**
  - The driver contains **13 matches** of `wait_for_validation` and `validation_passes` across the following lines:
    - **Line 92 & 93**: Waiting and validating prompt-ready via `prompt_ready`.
    - **Line 150 & 155**: Waiting and validating requested model via `{requested_model}_active`.
    - **Line 174**: Checking if `{requested_mode}_active` is already true.
    - **Line 319 & 323**: Verifying mode activation key.
    - **Line 495**: Pre-checking if validation key is already active.
    - **Line 520**: Checking validation key on last snapshot.
    - **Line 838 & 844**: Verifying file attachment success via `attach_success`.
    - **Line 962 & 967**: Verifying generation start via `send_success` Stop-button check.
    *Strict schema violation*: Drivers in the `identity_v1` paradigm must read the live AT-SPI checked or pressed states of elements mapped with an `active_state` recognition rule, completely bypassing dynamic validation queries.

---

### 2. Deviations from ChatGPT Gold-Standard (States-Live, Identities-Only)
* **No `schema: identity_v1` Specification [OBSERVED]**
  - `perplexity.yaml` is missing the `schema: identity_v1` header and `tree: schema: identity_v1` mapping, rendering it legacy.
* **Absence of `active_state` Mappings [OBSERVED]**
  - Mapped elements (like modes and tools) are completely missing the `active_state` property (such as used in `chatgpt.yaml` for active indicator detection).
* **Procedural Sub-menu Traversal [INFERRED]**
  - In `perplexity.py`, sub-menu modes are handled by custom YAML fields (`mode_submenu_keys` inside `workflow`) and custom python functions like `_select_mode_via_submenu` rather than utilizing the standard declarative `via` nested menu scheme.

---

### 3. Structural Gaps
* **Completely Empty `model_targets` Mapping [OBSERVED]**
  - Under `workflow.selection.model_targets` (Line 277 of `perplexity.yaml`), the dictionary is completely empty. Model selection is impossible in the current YAML layout:
    ```yaml
    # model_targets: empty until live AT-SPI scan of model selector dropdown
    # is available with exact [radio menu item] names.
    model_targets: {}
    ```
* **Unmapped Cloud Connectors [INFERRED]**
  - Standard Perplexity connectors like Notion, Slack, Google Drive, OneDrive, and Jira are omitted from the cloud service connector definitions.
* **Unmapped Contextual Thread Actions [INFERRED]**
  - Contextual thread actions (e.g., Rename/Delete thread, Edit source, View sources) are completely unmapped.
