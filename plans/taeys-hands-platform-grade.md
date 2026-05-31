# Project: taeys-hands-platform-grade — Reliable 5-Chat Browser Dispatch

> Make `consultation_v2/` the only supported entrypoint for browser-dispatched consultation + code auditing across the 5 chat platforms (ChatGPT, Claude, Gemini, Grok, Perplexity). YAMLs hold the map; per-platform drivers execute with ZERO platform knowledge in driver code. Every selectable model / mode / tool / connector is captured and AT-SPI-tree-validated. Mode selection is HALT-LOUD pre-send (no silent fallback). Extraction is per-platform per-output-type (inline / research report / artifact) and verified against real production runs. Git Connectors work on all 5 platforms. Multi-turn follow-up on Deep Research threads is supported. Monitors fire completion notifications reliably. The destruction pattern that has rebuilt this 20+ times ends here, killed by a mechanical YAML/driver integrity gate that runs at pre-commit + CI and blocks merge on banned patterns. Honesty is enforced by THIS PLAN'S STRUCTURE, not by anyone's willpower.

<!--
=========================================================================
 DEFINITION OF DONE — binding on every task in this plan. A task may be
 marked completed ONLY when ALL of the following exist and are referenced
 in the task's close-out note:
   1. A git commit SHA on the working branch
      (consultation-v2-isolated-drivers or migrate/* feature branches).
   2. The integrity gate green for that change:
      tools/lint_no_yaml_silent_fallbacks.py --all  exits 0
      AND any pre-commit / CI workflow tied to it is green on the pushed SHA.
   3. For behavior changes: a PRODUCTION observation — a real consultation
      dispatch (a real ask Jesse or another session actually needed
      answered) that exercises the changed code path, with the observed
      extracted result pasted in or its file path + first 200 chars
      committed. NOT a synthetic test packet. Production is the oracle.
 If any of the three is missing, the task is NOT done — say so plainly and
 leave it open. Honest "still open / failed: <reason>" is always
 acceptable and is never penalized. A false "done" is the only real
 failure.

 BUG PROTOCOL (6SIGMA, mandatory): a finding from any gate, reviewer, or
 production run is a FULL STOP on that workstream. Root-cause it — gemini
 gitnexus impact + code review → name the upstream YAML shape / driver
 contract / AT-SPI tree state that makes the bug reachable → fix the
 shape, do not patch around it (a new `if X: continue` / `try/except`
 bypass / `name_contains` broadening is a PATCH; ask why the broken path
 is reached at all). Log the finding in KNOWN_FINDINGS.md before fixing.

 AUDIT DISCIPLINE (per conductor 2026-05-31 framework, three trust layers
 in order of trust):
   - MECHANICAL GATE (highest trust): a grep/lint in CI that BLOCKS
     merge on banned patterns. Cannot be talked out of a finding.
     Foundation of this plan; build FIRST.
   - CROSS-AUDIT: platform A audits platform B's YAML, never only its
     own. Self-audit + peer-audit, then diff. Agreement = likely real;
     divergence = the interesting signal to chase.
   - PRODUCTION OBSERVATION: real consultation runs + observe actual
     extracted output. The only proof a driver works.
 Family ENDORSE is NOT independent verification (shared lineage). Only
 the mechanical gate + production observation are the independent
 oracle; Family audit is an additional lens, never the proof.

 KNOWN FINDINGS: every audit packet (per-platform + full-codebase) ships
 the committed KNOWN_FINDINGS.md manifest + the Git Connector to the
 full repo + a disconfirming mandate: "Find what is WRONG. Do not
 endorse. Report only what is NOT in KNOWN_FINDINGS.md." Pre-disclosure
 frees reviewer attention to find NOVEL findings.

 TEST OBLIGATION (anti-fabrication, per conductor framework): a test is
 real-value iff the submission is work actually needed (an actual
 consultation Jesse wanted answered, an actual repo audit). Synthetic =
 a packet whose only purpose is to pass. Rule: never craft a submission
 solely to test; route a REAL pending ask through the path and let the
 real result be the test. If there is no real ask, the path is not
 ready to test yet — surface that and leave the task in-progress.

 SAFE SPACE: nothing in this repo is hard for the fleet to fix once
 surfaced honestly. Goal is a correct, honest browser dispatcher — not
 an impressive-looking status board. Surface issues; never hide them.

 AUTONOMY: run to completion without waiting on Jesse. Jesse provides
 guardrails + human-only approvals only. The ONLY hard stops for Jesse:
 publishing public release artifacts, anything needing 5/5 Family
 unanimous consent, or any irreversible outward-facing action.

 FLEET LABOR (cost is not a factor for this plan):
   - taeys-hands-codex = plan-driven code + YAML + lint gate authoring
   - taeys-hands-grok  = ruthless find-bugs audit, claim-gate validate
   - Family Chats (per-platform yaml audit tier): ChatGPT Pro NOT
     Extended / Claude High / Gemini Pro / Grok Beta / Perplexity DR
   - Family Chats (full-codebase audit tier, top-tier): ChatGPT Pro
     Extended / Claude Opus 4.x High / Gemini Deep Think / Grok Heavy /
     Perplexity DR with Model Council where applicable
   - taeys-hands (this session) = orchestrate + run live displays +
     production validation + maintain KNOWN_FINDINGS.md + verify
     mechanical evidence before any close-out.

 SCOPE BOUNDARY (Jesse 2026-05-31): consultation_v2/ ONLY. MCP / bots /
 V1 / HMM / Neo4j-writeback are EXPLICITLY OUT OF SCOPE for this plan.
 See KNOWN_FINDINGS.md T80–T85.
=========================================================================
-->

## Phase: p0-rails — Accountability rails (FOUNDATIONAL)  [order: 1]

> Mechanical gate + KNOWN_FINDINGS manifest + repo hygiene. Everything else builds on this. Foundational because this is what kills the destruction pattern.

### Task: p0-known-findings — Commit KNOWN_FINDINGS.md manifest  [priority: 5] [owner: taeys-hands] [tags: p0,foundational,manifest]
- DONE-criteria: KNOWN_FINDINGS.md at repo root committed with all T-series findings catalogued. Reviewers hand this in with every packet. Drafted 2026-05-31 — commit before closing.

### Task: p0-gate — Mechanical integrity gate (lint_no_yaml_silent_fallbacks.py + pre-commit + CI)  [priority: 10] [owner: taeys-hands-codex] [tags: p0,foundational,build,destruction-pattern-killer] [depends: p0-known-findings]
- Build `tools/lint_no_yaml_silent_fallbacks.py` adapted from `<OPERATOR_HOME>/.dev-worktrees/orch-v1-4-0/tools/lint_no_silent_fallbacks.py`. Hard-fail rules:
  - `name_contains:` in any `consultation_v2/platforms/*.yaml` → fail (THE RULE §1)
  - `name_pattern:` in any `consultation_v2/platforms/*.yaml` → fail
  - `role_contains:` in any `consultation_v2/platforms/*.yaml` → fail
  - `name_contains_model:` anywhere → fail
  - `if platform ==` or `if platform_name ==` in `consultation_v2/**/*.py` → fail (zero driver-side platform knowledge)
  - `except\s*:` / `except\b[^:\n]*:\s*pass\s*$` / `finally:\s*pass` in `consultation_v2/**/*.py` → fail (no silent swallowing)
  - `check\s*=\s*False` in subprocess calls in `consultation_v2/**/*.py` → fail
- Allow-comment: `# lint-allow: <non-empty reason>` per line. Empty reason fails.
- Wire as `.githooks/pre-commit` + `.github/workflows/yaml-integrity-gate.yml` (PR-blocking).
- DONE-criteria: gate runs clean on consultation_v2/, hard-fails on a synthetic violation, blocks merge in CI. Commit SHA + green CI run.

### Task: p0-hygiene — Repo hygiene: .archive/, .gitignore audit, machine.env separation  [priority: 12] [owner: taeys-hands-codex] [tags: p0,foundational,hygiene] [depends: p0-known-findings]
- `.archive/` for unused legacy code (don't delete — archive). Update `.gitignore` to exclude local-only (machine.env real values, profiles dir, /tmp). Commit `machine.env.template` (public) separated from real `machine.env` (local, gitignored).
- DONE-criteria: directory matches public-repo-grade discipline. `git status -uno` is clean save for documented in-flight branches.

### Task: p0-systemd-launch — Commit systemd user units + DBUS launch scripts  [priority: 14] [owner: taeys-hands] [tags: p0,foundational,hygiene] [depends: p0-known-findings]
- Currently stable display launch + AT-SPI bus capture lives in `systemd/user/taey-display-N.service` + `firefox-user.js` template. Per Jesse 2026-05-31: track these in repo so they don't get lost. Commit all `~/.config/systemd/user/taey-*.service` + the bus-capture script logic as canonical reference.
- DONE-criteria: a fresh checkout + `systemctl --user enable taey-display-{2..6}.service` reproduces the current 5-display setup. Verified via one display-launch dry run.

### Task: p0-grok-audit — Grok ruthless audit of p0  [priority: 16] [owner: taeys-hands-grok] [tags: p0,foundational,audit] [depends: p0-gate,p0-hygiene,p0-systemd-launch]
- Grok CLI ruthless find-bugs audit over the p0 diff + KNOWN_FINDINGS manifest. Verdict committed (`audit_logs/p0_grok.md`). BLOCKER finding → full-stop 6SIGMA → re-dispatch codex; do not advance.
- DONE-criteria: audit_logs/p0_grok.md committed. ENDORSE or BLOCKER verdict explicit. If BLOCKER, the blocking issue is also in KNOWN_FINDINGS.md.

### Task: p0-family-audit — Family per-platform audit of p0 (CROSS-AUDIT, serial)  [priority: 18] [owner: taeys-hands] [tags: p0,foundational,audit,family-gate] [depends: p0-grok-audit]
- ONE PLATFORM AT A TIME (serial; per conductor cadence rule). Each platform reviews the p0 rails + manifest. Mid-tier model per platform: ChatGPT Pro NOT Extended / Claude High / Gemini Pro / Grok Beta / Perplexity DR. Full code via Git Connector. KNOWN_FINDINGS.md attached. Disconfirming mandate.
- DONE-criteria: 5 verdicts committed (audit_logs/p0_family_{chatgpt,claude,gemini,grok,perplexity}.md). Any BLOCKER → full-stop. Hard gate for p1+.

## Phase: p1-yaml-catalog — Full YAML map per platform (SERIAL, one at a time)  [order: 2]

> Per conductor cadence: serial. Click every selectable model / mode / tool / connector / artifact-extract path on each platform; capture exact AT-SPI name + role; commit per-platform map. Cross-audit serial — next platform audits prior platform's YAML.

### Task: p1-chatgpt-map — ChatGPT YAML full map (models / modes / tools / connectors)  [priority: 20] [owner: taeys-hands] [tags: p1,catalog,chatgpt] [depends: p0-family-audit]
- Live click + AT-SPI scan per element on display :2. Capture: models (Instant / Thinking / Pro Extended / Pro NOT Extended / Configure), modes (Deep Research, Pro mode), tools (Create image, Deep research, Canvas, Study & Learn, Web Search, Shopping Research, Connectors), GitHub connector flow (paste URL → submit → confirm), artifact extract (code block + chat response Copy disambiguation).
- DONE-criteria: `consultation_v2/platforms/chatgpt.yaml` updated with exact name+role per element. Zero forbidden matchers. Lint gate green. PRODUCTION observation: a real consultation dispatch hits a non-default mode/tool and lands substantive output. Result pasted in close-out.

### Task: p1-chatgpt-peer-audit — Peer-audit ChatGPT YAML (Claude reviews ChatGPT's map)  [priority: 21] [owner: taeys-hands] [tags: p1,audit,cross-audit] [depends: p1-chatgpt-map]
- Dispatch Claude High with the chatgpt.yaml + KNOWN_FINDINGS.md + disconfirming mandate. Hand the live AT-SPI baseline from c3 screenshots. Asks: novel findings only; cross-platform interaction bugs taeys-hands missed.
- DONE-criteria: audit_logs/p1_chatgpt_claude.md committed.

### Task: p1-claude-map — Claude YAML full map (all thinking levels + research + connectors)  [priority: 22] [owner: taeys-hands] [tags: p1,catalog,claude] [depends: p1-chatgpt-peer-audit]
- Live click + AT-SPI scan on :3. Capture: models (Opus 4.8 High, Opus 4.8 Extra, Sonnet 4.6, Haiku 4.5), all thinking levels (None, Extended, High, Adaptive), Research mode, GitHub connector full flow (paste URL / select directory / Add files / capacity check), artifacts (preview_then_copy strategy), code blocks (Copy response NOT Copy).
- DONE-criteria: `consultation_v2/platforms/claude.yaml` updated. Lint gate green. PRODUCTION observation pasted.

### Task: p1-claude-peer-audit — Peer-audit Claude YAML (Gemini reviews)  [priority: 23] [owner: taeys-hands] [tags: p1,audit,cross-audit] [depends: p1-claude-map]

### Task: p1-gemini-map — Gemini YAML full map (Deep Think + Deep Research with Start Research click + tools)  [priority: 24] [owner: taeys-hands] [tags: p1,catalog,gemini] [depends: p1-claude-peer-audit]
- Live click + AT-SPI scan on :4. Capture: models (3.1 Pro, 3.5 Flash, 3.5 Thinking, 3.1 Pro Advanced math+code), modes (Deep Think, Deep Research with two-phase Start Research click — T30), tools (Deep research, Canvas, Create image, Guided learning), Gmail / Drive attachment menus, artifact extract (Share & Export → Copy menu item — T42), Deep Research follow-up Q&A within thread (T44).
- DONE-criteria: `consultation_v2/platforms/gemini.yaml` updated. Lint gate green. PRODUCTION observation: Deep Research dispatch with Start Research click auto-fires + artifact extracts to substantive content (not framing-only).

### Task: p1-gemini-peer-audit — Peer-audit Gemini YAML (Perplexity reviews)  [priority: 25] [owner: taeys-hands] [tags: p1,audit,cross-audit] [depends: p1-gemini-map]

### Task: p1-grok-map — Grok YAML full map (Heavy + Beta + Imagine + GitHub)  [priority: 26] [owner: taeys-hands] [tags: p1,catalog,grok] [depends: p1-gemini-peer-audit]
- Live click + AT-SPI scan on :5. Capture: models (Auto / Fast / Expert / Heavy Team of Experts / Grok 4.3 beta / 4.20 Beta — verify exact current names via screenshot), Imagine mode for X image generation, GitHub connector (Skills & Connectors path), attach menu, response Copy + artifact extract.
- Fix per T31/T32 root cause: mode_select halt-loud + scope to model_selector button uniquely (not picking sidebar workspace dropdowns).
- DONE-criteria: `consultation_v2/platforms/grok.yaml` updated. Lint gate green. PRODUCTION observation: Heavy + Beta + Imagine each dispatched and landing substantive output (Imagine = real image artifact).

### Task: p1-grok-peer-audit — Peer-audit Grok YAML (ChatGPT reviews)  [priority: 27] [owner: taeys-hands] [tags: p1,audit,cross-audit] [depends: p1-grok-map]

### Task: p1-perplexity-map — Perplexity YAML full map (DR + Model Council + Computer + connectors)  [priority: 28] [owner: taeys-hands] [tags: p1,catalog,perplexity] [depends: p1-grok-peer-audit]
- Live click + AT-SPI scan on :6. Capture: models (Sonar, GPT-4, Claude, Grok, etc.), modes (Deep Research, Model Council, Search, Computer), tools (Spaces, sources filter, academic/social/news scoping), pre-expand Show full report → Copy contents (T43), GitHub connector flow, multi-turn DR follow-up.
- DONE-criteria: `consultation_v2/platforms/perplexity.yaml` updated. Lint gate green. PRODUCTION observation: DR + Model Council each dispatched substantive.

### Task: p1-perplexity-peer-audit — Peer-audit Perplexity YAML (Grok reviews)  [priority: 29] [owner: taeys-hands] [tags: p1,audit,cross-audit] [depends: p1-perplexity-map]

### Task: p1-family-full-audit — Full-codebase Family audit at top tier (parallel) — POST p1 cycle  [priority: 30] [owner: taeys-hands] [tags: p1,audit,family-gate,top-tier] [depends: p1-perplexity-peer-audit]
- 5 dispatches in PARALLEL (per conductor cadence: full-codebase tier parallel OK because Git Connector independent). Top tier: ChatGPT Pro Extended / Claude Opus 4.x High / Gemini Deep Think / Grok Heavy / Perplexity DR (with Model Council where applicable). Each platform via its OWN Git Connector to the consultation-v2-isolated-drivers branch. KNOWN_FINDINGS.md handed in. Disconfirming mandate. Use REAL pending asks where possible (anti-fabrication rule).
- DONE-criteria: 5 verdicts committed (audit_logs/p1_full_{chatgpt,claude,gemini,grok,perplexity}.md). Hard gate for p2+.

## Phase: p2-haltloud — Mode/tool selection HALT-LOUD pre-send + multi-phase send  [order: 3]

> Eliminate silent-fallback mode selection. Add multi-phase send for Gemini DR + Perplexity DR. Add multi-turn follow-up.

### Task: p2-mode-validate — Pre-send YAML-vs-tree validation, HALT-LOUD on mismatch  [priority: 40] [owner: taeys-hands-codex] [tags: p2,build,halt-loud] [depends: p1-family-full-audit]
- Before clicking send: scan AT-SPI tree, verify the YAML-declared model/mode/tool is the one currently selected. If mismatch → HALT with explicit diagnostic (which YAML key, which expected value, which observed value, what dropdown state). No retry. No fall-through to default. (Closes T33.)
- DONE-criteria: code in consultation_v2/runtime.py. Lint gate green. PRODUCTION observation: deliberate mode mismatch produces HALT not silent send.

### Task: p2-multi-phase-send — Multi-phase send sequences for Gemini DR + Perplexity DR  [priority: 42] [owner: taeys-hands-codex] [tags: p2,build,multi-phase] [depends: p2-mode-validate]
- Gemini Deep Research: post-initial-send, scan for `Start research` push button; click it; THEN start monitor (closes T30). Perplexity DR: ensure pre-expand `Show full report` step lands when artifact appears (closes T43). YAML sequence pattern: `workflow.send.sequence` with intermediate `wait_for_indicator` + `click` steps.
- DONE-criteria: PRODUCTION observation: Gemini DR dispatch self-fires Start Research click; Perplexity DR dispatch auto-pre-expands.

### Task: p2-followup-session-url — Multi-turn follow-up support on existing thread  [priority: 44] [owner: taeys-hands-codex] [tags: p2,build,multi-turn] [depends: p2-multi-phase-send]
- `run_consultation_v2.py --session-url <URL>` for continuing in an existing DR/chat thread instead of creating fresh chat. Per Jesse 2026-05-31 (T44). Validates URL belongs to the requested platform; navigates; sends in-thread; extracts new response only.
- DONE-criteria: PRODUCTION observation: real DR follow-up Q&A landed substantive against existing thread.

### Task: p2-grok-audit — Grok ruthless audit of p2  [priority: 46] [owner: taeys-hands-grok] [tags: p2,audit] [depends: p2-mode-validate,p2-multi-phase-send,p2-followup-session-url]

### Task: p2-family-audit — Family per-platform audit of p2 (CROSS-AUDIT)  [priority: 48] [owner: taeys-hands] [tags: p2,audit,family-gate] [depends: p2-grok-audit]

## Phase: p3-extract-matrix — Per-platform per-output-type extraction  [order: 4]

> inline / research report / artifact extraction reliable per platform. Verified against real production runs.

### Task: p3-extract-spec — Spec the per-platform per-output-type extract matrix in EXTRACTION_PATTERNS.md  [priority: 50] [owner: taeys-hands-codex] [tags: p3,spec] [depends: p2-family-audit]
- Update `consultation_v2/EXTRACTION_PATTERNS.md` with the canonical extract sequence per (platform, output_type) cell. 5 × 3 = 15 cells minimum.
- DONE-criteria: spec committed. Reviewed by codex for completeness.

### Task: p3-implement — Implement the matrix as YAML workflow.extract sequences  [priority: 52] [owner: taeys-hands-codex] [tags: p3,build] [depends: p3-extract-spec]
- Each YAML's `workflow.extract` resolves which sequence to run based on detected output type (inline-prose / research-artifact / canvas-doc / image / etc.). Use existing primitives (click / read_clipboard / read_element_text / pre_expand_click / etc.).
- DONE-criteria: PRODUCTION observation: a real dispatch lands each output-type variant cleanly across all 5 platforms (15 observations total — accept in batches as real asks arrive).

### Task: p3-family-audit — Family per-platform audit of p3 extracts  [priority: 54] [owner: taeys-hands] [tags: p3,audit,family-gate] [depends: p3-implement]

## Phase: p4-monitors — Reliable completion notification  [order: 5]

### Task: p4-monitor-build — Per-platform completion-detect primitive  [priority: 60] [owner: taeys-hands-codex] [tags: p4,build] [depends: p3-family-audit]
- Per-platform spec: which AT-SPI element disappearance / appearance signals completion. Generic monitor process polls + notifies. Per Jesse 2026-05-31: monitors are required.
- DONE-criteria: PRODUCTION observation: 5 dispatches each land completion notifications correctly within seconds of actual completion.

### Task: p4-family-audit — Family audit of monitor reliability  [priority: 62] [owner: taeys-hands] [tags: p4,audit,family-gate] [depends: p4-monitor-build]

## Phase: p5-connectors — Git Connectors for all 5 platforms  [order: 6]

### Task: p5-connector-maps — Per-platform connector YAML maps (paste URL / select-all / capacity)  [priority: 70] [owner: taeys-hands] [tags: p5,catalog,connectors] [depends: p4-family-audit]
- For each platform: capture connector flow exact name+role per element. Per Jesse: paste URL → select top checkbox (select all) → handle capacity warning if any → Add files. Where platform has alternative auth flows (OAuth GitHub connector), capture those too.
- DONE-criteria: `--git-repo URL` works on all 5 platforms via real production dispatch.

### Task: p5-cross-audit — Cross-platform connector audit (ChatGPT audits Grok's, etc.)  [priority: 72] [owner: taeys-hands] [tags: p5,audit,cross-audit] [depends: p5-connector-maps]

### Task: p5-family-fullcodebase — Full-codebase Family audit via Git Connectors at TOP tier (parallel)  [priority: 74] [owner: taeys-hands] [tags: p5,audit,top-tier,parallel] [depends: p5-cross-audit]
- 5 parallel dispatches at TOP tier (Pro Extended / Opus 4.x High / Deep Think / Heavy / DR-with-Model-Council). Real Git Connector to the consultation-v2-isolated-drivers HEAD. KNOWN_FINDINGS.md handed in. Disconfirming mandate. Routed through a real outstanding code question where possible (anti-fabrication rule).
- DONE-criteria: 5 verdicts committed. Hard gate before p6 production flip.

## Phase: p6-prod-flip — Manual-to-automated production flip  [order: 7]

### Task: p6-prod-cutover — Multi-session production-run cutover discipline  [priority: 80] [owner: taeys-hands] [tags: p6,production,cutover] [depends: p5-family-fullcodebase]
- After p5 family verdict + mechanical gate green + production observations across the matrix: announce to fleet that consultation_v2 is the production path. Other sessions begin using it for their dispatches. Old V1 `scripts/consultation.py` callers can keep V1 (per Jesse: V1 out of scope — leave alone).
- DONE-criteria: 3+ non-taeys-hands sessions report successful dispatch via the new path with substantive output. Pasted observations.

### Task: p6-postcutover-audit — Post-cutover Family audit + control gate  [priority: 82] [owner: taeys-hands] [tags: p6,audit,family-gate] [depends: p6-prod-cutover]
- Final family verdict: is the system production-grade? Open mandate: find what is still wrong. Three-register.
- DONE-criteria: Family verdict committed. If ENDORSE across all 5 + Grok validate + Codex repo-scan green → close project. If BLOCKER → re-enter 6SIGMA loop on the specific blocker.
