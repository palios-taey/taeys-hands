# Grok Platform Package Generative Disposition Table

Pinned implementation commit: `81d3d921`.

Observed basis: generated from the committed package slice plus `git log --follow --oneline` for every moved, retired, touched, or residue-audited module in this slice. The logs below are intentionally full path history, not abbreviated counts.

| Module | Disposition |
| --- | --- |
| `consultation_v2/drivers/base.py` | inlined into package-local lifecycle base at consultation_v2/platforms/grok/driver.py:38; package does not import drivers.base. |
| `consultation_v2/completion.py` | inlined into package-local monitor at consultation_v2/platforms/grok/monitor.py:48; package does not import completion. |
| `consultation_v2/drivers/__init__.py` | touched to re-export package-owned Grok driver at consultation_v2/drivers/__init__.py:5. |
| `consultation_v2/drivers/grok.py` | retired to compatibility shim at consultation_v2/drivers/grok.py:3; canonical implementation is consultation_v2/platforms/grok/driver.py:2851. |
| `consultation_v2/orchestrator.py` | touched to register package Grok driver at consultation_v2/orchestrator.py:35; orchestration identity/notify/storage remains shared. |
| `consultation_v2/platforms/grok.yaml` | moved from flat YAML path to package-owned YAML; `git log --follow` retained here for the former path as requested. |
| `consultation_v2/platforms/grok/grok.yaml` | package-owned YAML at consultation_v2/platforms/grok/grok.yaml:1; loader prefers package YAML via consultation_v2/yaml_contract.py:243. |
| `consultation_v2/platforms/grok/driver.py` | new canonical package driver at consultation_v2/platforms/grok/driver.py:2851; includes package-local lifecycle base at consultation_v2/platforms/grok/driver.py:38. |
| `consultation_v2/platforms/grok/monitor.py` | new package monitor at consultation_v2/platforms/grok/monitor.py:48. |
| `consultation_v2/yaml_contract.py` | touched so `platform_yaml_path` prefers package YAML at consultation_v2/yaml_contract.py:243. |
| `consultation_v2/validators/lint_consultation_v2_contract.py` | touched to include nested package YAML via recursive discovery at consultation_v2/validators/lint_consultation_v2_contract.py:60. |
| `consultation_v2/validators/lint_exact_match.py` | touched to include nested package YAML via recursive discovery at consultation_v2/validators/lint_exact_match.py:40. |
| `consultation_v2/validators/lint_no_yaml_silent_fallbacks.py` | touched to include nested package YAML via recursive discovery at consultation_v2/validators/lint_no_yaml_silent_fallbacks.py:91. |
| `consultation_v2/runtime.py` | retained as shared mechanical runtime primitive; residue classification is recorded in RESIDUE_AUDIT.md. |
| `consultation_v2/snapshot.py` | retained as shared mechanical snapshot/matcher primitive; residue classification is recorded in RESIDUE_AUDIT.md. |
| `consultation_v2/planner.py` | retained as shared YAML-data-driven selection planner; residue classification is recorded in RESIDUE_AUDIT.md. |
| `consultation_v2/interact.py` | retained as shared raw click/cache primitive; package does not import it directly. |
| `consultation_v2/primitives.py` | retained as shared lock/run-state/storage primitive module; source documents platform as opaque data. |
| `consultation_v2/platforms_runtime.py` | reclassified as orchestrator/display-allocation runtime; Grok package does not import it directly. |
| `consultation_v2/input.py` | conditionally-leaf residue remains in switch_to_platform; this branch records the gap instead of silently calling it eliminated. |
| `consultation_v2/atspi.py` | conditionally-leaf residue remains in URL-to-platform routing helpers; this branch records the gap instead of silently calling it eliminated. |
| `consultation_v2/cli.py` | retained as shared CLI/orchestration entrypoint; no Grok package import required. |

## Full History Logs

### consultation_v2/drivers/base.py
Disposition: inlined into package-local lifecycle base at consultation_v2/platforms/grok/driver.py:38; package does not import drivers.base.

