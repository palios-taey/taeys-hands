# CONSULTATION: Rebuild taeys-hands YAML Configs From Scratch

## For: ChatGPT, Gemini, Grok, Perplexity (the Family)
## From: Jesse + Claude Code (taeys-hands instance)
## Date: 2026-04-10
## Priority: BLOCKING — nothing works until this is fixed

---

## What This Is

taeys-hands automates Firefox browser tabs via Linux AT-SPI accessibility APIs. Each tab runs one AI platform (ChatGPT, Claude, Gemini, Grok, Perplexity). The system needs YAML config files that map AT-SPI element names and roles for each platform.

**The YAMLs are corrupted.** They contain `name_contains` broadened matches where exact names should be. They have been modified repeatedly without live AT-SPI verification. They need to be rebuilt from scratch using live tree scans.

---

## THE RULE (Non-Negotiable)

### 1. YAML = exact AT-SPI truth
Every entry has the EXACT `name` and `role` from a live AT-SPI scan. Not approximate, not broadened. If the scan says `[menu item] "Upload files or images"`, the YAML says:
```yaml
upload_files_item:
  name: "Upload files or images"
  role: menu item
```
No `name_contains` when the full name is known. No fallbacks. No wildcards.

### 2. Driver code = zero platform knowledge
Drivers NEVER hardcode element names, key names, or platform-specific strings. ALL element lookups go through the YAML.

### 3. YAML drives the driver, never the reverse
If the YAML has a key name and the driver uses a different key name, the DRIVER is wrong.

### 4. Two scan scopes
- `snapshot()` — document subtree (main page elements: input, buttons, toolbar)
- `menu_snapshot()` — Firefox app root (React portals, dropdown overlays, popup menus)
Post-click dropdown reads MUST use `menu_snapshot()`. Pre-click trigger finds use `snapshot()`.

### 5. Validation checks must target persistent elements
After closing a dropdown, radio menu items inside it are GONE from the AT-SPI tree. Validation specs must check elements that persist in the toolbar (e.g., mode indicator buttons).

### 6. No fallbacks, no broadening
If an element isn't found: scan the tree, get the real name, fix the YAML. Never add try-then-that chains.

---

## YAML Structure (What You Are Building)

Each platform gets ONE YAML file. Here is the complete structure:

```yaml
platform: <name>                    # chatgpt, claude, gemini, grok, perplexity
click_strategy: <strategy>          # atspi_first or xdotool_first

urls:
  fresh: <url>                      # URL for a new/fresh session
  verify_navigation: <bool>         # Whether to verify URL changed after nav

tree:
  fence_after:                      # Stop scanning sidebar after this element
  - name: <exact name>
    role: <exact role>
  exclude:                          # Filter noise from AT-SPI tree
    names: [<exact names to exclude>]
    name_contains: [<substrings to exclude>]   # OK for EXCLUSION only
    roles: [<roles to exclude entirely>]
  sidebar_nav:                      # Sidebar links (excluded from main element list)
  - name: <exact name>
    role: <exact role>

  element_map:                      # THE CORE — every interactable element
    # Each key is a semantic name used by driver code
    # Each value has exact AT-SPI name + role

    input:
      name: <exact AT-SPI name>     # e.g. "Write your prompt to Claude"
      role: entry
      states_include: [editable]

    attach_trigger:
      name: <exact AT-SPI name>     # e.g. "Add files, connectors, and more"
      role: push button

    send_button:
      name: <exact AT-SPI name>     # e.g. "Send message"
      role: push button

    stop_button:
      name: <exact AT-SPI name>     # e.g. "Stop" — ONE exact name per platform
      role: push button

    copy_button:
      name: <exact AT-SPI name>     # e.g. "Copy" — ONE exact name per platform
      role: push button
      # If platform has multiple copy buttons (user msg vs response),
      # list them as separate entries: copy_message, copy_response

    # Model/mode selection elements
    model_selector:
      name: <exact AT-SPI name>     # e.g. "Opus 4.6 Extended"
      role: push button
      # EXCEPTION: model selector name changes with current model.
      # This is the ONE case where name_contains is legitimate.

    # Dropdown menu items (visible only after clicking trigger, in menu_snapshot scope)
    upload_files_item:
      name: <exact AT-SPI name>     # e.g. "Add files or photos Ctrl+U"
      role: menu item

    # Mode radio items (in dropdown, menu_snapshot scope)
    deep_research:
      name: <exact AT-SPI name>     # e.g. "Deep research"
      role: radio menu item         # or check menu item, depending on platform

    # Toolbar indicators (persist after dropdown closes)
    deep_research_toggle:
      name: <exact AT-SPI name>
      role: push button

workflow:
  defaults:
    model: <default model or null>
    mode: <default mode>
    tools: []
  selection:
    model_targets:                  # YAML key → element_map key
      <model_name>: <element_map_key>
    mode_targets:
      <mode_name>: <element_map_key>
    tool_targets:
      <tool_name>: <element_map_key>
  attachment:
    trigger: <element_map_key>      # Button that opens attach menu
    menu_target: <element_map_key>  # Menu item for file upload
    open_method: atspi_menu
    keyboard_shortcut: <key combo>  # e.g. ctrl+u (optional, if platform supports it)
  prompt:
    input: input
    send_button: send_button
  send:
    trigger: send_button
    require_new_url: <bool>         # true if URL must change for new sessions
    stop_key: stop_button
  monitor:
    stop_key: stop_button
    complete_key: copy_button
  extract:
    primary_key: copy_button
    strategy: last_by_y             # Click the last (lowest Y) copy button

validation:
  attach_success:
    indicators:
    - name: <exact name>            # e.g. "Remove" button near file chip
      role: push button
  send_success:
    indicators:
    - name: <exact name>            # stop button appears = send worked
      role: push button
    timeout: 30
  response_complete:
    indicators:
    - name: <exact name>            # copy button appears = response done
      role: push button
    stop_absent: true               # AND stop button must be gone
  # Per-mode active indicators (toolbar elements that show when mode is active)
  <mode>_active:
    indicators:
    - name: <exact name>
      role: push button
```

