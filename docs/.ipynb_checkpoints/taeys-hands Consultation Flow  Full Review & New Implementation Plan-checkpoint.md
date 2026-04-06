# taeys-hands Consultation Flow: Full Review & New Implementation Plan

## Executive Summary

This report documents a full review of the `palios-taey/taeys-hands` repository's Consultation workflow and specifies a new, completely isolated per-platform implementation on a fresh branch. The root cause of the "fix one, break another" pattern is that every platform shares execution code paths in `tools/attach.py`, `core/mode_select.py`, `tools/extract.py`, and `tools/plan.py`, with hardcoded platform if/else logic scattered throughout. The solution is a new `consultation/` package where each AI platform gets its own executor class with **zero shared runtime logic** — only the YAML loader and Neo4j/Redis storage clients are shared.

***

## Current Architecture: What Exists

### Platform YAMLs (✅ solid foundation)

All five consultation platforms have well-defined YAMLs in `platforms/`. Each YAML correctly defines:
- `element_map`: exact AT-SPI name/role/states specs for every interactive element
- `element_filter.exclude`: elements to skip during traversal (sidebar history, logos, decorative items)
- `fence_after`: tree traversal stops at this node (cuts off sidebar history links)
- `validation`: AT-SPI indicators to verify each action actually took effect
- `click_strategy`: `atspi_first` (Gemini) or `xdotool_first` (all others)
- `attach_method`: `atspi_menu` (Claude, Gemini) or `keyboard_nav` (ChatGPT, Grok, Perplexity)
- `consultation_defaults`: default model/mode/attach/extract method per platform
- `mode_guidance`: how to select each mode (step sequences for multi-step like ChatGPT Pro+Extended)
- `stop_patterns`: exact text patterns for the stop button per platform

### Current Tool Chain (⚠️ shared, fragile)

The current flow uses these tools in sequence:

| Tool | File | Purpose |
|------|------|---------|
| `taey_plan` (create) | `tools/plan.py` | Build plan, prepend identity files, store in Redis |
| `taey_plan` (audit) | `tools/plan.py` | Scan AT-SPI tree, verify model/mode/attachment |
| `taey_select_dropdown` | `core/mode_select.py` | Click trigger → menu items → match → click → verify |
| `taey_attach` | `tools/attach.py` | Click attach trigger → dropdown/dialog → chip verify |
| `taey_send_message` | `tools/send.py` | Paste, Enter, URL capture, Neo4j store, monitor register |
| `taey_quick_extract` | `tools/extract.py` | Click copy button, read clipboard, store |

### The Root Cause of Cross-Platform Breakage

**1. `_match_element()` is duplicated in at least 3 files.** Each copy has slightly different fallback behavior. When one is updated for a new element pattern, the others drift.

**2. `core/mode_select.py::_determine_trigger_key()`** maps `how` text to element_map keys using string matching (`if 'model selector' in how_lower`). Adding a new platform or renaming a YAML key breaks other platforms that happen to share the same `how` text.

**3. `tools/attach.py::handle_attach()`** dispatches by `attach_method` but then falls through to shared dropdown scanning logic. Perplexity's special case (`if platform == 'perplexity'`) is inside `_click_upload_item()`. Adding a Grok fix changes code that Claude also runs.

**4. `tools/extract.py`** contains `_select_chatgpt_last_assistant_copy_button()` — a ChatGPT-specific function — but it also imports and calls Gemini-specific `_try_gemini_deep_research_extract()`. These are mixed into a single module that every platform calls.

**5. `tools/plan.py::_read_current_model_from_tree()`** has explicit `if platform == 'chatgpt'` and `if platform in _UNVERIFIABLE_MODEL_PLATFORMS` branches. Adding a new platform requires modifying this shared function.

***

## Per-Platform Element Maps (Complete Reference)

These are the exact AT-SPI elements as verified from each YAML. This section is the authoritative reference for the new implementation.

### ChatGPT

