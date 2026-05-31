# Claude :3 — Git Connector + full input-area click path map
## 2026-05-31

**Scope:** map exact AT-SPI element names + roles for every clickable surface on Claude.ai's fresh-chat input area, all dropdowns and sub-elements, especially the Git Connector flow. Click + scan after each step. No name_contains. No fuzzy match.

## Step 0 — fresh new chat navigation

## Step 1 — initial state map (page already on claude.ai/new with leftover dispatch chip + rate-limit banner)

Exhaustive AT-SPI scan of document subtree (interactive roles only). All names verbatim, all roles verbatim.

### Sidebar (left rail):
| role | name | extents |
|------|------|---------|
| push button | `Open sidebar` | (19,98,24x24) |
| link | `New chat` | (13,146,32x32) |
| link | `Chats` | (13,180,32x32) |
| link | `Projects` | (13,213,32x32) |
| link | `Artifacts` | (13,246,32x32) |
| link | `Customize` | (13,279,32x32) |
| link | `Code` | (13,355,32x32) |
| link | `Design` | (13,388,32x32) |
| link | `Get apps and extensions` | (13,978,32x32) |
| push button | `Jesse LaRose, Settings` | (5,1019,48x48) |

**Note:** sidebar has no standalone "Connectors" link. Connector flow must be reached via the input-bar "+" button.

### Top-right:
| role | name |
|------|------|
| link | `Home` (hidden — showing=False) |
| push button | `Use incognito` |
| push button | `Close` (rate-limit banner X) |

### Input bar — load-bearing for dispatch + connectors:
| role | name | extents | purpose |
|------|------|---------|---------|
| entry | `Write your prompt to Claude` | (669,604,638x246) | prompt input |
| push button | `Add files, connectors, and more` | (665,862,32x32) | "+" entry — opens connector/file flyout |
| push button | `Model: Opus 4.8 High` | (1098,862,129x32) | model picker |
| push button | `Press and hold to record` | (1235,862,32x32) | mic |
| push button | `Send message` | (1275,862,32x32) | submit |

### Currently attached (from earlier dispatch, will clear when "New chat" link clicked):
| role | name |
|------|------|
| push button | `taey_package_claude_1780193929.md MD` (chip) |
| push button | `Remove` (chip x) |

## Step 2 — click "Add files, connectors, and more" button (the "+" on input bar)


After click: flyout menu opens. 12 items, scanned at app-root scope (React portal).

| role | name | extents |
|------|------|---------|
| menu item | `Add files or photos Ctrl+U` | (669,516,237x32) |
| menu item | `Take a screenshot` | (669,548,237x32) |
| menu item | `Add to project` | (669,580,237x32) |
| menu item | **`Add from GitHub`** | (669,612,237x32) |
| menu item | `Skills` | (669,653,237x32) |
| menu item | `Connectors` | (669,685,237x32) |
| menu item | `Add plugins...` | (669,717,237x32) |
| check menu item | `Research` | (669,758,237x32) |
| check menu item | `Web search` | (669,790,237x32) |
| menu item | `Use style` | (669,822,237x32) |

Two distinct paths to GitHub:
- `Add from GitHub` — per-message single-repo attach (likely the target for `--git-repo`)
- `Connectors` — opens management page; for installing/managing the GitHub connector

NOTE: `Research` and `Web search` have role `check menu item`, not `menu item` — toggleable. If a YAML uses `menu item` for these, it's wrong shape.

## Step 3 — click `Add from GitHub`


After clicking `Add from GitHub`: modal dialog opens (rendered at document depth 8, role `dialog`).

| role | name | extents |
|------|------|---------|
| dialog | `Try Claude Code for GitHub` | (576,466,768x233) |
| heading | `Try Claude Code for GitHub` | (601,493,686x28) |
| link | `Learn more about Claude Code` | (721,592,205x18) |
| push button | **`Continue to GitHub sync`** | (971,638,198x36) — canonical Git Connector path |
| push button | `Try Claude Code` | (1177,638,142x36) — DIFFERENT product, DO NOT CLICK on connector flow |

