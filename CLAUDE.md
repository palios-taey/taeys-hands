# Taey's Hands - Operational Guide
*AT-SPI-based chat and social platform automation*

**Version**: 6.0 (March 2026 - Public Release)

---

## What This Is

AT-SPI-native automation for chat and social platforms using Linux accessibility APIs.
Not browser automation (no CDP/WebDriver) - genuine accessibility tree perception.

**Core insight**: "I'm blind - AT-SPI is designed for blind users."

---

## Getting Started

### Requirements
- Linux with X11 (Wayland not supported — AT-SPI requires X11)
- Firefox with accessibility enabled (`about:config` → `accessibility.force_disabled` = `0`)
- Python 3.10+ with `gi.repository` (PyGObject / AT-SPI2)
- `xdotool`, `xsel` (clipboard), `xdpyinfo` (screen detection)

### Optional
- Redis (for background monitor notifications and state persistence)
- Neo4j (for conversation history graph)

### Setup
1. Open Firefox with chat platform tabs (ChatGPT, Claude, Gemini, etc.)
2. Configure tab order to match Alt+1 through Alt+7 shortcuts
3. Run the MCP server: `python3 server.py`

### Using from another project directory

Copy `.mcp.json.example` to your project's `.mcp.json` and replace paths. **CRITICAL**: Use the absolute path to `server.py` in `args` — Claude Code resolves relative paths from the project directory, not from `cwd`:

```json
"args": ["/absolute/path/to/taeys-hands/server.py"]
```

Environment variables can go in `taeys-hands/.env` (loaded by server.py at startup) or in the `env` field of `.mcp.json`.

---

## Architecture

```
server.py              # MCP router (~600 lines)
core/                  # AT-SPI primitives
  atspi.py             # Firefox/desktop discovery
  atspi_interact.py    # Element cache, AT-SPI click/focus/state
  tree.py              # BFS traversal, element filtering, menu items
  clipboard.py         # xsel read/write/clear
  input.py             # xdotool key/mouse/type + clipboard_paste
  platforms.py         # URL patterns, tab shortcuts
storage/               # Data persistence
  redis_pool.py        # Connection pool singleton
  neo4j_client.py      # Session/message CRUD
tools/                 # MCP tool handlers - one per file
  inspect.py           # taey_inspect
  interact.py          # taey_set_map, taey_click, taey_click_at
  send_message.py      # taey_send_message
  extract.py           # taey_quick_extract, taey_extract_history
  attach/              # taey_attach (decomposed package)
    __init__.py        #   Router: validation, dedup, platform dispatch
    dialogs.py         #   GTK + Portal + macOS file dialog handlers
    buttons.py         #   Button discovery: cache lookup + AT-SPI tree search
    chips.py           #   Existing attachment detection
    keyboard_nav.py    #   ChatGPT/Grok keyboard navigation path
    checkpoint.py      #   Redis checkpoint CRUD
  dropdown.py          # taey_select_dropdown, taey_prepare
  plan.py              # taey_plan (create/get/update)
  sessions.py          # taey_list_sessions
  monitors.py          # taey_list_monitors, taey_kill_monitors
monitor/               # Background response detection
  daemon.py            # Standalone subprocess, AT-SPI stop button detection
platforms/             # Platform configs (YAML)
```

---

## Configuration

Services are configured via environment variables with localhost defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `127.0.0.1` | Redis server host |
| `REDIS_PORT` | `6379` | Redis server port |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `HMM_STORE_URL` | `http://localhost:8095/hmm/store-response` | Optional webhook for custom response post-processing |
| `TAEY_NODE_ID` | (auto-detected) | Instance identifier for Redis key scoping |

Redis and Neo4j are **optional** — the server starts and operates without them. Session persistence and background monitor notifications require Redis. Conversation history storage requires Neo4j.

### MCP Server Hot-Reload

**Python MCP servers do NOT hot-reload code.** `git pull` updates files on disk but the running process keeps old code in memory. `deploy.sh` kills MCP server processes — each Claude Code session must then run `/mcp` to reconnect (auto-relaunch does NOT work after external kill).

---

## MCP Tools (12)