| Step | Element Key | Name Match | Role |
|------|-------------|-----------|------|
| Model select trigger | `model_selector` | `name_contains: "Model selector"` | push button |
| Model: Pro | `model_pro` | `name: "Pro Research-grade intelligence"` | push button |
| Model: Thinking | `model_thinking` | `name: "Thinking For complex questions"` | push button |
| Model: Auto | `model_auto` | `name: "Auto Decides how long to think"` | push button |
| Attach trigger | `attach_trigger` | `name: "Add files and more"` | push button |
| Upload item | `tool_upload` | `name_contains: "Add photos"` | menu item |
| Input | `input` | `role: entry, states: editable` | entry |
| Send | `send_button` | `name: "Send prompt"` | push button |
| Stop | `stop_button` | `name_contains: "Stop streaming"` | push button |
| Copy | `copy_button` | `name_contains: "Copy"` | button |
| Extended Pro deselect | `extended_pro` | `name: "Extended Pro"` | push button |
| Pro mode indicator | `pro_indicator` | `name_pattern: "Pro, click to remove"` | push button |

**Key quirks:** React portal dropdowns are invisible to AT-SPI; model selector requires `xdotool_first`; `?temporary-chat=true` URL prevents Extended Pro inheritance; `fence_after: []` because model selector comes AFTER sidebar in tree.

### Claude

| Step | Element Key | Name Match | Role |
|------|-------------|-----------|------|
| Model selector | `model_selector` | `name_contains: ["Opus 4.6", "Sonnet 4.6", "Haiku 4.5"]` | push button |
| Model: Opus | `model_opus` | `name_contains: "Opus 4.6 Most capable"` | push button |
| Model: Sonnet | `model_sonnet` | `name_contains: "Sonnet 4.6 Most efficient"` | push button |
| Attach trigger | `toggle_menu` | `name_contains: ["Add files", "Toggle menu"]` | push button |
| Upload item | `upload_files_item` | `name_contains: ["Add files", "Add content"]` | item |
| Input | `input` | `name: "Write your prompt to Claude", role: entry` | entry |
| Send | `send_button` | `name: "Send message"` | push button |
| Stop | `stop_button` | `name_contains: "Stop response"` | push button |
| Copy | `copy_button` | `name_contains: "Copy"` | button |
| Extended thinking | `model_extended_thinking` | `name_contains: "Extended thinking"` | push button |

**Key quirks:** ProseMirror contenteditable does NOT accept AT-SPI `insert_text()` — **clipboard paste only**; `fence_after: [{ name: "Starred", role: heading }]` cuts off sidebar history; button name IS the model name.

### Gemini

| Step | Element Key | Name Match | Role |
|------|-------------|-----------|------|
| Mode picker (model) | `mode_picker` | `name: "Open mode picker"` | push button |
| Mode: Pro | `mode_pro` | `name_contains: "Pro Advanced math"` | item |
| Mode: Thinking | `mode_thinking` | `name: "Thinking Solves complex problems"` | item |
| Tools button | `tools_button` | `name: "Tools"` | push button |
| Tool: Deep think | `tool_deep_think` | `name: "Deep think"` | item |
| Tool: Deep research | `tool_deep_research` | `name: "Deep research"` | item |
| Attach trigger | `upload_menu` | `name: "Open upload file menu"` | push button |
| Upload item | `upload_files_item` | `name_pattern: "Upload files*"` | menu item |
| Input | `input` | `role: entry, states: editable` | entry |
| Send | `send_button` | `name: "Send message"` | push button |
| Stop | `stop_button` | `name_contains: "Stop response"` | push button |
| Copy | `copy_button` | `name_contains: "Copy"` | button |
| Share & Export (Deep Research) | `share_export` | `name_contains: "Share & export"` | button |
| Start research | `start_research` | `name: "Start research"` | push button |

**Key quirks:** `atspi_first` click strategy; AT-SPI tree nests buttons at depth 16-20; mode picker and tools button are **separate**; Deep Research is multi-step (plan card → Start research button click → respawn monitor → Share & Export → Copy Content); `fence_after: [{ name: "Chats", role: heading }]`.

### Grok

| Step | Element Key | Name Match | Role |
|------|-------------|-----------|------|
| Model selector | `model_selector` | `name: "Model select"` | push button |
| Model: Expert | (menu item) | contains "Expert" | push button |
| Model: Heavy | (menu item) | contains "Heavy" | push button |
| Attach trigger | `attach_trigger` | `name: "Attach"` | push button |
| Upload item | `upload_files_item` | `name: "Upload a file"` | menu item |
| Input | `input` | `role_contains: section, states: editable, focusable, multi-line` | section |
| Stop | `stop_button` | `name_contains: "Stop"` | push button |
| Copy | `copy_button` | `name: "Copy"` | push button |
| Share link | `create_share_link` | `name: "Create share link"` | push button |

