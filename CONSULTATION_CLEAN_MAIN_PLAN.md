# Project: consultation-clean-main - Clean canonical browser consultation engine [ref: FLOW_CONSULTATION_ENGINE.md:1-724]
> Goal: converge taeys-hands consultation dispatch onto one supported browser-driving flow that follows `FLOW_CONSULTATION_ENGINE.md`, preserves the production DBUS/Xvfb/Firefox display substrate, supports concurrent monitors, and extracts assistant text, research reports, artifacts, downloads, and attachment-derived outputs without fallbacks.
> Canonical context: `FLOW_CONSULTATION_ENGINE.md` is the project-level flow contract. Every phase and task carries a `[ref:]` to this in-repo taeys-hands file so wake/context injection gives each worker the same target model.
> Primary home: `taeys-hands` owns this product, this plan, and this contract. The old orchestrator planning copy is historical only and must not be treated as canonical.
> Required tracker supervisor: `taeys-hands`. Ingest with `taey-plan ingest --supervisor taeys-hands CONSULTATION_CLEAN_MAIN_PLAN.md`.

## Phase: p0-contract-crosscheck - Canonical contract, fleet review, and local-context ownership [order: 1] [ref: FLOW_CONSULTATION_ENGINE.md:1-196]

### Task: p0-flow-contract - Maintain the project-level FLOW_CONSULTATION_ENGINE.md contract with exact taeys-hands source refs, including production display-substrate preservation [priority: 100] [owner: taeys-hands-codex] [tags: contract,context,flow] [ref: FLOW_CONSULTATION_ENGINE.md:1-196]
- Keep Observed/Inferred/Unknown separated.
- Any contract change must line-pin the taeys-hands source file and range it depends on.

### Task: p0-gemini-crosscheck - Gemini/COSMOS cross-check of the contract and plan for missing territory, stale docs, monitor concurrency, and extraction/research gaps [priority: 95] [owner: taeys-hands-gemini] [tags: audit,crosscheck,cosmos] [depends: p0-flow-contract] [ref: FLOW_CONSULTATION_ENGINE.md:1-724]
- Report contradictions or missing source refs with file:line evidence.

### Task: p0-gemini-artifact-retry - Gemini/COSMOS re-check of the reconciled contract with a concrete report artifact and file:line evidence [priority: 94] [owner: taeys-hands-gemini] [tags: audit,crosscheck,artifact] [depends: p0-flow-contract] [ref: FLOW_CONSULTATION_ENGINE.md:1-724]
- Completion evidence must include a report path or commit plus exact file:line findings.

### Task: p0-grok-audit - Grok/LOGOS adversarial audit of the contract for fuzzy-match loopholes, duplicate implementation risk, action-retry risk, and false completion/extraction paths [priority: 95] [owner: taeys-hands-grok] [tags: audit,adversarial,logos] [depends: p0-flow-contract] [ref: FLOW_CONSULTATION_ENGINE.md:1-724]
- Return BLOCK/ENDORSE with exact blockers and the smallest root-cause correction.

### Task: p0-reconcile-verdicts - Reconcile Gemini and Grok verdicts into the contract before code work starts [priority: 90] [owner: taeys-hands-codex] [tags: reconcile,contract] [depends: p0-gemini-crosscheck,p0-grok-audit] [ref: FLOW_CONSULTATION_ENGINE.md:1-724]
- Update the contract if either review finds a real omission.
- Do not proceed to implementation until accepted blockers are folded in.

### Task: p0-conductor-local-context - Verify whether local conductor processes need a pointer, mirror, global ref, or no file at all for this project; implement only the least-drifting option [priority: 85] [owner: taeys-hands-codex] [tags: conductor,context,refs] [ref: FLOW_CONSULTATION_ENGINE.md:3-15] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]
- Do not create a second canonical `FLOW_*.md`.
- If `the-conductor` needs a local artifact, make it an explicit pointer to this taeys-hands-owned contract.

## Phase: p1-inventory - Line-pin what exists, what works, and what must be preserved [order: 2] [ref: FLOW_CONSULTATION_ENGINE.md:17-196]