(Plus a Close X button at top-right of dialog — confirmed visually, will name when re-scanned without filter.)

**Note for YAML driver:** The connector dispatch flow must click `Continue to GitHub sync`, never `Try Claude Code`. A `name_contains: "Claude"` match here would catch the wrong button — exact name required.

**Note for AT-SPI scan helper:** Initial filter list `('push button','toggle button','link','combo box','radio menu item','menu item','menu','radio button','check box','tab','text','entry')` MISSED the `dialog` and `heading` roles. The dialog scan must include `('dialog','heading','section','label')` to catch modal content. Pattern recurs across platforms — fold into scan utility.

## Step 4 — click `Continue to GitHub sync`


After clicking `Continue to GitHub sync`: dialog transitions to GitHub repo picker.

### Dialog `Add content from GitHub` (role `dialog`, depth 8, extents 576,224,768x718)

Full subtree walk (no role filter, scoped to dialog only):

| role | name | extents | notes |
|------|------|---------|-------|
| dialog | `Add content from GitHub` | (576,224,768x718) | root |
| heading | `Add content from GitHub` | (601,251,686x28) | title |
| push button | `Close` | (1295,249,32x32) | top-right X — collides with rate-limit banner Close; must scope by parent dialog |
| image | _(empty name)_ | (618,336,18x18) | GitHub octocat icon (visual only) |
| **combo box** | _(empty name)_ | (644,330,164x30) | "Select a repository" — visible label is purely visual; **AT-SPI name is empty** |
| push button | `Paste GitHub URL` | (818,329,32x32) | chain-link icon — alt path: paste URL directly |
| image | _(empty name)_ | (826,337,16x16) | chain icon inside the button |

**CRITICAL YAML EXCEPTION:**

The repo-picker combo box has an empty accessible name. This breaks the "exact name + role" rule unless we add a structured lookup convention:

- WRONG: `name_contains: "Select"` (forbidden by THE RULE)
- WRONG: `name: ""` (matches any nameless element)
- RIGHT: **Scoped lookup** — find ancestor `{name: "Add content from GitHub", role: dialog}`, then within that scope find the single `combo box`. This is structured tree navigation, not fuzzy matching.

This YAML pattern needs to exist:
```yaml
repo_picker_combo:
  scope:
    name: "Add content from GitHub"
    role: dialog
  role: combo box
  index: 0    # single combo box in dialog
```

Or equivalently the driver does the parent-search at runtime. Either way, the YAML names the EXACT parent dialog and the EXACT role of the child being targeted — no string fuzziness.

`Close` button inside this dialog has same name as the rate-limit banner `Close` button — also requires scoped lookup.

**Two valid attach paths:**
- Path A (connected repos): click the empty-name `combo box` → dropdown of available repos appears → click target repo (need to map this state too)
- Path B (paste URL): click `push button` `Paste GitHub URL` → URL entry field appears → paste → fetch

For `--git-repo https://github.com/X/Y` from CLI, **Path B** is cleaner because it doesn't depend on the repo being preconnected. Will map both.

## Step 5 — click the (empty-name) repo picker combo box to expose dropdown contents


After clicking `Paste GitHub URL`: combo box swaps to URL entry field, `Paste GitHub URL` button swaps to `Cancel` X.

| role | name | extents | notes |
|------|------|---------|-------|
| dialog | `Add content from GitHub` | (576,224,768x718) | unchanged |
| heading | `Add content from GitHub` | (601,251,686x28) | unchanged |
| push button | `Close` | (1295,249,32x32) | top-right X, unchanged |
| image | _(empty)_ | (618,336,18x18) | octocat icon, unchanged |
| entry | **`Paste GitHub URL`** | (659,335,238x20) | URL input — placeholder text IS the accessible name (exact match works) |
| push button | `Cancel` | (908,329,32x32) | revert to combo box |