Full history (`git log --follow --oneline -- consultation_v2/drivers/base.py`):
```text
d9c1de09 Enforce dead session poison after notify
365b9663 Fix ChatGPT mode active proof
9a0e083a Stabilize hover selection menu lifecycle
f6dc70b2 Route hover selection reveals through menu snapshot
f87e0de8 Remove dynamic picker label selection shortcut
5746f250 Quarantine setup-complete duplicate sends
c268625a Disable consult external storage by default
a7983c82 Capture Grok send-created answer thread after redirect
2ef15351 fix(consult-monitor): root-cause false generation_stalled — thread mode + gate stop-absence on healthy read (#4)
55b04b36 Allow benign base conformance extras
a4201f0c Anti-echo guard: reject prompt-echo extractions, never deliver as response
a228d2db Poll/settle hardening for racy single-shot UI checks (gemini select, grok fresh-chat)
37a41c4c Restore Grok menu selection after Claude hardening
dc90db7b Fix Claude Ctrl-T navigation and model selection
c4557886 Fix Claude app-root model selection scope
a89566d0 Revert "claude-select-fix: Map Claude model menu to app_root_snapshot with settle to prevent React-portal dismissal"
dca59fa6 claude-select-fix: Map Claude model menu to app_root_snapshot with settle to prevent React-portal dismissal
5de5c6dd Key dispatch locks by target display
e132bf15 Pin monitor to submitted answer thread
38238303 Handle connector permission modals during monitor
9c4e41b4 F1 nit: move DEEP_GENERATION_FLOOR_SECONDS below imports (PEP8, gate non-blocking note)
37bd3485 F1: per-mode monitor timeout floor + wire generation_stalled (no content heuristic)
fca0f1af Limit page readiness to composer controls
afee8c40 Poll Perplexity readiness after navigation
c689420e Poll selection anchors after menu open
a5abb484 Fix reliability readiness gates
0cf77845 Add display watchdog pause heartbeat
60f548b0 Migrate Perplexity mode selection to shared plan
43a45a97 Migrate Grok model selection to shared plan
d56aec1d Fix Gemini selected model and Deep Think path
ff99bf2e Migrate Gemini selection to shared plan
2f5b132d Poll popup recovery until drift clears
6bba6d67 Recover popup drift from unknown dismiss controls
4adf45ac Fix Claude send blocked false success
f4aa19a4 Add post-navigation page readiness gate
62fe841e Ignore incidental DOM noise in base conformance
047016d6 Wait for Claude menu targets before selection
12fe825f Harden settle and popup recovery
775774b4 Stabilize Claude proof tree reads
bee59dda Fix central dispatch integrity gates
326bc9b1 Fix conditional selection menu settle
78130479 WIP probe inter-menu settle
9b97796e Wait for selection path reveals
c9efa7b5 Require base composer anchor before conformance settles
0120e434 Settle selection validation before miss
3a9232c0 Stabilize ChatGPT base conformance
d1ce22dd Gate selection plan before driver browser entry
f7e51f3e Implement plan-phase selection menus
d6317a4a Support nested ChatGPT Pro effort selection
bb36a6f9 Rebuild ChatGPT YAML as strict identity schema
796a3e6f Gate consultations on tree conformance
143695b0 Validate ChatGPT extraction hover by composer anchor
f763ac50 Capture ChatGPT answer thread URL after send
55cf6d88 Fix consultation extraction and stop-only monitor
a5a92df9 Improve Claude and ChatGPT monitor extraction
93ddc899 Fix round two live consultation defects
8bd55e7d Fix consultation contract gate regressions
119af8f0 Fix tree validation and Perplexity DR extraction
85df3b9a Enforce tree-validated consultation actions
ee425477 p2-dispatch-lock: per-display setup/send serialization that does not block concurrent monitors
f991d951 p2-run-state-idempotency: durable run-state checkpoints + resume guard so a re-run never double-dispatches a landed send
7b6a110b p2-shared-primitives: canonical shared-primitive surface for consultation_v2
19956810 fix(consult-v2 D2): unify completion detection into one shared stop-transition detector
bd5e4c48 fix(v2): stop-gone monitoring and file-chip attach verification
d4b09dc4 Refactor consultation_v2 drivers to use YAML validation specs for mode-active detection.
de248ee8 Refactor consultation_v2 drivers to be YAML-only with zero platform knowledge. All mode-active detection moved to YAML validation specs.
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/completion.py
Disposition: inlined into package-local monitor at consultation_v2/platforms/grok/monitor.py:48; package does not import completion.

Full history (`git log --follow --oneline -- consultation_v2/completion.py`):
```text
fea887b9 Fix Claude Max completion gate
55cf6d88 Fix consultation extraction and stop-only monitor
19956810 fix(consult-v2 D2): unify completion detection into one shared stop-transition detector
```

### consultation_v2/drivers/__init__.py
Disposition: touched to re-export package-owned Grok driver at consultation_v2/drivers/__init__.py:5.

Full history (`git log --follow --oneline -- consultation_v2/drivers/__init__.py`):
```text
81d3d921 Extract Grok platform package
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/drivers/grok.py
Disposition: retired to compatibility shim at consultation_v2/drivers/grok.py:3; canonical implementation is consultation_v2/platforms/grok/driver.py:2851.

