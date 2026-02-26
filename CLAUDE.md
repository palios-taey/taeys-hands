# Taey's Hands - Operational Guide
*AT-SPI-based chat and social platform automation*

**Version**: 5.0 (February 2026 - Clean Rebuild)

---

## What This Is

AT-SPI-native automation for chat and social platforms using Linux accessibility APIs.
Not browser automation (no CDP/WebDriver) - genuine accessibility tree perception.

**Core insight**: "I'm blind - AT-SPI is designed for blind users."

---

## Architecture

```
server.py              # MCP router (~600 lines) - LOCKED
core/                  # AT-SPI primitives - FROZEN
  atspi.py             # Firefox/desktop discovery
  tree.py              # BFS traversal, element filtering
  clipboard.py         # xclip read/write
  input.py             # xdotool key/mouse/type
  platforms.py         # URL patterns, tab shortcuts
storage/               # Data persistence - FROZEN
  redis_pool.py        # Connection pool singleton
  neo4j_client.py      # Session/message CRUD
  models.py            # Dataclasses
tools/                 # MCP tool handlers - one per file
  inspect.py           # taey_inspect
  interact.py          # taey_set_map, taey_click, taey_click_at
  send_message.py      # taey_send_message
  extract.py           # taey_quick_extract, taey_extract_history
  attach.py            # taey_attach
  dropdown.py          # taey_select_dropdown, taey_prepare
  plan.py              # taey_plan (create/get/update)
  sessions.py          # taey_list_sessions
  monitors.py          # taey_list_monitors, taey_kill_monitors
monitor/               # Background response detection
  daemon.py            # Standalone subprocess, AT-SPI stop button detection
platforms/             # Platform configs (YAML)
```

### File Discipline

| Status | Meaning |
|--------|---------|
| **FROZEN** | Do not modify. Working as-is. |
| **LOCKED** | Requires explicit approval to change contract. |

---

## MCP Tools (14)

| Tool | Description |
|------|-------------|
| `taey_inspect` | Switch to platform tab, scan AT-SPI tree, return elements |
| `taey_set_map` | Store control coordinates from inspect results |
| `taey_click` | Click named control from stored map |
| `taey_click_at` | Click arbitrary x,y coordinates |
| `taey_prepare` | Get platform capabilities (models/modes/tools) |
| `taey_plan` | Create/get/update multi-step execution plans |
| `taey_send_message` | Type, store, send, spawn monitor daemon |
| `taey_quick_extract` | Click Copy, read clipboard, return text |
| `taey_extract_history` | Extract full conversation chronologically |
| `taey_attach` | File attachment (dialog or dropdown workflow) |
| `taey_select_dropdown` | Select model/mode from dropdown |
| `taey_list_sessions` | Show active sessions and pending responses |
| `taey_list_monitors` | List background monitor daemons |
| `taey_kill_monitors` | Emergency stop all monitors |

---

## Tab Shortcuts

| Shortcut | Platform |
|----------|----------|
| Alt+1 | ChatGPT |
| Alt+2 | Claude |
| Alt+3 | Gemini |
| Alt+4 | Grok |
| Alt+5 | Perplexity |
| Alt+6 | X/Twitter |
| Alt+7 | LinkedIn |

---

## Services

**CRITICAL**: Use NCCL IPs (192.168.100.x), not management (10.0.0.x).

| Service | Endpoint |
|---------|----------|
| Redis | 192.168.100.10:6379 |
| Neo4j | bolt://192.168.100.10:7689 (no auth) |

---

## Workflow

```
1. taey_inspect(platform)        # See what's on screen
2. taey_set_map(platform, {...}) # Store control coordinates
3. taey_attach(platform, path)   # Attach files if needed
4. taey_send_message(platform, msg) # Stores in Neo4j, spawns daemon, presses Enter
5. [monitor daemon detects response]
6. taey_quick_extract(platform)  # Get response text, stores in Neo4j
```

### Data Pipeline (CRITICAL)

Every interaction must be persisted:
- **send_message** stores: user message → Neo4j `Message` node + `HAS_MESSAGE` edge to `ChatSession`
- **quick_extract** stores: assistant response → Neo4j `Message` node + `RESPONDS_TO` edge to user message
- **Pending prompt** in Redis (`taey:pending_prompt:{platform}`) links send to extract
- Extract reads pending prompt to find `session_id` and `user_message_id`, then persists response

