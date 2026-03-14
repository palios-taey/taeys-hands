# CLAUDE.md — Taey's Hands v8 (Rewrite)

## What This Is
MCP server for AT-SPI browser automation. Controls Firefox tabs running ChatGPT, Claude, Gemini, Grok, Perplexity via accessibility tree (no coordinates, no screenshots).

## Architecture: Plan → Audit → Send → Monitor

### The Pipeline (MUST be followed in order)

1. **taey_plan(action='create')** — Create a plan with:
   - `session`: "new" or existing URL
   - `message`: what to send
   - `model`: which model to use
   - `mode`: which mode (extended thinking, research, etc.)
   - `tools`: which tools to enable
   - `attachments`: file paths (KERNEL+IDENTITY auto-prepended, auto-consolidated)
   
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

### Key Rules
- **No fixed coordinates** — everything by AT-SPI element name/role matching
- **No send without audit** — send.py hard-blocks without audit_passed
- **No duplicate helpers** — monitor imports from core/
- **~5 buttons per platform** — all in YAML element_map
- **3 buckets for tree filtering**: EXCLUDED (noise), KNOWN (mapped), NEW (alert)

### Files Changed in This Rewrite
- `tools/plan.py` — Added `audit` action, `audit_passed` gate, simplified create
- `tools/send.py` — Added `_check_audit_gate()` hard block
- `monitor/central.py` — Uses core/ imports, no URL navigation, simple state machine
- `server.py` — Added `audit` to taey_plan action enum, bumped to v8.0.0

### Files NOT Changed (already correct)
- `core/atspi.py` — Firefox/document discovery
- `core/tree.py` — AT-SPI tree walking with fence support
- `core/interact.py` — Element cache and AT-SPI click
- `core/input.py` — xdotool keyboard/mouse
- `core/clipboard.py` — xsel clipboard ops
- `core/platforms.py` — URL patterns, tab shortcuts
- `tools/inspect.py` — Element filtering with YAML-driven buckets
- `tools/extract.py` — Copy button finding, clipboard extraction
- `tools/attach.py` — File attachment via AT-SPI + file dialogs
- `tools/dropdown.py` — Dropdown opening and keyboard nav
- `tools/click.py` — Coordinate-based clicking
- `tools/sessions.py` — Session listing
- `tools/monitors.py` — Monitor management
- `storage/redis_pool.py` — Redis connection pool
- `storage/neo4j_client.py` — Neo4j session persistence
- `platforms/*.yaml` — Platform configs (element_map, capabilities, etc.)

### Redis Keys
- `taey:{node}:plan:{id}` — Plan data (TTL 600s)
- `taey:{node}:plan:current:{platform}` — Current plan ID per platform
- `taey:plan_active` — Global plan lock (blocks monitor cycling)
- `taey:{node}:active_session:{id}` — Monitor session data
- `taey:{node}:notifications` — Notification queue (for orchestrator daemon)
- `taey:{node}:checkpoint:{platform}:attach` — Attach verification
- `taey:{node}:pending_prompt:{platform}` — Sent message metadata