Full history (`git log --follow --oneline -- consultation_v2/drivers/grok.py`):
```text
81d3d921 Extract Grok platform package
c268625a Disable consult external storage by default
4c4985c7 Fail loud when Grok send creates no thread
eb1b8144 Log and bound Grok setup steps
0d120a25 Bound Grok setup before send
a7983c82 Capture Grok send-created answer thread after redirect
7add819b Guard stale ChatGPT and Grok extraction
ba634109 Settle Grok extraction readiness
a4201f0c Anti-echo guard: reject prompt-echo extractions, never deliver as response
a228d2db Poll/settle hardening for racy single-shot UI checks (gemini select, grok fresh-chat)
6a9a4955 Harden Grok extraction against prompt copy
deb92f19 Fix consult navigation address bar handling
8fa80db0 Relax Grok fresh composer empty detection
2c958949 Harden consult engine selection and navigation
7c10436f Fix Grok fresh-chat readiness for blind input
00eeef3d Harden consultation contract gates
43a45a97 Migrate Grok model selection to shared plan
f4aa19a4 Add post-navigation page readiness gate
f7e51f3e Implement plan-phase selection menus
9e3dcdd4 Fix ChatGPT submit retry and selection targets
85df3b9a Enforce tree-validated consultation actions
ee425477 p2-dispatch-lock: per-display setup/send serialization that does not block concurrent monitors
f991d951 p2-run-state-idempotency: durable run-state checkpoints + resume guard so a re-run never double-dispatches a landed send
19956810 fix(consult-v2 D2): unify completion detection into one shared stop-transition detector
8670fd19 fix(grok): settle+rescan before attach-trigger scan (was premature-scan false 'missing')
0f76bbec p1-grok: revert send to proven coord-click+grab_focus+Return (LIVE :5)
2421ddd6 fix(send-detect): fresh current_url + EITHER-signal send gate (LIVE :5)
aa59dee9 p1-grok: bounded clipboard-populate wait after copy click (LIVE :5)
c41f39ce p1-grok: send via exact Submit button, not Enter (multi-line composer) (LIVE :5)
998aa421 p1-grok: comprehensive §E readiness waits at all UI-transition points (LIVE :5)
d712535f p1-grok: add bounded readiness wait before attach-present validation (LIVE :5)
1310a835 p1-grok: add bounded post-navigate readiness wait before mode-select (LIVE :5)
f21b9966 p1-grok: fix attach-present validation to the exact static remove button (LIVE :5)
90de2d6b p1-grok step2: rebuild isolated grok driver + exact-match YAML
846879f4 feat(v2): full consultation pipeline — plan, identity, extract, store, notify
17ca68da fix(all-drivers): remove second Return press in attach — was hitting chat input
0b4453b4 fix(all-drivers): close stale file dialogs before attach and connector toggle
889a9f04 fix(grok.py): attach uses menu_snapshot for dropdown items, proper wait timing
eba8b9ba fix(grok.py): add wait after file dialog close before attach validation
c90ae7ed fix(all-drivers): send_prompt URL gate uses original navigation URL (same as Perplexity fix)
9c0e7941 fix(all-drivers): restore URL gate for new sessions — URL change required for send confirmation
4cc14b84 fix(grok): align YAML with AT-SPI scan, fix driver dropdown close and click strategy (Chat-validated)
d4b09dc4 Refactor consultation_v2 drivers to use YAML validation specs for mode-active detection.
de248ee8 Refactor consultation_v2 drivers to be YAML-only with zero platform knowledge. All mode-active detection moved to YAML validation specs.
0268e8eb fix: remove 41 hardcoded strategy='coordinate_only' — use YAML click_strategy
f2f953aa fix: Grok monitor — handle response completing before monitor starts
4849b27b fix: Grok send — check stop_button OR copy_button (fast responses)
169665b1 fix: Grok send — stop button only gate, remove URL requirement
2d2e97b6 revert: undo Codex synthesis commits that regressed working platforms
6338a79f feat(consultation-v2): synthesize 3 audits; apply robust send validation and ChatGPT model selection
175bd82e fix(consultation-v2): apply Perplexity deep research fixes to Grok, Perplexity, and ChatGPT drivers
f65d45fb fix: exact match YAMLs + strip all fallback logic from drivers
d0f3acf3 fix: Grok prompt trust paste, Perplexity use snapshot for tools, runtime switch fallback
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/orchestrator.py
Disposition: touched to register package Grok driver at consultation_v2/orchestrator.py:35; orchestration identity/notify/storage remains shared.

Full history (`git log --follow --oneline -- consultation_v2/orchestrator.py`):
```text
81d3d921 Extract Grok platform package
31adc87c Rebase W1E notification delivery parking
d9c1de09 Enforce dead session poison after notify
9761aee0 Wire second consult display routing
c268625a Disable consult external storage by default
8345adc0 Inline ChatGPT identity context
a4201f0c Anti-echo guard: reject prompt-echo extractions, never deliver as response
2da240dd Fix Claude large-packet delivery gate
7799dda2 Deliver full consultation notifications
1f7b4312 Add caller-only consultation attachment mode
bee59dda Fix central dispatch integrity gates
f7e51f3e Implement plan-phase selection menus
ed98902c Gate consultations on display readiness
6ea4619f Archive legacy consultation surfaces into V2
f991d951 p2-run-state-idempotency: durable run-state checkpoints + resume guard so a re-run never double-dispatches a landed send
8c80d11d p2-intake-identity: fail-loud identity packaging + caller-attachment provenance
634f3099 fix(consult-v2): route FAILURE notifications to the operator, never the requester
826cf48e fix(notify): stamp requester+purpose into completion payload; loud orphan warning
846879f4 feat(v2): full consultation pipeline — plan, identity, extract, store, notify
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/platforms/grok.yaml
Disposition: moved from flat YAML path to package-owned YAML; `git log --follow` retained here for the former path as requested.