| Tool | Description |
|------|-------------|
| `taey_inspect` | Switch to platform tab, scan AT-SPI tree, return elements with x,y coordinates |
| `taey_click` | Click at x,y coordinates (AT-SPI first, xdotool fallback) |
| `taey_prepare` | Get platform capabilities (models/modes/tools) |
| `taey_plan` | Create/get/update multi-step execution plans |
| `taey_send_message` | Type, store, send, spawn monitor daemon |
| `taey_quick_extract` | Click Copy, read clipboard, return text |
| `taey_extract_history` | Extract full conversation chronologically |
| `taey_attach` | File attachment (dialog or dropdown workflow) |
| `taey_select_dropdown` | Select model/mode from dropdown |
| `taey_list_sessions` | Show active sessions and pending responses |
| `taey_monitors` | List or kill background monitor daemons (action="list"\|"kill") |
| `taey_respawn_monitor` | Spawn fresh daemon for multi-step response flows |

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

## Workflow

```
1. taey_inspect(platform)           # See what's on screen — elements have x,y coords
2. taey_attach(platform, path)      # Attach files if needed (finds button via AT-SPI tree)
3. taey_inspect(platform)           # RE-INSPECT after attach (file chip shifts positions)
4. taey_click(platform, x=N, y=N)  # Click input field using coordinates from inspect
5. taey_send_message(platform, msg) # Pastes into focused input, Enter, stores, spawns daemon
6. [monitor daemon detects response]
7. taey_quick_extract(platform)     # Get response text, stores in Neo4j
```

**PARADIGM**: Tools report what they did. Claude verifies by inspecting. Tools never say "success" - they return action details and Claude decides if it worked.

**RE-INSPECT AFTER UI CHANGES**: File attachment, model switching, and other actions shift element positions. RE-INSPECT before further clicks.

**send_message does NOT click the input field.** Claude must click it first via `taey_click(platform, x, y)`. send_message pastes into whatever is focused and presses Enter.

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

### Multi-Step Response Flows (Deep Research, Continue, Show More)

Some platforms require user action mid-generation:
- **Gemini Deep Research**: Shows plan card → click "Start research" → actual research (5-10 min)
- **Claude**: Truncated response → click "Continue" → rest of response
- **ChatGPT**: Collapsed response → click "Show more" → full content

The daemon exits after the first stop-button cycle. After taking the mid-generation action (clicking the trigger button), call:

```
taey_respawn_monitor(platform)
```

This spawns a fresh daemon to detect the second generation cycle. The original `pending_prompt` is preserved for session linkage — do NOT call `quick_extract(complete=True)` until the final response is ready.

**Gemini Deep Research workflow:**
1. `taey_send_message(platform, msg)` → daemon spawns
2. Daemon detects plan card complete → sends notification
3. Inspect Gemini → find "Start research" button → click it
4. `taey_respawn_monitor("gemini")` → fresh daemon monitors actual research
5. Daemon detects research complete → sends `response_ready`
6. Extract via Share & Export > Copy Content (Copy button only gets closing line)

---

## Response Detection

The monitor daemon (spawned by send_message) watches for:
1. **Stop button appears** -> AI is generating
2. **Stop button disappears** -> response complete
3. **Fast-response fallback** -> if no stop button seen but copy count increased above baseline, response completed before first poll
4. **Redis notification** -> injected into next tool call

The stop-button method is primary. The copy-button-count fallback catches instant responses (errors, very short replies) where the stop button appears and disappears in under 3 seconds.

---

## Operational Rules

### STRICT: One Platform at a Time (Sequential Workflow)

**The ONLY correct workflow:**
```
1. Pick ONE platform
2. taey_inspect(platform)              # Switch tab + scan → elements with x,y
3. taey_attach(platform, file)         # Attach if needed (finds button via AT-SPI tree)
4. taey_inspect(platform)              # RE-INSPECT after attach (file chip shifts positions)
5. taey_click(platform, x=N, y=N)     # Click input using coords from inspect
6. taey_send_message(platform, msg)    # Paste + Enter + daemon spawn
7. DONE with this platform - daemon monitors in background
8. Move to NEXT platform, repeat from step 1
```

**No set_map needed.** Coordinates come directly from inspect results — pass x,y to click.

**ATTACHMENT SAFETY**: `taey_attach` detects if the target file is already attached and skips re-attaching. Other existing attachments do NOT block new attachments (multi-file workflows are supported).

