# FLOW_CONSULTATION_ENGINE.md

Canonical browser-consultation flow for `taeys-hands`.

Status: canonical in-repo contract, reconciled 2026-06-17.
Home: `taeys-hands/FLOW_CONSULTATION_ENGINE.md`.

This is the project-level flow reference that must be injected into every
consultation-engine audit, implementation task, and Family-chat review packet.
It supersedes fragmented historical contracts and notes, including
`100_TIMES.md`, `CONSULTATION_CONTRACT.md`, the older
`consultation_v2/*` contract files, and the orphan orchestrator planning copy.

If this file conflicts with those older contract files, the stricter no-guess,
exact-match, stop-button, no-retry rule wins.

## Truth Register

Observed:

- taeys-hands has an explicit deterministic contract:
  `CONSULTATION_CONTRACT.md:1-3` states that it is the model code and skills are
  graded against.
- The target implementation shape is `consultation_v2`, because it already has
  per-platform drivers, platform YAMLs, identity consolidation, a V2
  orchestrator, typed request/result records, and shared runtime/snapshot
  primitives. Evidence: `consultation_v2/orchestrator.py:1-7`,
  `consultation_v2/orchestrator.py:35-72`,
  `consultation_v2/types.py:7-23`, `consultation_v2/types.py:121-162`,
  and `consultations/inventory/p1_entrypoint_inventory.md:58-71`.
- At the start of cleanup, the active production reference path was root V1:
  `scripts/consultation.py`, root
  `platforms/{chatgpt,claude,gemini,grok,perplexity}.yaml`,
  `tools/attach.py`, `core/mode_select.py`, `monitor/central.py`, and
  `tools/extract.py`. Evidence:
  `consultations/inventory/p1_entrypoint_inventory.md:73-87`.
  That path is a migration source, not the final clean engine.
- The current closest monitor shape is the central monitor: one process cycles
  all active sessions. Evidence: `monitor/central.py:1-15`,
  `monitor/central.py:181-258`, and
  `consultations/inventory/p1_orchestrator_surface_audit.md:104-121`.
- The current monitor completion signal shape is sticky stop seen, then stop
  gone, with deep-mode stop-gone debounce and timeout backstops. It has no
  rendered-content freeze heuristic. Evidence:
  `monitor/central.py:312-421` and `consultation_v2/completion.py:1-135`.
- Monitor notification must use fleet-notify/taey-notify with recorded delivery
  or parked failure behavior. Evidence: `CONSULTATION_CONTRACT.md:41-42`,
  `monitor/central.py:423-568`, and this file's notification contract below.
- The production display substrate is not the consultation engine and must be
  retained: real Firefox on isolated X displays, isolated D-Bus/AT-SPI, and
  persistent profiles. Evidence: `design/PRODUCTION_GRADE_BRIEF.md:8-15`,
  `design/PRODUCTION_GRADE_BRIEF.md:47-50`,
  `scripts/install_machine_displays.sh:1-19`,
  `systemd/user/firefox-user.js:1-37`, and
  `consultations/inventory/p1_display_substrate_inventory.md:1-194`.
- Extraction exists, but it is not yet one clean mapped extraction contract.
  Evidence: `consultations/inventory/p1_extraction_inventory.md:34-91`
  and `consultations/inventory/p1_extraction_inventory.md:93-119`.
- Current YAML/driver debt is bounded and line-pinned: root chat YAML currently
  has zero forbidden loose matcher keys, while V2 has 18 forbidden matcher keys
  and V2 loader/matcher permissiveness. Evidence:
  `consultations/inventory/p1_yaml_driver_gap_map.md:22-51` and
  `consultations/inventory/p1_yaml_driver_gap_map.md:73-127`.

Inferred:

- The cleanup should repair `consultation_v2` in place rather than create a new
  package. The gap is bounded: strict loader/matcher enforcement, 18 V2 YAML
  debts, monitor registration/run-state integration, extraction matrix, and
  archive/stub cutover. A new package would duplicate the already-correct
  driver/YAML/runtime shape and increase cutover risk.
- Setup/send is sequential per machine/display to avoid browser and AT-SPI
  contention. Monitoring is concurrent after each send is registered.
- The clean engine needs explicit run-state checkpoints so a post-send failure
  cannot duplicate a prompt.
- Root V1 modules are production evidence and migration sources only. They must
  become archived paths, fail-loud stubs, or pure forwarders after cutover.