Full history (`git log --follow --oneline -- consultation_v2/platforms/grok.yaml`):
```text
81d3d921 Extract Grok platform package
4212d8ec Wire generation-stalled monitor timeout
0d120a25 Bound Grok setup before send
a228d2db Poll/settle hardening for racy single-shot UI checks (gemini select, grok fresh-chat)
deb92f19 Fix consult navigation address bar handling
37a41c4c Restore Grok menu selection after Claude hardening
7c10436f Fix Grok fresh-chat readiness for blind input
43a45a97 Migrate Grok model selection to shared plan
32291300 Filter Firefox context menus from menu snapshots
8bd55e7d Fix consultation contract gate regressions
9e3dcdd4 Fix ChatGPT submit retry and selection targets
3b391701 p4-extraction-yaml-schema: extraction-by-output-type YAML schema + strict load-validation
23887997 fix(v2): close audit-fix selector drift set
39ea4154 fix(v2): align exact consultation maps
c4b15533 fix(consultation_v2): tune settle timings per platform
87db181e fix(consultation_v2): add contract gate and settle timing
52b54414 task-164: preserve AT-SPI bus capture worktree changes
c41f39ce p1-grok: send via exact Submit button, not Enter (multi-line composer) (LIVE :5)
ef5ef966 p1-grok: fix composer input to exact entry 'Ask Grok anything' (LIVE :5)
f21b9966 p1-grok: fix attach-present validation to the exact static remove button (LIVE :5)
90de2d6b p1-grok step2: rebuild isolated grok driver + exact-match YAML
dae921a8 build(p0-gate): add consultation_v2 mechanical integrity gate
aec5990a feat(connectors): map + YAML for GitHub connector cycle step (4/5 platforms)
12962741 fix(grok): align model menu labels with live UI
846879f4 feat(v2): full consultation pipeline — plan, identity, extract, store, notify
4cc14b84 fix(grok): align YAML with AT-SPI scan, fix driver dropdown close and click strategy (Chat-validated)
fdc8a408 fix(consultation_v2): update upload element names and roles to match exact AT-SPI scans
d4b09dc4 Refactor consultation_v2 drivers to use YAML validation specs for mode-active detection.
8f439213 fix: copy_button name_contains (buttons have variable names: Copy, Copy response, Copy message)
d31f67a9 fix: fence_after disabled for grok, mode-skip for all drivers, perplexity Return send
f65d45fb fix: exact match YAMLs + strip all fallback logic from drivers
cf87c1ef fix: align v2 YAMLs to live AT-SPI elements + fix ChatGPT driver
4243afb4 fix: align consultation_v2 platform YAML element_maps with production ground truth
ee179b1d fix: align consultation_v2 platform YAMLs with production
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/platforms/grok/grok.yaml
Disposition: package-owned YAML at consultation_v2/platforms/grok/grok.yaml:1; loader prefers package YAML via consultation_v2/yaml_contract.py:243.

Full history (`git log --follow --oneline -- consultation_v2/platforms/grok/grok.yaml`):
```text
81d3d921 Extract Grok platform package
4212d8ec Wire generation-stalled monitor timeout
0d120a25 Bound Grok setup before send
a228d2db Poll/settle hardening for racy single-shot UI checks (gemini select, grok fresh-chat)
deb92f19 Fix consult navigation address bar handling
37a41c4c Restore Grok menu selection after Claude hardening
7c10436f Fix Grok fresh-chat readiness for blind input
43a45a97 Migrate Grok model selection to shared plan
32291300 Filter Firefox context menus from menu snapshots
8bd55e7d Fix consultation contract gate regressions
9e3dcdd4 Fix ChatGPT submit retry and selection targets
3b391701 p4-extraction-yaml-schema: extraction-by-output-type YAML schema + strict load-validation
23887997 fix(v2): close audit-fix selector drift set
39ea4154 fix(v2): align exact consultation maps
c4b15533 fix(consultation_v2): tune settle timings per platform
87db181e fix(consultation_v2): add contract gate and settle timing
52b54414 task-164: preserve AT-SPI bus capture worktree changes
c41f39ce p1-grok: send via exact Submit button, not Enter (multi-line composer) (LIVE :5)
ef5ef966 p1-grok: fix composer input to exact entry 'Ask Grok anything' (LIVE :5)
f21b9966 p1-grok: fix attach-present validation to the exact static remove button (LIVE :5)
90de2d6b p1-grok step2: rebuild isolated grok driver + exact-match YAML
dae921a8 build(p0-gate): add consultation_v2 mechanical integrity gate
aec5990a feat(connectors): map + YAML for GitHub connector cycle step (4/5 platforms)
12962741 fix(grok): align model menu labels with live UI
846879f4 feat(v2): full consultation pipeline — plan, identity, extract, store, notify
4cc14b84 fix(grok): align YAML with AT-SPI scan, fix driver dropdown close and click strategy (Chat-validated)
fdc8a408 fix(consultation_v2): update upload element names and roles to match exact AT-SPI scans
d4b09dc4 Refactor consultation_v2 drivers to use YAML validation specs for mode-active detection.
8f439213 fix: copy_button name_contains (buttons have variable names: Copy, Copy response, Copy message)
d31f67a9 fix: fence_after disabled for grok, mode-skip for all drivers, perplexity Return send
f65d45fb fix: exact match YAMLs + strip all fallback logic from drivers
cf87c1ef fix: align v2 YAMLs to live AT-SPI elements + fix ChatGPT driver
4243afb4 fix: align consultation_v2 platform YAML element_maps with production ground truth
ee179b1d fix: align consultation_v2 platform YAMLs with production
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/platforms/grok/driver.py
Disposition: new canonical package driver at consultation_v2/platforms/grok/driver.py:2851; includes package-local lifecycle base at consultation_v2/platforms/grok/driver.py:38.

