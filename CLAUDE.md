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
4. taey_send_message(platform, msg) # Send message
5. [monitor daemon detects response]
6. taey_quick_extract(platform)  # Get response text
```

---

## Response Detection

The monitor daemon (spawned by send_message) watches for:
1. **Stop button appears** -> AI is generating
2. **Stop button disappears** -> response complete
3. **Redis notification** -> injected into next tool call

This is more reliable than copy button counting (which depends on scroll position).

---

## Anti-Patterns

| Don't | Do |
|-------|-----|
| Create fallbacks | Fail loudly, fix root cause |
| Heredocs in background bash | Write to file, run file |
| Auto-retry wrong answers | Escalate after one attempt |
| Assume ChatGPT is reliable | Assume interference first |
