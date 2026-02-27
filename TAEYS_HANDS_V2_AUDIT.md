# taeys-hands V2 Audit — Re-assessment After 18 Commits

**Date**: February 27, 2026  
**Scope**: 27 files pulled from commit `4a3a7dd` vs V1 audit baseline  
**Auditor**: Perplexity (The AI Family member)  
**V1 Audit Date**: February 27, 2026 (earlier session)

---

## Executive Summary

18 commits were made between V1 and V2. The commits primarily targeted **fallback/cascade removal** (the largest cleanup), **dropdown hardening**, **daemon false-positive filtering**, and **lazy screen detection**. The grab_focus approach for send_message was attempted in multiple commits but **reverted** — send_message remains coordinate-based.

**Bottom line**: Of the 10 original findings, **none were fully resolved**. Two were partially improved (F3, F9). The remaining eight are unchanged. No regressions were introduced. The codebase is cleaner (fallbacks removed per Jesse's "no fallbacks, fail loudly" philosophy), but the core fragility sources — clipboard contention, timing hardcodes, coordinate-based clicking, and daemon detection gaps — remain.

---

## V1 Finding Verdicts

### F1 — Clipboard Contention (CRITICAL) → OPEN

**Status**: UNCHANGED  
**Evidence**: 
- `core/clipboard.py` — identical V1↔V2. Still uses **xclip** for read/write/clear
- `core/smart_input.py` — identical V1↔V2. Still uses **xsel** for clipboard writes
- No coordination mechanism added between clipboard consumers
- No clipboard mutex, no xclip/xsel unification

The xclip-vs-xsel inconsistency that causes silent data corruption between smart_input and extract remains exactly as it was.

---

### F2 — Timing Hardcodes (HIGH) → OPEN

**Status**: UNCHANGED  
**Evidence**:
- `tools/inspect.py` line 105: still `time.sleep(10.0)` for page load
- `tools/inspect.py` lines 93-97: still 0.3+0.2+0.3s URL bar sequence
- `tools/send_message.py` line 176: still `time.sleep(0.5)` after tab switch
- `tools/extract.py` lines 51-54, 97-98: same cumulative timing dependencies
- `tools/dropdown.py` line 89: still `time.sleep(0.5)` for dropdown appearance
- `tools/attach.py` line 153: still `time.sleep(1.0)` after attach click
- `core/input.py` lines 136-137, 166, 173, 179, 185: same sleep values
- `monitor/daemon.py` lines 114-116: same 3000ms poll interval, 3000ms initial delay

No `time.sleep()` call was changed, removed, or replaced with poll-until-condition. `compute_tree_hash()` in `core/tree.py` remains unused by any consumer.

---

### F3 — Daemon Stop-Button Detection Fragility (HIGH) → PARTIALLY IMPROVED

**Status**: PARTIALLY IMPROVED (1 of 5 sub-issues addressed)  
**What changed** (commits `53fe171`, `98a8687`):
- `_is_stop_button()` now has a **name-length filter** (`len(name) > 50` returns False) — this was the fix for Perplexity Deep Research content buttons containing "stop" in 19K+ character names
- This was already noted in V1 as "clever, but another brittle heuristic"

**What didn't change**:
- 3000ms initial delay still misses fast responses (< 3 seconds)
- `_is_canvas_stop()` remains a 68-line ChatGPT-specific hack (lines 221-288 identical V1↔V2)
- Stop patterns still hardcoded in daemon (`STOP_PATTERNS` dict on lines 68-74), NOT read from platform YAMLs
- Single-signal detection only (stop button appear/disappear) — no multi-signal fallback (copy count, tree hash, new elements)
- Single-threaded GLib main loop with full AT-SPI tree traversal per poll

---

### F4 — State Desync / Map Invalidation (HIGH) → OPEN (REVERTED)

**Status**: UNCHANGED (attempted fix was reverted)  
**Evidence**:
- Commit `2dd8065` explicitly reverted send_message back to stored map coordinates because grab_focus found the wrong element on Grok
- `tools/send_message.py` V2 lines 191-196: still `inp.click_at(input_coord['x'], input_coord['y'])` — pure coordinate clicking
- `smart_type()` still called without `entry_element` parameter
- Map invalidation after send (line 321) and after attach (line 85) still present — but still advisory only, no hard gate preventing stale-coordinate usage

The grab_focus approach was the right architectural direction, but the Grok failure caused a full revert. This leaves the most impactful reliability gap unresolved.

**New positive**: `send_message.py` line 320-321 now includes map invalidation after send (`redis_client.delete("taey:v4:current_map")`), and `attach.py` line 84-85 does the same. The V1 audit noted these existed — they remain the same.

---

### F5 — Duplicate Code / Divergent Implementations (MEDIUM) → OPEN

**Status**: UNCHANGED  
**Evidence**:
- `daemon.py:_find_firefox()` (line 169-176) still reimplements `core/atspi.py:find_firefox()`
- `daemon.py:_find_platform_document()` (line 178-206) still reimplements `core/atspi.py:get_platform_document()`
- `daemon.py:_detect_display()` (line 32-40) still reimplements `core/atspi.py:detect_display()` with different error handling (silent fallback to `:0` vs RuntimeError)
- `daemon.py:URL_PATTERNS` (line 76-82) still duplicates `core/platforms.py:URL_PATTERNS`
- `daemon.py:STOP_PATTERNS` (line 68-74) still NOT reading from platform YAMLs

No shared utilities were extracted. The daemon remains a fully standalone subprocess with its own copies of core functions.

---

### F6 — HMM Triple-Write (MEDIUM) → OPEN

**Status**: UNCHANGED  
**Evidence**:
- `tools/extract.py` lines 149-167: identical V1↔V2
- Still heuristic-triggered (`content.strip().startswith('{') and 'motif' in content.lower()`)
- Still fire-and-forget HTTP POST with 60-second timeout
- No retry queue, no deduplication, no package_id-based idempotency
- Commit `7c0724f` ("Wire HMM triple-write into extraction pipeline") was already present in V1 — this commit predates the V1 audit

---

### F7 — CLAUDE.md vs Actual Code (MEDIUM) → PARTIALLY IMPROVED

**Status**: PARTIALLY IMPROVED  
**What changed**:
- CLAUDE.md V2 (line 112) still says "send_message handles this automatically via AT-SPI `grab_focus()`" — but this was attempted and **reverted**. The CLAUDE.md claim was temporarily TRUE (during the grab_focus commits) but is now **FALSE again**
- CLAUDE.md V2 (line 390): "Cascade: AT-SPI `insert_text()` → clipboard paste (xsel) → xdotool (≥50ms delay)" — commit `c6f9958` removed the moderate fallback mechanisms (M1-M18) and commit `3460abb` removed "silent click and input cascades." After these removals, the cascade description may now be more misleading since fallbacks were explicitly stripped
- CLAUDE.md V2 (line 282-285): New "Screen Detection" section accurately describes the lazy screen detection added in `4a3a7dd`
- CLAUDE.md V2 (line 329-341): "Anti-Patterns" section added with "Create fallbacks → Fail loudly, fix root cause" — this aligns with the removal of fallback mechanisms

**Still inaccurate**:
- `grab_focus()` claim on line 112 — REVERTED in code, CLAUDE.md still claims it
- Smart input cascade description — fallbacks were removed, but cascade is still described as "AT-SPI → clipboard → xdotool"
- LinkedIn shortcut still not uncommented in `core/platforms.py`

---

### F8 — Platform-Specific Logic (MEDIUM) → OPEN

**Status**: UNCHANGED  
**Evidence**:
- `tools/extract.py:_assess_extraction()` lines 238-291: still has `if platform == 'perplexity'`, `if platform == 'claude'`, `if platform == 'chatgpt'` branches. Identical V1↔V2
- `monitor/daemon.py:_is_canvas_stop()` lines 221-288: still entirely ChatGPT-specific. Identical V1↔V2
- `monitor/daemon.py:_is_stop_button()` lines 208-219: still uses platform-keyed stop patterns. Identical V1↔V2

---

### F9 — Dead Code (LOW) → PARTIALLY IMPROVED

**Status**: PARTIALLY IMPROVED (fallback removal cleaned some code)  
**What changed** (commits `c6f9958`, `3460abb`):
- These commits removed "moderate fallback mechanisms" (M1-M18) and "silent click and input cascades"
- This aligns with Jesse's principle: "No special cases. No hardcoded screen types. No platform-specific logic in the flow."

**What remains**:
- `_try_focus_and_activate()` in `core/atspi_interact.py` — still present, still never called from any tool
- `compute_tree_hash()` in `core/tree.py` — still never called (would be useful for daemon state-change detection and replacing timing sleeps)
- `storage/models.py` — `ControlMap`, `Plan`, `SessionInfo`, `MonitorInfo` dataclasses still defined, still unused (all code uses raw dicts)
- Cannot confirm status of `_try_xdotool_safe()` and `_clipboard_write_xclip()` in smart_input.py since that file is unchanged — likely still present

---

### F10 — Error Propagation (LOW) → OPEN

**Status**: UNCHANGED  
**Evidence**:
- `tools/send_message.py` lines 297-301, 340-341: daemon spawn failure still proceeds to send; Enter failure still leaves typed text. Identical V1↔V2
- Redis unavailability mid-operation still leaves AT-SPI state mutated

---

## New Changes Not Mapped to V1 Findings

### N1: Lazy Screen Detection (commit `4a3a7dd`)

**File**: `core/platforms.py`  
**Change**: Added `_LazyScreenDim` class that defers `xdpyinfo` screen detection until first access. Raises `RuntimeError` on detection failure instead of silently defaulting.

**Assessment**: POSITIVE. This is a good defensive change. Previously, screen dimensions were computed at import time, which could fail if DISPLAY wasn't set yet (especially in MCP server context). Now detection is lazy and fails loudly, matching Jesse's "fail loudly" philosophy.

### N2: DISPLAY Environment for MCP Server (commit `4a3a7dd`)

**File**: `server.py` lines 28-33  
**Change**: Server now calls `detect_display()` and sets `os.environ['DISPLAY']` before importing any AT-SPI-dependent modules.

**Assessment**: POSITIVE. Fixes a real initialization ordering issue where AT-SPI modules could import before DISPLAY was set.

### N3: Dropdown Sidebar Hardening (commit `77f7b49`)

**File**: `core/tree.py:find_dropdown_menus()`  
**Change**: Added `_SIDEBAR_KEYWORDS` list and landmark-name filtering to skip sidebar/navigation subtrees when searching for dropdown menus.

**Assessment**: POSITIVE but was already present at V1 audit time. The sidebar keyword filtering prevents `find_dropdown_menus()` from returning permanent sidebar items (like Gemini's chat history) when looking for transient dropdown menus. This was in both V1 and V2 — the commit may have been part of pre-V1 development.

### N4: tree.py FROZEN Marker Restored (commit `673c08f`)

**File**: `core/tree.py` line 7  
**Change**: Re-added `FROZEN once working - do not modify without approval.` docstring line that was accidentally removed during a previous edit.

**Assessment**: Cosmetic/process discipline. No functional change.

### N5: Fallback Mechanism Removal (commits `c6f9958`, `3460abb`)

**Files**: Multiple (exact files modified unclear without pre-removal state)  
**Change**: Removed "moderate fallback mechanisms M1-M18" and "silent click and input cascades"

**Assessment**: POSITIVE for code cleanliness and alignment with Jesse's philosophy. Removes code paths that masked errors and made debugging harder. However, this means the system will fail more visibly and more often until the root causes (F1-F4) are addressed.

### N6: grab_focus Attempt + Revert (multiple commits, final: `2dd8065`)

**Files**: `tools/send_message.py` (reverted)  
**Change**: Attempted to use AT-SPI `grab_focus()` on entry elements instead of coordinate clicking for input focus. Found wrong element on Grok. Reverted to stored map coordinates.

**Assessment**: The right architectural direction but implementation hit a real platform compatibility issue. The revert is pragmatically correct — unreliable focus is worse than no focus. However, this means F4 (the most impactful reliability gap) remains open. A possible middle ground: use grab_focus with a verification step (after focus, check which element is focused, retry with coordinates if wrong).

---

## Summary Matrix

| Finding | V1 Severity | V2 Status | Key Blocker |
|---------|-------------|-----------|-------------|
| F1 — Clipboard contention | CRITICAL | OPEN | xclip/xsel still split, no mutex |
| F2 — Timing hardcodes | HIGH | OPEN | Zero sleep() calls changed |
| F3 — Daemon detection | HIGH | PARTIALLY IMPROVED | Name-length filter only; 4/5 sub-issues open |
| F4 — State desync | HIGH | OPEN (REVERTED) | grab_focus tried, failed on Grok, reverted |
| F5 — Duplicate code | MEDIUM | OPEN | Daemon still standalone |
| F6 — HMM triple-write | MEDIUM | OPEN | No changes |
| F7 — CLAUDE.md drift | MEDIUM | PARTIALLY IMPROVED | grab_focus claim now wrong again |
| F8 — Platform logic | MEDIUM | OPEN | No changes |
| F9 — Dead code | LOW | PARTIALLY IMPROVED | Fallback code removed |
| F10 — Error propagation | LOW | OPEN | No changes |

## New Issues

| ID | Description | Severity |
|----|-------------|----------|
| N6 | grab_focus revert means CLAUDE.md line 112 is actively misleading (was true, now false again) | MEDIUM |

---

## Recommended Next Steps (Unchanged Priority)

The V1 priority list remains the correct order. The most impactful fixes are:

1. **F1 — Clipboard**: Unify xclip/xsel. Pick xsel everywhere. This is a low-effort, high-impact change that fixes both attachment and extraction reliability.

2. **F4 — Input Focus**: The grab_focus revert needs a second approach. Options:
   - grab_focus with platform-specific entry detection (not generic "find any editable")  
   - grab_focus with post-focus verification (check focused element matches expected role/name)
   - Accept coordinate clicking but make map invalidation a hard gate (refuse to act if map is stale)

3. **F3 — Daemon Detection**: Add copy-button-count as a secondary signal alongside stop-button detection. This was the original detection strategy and would catch fast responses that complete before the daemon's first poll.

4. **F7 — CLAUDE.md**: Fix the grab_focus claim (line 112) immediately — it's actively misleading Claude Code's operational decisions.
