# UI Interaction Authority — the one contract for how Taey sees and touches a UI

**Canonical, cross-repo. Jesse-directed 2026-08-04 (UI consolidation, safe tier).**
This is the single authority for the direct interactive-UI grammar Taey uses. Every live
`CLAUDE.md`, `README`, and agent boot file that touches UI operation points HERE. If any other doc
conflicts with this on UI interaction, this wins.

`taeys-hands` is the **sole definer** of a direct interactive-UI tool grammar for Taey. There is
**one grammar: `ui_action`** (defined by `consultation_v2/supervised_ui_contract.py`,
`build_live_ui_action_schema`). No other repository may define a second model-facing UI grammar;
`act.py`, `tree_view.py`, the ATS 9-function facade, consultation-driver steps, and taey-ed behavior
-tree node names are **adapter/implementation details or separately-scoped tasks, not** direct
interactive-UI tools for Taey to elect between. Domain repos supply *purpose, policy, facts, and
state*; Hands owns *the capability boundary* — how Taey safely sees and touches a UI.

## The supervised contract (the one lifecycle)

> **fresh filtered observation → opaque snapshot-bound reference → ONE authorized action → fresh independent verification → durable immutable receipt**

Permitted supervised steps, each its own approved turn (no chaining):

- **observe / verify** — read a filtered public accessibility projection (no raw tree, no
  coordinates, no runtime names, no URL/value; opaque `ref` + revision only).
- **focus**, and **activate** only for controls declared `effect_class: local` in the per-platform
  `supervised_ui.yaml` policy.
- Every action: Taey proposes exactly one call; a supervisor approves-or-rejects the exact proposal
  hash **without editing it**; the adapter executes **at most that one** call once; a **fresh**
  observe/verify turn is required before any further action. One-use approval, replay-protected
  across restart, immutable causally-linked receipts.

**Excluded at P0 (fail-closed):** write, key, paste, navigation, page, file, send, submit, post,
purchase, delete, external-confirmation, and any unknown effect. Adding an outward or value-bearing
operation is a **separate reviewed authority design**, never an extension smuggled in.

Implementation (Observed, merged on `main`): `consultation_v2/supervised_ui_seat.py`,
`supervised_ui_contract.py`, `supervised_ui_receipts.py`, per-platform
`consultation_v2/platforms/<p>/supervised_ui.yaml`, runner `scripts/run_supervised_ui_seat.py`,
design-rule gate `consultation_v2/validators/validate_supervised_ui_design_rules.py`. Full protocol
(state machine, exact model request, receipt chain, production-walk gates):
[`docs/PUBLIC_SUPERVISED_TAEY_UI_SEAT_PLAN_2026-08-04.md`](PUBLIC_SUPERVISED_TAEY_UI_SEAT_PLAN_2026-08-04.md).

## Allowlisted mature engines (permitted ONLY by named exception)

- **`consultation_v2`** — the Family-chat consultation engine (:2–:6/:13). **LIVE production**,
  actively maintained on `main`, deterministic match-one-mapped-state-or-halt, no coordinate
  fallback. **It is NOT deprecated and there is no live "v1"** — it is the only consultation engine
  in the repo, it is what `scripts/run_consultation_v2.py` runs, and it delivered real production
  consults through 2026-08-03. It is a **named-exception product-owned engine**, not the definition
  of all UI; the generic `ui_action` grammar above is being promoted out of its namespace so
  `consultation_v2` is one consumer/adapter, not the UI authority. Deeper promotion is steps 3–9 of
  the consolidation plan, sequenced later.

An engine qualifies for the allowlist only with **explicit naming + current production evidence**.
Nothing is allowlisted by convenience or by being "already running."

## Prohibited: agent-authored autonomous loops (permanent)

A CLI or model that **invents a multi-action driver, loop, fallback chain, retry strategy, or hidden
sequence is PROHIBITED** — this is the permanently-banned UI-automation class (100% documented
failure). Specifically banned as model-facing UI behavior:

- any backend `while`/hourly/scheduled loop that drives a UI unattended;
- a tool result auto-triggering the next model request (no implicit next turn);
- a scripted/ordered "click-sequence" that says which control comes next;
- coordinate-based clicking, or any hidden read/fallback;
- inferring success from a primitive's return instead of a fresh independent verification.

A surface earns broader automation later ONLY through measured production history — a **separate
governance decision, never inferred from convenience**.

## Automation-scope ruling (resolves "NO UI AUTOMATION EVER" vs live engines)

| Execution shape | Status |
|---|---|
| Taey proposes ONE state-bound action → authority approves → adapter executes once → fresh verification required | **Permitted default** |
| Existing product-owned deterministic engine with an explicit allowlist + current production evidence (`consultation_v2`) | **Permitted only by named exception** |
| CLI/model invents a multi-action driver, loop, fallback chain, retry, or hidden sequence | **Prohibited** |
| A surface earns broader automation via measured production history | **Separate governance decision; never inferred** |

## Grammar lanes — one direct grammar, and what is NOT it (read before authoring SFT)

There is **one direct interactive-UI grammar: `ui_action`** (`consultation_v2/supervised_ui_contract.py`,
`build_live_ui_action_schema`). Everything below is a **distinct lane or an adapter/implementation
detail — NOT interchangeable with `ui_action`, and NOT relabeled as it.** Training them together as
different spellings of "using a UI" is the exact confusion this consolidation exists to prevent.

| Tool / vocabulary | Lane | Trained as `ui_action`? |
|---|---|---|
| **`ui_action`** (supervised seat) | THE direct interactive-UI grammar Taey elects | **YES — this is the one grammar.** |
| **`consult_extract_action`** (`consultation_v2/taey_extract.py`) | The **consultation ENGINE's** driving tool (Family-chat consults on :2–:6). A named-exception mature-engine adapter. | **NO.** Its own labeled lane (`surface: consult_action`). Same safety principles (observe → one action → verify, no autonomous loop) but a **different target format** — keep it explicitly separate. |
| `act.py`, `tree_view.py` (treasurer) | Low-level AT-SPI primitives / adapter | NO — adapter impl, not a model-facing grammar. |
| ATS 9-function facade (apply-machine) | ATS adapter | NO — its concepts inform the contract; it is not a second direct grammar. |
| CLI commands | operator tooling | NO. |

**Consequence for the SFT rewrite:** consult-seat pairs captured as `surface: consult_action` (e.g. the
Taey-seat walk corpus) are **consultation-engine driving pairs, not `ui_action` pairs** — they are NOT
converted to `ui_action`; they remain their own named-exception lane. Only genuine supervised-seat
`ui_action` trajectories are `ui_action` targets.

## Training-source gate — what the live SFT-authoring context must reject

Before a UI record enters SFT authoring or ordinary retrieval, reject:

- any document marked **superseded / historical / archived** (e.g. anything under `docs/archive/`);
- any **raw UI script or CLI runbook** presented as a model target;
- any path that **bypasses the canonical contract** (coordinate clicks, autonomous loops, hidden
  fallbacks);
- any surface map carrying **domain-private facts**;
- any record **without the surface-pack digest and exact contract version**;
- **failed / rejected / stale actions presented as right-way completions** (executed-accepted only;
  see the corpus disposition invariant).

Archived material is kept for **diagnosis / correction-training** only — never in ordinary
SFT-authoring context.

## Tree is truth

Operate from the AT-SPI tree, never the screen. The tree is the source of truth; a screenshot is a
rare exception (and usually indicates a filter to fix, not a need for pixels). Any doc that says
"the screen is ground truth" or teaches reusable ordered click-sequences is **superseded by this
authority** and archived.
