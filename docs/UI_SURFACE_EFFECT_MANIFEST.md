# UI Surface & Effect-Class Manifest

**Canonical. Companion to [`UI_INTERACTION_AUTHORITY.md`](UI_INTERACTION_AUTHORITY.md)** (spec §1.5:
"Maintain a canonical manifest stating which surfaces and effect classes are permitted,
experimental, or prohibited"). taey-ed surfaces are **out of scope** for this consolidation.

This manifest states, per the `ui_action` supervised grammar, which **effect classes** are permitted,
experimental, or prohibited, and which **surfaces** carry supervised policy. It is grounded in the
live per-platform `supervised_ui.yaml` policies — not aspirational.

## Effect classes

| Effect class | Status | Meaning / operations |
|---|---|---|
| **`local`** | **PERMITTED (P0)** | Non-outward, non-value-bearing, reversible-in-place: `observe`, `verify`, `focus`, and `activate` **only** for a control explicitly declared `effect_class: local` in the surface policy. |
| *(outward / value-bearing)* — write, key, paste, navigation, page, file, send, submit, post, purchase, delete, external-confirmation | **PROHIBITED (P0, fail-closed)** | Excluded at P0. Adding any of these is a **separate reviewed authority-provider design**, never an extension inside the P0 seat. |
| *(unknown effect)* | **PROHIBITED (fail-closed)** | A control whose effect class is unknown fails closed — never actuated. |
| *(experimental)* | **NONE at P0** | No effect class is currently in an experimental tier. Promotion of any class to permitted is a **separate governance decision, never inferred from convenience**. |

Observed ground truth: the five supervised policies currently declare **only `effect_class: local`**
(no outward class is declared anywhere), consistent with P0 being read + local-only.

## Surfaces

### Supervised `ui_action` surfaces (the direct-grammar lane)
Per-platform supervised policy: `consultation_v2/platforms/<platform>/supervised_ui.yaml`.

| Surface | Policy file | Status |
|---|---|---|
| chatgpt, claude, gemini, grok, perplexity | `consultation_v2/platforms/<p>/supervised_ui.yaml` | **PERMITTED — supervised, local-effect only.** Policy declares capability + effect only; it carries no recommended order, target sequence, expected-next control, or corrective answer. |
| Sales Navigator public-safe control maps | *(not yet migrated)* | **NOT YET IN SCOPE** — migration to a supervised surface is a later consolidation step, gated separately. |
| ATS provider read-only maps | `consultation_v2/ats/providers/*.yaml` | **PUBLIC MECHANICAL CANDIDATE, NOT PRODUCTION-QUALIFIED** — Greenhouse alone may compile one terminal read-only observation. Lever/Ashby are mapping-only; Workday is inactive. Fill, upload, and submit remain prohibited. Private application state stays outside Hands. |
| taey-ed Mac screen recipes | *(taey-ed)* | **EXCLUDED** from this consolidation (Jesse). |

### Named-exception mature engine (distinct lane — not `ui_action`)
| Surface | Files | Status |
|---|---|---|
| ChatGPT/Claude/Gemini/Grok/Perplexity **consultation** element maps | `consultation_v2/platforms/<p>/<p>.yaml` | **PERMITTED by NAMED EXCEPTION** — the live deterministic Family-chat consult engine (`consultation_v2`). Its tool is `consult_extract_action`, NOT the direct `ui_action` grammar (see the authority doc's grammar-lanes section). Not deprecated; not the definition of all UI. |
| LinkedIn Jobs read-only capture | `consultation_v2/platforms/linkedin/linkedin.yaml`, `scripts/run_linkedin_jobs.py` | **PERMITTED by NAMED EXCEPTION** — a frozen private transaction selects or consumes one exact job detail, writes only to a private sink, and performs no application, message, post, save, or retry. Taey receives only compact counts, hashes, state, and receipt evidence. |

## Prohibited (permanent)
Agent-authored autonomous loops, scripted click-sequences, raw/hardcoded coordinate locators or coordinate
fallback clicking, hidden read/fallback,
implicit next-turn, and inferring success from a primitive return — all **prohibited** as model-facing
UI behavior, on every surface. See the authority doc's automation-scope table.
