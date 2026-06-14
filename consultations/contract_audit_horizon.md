I read the contract as requiring a hard binary: exact YAML match by live AT-SPI tree, one settle/re-scan on miss, then NOTIFY+HALT; no fuzzy matching, no downgrade, no action retry, and “submit/generating/complete” keyed mainly to URL change plus Stop-button presence/absence. 

## P0 — holes that can produce wrong action, duplicate submission, or false completion

### 1. **Irreversible-action ambiguity: “re-run after YAML update” can duplicate a send**

**Break:** The contract bans retrying the action on a miss, but then says a human updates YAML and “re-run.” If the missed validation happened after an irreversible action, especially submit, the prompt may already have been sent even though the engine failed to observe `new URL + Stop`. Re-running from the same step can duplicate the prompt, create a second chat, or burn quota.

**Concrete amendment:** Add an **irreversible action barrier**.

```yaml
action_classes:
  reversible:
    examples: [open_menu, select_mode, attach_menu]
    on_validation_miss: notify_halt_resume_same_state_allowed
  irreversible:
    examples: [submit_prompt, send_file, delete_attachment, stop_generation]
    on_validation_miss: side_effect_uncertain_notify_halt
    auto_rerun: forbidden
    required_reconciliation:
      - capture_current_url
      - capture_transcript_message_count
      - capture_latest_user_message_exact_or_hash
      - capture_stop_state
      - operator_marks: [sent, not_sent, unknown]
```

Rule: after an irreversible action validation miss, the engine may not repeat that action until the live state is reconciled by exact mapped evidence or by operator-marked quarantine.

---

### 2. **“Stop gone = complete” is not sufficient**

**Break:** Stop disappearance can mean complete, but it can also mean request failed, rate-limited, disconnected, blocked by policy, paused into “Continue generating,” crashed, replaced by another progress control, or hidden due to accessibility lag. Absence alone is not a positive completion proof.

**Concrete amendment:** Replace `complete = Stop gone` with a positive completed-state spec:

```yaml
states:
  completed:
    required_present:
      - composer_ready.enabled
      - send_button.present_or_disabled_due_empty_input
      - assistant_response_container.present
      - latest_assistant_turn.stable_for_ms: 1500
    required_absent:
      - stop_button
      - generating_spinner
      - network_error_banner
      - rate_limit_banner
      - continue_generating_button
      - retry_button
      - captcha_or_auth_modal
```

Rule: Stop absence is necessary but never sufficient. Completion requires a mapped positive “ready for next prompt” state plus no mapped blocker/error/continuation state.

---

### 3. **Fast responses can skip observable “Stop present”**

**Break:** The contract says submit succeeded only if a new chat URL appears and Stop appears. A very fast response can complete between scans; the engine may never see Stop even though submission succeeded.

**Concrete amendment:** Add two accepted post-submit paths, both binary:

```yaml
post_submit_success:
  path_a_generating_observed:
    required: [new_chat_url, stop_button_appeared_event_or_state]
  path_b_fast_complete:
    required:
      - new_chat_url
      - latest_user_message_matches_submitted_payload
      - assistant_response_container.present
      - completed_state.matches
```

No guessing: if neither path matches, notify/halt. This keeps the model binary while avoiding a false drift on fast completions.

---

### 4. **Partial submit states are undefined**

**Break:** After clicking submit, the world can split into mixed states:

* URL changed, Stop absent.
* Stop present, URL unchanged.
* user message visible, no assistant response yet.
* Stop appeared then disappeared before the monitor observed it.
* platform creates chat only after first token.
* platform accepts the message in an existing empty-chat URL.

The current contract treats these as mismatch, but some are valid platform transitions.

**Concrete amendment:** Add an explicit `post_submit_transition_matrix`.

```yaml
post_submit_transition_matrix:
  url_changed_stop_present: generating
  url_changed_completed_state: fast_complete
  url_changed_error_banner: terminal_error
  stop_present_url_same:
    allowed_only_if: platform.submit_url_policy == "url_delayed"
    state: generating_pending_url
  user_message_visible_no_stop_no_response:
    state: accepted_pending_generation
    deadline_ms: 10000
  no_user_message_no_stop_no_url:
    state: submit_not_observed_notify_halt
```

Each row is exact and finite. No action retry.

---

### 5. **Auth/session expiry is not mapped as first-class state**