**Good shape note:** The URL entry's accessible `name` is the placeholder text. Exact-match YAML works here without scoped lookup.

## Step 6 — paste a real URL into the entry + submit


After typing URL into entry: a `Submit URL` button appears INSIDE the entry (child of entry, not sibling).

| role | name | extents | parent |
|------|------|---------|--------|
| entry | `Paste GitHub URL` | (659,335,210x20) | dialog |
| push button | **`Submit URL`** | (873,333,24x24) | **entry** (depth-nested) |
| push button | `Cancel` | (908,329,32x32) | dialog (sibling of entry) |

**Tree depth note:** Submit button is a CHILD of the entry, not a sibling. Exact tree position matters — flat name lookup is unique here (no other "Submit URL" in tree) but the nesting is structural.


## Step 7 — LABELLED_BY verification on empty-name combo box

Per Perplexity DR (full response: /tmp/claude_yaml_shape_pplx_response.md, citations to Playwright + AT-SPI2 spec + dogtail + freedesktop.org), the AT-SPI-native answer for an empty-name element is the `ATSPI_RELATION_LABELLED_BY` relation pointing to its visual label. Tested on the live combo box:

```python
combo = find_combo_box_in_dialog("Add content from GitHub")
combo.get_name()           # ""
combo.get_description()    # ""
combo.get_relation_set()   # []   ← NO LABELLED_BY relation
combo.get_attributes()     # {}   ← no aria-labelledby exposed
```

**Result:** Firefox/Claude.ai does NOT bind `aria-labelledby` for this element. The `labelled_by` strategy is unavailable here. Must use `scoped_index` fallback.

This is exactly Perplexity's open question #4: "Whether Firefox exposes LABELLED_BY via AT-SPI for Gecko-rendered web content vs native GTK widgets... depends on whether Claude.ai's DOM uses aria-labelledby or a purely visual label." Empirical answer: not bound.

## Proposed YAML shape (synthesis)

```yaml
element_map:
  # Existing exact-match (unchanged — most elements work here)
  add_files_trigger:
    name: "Add files, connectors, and more"
    role: push button
  add_from_github_item:
    name: "Add from GitHub"
    role: menu item
  try_code_for_github_dialog:
    name: "Try Claude Code for GitHub"
    role: dialog
  continue_to_github_sync_btn:
    name: "Continue to GitHub sync"
    role: push button
  add_content_from_github_dialog:
    name: "Add content from GitHub"
    role: dialog
  paste_github_url_btn:
    name: "Paste GitHub URL"
    role: push button
  paste_github_url_entry:
    name: "Paste GitHub URL"
    role: entry
  submit_url_btn:
    name: "Submit URL"
    role: push button
  cancel_url_btn:
    name: "Cancel"
    role: push button
    scope:
      name: "Add content from GitHub"
      role: dialog
    lookup_strategy: scoped

  # The empty-name combo box (scoped + index fallback)
  repo_picker_combo:
    lookup_strategy: scoped_index
    scope:
      name: "Add content from GitHub"
      role: dialog
    role: combo box
    index: 0

  # The dialog-scoped Close X (name collides with banner Close)
  github_dialog_close:
    lookup_strategy: scoped
    scope:
      name: "Add content from GitHub"
      role: dialog
    name: "Close"
    role: push button
```

### Lookup strategy hierarchy in driver:
1. **(absent / default)**: flat exact `name + role` — fastest, used when name is unique
2. **`scoped`**: find ancestor by exact `scope: {name, role}`, then find exact `name + role` child within it
3. **`labelled_by`**: find element where `LABELLED_BY` relation target's name matches `label_name` — preferred for empty-name when web app binds aria-labelledby (does NOT work here for Claude.ai combo box)
4. **`scoped_index`**: find ancestor, collect all children matching `role`, return `index`th — last resort; fragile to dialog reorder but currently exact (Claude combo box has unique role in dialog)

