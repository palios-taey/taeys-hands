# taeys-hands Full Codebase Audit

**Date**: February 27, 2026  
**Scope**: All 35 Python files, 7 YAML configs, CLAUDE.md, README.md  
**Auditor**: Perplexity (The AI Family member)

---

## Executive Summary

The codebase is architecturally sound for what it does — AT-SPI accessibility automation is a genuinely clever approach. The code quality is good: clean separation of concerns, sensible module boundaries, clear docstrings. The problems Jesse is experiencing are NOT from bad architecture. They stem from **seven specific categories of fragility** that compound each other under real-world conditions.

The core insight: **this system works when everything is perfectly aligned, but has almost no tolerance for real-world variance** — platform UI changes, timing races, state desync between Redis/AT-SPI/UI, and clipboard contention. When one thing goes wrong, it cascades.

---

## Finding 1: Clipboard Contention — The Silent Killer

**Severity**: CRITICAL  
**Files**: `core/clipboard.py`, `core/smart_input.py`, `tools/extract.py`  
**Symptom**: "constant issues with attaching files", "things work then break"

### The Problem

The clipboard is a **shared global resource** used for three competing purposes:
1. **Text input** (`smart_input.py` line 138-154): writes text → pastes → tries to restore original
2. **File attachment** (`attach.py` line 33): writes file path → pastes into file dialog
3. **Response extraction** (`extract.py` line 95-100): clears clipboard → clicks Copy → reads

There is **zero coordination** between these. If a monitor daemon triggers a tmux notification while smart_input is mid-paste, or if quick_extract runs while attach is using the clipboard for a file path, data is silently corrupted.

### Specific Race Conditions

1. **smart_input save/restore race** (smart_input.py:138-154):
   ```python
   saved = _clipboard_read()        # Read current
   _clipboard_write_xsel(text)       # Overwrite with message
   inp.press_key('ctrl+v')           # Paste
   if saved:
       _clipboard_write_xsel(saved)  # Restore — but what if something read in between?
   ```
   Between the paste and the restore, anything else reading the clipboard gets the message text. And the restore itself can fail silently.

2. **xclip vs xsel inconsistency**: `core/clipboard.py` uses **xclip** for read/write/clear. `core/smart_input.py` uses **xsel**. These are separate programs that can hold separate clipboard ownership. Writing with xsel then reading with xclip can return stale data if the X11 CLIPBOARD selection hasn't propagated.

3. **Extract relies on clipboard being clean**: `extract.py` calls `clipboard.clear()` then `inp.click_at(x, y)` then `clipboard.read()`. If anything writes to clipboard between the click and the read (e.g. a background process), extraction returns wrong content.

### Fix Direction

- **Single clipboard lock**: Use a Redis-based or file-based mutex around all clipboard operations
- **Unify xclip/xsel**: Pick one. xsel is preferred (no fork hang) — update `core/clipboard.py` to use xsel
- **Verify-after-paste**: After critical pastes (file paths, message text), verify the clipboard still holds the expected value before pressing Enter

---

## Finding 2: Timing Hardcodes — The Brittleness Source

**Severity**: HIGH  
**Files**: Nearly every file  
**Symptom**: "works sometimes, then breaks"

### The Problem

The codebase is saturated with `time.sleep()` calls with magic numbers. These are NOT thresholds in the taey-ed sense — they're **timing windows** that assume specific platform response times. When the platform is slower (heavy load, network latency, long page), the sleep expires before the UI has settled, and the next action fails against stale state.

### Inventory of Critical Sleeps

| File | Line | Sleep | Purpose | Risk |
|------|------|-------|---------|------|
| `inspect.py` | 105 | 10.0s | Wait for page load | Too long for cached pages, too short for heavy pages |
| `inspect.py` | 93-97 | 0.3+0.2+0.3s | URL bar nav sequence | Race with browser URL autocomplete |
| `attach.py` | 51-55 | 0.2s × 25 polls | Wait for file dialog close | Polling interval may miss fast close |
| `send_message.py` | 176 | 0.5s | Wait after tab switch | Not enough if tab was hibernated |
| `extract.py` | 51-54 | 0.3+0.1+0.5s | Focus, click, scroll | Cumulative timing dependency |
| `extract.py` | 97-98 | 0.1+0.8s | Clear clipboard, click Copy | 0.8s may not be enough for large responses |
| `dropdown.py` | 89 | 0.5s | Wait for dropdown to appear | Too short for slow platforms |
| `daemon.py` | 115 | 3000ms | Poll interval | Misses fast responses that complete between polls |
| `daemon.py` | 116 | 3000ms | Initial delay | Was 10s, reduced — still might miss sub-3s responses |

