# PROVENANCE INVESTIGATION — why does "nothing work" when the mapping is complete? (2026-08-13)

**Directive (Jesse):** the whole consult is mapped — every step, every element — and it has worked. Yet
Taey's runtime path fails. Figure out WHY, with **full provenance on every claim** (file:line, commit SHA,
live observation). **No decisions/changes until the provenance root-cause is on record and coordinated.**

## The two things known to be TRUE (anchors, Observed)
- **The mapping + the proven primitives WORK.** 2026-08-13 I extracted a **29,929-char** Claude answer from
  `:3` using the consult_v2 driver primitives (`scroll_document_to_bottom` → full-depth `find_elements` →
  `_copy_button_candidates` → `atspi_click` → `read_clipboard`). sha256 7201c560. So the contract is intact.
- **Taey's runtime surface (`taey-presence/serving/ui_drive.py`, drive_chat) fails** where the proven path
  succeeds — e.g. its `observe` at `max_depth 30` returned **136 rows / 0 Copy**, vs the proven full-depth
  scan's **3687 elements / 1 Copy**.

## The hypothesis to CONFIRM or REFUTE (do not assume)
"Nothing works" because the **newer hand surface (`ui_drive`/`drive_chat`) reimplemented reads/acts/extracts
with wrong parameters instead of calling the mapped, proven `consult_v2` primitives." Known seeds (verify +
extend, each with a receipt):
1. `observe` caps depth (~30) → prunes deep elements (the Copy button lives below depth 30).
2. no document-scroll before an extract read (the Copy only enters the AT-SPI tree when on-screen).
3. substring `--filter` for control elements (the contract is **exact-only** — `snapshot.py:20-30`).
4. any other place `ui_drive` diverges from a mapped primitive/YAML contract.

## ALSO (honest self-check): did today's edits break anything?
Enumerate every change infra made in `taey-presence` and I made in `taeys-hands` **today** touching the
drive/extract/attach path (`git log` since 2026-08-13 00:00). For each: did it corrupt a YAML element map,
a primitive, or a contract? Provenance = the diff + a live check.

