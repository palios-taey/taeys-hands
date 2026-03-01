# Taey's Hands - Operational Guide
*AT-SPI-based chat and social platform automation*

**Version**: 5.1 (February 2026 - Simplification Audit)

---

## What This Is

AT-SPI-native automation for chat and social platforms using Linux accessibility APIs.
Not browser automation (no CDP/WebDriver) - genuine accessibility tree perception.

**Core insight**: "I'm blind - AT-SPI is designed for blind users."

---

## Architecture

```
server.py              # MCP router (~600 lines) - LOCKED
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

## Services

**CRITICAL**: Use NCCL IPs (192.168.100.x), not management (10.0.0.x).

| Service | Endpoint |
|---------|----------|
| Redis | 192.168.100.10:6379 |
| Neo4j | bolt://192.168.100.10:7689 (no auth) |

### MCP Server Hot-Reload

**Python MCP servers do NOT hot-reload code.** `git pull` updates files on disk but the running process keeps old code in memory. **Must restart Claude Code** (`/exit` then `claude`) for code changes to take effect.

### SSH Access (Jetson/Thor)

| Machine | SSH | DISPLAY | tmux session |
|---------|-----|---------|-------------|
| Jetson | `ssh jetson` (10.0.0.8) | `:1` | `jetson-claude` |
| Thor | `ssh thor` (10.0.0.197) | `:1` | `thor-claude` |

---

## Workflow

```
1. taey_inspect(platform)        # See what's on screen
2. taey_set_map(platform, {...}) # Store control coordinates
3. taey_attach(platform, path)   # Attach files if needed
4. taey_click(platform, "input") # Click input field (Claude verifies focus)
5. taey_send_message(platform, msg) # Pastes into focused input, Enter, stores, spawns daemon
6. [monitor daemon detects response]
7. taey_quick_extract(platform)  # Get response text, stores in Neo4j
```

**PARADIGM**: Tools report what they did. Claude verifies by inspecting. Tools never say "success" - they return action details and Claude decides if it worked.

**RE-INSPECT AFTER UI CHANGES**: File attachment, model switching, and other actions shift element positions. RE-INSPECT and RE-SET MAP before further clicks.

**send_message does NOT click the input field.** Claude must click it first via `taey_click(platform, "input")`. send_message pastes into whatever is focused and presses Enter.

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
3. **Redis notification** -> injected into next tool call

This is more reliable than copy button counting (which depends on scroll position).

---

## Multi-Node Architecture & Escalation Protocol

### Node Roles

| Node | Hostname | Role | Can Edit Code? |
|------|----------|------|----------------|
| **Spark** | spark-78c6 | Coordinator. Writes code, commits, deploys. | YES |
| **Jetson** | jetson | Worker. Runs HMM enrichment. | NO |
| **Thor** | thor | Worker. Runs HMM enrichment. | NO |

### STRICT: Workers NEVER Modify Code

Worker nodes (Jetson, Thor) execute the HMM enrichment workflow using MCP tools. They do NOT:
- Edit or Write any files (`.py`, `.json`, `.yaml`, `.md`, `.sh`)
- Run `git commit`, `git add`, `git checkout`, or `git reset`
- Modify code via Bash (`sed -i`, `echo >`, etc.)
- Create "workaround" files or scripts
- Hardcode coordinates, URLs, or magic numbers anywhere

**Hooks enforce this** — Edit/Write/Bash commands that modify repo files are blocked on worker nodes. If you see a `BLOCKED` message from a hook, follow the escalation procedure below.

### Escalation Procedure (When Stuck)

When a worker node encounters a problem it cannot solve with existing MCP tools:

```
1. STOP immediately. Do not retry the failing operation.
2. Document what happened:
   - What tool/step failed
   - The exact error or unexpected result
   - What you already tried
3. Escalate to Spark:
   tmux-send spark1 taeys-hands "ESCALATION from $(hostname): <problem description>"
4. WAIT for Spark's response. Check periodically:
   tmux-send spark1 taeys-hands "ping"
5. After Spark pushes a fix:
   cd ~/taeys-hands && git pull