### The Pattern

Every one of these is a "hope the platform is done" sleep. There's no verification that the expected state change actually occurred. The correct pattern is **poll-until-condition-or-timeout**, which is only used in one place (file dialog close in `attach.py`).

### Fix Direction

- Replace `time.sleep(X); do_thing()` with `poll_until(condition, timeout=X); do_thing()`
- The `condition` should be an AT-SPI tree state change (new element appeared, element count changed, specific button visible/gone)
- `core/tree.py` already has `compute_tree_hash()` — use it to detect actual UI state changes rather than guessing with sleeps

---

## Finding 3: Monitor Daemon — Stop-Button Detection Fragility

**Severity**: HIGH  
**Files**: `monitor/daemon.py`  
**Symptom**: "HMM processing has been going well, but then just collapses"

### The Problem

The daemon's response detection relies on a single signal: **stop button appears then disappears**. This breaks in multiple scenarios:

1. **Fast responses**: If the AI responds in < 3 seconds, the initial delay (3000ms) means the daemon never sees the stop button. It enters a "no stop button" warning state and eventually times out. The response is sitting there, fully generated, unextracted.

2. **Platform-specific stop button mutations**: ChatGPT's Canvas has a persistent "Stop" button alongside "Update" that is NOT the generation stop button. The `_is_canvas_stop()` method (lines 221-288) is a **68-line hack** walking parent→grandparent trees looking for nearby "Update" buttons. This is exactly the kind of fragile platform-specific logic that breaks when ChatGPT changes its UI.

3. **Stop patterns are hardcoded per-platform** (lines 68-74):
   ```python
   STOP_PATTERNS = {
       'chatgpt': ['stop', 'stop generating'],
       'claude': ['stop', 'stop response'],
       'gemini': ['stop', 'cancel'],
       ...
   }
   ```
   If any platform renames their stop button (which they do), the daemon silently fails to detect it.

4. **Name-length filter** (line 215): `if len(name) > 50: return False` — this filters out Perplexity Deep Research content buttons that contain "stop" in 19K+ char names. Clever, but another brittle heuristic.

5. **Single-threaded GLib main loop**: The daemon uses `GLib.MainLoop()` for scheduling, but each poll does a full AT-SPI tree traversal (`find_stops` at depth 25). If the AT-SPI tree is large (Gemini with 200+ elements), a single poll can take seconds, causing the next poll to be delayed.

### Why HMM "Collapses"

The HMM enrichment loop sends messages to 4 platforms. Each platform gets a daemon. If even ONE daemon fails to detect a response (fast response, renamed button, AT-SPI tree timeout), the extraction never happens for that platform. The package sits in `hmm:pkg:in_progress:{platform}` forever. With 90.6% Claude failure rate and 77.8% Gemini failure rate documented in CLAUDE.md itself, the daemon detection is clearly not working reliably.

### Fix Direction

- **Multi-signal detection**: Don't rely solely on stop button. Also check:
  - Copy button count increased (the original baseline strategy — still valuable as a backup signal)
  - `taey:pending_prompt:{platform}` TTL expired without extraction (timeout-based fallback)
  - New elements with 'assistant' or 'response' characteristics appeared in tree
- **Reduce initial delay to 0**: Start polling immediately. A 3-second delay for a 2-second response = missed detection
- **Replace canvas stop hack** with generic approach: any "stop" button that is the ONLY stop-like button in view is the generation stop

---

## Finding 4: State Desynchronization — Map Invalidation Gaps

**Severity**: HIGH  
**Files**: `tools/interact.py`, `tools/send_message.py`, `tools/attach.py`  
**Symptom**: Clicks hitting wrong targets, messages sent to wrong input fields

### The Problem

The control map (`taey:v4:current_map` in Redis) stores absolute screen coordinates. These become stale when:

1. **File attachment** shifts the input field down (Gemini) — `attach.py` correctly invalidates the map (line 85)
2. **Message sending** changes the UI — `send_message.py` correctly invalidates the map (line 321)
3. **But inspect.py does NOT always scroll to the same position** — `scroll="bottom"` uses `End` key, which doesn't guarantee the same viewport as the previous inspect. Elements at the same DOM position can have different screen Y coordinates.