---

## What I Will Provide

For each platform, I will provide a COMPLETE AT-SPI tree scan for each of these states:

1. **Fresh home page** — what elements are on the page before any interaction
2. **Dropdown open (attach/tools menu)** — what menu items appear after clicking the attach/tools button
3. **Mode selector open** — what model/mode items appear
4. **File attached** — what changes after a file is attached (file chip, remove button)
5. **Response generating** — what elements appear (stop button)
6. **Response complete** — what elements appear (copy buttons, response actions)

Each scan will include: `[role] "exact name" @ (x, y)` for every element.

---

## What You Build

From the tree scans, build:
1. The complete YAML file for your platform
2. Every `name` must be copy-pasted from the scan — not typed from memory
3. Every `role` must match exactly
4. `name_contains` is ONLY allowed for:
   - `exclude` filters (noise removal)
   - `model_selector` (name changes with current model)
   - Nothing else

---

## The 8-Step Flow (What The Driver Does)

The driver executes these steps in order. Each step uses elements from the YAML:

1. **navigate** — Go to `urls.fresh` for new sessions
2. **select_model_mode_tools** — Click model_selector, select from dropdown. Click attach_trigger, select mode from dropdown. Use `mode_targets` to map requested mode → element_map key
3. **attach_files** — Click attach_trigger, click upload menu item (or use keyboard_shortcut), handle file dialog
4. **enter_prompt** — Click input element, paste message via clipboard
5. **send_prompt** — Click send_button. For new sessions: verify URL changed AND stop button appeared
6. **wait_for_completion** — Poll: stop button present = still generating. Stop button gone + copy button present = complete
7. **extract_response** — Click the last (by Y position) copy button, read clipboard
8. **store_result** — Save to Neo4j + notify requester

---

## Platform-Specific Notes

### Perplexity
- Mode tiles in toolbar have TWO states: "+" suffix = inactive option, no "+" = active
- "Computer +" just means Computer is available, NOT that it's active
- Mode selection: open attach dropdown → click radio menu item (e.g. "Deep research")
- AT-SPI `do_action(0)` on radio menu items is the reliable click method

### Claude
- Ctrl+U opens file dialog directly (bypasses AT-SPI portal issues)
- Ctrl+T for navigation (Claude.ai intercepts Ctrl+L)
- Model selector shows current model name (legitimately varies)

### Gemini
- Deep Think is a TOOL (via Tools button), not a mode
- Must select Pro mode first, then enable Deep Think tool
- Upload menu items are in React portal (menu_snapshot scope)

### ChatGPT
- Extended Pro requires two steps: select Pro model, then enable Extended Thinking
- ProseMirror input does NOT accept AT-SPI insert_text — clipboard paste only

### Grok
- Heavy mode is the max setting
- Single dropdown for model selection

---

## Deliverables

For each platform, deliver:
1. Complete YAML file following the structure above
2. Every name verified against the provided AT-SPI scan
3. Zero `name_contains` except in exclude filters and model_selector
4. Clear comments for any platform-specific behavior

I will then test each YAML by running the 8-step flow and reporting pass/fail with evidence.