Unknown:

- The exact live AT-SPI replacement for each of the 18 V2 loose YAML keys until
  p5 platform migration performs live scans.
- The final exact ChatGPT Canvas/Download extraction path and Grok image download
  executor. Current docs identify the need, but not a production-wired V2 path.
- Whether the checked-in production display units and the live
  `~/.config/systemd/user` units are byte-identical. The display substrate
  inventory records drift and a no-regeneration-without-verification rule.

## Source Evidence

Core deterministic contract:

- `CONSULTATION_CONTRACT.md:5-18`: binary match-or-notify; no guessing,
  downgrade, fallback, loose matching, or action retry.
- `CONSULTATION_CONTRACT.md:20-30`: one YAML and one driver per platform; YAML
  maps menus, generating, completed, and validation specs.
- `CONSULTATION_CONTRACT.md:32-43`: settle plus rescan is observation; submit
  succeeds when URL and Stop evidence are captured; complete is Stop gone with no
  mapped exception state; monitor notifies via fleet-notify.
- `CONSULTATION_CONTRACT.md:49-56`: enforcement must be behavioral and
  machine-readable, not memory or comments.

Operational rules Jesse has repeated:

- `100_TIMES.md:8-14`: Stop appears means generating; Stop disappears means
  complete; no copy-button fallback.
- `100_TIMES.md:16-26`: extraction normally scrolls to the final answer and uses
  the copy-button element action, but reports and attachments require special
  handling.
- `100_TIMES.md:28-47`: exact YAML only, validate every step, zero action
  retries; manual recovery is allowed after a halt.
- `100_TIMES.md:54-57`: dispatch setup must be sequential on shared
  infrastructure.
- `100_TIMES.md:95-100`: ChatGPT send is focus composer plus Enter, while the
  tree send button is presence verification.

V2 implementation contracts:

- `consultation_v2/DRIVER_CONTRACT.md:10-16`: Stop-button completion, no
  fallback.
- `consultation_v2/DRIVER_CONTRACT.md:18-24`: copy-button extraction and
  artifact guard.
- `consultation_v2/DRIVER_CONTRACT.md:26-38`: exact YAML and tree validation.
- `consultation_v2/DRIVER_CONTRACT.md:40-50`: zero action retries.
- `consultation_v2/DRIVER_CONTRACT.md:56-73`: sequential dispatch, wake while in
  flight, and per-platform send method.
- `consultation_v2/YAML_SCHEMA.md:10-31`: exact element map grammar and
  forbidden loose keys.
- `consultation_v2/YAML_SCHEMA.md:33-53`: structural locator exception for
  dynamic leaves.
- `consultation_v2/YAML_SCHEMA.md:55-84`: validation and matcher contract.

Current gaps to close:

- `consultation_v2/snapshot.py:33-83` still accepts loose keys such as
  `name_contains`, `name_pattern`, and `role_contains`.
- `consultation_v2/snapshot.py:97-99` still accepts exclusion
  `name_contains`.
- `consultation_v2/drivers/base.py:34-93` still has URL substring validation and
  filename substring chip matching.
- `consultation_v2/yaml_contract.py:26-36` only checks top-level keys; it does
  not reject loose matcher grammar at load.
- `consultation_v2/orchestrator.py:39-49` catches identity consolidation failure
  and can continue; clean behavior must fail loud if required identity files are
  missing.
- `consultation_v2/orchestrator.py:70-72` runs driver lifecycle synchronously;
  clean dispatch must validate send, write run state, register monitor, then move
  on while monitors observe concurrently.
- `consultation_v2/cli.py:6-33` is currently a fail-loud legacy pointer to the
  root V1 path. P2 must restore this as the clean CLI.

Production display substrate to preserve:

- `scripts/install_machine_displays.sh:1-19`: machine-level installer owns Xvfb,
  Firefox, AT-SPI, x11vnc, and profile provisioning per platform display.
- `scripts/install_machine_displays.sh:57-88`: required tooling and real Firefox
  binary detection; avoid wrapper paths that break profile semantics.
- `scripts/install_machine_displays.sh:101-136`: generated Xvfb template and
  `taey-bus-watcher@` unit.
- `scripts/install_machine_displays.sh:167-183`: generated per-display unit
  launches `dbus-run-session`, AT-SPI, openbox, x11vnc, persistent Firefox
  profile, and the platform URL.