### Task: p1-entrypoint-inventory - Inventory every current consultation entrypoint and mark keep, adapt, archive, or fail-loud-stub [priority: 90] [owner: taeys-hands-codex] [tags: inventory,cutover] [depends: p0-reconcile-verdicts] [ref: FLOW_CONSULTATION_ENGINE.md:21-37] [ref: FLOW_CONSULTATION_ENGINE.md:132-149] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]
- Include MCP-era tools, old V1 scripts, `build_consultation.py`, `scripts/consultation.py`, `consultation_v2`, direct `tools/send.py`, and extraction helpers.

### Task: p1-display-substrate-inventory - Audit the production DBUS/Xvfb/Firefox launch process and prove what must be retained before the consultation engine changes [priority: 95] [owner: taeys-hands-codex] [tags: display,dbus,firefox,production] [depends: p0-reconcile-verdicts] [ref: FLOW_CONSULTATION_ENGINE.md:48-54] [ref: FLOW_CONSULTATION_ENGINE.md:151-178] [ref: FLOW_CONSULTATION_ENGINE.md:325-371]
- Reconcile checked-in `taey-display-N.service` units with `scripts/install_machine_displays.sh` generation and `taey-bus-watcher@`.
- Produce a no-regeneration-without-verification rule for cutover.

### Task: p1-extraction-inventory - Line-pin the current working extraction paths for assistant text, research reports, artifacts, downloads, and attachment-derived content [priority: 90] [owner: taeys-hands-codex] [tags: extraction,inventory,research] [depends: p0-reconcile-verdicts] [ref: FLOW_CONSULTATION_ENGINE.md:55-57] [ref: FLOW_CONSULTATION_ENGINE.md:180-190] [ref: FLOW_CONSULTATION_ENGINE.md:551-605]
- Include ChatGPT reports/canvas, Claude artifacts, Gemini Deep Research, Grok, and Perplexity Deep Research.
- Mark which paths are production-proven, stale, or only planned.

### Task: p1-yaml-driver-gap-map - Produce a per-platform YAML/driver gap map against the exact-match-only contract [priority: 88] [owner: taeys-hands-codex] [tags: yaml,drivers,inventory] [depends: p0-reconcile-verdicts] [ref: FLOW_CONSULTATION_ENGINE.md:58-62] [ref: FLOW_CONSULTATION_ENGINE.md:126-141] [ref: FLOW_CONSULTATION_ENGINE.md:405-457]
- Count loose matcher keys and driver-side platform strings.
- Separate strict-loader work from platform migration work.

### Task: p1-orchestrator-surface-audit - Audit orchestrator, conductor, hooks, demos, services, and local process surfaces for consultation launch paths [priority: 94] [owner: taeys-hands-codex] [tags: orchestrator,inventory,cutover] [depends: p0-reconcile-verdicts] [ref: FLOW_CONSULTATION_ENGINE.md:198-224] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]
- Mark each external surface as preserve, fail-loud-stub, pure forwarder, or out of scope.

### Task: p1-mechanical-stop-gates - Add baseline-aware gates for duplicate entrypoints, loose matchers, protected display-substrate edits, and machine-readable stop conditions [priority: 98] [owner: taeys-hands-codex] [tags: gates,lint] [depends: p1-entrypoint-inventory] [ref: FLOW_CONSULTATION_ENGINE.md:680-724]

## Phase: p2-clean-engine-core - Build the single clean flow boundary [order: 3] [ref: FLOW_CONSULTATION_ENGINE.md:198-549]

### Task: p2-cutover-shape-decision - Decide whether to repair consultation_v2 in place or create a clean package, using inventory evidence and the one-entrypoint cutover rule [priority: 85] [owner: taeys-hands-codex] [tags: architecture,decision,contract] [depends: p1-entrypoint-inventory,p1-yaml-driver-gap-map] [ref: FLOW_CONSULTATION_ENGINE.md:226-269] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]
- The decision must name the final supported CLI/API entrypoint.
- This task also closes the contract-home reconcile gate: taeys-hands owns the canonical plan and FLOW.
- No p2 runtime code may start until Gemini and Grok re-audit this final contract and p0-reconcile is recorded.