**Break:** A run can begin logged in and later hit sign-in, re-auth, account switcher, 2FA, CAPTCHA, Cloudflare/device check, subscription prompt, workspace selector, cookie banner, age gate, or “verify it’s you.” Underlying page controls may still exist in the tree, so the engine could match a composer behind a blocking modal.

**Concrete amendment:** Add a **blocking-state priority layer** evaluated before normal step validation.

```yaml
state_priority:
  1_blocking_modal_or_auth
  2_platform_error_or_rate_limit
  3_native_dialog
  4_expected_session_state

blocking_states:
  signed_out:
    exact_elements: [...]
    terminal: true
  session_expired:
    exact_elements: [...]
    terminal: true
  captcha_or_device_check:
    exact_elements: [...]
    terminal: true
  account_switcher:
    exact_elements: [...]
    terminal: true
```

Rule: if any blocking/auth state matches, it overrides the happy-path state and halts the platform.

---

### 6. **Rate limits, quota, model unavailable, and platform errors are not enumerated**

**Break:** The contract assumes “drift” is the only unknown. It is not. A live UI can exactly show “limit reached,” “model unavailable,” “try again later,” “something went wrong,” “message failed,” “server overloaded,” “network error,” or “refresh required.” These are not YAML drift; they are valid terminal states.

**Concrete amendment:** Add a required `terminal_platform_states` section per platform.

```yaml
terminal_platform_states:
  rate_limited:
    exact_elements: [...]
    notify_payload: [state_id, quota_text, platform, account_id_alias]
  model_unavailable:
    exact_elements: [...]
  message_failed:
    exact_elements: [...]
  network_disconnected:
    exact_elements: [...]
  service_overloaded:
    exact_elements: [...]
```

Rule: terminal platform states are matches, not mismatches. They notify and halt without asking a human to “update the exact value.”

---

### 7. **“Continue generating” / “Regenerate” / “Retry” states break completion**

**Break:** Stop gone plus a visible “Continue generating” means the answer is incomplete. “Regenerate” might mean complete, but “Retry” might mean failed. Some platforms expose a final answer with a continuation affordance after truncation.

**Concrete amendment:** Split post-generation into exact states:

```yaml
generation_end_states:
  complete:
    required_present: [assistant_response_container, composer_ready]
    required_absent: [continue_generating, retry, error_banner]
  incomplete_continue_available:
    required_present: [continue_generating]
    terminal_or_policy: notify_halt
  failed_retry_available:
    required_present: [retry_button_or_error_banner]
    terminal: true
  regenerate_available_complete:
    required_present: [regenerate_button, completed_state]
    classification: complete
```

Do not auto-click Continue or Retry unless the consultation protocol explicitly maps that as a separate irreversible action.

---

### 8. **Generated transcript content is unbounded, so “every other element exact” is impossible**

**Break:** The spec filters sidebar previous chats, but not the transcript. User prompts, assistant answers, citations, source cards, code blocks, file names, copy buttons, markdown links, and tool result panels are dynamic. A finite complete map cannot exact-match all of that.

**Concrete amendment:** Define **trusted chrome zones** and **dynamic content zones**.

```yaml
zones:
  trusted_controls:
    include_ancestor_paths:
      - app_root > header
      - app_root > composer
      - app_root > model_menu
      - app_root > tools_menu
    exact_match_required: true

  transcript_dynamic:
    include_ancestor_paths:
      - app_root > conversation_region
    exact_match_required: false
    allowed_validations:
      - latest_user_message_exact_or_hash
      - latest_assistant_turn_container_present
      - response_stable
    controls_inside_zone_are_untrusted_for_session_driving: true
```

Rule: session-driving controls must be matched only inside trusted scoped regions. Transcript content cannot satisfy “Stop,” “Send,” “Retry,” or model-selection locators.

---

### 9. **Name+role is under-specified; duplicates are inevitable**

**Break:** Exact name+role does not identify a unique actionable element. There may be multiple “Send” buttons, “Stop” buttons, “Copy” buttons, model names, menu items, or hidden/offscreen duplicates. Exact match with two candidates is not defined.

**Concrete amendment:** Define locator identity as exact **cardinality-one scoped path**, not just name+role.