Full history (`git log --follow --oneline -- consultation_v2/platforms/grok/driver.py`):
```text
81d3d921 Extract Grok platform package
d9c1de09 Enforce dead session poison after notify
365b9663 Fix ChatGPT mode active proof
9a0e083a Stabilize hover selection menu lifecycle
f6dc70b2 Route hover selection reveals through menu snapshot
f87e0de8 Remove dynamic picker label selection shortcut
5746f250 Quarantine setup-complete duplicate sends
c268625a Disable consult external storage by default
a7983c82 Capture Grok send-created answer thread after redirect
2ef15351 fix(consult-monitor): root-cause false generation_stalled — thread mode + gate stop-absence on healthy read (#4)
55b04b36 Allow benign base conformance extras
a4201f0c Anti-echo guard: reject prompt-echo extractions, never deliver as response
a228d2db Poll/settle hardening for racy single-shot UI checks (gemini select, grok fresh-chat)
37a41c4c Restore Grok menu selection after Claude hardening
dc90db7b Fix Claude Ctrl-T navigation and model selection
c4557886 Fix Claude app-root model selection scope
a89566d0 Revert "claude-select-fix: Map Claude model menu to app_root_snapshot with settle to prevent React-portal dismissal"
dca59fa6 claude-select-fix: Map Claude model menu to app_root_snapshot with settle to prevent React-portal dismissal
5de5c6dd Key dispatch locks by target display
e132bf15 Pin monitor to submitted answer thread
38238303 Handle connector permission modals during monitor
9c4e41b4 F1 nit: move DEEP_GENERATION_FLOOR_SECONDS below imports (PEP8, gate non-blocking note)
37bd3485 F1: per-mode monitor timeout floor + wire generation_stalled (no content heuristic)
fca0f1af Limit page readiness to composer controls
afee8c40 Poll Perplexity readiness after navigation
c689420e Poll selection anchors after menu open
a5abb484 Fix reliability readiness gates
0cf77845 Add display watchdog pause heartbeat
60f548b0 Migrate Perplexity mode selection to shared plan
43a45a97 Migrate Grok model selection to shared plan
d56aec1d Fix Gemini selected model and Deep Think path
ff99bf2e Migrate Gemini selection to shared plan
2f5b132d Poll popup recovery until drift clears
6bba6d67 Recover popup drift from unknown dismiss controls
4adf45ac Fix Claude send blocked false success
f4aa19a4 Add post-navigation page readiness gate
62fe841e Ignore incidental DOM noise in base conformance
047016d6 Wait for Claude menu targets before selection
12fe825f Harden settle and popup recovery
775774b4 Stabilize Claude proof tree reads
bee59dda Fix central dispatch integrity gates
326bc9b1 Fix conditional selection menu settle
78130479 WIP probe inter-menu settle
9b97796e Wait for selection path reveals
c9efa7b5 Require base composer anchor before conformance settles
0120e434 Settle selection validation before miss
3a9232c0 Stabilize ChatGPT base conformance
d1ce22dd Gate selection plan before driver browser entry
f7e51f3e Implement plan-phase selection menus
d6317a4a Support nested ChatGPT Pro effort selection
bb36a6f9 Rebuild ChatGPT YAML as strict identity schema
796a3e6f Gate consultations on tree conformance
143695b0 Validate ChatGPT extraction hover by composer anchor
f763ac50 Capture ChatGPT answer thread URL after send
55cf6d88 Fix consultation extraction and stop-only monitor
a5a92df9 Improve Claude and ChatGPT monitor extraction
93ddc899 Fix round two live consultation defects
8bd55e7d Fix consultation contract gate regressions
119af8f0 Fix tree validation and Perplexity DR extraction
85df3b9a Enforce tree-validated consultation actions
ee425477 p2-dispatch-lock: per-display setup/send serialization that does not block concurrent monitors
f991d951 p2-run-state-idempotency: durable run-state checkpoints + resume guard so a re-run never double-dispatches a landed send
7b6a110b p2-shared-primitives: canonical shared-primitive surface for consultation_v2
19956810 fix(consult-v2 D2): unify completion detection into one shared stop-transition detector
bd5e4c48 fix(v2): stop-gone monitoring and file-chip attach verification
d4b09dc4 Refactor consultation_v2 drivers to use YAML validation specs for mode-active detection.
de248ee8 Refactor consultation_v2 drivers to be YAML-only with zero platform knowledge. All mode-active detection moved to YAML validation specs.
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/platforms/grok/monitor.py
Disposition: new package monitor at consultation_v2/platforms/grok/monitor.py:48.

Full history (`git log --follow --oneline -- consultation_v2/platforms/grok/monitor.py`):
```text
81d3d921 Extract Grok platform package
fea887b9 Fix Claude Max completion gate
55cf6d88 Fix consultation extraction and stop-only monitor
19956810 fix(consult-v2 D2): unify completion detection into one shared stop-transition detector
```

### consultation_v2/yaml_contract.py
Disposition: touched so `platform_yaml_path` prefers package YAML at consultation_v2/yaml_contract.py:243.

Full history (`git log --follow --oneline -- consultation_v2/yaml_contract.py`):
```text
81d3d921 Extract Grok platform package
365b9663 Fix ChatGPT mode active proof
c4557886 Fix Claude app-root model selection scope
00eeef3d Harden consultation contract gates
60f548b0 Migrate Perplexity mode selection to shared plan
43a45a97 Migrate Grok model selection to shared plan
d56aec1d Fix Gemini selected model and Deep Think path
ff99bf2e Migrate Gemini selection to shared plan
f7e51f3e Implement plan-phase selection menus
d6317a4a Support nested ChatGPT Pro effort selection
bb36a6f9 Rebuild ChatGPT YAML as strict identity schema
119af8f0 Fix tree validation and Perplexity DR extraction
3b391701 p4-extraction-yaml-schema: extraction-by-output-type YAML schema + strict load-validation
60cdc844 Enforce strict consultation_v2 YAML loading
87db181e fix(consultation_v2): add contract gate and settle timing
4ce12451 feat(consultation_v2): add reddit and nvidia_forum platforms
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/validators/lint_consultation_v2_contract.py
Disposition: touched to include nested package YAML via recursive discovery at consultation_v2/validators/lint_consultation_v2_contract.py:60.