### Task: p2-strict-yaml-loader - Implement strict YAML schema/runtime load rejection for loose keys and unmapped validation states [priority: 90] [owner: taeys-hands-codex] [tags: yaml,strict,code] [depends: p2-cutover-shape-decision] [ref: FLOW_CONSULTATION_ENGINE.md:405-457]
- Accepted grammar is exact `name`, exact `role`, `states_include`, exact-enumerated `names_any_of`, and structural locators only.

### Task: p2-shared-primitives - Define and wire shared primitives only: snapshot, menu_snapshot, exact/structural match, click, pointer move, paste, key press, scroll, clipboard, URL read, focus, locks, run-state, monitor registration, storage, notify [priority: 88] [owner: taeys-hands-codex] [tags: primitives,code] [depends: p2-cutover-shape-decision] [ref: FLOW_CONSULTATION_ENGINE.md:440-457]
- Shared primitives must contain no platform strings.

### Task: p2-intake-identity - Implement intake and identity packaging with fail-loud missing `FAMILY_KERNEL.md` or platform `IDENTITY_*.md` behavior [priority: 85] [owner: taeys-hands-codex] [tags: intake,identity,attachments] [depends: p2-cutover-shape-decision] [ref: FLOW_CONSULTATION_ENGINE.md:271-323]
- Preserve caller attachment metadata and hashes before consolidation.

### Task: p2-run-state-idempotency - Add durable run-state checkpoints for setup, submitted URL, monitor id, prompt hash, attachment hashes, completion, extraction, and notification evidence [priority: 90] [owner: taeys-hands-codex] [tags: idempotency,state] [depends: p2-cutover-shape-decision] [ref: FLOW_CONSULTATION_ENGINE.md:487-489] [ref: FLOW_CONSULTATION_ENGINE.md:607-621]
- Re-runs must resume after a landed send and never duplicate an irreversible prompt.

### Task: p2-dispatch-lock - Implement per-display setup/send serialization without blocking concurrent monitors [priority: 88] [owner: taeys-hands-codex] [tags: dispatch,locks,concurrency] [depends: p2-run-state-idempotency] [ref: FLOW_CONSULTATION_ENGINE.md:527-549]

## Phase: p3-monitors - Concurrent monitor registration, completion detection, and notification [order: 4] [ref: FLOW_CONSULTATION_ENGINE.md:491-549]

### Task: p3-send-monitor-registration - Make send success require Stop appeared, URL captured, run-state written, and monitor registration ACKed [priority: 95] [owner: taeys-hands-codex] [tags: send,monitor,state] [depends: p2-run-state-idempotency,p2-dispatch-lock] [ref: FLOW_CONSULTATION_ENGINE.md:459-525]
- No request may be reported sent when no monitor session exists.

### Task: p3-concurrent-monitor-adapter - Adapt or replace the central monitor so it observes all submitted sessions concurrently while setup/send continues sequentially [priority: 90] [owner: taeys-hands-codex] [tags: monitor,concurrency] [depends: p3-send-monitor-registration] [ref: FLOW_CONSULTATION_ENGINE.md:491-549]
- Central monitor is acceptable if it cleanly supports all platforms; per-display monitors are acceptable if simpler and verifiable.

### Task: p3-concurrent-monitor-implementation - Implement the chosen concurrent monitor adapter with durable session registry and per-session notification routing [priority: 90] [owner: taeys-hands-codex] [tags: monitor,concurrency,code] [depends: p3-concurrent-monitor-adapter] [ref: FLOW_CONSULTATION_ENGINE.md:491-549]

### Task: p3-stop-state-machine - Enforce Stop-seen then Stop-gone completion with debounce, mapped exception checks, generation timeout, and hang notification [priority: 88] [owner: taeys-hands-codex] [tags: monitor,completion] [depends: p3-concurrent-monitor-adapter] [ref: FLOW_CONSULTATION_ENGINE.md:507-518]