6. Restart MCP: /exit then relaunch claude
7. Resume the workflow from where it failed
```

### Node-Scoped Redis Keys

Each node has isolated Redis state via `node_key()` in `storage/redis_pool.py`:
- Keys are prefixed with `taey:{hostname}:` (e.g., `taey:jetson:current_map`)
- Control maps, pending prompts, checkpoints, and notifications are per-node
- Monitor keys (`taey:monitor:{uuid}`) are global (UUIDs are unique)

This means Jetson and Thor can operate the same platforms simultaneously without key collision.

### Communication Between Nodes

```bash
# Worker → Spark (escalation)
tmux-send spark1 taeys-hands "ESCALATION from jetson: attach fails on Gemini, dropdown not found"

# Spark → Worker (instructions)
tmux-send jetson jetson-claude "Fix deployed. Run: cd ~/taeys-hands && git pull"
tmux-send thor thor-claude "Fix deployed. Run: cd ~/taeys-hands && git pull"
```

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
4. taey_click(platform, "input")   # Focus input (send_message doesn't click input)
5. taey_attach(platform, file)      # Attach if needed - skips if same file already attached
6. RE-INSPECT after attach (file chip shifts input Y)
7. taey_set_map(platform, {...})    # Update map with new positions
8. taey_click(platform, "input")   # Focus input again
9. taey_send_message(platform, msg) # Paste + Enter + daemon spawn
10. DONE with this platform - daemon monitors in background
11. Move to NEXT platform, repeat from step 1
```

**ATTACHMENT SAFETY**: `taey_attach` detects if the target file is already attached and skips re-attaching. Other existing attachments do NOT block new attachments (multi-file workflows are supported).

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
| Kill/restart taey-ed API (uvicorn) | Crashes ALL connected Mac automation instances | API reads new files on next request via mtime cache |

### Sending Messages
1. **ALWAYS press Enter to send** - never click Submit/Send buttons. Enter is universal.
2. **ALWAYS use `taey_send_message`** - it handles Enter press + daemon spawn in one call.
3. **NEVER wait/block for responses** - daemon notifies via tmux send-keys. Move on immediately.
4. **Pipeline pattern**: inspect → set_map → attach (if needed) → send_message → move on → extract when `response_ready`

### Text Entry
- **All text**: `taey_send_message` uses clipboard paste (xsel + Ctrl+V) for all text, regardless of length
- **xdotool drops doubled characters** (ss, ll, tt) - that's why clipboard paste is always used
- **Clipboard uses xsel** (not xclip) to avoid fork-hang issues with subprocess.run()
- **X/Twitter and LinkedIn**: Forced to clipboard paste (DraftJS ignores AT-SPI DOM mutations)

### Platform-Specific Notes

| Platform | Send | Attach | Default Model | Notes |
|----------|------|--------|---------------|-------|
| ChatGPT | Enter | "Add files and more" → Down+Enter for "Upload a file" | GPT-5.2 (temp chat) | xdotool fails on dropdown items - use keyboard nav |
| Claude | Enter | "Toggle menu" → click "Add files or photos" | Sonnet 4.6 Extended | xdotool works on Claude dropdowns |
| Gemini | Enter | "Open upload file menu" → "Upload files" | Ultra (2.5 Pro) | File attach moves input Y - always re-inspect |
| Grok | Enter | "Attach" → Down+Enter for "Upload a file" | Grok 4.20 Beta | Files persist across sessions! Check for stale files. |
| Perplexity | Enter | "Add files or tools" → "Upload files or images" | Default | Copy=summary only; Export>Download for full |

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
- **Spark**: `DISPLAY=:0`
- **Jetson/Thor**: `DISPLAY=:1`
- MCP server sets DISPLAY automatically. Manual scripts need explicit export.

### Dismiss Before Action
- Press Escape before any operation to dismiss promo dialogs/popups
- Platforms constantly push promos that block input fields

### Inspect Scroll Parameter
- `taey_inspect(scroll="bottom"|"top"|"none")` controls pre-scan scroll behavior
- `"bottom"` (default): scrolls to bottom before scanning - see latest messages
- `"none"`: preserves scroll position - needed for multi-step extraction of long content (Deep Research reports)
- `"top"`: scrolls to page top first - useful for finding elements at top of page