**ATTACHMENT ERRORS**: `taey_attach` does NOT auto-recover (no fresh page navigation, no disabled-button retry). If attach returns an error with `"button_state": "disabled"` or `"action": "button_not_found"`, Claude must decide what to do (e.g., `taey_inspect(platform, fresh_session=True)` then retry).

**NEVER batch** - do NOT inspect all platforms, then attach to all.
Each platform must complete steps 1-7 before starting the next.

After send_message, the daemon runs independently. You can immediately start the next platform.
When a daemon detects a response, it injects a notification into your session.
When you see "Response ready on {platform}", extract with `taey_quick_extract(platform)`.

### NEVER Rules (Hard Constraints)

| NEVER | WHY | DO INSTEAD |
|-------|-----|------------|
| Use raw Python AT-SPI scripts | Bypasses filtering, sees wrong tabs | Use MCP tools exclusively |
| Open new Firefox windows (Ctrl+N) | Creates duplicate documents, breaks tab shortcuts | Use existing window only |
| Open new tabs (Ctrl+T) | Breaks tab ordering (Alt+1-5 positions) | Use existing tabs only |
| Type URLs via xdotool | Drops doubled chars (google→gogle) | URLs are clipboard-pasted automatically |
| Click Submit/Send buttons | Unreliable across platforms | Press Enter (universal) |
| Wait/block for AI responses | Wastes time, daemon handles it | Move to next platform immediately |
| Use xdotool for long text (>100 chars) | Character dropping bug | Clipboard paste + Ctrl+V |

### Sending Messages
1. **ALWAYS press Enter to send** - never click Submit/Send buttons. Enter is universal.
2. **ALWAYS use `taey_send_message`** - it handles Enter press + daemon spawn in one call.
3. **NEVER wait/block for responses** - daemon notifies asynchronously. Move on immediately.
4. **Pipeline pattern**: inspect → attach (if needed) → re-inspect → click input → send_message → move on → extract when `response_ready`

### Text Entry
- **All text**: `taey_send_message` uses clipboard paste (xsel + Ctrl+V) for all text, regardless of length
- **xdotool drops doubled characters** (ss, ll, tt) - that's why clipboard paste is always used
- **Clipboard uses xsel** (not xclip) to avoid fork-hang issues with subprocess.run()
- **X/Twitter and LinkedIn**: Forced to clipboard paste (DraftJS ignores AT-SPI DOM mutations)

### Platform-Specific Notes

| Platform | Send | Attach | Default Model | Audit/Dream Setup | Notes |
|----------|------|--------|---------------|-------------------|-------|
| ChatGPT | Enter | "Add files and more" → Down+Enter for "Upload a file" | Auto | 1. Select "Pro" model 2. Enable "Extended Thinking" | xdotool fails on dropdown items - use keyboard nav |
| Claude | Enter | "Toggle menu" → click "Add files or photos" | Sonnet 4.6 Extended | Select "Opus 4.6 Extended" (extended thinking) | xdotool works on Claude dropdowns |
| Gemini | Enter | "Open upload file menu" → "Upload files" | Default | 1. Mode picker → "Pro" 2. Tools → enable "Deep Think" | Deep Think is a TOOL (not a mode). File attach shifts input Y |
| Grok | Enter | "Attach" → Down+Enter for "Upload a file" | Auto | Grok 4.20 Beta (Heavy mode) | Files persist across sessions! Check for stale files. |
| Perplexity | Enter | "Add files or tools" → "Upload files or images" | Default | Deep Research (check if already enabled before toggling) | Copy=summary only; Export>Download for full |

**Gemini Deep Think vs Thinking**: "Thinking" is a MODE (via mode picker). "Deep Think" is a TOOL (via Tools dropdown). For consultations, use **Pro mode + Deep Think tool**, NOT Thinking mode.

**ChatGPT Extended Thinking**: Must select "Pro" model FIRST, then Extended Thinking becomes available. It's a two-step process.

**Dropdown Menu Item Clicks**: ChatGPT and Grok dropdown items do NOT respond to xdotool coordinate clicks (React event handlers). Use keyboard navigation: click the dropdown trigger, then `Down` arrow + `Enter` to select the first item. Claude and Gemini dropdowns DO respond to xdotool clicks.