```yaml
locator:
  id: submit_button
  scope: composer_region
  ancestor_chain:
    - {role: frame, name: ChatGPT}
    - {role: document, name: ""}
    - {role: section, name: composer}
  target:
    role: push button
    name: Send prompt
    states_required: [showing, visible, sensitive, enabled]
    actions_required: [press]
  cardinality: exactly_one
```

Rule: zero matches and multiple matches are both drift/notify. “Exact” must include scope, state, actionability, and uniqueness.

---

### 10. **Disabled vs enabled controls are not represented**

**Break:** A button can match exact name+role while disabled. Clicking it may do nothing, but the contract would say “match → proceed.”

**Concrete amendment:** Add state requirements to every actionable locator.

```yaml
actionable_requirements:
  required_states: [showing, visible, sensitive, enabled]
  forbidden_states: [defunct, stale, offscreen, obscured_if_detectable]
  required_actions: [press_or_click]
```

Rule: element present but disabled is a distinct mapped state, not a successful match.

---

### 11. **Native file picker and focus transfer are not covered**

**Break:** File upload often opens a native GTK/portal file chooser outside the browser document. Focus may move to a different window on the same X display. The browser AT-SPI tree can still look unchanged while the active window is the file dialog.

**Concrete amendment:** Add native-dialog state maps and display focus invariants.

```yaml
native_dialogs:
  file_chooser_open:
    window_role: dialog
    window_name_exact_by_locale: "Open File"
    required_controls:
      - path_entry
      - open_button
      - cancel_button
    active_window_required: true

upload_lifecycle:
  chooser_open
  file_selected
  upload_in_progress
  file_tile_visible
  upload_complete
  upload_rejected
```

Rule: “file tile visible” is not enough. Upload success requires the exact file tile plus no upload progress/error state.

---

### 12. **AT-SPI can expose stale, hidden, or no elements**

**Break:** The contract says nothing is hidden, but AT-SPI can expose offscreen/stale nodes, fail to expose canvas/shadow/iframe surfaces, or lag behind rendered UI. A surface may be visible but inaccessible, or accessible but not visible/actionable.

**Concrete amendment:** Add an accessibility preflight and liveness contract.

```yaml
accessibility_preflight:
  required:
    - app_window_exact
    - document_root_present
    - tree_node_count_min
    - known_persistent_control_present
    - snapshot_freshness_ms_max
  terminal_states:
    accessibility_tree_empty
    accessibility_tree_stale
    platform_surface_not_exposed
```

Rule: if the platform exposes nothing usable to AT-SPI, that is not drift to “fix” with a guessed click. It is a terminal `ACCESSIBILITY_UNAVAILABLE` match with notify/halt.

---

### 13. **One settle/re-scan is too crude for asynchronous transitions**

**Break:** The contract treats timing lag as one settle then re-scan. That works for a React portal opening; it does not work for navigation, upload processing, generation queueing, file scanning, or network reconnect. Those are real states, not tree-refresh lag.

**Concrete amendment:** Separate **UI-settle lag** from **async operation wait states**.

```yaml
timing:
  ui_settle:
    applies_to: [menu_open, post_click_tree_refresh]
    scans: 2
    quiet_window_ms: platform_constant
  async_wait:
    applies_to: [navigation, upload, generation_start, generation_complete]
    poll_interval_ms: platform_constant
    deadline_ms: platform_constant
    required_each_poll: some_mapped_pending_or_terminal_state
```

Rule: polling a mapped pending state is allowed. Retrying the action is not.

---

### 14. **Network stall with Stop present is not expressible**

**Break:** “Generating = Stop present” can hang forever. Stop present does not distinguish legitimate long reasoning from a network stall, frozen tab, lost websocket, or platform backend failure.

**Concrete amendment:** Add progress and deadline states.

```yaml
generating_state:
  required_present: [stop_button]
  progress_signals_any:
    - assistant_text_delta
    - streaming_indicator_delta
    - status_text_changed
    - elapsed_under_deadline
  no_progress_deadline_ms: platform_constant
  on_deadline: generation_stalled_notify_halt
```

This is still binary: at each poll, either a mapped generating/progress state matches, a mapped terminal state matches, or the engine halts.

---

### 15. **URL validation is under-defined and not exact-matchable**

**Break:** “New URL on a new chat” contains dynamic IDs, query params, redirects, hash routes, and possible delayed URL updates. Exact URL cannot be pre-mapped, and fuzzy URL matching would violate the spirit unless defined.