### Task: p3-notify-ack-park - Route completion, timeout, hang, and drift through fleet-notify with ACK evidence and parked needs-attention fallback [priority: 86] [owner: taeys-hands-codex] [tags: notify,evidence] [depends: p3-concurrent-monitor-adapter] [ref: FLOW_CONSULTATION_ENGINE.md:520-525] [ref: FLOW_CONSULTATION_ENGINE.md:607-621]

## Phase: p4-extraction - YAML-mapped extraction including research and artifacts [order: 5] [ref: FLOW_CONSULTATION_ENGINE.md:551-621]

### Task: p4-extraction-yaml-schema - Add YAML extraction workflow schema by output type and platform [priority: 92] [owner: taeys-hands-codex] [tags: extraction,yaml] [depends: p1-extraction-inventory,p2-strict-yaml-loader] [ref: FLOW_CONSULTATION_ENGINE.md:551-605]

### Task: p4-assistant-text-extract - Implement assistant_text extraction through bottom scroll, exact final response copy button, AT-SPI element action, clipboard read, and prompt-echo validation [priority: 85] [owner: taeys-hands-codex] [tags: extraction,assistant-text] [depends: p4-extraction-yaml-schema] [ref: FLOW_CONSULTATION_ENGINE.md:573-580]

### Task: p4-research-report-extract - Implement research_report extraction for Perplexity Deep Research and Gemini Deep Research without using generic bottom copy [priority: 90] [owner: taeys-hands-codex] [tags: extraction,research] [depends: p4-extraction-yaml-schema] [ref: FLOW_CONSULTATION_ENGINE.md:581-591]

### Task: p4-artifact-download-attachment-extract - Implement artifact, downloaded_file, and attachment_echo extraction with file hashes and assistant-message links [priority: 88] [owner: taeys-hands-codex] [tags: extraction,artifacts,attachments] [depends: p4-extraction-yaml-schema] [ref: FLOW_CONSULTATION_ENGINE.md:565-591]

### Task: p4-storage-schema - Persist prompts, assistant responses, URLs, run audits, source attachment hashes, extracted artifacts, extraction method, notification evidence, and storage ids [priority: 82] [owner: taeys-hands-codex] [tags: storage,evidence] [depends: p4-assistant-text-extract,p4-research-report-extract,p4-artifact-download-attachment-extract] [ref: FLOW_CONSULTATION_ENGINE.md:607-621]

## Phase: p5-platform-migration - Move each platform through the clean flow [order: 6] [ref: FLOW_CONSULTATION_ENGINE.md:198-621]

### Task: p5-chatgpt - Migrate ChatGPT setup/send/monitor/extract to the clean flow, including focus-composer-plus-Enter send and report/canvas extraction cases [priority: 86] [owner: taeys-hands-codex] [tags: platform,chatgpt] [depends: p3-stop-state-machine,p4-storage-schema] [ref: FLOW_CONSULTATION_ENGINE.md:198-621]

### Task: p5-claude - Migrate Claude setup/send/monitor/extract to the clean flow, including Extra effort, attachment upload waits, and artifact extraction [priority: 86] [owner: taeys-hands-codex] [tags: platform,claude] [depends: p3-stop-state-machine,p4-storage-schema] [ref: FLOW_CONSULTATION_ENGINE.md:198-621]

### Task: p5-gemini - Migrate Gemini setup/send/monitor/extract to the clean flow, including Deep Think and Deep Research post-send Start Research plus report extraction [priority: 86] [owner: taeys-hands-codex] [tags: platform,gemini] [depends: p3-stop-state-machine,p4-storage-schema] [ref: FLOW_CONSULTATION_ENGINE.md:198-621]

### Task: p5-grok - Migrate Grok setup/send/monitor/extract to the clean flow, including Heavy mode, stale attachment handling, and exact stop/copy behavior [priority: 84] [owner: taeys-hands-codex] [tags: platform,grok] [depends: p3-stop-state-machine,p4-storage-schema] [ref: FLOW_CONSULTATION_ENGINE.md:198-621]

### Task: p5-perplexity - Migrate Perplexity setup/send/monitor/extract to the clean flow, including Deep Research full-report extraction [priority: 86] [owner: taeys-hands-codex] [tags: platform,perplexity] [depends: p3-stop-state-machine,p4-storage-schema] [ref: FLOW_CONSULTATION_ENGINE.md:198-621]

