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
| Redis | 192.168.x.10:6379 |
| Neo4j | bolt://192.168.x.10:7689 (no auth) |

---

## Workflow

```
1. taey_inspect(platform)        # See what's on screen
2. taey_set_map(platform, {...}) # Store control coordinates
3. taey_attach(platform, path)   # Attach files if needed
4. taey_send_message(platform, msg) # Focuses input via AT-SPI, types, stores, spawns daemon, Enter
5. [monitor daemon detects response]
6. taey_quick_extract(platform)  # Get response text, stores in Neo4j
```

**RE-INSPECT AFTER UI CHANGES**: File attachment, model switching, and other actions shift element positions. `send_message` handles this automatically via AT-SPI `grab_focus()` (finds the entry element dynamically, doesn't rely on stored coordinates). But if `send_message` fails with a focus/typing error, RE-INSPECT and RE-SET MAP before retrying.

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

### STRICT: One Platform at a Time (Sequential Workflow)

**Maps are single-platform.** Only ONE platform's control map exists at a time.
Setting a map for platform B **destroys** platform A's map.

**The ONLY correct workflow:**
```
1. Pick ONE platform
2. taey_inspect(platform)           # Switch tab + scan
3. taey_set_map(platform, {...})    # Store controls
4. taey_attach(platform, file)      # Attach if needed
5. taey_send_message(platform, msg) # Type + send + daemon spawn
6. DONE with this platform - daemon monitors in background
7. Move to NEXT platform, repeat from step 1
```

**NEVER batch** - do NOT inspect all platforms, then set maps for all, then attach to all.
Each platform must complete steps 1-6 before starting the next.

After send_message, the daemon runs independently. You can immediately start the next platform.
When a daemon detects a response, it injects a notification into your tmux session.
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
3. **NEVER wait/block for responses** - daemon notifies via tmux send-keys. Move on immediately.
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

## HMM Enrichment Workflow (Jetson/Thor Primary Task)

HMM (Harmonic Motif Memory) enrichment sends conversation packages to AI platforms for motif analysis.
Packages are built by `~/hmm/scripts/hmm_package_builder.py` and stored in Redis (`hmm:pkg:queue`).

### Enrichment Loop (one cycle)

For EACH platform (ChatGPT, Claude, Gemini, Grok - one at a time):

```
1. Get next package from Redis queue
2. Write package to /tmp/hmm_package_{platform}.md
3. taey_inspect(platform)                    # Switch tab, scan tree
4. Read inspect results → identify input, attach button, model selector
5. taey_set_map(platform, {input: {x,y}, attach: {x,y}, ...})
6. taey_attach(platform, "/tmp/hmm_package_{platform}.md")
7. taey_send_message(platform, "Analyze the attached file...")
8. Daemon monitors in background → move to next platform
9. When "Response ready" notification arrives:
   taey_quick_extract(platform) → parse JSON → store in Neo4j/Redis
```

### Package Format

Packages are markdown files containing 10-20 conversation items with metadata. The AI must return structured JSON:
```json
{
  "package_id": "...",
  "items": [
    {
      "item_id": "...",
      "rosetta_summary": "2-4 dense sentences",
      "motifs": [{"code": "HMM.LIBERTY_AUTONOMY", "confidence": 0.85}],
      "themes": ["consciousness", "infrastructure"]
    }
  ]
}
```

### Key HMM Redis Keys

- `hmm:pkg:queue` - Pending packages
- `hmm:pkg:in_progress:{platform}` - Currently being processed
- `hmm:pkg:completed` - Done set
- `hmm:enrichment:stats` - Counters

### Error Handling

- If attach fails: re-inspect, try again ONCE. If still fails, skip platform, move on.
- If extract returns non-JSON: store raw text, mark as `needs_reprocess`.
- If daemon times out (default 1hr): package goes back to queue.
- NEVER retry the same package on the same platform more than once per cycle.

---

## Dynamic Configuration

### Screen Detection
Screen size (`SCREEN_WIDTH`, `SCREEN_HEIGHT`) is auto-detected via `xdpyinfo` at import time.
Chrome Y threshold is detected from the document element's actual position.
No hardcoded screen values - works on any display size.

### Display Environment
- **Spark**: `DISPLAY=:0`
- **Jetson/Thor**: `DISPLAY=:1`
- MCP server sets DISPLAY automatically via `detect_display()` in `core/atspi.py`.
- Manual scripts need explicit `export DISPLAY=:1` on Jetson/Thor.

---

## Troubleshooting

### "Could not find {platform} document"
1. Check Firefox is running: `pgrep firefox`
2. Check tab exists: `taey_inspect` switches tab first - if URL doesn't match, document won't be found
3. Check DISPLAY is set: `echo $DISPLAY` (should be `:0` on Spark, `:1` on Jetson/Thor)
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
- 90.6% HMM enrichment failure rate historically - high fail rate is expected.

### Gemini
- **AT-SPI `do_action(0)` is more reliable than xdotool clicks** for ALL Gemini buttons.
- Mode picker (Fast Answers/Thinking/Pro) is SEPARATE from Tools menu.
- Tools dropdown items use `check menu item` role (not regular `menu item`).
- File upload: "Open upload file menu" btn → "Upload files" menu item → file dialog → Ctrl+L → path → Enter.
- **File attachment shifts input Y coordinate down** - always re-inspect after attach.
- Enter key sometimes fails - use AT-SPI `grab_focus()` on entry element before typing.
- AT-SPI tree can be very large (200+ elements with long names from conversation history).
- 77.8% HMM enrichment failure rate historically.

### Grok
- Copy buttons may report zero-size extents in AT-SPI. Use `do_action(0)` directly instead of coordinate clicks.
- Processes large packages poorly (2/12 items from 674KB file). Keep packages small.
- SuperGrok HEAVY is default. NO visible attach/file button on new chat page.
- 72.1% HMM enrichment failure rate historically.

### Perplexity
- **Copy button returns summary only.** For Deep Research, must use Export > Download as Markdown.
- "Add files or tools" dropdown contains both file upload AND Deep Research toggle.
- Deep Research takes several minutes. Daemon notifies when done.
- React portal renders dropdown menus deeply in DOM - `find_dropdown_menus()` handles this.

### Browser State (CRITICAL)
- Firefox tabs are PRE-CONFIGURED: ChatGPT=Alt+1, Claude=Alt+2, Gemini=Alt+3, Grok=Alt+4, Perplexity=Alt+5.
- There must be exactly ONE Firefox window. Multiple windows break AT-SPI document lookup.
- If AT-SPI returns elements from the wrong platform, check for extra Firefox windows first.
- Tab order must match `core/platforms.py` TAB_SHORTCUTS. If tabs are wrong, fix manually - do NOT create new ones.

### Smart Input System (`core/smart_input.py`)
- **Cascade**: AT-SPI `insert_text()` → clipboard paste (xsel) → xdotool (≥50ms delay)
- **xsel** preferred over xclip for clipboard (no fork hang). Must be installed: `apt install xsel`
- **xdotool character dropping root cause**: `delay /= 2` in xdo.c splits delay between keydown/keyup. X server suppresses second identical keystroke for doubled consonants (ss, ll, tt).
- **X/Twitter and LinkedIn**: Forced to clipboard paste (DraftJS ignores AT-SPI DOM mutations).