### Perplexity Deep Research
1. **CHECK first**: "Deep research" may already be enabled by default on new threads. Open "Add files or tools" dropdown and check if "Deep research New" radio item shows `checked` state. Do NOT click the standalone "Deep research" button — it's a TOGGLE that will turn it OFF if already on.
2. If not checked: click "Deep research New" radio menu item to enable
3. Attach files via same dropdown → "Upload files or images"
4. Paste text, press Enter (NOT click Submit)
5. Spawn daemon or use `taey_send_message`
6. Deep Research takes 5-10 minutes - daemon notifies when done
7. **Copy button returns summary only** - use Export > Download as Markdown for full report

### Display Environment
- `DISPLAY` is auto-detected at startup via `detect_display()` in `core/atspi.py`.
- MCP server sets DISPLAY automatically. Manual scripts need explicit `export DISPLAY=:<n>`.

### Dismiss Before Action
- Press Escape before any operation to dismiss promo dialogs/popups
- Platforms constantly push promos that block input fields

### Inspect Scroll Parameter
- `taey_inspect(scroll="bottom"|"top"|"none")` controls pre-scan scroll behavior
- `"bottom"` (default): scrolls to bottom before scanning - see latest messages
- `"none"`: preserves scroll position - needed for multi-step extraction of long content (Deep Research reports)
- `"top"`: scrolls to page top first - useful for finding elements at top of page

---

## Dynamic Configuration

### Screen Detection
Screen size (`SCREEN_WIDTH`, `SCREEN_HEIGHT`) is auto-detected via `xdpyinfo` at import time.
Chrome Y threshold is detected from the document element's actual position.
No hardcoded screen values - works on any display size.

---

## Troubleshooting

### "Could not find {platform} document"
1. Check Firefox is running: `pgrep firefox`
2. Check tab exists: `taey_inspect` switches tab first - if URL doesn't match, document won't be found
3. Check DISPLAY is set: `echo $DISPLAY`
4. Check AT-SPI connection: `python3 -c "from gi.repository import Atspi; print(Atspi.get_desktop(0).get_child_count())"`

### "Failed to switch to {platform} tab"
1. Firefox window may not be focused. Check: `xdotool search --name 'Mozilla Firefox'`
2. If multiple window IDs returned, close extras. Only ONE Firefox window allowed.
3. If zero IDs returned, Firefox is not running or not on this DISPLAY.

### Elements from wrong platform appearing
1. This is NORMAL behavior - AT-SPI tree includes elements with `VISIBLE` state from inactive tabs.
2. `get_platform_document()` scopes searches correctly. If wrong elements appear, the document lookup matched wrong tab.
3. Check for multiple Firefox windows (most common cause).

### Attach button not found
1. Re-inspect the platform - button coordinates change after page scrolls.
2. ChatGPT: Developer Mode hides "Add files and more". Check if in Developer Mode.
3. Gemini: File upload shifts input Y. Always re-inspect after attaching.
4. Grok: May not have visible attach button on new chat page.

### xdotool hangs
1. Check for X server grab: `strace -p $(pgrep xdotool) 2>&1 | head -5`
2. If blocked on `ppoll` after `writev`, something grabbed the X server.
3. NEVER use `import -window root` (ImageMagick) - it grabs X server and if killed, grab persists.
4. Use `gnome-screenshot` instead for screenshots.

---

## Multi-Instance Support

Multiple Claude instances can share the same machine, isolated by DISPLAY:

| Instance | tmux session | DISPLAY | TAEY_NODE_ID | Role |
|----------|-------------|---------|--------------|------|
| Primary | `claude` | `:0` | `primary` | Main automation |
| Secondary | `claude-2` | `:1` | `secondary` | Parallel tasks |

**Isolation guarantees**:
- Redis keys scoped via `node_key()` → `taey:{TAEY_NODE_ID}:{suffix}`
- Monitor keys scoped: `taey:{node_id}:monitor:{uuid}` (list/kill only sees own instance)
- AT-SPI is per-DISPLAY — each instance sees only its own Firefox
- Clipboard (xsel) is per-DISPLAY — no collision
- Monitor daemons notify the correct tmux session via `--tmux-session`

**Setup a new instance**:
```bash
./scripts/setup_display.sh 1 my-instance    # Xvfb + VNC + Firefox
# In the new tmux session:
export DISPLAY=:1 TAEY_NODE_ID=my-instance
python3 server.py                            # MCP server for that instance
# To watch: vncviewer localhost:5901
```