## Phase: p6-archive-cutover - Remove duplicate live implementations and make the clean path unavoidable [order: 7] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]

### Task: p6-archive-legacy-paths - Archive or fail-loud-stub old MCP/V1/direct consultation paths after inventory and migration evidence [priority: 90] [owner: taeys-hands-codex] [tags: archive,cutover] [depends: p5-chatgpt,p5-claude,p5-gemini,p5-grok,p5-perplexity] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]

### Task: p6-one-entrypoint - Flip docs/scripts/skills to one supported CLI/API entrypoint and one YAML directory [priority: 88] [owner: taeys-hands-codex] [tags: entrypoint,docs] [depends: p6-archive-legacy-paths] [ref: FLOW_CONSULTATION_ENGINE.md:251-259] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]

### Task: p6-import-lint - Add an import/lint gate so clean engine modules cannot import legacy platform-driving modules or loose matcher helpers [priority: 84] [owner: taeys-hands-codex] [tags: lint,guardrails] [depends: p6-one-entrypoint] [ref: FLOW_CONSULTATION_ENGINE.md:405-457] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]

### Task: p6-conductor-pointer - Remove or neutralize stale conductor/orchestrator consultation contract pointers after taeys-hands becomes the canonical home [priority: 80] [owner: taeys-hands-codex] [tags: conductor,context,cutover] [depends: p6-one-entrypoint] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]

### Task: p6-conductor-forwarder-guard - Replace external consultation-capable surfaces with fail-loud stubs or pure forwarders to the one supported entrypoint [priority: 80] [owner: taeys-hands-codex] [tags: conductor,context,cutover] [depends: p6-one-entrypoint] [ref: FLOW_CONSULTATION_ENGINE.md:623-659]

## Phase: p7-acceptance - Production evidence and handoff [order: 8] [ref: FLOW_CONSULTATION_ENGINE.md:680-724]

### Task: p7-display-substrate-production-check - Before final browser runs, verify production DBUS/Xvfb/Firefox units, bus files, Firefox pids, and tree visibility on each production display [priority: 95] [owner: taeys-hands-codex] [tags: production,display,verification] [depends: p6-one-entrypoint] [ref: FLOW_CONSULTATION_ENGINE.md:325-371] [ref: FLOW_CONSULTATION_ENGINE.md:680-724]

### Task: p7-five-platform-real-runs - Run one real consultation on ChatGPT, Claude, Gemini, Grok, and Perplexity through setup, send, monitor, extract, store, and notify [priority: 98] [owner: taeys-hands-codex] [tags: production,acceptance] [depends: p7-display-substrate-production-check,p6-import-lint] [ref: FLOW_CONSULTATION_ENGINE.md:680-724]
- Evidence for each platform: submitted URL, monitor id, Stop seen/gone evidence, extracted response or artifact path, notification ACK or parked evidence, and storage id.

### Task: p7-multi-monitor-concurrency-run - Prove the required concurrency model: dispatch multiple Chats sequentially, monitor them simultaneously, and receive independent completion notifications while later sends are in flight [priority: 96] [owner: taeys-hands-codex] [tags: production,monitor,concurrency] [depends: p7-five-platform-real-runs] [ref: FLOW_CONSULTATION_ENGINE.md:527-549] [ref: FLOW_CONSULTATION_ENGINE.md:680-724]

### Task: p7-clean-main-handoff - Commit, report branch/hash/files/verification, and hand off for merge to the clean main path only after acceptance evidence is recorded [priority: 90] [owner: taeys-hands-codex] [tags: handoff,merge] [depends: p7-multi-monitor-concurrency-run] [ref: FLOW_CONSULTATION_ENGINE.md:623-724]

## User Stop Conditions
- stop_when_duplicate_live_implementation_detected
- stop_when_monitor_registration_cannot_be_proven
- stop_when_production_display_substrate_would_be_replaced
- stop_when_extraction_for_research_or_artifacts_is_unmapped
- stop_when_crosscheck_completion_has_no_artifact
- stop_when_final_acceptance_evidence_recorded
