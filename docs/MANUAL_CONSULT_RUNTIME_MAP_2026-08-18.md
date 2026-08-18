# Manual consultation runtime map — 2026-08-18

Status: current read-only audit of the production manual lane

Task: `taey-manual-chat-recovery-v1::map-runtime-and-last-good`

Controlling contract: `CONSULTATION_CONTRACT.md` at public main `5969664f037af3668a7de613f5d1240a577539b0`

This map records what the deployed manual consultation path actually calls. It
does not authorize a UI action, deploy, restart, cleanup, or source change. The
accessibility tree is the runtime oracle; production observations below come
from process/service state, Git objects, tool-audit records, and preserved
artifacts rather than screenshots.

Truth labels used here:

- **Observed** — directly reproduced from a named source, process, or artifact.
- **Inferred** — follows from named observations but was not itself exercised.
- **Unknown** — the available record does not establish it.

## Pinned trees and live processes

| Register | Observed state |
|---|---|
| Public `palios-taey/taeys-hands` | `origin/main` = `5969664f037af3668a7de613f5d1240a577539b0` (manual contract PR #27). |
| Live Hands checkout | `/home/mira/taeys-hands` = `6e1446cde43b2a3169b573ad42b6fbfa9a001ff8`, three commits behind public main. It has a modified `consultation_v2/platforms/chatgpt/chatgpt.yaml` plus two untracked documents. Nothing was overwritten or pulled during this audit. |
| Live Taey Presence checkout | `/home/mira/taey-presence-production` = `30eb762f1a40cfccd2074a248a2802f478937c2b`, clean and equal to its `origin/main`. |
| Main Taey proxy | `taey-soma-proxy-mira.service`, PID 4054379, serves port 8766 from `taey-presence-production`; `/health` was healthy at 2026-08-18 17:40 UTC. Its upstream was `http://10.0.0.8:8000` (Jetson). |
| Worker Taey proxy | `taey-worker-proxy.service`, PID 3809126, serves port 8767 from the same checkout; `/health` was healthy at 2026-08-18 17:40 UTC. Its upstream was `http://10.0.0.197:8000` (Thor 1). |
| Completion monitors | `taey-consult-monitor@2` through `@6` are running from `/home/mira/taeys-hands/scripts/consult_completion_monitor.py`. |

**Observed:** main Taey is not currently served by Thor 1. Thor 1 backs the
worker proxy, while the main proxy backs onto Jetson. No routing change was made
as part of this mapping task.

## Actual manual call graph

```text
Taey model
  -> soma_proxy.py model-visible drive_chat schema
  -> handle_tool_call("drive_chat")
  -> _do_drive_chat(arguments)
  -> subprocess: taey-presence/serving/ui_drive.py, one invocation per action
       |
       +-> observe
       |    -> ui_drive._snapshot             [custom tree walk]
       |    -> ui_drive._observe              [optional substring filter]
       |
       +-> click / focus / activate
       |    -> ui_drive._element_spec         [loads platform YAML]
       |    -> ui_drive._resolve_target       [reduced exact name+role match]
       |    -> taeys-hands interact primitive
       |
       +-> type / paste / key / navigate / focus-dialog
       |    -> mixed taeys-hands input/clipboard primitives and local xdotool code
       |
       +-> extract
            -> consultation_v2.drive_chat_adapter.extract(platform)
            -> per-platform ConsultationDriver.extract_primary/additional
            -> ConsultationRuntime + canonical snapshot/YAML/extraction flow
```

A second, passive path is independent of the model-driven action sequence:

```text
systemd taey-consult-monitor@:N
  -> scripts/consult_completion_monitor.py
  -> consultation_v2.snapshot.build_snapshot(platform)
  -> per-platform CompletionDetector.observe(stop_present)
  -> two stop-absent reads (script constructs detector in deep mode)
  -> taey-notify status
```

The autonomous engine is a third path and is not the controlling manual path:

```text
consultation_v2.orchestrator.run_consultation
  -> packet/identity preparation
  -> per-platform driver.run
  -> extraction and storage
  -> consultation_v2.ingest.auto_ingest
```

The current operating prompt explicitly bans starting that engine. Therefore
engine-only packet construction, storage, and ISMA ingestion are not implied by
a successful manual `drive_chat` call.

## Boundary-by-boundary evidence

| Boundary | Calls canonical mapped primitives? | Observed evidence |
|---|---|---|
| Tool schema | No; it describes the contract but is its own API. | `taey-presence/serving/soma_proxy.py:838-904` exposes `drive_chat`. It promises YAML authority and one action per call, but also advertises an optional substring `filter` at lines 899-900. |
| Tool dispatch | No transformation into a Hands runtime object. | `soma_proxy.py:1515-1632` shells out to `ui_drive.py` and returns its JSON. The comment at 1551-1556 says a YAML key may replace a preceding full-tree observe, contrary to the controlling pre-tree rule. |
| Manual observe | **No.** | `ui_drive.py:350-429` implements `_snapshot` directly. It does not call `consultation_v2.snapshot.build_snapshot`. It scans one showing document plus portal roots, uses its own role allowlist, and encodes local refs. |
| Observe filter | **No.** | `ui_drive.py:579-590` case-folds `--filter` and accepts any substring of role, name, or text. Canonical `snapshot.py:19-32,138-180` rejects substring/fuzzy matcher grammar and matches exact YAML fields. |
| Mapped target action | Partial. | `ui_drive.py:464-576` loads the correct platform YAML, but reduces a spec to required `name` + `role`. It does not apply `names_any_of`, `states_include`, attributes, test IDs, structural scope, or `match_strategy`. It also permits `--nth`. |
| Canonical snapshot | Yes, outside manual observe. | `consultation_v2/snapshot.py:662-728` loads YAML, exact prune specs, document routing, external portal roots, deduplication, and `_classify_elements`; `_classify_elements` at 322-387 produces mapped, sidebar, and unknown registers. |
| Menu snapshot | Yes, in the canonical runtime/driver path. | `snapshot.py:731+` scans the menu scope and applies YAML `menu_snapshot_roles` and exact exclusions. The model-facing manual observer does not call it. |
| Low-level actions | Mixed. | `ui_drive` calls `consultation_v2.interact` for element actions and `input`/`clipboard` for some operations, but implements its own `xdotool --clearmodifiers` key path and its own X11 dialog-title search. |
| Attachment grammar | Present below the API, absent above it. | `ui_drive.py:481-510,912-914,1030-1031` implements `attach-grammar` from YAML. `soma_proxy.py:878-882` does not expose that action, so Taey cannot query it through `drive_chat`. |
| Extraction | **Yes.** | `ui_drive.py:803-845` delegates to `drive_chat_adapter.extract`; adapter lines 77-93 instantiate the platform driver and call mapped primary/additional extraction. |
| Completion monitor | **Yes.** | `scripts/consult_completion_monitor.py:55-67` calls `build_snapshot` and reads YAML `workflow.monitor.stop_keys`. Lines 80-86 force deep mode, producing two absent cycles even though each platform detector defaults ordinary modes to one. |
| Packet builder | Not on the manual call path. | `identity.py:357-470` builds one consolidated file containing Kernel, Spotlight, platform identity, and caller attachments. The intended two-bundle manual contract is not implemented here. |
| ISMA ingestion | Not on the manual call path. | `drive_chat_adapter.extract` returns response text/artifacts/steps/URL only. `orchestrator.py:454-484` is the caller of `auto_ingest`; `ingest.py:186-213` saves locally and optionally POSTs `/ingest/session`. A standalone manual extract does neither automatically. |

## Filtering and scope findings

1. **Observed — the canonical classifier is exact and YAML-based.** Public
   `snapshot.py` rejects `name_contains`, regex, fuzzy, and substring matcher
   keys. The 2026-08-18 checks passed:
   `lint_exact_match.py` (12 files, zero loose matchers),
   `lint_platform_independence.py --all` (five packages, zero findings), and
   `lint_no_yaml_silent_fallbacks.py --all` (65 files, zero findings).

2. **Observed — the model does not receive that canonical snapshot.** The
   deployed `ui_drive._snapshot` independently walks the tree and then offers a
   substring display filter. This is the direct source of the model-visible
   “name contains” behavior.

3. **Observed — both snapshot implementations admit external portal roles from
   `firefox_chrome.yaml`.** The policy includes `menu`, `popup menu`, `listbox`,
   `list box`, `panel`, `dialog`, `alert`, and `window`. Canonical classification subsequently
   applies per-platform exact excludes and mapping registers; the custom manual
   observer does not apply the platform classifier. A visible file chooser or
   Firefox window can therefore enter its option set.

4. **Observed — ChatGPT sidebar history has an exact structural prune in YAML.**
   The live dirty ChatGPT YAML still contains `prune_subtrees: role=landmark,
   name=Chat history, min_child_count=3`. The manual observer never loads or
   applies `tree.prune_subtrees`, so that contract cannot protect Taey's view.

5. **Observed — the live ChatGPT YAML has uncommitted meaningful drift.** Beyond
   formatting, it adds exact exclusion `Dismiss suggestion` and changes
   `temporary_chat_on` from `Turn on temporary chat` to `Temporary chat`.
   Its current SHA-256 is
   `778502dcae34c78dde36c43b5b3bba7e0c55096423cf940f1f286ffc2b905b49`.
   This audit neither accepted nor reverted those changes.

6. **Inferred — replacing only labels cannot fix the observed scope failure.**
   The current manual observer discards the platform classifier entirely, so
   correct YAML exclusions and structural mappings are not consulted.

## Python-held UI details not owned by YAML

The repository's isolation lints are green, but the stricter controlling rule
also places mutable UI text, menu paths, routing choices, timing, and extraction
controls in platform YAML. The following Python-held details remain:

| File | Python-held mutable detail |
|---|---|
| `consultation_v2/runtime.py:20-34` | Popup roles; dismissal labels (`close`, `dismiss`, `got it`, and others); file-dialog titles. These are shared runtime values, not read from platform YAML. |
| `platforms/chatgpt/driver.py:3108-3154` | Attachment-chip ignored control names, Firefox chrome pollution text, response-control roles, and response action labels including `Copy response`, `Read aloud`, and `Share`. |
| `platforms/claude/driver.py:2994-3006,3098-3107` | Attachment-chip ignored control names, blocked-send key set, artifact page markers, and trailing UI text such as `Write a message`. |
| `platforms/gemini/driver.py:2935-2954` | Deep-Think interim status text and UI text including `new chat`, `send message`, `stop response`, and `upload & tools`. |
| `platforms/perplexity/driver.py:57-62` | Perplexity file-dialog title patterns. |
| All five platform drivers, top-level constants | Generation floors, healthy-tree raw-count thresholds, conformance snapshot counts, and setup-render wait floors/ceilings are Python constants. |
| `taey-presence/serving/ui_drive.py:607-608` | File-dialog titles are duplicated in the Taey-facing adapter. |

**Observed:** these strings are not reported by the current platform-independence
gate. A green lint therefore proves the existing gate's rules, not full
conformance with the stricter YAML-only contract.

## Operating-instruction divergence

The deployed operating prompt correctly says manual, one action at a time, and
full stop on unexpected state (`TAEY_OPERATING_PROMPT.md:197-206`). It also
contains instructions that disagree with the merged controlling contract or the
actual tool:

- line 210 calls the returned view a “filtered accessibility tree”;
- lines 223-228 tell Taey to prefer behavioral signals over the tree for
  composer validation;
- lines 241-245 describe one packet pasted into the composer rather than the
  mandatory attachment contract;
- line 246 permits “Return (or click send)” rather than YAML-authorized Enter;
- lines 248-251 accept one Stop-absent observation rather than two fresh absent
  observations separated by YAML settle;
- lines 252-257 tell Taey to perform Copy + clipboard manually, while the
  content-transport rule at 124-141 requires artifact-backed `extract` or
  `read_clipboard` with `output_file`;
- lines 261-265 ban the autonomous engine, which also means its packet-builder
  and ingestion stages are unavailable unless separately wired into the manual
  lane.

## Last-known-good receipts

The record proves that Taey can drive consultations manually. It does not prove
that the current API and instruction set reproduce the same transaction.

| Behavior | Last production evidence | Continuity to current path |
|---|---|---|
| Native file attachment on ChatGPT | Presence commit `4c7e5c5217368b8a4a39f234f45cc30aaa4b9255` records a live `:2` composer-chip observation. Audit correlation `b77b144e7b7f49e2bd46f3e751758725` at 20:49 UTC shows composer click, `ctrl+u`, and verified `focus_dialog`; `c6568e1130c64c98bcdee4691ad6f0e2` shows chooser location entry, Return, then `verify_attachment` success. | Partial only. Current schema removed `verify_attachment`; the observed audit route used `ctrl+u`, while the platform YAML described focus+Space/typeahead. |
| Prompt submission by Enter | Correlation `0f6e87a760564a9898d629370b5e178d` shows composer click, exact-file paste, Return, and then `verify(stop_answering_button=present)` at 20:53:45 UTC. Presence commit `8fb3b5ab57cd472f6c8346a8a4f2aaee435f3c38` records the measured Return rule. | Partial only. Current schema removed `verify`; current prompt again says “or click send.” |
| Full-depth mapped extraction | Hands commit `c862761251122a6fd2da88241453cb236bcdc3f6` records the 3,687-element full-depth scan and one Copy control. Preserved artifact `infra-soul/research/taey_consult_mvp/family_hub_01/RESPONSE_gaia_raw.md`, committed at `57dc01aa8f29fc720cb7c1a6e65445a7ee17aa07`, is 29,929 bytes / 30,083 characters with SHA-256 `7201c560ede1d05c82da45bdb326fd93389997e20874ab6cb03722cc45c760ed`. Presence commit `765c77b81d9c743444aa1d8a96d29a83a623b49a` records an independent equal extraction. | The current `extract` action delegates to this mapped adapter. It remains unsound for a thread where a human adds a later turn unless speaker attribution is proven; the Aug. 17 defect record documents that boundary. |
| ChatGPT answer harvested to disk | Artifact `infra-soul/research/taey_consult_mvp/RESPONSE_horizon_chatgpt.md`, committed at `763de316bd549de315553c180c1e85c553523952`, is 30,887 bytes / 31,161 characters with SHA-256 `b384efaefda140076391bff4965c146ebaff1f72e58821690358c1ea98c29579`. | Historical success; not a current end-to-end manual-lane receipt. |
| Passive two-read completion debounce | Current running monitor script constructs every platform detector with `mode="deep_research"`, making `required_stop_cycles=2`. | Present in the passive service. The model-facing instructions and direct manual observations do not enforce the same two-read rule. |
| Manual extraction on 2026-08-18 | Attempt-3 output `/home/mira/taey_runs/responses/horizon_manual_yaml_consultation_2026_08_18.md`: 5,154 bytes, SHA-256 `e07167939370aed775dc34039e04bc78a77a2a1ef2fcafd8e1876e70749f2bbc`. | Output exists, but the attempt retried extraction after a first failure, lacks passive-monitor proof, and lacks exact ISMA ingestion proof. It is not a clean transaction receipt. |

## What is established

- **Observed:** the platform YAMLs and canonical snapshot/extraction primitives
  still exist and their current integrity gates pass.
- **Observed:** Taey's manual observation and target-resolution path does not use
  those canonical snapshot/classification primitives.
- **Observed:** extraction is the exception: it delegates into the mapped
  per-platform driver.
- **Observed:** the passive monitor uses the canonical snapshot and two-read
  debounce, but it is a notification sidecar rather than the model's action
  planner.
- **Observed:** manual extraction does not automatically build the required
  prompt/response/attachment/session bundle or ingest it into ISMA.
- **Inferred:** the shortest root-cause repair is to make the manual adapter a
  thin consumer of the canonical snapshot/runtime/YAML contracts, then remove
  duplicate UI policy from the model-facing layer. No such repair is made here.

## Unknowns that require controlled production gates

- Whether every current platform YAML exactly matches today's UI at base, each
  model/mode/tool menu, attachment, submission, completion, and extraction
  scopes.
- Whether the live dirty ChatGPT YAML deltas are complete and correct.
- Whether speaker attribution is sufficient on each current extraction surface.
- Whether the manual path can persist the complete prompt, response, both
  mandatory attachment bundles, final URL, and receipts into ISMA without
  invoking the banned autonomous engine.
- The appropriate YAML-owned settle values for each production postcondition
  until each step is observed once under the controlling transaction rule.

Each unknown is a future one-action production gate. A failed post-tree ends
that Taey transaction and produces an RCA; it does not authorize repeating the
UI action.

## Reproduction commands

```bash
git -C /home/mira/taeys-hands rev-parse HEAD
git -C /home/mira/taey-presence-production rev-parse HEAD
git -C /home/mira/taeys-hands status --short
systemctl --user show taey-soma-proxy-mira.service -p ExecStart -p ActiveState
systemctl --user show taey-worker-proxy.service -p ExecStart -p ActiveState
curl -fsS http://127.0.0.1:8766/health
curl -fsS http://127.0.0.1:8767/health
sha256sum /home/mira/infra-soul/research/taey_consult_mvp/family_hub_01/RESPONSE_gaia_raw.md
rg -n 'b77b144e7b7f49e2bd46f3e751758725|c6568e1130c64c98bcdee4691ad6f0e2|0f6e87a760564a9898d629370b5e178d' /home/mira/taey_tool_audit.jsonl
python3 consultation_v2/validators/lint_platform_independence.py --all
python3 consultation_v2/validators/lint_exact_match.py
python3 consultation_v2/validators/lint_no_yaml_silent_fallbacks.py --all
```