- `scripts/install_machine_displays.sh:205-248`: systemd user daemon reload,
  enable, restart, and verification.
- `systemd/user/taey-xvfb@.service:1-13`: checked-in Xvfb template.
- `systemd/user/taey-display-2.service:1-16`: checked-in production display unit
  shape, including display dependency, D-Bus/AT-SPI capture, Firefox launch, VNC,
  pid file, and restart policy.
- `scripts/bus_watcher.sh:1-14`: bus-file watcher writes `/tmp/a11y_bus_:N`
  from the live X root `AT_SPI_BUS` property.
- `core/platforms.py:98-175`: platform-to-display mapping and bus resolution,
  including live X root fallback when the bus file is missing.
- `machine.env.example:1-32`: machine-local display/platform/profile/source URL
  mapping is the single source of truth for launch scripts.
- `systemd/user/firefox-user.js:1-37`: profile policy preserves one-tab behavior
  and forces Firefox accessibility on.
- `consultations/inventory/p1_display_substrate_inventory.md:1-194`: retain
  list, checked-in vs live drift, redundant bus-refresh note, and
  no-regeneration-without-verification rule.

Historical full-flow blueprint:

- `docs/taeys-hands Consultation Flow  Full Review & New Implementation Plan.md:186-242`
  maps model/mode/tools, attachment, prompt entry, send, URL capture, and
  post-send actions.
- `docs/taeys-hands Consultation Flow  Full Review & New Implementation Plan.md:244-266`
  maps monitor registration, but its copy-button completion wording is
  superseded by this Stop-only contract.
- `docs/taeys-hands Consultation Flow  Full Review & New Implementation Plan.md:268-312`
  maps extraction, attachment extraction, storage, and cleanup. Keep the
  extraction cases, but re-express them as YAML-driven output-type workflows.
- `docs/taeys-hands Consultation Flow  Full Review & New Implementation Plan.md:316-344`
  describes the desired runner result surface.
- `docs/taeys-hands Consultation Flow  Full Review & New Implementation Plan.md:348-360`
  gives useful implementation rules, but the "no shared runtime logic" wording
  is superseded by the newer "drivers have no platform strings, shared
  primitives only" contract.

## 0. Scope

The supported consultation engine is the browser consultation flow:

```text
request
  -> route platform/model/mode/tools/connectors
  -> consolidate identity + attachments
  -> drive one browser platform through its YAML-backed driver
  -> validate send by stop-button appearance and URL capture
  -> write durable run state
  -> register/monitor in-flight session
  -> detect completion by stop-button disappearance
  -> notify via fleet-notify/taey-notify
  -> extract by mapped copy/report/artifact/download control
  -> store/deliver response and evidence
```

Target architecture:

- one active package: `consultation_v2`
- one active chat YAML directory: `consultation_v2/platforms/`
- one platform YAML plus one platform driver per chat platform
- shared code provides only primitives, validation mechanics, run state,
  storage, monitor registration, and notification transport
- root V1/MCP/tool/bot paths become archived history, fail-loud stubs, or pure
  forwarders after migration

## 1. P2 Cutover Shape Decision

Decision: repair `consultation_v2` in place. Do not create a new
`consultation_clean` package.

Grounds:

- P1 entrypoint inventory identifies `consultation_v2` as the closest final
  architecture: per-platform drivers, per-platform YAML, shared runtime/snapshot
  primitives, typed request/result objects, and a V2 orchestrator. Evidence:
  `consultations/inventory/p1_entrypoint_inventory.md:58-71`.
- P1 YAML/driver gap map shows the main gap is bounded: 18 V2 forbidden YAML
  keys plus V2 loader/matcher permissiveness, not a broad driver rewrite.
  Evidence: `consultations/inventory/p1_yaml_driver_gap_map.md:22-51` and
  `consultations/inventory/p1_yaml_driver_gap_map.md:73-127`.
- P1 extraction inventory shows plain assistant extraction is already wired for
  all five V2 drivers and report extraction is production-proven for Gemini and
  Perplexity, with specific gaps to migrate for Claude artifacts, ChatGPT
  Canvas/Download, Grok image download, and copy disambiguation. Evidence:
  `consultations/inventory/p1_extraction_inventory.md:34-91` and
  `consultations/inventory/p1_extraction_inventory.md:93-119`.