**Concrete amendment:** Define URL predicates as structured binary validators, separate from control-element matching.

```yaml
url_policy:
  new_chat:
    previous_url_must_differ: true
    allowed_route_shapes:
      - path_segments_exact: ["c", "{chat_id}"]
        chat_id_type: uuid_or_platform_id
      - path_segments_exact: ["app", "{chat_id}"]
    forbidden:
      - login_route
      - error_route
      - pricing_route
```

Rule: URL validation may use exact route schemas with typed captures. It must not use ad hoc substring checks.

---

## P1 — holes that make drift detection noisy or force humans to guess

### 16. **Modal priority and occlusion are not specified**

**Break:** A blocking dialog can coexist with a matching underlying page. Without topmost-window/modal priority, the engine may click controls behind a modal or classify the wrong state.

**Concrete amendment:** Every snapshot must first classify top-level windows/dialogs.

```yaml
snapshot_classification_order:
  - active_x_display
  - active_window
  - topmost_modal
  - native_dialog
  - browser_document
  - expected_control_scope
```

Rule: underlying controls cannot satisfy a step while a mapped blocker is active.

---

### 17. **Hover-to-expand and multi-step flyouts need their own states**

**Break:** Menus and submenus are not just static trees. Hover paths can close, submenus can be portals, and moving the pointer can mutate the tree. “Every menu/submenu mapped” is not enough without transition guards.

**Concrete amendment:** Model menus as stateful transition graphs.

```yaml
menus:
  model_picker:
    states:
      closed
      root_open
      submenu_hovered
      submenu_open
      option_selected
    transitions:
      open_root:
        action: click
        validate: root_open
      open_submenu:
        action: hover
        validate: submenu_open
        pointer_guard_region: [...]
```

Rule: every hover/click menu transition has exact pre-state and exact post-state validation.

---

### 18. **The selected option may not be visible in the collapsed control**

**Break:** The contract says selected options show on screen. Some platforms expose selected model/mode only as checked menu item, ARIA selected state, tooltip, account-level default, or not at all until the menu is reopened.

**Concrete amendment:** Each selection needs an exact **selection proof**.

```yaml
selection_validation:
  selected_model:
    acceptable_proofs:
      - collapsed_button_name_exact
      - menu_item_checked_state_exact_after_reopen
      - persistent_header_label_exact
    if_no_proof_exposed: terminal_selection_unverifiable
```

Rule: if a selected option cannot be verified through AT-SPI, the engine halts. It must not assume selection from a prior click.

---

### 19. **Model/mode inventories are account- and feature-flag-dependent**

**Break:** The same platform can show different models, tools, and modes by account plan, region, A/B bucket, workspace, or date. “Finite and complete” must be scoped to an environment.

**Concrete amendment:** Add an environment contract per YAML.

```yaml
environment_contract:
  browser_version: exact
  locale: en-US
  account_plan: exact_or_alias
  workspace: exact
  feature_flags_expected:
    - tools_menu_version_x
    - model_picker_variant_y
  model_inventory:
    exact_options: [...]
  preflight_must_match: true
```

Rule: if the account inventory differs, that is an environment mismatch, not normal drift.

---

### 20. **Prompt paste success is not validated**

**Break:** Pasting can silently fail, truncate, normalize line endings, drop attachments, trigger IME issues, or land in the wrong textbox. The spec validates selected UI options but not the actual payload.

**Concrete amendment:** Add composer payload validation.

```yaml
paste_validation:
  textbox_focused: true
  accessible_text_equals: submitted_prompt_exact
  if_too_large_for_exact_read:
    required_sentinel_prefix: exact
    required_sentinel_suffix: exact
    required_length: exact
    required_hash_visible_or_internal: exact
  send_button_enabled_after_paste: true
```

Rule: submit is forbidden unless the composer content is verified exact or via a predeclared hash/sentinel scheme.

---

### 21. **File tile visible does not prove file upload is complete**

**Break:** A tile can appear while upload is still processing, virus-scanning, rejected, too large, unsupported, or removable but not attached. The spec says the file tile shows on screen, but not what state proves upload completion.

**Concrete amendment:** Add upload completion validators.

```yaml
attachment_validation:
  required:
    - tile_name_exact: "{basename}"
    - tile_state: uploaded_complete
  forbidden:
    - progress_bar
    - spinner
    - failed_label
    - unsupported_file_label
    - remove_only_pending_state
```