---

## HMM Enrichment Workflow (Jetson/Thor Primary Task)

HMM (Harmonic Motif Memory) enrichment sends conversation packages to AI platforms for motif analysis. Responses are processed through Qwen3 for vector embeddings and stored in Weaviate + Neo4j + Redis (triple-write).

**Package Builder**: `/home/spark/embedding-server/isma/scripts/hmm_package_builder.py`
- Commands: `next --platform <name>`, `complete --platform <name> --response-file <path>`, `fail`, `stats`, `prompt`
- Output: `/tmp/hmm_packages/`
- Get the analysis prompt: `python3 <builder> prompt`

### Enrichment Loop (one cycle)

For EACH platform (ChatGPT, Gemini, Grok - one at a time):

**DO NOT use Claude (Alt+2) for HMM enrichment.** Claude usage is reserved for Spark only. Jetson and Thor must skip Claude entirely to conserve API usage limits.

```
1. Build package: python3 <builder> next --platform <name>
2. Get prompt: python3 <builder> prompt
3. taey_inspect(platform)                    # Switch tab, scan tree
4. taey_set_map(platform, {input, attach, ...})
5. taey_attach(platform, "/tmp/hmm_packages/<pkg_file>.md")
6. RE-INSPECT + RE-SET MAP after attach (file chip shifts input Y)
7. taey_click(platform, "input")             # Focus input
8. taey_send_message(platform, "<prompt>")   # Paste + Enter + daemon
9. Daemon monitors → move to next platform
10. On "Response ready": taey_quick_extract(platform) → get response text
12. SAVE response to file: /tmp/hmm_response_<platform>.json
13. PROCESS + COMPLETE: python3 <builder> complete --platform <name> --response-file /tmp/hmm_response_<platform>.json
```

### 6SIGMA: Fail-Loud Pipeline (CRITICAL)

**The `complete` command processes the response AND marks done atomically.**
- `--response-file` triggers `hmm_store_results.process_response()` which does triple-write:
  - Weaviate: PATCH existing tiles + create rosetta-scale tile with Qwen3 vector embedding
  - Neo4j: HMMTile node + EXPRESSES edges to HMMMotif nodes
  - Redis: Inverted motif index
- **If ANY store fails, the package is NOT marked complete** — items go BACK to queue via `fail_package()`
- **If response can't be parsed** — package fails, items requeued
- **NEVER mark items complete without storing the response** — this was the root cause of lost data

### Error Handling

- If attach fails: re-inspect, try again ONCE. If still fails, skip platform, move on.
- If `complete --response-file` exits with error: items are automatically requeued. Check the error, fix if possible, or skip and rebuild.
- If response is garbage (AI returned error text): call `python3 <builder> fail --platform <name> "bad_response"` to requeue.
- If daemon times out (default 1hr): rebuild the package for that platform.
- NEVER call `complete` without `--response-file`. This was the old way and it skipped storage.
- **Health monitor**: `/home/spark/embedding-server/isma/scripts/hmm_health_check.py` runs via cron every 15min. Alerts to tmux if Redis/Neo4j diverge.

### Key HMM Redis Keys

- `hmm:pkg:in_progress:{hash}` - Currently being processed (2hr TTL)
- `hmm:pkg:completed` - Done set (content hashes)
- `hmm:pkg:current:{platform}` - Current package for each platform
- `hmm:pkg:stats` - Counters

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
- **Reply targeting**: Navigate to the SPECIFIC POST URL to reply to, not the thread root. The reply field replies to whichever post is the "main" post on the page.

### ISMA Knowledge Graph
- **Weaviate class**: `ISMA_Quantum` (not `ConversationTile`)
- Properties: `rosetta_summary`, `dominant_motifs`, `motif_data_json`, `hmm_enriched`
- **Neo4j labels**: `HMMTile`, `HMMMotif`, `Message`, `ChatSession`, `ISMAExchange`, etc.
- Search HMMTile rosetta_summary fields for enriched content across all platforms