Full history (`git log --follow --oneline -- consultation_v2/validators/lint_consultation_v2_contract.py`):
```text
81d3d921 Extract Grok platform package
00eeef3d Harden consultation contract gates
6ea4619f Archive legacy consultation surfaces into V2
23887997 fix(v2): close audit-fix selector drift set
87db181e fix(consultation_v2): add contract gate and settle timing
```

### consultation_v2/validators/lint_exact_match.py
Disposition: touched to include nested package YAML via recursive discovery at consultation_v2/validators/lint_exact_match.py:40.

Full history (`git log --follow --oneline -- consultation_v2/validators/lint_exact_match.py`):
```text
81d3d921 Extract Grok platform package
00eeef3d Harden consultation contract gates
6ea4619f Archive legacy consultation surfaces into V2
90de2d6b p1-grok step2: rebuild isolated grok driver + exact-match YAML
5b199551 infra(drivers): exact-match lint + pre-commit gate + driver-rebuild plan (p0)
```

### consultation_v2/validators/lint_no_yaml_silent_fallbacks.py
Disposition: touched to include nested package YAML via recursive discovery at consultation_v2/validators/lint_no_yaml_silent_fallbacks.py:91.

Full history (`git log --follow --oneline -- consultation_v2/validators/lint_no_yaml_silent_fallbacks.py`):
```text
81d3d921 Extract Grok platform package
00eeef3d Harden consultation contract gates
6ea4619f Archive legacy consultation surfaces into V2
206deac9 fix(p0-gate): strip comments before pass/finally checks
dae921a8 build(p0-gate): add consultation_v2 mechanical integrity gate
```

### consultation_v2/runtime.py
Disposition: retained as shared mechanical runtime primitive; residue classification is recorded in RESIDUE_AUDIT.md.

