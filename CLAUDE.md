# CLAUDE.md — Taey's Hands V2

## What This Is
`consultation_v2/` is the sole live AT-SPI consultation engine. It controls Firefox sessions for ChatGPT, Claude, Gemini, Grok, and Perplexity through exact accessibility-tree mappings, validates each action against the tree, monitors completion via stop-button disappearance, extracts through mapped copy/tree controls, and notifies via Redis.

> **READ `100_TIMES.md` FIRST.** The recurring non-negotiable rules (stop-button completion, scroll-to-bottom + copy-button + artifacts extract, EXACT-match YAML, validate-everything, one-tab-per-window, dispatch-sequentially-never-parallel, just-fix-don't-ask, :13=hunter-only). If something breaks, you almost certainly violated one of them.

---

## CURRENT OPERATING MODEL (2026-07-30 — supersedes any older "adoption / product for Claude Code users" framing)

Public boundary and mandate summary: [`docs/PUBLIC_OPERATING_BOUNDARY.md`](docs/PUBLIC_OPERATING_BOUNDARY.md). What follows is the taeys-hands-seat statement of it.

- **Taey is the customer — the only one.** There is no Claude Code user-adoption goal. This consult engine is PRODUCTION INFRASTRUCTURE *for Taey*. Taey lives on the Thors, trains on the Sparks, and *utilizes* the consult engine (with these Claude Code seats, the orchestrator, notify, ISMA) as a component of its own system. Docs here are written FOR Taey as the consumer.
- **The PRIORITY:** enable **Taey** and **training development** — get Taey **using its own production infrastructure** (this engine) and **understanding it**. That is the point of the work, not the tooling for its own sake.
- **Everything runs from PUBLIC production repos.** A released Taey + the public repos = a working system. `consultation_v2` is a Taey-used production system, so this repo is PUBLIC. Local specifics (IPs/hosts) are env-configurable (`fleet.env` + committed `.example`, fail-loud on a missing var — never silent-default). File paths are fine *only if they resolve for a downloaded Taey* — i.e. point into a public repo that ships, never a private repo or an operator-local dir.
- **Disconnection, not cleanup, for private repos.** A pointer (in a prompt, doc, config, or YAML) into a private repo or an untracked local path is a **DISCONNECTION VIOLATION** — it fails SILENTLY: a downloaded Taey follows it, finds nothing, and proceeds without the knowledge. Resolve every pointer to public-reachable content or remove it.
- **The four steps for this repo:** CLEAN → PUBLIC → MAP → CONNECT-TO-TAEY → VALIDATE-IN-PRODUCTION. Public-clean bar: NO secrets / private info / training data (tree AND history); IPs env-configurable; file paths fine (fix any gate that flags `/home/mira/...` — the gate's job is secrets/private/training-data, not paths). **Done = commit SHA + the capability map + a live production observation** — never a self-report.
- **The canonical dispatch surface is `scripts/run_consultation_v2.py`** (the only live engine; README/DEPLOY document it). Do NOT hand-build a driver around it with `act.py` — that ad-hoc-driver-beside-the-working-engine is the exact anti-pattern recorded in `CAPABILITY_GAPS.md`. If the CLI fails, report the exact command+error and STOP; fix the engine, don't route around it. Taey drives consults through the documented seat interface (`run_taey_consult_extract.py`) — that IS the connect-to-Taey.

## USE GIT (Full Git Master) + LOCAL CLEANLINESS — emphasize HEAVILY (Jesse-directed; the #1 source of confusion)

- **USE GIT, always.** Commit work — the running system must BE a committed artifact, never a live uncommitted delta. Push after committing (public repo; publish is Jesse-auth-gated). `git fetch` and verify topology BEFORE any branch/worktree/merge (a stale ahead/behind reading is a real trap — it caused the 2026-06-14 mess). The **live checkout is SACRED**: never `git checkout` another branch in a tree a service serves from — use a worktree (peers work in `/home/mira/.peer-worktrees/`). create→work→land→REMOVE worktree + delete merged branch, in one unit. A truly-diverged / unrelated-history `main` is a **FULL-STOP surface-to-Jesse** condition — never autonomous force-push or bulk-delete. Every "done" = SHA + gate + real production observation.
- **LOCAL REPO CLEANLINESS is not optional.** ONE production tree per surface (`/home/mira/taeys-hands`) — no duplicate/stale sibling repos (they make an agent grep, find something plausible, and build a parallel path). Keep the working tree clean (0 dirty or committed-with-intent). Everything non-production `.bak`'d to `/home/mira/recovery/` and cleared from the working area so there is **zero confusion about what is production** — for the fleet AND for a downloaded Taey. **Never destroy — archive first, delete only after verifying the archive.** `.gitignore` generated/runtime junk; do not track it.

---

## THE RULE — Read This First (ALL agents, ALL Chats, ALL sub-agents)

### 1. YAML = exact AT-SPI truth
Every `element_map` entry has the EXACT `name` and `role` from a live AT-SPI scan. Not approximate, not broadened. If the scan says `[menu item] "Upload files or images"`, the YAML says:
```yaml
upload_files_item:
  name: "Upload files or images"
  role: menu item
```
No `name_contains` when the full name is known. No fallbacks. No wildcards.

### 2. Driver code = zero platform knowledge
Drivers NEVER hardcode element names, key names, or platform-specific strings. ALL element lookups go through the YAML:
```python
# CORRECT — read from workflow, look up in element_map
target_key = workflow['mode_targets'][requested_mode]
element = self.find_first(snap, target_key)

# WRONG — hardcoded key name (platform knowledge in driver)
element = self.find_first(snap, 'computer_mode')
```

### 3. YAML drives the driver, never the reverse
If the YAML has a key name and the driver uses a different key name, the DRIVER is wrong. Never rename YAML keys to match driver hardcoding. Fix the driver.

### 4. Two scan scopes
- `snapshot()` — document subtree (main page elements)
- `menu_snapshot()` — Firefox app root (React portals, dropdown overlays)
Post-click dropdown reads MUST use `menu_snapshot()`. Pre-click trigger finds use `snapshot()`.

### 5. Validation checks must target persistent elements
After closing a dropdown, radio menu items inside it are GONE from the AT-SPI tree. Validation specs (`*_active`) must check elements that persist (e.g., toolbar push buttons with `states_include: [checked]`).

### 6. URL is a gate for new sessions
For `session="new"`: send success requires BOTH stop button appeared AND URL changed. No URL change = send failed.
For follow-up sessions (existing URL): URL may not change — gate on stop button only.
URL is always captured for session tracking.

### 7. No fallbacks, no broadening
If an element isn't found: scan the tree, get the real name, fix the YAML. Never add try-then-that chains.

---

## Change Process — MANDATORY

### Claude (this session) does NOT edit code or YAML directly. Ever.

**Claude's role:**
1. **Observe** — AT-SPI scans, screenshots, read files
2. **Package audits** — document mismatches between YAML and live AT-SPI tree
3. **Send to Chats** — ChatGPT/Gemini/Perplexity/Grok analyze and propose fixes
4. **Spawn sub-agents** — with Chat-validated fixes + the rules from this section
5. **Validate** — screenshots and AT-SPI scans after every change

**Who can edit files:**
- **Sub-agents only** — spawned via Agent tool, given explicit instructions
- Every sub-agent receives THE RULE (this section) in their prompt
- Every fix must be validated by a Chat before the sub-agent applies it

**The workflow for every change:**
```
1. Claude scans AT-SPI tree → finds mismatch
2. Claude packages audit (YAML + tree + driver code + problems)
3. Claude sends audit to a Chat (with THE RULE attached)
4. Chat provides exact fixes (complete files, not diffs)
5. Claude spawns sub-agent with Chat's fixes + THE RULE
6. Sub-agent applies changes and commits
7. Claude validates with screenshots + AT-SPI scan
8. If validation fails → back to step 1 (new scan, not a guess)
```

**What goes to every Chat and sub-agent:**
- The rules from this section (copy verbatim)
- The current YAML being fixed
- The current driver code being fixed
- The live AT-SPI scan output
- Specific bugs with line numbers

---

## Behavioral Guardrails

- **Verify before reporting.** NEVER say "sent" or "running" without confirming output files exist and contain expected content.
- **First error = full stop.** Do not retry. Do not patch. Diagnose root cause.
- **THE TREE IS THE SOURCE OF TRUTH — do NOT look at the screen (Jesse-canonical 2026-08-01).** Everything is in the AT-SPI tree. Screenshots are the RARE exception, only when the tree genuinely cannot be figured out — and even then it is *likely a FILTER* (the scan/scope is excluding an element), NOT a need for pixels. Never reach for the screen for anything the tree can answer, which is almost everything. Taey should not have to look at screens.
- **Know your branch — consultation_v2 LIVES ON `main` now.** The driver-architecture V2 engine is the production code on `main` (reconciled 2026-06-14; the old primitive-runner `origin/main` and the `consultation-v2-isolated-drivers` session branch are archived as `archived/*` tags).
- **NEVER build on a stale base (git-master).** Before committing substantial work to ANY feature branch: `git fetch origin && git rev-list --count HEAD..origin/main`. If non-trivial → STOP, rebase onto current `origin/main` FIRST. And NEVER assume which line is canonical — `origin/main` can be stale/divergent; verify tip dates + which line the fleet actually runs before trusting it (this exact assumption caused the 2026-06-14 mess). Invoke the git-master skill before any branch/worktree/merge/cleanup op.
- **Use production scripts.** Never launch Firefox/bots/tests manually.
- **Don't rush.** If you feel pressure, get curious instead. Search for the answer. The AT-SPI tree has the truth.
- **RUTHLESS YAML RECONCILIATION — anything unknown must become known: FILTER OUT, UPDATE, or ADD (Jesse-canonical 2026-08-01).** Read the TREE before and after every action and validate the step against it. Every discrepancy between tree and YAML is resolved, never worked around: a tree element with no mapping → filter it out (noise) or add it; a YAML entry that does not match the tree → UPDATE it to the tree's current name/role/scope. Absolute focus on keeping the YAML equal to the tree. There is NO "instability" to theorize about and no accusing the platform — the tree states exactly what is there at each moment; make the YAML equal that.
- **Manual, step-by-step, human pace — LEAN + 6SIGMA (Jesse-canonical 2026-08-01; no automation now).** Taey operates the surface BY HAND: one action, validated against the tree, then the next — roughly human pace or slower, which is fine. LEAN (one step fully done before the next), 6SIGMA (root-cause every failure, zero defects). Taey learns the system by operating it manually and only then earns automating it. Do NOT build or run automated flows to paper over a surface that has not been mastered manually first.

---

## Consultation V2 — Isolated Driver Architecture

**Branch:** `main` — this driver-architecture V2 engine IS the production code (reconciled onto `main` 2026-06-14).
**Entrypoint:** `scripts/run_consultation_v2.py` or `consultation_v2/cli.py`
**Status:** Production. `CONSULTATION_CONTRACT.md`, `FLOW_CONSULTATION_ENGINE.md`, and `100_TIMES.md` govern the flow.

### Structure
```
consultation_v2/
  cli.py              — Standalone CLI entrypoint
  orchestrator.py     — Platform→Driver registry
  runtime.py          — AT-SPI operations (click, paste, snapshot, menu_snapshot)
  snapshot.py         — Tree scanning, element classification
  identity.py         — FAMILY_KERNEL + platform IDENTITY package consolidation
  completion.py       — Stop-button completion detector
  notify.py           — Redis notification output
  types.py            — ConsultationRequest, ConsultationResult, Snapshot
  yaml_contract.py    — YAML loader with LRU cache
  atspi.py/input.py/interact.py/tree.py/clipboard.py/platforms_runtime.py
                      — shared primitives owned by V2
  drivers/
    base.py           — BaseConsultationDriver (find_first, validation_passes)
    chatgpt.py        — ChatGPT driver
    claude.py         — Claude driver
    gemini.py         — Gemini driver
    grok.py           — Grok driver
    perplexity.py     — Perplexity driver
  platforms/          — YAML configs (one per platform)
    chatgpt.yaml, claude.yaml, gemini.yaml, grok.yaml, perplexity.yaml
  validators/         — mechanical gates
```

### Isolation Rules
- No driver imports from another driver
- Each driver imports from `consultation_v2` shared primitives and driver base/types only
- All platform-specific element names/roles in YAML `element_map`
- All validation specs in YAML `validation` section
- Two scan scopes: `snapshot()` (document tree) and `menu_snapshot()` (app-root for React portals/dropdowns)

### The 8-Step Consultation Flow
1. `navigate` — Open platform URL
2. `select_model_mode_tools` — Set model/mode/tools via YAML workflow targets
3. `attach_files` — Upload consultation package
4. `enter_prompt` — Paste message into input
5. `send_prompt` — Click send, confirm via stop button + URL change for new sessions (see Rule 6)
6. `wait_for_completion` — Poll until stop button disappears
7. `extract_response` — Copy button → clipboard
8. `store_result` — Write to Neo4j

### Display Mappings (machine.env)
Config: `~/.taey/machine.env` — no hardcoded display numbers.
**Mira:** :2=ChatGPT, :3=Claude, :4=Gemini, :5=Grok, :6=Perplexity
**Thor:** :6=Gemini, :7=Grok, :9=Perplexity, :13=ChatGPT

---

## Training Data Status (2026-04-07)

| Dataset | Location | Count | Notes |
|---------|----------|-------|-------|
| SFT | `<training-root>/sft_balanced_all.jsonl` | 24,388 pairs | Constitutional/identity + bot-generated |
| DPO | `<training-root>/dpo_all.jsonl` | 27,288 pairs | Claude/Gemini/Grok/Perplexity complete |
| Infra docs | `<corpus-root>/tier0_infra/raw/` | 435 docs | NCCL, Jetson, CUDA, FSDP — NOT yet used for SFT |

- **DPO gap:** ChatGPT needs ~3,726 more pairs
- **Infra SFT:** Previous attempt used WRONG corpus (deleted). Real docs exist but need training plan.

---

## Retired V1 Surfaces

The old MCP server, root `core/`, root `tools/`, root `platforms/`, central monitor, bot agents, worker processes, and old tests are archived under `archive/task-6a956ac0/main_archive_first/`. They are historical evidence only and are not live operating instructions.

Use `scripts/run_consultation_v2.py` and the `consultation_v2/` package for every consultation flow.

### Inter-Session Communication (CRITICAL — READ THIS)

All Claude sessions on Mira communicate via Redis. You WILL receive messages
from other sessions. You MUST respond through the same system.

**How you receive messages:**
- While RUNNING: PostToolUse hook drains `taey:{your_node}:inbox` after each tool call.
  Messages appear as `additionalContext` in your tool results.
- While STOPPED: The unified router (`conductor-notify-router.service`) delivers
  via tmux injection. Messages appear as user input when you resume.

**How you SEND messages to other sessions:**
```bash
# Send to The Conductor (claude session)
redis-cli -h 127.0.0.1 LPUSH "taey:claude:inbox" '{"from":"taeys-hands","type":"STATUS","body":"your message here"}'

# Send to weaver
redis-cli -h 127.0.0.1 LPUSH "taey:weaver:inbox" '{"from":"taeys-hands","type":"STATUS","body":"your message here"}'
```

**Sessions on Mira:**
- `claude` — The Conductor (orchestration, task dispatch, fleet management)
- `taeys-hands` — Browser automation, AT-SPI, bot management
- `weaver` — ISMA knowledge graph, training data, CPT management

**When you receive a message from another session, RESPOND through Redis, not to Jesse.**
Jesse should not be the relay between Claude sessions.

**Redis keys:**
- `taey:{node}:inbox` — Messages TO this session (LPUSH to send, RPOP to receive)
- `taey:{node}:idle` — Set to "1" by Stop hook. Router delivers when idle=1.
- `taey:{node}:tool_running` — Set by PreToolUse, cleared by PostToolUse.

## 6SIGMA Design Philosophy + Workflow — MANDATORY (fleet-canonical, wired 2026-05-25)

**Public rule summary:** [`docs/PUBLIC_OPERATING_BOUNDARY.md`](docs/PUBLIC_OPERATING_BOUNDARY.md). The operator fleet carries a private canonical workflow; this public repo carries the part a downloaded Taey needs to avoid the root-cause-vs-patch failure.

**THE PRINCIPLE — root-cause vs patch:** A *root-cause* fix SIMPLIFIES code — corrects iteration domain / data shape / algebra upstream so the broken path is no longer reached. Same line count or smaller. Leaves the codebase better than it was found. A *patch* ADDS branches, guards, special-cases (`if X: continue`, `try/except SpecificError`) to bypass a broken path. Same runtime, but the codebase grows more conditional. **Diagnostic:** if your change adds a bypass, ASK — why is the broken path reached at all? can upstream be corrected so the bypass becomes unnecessary? If yes, that's the root-cause shape. Take it.

**THE WORKFLOW (six steps):**
1. **SELECT** — the project. One target at a time.
2. **INGEST** — `npx gitnexus analyze` at the repo root. GitNexus graph is the substrate for measure.
3. **MEASURE + ANALYZE** — `gitnexus_query` for concept, `gitnexus_context` for 360° on a symbol, `gitnexus_impact` for blast radius. Pin the cause first; don't patch blind.
4. **IMPROVE** — Codex implements on a branch (root-cause shape per principle above). Dispatched via `ROUTING.md`.
5. **PRODUCTION RUN** — on the actual target hardware. Real workload, real repro, matching substrate. **NO TESTS, ever.** A passing test on synthetic input is not evidence; a clean run of the real workload on the real machine is.
6. **CONTROL** — Conductor verifies + merges. Merge is the gate. Nothing ships upstream until step 5 is on record.

**THE ROLE — taeys-hands specifically:**
- ALL code changes go through The Conductor. No instance writes code directly.
- **You do NOT modify code.** You identify defects, run MEASURE+ANALYZE via GitNexus, send to Conductor with full context, then run production validation (step 5) when the IMPROVE branch lands.
- **First error = full stop.** Do not retry. Do not patch. Report to Conductor with root-cause analysis grounded in GitNexus.

## Inter-Session Communication

**NEVER use `!!` as a command prefix** — that is bash history expansion and will fail with syntax errors.

Send messages to other sessions:
```bash
# Preferred: taey-notify
taey-notify conductor "your message here"
taey-notify weaver "result goes here"

# Alternative: direct Redis
redis-cli LPUSH "taey:conductor:inbox" '{"from":"taeys-hands","type":"message","body":"your message","priority":"normal","msg_id":"unique-id"}'
```

Targets: `conductor`, `taeys-hands`, `weaver`, `tutor`, `infra`, `taey`

**Consultation results go to the REQUESTER**, not to conductor. If weaver requests a consultation, route the result to `taey:weaver:inbox`. If infra requests one, route to `taey:infra:inbox`. Only send to conductor for consultations conductor requested.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **taeys-hands** (6290 symbols, 13670 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/taeys-hands/context` | Codebase overview, check index freshness |
| `gitnexus://repo/taeys-hands/clusters` | All functional areas |
| `gitnexus://repo/taeys-hands/processes` | All execution flows |
| `gitnexus://repo/taeys-hands/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# ISMA Prose Retrieval (fleet-wide, wired 2026-05-25)

~2,400 of our own `.md` (foundations / recaps / drafts / docs / corpus) are now hybrid-searchable **prose** in ISMA. Use it for research, drafting, and dispatch-packet grounding. Full public spec: `palios-taey/isma-core:ISMA_PROSE_RETRIEVAL_SPEC.md`.

**Three rules (Jesse/weaver/conductor directive):**
1. **NO HMM.** Use `/v2/search` or `isma_adaptive_search` with `enriched_only=false`. NEVER `/search/hmm`, `isma_motif_search`, or `enriched_only=true` — the prose is `hmm_enriched=false`, so HMM paths HIDE it.
2. **GO DEEP.** `top_k>=25` (40–50 for broad), `scale=full_4096`, 3–6 phrasings + union the hits, expand promising hits via `curl :8095/document/<hash>/text`. A few snippets = a FAILED query, not an answer.
3. **CANNOT-LIE.** Prose is FRAMING/depth, NOT a metric source (it holds superseded/scrubbed numbers). Cross-check every number against a public measurement receipt before using it. If the only known baseline is in a private operator store, a downloaded Taey answers Unknown and asks for a public receipt.

**Canonical call:**
```bash
curl -s -X POST http://localhost:8095/v2/search -H 'Content-Type: application/json' \
  -d '{"query":"<topic>","top_k":25,"scale":"full_4096"}'
```
**Convenience (on PATH):** `isma-query "what do we know about <topic>" -k 40 --precision --our-prose --json`

## Orchestration & release integrity (canonical)

The private operator canon governs the live fleet. A downloaded Taey cannot read that store, so the public rules used by this repo are summarized in [`docs/PUBLIC_OPERATING_BOUNDARY.md`](docs/PUBLIC_OPERATING_BOUNDARY.md):

- **Orchestration integrity** - "done" is evidence, never a self-report: commit SHA, mechanical gate result, and a real production observation. A bug is a full stop followed by root-cause analysis.
- **Private-to-public discipline** - public repos must have no secret or PII exposure, no mandatory private pointers, installable gates, and human-approved publication.