### Connector dispatch workflow (--git-repo URL path):

```yaml
workflow:
  git_connector_paste_url:
    steps:
      - click: add_files_trigger
        wait: 0.5
      - click: add_from_github_item
        wait: 2.0
      - click: continue_to_github_sync_btn
        wait: 2.0
        verify_appeared: add_content_from_github_dialog
      - click: paste_github_url_btn
        wait: 0.5
        verify_appeared: paste_github_url_entry
      - focus_and_type: paste_github_url_entry
        text: "${git_repo_url}"
      - click: submit_url_btn
        wait: 5.0
      # next: map file picker state after fetch completes
```


## Git history check + REVISED proposal

Read commit `e8121e2 feat(connectors): map + YAML for GitHub connector cycle step` (the "working" prior connector commit). Schema there is the SAME flat shape as today, just with `name_contains`/`role_contains` allowed. Subsequent commit `8cd8ee5 fix: exact match YAMLs + strip all fallback logic from drivers` was supposed to remove fuzzy matchers but the cleanup never finished — current YAML still has `name_contains` on `toggle_menu`, `upload_files_item`, `copy_button`, `prompt_tab`, `incognito`. Commit `675fc1d fix: copy_button name_contains` is a prior Claude session that REVERTED the rule with the justification "buttons have variable names: Copy, Copy response, Copy message" — exactly the kind of shortcut Jesse keeps catching.

### The legitimate exact-match shapes (per resolver code in tools/inspect._match_element)

The resolver supports six matching keys. Three are legitimate, three are forbidden:

| key | legitimate? | meaning |
|-----|-------------|---------|
| `name: "exact string"` | ✓ | case-insensitive equality |
| `names_any_of: ["exact A", "exact B"]` | ✓ | matches if name equals any string in list (used for stateful labels like Copy variants) |
| `role: "push button"` | ✓ | exact role equality |
| `name_contains: "fragment"` | ✗ FORBIDDEN | substring — fuzzy |
| `name_pattern: "Model: *"` | ✗ FORBIDDEN | fnmatch glob — fuzzy |
| `role_contains: "item"` | ✗ FORBIDDEN | substring on role |

### No schema invention needed

The Perplexity-DR-proposed `lookup_strategy` enum was overkill for the actual problem. The resolver already has `name` + `names_any_of` for exact match. The right fix is:
1. Replace every `name_contains` with either single-exact `name` or `names_any_of`
2. Replace every `role_contains: item` with `role: "menu item"` (or `radio menu item`, exact)
3. Replace every `name_pattern: "Model: *"` with `names_any_of:` listing every model selector label variant we've observed

For the dispatch-critical connector workflow (Path B / paste URL), every element has a globally unique exact name. No `scope:` field needed at all for the happy path. Scoped lookup is a real but separate problem for the empty-name combo box and dialog Close collision — those are out of scope for `--git-repo` dispatch and can be addressed later if Path A (repo list) is ever wired up.

### Proposed claude.yaml diff (subset — connector + cleanup of forbidden matchers)