- P1 display inventory says the engine should consume the existing display
  substrate, not replace it. Evidence:
  `consultations/inventory/p1_display_substrate_inventory.md:155-194`.

Single supported entrypoint after cutover:

- Canonical user/API entrypoint: `consultation_v2/cli.py`.
- Required bus-binding wrapper for production display execution:
  `scripts/run_consultation_v2.py`.
- `scripts/run_consultation_v2.py` may remain as a pure pre-import environment
  binder and forwarder to `consultation_v2.cli:main`. It may not contain
  platform matching, YAML matching, send, monitor, extraction, fallback, or
  storage logic.
- `consultation_v2/cli.py` must be restored from its current disabled state
  (`consultation_v2/cli.py:6-33`) into the clean CLI that builds a
  `ConsultationRequest`, calls the clean dispatch boundary, and returns durable
  run/monitor/extraction/notification evidence.

Implementation gate:

- No p2 runtime code may begin until this canonical contract is committed,
  tracker refs point at this in-repo file, and Gemini/Grok re-audits have been
  recorded against this final contract.

## 2. Request Intake

A request contains, explicitly or by deterministic YAML-declared default:

- `platform`: `chatgpt`, `claude`, `gemini`, `grok`, or `perplexity`
- `requester`: fleet node/session that must receive the final notification
- `message`: the prompt or lens for the platform
- `model`: optional platform model key
- `mode`: optional platform reasoning/research/tool mode key
- `tools` and `connectors`: optional platform capability keys
- `attachments`: caller-provided files
- `session_url`: absent for a new session, present for a follow-up
- `timeout`, `purpose`, and storage/ingestion flags
- `output_type`: explicit or derived extraction type such as `assistant_text`,
  `research_report`, `artifact`, `downloaded_file`, or `attachment_echo`

No component may silently downgrade a requested model/mode/tool. If the request
cannot be mapped to an exact YAML workflow target, the engine stops and reports
that mapping failure.

## 3. Routing And Resolution

The resolver determines the platform driver and the requested/default
model/mode/tools/connectors before browser actions begin.

Rules:

- The platform selects exactly one YAML and exactly one driver.
- Platform-specific labels, roles, URLs, validation keys, tool menu targets,
  stop keys, and extraction controls live in the platform YAML.
- Driver code may contain platform behavior only inside that platform's driver.
- Shared primitives must not branch on platform names except to load that
  platform's YAML or resolve the platform's production display/bus.
- Missing or unsupported model/mode/tool/connectors stop before send.

## 4. Identity And Attachment Consolidation

Before any send, the engine builds one consolidated attachment package.

Required order:

1. `FAMILY_KERNEL.md`
2. the platform identity file, `IDENTITY_<platform>.md`
3. caller attachments and any audit packet/source files
4. request metadata and prompt/lens context where needed

The package path is the only file sent to the browser unless the request
explicitly requires multiple files. Missing identity/kernel content is a loud
failure, not a warning that the driver can ignore.

For follow-up sessions, identity/package rules may differ only if the contract
for that session type says so explicitly. The driver must still preserve
provenance of what was sent.

## 5. Display, DBUS, And Firefox Preconditions

Production display mapping on Mira:

```text
chatgpt    -> :2
claude     -> :3
gemini     -> :4
grok       -> :5
perplexity -> :6
```

Before importing or using AT-SPI, the process must bind to the target display's
live accessibility bus:

- `DISPLAY=:N`
- `AT_SPI_BUS_ADDRESS=$(cat /tmp/a11y_bus_:N)`
- `DBUS_SESSION_BUS_ADDRESS=$(cat /tmp/dbus_session_bus_:N)` when present

The launch/systemd layer owns Xvfb, Firefox profiles, DBUS session launch,
AT-SPI bus capture, bus refresh files, and Firefox PID files. These production
processes must be retained and documented, not replaced by ad hoc launch code.

Preconditions:

- One Firefox window per display.
- One tab per Firefox window.
- Existing tab is navigated in place; never `ctrl+t`.
- Firefox document URL must match the platform or a mapped alternate state.
- Critical controls must be visible in the AT-SPI tree or the platform/flow is
  out of scope until remapped.

Required verification before cutover:

- `systemctl --user status taey-display-N.service` for each production display
- `systemctl --user status taey-xvfb@N.service` for each production display
- `systemctl --user status taey-bus-watcher@N.service` if watcher units are used
- `/tmp/a11y_bus_:N` exists and matches `xprop -display :N -root AT_SPI_BUS`
- `/tmp/firefox_pid_:N` points to a live Firefox process
- a tree read can find Firefox on each display before any consultation send

Forbidden during consultation cleanup:

- replacing production launch with one-off shell launch commands
- switching to a browser automation framework to avoid the AT-SPI contract
- collapsing displays onto a shared D-Bus or shared Firefox profile
- deleting or regenerating systemd units without production verification

## 6. Setup Flow

Setup is sequential for a single dispatch:

1. switch/focus the platform display/window
2. navigate the existing tab to the requested URL or platform fresh URL
3. select model/mode
4. enable tools/connectors
5. attach the consolidated package
6. focus and populate the prompt/composer

Every step is validated against a fresh AT-SPI tree and, when debugging, a
screenshot. A successful action is not assumed from the action return value.

Allowed timing behavior:

- one readiness wait before a single action
- re-scanning the tree after a wait
- stop-button debounce during monitoring

Forbidden behavior:

- repeating a failed action
- re-clicking to recover
- fallback click paths after an action failure
- substring/fuzzy/name-pattern matching
- silent defaulting or mode downgrade
- proceeding when validation is missing

First failed action means stop, notify the driving session, and root-cause the
YAML/driver/page-state mismatch before another automated attempt.

## 7. YAML And Matching Contract

Element matching is exact:

- exact `name`
- exact `role`
- optional exact `states_include`
- `names_any_of` only for an enumerated list of exact alternative labels
- **STABLE-LOCATOR rule (REQUIRED, per CONSULTATION_CONTRACT.md:12):** a control
  must be located by a STABLE key — an attribute/testid or an exact
  role+container-path — and NEVER by an intrinsically-dynamic visible `name`, i.e.
  a name that reflects current selection/count/locale. The canonical trap is the
  model/mode picker, whose visible name IS the currently-selected model (so an
  exact `name: "Claude Opus 4.6 Extended"` locator silently breaks the instant the
  selection changes, producing false drift or a stale match on the
  no-downgrade model/mode step). Such dynamic-name controls MUST be located
  structurally (exact role+container-path), never by their dynamic name.
- structural locators are used both for the above dynamic-name controls AND for
  inherently dynamic leaves (file chips, generated IDs), and only when the
  structural locator itself is exact

Forbidden in active consultation YAML and active matchers:

- `name_contains`
- `name_not_contains`
- `name_contains_all`
- `name_pattern`
- `role_contains`
- `url_contains`
- regex/fuzzy/substring matchers

Validation specs read persistent live-tree signals. Dropdown-only elements may
validate a dropdown interaction only while that dropdown is intentionally open;
they must not be used as persistent post-close proof unless the flow says the
dropdown remains open.

YAML owns:

- URLs and exact platform page states
- model, mode, tools, connectors, and attachment workflows
- menu trigger types, including click and hover/pointer move
- validation states for every setup step
- stop-button key, debounce policy, generation timeout, and mapped exceptions
- extraction workflow by output type

Drivers own:

- reading the YAML workflow
- invoking shared primitives
- preserving durable run state
- returning exact Match or NoMatch/AlternateState outcomes
- failing loud with tree and screenshot evidence when a mapped state is absent

Shared primitives own:

- snapshot and menu_snapshot
- exact match and structural match
- click element, pointer move, paste, key press, scroll, clipboard read
- URL read and display/window focus
- lock, run-state, monitor registration, storage, and fleet-notify calls

Shared primitives must not own platform strings, fallback guesses, or central
tool modules that branch by platform.

## 8. Send Contract

Send is a single irreversible action.

Before send:

- model/mode/tool state is validated
- attachments are validated
- prompt readiness is validated
- composer/input is focused immediately before the send action

After send:

- `stop_button` appears means generation started
- new sessions must capture the new conversation URL
- follow-up sessions may keep the same URL, but still require generation proof
- no stop button after send is a send failure unless a mapped alternate state
  explains it

For new sessions, the target state is:

```text
stop button appeared AND session URL captured
```

If the driver cannot prove send success, it must not register a successful
dispatch or move on as if the request is monitored.

After send validation, write durable run state: request id, platform, display,
URL, session id, prompt hash, attachment hashes, status `submitted`, and monitor
id. This state prevents duplicate sends during re-run or recovery.

