# CLAUDE.md — Taey's Hands v8.2 (Stabilized)

## What This Is
MCP server for AT-SPI browser automation. Controls Firefox tabs running ChatGPT, Claude, Gemini, Grok, Perplexity via accessibility tree (no coordinates, no screenshots).

## Architecture: Plan → Audit → Send → Monitor

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