```yaml
element_map:
  # ── Input area ─────────────────────────────────────────────
  input:
    name: "Write your prompt to Claude"
    role: entry
    states_include: [editable]

  # Was: name_contains: ["Add files", "Toggle menu"]
  # Now: exact, current UI label
  toggle_menu:
    name: "Add files, connectors, and more"
    role: push button

  # ── "+" flyout menu items ──────────────────────────────────
  # Was: name_contains + role_contains
  upload_files_item:
    name: "Add files or photos Ctrl+U"
    role: menu item

  # Was: role_contains: item
  git_connector_item:
    name: "Add from GitHub"
    role: menu item

  # ── GitHub connector flow (NEW: full Path B mapped 2026-05-31) ──
  try_code_for_github_dialog:
    name: "Try Claude Code for GitHub"
    role: dialog
  github_continue_sync:
    name: "Continue to GitHub sync"
    role: push button
  github_add_content_dialog:
    name: "Add content from GitHub"
    role: dialog
  github_paste_url_btn:
    name: "Paste GitHub URL"
    role: push button
  github_paste_url_entry:
    name: "Paste GitHub URL"
    role: entry
  github_submit_url:
    name: "Submit URL"
    role: push button
  github_cancel_url:
    name: "Cancel"
    role: push button

  # ── Model selector ────────────────────────────────────────
  # Was: name_pattern: "Model: *"
  # Now: exact list of observed stateful labels
  model_selector:
    names_any_of:
      - "Model: Opus 4.8 High"
      - "Model: Opus 4.8 Extra"
      - "Model: Sonnet 4.6"
      - "Model: Haiku 4.5"
    role: push button
  model_opus:
    name: "Opus 4.8 Most capable for ambitious work"
    role: radio menu item
  model_sonnet:
    name: "Sonnet 4.6 Most efficient for everyday tasks"
    role: radio menu item
  model_haiku:
    name: "Haiku 4.5 Fastest for quick answers"
    role: radio menu item

  # ── Stateful labels (Copy variants, banner Close) ─────────
  # Was: name_contains: "Copy" + role_contains: button
  copy_button:
    names_any_of: ["Copy response", "Copy message", "Copy"]
    role: push button

  stop_button:
    name: "Stop response"
    role: push button

  # ── Sidebar/nav (cleanup of forbidden matchers) ───────────
  open_sidebar:
    name: "Open sidebar"
    role: push button
  incognito:
    name: "Use incognito"
    role: push button
  send_button:
    name: "Send message"
    role: push button

  # Was: name_contains list
  prompt_categories:
    name: "Prompt categories"
    role: page tab list
  # Removed prompt_tab entirely — name_contains on a tab list is fuzzy.
  # If a specific tab is needed, add named entries: prompt_tab_write, prompt_tab_learn, etc.
```

### Workflow addition

```yaml
workflow:
  attachment:
    keyboard_shortcut: ctrl+u    # unchanged — fastest path for local files

  git_connector_url:
    description: "Attach a GitHub repo to the current chat via the Paste-URL path"
    steps:
      - click: toggle_menu
        wait: 0.5
      - click: git_connector_item
        wait: 2.0
        verify_appeared: try_code_for_github_dialog
      - click: github_continue_sync
        wait: 2.0
        verify_appeared: github_add_content_dialog
      - click: github_paste_url_btn
        wait: 0.5
        verify_appeared: github_paste_url_entry
      - focus_and_type: github_paste_url_entry
        text: "${git_repo_url}"
      - click: github_submit_url
        wait: 5.0
        # Next: file picker state mapping (deferred until clicked live)
```

### What this fixes / what's still pending

**Fixed by this diff:**
- All `name_contains`, `name_pattern`, `role_contains` removed from claude.yaml
- Connector dispatch path is fully exact-match
- Stateful labels (Copy variants, Model: variants) use the right primitive (`names_any_of` — listed exact alternatives, not fragments)

