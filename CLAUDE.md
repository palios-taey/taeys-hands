# CLAUDE.md — Taey's Hands v8.2 (Stabilized)

## What This Is
MCP server for AT-SPI browser automation. Controls Firefox tabs running ChatGPT, Claude, Gemini, Grok, Perplexity via accessibility tree (no coordinates, no screenshots).

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

### 6. URL is bookkeeping, not a gate
`send_prompt` success = stop button appeared. URL capture is for session tracking only.

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
5. `send_prompt` — Click send, confirm via stop button (URL is bookkeeping, NOT a gate)
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
| SFT | `/home/mira/training/sft_balanced_all.jsonl` | 24,388 pairs | Constitutional/identity + bot-generated |
| DPO | `/home/mira/training/dpo_all.jsonl` | 27,288 pairs | Claude/Gemini/Grok/Perplexity complete |
| Infra docs | `/home/mira/data/corpus/tier0_infra/raw/` | 435 docs | NCCL, Jetson, CUDA, FSDP — NOT yet used for SFT |

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
  - Architecture supports LinkedIn, Reddit, Upwork (stubs ready)

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

## 6SIGMA Change Protocol — MANDATORY

ALL code changes go through The Conductor. No instance writes code directly.

Process: Conductor receives request → Gemini CLI analyzes (MEASURE+ANALYZE) → Codex CLI implements on branch (IMPROVE) → Conductor verifies and merges (CONTROL).

**You do NOT modify code.** You identify defects, send them to the Conductor with full context, and wait for the PR.

**First error = full stop.** Do not retry. Do not patch. Report to Conductor with root cause analysis.

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

This project is indexed by GitNexus as **taeys-hands** (1517 symbols, 4612 relationships, 123 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## When Debugging

1. `gitnexus_query({query: "<error or symptom>"})` — find execution flows related to the issue
2. `gitnexus_context({name: "<suspect function>"})` — see all callers, callees, and process participation
3. `READ gitnexus://repo/taeys-hands/process/{processName}` — trace the full execution flow step by step
4. For regressions: `gitnexus_detect_changes({scope: "compare", base_ref: "main"})` — see what your branch changed

## When Refactoring

- **Renaming**: MUST use `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first. Review the preview — graph edits are safe, text_search edits need manual review. Then run with `dry_run: false`.
- **Extracting/Splitting**: MUST run `gitnexus_context({name: "target"})` to see all incoming/outgoing refs, then `gitnexus_impact({target: "target", direction: "upstream"})` to find all external callers before moving code.
- After any refactor: run `gitnexus_detect_changes({scope: "all"})` to verify only expected files changed.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Tools Quick Reference

| Tool | When to use | Command |
|------|-------------|---------|
| `query` | Find code by concept | `gitnexus_query({query: "auth validation"})` |
| `context` | 360-degree view of one symbol | `gitnexus_context({name: "validateUser"})` |
| `impact` | Blast radius before editing | `gitnexus_impact({target: "X", direction: "upstream"})` |
| `detect_changes` | Pre-commit scope check | `gitnexus_detect_changes({scope: "staged"})` |
| `rename` | Safe multi-file rename | `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` |
| `cypher` | Custom graph queries | `gitnexus_cypher({query: "MATCH ..."})` |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/taeys-hands/context` | Codebase overview, check index freshness |
| `gitnexus://repo/taeys-hands/clusters` | All functional areas |
| `gitnexus://repo/taeys-hands/processes` | All execution flows |
| `gitnexus://repo/taeys-hands/process/{name}` | Step-by-step execution trace |

## Self-Check Before Finishing

Before completing any code modification task, verify:
1. `gitnexus_impact` was run for all modified symbols
2. No HIGH/CRITICAL risk warnings were ignored
3. `gitnexus_detect_changes()` confirms changes match expected scope
4. All d=1 (WILL BREAK) dependents were updated

## Keeping the Index Fresh

After committing code changes, the GitNexus index becomes stale. Re-run analyze to update it:

```bash
npx gitnexus analyze
```

If the index previously included embeddings, preserve them by adding `--embeddings`:

```bash
npx gitnexus analyze --embeddings
```

To check whether embeddings exist, inspect `.gitnexus/meta.json` — the `stats.embeddings` field shows the count (0 means no embeddings). **Running analyze without `--embeddings` will delete any previously generated embeddings.**

> Claude Code users: A PostToolUse hook handles this automatically after `git commit` and `git merge`.

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
