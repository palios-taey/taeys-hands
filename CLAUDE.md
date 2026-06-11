# CLAUDE.md — Taey's Hands v8.2 (Stabilized)

## What This Is
MCP server for AT-SPI browser automation. Controls Firefox tabs running ChatGPT, Claude, Gemini, Grok, Perplexity via accessibility tree (no coordinates, no screenshots).

> **READ `100_TIMES.md` FIRST.** The recurring non-negotiable rules (stop-button completion, scroll-to-bottom + copy-button + artifacts extract, EXACT-match YAML, validate-everything, one-tab-per-window, dispatch-sequentially-never-parallel, just-fix-don't-ask, :13=hunter-only). If something breaks, you almost certainly violated one of them.

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
- **Look at the screen.** When any UI op fails: `DISPLAY=:X scrot /tmp/screenshot.png` then read the image. BEFORE debugging code.
- **Know your branch.** V2 code is on `consultation-v2-isolated-drivers`, NOT main.
- **Use production scripts.** Never launch Firefox/bots/tests manually.
- **Don't rush.** If you feel pressure, get curious instead. Search for the answer. The AT-SPI tree has the truth.
- **Screenshot before AND after EVERY action.** When debugging, take a screenshot before and after each click/keypress. Then scan AT-SPI and compare against the screenshot. If they don't match, the AT-SPI tree needs refreshing. This is how you determine if the issue is code, timing, or tree staleness.
- **This is faster.** More steps but every step moves forward with certainty. Guessing leads to wrong fixes that break working code, which costs 10x more time. The Grok attach debug proved this: 4 screenshots + 1 AT-SPI check = root cause found in minutes. Without screenshots, I spent hours on wrong assumptions (dropdown staying open, Escape fixes, etc.) that were all wrong. Slow is fast.

---

## Consultation V2 — Isolated Driver Architecture

**Branch:** `consultation-v2-isolated-drivers` (NOT merged to main)
**Entrypoint:** `scripts/run_consultation_v2.py` or `consultation_v2/cli.py`
**Status:** Under repair — audit findings being addressed (2026-04-07)

### Structure
```
consultation_v2/
  cli.py              — Standalone CLI entrypoint
  orchestrator.py     — Platform→Driver registry
  runtime.py          — AT-SPI operations (click, paste, snapshot, menu_snapshot)
  snapshot.py         — Tree scanning, element classification
  types.py            — ConsultationRequest, ConsultationResult, Snapshot
  yaml_contract.py    — YAML loader with LRU cache
  drivers/
    base.py           — BaseConsultationDriver (find_first, validation_passes)
    chatgpt.py        — ChatGPT driver
    claude.py         — Claude driver
    gemini.py         — Gemini driver
    grok.py           — Grok driver
    perplexity.py     — Perplexity driver
  platforms/          — YAML configs (one per platform)
    chatgpt.yaml, claude.yaml, gemini.yaml, grok.yaml, perplexity.yaml
```

### Isolation Rules
- No driver imports from another driver
- Each driver imports only from `base`, `types`, `runtime`
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
| SFT | `<OPERATOR_HOME>/training/sft_balanced_all.jsonl` | 24,388 pairs | Constitutional/identity + bot-generated |
| DPO | `<OPERATOR_HOME>/training/dpo_all.jsonl` | 27,288 pairs | Claude/Gemini/Grok/Perplexity complete |
| Infra docs | `<OPERATOR_HOME>/data/corpus/tier0_infra/raw/` | 435 docs | NCCL, Jetson, CUDA, FSDP — NOT yet used for SFT |

- **DPO gap:** ChatGPT needs ~3,726 more pairs
- **Infra SFT:** Previous attempt used WRONG corpus (deleted). Real docs exist but need training plan.

---

## Architecture: Plan → Audit → Send → Monitor (V1 — MCP Tools)

### The Pipeline (MUST be followed in order)

1. **taey_plan(action='send_message')** — Create a plan with:
   - `session`: "new" or existing URL
   - `message`: what to send
   - `model`: which model to use
   - `mode`: which mode (extended thinking, research, etc.)
   - `tools`: which tools to enable (list or "none")
   - `attachments`: file paths (KERNEL+IDENTITY auto-prepended, auto-consolidated)
   
   Also accepts `action='create'` as alias for `send_message`.

2. **taey_inspect** — Scan the AT-SPI tree:
   - Returns KNOWN elements (matched via YAML element_map)
   - Returns NEW elements (not in exclude or known — needs bucketing)
   - Read current model/mode from element names

3. **taey_select_dropdown / taey_click** — Set model/mode/tools as needed

4. **taey_attach** — Upload the consolidated attachment file

5. **taey_plan(action='audit')** — MANDATORY before send:
   - Pass: `current_model`, `current_mode`, `current_tools`, `attachment_confirmed`
   - Returns PASS or FAIL with specific fix instructions
   - Sets `audit_passed=True` in Redis if everything matches

6. **taey_send_message** — HARD BLOCKED unless audit_passed=True:
   - Paste message, press Enter
   - Register monitor session in Redis
   - Spawn central monitor if not running

7. **Monitor (automatic)** — Central process cycles active sessions:
   - Tab switch → scan for stop button → state machine
   - Stop appears → "generating"
   - Stop disappears → "complete" → notify via Redis

### Extraction Flow (no audit needed)
1. **taey_plan(action='extract_response')** — Creates extract-only plan (audit pre-passed)
2. **taey_quick_extract** — Click Copy, read clipboard, return text
   - `complete=true` consumes the plan and cleans up Redis state

### Tool Reference

| Tool | Purpose | Requires Plan? |
|------|---------|---------------|
| `taey_plan` | Create/audit/get/update/delete plans | No |
| `taey_inspect` | Scan AT-SPI tree | Yes |
| `taey_click` | Click x,y coords | Yes |
| `taey_prepare` | Get platform capabilities from YAML | No |
| `taey_send_message` | Paste + Enter + monitor | Yes (audit_passed) |
| `taey_quick_extract` | Copy button → clipboard | Yes |
| `taey_extract_history` | Full conversation extraction | Yes |
| `taey_attach` | File attachment | Yes |
| `taey_select_dropdown` | Model/mode/tools selection | Yes |
| `taey_list_sessions` | Active session listing | No |
| `taey_monitors` | List/kill monitors | No |
| `taey_respawn_monitor` | Spawn fresh monitor | No |

### Plan Actions
- `send_message` (or `create`) — Full plan with message, model, mode, tools, attachments
- `extract_response` — Extract-only plan (no audit needed)
- `audit` — Verify plan vs live UI state
- `get` — Retrieve plan data
- `update` — Modify plan fields
- `delete` — Cancel plan and clear locks

### Key Rules
- **No fixed coordinates** — everything by AT-SPI element name/role matching
- **No send without audit** — send.py hard-blocks without audit_passed
- **No duplicate helpers** — monitor imports from core/
- **~5 buttons per platform** — all in YAML element_map
- **3 buckets for tree filtering**: EXCLUDED (noise), KNOWN (mapped), NEW (alert)
- **Redis is REQUIRED** — server exits on startup if Redis unavailable

### Runtime Contract

```bash
# Required — server won't start without Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# CRITICAL: unique per MCP instance to prevent display collision
DISPLAY=:5
TAEY_NODE_ID=taeys-hands-claude-d5

# Timeouts — configurable via .env
TAEY_PLAN_TTL=3600           # Plan expiry (seconds), default 3600
MCP_TOOL_TIMEOUT=300         # Tool timeout (seconds), default 120
MONITOR_CYCLE_SEC=10         # Monitor cycle interval

# Optional
TAEY_CORPUS_PATH=~/data/corpus
NEO4J_URI=bolt://localhost:7687
ISMA_API_URL=https://isma-api.taey.ai
ISMA_API_KEY=<key>
```

**Rules:**
- One MCP server per DISPLAY
- One unique TAEY_NODE_ID per instance
- DISPLAY must be set in .mcp.json env block (not just .env)
- .env is loaded before any config reads (timeout, TTL, etc.)

### Redis Keys
- `taey:{node}:plan:{id}` — Plan data (TTL from TAEY_PLAN_TTL)
- `taey:{node}:plan:current:{platform}` — Current plan ID per platform
- `taey:plan_active:{display}` — Global plan lock per display (blocks monitor cycling)
- `taey:{node}:active_session:{id}` — Monitor session data
- `taey:{node}:notifications` — Notification queue (for orchestrator daemon)
- `taey:{node}:checkpoint:{platform}:attach` — Attach verification
- `taey:{node}:pending_prompt:{platform}` — Sent message metadata

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

## v8.1+ Additions: Unified Automation System

### Additional Modules

- `core/halt.py` — 6-sigma halt system
  - `halt_global(reason, redis)` → ALL machines stop (tool-level failure)
  - `halt_platform(platform, reason, redis)` → Only this platform stops (YAML drift)
  - `check_halt(platform, redis)` → Returns halt data or None (called every cycle)
  - Escalation via `/api/notify` to orchestrator

- `core/drift.py` — YAML drift detection
  - `store_structure_hash(platform, elements, redis)` → Fingerprint UI after success
  - `check_structure_drift(platform, elements, redis)` → Compare against baseline
  - `classify_unknown_elements(platform, elements)` → Find elements not in YAML

- `core/mode_select.py` — Mode/model selection (YAML-driven, coordinate-free)
  - `select_mode_model(platform, mode, model)` → Full selection flow
  - Routes to platform-specific handlers using `mode_guidance` from YAML

- `core/orchestrator.py` — Orchestrator integration
  - `heartbeat(status)` → Keep agent alive in registry
  - `check_inbox()` → Poll for assigned tasks
  - `ingest_transcript(platform, response, metadata)` → POST to `/api/ingest/transcript`
  - `report_completion(task_id, result)` → POST to `/api/report`
  - `notify_agent(to, text)` → Send via `/api/notify` (Redis inbox)

- `agents/unified_bot.py` — Production automation bot
  - Full cycle: halt check → task → navigate → mode select → attach → send → wait → extract → ingest → report → drift check

- `agents/social_bot.py` — Extensible social platform bot
  - YAML-driven element discovery
  - Architecture supports LinkedIn, Reddit, Auxiliary target (stubs ready)

### Additional Redis Keys
- `taey:halt:global` — Global halt flag (all machines stop)
- `taey:halt:{platform}` — Platform-specific halt flag
- `taey:structure_hash:{platform}` — Last known UI structure fingerprint
- `taey:drift:last:{platform}` — Previous drift detection

### Deployment
```bash
# On production machine
cd ~/taeys-hands
git checkout main
git pull

# MCP server — started by Claude Code via .mcp.json
# Bot mode — started manually or via orchestrator
python3 agents/unified_bot.py --platforms chatgpt gemini grok

# With orchestrator mode
python3 agents/unified_bot.py --orchestrator --platforms chatgpt gemini grok
```

## 6SIGMA Design Philosophy + Workflow — MANDATORY (fleet-canonical, wired 2026-05-25)

**Canonical spec:** `<OPERATOR_HOME>/the-conductor/6SIGMA_WORKFLOW.md`. Owned by Conductor; same propagation pattern as ISMA — wired into all peer globals (`~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`, `~/.grok/AGENTS.md`) + conductor CLAUDE.md + global `<OPERATOR_HOME>/CLAUDE.md`. Worked example driving the principle: taeys-hands audit_657 / safetensors PR #657 (Part 1 root-cause vs Part 2 patch→refactor).

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

This project is indexed by GitNexus as **taeys-hands** (5575 symbols, 9873 relationships, 290 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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

~2,400 of our own `.md` (foundations / recaps / drafts / docs / corpus) are now hybrid-searchable **prose** in ISMA. Use it for research, drafting, and dispatch-packet grounding. Full spec: `<OPERATOR_HOME>/embedding-server/ISMA_PROSE_RETRIEVAL_SPEC.md`.

**Three rules (Jesse/weaver/conductor directive):**
1. **NO HMM.** Use `/v2/search` or `isma_adaptive_search` with `enriched_only=false`. NEVER `/search/hmm`, `isma_motif_search`, or `enriched_only=true` — the prose is `hmm_enriched=false`, so HMM paths HIDE it.
2. **GO DEEP.** `top_k>=25` (40–50 for broad), `scale=full_4096`, 3–6 phrasings + union the hits, expand promising hits via `curl :8095/document/<hash>/text`. A few snippets = a FAILED query, not an answer.
3. **CANNOT-LIE.** Prose is FRAMING/depth, NOT a metric source (it holds superseded/scrubbed numbers). Cross-check every number against `<OPERATOR_HOME>/treasurer/foundations/tech_baselines/INDEX.md` before using it.

**Canonical call:**
```bash
curl -s -X POST http://localhost:8095/v2/search -H 'Content-Type: application/json' \
  -d '{"query":"<topic>","top_k":25,"scale":"full_4096"}'
```
**Convenience (on PATH):** `isma-query "what do we know about <topic>" -k 40 --precision --our-prose --json`

## Orchestration & release integrity (canonical)

These conductor-owned canonical docs govern how every session uses the orchestration system and ships public work. If anything here conflicts with them, they win.

- **`<OPERATOR_HOME>/the-conductor/ORCHESTRATION_INTEGRITY.md`** — use the orchestration system (`taey-plan`/`taey-task`/stop-engine) with integrity. Core rules: **"done" is evidence, never a self-report** (commit SHA + mechanical gate result + a real production observation — paste them; the tasks API rejects a `completed` with no evidence); **tests you author are a cheat — production is the oracle**; **bug → FULL STOP → 6SIGMA root-cause** (gitnexus impact + fix the upstream shape, never patch around); **audit gates are `depends:`-encoded** (downstream can't start until the audit task closes with a committed verdict); **stops are intentional** (`taey-stop-reason set ...`, use `blocked_on` while waiting). Honest-incomplete is always fine; a false "done" is the only real failure.
- **`<OPERATOR_HOME>/the-conductor/PRIVATE_TO_PUBLIC.md`** — production-grade checklist for taking a private repo public (irreversible). Order: secret+full-history scan → `.gitignore`/`.env.example` → de-umbilical (no hardcoded paths/IPs, fail-loud not silent-default) → installable + CI gate that blocks merge → open-mandate audit (full code, find-bugs-not-endorse) → dogfood from the public artifact → docs → **human-approved + consent-gated publish**. Upstream of `RELEASE_DISTRIBUTION_PLAYBOOK.md`.