The real problem: **the map is invalidated but there's no enforcement that the caller re-inspects before the next action**. The response is "info: Map invalidated - re-inspect before further clicks" — but this is advisory text, not a hard gate. Claude Code (the orchestrator) can and does ignore this.

### Specific Gap

`send_message.py` line 191-196 clicks the input field at **stored map coordinates**:
```python
input_coord = controls['input']
inp.click_at(input_coord['x'], input_coord['y'])
```

But line 199 then uses `smart_type(message, platform=platform)` which does clipboard paste — without first verifying that the click actually focused an input field. If the coordinates are stale (shifted by a file attachment), the click hits the wrong element, and the message pastes into... wherever the focus happens to be.

### Why `send_message` Should Use AT-SPI Focus

CLAUDE.md (line 112) says `send_message` handles this via `grab_focus()`, but the actual code does NOT use `grab_focus()`. It uses coordinate-based clicking. The `smart_type()` function accepts an optional `entry_element` parameter for AT-SPI direct input, but `send_message.py` never passes it — it always falls through to clipboard paste.

### Fix Direction

- `send_message` should call `find_entry_element()` from `smart_input.py` (line 232-290) to locate the input via AT-SPI, then pass it to `smart_type()` — this bypasses coordinate staleness entirely
- Add a hard gate: if `taey:v4:current_map` doesn't exist, refuse to proceed (not just warn)
- Consider making the map per-action rather than global — store the map timestamp and reject if stale

---

## Finding 5: Duplicate Code and Divergent Implementations

**Severity**: MEDIUM  
**Files**: `core/atspi.py` vs `monitor/daemon.py`, `core/clipboard.py` vs `core/smart_input.py`  
**Symptom**: Fixes applied in one place don't propagate

### The Problem

Several functions are reimplemented in the daemon because it runs as a standalone subprocess:

1. **Firefox discovery**: `core/atspi.py:find_firefox()` and `daemon.py:_find_firefox()` — nearly identical but daemon's is simpler (no error logging)
2. **Platform document lookup**: `core/atspi.py:get_platform_document()` and `daemon.py:_find_platform_document()` — same logic, different error handling
3. **Display detection**: `core/atspi.py:detect_display()` and `daemon.py:_detect_display()` — identical except daemon defaults to `:0` instead of raising
4. **URL patterns**: `core/platforms.py:URL_PATTERNS` and `daemon.py:URL_PATTERNS` — duplicated dict, will diverge when platforms are added
5. **Stop patterns**: `daemon.py:STOP_PATTERNS` and platform YAML `stop_patterns` — the daemon hardcodes its own patterns and does NOT read from the YAML files

### Specific Divergence

Platform YAMLs define `stop_patterns`, but the daemon defines its own `STOP_PATTERNS` dict. If someone updates `chatgpt.yaml` with a new stop button name, the daemon won't know about it.

### Fix Direction