## 9. Monitor Contract

After a validated send, the engine registers an active monitor session with:

- platform
- monitor/session ID
- requester/route target
- mode/timeout
- captured URL
- display/worker context
- storage/provenance metadata

The monitor may watch many active sessions simultaneously. Dispatch itself
remains sequential on shared browser infrastructure, but in-flight generations
can overlap because monitoring is passive.

Completion logic:

- stop button visible means generating
- stop button was seen, then disappears, means complete
- deep/extended modes require the configured stop-gone debounce cycle count
- stop present means generating regardless of rendered text; there is no
  rendered-content freeze heuristic
- stop never seen within the generation-start window is `send_failure`
- a genuinely stuck visible-stop run is bounded by the request timeout, which is
  loud failure

There is no copy-button fallback for completion. Completion is not inferred from
elapsed time, copy buttons, or response-looking content.

Notification:

- monitor completion/failure uses fleet-notify/taey-notify transport
- **delivery-ACK is REQUIRED (per CONSULTATION_CONTRACT.md:17):** notification is
  not complete until the notify is ACKed as received by the driving session. An
  unacked notify is itself an ERROR, not a satisfied surface — it must trigger a
  durable local log + retry + a secondary channel, and surface a queryable
  parked/needs-attention state. A notify into the void at this single chokepoint is
  a silently-swallowed miss and is forbidden.
- notification delivery (and its ACK or parked-state) must be recorded loudly
- failures notify the operator/driver session, not the requester as a deliverable
- successful completed responses notify the original requester

## 10. Concurrency Model

Sequential:

- navigating a browser window
- selecting model/mode/tools/connectors
- attaching files
- pasting prompt text
- pressing Enter or clicking Submit

Concurrent:

- registered monitor sessions
- stop-button polling
- completion notification delivery
- extraction after each independent completion, subject to per-display locks if
  extraction must drive that browser window

Required invariant:

- One Chat is sent, its monitor is registered or a loud error is raised, then
  the dispatcher moves to the next Chat. Any completed monitor may notify and
  extract while later sends are still in progress.

## 11. Extraction Contract

Every request declares or derives an output type. The platform YAML maps that
output type to an extraction workflow.

Required output types:

- `assistant_text`: scroll conversation to the final answer, choose the lowest
  exact copy button or exact response-scoped copy button, activate by AT-SPI
  element action, read clipboard, validate content is not prompt echo.
- `research_report`: use the platform report controls, not the generic bottom
  copy button. Perplexity Deep Research must extract the full report, not only
  the summary copy. Gemini Deep Research must use its Share/Export/Copy Content
  path.
- `artifact`: open the artifact/canvas/panel and copy the artifact content from
  that panel. Claude artifacts and ChatGPT canvases must not be reduced to the
  surrounding chat bubble.
- `downloaded_file`: use YAML-declared export/download controls, store the file
  path, hash, and content type, and link it to the assistant message.
- `attachment_echo`: verify any extracted attachment/canvas content against the
  source attachment hash when the platform reproduces attached content.

Plain chat extraction:

1. scroll to the bottom using the platform-safe scroll primitive
2. select the mapped final response copy button
3. activate it via AT-SPI element action, not raw coordinates
4. read clipboard
5. validate content is non-empty, longer than the prompt, and not a prompt echo

Reports and artifacts:

- Perplexity Deep Research uses the mapped full-report control, such as
  `Copy contents`, and must not scroll past the report-level control.
- Gemini Deep Research uses the mapped report export/copy flow when the normal
  chat copy only returns a summary.
- Claude artifacts use the artifact panel copy path, not the chat bubble.
- ChatGPT Canvas/Download extraction must be mapped before it is claimed
  supported.
- Grok generated-image download must be mapped and executable before it is
  claimed supported.

Extraction validation:

- non-empty content
- content length and lexical shape inconsistent with prompt echo
- expected report/artifact markers when the output type requires them
- saved artifact/download hash when a file is produced
- screenshot or tree evidence for any special extraction path

Extraction failure:

- halt loud to taeys-hands/operator with tree, screenshot, URL, output type,
  extraction workflow step, and clipboard length. Do not tell the requester the
  platform is down until the on-screen response has been inspected.

## 12. Storage And Delivery

After validated extraction:

- store user prompt, attachments/provenance, assistant response, artifacts, URL,
  and session ID