**Still pending (out of scope for `--git-repo`):**
- Empty-name combo box (Path A — repo list selection) — needs scope+index if/when wired
- Dialog Close vs banner Close collision — needs scope if/when dialog cleanup is added
- File picker state after `Submit URL` fires (next click I haven't mapped yet)
- Same cleanup needs to run on chatgpt.yaml, gemini.yaml, grok.yaml, perplexity.yaml


## Step 7 — Submit URL → file picker → root select → Add files

After typing URL + clicking `Submit URL`: dialog populates with repo file/folder tree.

### Repo-loaded state (push buttons in dialog scope):
| role | name | extents | notes |
|------|------|---------|-------|
| push button | `Close` | (1295,249,32x32) | dialog close X |
| push button | `Paste GitHub URL` | (984,329,32x32) | URL paste icon — now smaller (re-trigger URL change) |
| push button | `Search files` | (1018,329,32x32) | magnify icon — search within repo files |
| push button | `Add files` | (1211,327,91x36) | **NOT VISIBLE until ≥1 file is selected** — final submit |

### File tree row pattern:
Every row has the same accessible-name shape — **labels are not unique, only the visible text differs**:

```
label: "Select directory"   ← root repo container only
  check box: "Select directory" (1x1 hidden)
    label: "Select item"     ← per-file/folder
      check box: "Select item" (1x1 hidden)
    image: "" (folder/file icon)
```

The visible filenames (`docs`, `lib`, `README.md`, etc.) are NOT in the AT-SPI tree at all — they're rendered as raw text outside the focus path. So **selecting a specific file by name requires OCR or screenshot — not possible via AT-SPI alone.**

Two practical consequences:
1. **Full-repo attach** (only `--git-repo URL`, all-or-nothing) is trivial: click root `Select directory` once → all files cascade-selected → click `Add files` button.
2. **Per-file selection** would require an OCR pass over the visible text column, then computing y-offset and clicking the corresponding row's `Select item` checkbox. Out of scope.

### Clicking root `Select directory`

After clicking the root `Select directory` checkbox: 31 files marked. Footer changes from `Select files to add to chat context` to `31 files selected | 23% of capacity used`. The `Add files` push button appears (extents 1211,327,91x36).

### Jesse operational guidance (2026-05-31)

For Claude `--git-repo` dispatch: **default is click the TOP `Select directory` checkbox to select everything** — Claude does NOT search the attached repo, it ingests directly, so all files need to be attached. Per-row selection is override-only (specific directory requested, or capacity exceeded). Capacity is a hard ceiling — the footer reports `N% of capacity used` after root-select; if >100%, the attach will fail and the dispatch needs to either narrow to a subdirectory or chunk across multiple repos.

**Practical handling for Claude driver:**
1. Click root `Select directory` checkbox.
2. Scan dialog for footer text matching `% of capacity used` — if number ≥ 100 (or no `Add files` button appears within timeout), fail loud with capacity-exceeded error (do NOT silently proceed with partial selection).
3. Click `Add files` to commit.

### Per-row file selection (override only — out of standard path)

The 31 per-row "Select item" checkboxes share the same accessible name. The visible filenames render in inline `[section]` elements at `(670, Y, 520x24)` extents per row — verified by full no-filter walk of the dialog: name, description, and queryText() are all empty on those sections. Filenames are NOT exposed via AT-SPI text properties in the current Firefox/Claude.ai build (web-content accessibility bridge gap). **For override selection, the only AT-SPI-driven path is by row y-extent**: walk all `(617, Y, 1x1)` `check box: "Select item"` entries sorted by y, with the row ordering matching the visible alphabetical sort. Selecting "the 3rd row" works; selecting "lib/" by name does not (would require OCR or DOM bridge). This is acceptable per Jesse — the standard path is select-all, override is rare.

## FULL Path B click sequence — exact names, exact roles, no fuzzy

1. `push button: "Add files, connectors, and more"` (input bar "+")
2. `menu item: "Add from GitHub"` (flyout)
3. `push button: "Continue to GitHub sync"` (modal "Try Claude Code for GitHub")
4. `push button: "Paste GitHub URL"` (modal "Add content from GitHub")
5. `entry: "Paste GitHub URL"` — focus + xdotool type the URL
6. `push button: "Submit URL"` — submit, wait for fetch (~5s for small repos)
7. `check box: "Select directory"` (root row only — labels and checkboxes share the name across rows; root is the FIRST one rendered, distinguished by having no parent `Select item` ancestor)
8. `push button: "Add files"` — final submit, attaches repo to chat context

### Updated element_map additions for the full path:

```yaml
github_search_btn:
  name: "Search files"
  role: push button
github_root_select:
  name: "Select directory"
  role: check box
github_add_files:
  name: "Add files"
  role: push button
```