Rule: a file is usable only when the exact completed tile state matches.

---

### 22. **“Live candidates” notification is underspecified**

**Break:** On mismatch, a human needs enough data to update YAML without guessing. “Live candidates” could mean entire tree, nearby controls, same-role controls, visible controls, or scoped candidates. Too much leaks secrets; too little causes bad YAML patches.

**Concrete amendment:** Define a notification schema.

```yaml
notify_payload:
  required:
    - platform
    - x_display
    - step_id
    - expected_locator_id
    - expected_scope
    - mismatch_type: [zero, multiple, wrong_state, blocked, stale_tree]
    - candidate_table:
        fields: [path, role, name, states, actions, bounds, scope_id]
    - active_url_redacted
    - screenshot_redacted_optional
    - raw_tree_artifact_path_redacted
    - irreversible_action_barrier_status
```

Rule: notification artifacts must be redacted, persisted, and linked to the YAML change/repro.

---

### 23. **HALT semantics are incomplete**

**Break:** “HALT that step” does not say whether the browser is left open, whether generation continues, whether other platforms proceed, whether the prompt is quarantined, or whether the engine releases locks. In a five-platform consultation run, partial state matters.

**Concrete amendment:** Define halt scope.

```yaml
halt_policy:
  platform_halt:
    freeze_display_input: true
    preserve_browser_state: true
    collect_snapshot: true
    no_cleanup_unless_cleanup_state_mapped: true
  consultation_halt:
    default: halt_aggregate_if_any_platform_halts
    partial_results_policy: quarantined_not_published
```

Rule: partial outputs cannot be merged into the consultation result unless the contract explicitly allows degraded quorum. Your current contract forbids downgrade, so the safe default is aggregate halt.

---

### 24. **Re-entry after halt is not specified**

**Break:** A halted browser may be left with an open menu, pasted prompt, native dialog, half-uploaded file, or already-submitted chat. A later run starting at “open new chat” may violate the no-retry rule.

**Concrete amendment:** Add re-entry states.

```yaml
reentry:
  allowed_start_states:
    - clean_new_chat_ready
    - halted_menu_open
    - halted_prompt_pasted_not_submitted
    - halted_post_submit_side_effect_uncertain
    - halted_generation_in_progress
  each_requires_exact_reconciliation: true
```

Rule: no run resumes from an assumed clean state. It resumes only from a matched re-entry state.

---

### 25. **The monitor/driver ownership split is ambiguous**

**Break:** The contract says Stop detection is owned by `claude-code-fleet-notify`, not bespoke per-driver code, but submit validation depends on Stop. Without a clear API, drivers may reimplement detection or race the monitor.

**Concrete amendment:** Add a single observer API.

```yaml
observer_contract:
  owner: monitor
  drivers_may_call_only:
    - wait_for_state(state_id)
    - assert_state(state_id)
    - get_last_observed_event(event_id)
  forbidden:
    - driver_direct_stop_button_lookup
    - driver_private_tree_scan
```

Rule: Stop/generating/completion state is centralized and event-logged.

---

## P2 — structural/spec contradictions that will rot the contract over time

### 26. **“1 YAML + 1 driver” conflicts with “drivers carry zero platform knowledge”**

**Break:** If there is one driver per platform, the driver will tend to accumulate platform sequence knowledge. If drivers truly carry zero platform knowledge, there should be one generic executor plus per-platform YAML state graphs.

**Concrete amendment:** Choose one:

```yaml
architecture_option_a:
  universal_driver: true
  platform_yaml_contains:
    - states
    - transitions
    - actions
    - validations

architecture_option_b:
  platform_driver_allowed: true
  platform_driver_is_session_driving_surface: true
  driver_logic_subject_to_same_gate: true
```

The cleaner amendment is option A: one generic deterministic executor, five YAML state machines.

---

### 27. **Exact accessible names are not stable unless locale/browser/profile are pinned**

**Break:** Accessible names can change with locale, browser version, screen size, accessibility settings, account name, workspace name, feature flags, and experiment buckets.

**Concrete amendment:** Add a pinned runtime profile and preflight.

```yaml
runtime_profile:
  browser: exact_version
  os_locale: exact
  display_scale: exact
  font_dpi: exact
  accessibility_backend: exact
  account_alias: exact
  workspace_alias: exact
```