- link plan/session/message records when storage is enabled
- ingest into ISMA only after a real response exists
- notify requester with response-ready payload and preview
- persist run audit, source attachment hashes, extraction method, notification
  delivery evidence, and storage ids

If storage or ingestion is optional and fails, the result may still be delivered
only if the response text is real and preserved. If notification fails, the
result is parked in a queryable failure state; it is not silently dropped.

## 13. Archive And Cutover Rule

The cleanup is not complete while multiple live implementations can be chosen
accidentally.

Required cutover state:

- one supported CLI/API entrypoint
- one package that loads one YAML directory
- old V1/MCP/direct tool paths archived under a clearly named archive directory
  or replaced with fail-loud stubs pointing to the supported entrypoint
- import/lint gate preventing clean engine modules from importing legacy
  platform-driving modules
- documentation updated so every skill and plan points at this flow contract
- no `.bak`/duplicate files in active import paths

Minimum old runnable paths to archive, stub, or forward only after migration:

- `scripts/consultation.py`
- root `platforms/{chatgpt,claude,gemini,grok,perplexity}.yaml`
- `server.py`
- `tools/send.py`
- `tools/send_message.py`
- `tools/extract.py` as direct extraction entrypoint
- `tools/attach.py`, `tools/mode_select.py`, `tools/dropdown.py`,
  `tools/click.py`, and `tools/inspect.py` as callable UI-dispatch tools
- `tools/monitors.py`
- `monitor/daemon.py`
- old bot paths that directly drive chat platforms
- conductor/orchestrator surfaces that can launch, send, monitor, or extract
  without the single clean entrypoint

Allowed compatibility wrapper:

- A legacy path may remain only as a fail-loud stub or pure forwarder to the
  supported entrypoint. A forwarder may not contain matching, clicking, send,
  monitor, extraction, fallback, or storage logic.

## 14. Manual Recovery

Manual recovery is allowed only after automation halts before another
irreversible action.

Manual recovery must still follow this flow:

- inspect screenshot and AT-SPI tree
- identify the exact missing/new state
- perform human-paced manual action if needed
- record why automation halted
- record whether a side effect may have landed
- update YAML/driver with the exact observed state
- avoid duplicate sends by checking URL, stop state, run state, and sent content
  first

Manual recovery is not a code fallback and must not be hidden inside a driver as
a retry path. Manual recovery must never become an automatic retry loop.

## 15. Current Acceptance Gate

As of 2026-06-17, verify these before claiming the active production engine is
clean:

- this file is the only canonical flow contract and the tracker source path is
  the taeys-hands in-repo `CONSULTATION_CLEAN_MAIN_PLAN.md`
- Gemini and Grok have re-audited this reconciled contract after the p2
  decision
- `consultation_v2/cli.py` is restored as the clean CLI and
  `scripts/run_consultation_v2.py` is only a bus-binding forwarder
- root V1/MCP/direct entrypoints are archived, fail-loud stubs, or pure
  forwarders after migration
- root platform YAMLs are no longer an active consultation YAML tree
- shared primitives reject forbidden matcher keys for chat platforms
- setup validation uses exact YAML state after navigation, model/mode, tools,
  attachments, prompt, send, and session URL capture
- no send path contains a hidden second send, retry, or fallback click
- monitor registration is required and accepts multiple simultaneous active
  sessions
- monitor completion uses Stop-seen then Stop-gone only, with loud
  send-failure, hang, timeout, and mapped exception paths
- extraction is fully mapped for plain chat, report, artifact, download, and
  attachment-output flows
- Claude `:3` usage-limit/OAuth state is not counted as an operational Claude
  production run

Final acceptance requires one real production run per platform plus a
multi-monitor concurrency run. Evidence for each run must include submitted URL,
monitor id, Stop seen/gone evidence, extracted response or artifact path,
notification ACK or parked evidence, and storage id.

## 16. Done Evidence

A task is not done by self-report. Done evidence for this cleanup is:

- branch and commit hash
- exact files changed
- tracker task id when applicable
- line-pinned contract or code refs updated
- real production observation for browser-driving changes
- five platform run records for final acceptance: ChatGPT, Claude, Gemini, Grok,
  and Perplexity
- for each run: submitted URL, monitor id, Stop seen/gone evidence, extraction
  artifact/response path, notification ACK or parked evidence, and storage id