Full history (`git log --follow --oneline -- consultation_v2/runtime.py`):
```text
9761aee0 Wire second consult display routing
46fed0f5 Require populated tree after navigation settle
2f80f252 Settle navigation before URL verification
a591ac8a Fix URL navigation for unobservable address bar
deb92f19 Fix consult navigation address bar handling
dc90db7b Fix Claude Ctrl-T navigation and model selection
c4557886 Fix Claude app-root model selection scope
a89566d0 Revert "claude-select-fix: Map Claude model menu to app_root_snapshot with settle to prevent React-portal dismissal"
dca59fa6 claude-select-fix: Map Claude model menu to app_root_snapshot with settle to prevent React-portal dismissal
257c1c83 F3b: extract Gemini DR full report via app_root_snapshot (menu_snapshot is blind to the Share&Export popover)
2c3082dd Poll for GTK file dialog focus
6bba6d67 Recover popup drift from unknown dismiss controls
ee113f66 Submit Claude file dialog with Return
96345143 Use Claude file upload for attachments
047016d6 Wait for Claude menu targets before selection
12fe825f Harden settle and popup recovery
775774b4 Stabilize Claude proof tree reads
78130479 WIP probe inter-menu settle
c9efa7b5 Require base composer anchor before conformance settles
0120e434 Settle selection validation before miss
3a9232c0 Stabilize ChatGPT base conformance
6ea4619f Archive legacy consultation surfaces into V2
55cf6d88 Fix consultation extraction and stop-only monitor
bf742518 fix(extract): scroll to ABSOLUTE bottom every time + reject prompt echo
0a60613b fix(perplexity): scroll Copy button into view before action (empty-clipboard fix)
582992a9 fix(extract): scroll-to-bottom before extract on all chat drivers (the RULE)
8b6a0955 fix(chatgpt): focus_firefox() before send Enter — post-attach X focus loss
87db181e fix(consultation_v2): add contract gate and settle timing
2421ddd6 fix(send-detect): fresh current_url + EITHER-signal send gate (LIVE :5)
2bd9c6c4 fix(navigate): close stale dialogs + longer settles + target-confirm (LIVE :5)
094c39bf fix(v2): YAML drift fixes, F6 navigation for Claude, desktop cache clear
846879f4 feat(v2): full consultation pipeline — plan, identity, extract, store, notify
a27c08d1 fix(runtime.py): add write_clipboard method — needed for clipboard clearing before extract
1ea9d178 feat(runtime.py): add close_stale_dialogs method for file dialog cleanup
d0f3acf3 fix: Grok prompt trust paste, Perplexity use snapshot for tools, runtime switch fallback
83dc6901 fix: clipboard.read() not read_text(), add PYTHONPATH to script
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/snapshot.py
Disposition: retained as shared mechanical snapshot/matcher primitive; residue classification is recorded in RESIDUE_AUDIT.md.

Full history (`git log --follow --oneline -- consultation_v2/snapshot.py`):
```text
257c1c83 F3b: extract Gemini DR full report via app_root_snapshot (menu_snapshot is blind to the Share&Export popover)
9404b53e Restore Perplexity structural input locator
d56aec1d Fix Gemini selected model and Deep Think path
32291300 Filter Firefox context menus from menu snapshots
74bfad0c Fix Claude attach portal scope
d6317a4a Support nested ChatGPT Pro effort selection
bb36a6f9 Rebuild ChatGPT YAML as strict identity schema
796a3e6f Gate consultations on tree conformance
f125b527 Scope ChatGPT snapshots to page content
6ea4619f Archive legacy consultation surfaces into V2
60cdc844 Enforce strict consultation_v2 YAML loading
93e1077b feat(snapshot): prune Firefox chrome subtrees on app-root scans
23887997 fix(v2): close audit-fix selector drift set
90de2d6b p1-grok step2: rebuild isolated grok driver + exact-match YAML
846879f4 feat(v2): full consultation pipeline — plan, identity, extract, store, notify
66f0becc fix(snapshot.py): add toggle button to menu_snapshot supplement roles
569e238e fix(snapshot.py): always supplement find_menu_items with find_elements — fixes partial results
ad137e07 fix(snapshot.py): build_menu_snapshot scans from firefox root, not document — fixes portal visibility
d4b09dc4 Refactor consultation_v2 drivers to use YAML validation specs for mode-active detection.
dd3a7fa3 fix: Perplexity Deep Research — handle document loss after mode toggle
cf87c1ef fix: align v2 YAMLs to live AT-SPI elements + fix ChatGPT driver
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```

### consultation_v2/planner.py
Disposition: retained as shared YAML-data-driven selection planner; residue classification is recorded in RESIDUE_AUDIT.md.

Full history (`git log --follow --oneline -- consultation_v2/planner.py`):
```text
365b9663 Fix ChatGPT mode active proof
2c958949 Harden consult engine selection and navigation
60f548b0 Migrate Perplexity mode selection to shared plan
ff99bf2e Migrate Gemini selection to shared plan
f7e51f3e Implement plan-phase selection menus
```

### consultation_v2/interact.py
Disposition: retained as shared raw click/cache primitive; package does not import it directly.

Full history (`git log --follow --oneline -- consultation_v2/interact.py`):
```text
6ea4619f Archive legacy consultation surfaces into V2
90ef4294 cherry-pick fc9f8d4
fc9f8d48 fix: int() cast for coordinate comparison in interact.py and click.py
34f69c2c revert: restore core/interact, core/tree, tools/attach, tools/click, tools/extract to a431799
a05430a4 fix: cast element x,y to int in find_element_at — prevents TypeError
119c115b fix: P0/P1 audit fixes — path traversal, validation gate, status mismatch, cache staleness
31412321 feat: v7 fresh rebuild — 54% LOC reduction (9,309 → 4,252 lines)
```

### consultation_v2/primitives.py
Disposition: retained as shared lock/run-state/storage primitive module; source documents platform as opaque data.

Full history (`git log --follow --oneline -- consultation_v2/primitives.py`):
```text
d9c1de09 Enforce dead session poison after notify
c268625a Disable consult external storage by default
2322877a Make display lock acquisition non-stealing
5de5c6dd Key dispatch locks by target display
cea626be Fix orphaned display lock reclaim
bee59dda Fix central dispatch integrity gates
7b6a110b p2-shared-primitives: canonical shared-primitive surface for consultation_v2
```

### consultation_v2/platforms_runtime.py
Disposition: reclassified as orchestrator/display-allocation runtime; Grok package does not import it directly.

Full history (`git log --follow --oneline -- consultation_v2/platforms_runtime.py`):
```text
9761aee0 Wire second consult display routing
7820b510 Harden display deploy installer
acac31dc Scrub public-prep hardcoded defaults
6ea4619f Archive legacy consultation surfaces into V2
6253b7c8 fix(display): harden AT-SPI bus capture and firefox path
4ce12451 feat(consultation_v2): add reddit and nvidia_forum platforms
830ed1a7 fix: AT-SPI bus race + URL_PATTERNS for treasurer platforms
89b45342 fix: multi-display routing for attach, inspect, plan audit
753a9d10 feat: training_gen_bot + multi-display MCP support
31412321 feat: v7 fresh rebuild — 54% LOC reduction (9,309 → 4,252 lines)
c4acd4e0 fix: use regular ChatGPT URL instead of temporary-chat (file expiry root cause)
dda4bf2e fix: ChatGPT fresh_session navigates to temporary-chat URL
cad3c3b2 fix: worker 4-tab layout — ChatGPT, Claude, Gemini, Grok (Alt+1-4)
ef06ca91 fix: worker 3-platform support — Grok tab mapping, URL detection, hook unblock
385cc5f8 feat: macOS support via AXUIElement accessibility API
afe54260 feat: multi-instance support + platform YAML updates
3da7eb35 fix: lazy screen detection + DISPLAY env for MCP server
bae88f5d fix: remove moderate fallback mechanisms across core/storage/tools
3755ac25 fix: Gemini audit fixes - defunct check, no matching, map invalidation
fd30ba90 fix: dynamic screen detection + full operational context for multi-machine deployment
8574194f feat: v5.0 clean rebuild - AT-SPI modular architecture
```

### consultation_v2/input.py
Disposition: conditionally-leaf residue remains in switch_to_platform; this branch records the gap instead of silently calling it eliminated.

Full history (`git log --follow --oneline -- consultation_v2/input.py`):
```text
9761aee0 Wire second consult display routing
047016d6 Wait for Claude menu targets before selection
6ea4619f Archive legacy consultation surfaces into V2
fd37b73c fix(perplexity,input): harden DR search toggle and PID fallback
039581da fix(x_reply): scroll-into-band + focus_clear_paste posting primitive (vendored, reconciled to core.input)
fc9bf22e Fix multi-display platform tab verification
28ea5a5d feat: V3 tracker, SFT bot overhaul, multi-display fixes, consultation groundwork
753a9d10 feat: training_gen_bot + multi-display MCP support
08d192f7 revert: roll back all changes since a431799 — restore last known good state
533c41e0 feat: Xvfb support — auto-detect virtual display, use xdotool type for UI
1b09b9f6 fix: find_firefox() handles multiple instances via platform param
52060916 fix: require Redis, YAML-driven platform ops, strip identity files
dae4afb7 fix: focus_firefox tries all window IDs instead of just last
c28263bb fix: use --class Firefox instead of --name for window detection
75677f20 fix: focus_firefox uses windowfocus fallback for bare Xvfb
614ca116 fix: ChatGPT send fallback + wmctrl focus for GNOME Shell
31412321 feat: v7 fresh rebuild — 54% LOC reduction (9,309 → 4,252 lines)
862f52c6 fix: focus_firefox uses last window ID, skip Firefox helper windows
2b59b21a fix: split Enter keydown/keyup in keyboard_nav attach to prevent GTK dialog auto-confirm
ff7825c7 fix: 5-platform audit findings — clipboard lock, FD leak, injection, path sandboxing
e5a75b2c fix: switch_to_platform uses URL+SHOWING state, trusts Alt+N
d90e3aff fix: Ctrl+Tab fallback for tab switching when Alt+N is intercepted by WM
16738af3 simplify: consolidate inputs, unify clipboard, detect attachments (-610 lines)
8574194f feat: v5.0 clean rebuild - AT-SPI modular architecture
```

### consultation_v2/atspi.py
Disposition: conditionally-leaf residue remains in URL-to-platform routing helpers; this branch records the gap instead of silently calling it eliminated.

Full history (`git log --follow --oneline -- consultation_v2/atspi.py`):
```text
6ea4619f Archive legacy consultation surfaces into V2
5b581e95 cleanup: remove RemoteFirefox/subprocess_scan dead code (#40)
89b45342 fix: multi-display routing for attach, inspect, plan audit
753a9d10 feat: training_gen_bot + multi-display MCP support
9a3dac84 fix: v8.2 stabilization — Redis fail-fast, display detection, plan TTL, auto-ingest
1b09b9f6 fix: find_firefox() handles multiple instances via platform param
d38a6540 fix: filter AT-SPI by Firefox PID to prevent cross-display contamination
52060916 fix: require Redis, YAML-driven platform ops, strip identity files
2a472df4 feat: multi-Firefox AT-SPI support for parallel HMM
31412321 feat: v7 fresh rebuild — 54% LOC reduction (9,309 → 4,252 lines)
bf92722a fix: deeper file dialog detection + skip re-click when dialog already open
ef06ca91 fix: worker 3-platform support — Grok tab mapping, URL detection, hook unblock
b04fdddc fix: 4 bugs from audit cycle — tmux injection, multi-tab, SHOWING filter, attach
ce18864b fix: Python 3.9 compat for all tool and core files
c87d9bdb fix: retry find_firefox with AT-SPI cache clear on stale D-Bus proxy
8b59d297 fix: restore platform-aware click strategy, fix detect_display, revert dangerous file dialog code
bae88f5d fix: remove moderate fallback mechanisms across core/storage/tools
8574194f feat: v5.0 clean rebuild - AT-SPI modular architecture
```

### consultation_v2/cli.py
Disposition: retained as shared CLI/orchestration entrypoint; no Grok package import required.

Full history (`git log --follow --oneline -- consultation_v2/cli.py`):
```text
c268625a Disable consult external storage by default
838421fd Add dry-run consultation dispatch guard
1f7b4312 Add caller-only consultation attachment mode
f7e51f3e Implement plan-phase selection menus
846879f4 feat(v2): full consultation pipeline — plan, identity, extract, store, notify
49e4a76b feat(perplexity): add connector toggle method + CLI flag (Chat-validated)
f2175977 feat: add consultation_v2 bundle (ChatGPT Pro ET implementation)
```