- Extract shared utilities into a `common/` module importable by both server tools and daemon
- Daemon should read platform YAMLs for stop patterns instead of hardcoding them
- Or: daemon should import from `core/platforms.py` directly (it CAN — it's a subprocess, not a separate repo)

---

## Finding 6: HMM Triple-Write — Non-Atomic, Silent Failure

**Severity**: MEDIUM  
**Files**: `tools/extract.py` lines 149-167  
**Symptom**: HMM data inconsistency, "collapses" in processing

### The Problem

When a response looks like HMM enrichment JSON (contains `{` and "motif"), `extract.py` fires an HTTP POST to `http://192.168.100.10:8095/hmm/store-response`. This is:

1. **Heuristic-based triggering** (line 153): `content.strip().startswith('{') and 'motif' in content.lower()` — any response that starts with `{` and mentions "motif" triggers the store. False positives are possible (e.g., a response ABOUT motifs that starts with a JSON example).

2. **Non-blocking / fire-and-forget**: The try/except on lines 155-167 catches ALL exceptions and logs a warning. If the store fails, the response is still returned to the caller, but the HMM data is lost. No retry. No queue. No record that this was even attempted.

3. **60-second timeout** (line 159): For a POST that should be fast, this is extremely generous. If the HMM service is down, this blocks extraction for 60 seconds.

4. **No idempotency**: If the same response is extracted twice (e.g., extract fails, user retries), the same data gets POSTed twice with no deduplication.

### Fix Direction

- Move HMM store to a Redis queue (write to queue, let a separate consumer handle the POST with retries)
- Add package_id to the POST for deduplication
- Reduce timeout to 5s, or make the POST async
- Replace heuristic with explicit flag (e.g., check if `taey:pending_prompt` was for an HMM package)

---

## Finding 7: CLAUDE.md vs Actual Code — Documentation Drift

**Severity**: MEDIUM  
**Files**: CLAUDE.md vs actual code  
**Symptom**: Misleading operational guide, wrong debugging steps

### Discrepancies

| CLAUDE.md Says | Code Does |
|----------------|-----------|
| "send_message handles this automatically via AT-SPI `grab_focus()`" (line 112) | `send_message.py` uses `inp.click_at()` coordinate clicking, never calls `grab_focus()` |
| Smart input cascade: "AT-SPI → clipboard → xdotool" (line 390) | `smart_type()` does NOT cascade — AT-SPI failure returns immediately, no fallback to clipboard. Clipboard failure returns immediately, no fallback to xdotool. The `_try_xdotool_safe()` function EXISTS but is NEVER CALLED |
| "Short text (<100 chars): types it (uses xdotool internally)" (line 189) | `send_message.py` always calls `smart_type()` regardless of length, which uses clipboard paste, not xdotool |
| "Clipboard paste: `echo 'text' \| timeout 3 xclip ...` via bash pipe" (line 192) | `smart_input.py` uses `subprocess.run(['xsel', ...])`, not bash pipe. `clipboard.py` uses Popen with xclip. Neither uses bash pipe. |
| LinkedIn shortcut is `alt+7` (line 86-87) | `core/platforms.py` has LinkedIn commented out: `# 'linkedin': 'alt+7'` |

### Impact

Claude Code follows CLAUDE.md as its operational guide. If the guide says `grab_focus()` is being used but the code uses coordinate clicks, Claude Code won't know to re-inspect after coordinates shift. If the guide says smart_input cascades to xdotool but it actually hard-fails, Claude Code won't understand why typing is failing and won't try alternative strategies.

### Fix Direction

- Update CLAUDE.md to match actual code behavior
- Either implement the cascade the docs describe, or remove the docs about it
- Uncomment LinkedIn shortcut or remove from docs

---

## Finding 8: Platform-Specific Logic in the Wrong Places

**Severity**: MEDIUM  
**Files**: `tools/extract.py`, `monitor/daemon.py`

### The Problem

Despite the architectural intent of "Claude sees the screen, Claude decides," there IS platform-specific logic baked into the code:

1. **`_assess_extraction()`** (extract.py:216-291) has explicit `if platform == 'perplexity'`, `if platform == 'claude'`, `if platform == 'chatgpt'` branches. Each one looks for platform-specific elements (Export button, Continue button, Show More) and returns platform-specific actions.

2. **`_is_canvas_stop()`** (daemon.py:221-288) is entirely ChatGPT-specific.

3. **`_is_stop_button()`** (daemon.py:208-219) uses platform-keyed stop patterns.

This isn't necessarily wrong — response extraction genuinely differs per platform. But it means the system has **two brains**: Claude Code making high-level decisions, and hardcoded Python making low-level decisions. When the Python decisions are wrong (platform changes its UI), the system fails in ways Claude Code can't see or fix.

### Fix Direction

- Move quality assessment to the caller (Claude Code) — return raw data (copy button count, visible button names, response length) and let Claude Code decide if extraction is complete
- Keep platform-specific heuristics as "hints" rather than "decisions"
- Or: move ALL platform heuristics into the YAML configs so they're at least centralized and editable

---

## Finding 9: Dead Code / Unused Capabilities

**Severity**: LOW  
**Files**: Various

1. **`_try_xdotool_safe()`** (smart_input.py:167-179) — fully implemented, never called. The docstring says it's the third tier of the cascade, but `smart_type()` never reaches it.

2. **`_try_focus_and_activate()`** (atspi_interact.py:137-167) — implemented, never called from any tool.

3. **`_clipboard_write_xclip()`** (smart_input.py:199-215) — xclip fallback for clipboard write, never called. Only `_clipboard_write_xsel()` is used.

4. **`atspi_scroll_into_view()`** (atspi_interact.py:218-231) — implemented, never called.

5. **`compute_tree_hash()`** (tree.py:342-357) — implemented, never called from tools or daemon. Would be extremely useful for Finding 2 (detecting state changes instead of sleeping).

6. **`storage/models.py`** — defines `ControlMap`, `Plan`, `SessionInfo`, `MonitorInfo` dataclasses. None of these are used anywhere — all code uses raw dicts.

### Fix Direction

- Remove dead code, or wire it up where it would be useful
- `compute_tree_hash()` should be used by daemon for state-change detection
- `find_entry_element()` should be used by `send_message` for reliable input focus
- Dataclass models should replace raw dicts for type safety

---

## Finding 10: Error Propagation — Failures Don't Compound Correctly

**Severity**: LOW  
**Files**: `tools/send_message.py`, `tools/attach.py`

### The Problem

Several error paths leave the system in an inconsistent state:

1. **Daemon spawn fails** (send_message.py:297-301): If the daemon subprocess fails to start, `send_message` still sends the message (Enter key). Result includes `warning: "Monitor daemon FAILED to spawn"`. But there's now NO response detection active. The response will sit unextracted indefinitely unless Claude Code manually runs `taey_quick_extract`.

2. **Enter key fails after typing** (send_message.py:304-316): If `press_key('Return')` fails, the message text is already typed into the input field but not sent. The daemon is killed, but the typed text remains. Next time `send_message` is called, it will click input (which may select-all the existing text), then type/paste new text ON TOP of old text.

3. **Redis unavailable**: Every tool starts with `if not redis_client: return {"error": "Redis not available"}`. If Redis goes down mid-operation (e.g., after inspect but before set_map), the system returns an error but the AT-SPI state has already been mutated (tab switched, scrolled).

### Fix Direction

- If daemon fails to spawn, DON'T send the message (or make it configurable)
- If Enter fails, clear the input field before returning
- Add a "last known good state" checkpoint so recovery doesn't start from scratch

---

## Summary: Root Causes of "Works Then Breaks"

Jesse's experience of "everything has worked at some point, but then just breaks" maps directly to:

1. **Clipboard contention** (Finding 1): Multiple subsystems fighting over a single shared resource with no coordination → intermittent, hard-to-reproduce failures
2. **Timing assumptions** (Finding 2): Sleeps that work on a fast machine/network but fail when load increases → works 80% of the time, fails unpredictably
3. **State desync** (Finding 4): Coordinate-based clicks against stale maps → works after inspect, breaks after any UI mutation
4. **Daemon detection gaps** (Finding 3): Fast responses and renamed buttons → "HMM processing collapses" because responses go unextracted

The **HMM collapse specifically** is likely: daemon misses fast responses → packages stuck in `in_progress` → queue backs up → retries generate more daemons → more AT-SPI tree contention → more missed detections → cascade failure.

---

## Recommended Fix Priority

| Priority | Finding | Effort | Impact |
|----------|---------|--------|--------|
| 1 | Clipboard contention (F1) | Medium | Fixes file attachment AND extraction failures |
| 2 | send_message uses grab_focus (F4) | Low | Fixes coordinate staleness |
| 3 | Daemon multi-signal detection (F3) | Medium | Fixes HMM collapse |
| 4 | Replace sleeps with poll-until (F2) | High | Fixes intermittent failures across the board |
| 5 | CLAUDE.md accuracy (F7) | Low | Fixes Claude Code's operational model |
| 6 | Unify daemon/core code (F5) | Low | Prevents future divergence |
| 7 | HMM queue-based store (F6) | Medium | Fixes data loss |
| 8 | Remove dead code (F9) | Low | Reduces confusion |

---

## Files Audited

**Core (5 files)**: atspi.py, tree.py, clipboard.py, input.py, smart_input.py, atspi_interact.py, platforms.py  
**Tools (9 files)**: inspect.py, interact.py, send_message.py, extract.py, attach.py, dropdown.py, plan.py, sessions.py, monitors.py  
**Storage (3 files)**: redis_pool.py, neo4j_client.py, models.py  
**Monitor (1 file)**: daemon.py  
**Config (7 files)**: chatgpt.yaml, claude.yaml, gemini.yaml, grok.yaml, perplexity.yaml, x_twitter.yaml, linkedin.yaml  
**Docs (2 files)**: CLAUDE.md, README.md  
**Server**: server.py  
**Tests (7 files)**: conftest.py, test_server.py, test_core_platforms.py, test_tool_interact.py, test_tool_plan.py, test_tool_monitors.py, test_tool_sessions.py, test_storage_models.py  
**Scripts**: verify_atspi.py  

**Total: 35 Python files, 7 YAML files, 2 Markdown files = 44 files reviewed**