Rule: profile mismatch halts before platform interaction.

---

### 28. **Dynamic exact values need a formal templating system**

**Break:** File names, chat IDs, prompt titles, account names, and uploaded tile names are dynamic. If exact matching forbids variables, the finite map cannot cover them. If variables are informal, future editors will smuggle in fuzzy matching.

**Concrete amendment:** Permit only typed exact variables.

```yaml
variables:
  file_basename:
    source: run_manifest
    validation: exact_string
  chat_id:
    source: url_capture
    validation: platform_chat_id_type
  prompt_hash:
    source: run_manifest
    validation: sha256
```

Rule: variables are resolved before matching. No regex/contains except declared typed parsers for non-control data like URLs.

---

### 29. **“Nothing is ever hidden” is false as a platform-independent invariant**

**Break:** Browser accessibility trees routinely include collapsed, offscreen, stale, inactive, or hidden elements, and may omit visible canvas/shadow/iframe content. The stronger enforceable invariant is not “nothing is hidden,” but “only showing/actionable scoped elements can satisfy control locators.”

**Concrete amendment:** Replace the invariant:

```text
Only elements satisfying required AT-SPI visibility/actionability states inside the expected scope may validate a step. Hidden/offscreen/stale elements are candidates for diagnostics only and never satisfy control matches.
```

---

### 30. **Same name+role can hide semantic drift**

**Break:** The UI label can stay identical while the platform changes what the option means. Example: a model name remains the same but its context limit, tool mode, thinking mode, or routing changes. AT-SPI cannot prove the backend semantics.

**Concrete amendment:** Add semantic canaries where semantics matter.

```yaml
semantic_validation:
  extended_thinking_mode:
    ui_proof_required: selected_mode_exact
    canary_optional_or_scheduled:
      prompt: known_low-risk_probe
      expected_ui_metadata: exact
    if_semantics_not_ui_observable: mark_unverifiable_notify
```

Rule: UI exactness proves UI state, not backend semantics. Any backend guarantee requires a separate mapped validation artifact or must be labeled unverifiable.

---

### 31. **User/content can create false candidates unless transcript is untrusted**

**Break:** A generated answer can include links, buttons, citations, source cards, code UI, or copied text with names matching platform controls. If the engine searches globally, content can poison control matching.

**Concrete amendment:** Add a hard trust boundary:

```yaml
untrusted_content_zones:
  - conversation_region
  - web_result_cards
  - uploaded_document_preview
  - generated_code_preview

rule:
  no_session_driving_locator_may_resolve_inside_untrusted_content_zone
```

---

### 32. **Browser/OS prompts outside the platform are missing**

**Break:** Notification permission, password-save bubbles, extension popups, keyring unlock, crash restore, downloads shelf, certificate warning, proxy auth, browser update prompts, and tab crash pages can interrupt or occlude the app.

**Concrete amendment:** Add browser/OS blocker maps or disable them by profile and verify disabled.

```yaml
browser_blockers:
  notification_permission_prompt: terminal
  save_password_prompt: terminal_or_disabled_by_profile
  tab_crashed: terminal
  browser_update_prompt: terminal
  proxy_auth: terminal
```

Rule: every non-platform window capable of taking focus is either disabled by profile preflight or mapped as terminal.

---

## Sticky-enforcement holes

### 33. **Pre-commit lint is not regression-proof**

**Break:** Pre-commit can be bypassed locally, and string lint will miss semantic fallbacks hidden behind helpers, dependencies, env flags, generated code, shell scripts, YAML match modes, or renamed functions.

**Concrete amendment:** Move enforcement to CI and architecture, not just lint.

```yaml
enforcement:
  ci_required: true
  protected_branch_required: true
  exact_match_api_only: true
  direct_pyatspi_access_forbidden_except_snapshot_module: true
  ast_lint:
    forbidden_calls:
      - contains
      - regex_match_for_control_name
      - fallback_select
      - default_model_on_failure
  dependency_review_required: true
  generated_code_checked: true
```

Rule: developers cannot import raw tree APIs from session-driving code. They can only call the exact-match primitive.

---

### 34. **“Session-driving surface” can be misclassified**

**Break:** A future editor can put fallback behavior in shared primitives, YAML schema, monitor code, browser profile scripts, notification recovery, test utilities, or deployment config and argue it is not a driver.