**Key quirks:** Model select button text does NOT change — must reopen to verify; files **persist across sessions** (stale check required); copy buttons may have zero-size extents → use `do_action(0)`; `fence_after: [{ name: "History", role: push button }]`; `consultation_defaults.mode: heavy`.

### Perplexity

| Step | Element Key | Name Match | Role |
|------|-------------|-----------|------|
| Model selector | `model_selector` | `name: "Model"` | push button |
| Attach/Tools trigger | `attach_trigger` | `name: "Add files or tools"` | push button |
| Upload item | `upload_files_item` | `name_contains: "Upload files"` | menu item |
| Deep research item | (radio item) | `name: "Deep research New"` | menu item |
| Input | `input` | `role: entry, states: editable` | entry |
| Submit | `submit_button` | `name: "Submit"` | push button |
| Stop | `stop_button` | `name_contains: "Stop response"` | push button |
| Copy | `copy_button` | `name: "Copy"` | push button |
| Copy contents | `copy_contents_button` | `name: "Copy contents"` | button |
| Thread actions | `thread_actions` | `name: "Thread actions"` | push button |
| Share | `share_button` | `name: "Share"` | push button |
| Download | `download_button` | `name: "Download"` | push button |

**Key quirks:** Deep research is a **radio menu item** in the tools dropdown, not a standalone mode; Copy button returns summary only — for full Deep Research reports, use Export → Download as Markdown; model selector has static name "Model" (can't verify from tree); `fence_after: [{ name: "Recent Collapse", role: push button }]`; `consultation_defaults.mode: deep_research`.

***

## New Implementation Design

### Branch Name
`feature/consultation-isolated-executors`

### Package Structure

```
consultation/
├── __init__.py
├── base.py                    # Abstract ConsultationExecutor (interface only, no logic)
├── runner.py                  # ConsultationRunner: load executor, execute 8 steps, return result
├── executors/
│   ├── __init__.py
│   ├── chatgpt.py             # ChatGPTConsultation — all 8 steps
│   ├── claude.py              # ClaudeConsultation — all 8 steps
│   ├── gemini.py              # GeminiConsultation — all 8 steps
│   ├── grok.py                # GrokConsultation — all 8 steps
│   └── perplexity.py          # PerplexityConsultation — all 8 steps
└── validate.py                # AT-SPI validation helpers (YAML-driven, read-only)
```

**Dependency rule:** Each executor in `consultation/executors/` MUST NOT import from any other executor. They may import from:
- `core.config` (YAML loader)
- `core.atspi` (tree access)
- `core.input` (keyboard/mouse)
- `core.tree` (find_elements)
- `core.interact` (atspi_click)
- `storage.neo4j_client`, `storage.redis_pool`
- `consultation.validate` (validation helpers)

They must NOT import from `tools/attach.py`, `tools/extract.py`, `core/mode_select.py`, or any other executor.

***

## Step-by-Step Implementation Per Platform

### Step 1: Model/Mode/Tools Selection

**Principle:** The YAML `element_map` specifies every button. The executor reads it directly. No string matching on `how` text.

**Per-platform logic:**

- **ChatGPT**: `xdotool_first` click on `model_selector` → wait for React portal → scan AT-SPI for `model_{target}` element_map match → click. For Extended: after Pro selected, scan for `extended_pro` / `thinking_extended` tiles. Check for and remove stale Extended Pro indicator (`extended_pro` button named "Extended Pro, click to remove") on fresh sessions.
- **Claude**: `xdotool_first` click on `model_selector` (button name is current model) → AT-SPI scan for model dropdown items → click `model_{target}`. For Extended Thinking: click `model_extended_thinking` button via `toggle_menu`.
- **Gemini**: `atspi_first` click on `mode_picker` → AT-SPI scan for `mode_{target}` radio item → click. Tools (Deep Think, Deep Research): `atspi_first` click on `tools_button` → scan for `tool_{target}` check menu item → click. Verify via checked state.
- **Grok**: `xdotool_first` click on `model_selector` → AT-SPI scan for model items → click → reopen to verify (per YAML `reopen_to_verify: true`).
- **Perplexity**: `xdotool_first` click on `model_selector` → AT-SPI scan model items → click. Deep Research: `xdotool_first` click on `attach_trigger` → scan for "Deep research New" radio item → verify checked state.

**AT-SPI validation:** After each selection, re-scan tree and verify using `validation.model_selected` spec from YAML. Log `verification_source: 'tree'` or `'unverifiable'`.

### Step 2: Attachment

**Principle:** The YAML `attach_method` determines the path. No fallback guessing — if YAML spec doesn't match, raise an error with the actual AT-SPI tree dump.

**Per-platform logic:**

- **ChatGPT** (`keyboard_nav`): `xdotool_first` on `attach_trigger` ("Add files and more") → scan AT-SPI for `tool_upload` item (`name_contains: "Add photos"`) → if found, click; else fall back to Down+Enter (max 3) → wait for GTK/portal dialog → Ctrl+L, paste path, Enter → verify `validation.attach_success.indicators` (Remove button appears).
- **Claude** (`atspi_menu`): `xdotool_first` on `toggle_menu` → scan AT-SPI for `upload_files_item` (`name_contains: ["Add files", "Add content"]`) → `atspi_click` on item → wait for dialog → Ctrl+L, paste path, Enter → verify Remove button. **Never xdotool the menu item** (Claude coordinate clicks on menu items work per quirk note).
- **Gemini** (`atspi_menu`): `atspi_first` on `upload_menu` → scan AT-SPI for `upload_files_item` (`name_pattern: "Upload files*"`) → `atspi do_action(0)` → wait for GTK/portal dialog → Ctrl+L, paste path, Enter → verify Remove button. Note: input Y shifts after attach — re-inspect before prompt entry.
- **Grok** (`keyboard_nav`): Check for **stale attachments first** (`stale_check: true`). `xdotool_first` on `attach_trigger` ("Attach") → scan AT-SPI for `upload_files_item` ("Upload a file") → if found, `xdotool_first` (coordinate clicks work; AT-SPI do_action only focuses) → dialog → Ctrl+L, paste, Enter → verify. If model selector is active, activate input field first before attach.
- **Perplexity** (`keyboard_nav`): `xdotool_first` on `attach_trigger` — use direct xdotool coordinate click (not `taey_select_dropdown`; tabs context menu conflict documented in quirks). Scan for `upload_files_item` (`name_contains: "Upload files"`) → click by coordinate → dialog → Ctrl+L, paste, Enter → verify Remove button. Note: GTK dialog Ctrl+L may conflict with Firefox URL bar in some sessions.

**Validation:** After dialog closes, poll AT-SPI tree for indicators from `validation.attach_success.indicators` (up to 4s, 0.2s interval). Write Redis checkpoint `checkpoint:{platform}:attach`.

### Step 3: Prompt Entry

**Principle:** Find the input element via `element_map.input` spec, click it, grab_focus via AT-SPI component interface, then clipboard paste. **Never AT-SPI insert_text()** — it fails on ProseMirror (Claude) and is unreliable on others.

**Per-platform specifics:**
- **Claude**: Input is `name: "Write your prompt to Claude", role: entry`. ProseMirror — clipboard paste is the only method.
- **Gemini**: Two possible input elements (`input` and `input_alt`). After attachment, input Y position shifts — must re-scan elements, don't use cached Y coordinate.
- **Grok**: Input is `role_contains: section, states: editable, focusable, multi-line` (not `entry`). Standard clipboard paste.
- **ChatGPT/Perplexity**: Standard `role: entry, states: editable`.

**Flow:** `click_at(input_x, input_y)` → `grab_focus()` via AT-SPI component interface → `inp.clipboard_paste(message)` → verify input is non-empty (optional: re-scan for input element, check name/value changed).

### Step 4: Send

**Principle:** Find the send button via `element_map.send_button`, click it, then poll for URL change to validate the send actually reached the backend.

| Platform | Send Button Name | Role |
|---------|-----------------|------|
| ChatGPT | `"Send prompt"` | push button |
| Claude | `"Send message"` | push button |
| Gemini | `"Send message"` | push button |
| Grok | (Enter key) | — |
| Perplexity | `"Submit"` | push button |

**URL capture:** Poll `atspi.get_document_url(doc)` for up to 5 seconds (5 × 1s). Perplexity does a multi-stage redirect (`/search/new/{uuid}` → `/search/{slug}`) — capture the **final** URL, not the first change. Store final URL in Neo4j session and Redis `pending_prompt:{platform}`.

**Gemini Deep Research post-send action:** After send, scan for `start_research` button (`name: "Start research"`). If found, wait 3s (per YAML `post_send_action.wait_before`), click it, then respawn monitor.

**Validation (send_success):** Poll AT-SPI tree for `stop_button` within 30s. If stop button never appears within 90s, declare `send_failure` (prevents looping for 2 hours as per recent Perplexity fix).

### Step 5: Stop Button Monitoring

**Principle:** Register a monitor session in Redis before send. The central monitor (`monitor/central.py`) polls registered sessions. Each executor defines its platform-specific stop patterns.

**Stop patterns per platform:**
- ChatGPT: `["stop", "stop generating", "stop streaming"]`
- Claude: `["stop", "stop response"]`
- Gemini: `["stop", "stop response", "cancel"]`
- Grok: `["stop", "stop generating", "stop model response", "thinking"]`
- Perplexity: `["stop", "stop response (esc)", "cancel"]`

**Monitor session data written to Redis:**
```json
{
  "platform": "...", "monitor_id": "...", "url": "...",
  "session_id": "...", "mode": "...", "timeout": ...,
  "stop_seen": false, "generating_since": null
}
```

**Timeout values** come from `mode_guidance.{mode}.timeout` in YAML (e.g., Deep Research = 7200s, normal = 1800s).

**Completion detection:** Response is complete when the copy button appears AND the stop button is absent (per `validation.response_complete` in each YAML).

### Step 6: Response Extraction

**Principle:** Each platform has its own extraction path. No shared extraction function.

| Platform | Method | Notes |
|---------|--------|-------|
| ChatGPT | Last copy button in last assistant group | Walk AT-SPI for `presentation` role groups containing copy button; click lowest Y |
| Claude | Last copy button in conversation | `extract_method: last_copy_button`; scan for `copy_button` spec |
| Gemini (standard) | Last copy button | `extract_method: last_copy_button`; scan for `copy_button` spec |
| Gemini (Deep Research) | Share & Export → Copy Content | Click `share_export` button → wait for dropdown → click "Copy Content" |
| Grok | Last copy button | `do_action(0)` not coordinate click (zero-size extents quirk) |
| Perplexity (standard) | `copy_button` (`name: "Copy"`) | Returns summary only |
| Perplexity (Deep Research) | Thread Actions → Export → Download as Markdown | Full report extraction |

**After clipboard read:** Verify content is non-empty and length > 50 chars. Retry once if empty (some platforms need a second click due to clipboard timing).

### Step 7: Attachment Extraction

**Principle:** Extract the content of any attached files from the conversation response. Platforms may reference attached content in their response, but the actual file bytes need to be stored separately.

**Implementation per platform:**
- Read the `attachment_sources` from the plan (list of original file paths before consolidation).
- For each source file, read its content from disk (already available at the paths used in attach step).
- If the platform included attachment content in the response (common with Claude artifacts and ChatGPT canvas), extract those artifact/canvas blocks from the copied response text using regex on markdown code block boundaries.
- Store each attachment as a separate Neo4j `Attachment` node linked to the `Message` node.

**Claude artifacts:** Look for artifact boundaries in copied response: `\`\`\`artifact` or ProseMirror document chunks (these appear as "Pasted Text" document chips with content visible in response).

**Validation:** After extraction, verify extracted attachment content matches source file content (hash comparison for binary, text comparison for markdown).

### Step 8: Storage in Neo4j

**Principle:** All 8 steps produce data that must be persisted. Storage happens at each step, not only at the end.

**Neo4j node types and when they're written:**

| Node | Created At | Data |
|------|-----------|------|
| `Session` | Step 4 (send) | platform, url, session_type, purpose |
| `Message (user)` | Step 4 (send) | content, attachments list |
| `Message (assistant)` | Step 6 (extract) | content, extracted_at, word_count |
| `Attachment` | Step 7 | filename, content, type, source_path |
| `ConsultationRun` | Step 8 (final) | all step results, timings, success flags |

**Redis cleanup on completion:** Delete `plan:current:{platform}`, `plan:{platform}`, `pending_prompt:{platform}`, `checkpoint:{platform}:attach`, and release the global plan lock `taey:plan_active:{display}`.

***

## Consultation Runner Interface

The new `ConsultationRunner` accepts a structured plan dict and executes all 8 steps, returning a `ConsultationResult`:

```python
# consultation/runner.py

class ConsultationPlan:
    platform: str          # 'chatgpt' | 'claude' | 'gemini' | 'grok' | 'perplexity'
    model: str             # exact model name or 'default'
    mode: str              # mode key from YAML mode_guidance
    tools: list[str]       # tool names to enable ([] for none)
    attachments: list[str] # file paths (identity files prepended automatically)
    prompt: str            # the consultation prompt text
    session: str           # 'new' or existing session URL

class ConsultationResult:
    success: bool
    platform: str
    session_url: str       # final URL after redirect
    neo4j_session_id: str
    neo4j_message_id: str  # assistant response message ID
    response_text: str     # extracted response
    attachments_extracted: list[dict]
    step_results: dict     # per-step timing and success
    errors: list[str]
```

**Ideal automated end state:** Claude creates a `ConsultationPlan` JSON. The runner dispatches it to the correct executor. Each executor runs the 8 steps, validates each via AT-SPI, and returns a `ConsultationResult`. Claude only needs to provide the plan — all AT-SPI interaction is handled by the executor.

***

## Critical Implementation Rules

1. **No shared runtime logic between executors.** If ChatGPT needs a helper function, it lives in `consultation/executors/chatgpt.py`. If Claude needs the same pattern, it gets its own copy in `claude.py`. This is intentional duplication to prevent cross-platform breakage.

2. **Every action must be validated in the AT-SPI tree before proceeding.** No "click and hope." After each step, scan the tree for the validation indicator defined in the platform YAML.

3. **Send is validated by URL change.** A new URL appearing after pressing Enter/Submit is the proof that the message was received. Store it.

4. **`_match_element()` lives in one place: `consultation/validate.py`.** All executors import it from there. No more duplicate copies in attach.py, plan.py, and inspect.py.

5. **YAML is the authority.** If the AT-SPI tree shows an element whose name doesn't match the YAML spec, log it as a DRIFT event (for future YAML update), but do not silently fall back to guessing.

6. **Clipboard paste is the only input method.** Never attempt AT-SPI `insert_text()` on any platform. Click input, grab_focus, then clipboard paste.

7. **Grok stale attachment check before every attach.** Scan for Remove buttons before opening the attach dialog. If found, click them to clear.

8. **Gemini re-inspect after attach.** The input field Y position shifts after a file is attached on Gemini. Always re-scan elements before prompt entry on Gemini.

9. **ChatGPT Extended Pro cleanup.** On every fresh ChatGPT session (URL contains `temporary-chat=true`), scan for `extended_pro` button. If found, click it to deselect before setting the desired mode.

10. **Perplexity Deep Research full extraction.** The standard Copy button returns summary only. If `mode == 'deep_research'`, the executor must use Thread Actions → Export → Download as Markdown for full content.

***

## Suggested Branch Creation Steps

The new branch should be created from `main` as `feature/consultation-isolated-executors`. The implementation order:

1. Create `consultation/base.py` with the `ConsultationExecutor` abstract class and `ConsultationResult` dataclass.
2. Create `consultation/validate.py` with the single canonical `_match_element()`, `_find_by_spec()`, and `_poll_for_indicator()` functions.
3. Implement `consultation/executors/claude.py` first (simplest AT-SPI behavior, most reliable).
4. Implement `consultation/executors/chatgpt.py` (React portal workarounds well-documented).
5. Implement `consultation/executors/gemini.py` (most complex — Deep Research multi-step).
6. Implement `consultation/executors/grok.py` (stale file quirk, zero-size button quirk).
7. Implement `consultation/executors/perplexity.py` (radio item tools, two extraction paths).
8. Create `consultation/runner.py` to dispatch plans to executors.
9. Wire up the MCP tool endpoint to call `ConsultationRunner.run(plan)`.

The existing `tools/plan.py`, `tools/attach.py`, `core/mode_select.py`, and `tools/extract.py` are **left untouched** — they continue to serve the bot workflow and manual tool calls. The new `consultation/` package is additive and parallel.

That's everything needed. The answer is direct and clear now.

Yes — the bots can and should reuse the exact same executor classes. Here's exactly how it works:

## Bots vs. Consultations: Same Executor, Different Loop

The key difference is **who calls the executor and what the loop looks like:**

| Dimension | Consultation | Bot (e.g. hmm_bot) |
|-----------|-------------|---------------------|
| Who generates the plan | Claude (one-shot) | Bot loop (programmatically, every cycle) |
| Prompt | Varies per consultation | Same prompt every cycle (`get_prompt()` called once at startup) |
| Attachments | Varies per consultation | Different package file each cycle (`get_next_package(platform)`) |
| Model/mode/tools | Set by consultation plan | Fixed in bot config — set once per session, not re-selected each cycle |
| Session | New session each consultation | New fresh session each cycle (navigates to `FRESH_URLS[platform]`) |
| Post-extraction | Store to Neo4j | Call `complete_package(platform, response_file)` then loop |

## What This Means Structurally

The `ConsultationExecutor` you build for the new `consultation/` package has all 8 steps. For bots, you **skip step 1 (model/mode/tools select) after the first cycle** — those settings are fixed and already selected on the fresh session. Everything else — attach, prompt entry, send, stop monitoring, extract, Neo4j storage — runs identically.

The bot's `process_platform()` becomes:

```python
# agents/hmm_bot.py — after consultation executors exist

from consultation.runner import ConsultationRunner

def process_platform(platform: str, prompt: str) -> dict:
    pkg_path = get_next_package(platform)
    if not pkg_path:
        return {'error': 'no_items'}

    plan = ConsultationPlan(
        platform=platform,
        model='auto',            # fixed per bot config
        mode='auto',             # fixed — no re-selection each cycle
        tools=[],
        attachments=[pkg_path],
        prompt=prompt,           # same prompt every cycle
        session='new',
    )

    result = ConsultationRunner.run(plan)

    if result.success:
        complete_package(platform, result.response_text)
    else:
        fail_package(platform, result.errors[0])

    return result
```

## The One Bot-Specific Difference: Model/Mode Skip

Looking at `hmm_bot.py`, it only calls `select_model()` for ChatGPT, and even then uses `'auto'` — the simplest possible mode. For all other platforms the bot just navigates fresh and goes directly to attach. The executor needs a `skip_model_select: bool` flag on `ConsultationPlan` (defaulting to `False` for consultations, `True` for bots after the first cycle), so the executor skips Step 1 entirely rather than wasting time clicking through the model picker for a setting that's already correct on a fresh session.

## What the Bot Loop Actually Becomes

```
LOOP:
  1. get_next_package(platform)          → pkg_path
  2. ConsultationRunner.run(plan)        → handles steps 2-8 via platform executor
  3. complete_package() or fail_package()
  4. sleep + jitter, repeat
```

The 69,000-line `hmm_bot.py` collapses to ~50 lines of loop logic. All the attach/send/wait/extract complexity that is currently duplicated inside `hmm_bot.py` (its own `attach_file()`, `send_prompt()`, `wait_for_response()`, `extract_response()`) gets deleted and replaced by the executor. Same for `sft_gen_bot.py`, `dpo_bot.py`, `training_gen_bot.py` — they all have the same pattern.

## Implementation Order

1. Build consultation executors on `feature/consultation-isolated-executors` (as planned)
2. Add `skip_model_select` flag to `ConsultationPlan`
3. Refactor `hmm_bot.py` first (it's the most complete reference) — replace its internal implementations with `ConsultationRunner.run()`
4. Once `hmm_bot` validates successfully, the other bots follow the same pattern one-for-one

The bots become thin loop controllers; all AT-SPI logic lives in the executors exactly once.