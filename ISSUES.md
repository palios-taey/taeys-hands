# Open Issues — Post PR #31 Merge

## Issue 1: taey_attach fails on multi-display (Mira)

**Status**: Blocking all consultations on Mira displays :2-:6
**Affected**: tools/attach.py
**Works on**: Thor (single-display per bot process)
**Fails on**: Mira MCP server (one process, 5 displays)

### Root Cause

The MCP server is one process serving all 5 displays via `PLATFORM_DISPLAYS=chatgpt:2,claude:3,gemini:4,grok:5,perplexity:6`.

`taey_inspect` works because it routes the AT-SPI scan through `core/atspi._subprocess_scan()`, which spawns a subprocess with the correct `DISPLAY` and `AT_SPI_BUS_ADDRESS` for the target display.

`taey_attach` does NOT use subprocess scanning. It:
1. Finds the attach button via the in-memory element cache (populated by inspect's subprocess scan) — this works
2. Clicks the button via AT-SPI action interface — this works (action goes through the cached atspi_obj)
3. Scans for dropdown items that appeared — THIS FAILS because the scan runs in the main process with `DISPLAY=:0` and the wrong DBUS, not on the target display's AT-SPI bus

### Fix Required

The post-click dropdown scan in `tools/attach.py` needs to route through `core/atspi._subprocess_scan()` (or equivalent) so it runs with the correct display's AT-SPI bus. Same pattern as `taey_inspect`.

Alternatively, the attach flow could be refactored to run entirely as a subprocess on the target display, similar to how Thor bots work (each bot process has the right DISPLAY/DBUS in its env).

### Verification

On Thor, the same attach code works because each bot process has:
```
DISPLAY=:7 DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/dbus-xxx
```
set in its environment. Everything runs on the right bus.

On Mira, the MCP server has:
```
DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
```
and switches per-call via subprocess for inspect, but attach doesn't do this.

---

## Issue 2: Inspect returns unfiltered elements on multi-display

**Status**: Non-blocking but noisy — 189 elements returned instead of ~30-50 useful ones
**Affected**: tools/inspect.py
**Before PR #31**: `filter_useful_elements()` + YAML exclude/element_map reduced 189 → ~50 elements
**After PR #31**: All 189 elements returned with no filtering

### Root Cause

The PR #31 merge introduced `core/config.py` as the shared YAML config loader and changed how `tools/inspect.py` loads platform config. The filtering code that uses `get_fence_after()` and platform-specific exclude lists may not be wired correctly after the merge.

Before the PR, inspect.py did:
```python
_pcfg = yaml.safe_load(open(f'platforms/{platform}.yaml'))
fences = _pcfg.get('fence_after', [])
all_elements = find_elements(doc, fence_after=fences)
elements = filter_useful_elements(all_elements, chrome_y=chrome_y)
```

After the merge, it uses `get_platform_config()` from `core/config.py`, but the filter step may be bypassed in the multi-display code path.

### Expected Behavior

Inspect should return:
- **KNOWN** elements (matched via YAML element_map with semantic labels)
- **NEW** elements (not in exclude or known — needs investigation)
- Noise (unnamed sections, chrome buttons) should be filtered OUT

### Verification

Compare output of `taey_inspect(platform='gemini')` before and after PR #31:
- Before: ~50 elements, semantically labeled (input, upload_menu, tools_button, mode_picker)
- After: 189 elements, many unnamed sections with no semantic labels