**Concrete amendment:** Define session-driving transitively.

```text
A session-driving surface is any code, YAML, prompt, skill, config, dependency, browser profile, monitor, notification handler, or script that can influence observation, matching, action selection, timing, retry, halt, or recovery for a live platform session.
```

Then enforce CODEOWNERS/r5-audit-gate on all such paths.

---

### 35. **YAML can smuggle fuzziness**

**Break:** Even if code bans fuzzy logic, YAML can reintroduce it with fields like `aliases`, `contains`, `optional`, `prefer`, `fallback`, `default`, broad scopes, or multiple acceptable options.

**Concrete amendment:** Add a strict YAML schema.

```yaml
schema_forbidden_fields:
  - contains
  - regex_name
  - aliases
  - fallback
  - default_on_missing
  - optional_for_actionable_control
  - prefer
  - best_effort

schema_required_fields_for_actionable:
  - exact_name
  - exact_role
  - exact_scope
  - exact_state_requirements
  - cardinality: exactly_one
```

Rule: YAML validation must fail closed.

---

### 36. **Human YAML updates can become manual fallback**

**Break:** “A human/operator reads the new option/name and YAML is updated” can devolve into live hand-patching to get past a blocker, without proving the new state is stable, complete, or scoped.

**Concrete amendment:** Require drift PR artifacts.

```yaml
drift_update_requirements:
  - raw_tree_snapshot_before
  - redacted_screenshot_before
  - exact candidate chosen
  - reason not dynamic/user-content
  - updated YAML
  - replay test against captured tree
  - gatekeeper execution on repro
  - version bump
```

Rule: no production hot patch unless the system remains halted and the update passes replay.

---

### 37. **Operator/manual input can bypass the contract**

**Break:** An operator with access to the X display can click, type, close modals, or choose options manually. The code would still be clean, but the session was not contract-driven.

**Concrete amendment:** Add runtime input provenance.

```yaml
runtime_integrity:
  display_input_lock: enabled
  allowed_input_sources:
    - deterministic_driver
  event_recorder:
    records_mouse_keyboard_events: true
    flags_manual_events: true
  on_manual_event: session_tainted_notify_halt
```

Rule: any manual event taints the run unless it occurs in an explicitly declared supervised-recovery mode.

---

### 38. **Gatekeeper/grok repro can be ceremonial unless artifacts are signed**

**Break:** “grok + Gatekeeper executing the repro” is good, but not enough unless the exact artifacts, versions, and result are immutable. Otherwise reviewers can approve one thing and merge another.

**Concrete amendment:** Add signed replay artifacts.

```yaml
audit_gate:
  required_artifacts:
    - commit_sha
    - yaml_version
    - browser_profile_hash
    - raw_tree_fixture_hash
    - replay_log_hash
    - reviewer_signatures
  merge_condition:
    all_hashes_match_ci_run: true
```

---

## Cases the binary cannot express unless folded back into explicit states

1. **AT-SPI unavailable or empty:** cannot be driven. Fold into `ACCESSIBILITY_UNAVAILABLE` terminal state with notify/halt. Do not add visual guessing.

2. **Backend semantics changed while UI label stayed same:** AT-SPI cannot prove semantics. Fold into semantic canaries or mark `SEMANTICS_UNVERIFIABLE`.

3. **Legitimate long generation vs network stall:** Stop presence cannot decide forever. Fold into mapped generating-progress states plus a deadline-triggered `GENERATION_STALLED` terminal state.

4. **Unbounded transcript content:** cannot finite-map all names/roles. Fold into dynamic transcript zones with exact container validation and hard exclusion from session-driving locators.

5. **Post-submit uncertainty:** cannot know whether a side effect happened from a failed validation alone. Fold into `SIDE_EFFECT_UNCERTAIN` quarantine, not rerun.

I do not see an unavoidable **action fallback**. I do see unavoidable **terminal halt states** where AT-SPI cannot provide enough evidence. If the requirement is truly “100% reliable across third-party changing web UIs,” AT-SPI-only observation cannot guarantee that; the contract must either accept terminal non-drivable states or add another explicitly contracted observation channel.

**Verdict: not yet airtight enough for a 100%-reliable engine; the single most important fix is to replace the happy-path binary rules with an executable finite state machine that includes blocker/error/auth/inaccessible/side-effect-uncertain states before any irreversible action can be rerun.**