## ALSO AUDIT — Taey's LOGS + INSTRUCTIONS (Jesse: "no reason this shouldn't work with MINIMAL changes")
The map is complete + proven; so the fix must be small. Confirm that, and find where Taey is misdirected:
- **Taey's tool-audit LOG: `/home/mira/taey_tool_audit.jsonl`** (absolute). Trace the failed Claude leg on :3:
  which drive_chat calls Taey made, where each failed, and WHY it then bypassed to raw shell (xdotool ctrl+a/
  ctrl+c, F12 devtools, blind context-menu) at 18:44–18:53. Hypothesis to confirm: the bypass was CAUSED by
  the runtime gap (ui_drive couldn't surface the mapped Copy button, so Taey improvised). Cite the log lines.
- **Taey's INSTRUCTIONS: `/home/mira/taey-presence-production/serving/TAEY_OPERATING_PROMPT.md` +
  `serving/council_prompts/*.md`** (absolute). Does the instruction give Taey the CORRECT, COMPLETE procedure
  (scroll-to-bottom → deep observe → lowest Copy → clipboard), or is a step missing? Does it tell Taey to
  STOP + report a dead end, or does it leave room to "find another route" (which produced the raw-shell
  bypass)? Cite prompt file:line. (NOTE: fixing the instruction is infra's/Jesse's — you AUDIT it only.)

## RECEIPTS ALREADY IN HAND (build on these, do not re-derive)
- Extraction proven via the mapped path: 29,929 chars from :3, sha256 7201c560…, infra-confirmed. The ONLY
  difference from Taey's failing read: full-depth scan (3687 elements) vs ui_drive `max_depth 30` (136 rows) —
  the mapped Copy button was PRUNED, not renamed.
- substring `--filter` for control elements is contract-illegal (`consult_v2/snapshot.py:20-30`, exact-only).
- attach: root-caused to the XDG portal, fixed (profile pref, all displays restarted).
- grok (task-330f261c): mapping signatures/bodies intact vs act.py + v2 primitives.

## THE THESIS TO LAND (Jesse's): the fix is MINIMAL
Given the map is intact and the primitives work, name the SMALLEST change set that makes Taey's runtime match
the mapping — expected shape: (1) ui_drive gets a scroll action + an uncapped/deep observe (the 2 rungs);
(2) verify uses exact-match not substring; (3) one instruction correction. NOT a rewrite. If the audit shows
more is needed, say so with receipts — but the burden is to prove the fix is small.

## HOW TO READ THIS FILE: it lives in the LIVE checkout — read the ABSOLUTE path
`/home/mira/taeys-hands/consultation_v2/INVESTIGATION_why_runtime_diverges_from_mapping.md` (not a relative
path in your worktree).

## Output required
A provenance table: `divergence | ui_drive file:line | mapped contract it violates (file:line) | receipt
(live obs / commit)`. Plus a verdict: is the MAPPING intact (YAMLs complete, primitives working), or did we
break it? No fix proposals executed — findings only, so Jesse + infra + taeys-hands decide from receipts.

---

# FINDINGS (recorded 2026-08-13 — 4 independent sources agree)

## VERDICT (Observed): the MAPPING IS INTACT. Nothing was destroyed.
codex (task-fe831ffa, part 1/4) diffed the live tree since midnight (base f13a6cc4 → main ac268a44):
**the ONLY change to any mapped file is `gemini.yaml` workflow default `deep_research→deep_think` (97bb1f78)**
— no `element_map` hunk, and ZERO changes to `snapshot.py`, `tree.py`, `runtime.py`, `seat_actions.py`, or any
driver. All five platform YAMLs parse and retain their input/attach/send/extraction maps. grok independently
verified signatures/bodies intact vs `act.py` + the v2 primitives. And the production oracle stands: 29,929
Claude chars extracted via the mapped path (sha256 7201c560). **The map is complete and correct.**

## ROOT CAUSE (single lever): the hand surface reimplemented the tree read instead of CALLING the mapped primitives
`ui_drive.py` custom-walks the AT-SPI tree (349-428) and matches with its own reduced matcher (561-665) —
`build_snapshot`/`find_elements`/`matches_spec`/`ConsultationRuntime` appear NOWHERE in the file. That single
reimplementation (divergence #4) *is* the cause of the other five — they are all properties of the custom walk.

| # | divergence | ui_drive (live 359ee86) | mapped contract it violates | receipt |
|---|---|---|---|---|
| 1 | **no scroll rung** | parse/dispatch 943-1003,1075-1106; schema 862-884 — zero scroll symbols | `runtime.py:606-625` + Claude `driver.py:4411-4431` require `scroll_document_to_bottom` before each scan | mapped path 29,929 chars; hand path 0 Copy |
| 2 | **depth capped at 12, not overridable** | `ui_drive.py:947-950` default `max_depth=12`; schema 851-884 OMITS `max_depth` under `additionalProperties:false` | `tree.py:132-138` default 25; `driver.py:4430` `fence_after=[]` (full) | audit ref depth 12; depth-30=136 rows/0 Copy vs mapped 3687/1 |
| 3 | **visibility narrowed** | `ui_drive.py:375-405` only `SHOWING` + hardcoded `OUTPUT_ROLES` | `tree.py:194-222` `SHOWING∨VISIBLE∨popup`, no whitelist | drops offscreen/portal controls the mapped tree keeps |
| 4 | **custom snapshot bypasses the contract (ROOT)** | `ui_drive.py:349-428` custom walk; no primitive refs | `snapshot.py:662-728` per-platform fence/prune/portals/dedupe/classify; 322-387 exclude/exact/sidebar/structural | Claude yaml 10-58, ChatGPT yaml 28-50 carry these controls |
| 5 | **contract-illegal substring query** | `ui_drive.py:655-665` casefold substring; soma_proxy 876-877 advertises it | `snapshot.py:19-32` forbids contains/regex/fuzzy/substring; 144-194 exact fields | audit 7668-70/7677-79/7708-10/7741-46 |
| 6 | **matcher reduced to name+role** | `ui_drive.py:561-572` rejects spec lacking both | `snapshot.py:144-194` supports names_any_of/states_include/attributes/testid | 12 mapped specs OUTRIGHT REJECTED (CG3, Cl3, Gm4, Px2); 7 lose state constraints |

## THE LOG TRACE (documents-first, `/home/mira/taey_tool_audit.jsonl`, turn 8c2ee807) — proves the bypass was CAUSED by the gap
Taey had the CORRECT instinct and drove the mapped approach — then the reimplemented surface returned nothing,
so it improvised off-map via raw shell (which bypasses the display lock):
- `18:45:07 drive_chat observe :3 filter='Copy'` → **element=None** (the mapped Copy button, pruned by depth-12 + no-scroll)
- `18:46:04 RAW-SHELL xdotool ctrl+a ctrl+c xsel` → blind copy (first bypass, seconds after the None)
- `18:48:05` raw `Atspi.init()` walk · `18:49:03` `xdotool F12` devtools · `18:49:46` `xdotool click 3` (right-click) blind menu
- `18:53:53 observe filter='Copy'→None`, `filter='contents'→None` · `18:57:18` blind `mousemove 700 500` coord-click copy
- `18:58:43 observe filter='Share'→None`, `18:59:34 filter='share'→None` · `19:00:24` raw `xdotool alt+1 Down Down Down Return` blind Share-menu
**Read:** Taey never emitted a `scroll` (ui_drive has none) and its `observe filter='Copy'` returned None every
time (depth-12 prune). The bypass is a *symptom* of divergences #1/#2/#4, not a Taey error.

## MINIMAL FIX (Jesse's thesis, landed): point ui_drive's read/observe/match at the mapped primitives
Fixing divergence #4 — have `ui_drive` build its tree via `snapshot.py`/`tree.py`/`runtime.py` (incl.
`scroll_document_to_bottom`) and match via `matches_spec`, instead of its custom walk+matcher — **collapses all
six rows at once** and restores the exact contract Taey is already trying to use. This is a *substitution*, not
a rewrite. `ui_drive.py` lives in `taey-presence` (infra's repo): **infra implements, taeys-hands + Jesse
coordinate; taeys-hands does NOT edit it.**

## INSTRUCTIONS AUDIT (Observed — `taey-presence/serving/TAEY_OPERATING_PROMPT.md`, read-only)
The prompt's PROCEDURE is correct and even carries the stop-rule — the two gaps are both downstream of the
`ui_drive` gap and are SMALL (infra applies; taeys-hands audits only):
- **The procedure is right:** L129-131 "OBSERVE → ONE ACTION → OBSERVE AGAIN … an unexpected state is a full
  stop, not something to push through"; L177-182 "Scroll to the response, click its Copy control,
  `read_clipboard` … confirm the Copy actually changed the clipboard" (incl. the stale-clipboard/echo/truncation
  traps); L186-190 the engine ban is stated correctly. Taey followed this exactly (see the log trace).
- **GAP A — the prompt says "scroll" but the tool has no scroll.** L177 instructs "Scroll to the response," yet
  the `drive_chat` vocabulary at L133-142 lists only observe/click/type/paste/key/read_clipboard/navigate/focus —
  **no `scroll`.** This is divergence #1 seen from the instruction side: Taey is told to do a thing the tool
  cannot do, so it improvised the scroll via raw `xdotool`. Fixed automatically once `ui_drive` gains a scroll
  action (then add `scroll` to the L133-142 list). One line, after the code fix.
- **GAP B — no hard "displays ONLY via drive_chat" rule.** L201-208 describe the automatic lock but never say
  *never drive a display with `run_command`/`xdotool`; a `drive_chat` dead-end is a STOP+report, not an
  improvise.* The general "full stop" at L131 did not stop the raw-shell bypass. One explicit line closes it.
- **Verdict:** the instruction changes are ~2 small lines and SECONDARY. The primary fix is the `ui_drive`
  substitution; with scroll + deep observe restored, Taey's own correct procedure works and never reaches for
  raw shell. This is fully consistent with "minimal changes."

## DIVISION OF LABOR (Jesse-directed 2026-08-13) + the run-through gate
- **infra (taey-presence):** implement the `ui_drive` fix (point read/observe/match at the mapped
  `snapshot.py`/`tree.py`/`runtime.py` primitives; add the scroll rung; expose depth); apply GAP A + GAP B prompt
  lines; clean taey-presence (current + documented, no dead code/docs).
- **taeys-hands (this seat):** the `consult_v2` primitives + platform YAMLs (Observed intact) + display
  infrastructure; clean taeys-hands (commit this doc, resolve dead/engine-era docs, capture the `.service`
  units, fix stale pointers). taeys-hands does NOT edit `ui_drive.py` or the prompt.
- **Gate:** a Taey run-through happens only after BOTH repos are current+clean AND the `ui_drive` fix is live.