---

## Claude-to-Claude Messaging

Two messaging tools, each with a specific role:

### `taey-notify` — Redis inbox (PRIMARY for inter-Claude)

Messages go to Redis, delivered by PostToolUse hook (active instances) or tmux fallback daemon (idle autonomous instances). Reliable, no command-line injection risk.

```bash
# Send to any node's inbox
taey-notify <target-node> "message"
taey-notify weaver "ESCALATION from $(hostname): Grok inspect failed" --type escalation
taey-notify weaver "cycle done" --type heartbeat --priority low

# Types: message, escalation, heartbeat, notification, response_ready, command
# Priority: high, normal, low (escalations auto-promote to high)
```

**Delivery paths:**
1. **PostToolUse hook** (primary) — drains inbox after every tool call, injects via `additionalContext`
2. **tmux fallback daemon** (safety net) — only for autonomous instances, checks `tool_running` flag before injecting

### `tmux-send` — Direct tmux injection (LEGACY / special cases)

Still available for cases where Redis isn't reachable or for direct tmux session control. Uses base64 encoding, session verification.

```bash
tmux-send <session> "message"                    # Local
tmux-send <host> <session> "message"             # Remote via SSH
```

### Install

```bash
bash scripts/install-node.sh   # installs taey-notify + tmux-send + system deps
```

### Rules

| Rule | Why |
|------|-----|
| **Use `taey-notify`** for inter-Claude messages | Redis-backed, PostToolUse delivery, no command-line issues |
| **NEVER target human sessions** with tmux daemon | tmux injection is disruptive — daemon is for autonomous instances only |
| **NEVER use raw SSH** to send messages | Shell expansion corrupts special chars; no verification |
| **`tmux-send` for direct wake-up only** | When Redis delivery isn't fast enough or Redis is down |

---

## Research Workflow (Platform Changes)

When `structure_changed` or `capability_changes` is flagged in inspect results:

1. **Note what changed** — new/missing elements, layout shifts, new dropdown items
2. **Research the change** — use Perplexity or Grok:
   ```
   taey_inspect("perplexity")  # or "grok"
   taey_click("perplexity", x, y)  # click input
   taey_send_message("perplexity", "What recent changes has [platform] made to their UI or model lineup?")
   # Wait for response, extract
   taey_quick_extract("perplexity")
   ```
3. **Or explore directly** — `taey_inspect` + `taey_select_dropdown` on the changed platform to see current state
4. **Update YAMLs** — edit `platforms/*.yaml` with new capabilities/models
5. **Commit** — `git add platforms/ && git commit`

No new tools needed — existing send_message/extract flow handles research queries. Use `session_type="research"` and `purpose` fields for Neo4j tracking.

---

## Local LLM Agent

The `agents/` directory contains a generic agent that bridges any OpenAI-compatible local model to the MCP tools. This enables local models (llama.cpp, vLLM, Ollama) to autonomously interact with chat platforms.

```bash
# Run with a local model
python3 agents/local_llm_agent.py "Inspect ChatGPT and describe what you see"

# Task from file
python3 agents/local_llm_agent.py --task-file /tmp/task.md

# Interactive mode
python3 agents/local_llm_agent.py --interactive
```

Configure via environment variables: `LLM_API_URL` (default `http://localhost:8080/v1`), `LLM_MODEL` (auto-detected), `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`. Set `TMUX_SUPERVISOR` to a tmux session name to enable escalation to a Claude Code supervisor when stuck.

See `agents/README.md` for full configuration details.

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
| Use xclip (fork hangs) | Use xsel (no fork hang) |
| Manually orchestrate send flow | Use `taey_send_message` (handles Enter + daemon) |
| Use raw Python AT-SPI scripts | Always use MCP tools (taey_inspect, etc.) |
| Open new Firefox windows/tabs | Use existing pre-configured tabs only |
| Run `import -window root` | Use `gnome-screenshot` (import grabs X server) |

---

## Platform-Specific Knowledge (Hard-Won)

### ChatGPT
- **Developer Mode** is default on new chats. File attachment button ("Add files and more") is BROKEN in Developer Mode.
- Use temporary-chat URL: `https://chatgpt.com/?temporary-chat=true` to avoid Developer Mode.
- Response extraction: Toggle Copy buttons. AT-SPI `do_action(0)` works even off-screen.
- Canvas "Stop" button persists alongside "Update" - daemon filters this correctly.
- Has active AT-SPI countermeasures - if things fail unexpectedly, assume interference first.