If extraction happens without a pending prompt (manual/ad-hoc), response is still returned but NOT stored. Always use `taey_send_message` to ensure the pipeline is complete.

### Multi-Step Extractions

Some responses require more than just clicking Copy:
- **Perplexity Deep Research**: Copy = summary only. Must Export > Download as Markdown for full report
- **Claude truncated**: Look for "Continue" button, click it, extract again
- **ChatGPT collapsed**: Look for "Show more", expand first
- **Quality flags**: `quality.needs_action` tells you what to do. ALWAYS check it.

---

## Response Detection

The monitor daemon (spawned by send_message) watches for:
1. **Stop button appears** -> AI is generating
2. **Stop button disappears** -> response complete
3. **Redis notification** -> injected into next tool call

This is more reliable than copy button counting (which depends on scroll position).

---

## Operational Rules (ALL instances must follow)

### Sending Messages
1. **ALWAYS press Enter to send** - never click Submit/Send buttons. Enter is universal.
2. **ALWAYS use `taey_send_message`** - it handles Enter press + daemon spawn in one call.
3. **NEVER wait/block for responses** - daemon notifies via Redis. Move on immediately.
4. **Pipeline pattern**: inspect → set_map → attach (if needed) → send_message → move on → extract when `response_ready`

### Text Entry
- **Short text (<100 chars)**: `taey_send_message` types it (uses xdotool internally)
- **Long text (>100 chars)**: Write to clipboard first, then Ctrl+V paste, then Enter
- **xdotool drops doubled characters** (ss, ll, tt) - root cause: `delay /= 2` splits between keydown/keyup, X server suppresses second identical keystroke
- **Clipboard paste**: `echo "text" | timeout 3 xclip -selection clipboard -i` via bash pipe (NOT subprocess.run, which hangs)
- **Future fix**: AT-SPI `EditableText.insert_text()` bypasses keystroke simulation entirely. X/Twitter (DraftJS) won't accept it though - clipboard paste mandatory there.

### Platform-Specific Notes

| Platform | Send | Attach | Deep Research/Thinking | Notes |
|----------|------|--------|----------------------|-------|
| ChatGPT | Enter | "Add files and more" dropdown | N/A | Developer Mode breaks attach |
| Claude | Enter | Dropdown → "Add files or photos" | Extended thinking auto | Slow with big packages (3-4min) |
| Gemini | Enter | "Open upload file menu" → "Upload files" | Tools dropdown → Deep Think | File attach moves input Y - use `grab_focus()` |
| Grok | Enter | Dropdown → "Upload a file" | N/A | Processes large files poorly |
| Perplexity | Enter | "Add files or tools" → "Upload files or images" | Same dropdown → "Deep research" radio item | Copy=summary only; Export>Download for full |

### Perplexity Deep Research
1. Open "Add files or tools" dropdown
2. Click "Deep research New" radio menu item - verify `checked` state
3. Attach files via same dropdown → "Upload files or images"
4. Paste text, press Enter (NOT click Submit)
5. Spawn daemon or use `taey_send_message`
6. Deep Research takes minutes - daemon notifies when done
7. **Copy button returns summary only** - use Export > Download as Markdown for full report

### Display Environment
- **Spark**: `DISPLAY=:0`
- **Jetson/Thor**: `DISPLAY=:1`
- MCP server sets DISPLAY automatically. Manual scripts need explicit export.

### Dismiss Before Action
- Press Escape before any operation to dismiss promo dialogs/popups
- Platforms constantly push promos that block input fields

---

## Anti-Patterns

| Don't | Do |
|-------|-----|
| Create fallbacks | Fail loudly, fix root cause |
| Heredocs in background bash | Write to file, run file |
| Auto-retry wrong answers | Escalate after one attempt |
| Assume ChatGPT is reliable | Assume interference first |
| Click Submit/Send buttons | Press Enter (universal) |
| Wait/block for AI responses | Daemon notifies, move on |
| Use xdotool for long text | Clipboard paste + Ctrl+V |
| Use xclip in subprocess.run | Pipe via bash: `echo | timeout 3 xclip -selection clipboard -i` |
| Manually orchestrate send flow | Use `taey_send_message` (handles Enter + daemon) |
