# Git Connector Discovery — live AT-SPI flows (2026-05-22)

Goal: make "connect a GitHub repo" a reusable consultation-cycle step on all 5 platforms.
Split (per Jesse): taeys-hands does live discovery + YAML; driver `.py` (connect_repo step) → Conductor per 6SIGMA.

Reference impl: `consultation_v2/drivers/perplexity.py::toggle_connectors()` (only platform wired today).

---

## Claude (:3) — VERIFIED 2026-05-22  (GitHub auth ALREADY connected on profile)

Flow (entry → repo selection):
1. Composer **`+`** button → opens menu `Add files, connectors, and more`.
2. Menu item **`Add from GitHub`** (role: `menu item`).  ✓ matches YAML `git_connector_item`.
3. Interstitial modal **"Try Claude Code for GitHub"** → push button **`Continue to GitHub sync`**
   (the other button `Try Claude Code` is the wrong path — opens Claude Code web).  **[NEW — not in YAML/driver]**
4. Modal **"Add content from GitHub"** ("Select the files you would like to add to this chat"):
   - repo dropdown — displayed text `Select a repository` (AT-SPI: `combo box`, empty name).
   - push button **`Paste GitHub URL`** (alt path: paste a repo URL directly).
   - file tree appears after repo chosen; footer meter `N% of capacity used`; "Select files to add to chat context".

Also-observed menu drift to fix in YAML:
- `add_connectors`: YAML name `"Add connectors"` → live is **`Connectors`** (drift).
- upload item live name is `Add files or photos Ctrl+U` (verify against YAML `upload_files_item`).

Driver step needed (claude.py): after attach/mode, if `request.connectors` includes a github repo →
click `+` → `Add from GitHub` → `Continue to GitHub sync` → repo combo (type/select repo OR `Paste GitHub URL`) →
select files → confirm. Verify via repo chip / capacity meter > 0%.

---

## Grok (:5) — VERIFIED 2026-05-22  (GitHub connector already configured on profile)

Flow:
1. Composer **`Attach`** push button (40x40, bottom-left) — open via COORDINATE click (React portal; `do_action(0)` does NOT open it).
2. Menu items: `Upload a file`, `Connectors`. Click **`Connectors`** (menu item, coordinate click).
3. Submenu: `Upload a file`, `Recent`, `Skills`, `Connectors`, **`GitHub`** (role: `check menu item` — TOGGLE), `Add connector`.
4. Click **`GitHub`** to toggle the connector ON. Verify via `checked` state on the check menu item.

Pattern = Perplexity-style toggle. Straightforward. NOTE: this toggles GitHub as a *source*; scoping a
specific repo (if supported) is a follow-on not yet mapped — for cycle use, toggling the connector + naming
the repo in the prompt is the minimum. `Add connector` is the one-time auth/setup path (already done here).

---

## Gemini (:4) — VERIFIED 2026-05-22  ❌ NO GITHUB CONNECTOR

`Upload & tools` push button → menu = {`Upload files. Documents, data, code files`,
`Add from Drive. Sheets, Docs, Slides`, `Create image`, `Create video`, `Canvas`,
`Deep research`, `Create music`}. Sources are file-upload + Google Drive ONLY.
**Gemini has no GitHub/repo connector and no generic "connectors" surface.**
=> For Gemini, "connect a repo" is not possible natively. Repo content reaches Gemini only via
FILE UPLOAD (e.g. a packed/zipped repo) — i.e. the existing `attach_files` path, not a connector.
No driver/YAML connector work applies to Gemini. (Contradicts the "all platforms" assumption — flag to Jesse.)

---

## ChatGPT (:2) — VERIFIED 2026-05-22  (GitHub authed; per-repo INDEXING required)

Flow (all React portals → COORDINATE clicks, not do_action):
1. Composer **`Add files and more`** push button.
2. Menu: `Add photos & files Control U`, `Recent files`, `Create image`, `Deep research`, `Web search`, **`More`**.
3. Hover/click **`More`** → submenu adds: `Agent mode`, `Create task`, `Finances`, **`GitHub`** (role `radio menu item`), `Gmail`, `OpenAI Platform`.
4. Click **`GitHub`** → activates the tool: composer shows chip `GitHub, click to remove` (push button) + a `GitHub` push button (the repo selector).
5. Click the `GitHub` push button → repo dropdown:
   - `Search repositories…` (menu item — type to filter)
   - repo menu items `palios-taey/<repo>` (e.g. `palios-taey/taeys-hands`, `palios-taey/embedding-server`).
   - **INDEXING SIGNAL: un-indexed repos have a trailing ` Not indexed` in the menu-item NAME**
     (e.g. `palios-taey/taeys-hands-v2 Not indexed`). Indexed repos have no suffix. Driver MUST detect this:
     indexed → select directly; ` Not indexed` → must index first (slow, async) via `Configure Repositories`.
   - `Configure Repositories` (menu item) = manage/add/index repos (one-time, minutes per repo).
6. Select an INDEXED `palios-taey/<repo>` menu item to scope it. `palios-taey/taeys-hands` IS indexed/ready.

YAML drift to fix: chatgpt.yaml `tool_github` role → `radio menu item`; menu also now has `Finances`,
`Create task`, `OpenAI Platform` (new); `Quizzes`/`GitHub`(old item) — re-baseline `tool_*` submenu list.
`tool_upload` live name = `Add photos & files Control U`.

---

## Perplexity (:6) — driver-wired (toggle_connectors), re-verify live names

`drivers/perplexity.py::toggle_connectors()` already implements: attach_trigger → `git_connector_item`
(YAML name `Connectors and sources`) → search_sources → type connector → toggle → re-verify checked.
Re-verify the live element names match (deferred — Perplexity busy on other work).

---

## SUMMARY — GitHub connector availability
| Platform | GitHub connector? | Mechanism | Difficulty |
|---|---|---|---|
| Claude | YES (authed) | +menu → Add from GitHub → Continue to GitHub sync → repo combo / Paste URL → pick files | few clicks + 1 new modal step |
| Grok | YES (authed) | Attach → Connectors → GitHub (check toggle) | simple toggle (coord clicks) |
| ChatGPT | YES (authed) | Add files and more → More → GitHub → repo dropdown; per-repo INDEXING (` Not indexed` flag) | HARD (indexing, React portals) |
| Perplexity | YES (driver done) | toggle_connectors (Connectors and sources) | already implemented |
| Gemini | **NO** | only Upload files + Add from Drive — no GitHub surface | N/A — use file upload (packed repo) |