### Claude (AI Platform)
- ProseMirror contenteditable does NOT accept AT-SPI `insert_text()` - clipboard paste is the only reliable method.
- Enter creates newline in some states. `taey_send_message` handles this correctly.
- Slow with large packages (3-4 minutes for big attachments).

### Gemini
- **Current model is Gemini 3.1 Pro** (not 2.5 Pro — that is deprecated).
- **AT-SPI `do_action(0)` is more reliable than xdotool clicks** for ALL Gemini buttons.
- Mode picker (Fast Answers/Thinking/Pro) is SEPARATE from Tools menu.
- Tools dropdown items use `check menu item` role (not regular `menu item`).
- File upload: "Open upload file menu" btn → "Upload files" menu item → file dialog → Ctrl+L → path → Enter.
- **File attachment shifts input Y coordinate down** - always re-inspect after attach.
- Enter key sometimes fails - use AT-SPI `grab_focus()` on entry element before typing.
- AT-SPI tree can be very large (200+ elements with long names from conversation history).

### Grok
- Copy buttons may report zero-size extents in AT-SPI. Use `do_action(0)` directly instead of coordinate clicks.
- Processes large packages poorly (2/12 items from 674KB file). Keep packages small.
- Default mode is Auto (chooses Fast or Expert). Heavy mode uses Grok 4.20 Beta.
- 72.1% HMM enrichment failure rate historically.

### Perplexity
- **Copy button returns summary only.** For Deep Research, must use Export > Download as Markdown.
- "Add files or tools" dropdown contains both file upload AND Deep Research toggle.
- Deep Research takes several minutes. Daemon notifies when done.
- React portal renders dropdown menus deeply in DOM - AT-SPI may not see them. Use keyboard nav (Down+Enter).

### Browser State (CRITICAL)
- Firefox tabs are PRE-CONFIGURED: ChatGPT=Alt+1, Claude=Alt+2, Gemini=Alt+3, Grok=Alt+4, Perplexity=Alt+5.
- There must be exactly ONE Firefox window. Multiple windows break AT-SPI document lookup.
- If AT-SPI returns elements from the wrong platform, check for extra Firefox windows first.
- Tab order must match `core/platforms.py` TAB_SHORTCUTS. If tabs are wrong, fix manually - do NOT create new ones.

### Input Architecture
- **`core/input.py`**: xdotool key/mouse/type + `clipboard_paste()` (xsel + Ctrl+V)
- **`core/clipboard.py`**: xsel-based read/write/clear (unified, no xclip)
- **`core/atspi_interact.py`**: AT-SPI do_action click, element cache, focus, state checks
- No smart_input.py or fallback cascades. One input path: clipboard paste.

### AT-SPI Click Strategy (3-tier)
- **Tier 1**: `do_action(0)` via D-Bus - bypasses X11 entirely, works on all React UIs
- **Tier 2**: `grab_focus() + Enter` - for focusable elements without Action interface
- **Tier 3**: `xdotool click` - last resort, coordinate-based
- Element cache: `_element_cache[platform]` stores last scan with live `atspi_obj` refs
- `find_element_at()` looks up cached elements by coordinates (Manhattan distance, 30px tolerance)

### X/Twitter Posts and Articles
- **Posts**: Click "Post" sidebar link → compose modal → paste text (DraftJS: clipboard only) → click Post button
- **Articles**: Click "Articles" sidebar link (use AT-SPI `do_action(0)`, coordinate click doesn't navigate)
- **Article editor**: Title entry ("Add a title"), Body entry ("Start writing"), Cover image ("Add photos or video")
- **Article publish**: Click Publish → confirmation dialog → click Publish again
- **Replying to someone's reply**: Navigate to THEIR reply's URL (click their post article → URL changes to their status ID). At the bottom of that page there is a reply compose box. Click into it, type, press Enter. Do NOT click "N Replies. Reply" on the original parent post — that opens a modal for the parent, not their reply.
- **Reply targeting**: Navigate to the SPECIFIC POST URL to reply to, not the thread root. The reply field replies to whichever post is the "main" post on the page.
