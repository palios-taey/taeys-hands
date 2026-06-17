# EXACT-MATCH-ONLY YAML Schema — consultation_v2 (p0-yaml-schema, the contract codex implements)

> Defines the ONLY legal element/validation grammar for `consultation_v2/platforms/*.yaml`.
> Enforced two ways: **lint** (`tools/lint_exact_match.py` + `.githooks/pre-commit`, already wired)
> blocks the commit; **runtime assert** (in the matcher, p1-grok landing) rejects any non-exact
> key at load so the rule cannot regress silently. Builds on [[PRIMITIVES_CONTRACT]] §3.

---

## 1. element_map — exact name + role ONLY

Every entry is matched against a live AT-SPI element by **verbatim `name`** and **`role`**:

```yaml
element_map:
  send_button:
    name: "Send message"        # EXACT AT-SPI name string, verbatim, case-sensitive as scanned
    role: push button           # EXACT AT-SPI role
  stop_button:
    name: "Stop response (Esc)"
    role: button
```

Optional refinement (still exact, never loosening):
- `states_include: [checked]` — element must currently expose ALL listed AT-SPI states (exact tokens).

**FORBIDDEN keys (lint + runtime reject):** `name_contains`, `name_not_contains`, `name_contains_all`,
`name_pattern`, `role_contains`, `url_contains`, `title_contains`, `contains`, `regex`, `matches`,
`fuzzy`. If the real name is known, the YAML states it exactly. If an element needs a short list of
exact labels, `names_any_of` is allowed. If an element "isn't found", the fix is a LIVE AT-SPI scan
to get the real name+role — never a broadened matcher.

## 2. The ONE exception — `structural:` locator for inherently-dynamic leaves

When a value MUST vary at runtime — a file chip carrying the timestamped upload filename, the
response text, a generated thread id — match the **structural position** of the element, not its
text. The locator is itself exact; only the leaf text is allowed to vary because it has to:

```yaml
element_map:
  uploaded_file_chip:
    structural:
      role: list item            # EXACT role of the chip element
      parent: attachment_row     # EXACT element_map key of its container (resolved, not a substring)
      index: 0                   # integer ordinal among matching siblings (0-based); or `ordinal: last`
```

Rules for `structural:`:
- `role` is required and exact. `parent` is an exact element_map KEY (the container is itself an
  exact-match entry). `index` (int) or `ordinal: first|last` selects among siblings — no text match.
- A `structural:` entry MAY carry `name_must_be_nonempty: true` (presence check) but MUST NOT carry
  any `*_contains`/substring of the dynamic text. Matching the dynamic text is the thing we are
  banning; structural matching is the sanctioned replacement.

## 3. validation — through the live tree, on everything

Every validation (mode set, attach present, send fired, response complete) reads the live AT-SPI
tree for an exact element + state. The tree is the oracle — never a screenshot-as-truth, never an
assumption, never a substring.

```yaml
validation:
  mode_active:
    indicators:                  # ALL must be present (exact element_map specs)
      - { name: "Deep Think", role: toggle button, states_include: [checked] }
  send_fired:
    stop_present: stop_button    # exact element_map key that must appear
  response_complete:
    stop_absent: stop_button     # exact key that must be GONE (persists-check: gate on a persistent
                                 # element, never on a dropdown item that vanishes on close)
  deep_research_active:
    indicators:
      - { name: "Deep research", role: toggle button, states_include: [pressed] }
    absent:
      - search_mode_trigger       # exact key that must NOT remain in the fresh tree
  attach_present:
    file_chip: uploaded_file_chip # the structural locator from §2 — presence of the chip, not its text
```

Until every dynamic chip has a structural locator, `file_chip.roles` is allowed
only when the driver supplies the uploaded file path. Runtime validation then
requires a live tree element whose `name` equals `basename(path)` exactly and
whose `role` is one of the listed exact roles. Truncation, prefix matching, and
extension-only matching fail loud.

**Banned in validation too:** `url_contains` and any substring matcher. A URL gate, when needed,
matches the platform's exact `url` / `url_match` field (per [[PRIMITIVES_CONTRACT]] §2.D) — exact,
from YAML, never a hardcoded substring in code.

## 4. The matcher contract (what codex implements; verified in p1-grok against a real exact YAML)

`matches_spec(element, spec)` accepts EXACTLY: `name` (verbatim equality), `role` (equality),
`states_include` (subset), and a `structural:` block (role + parent-key + index/ordinal). Any other
key → **raise at load** (runtime assert), so a loose matcher can never silently re-enter. The lint
catches it at commit; the assert catches it at run. Two gates, same rule.

> Sequencing (cannot-lie): the runtime-assert matcher rewrite lands WITH p1-grok — the first
> platform whose YAML is rebuilt exact-match — so it is production-verified against a real exact
> YAML rather than flipped on 13 YAMLs that still carry 75 loose matchers (those are migrated
> per-platform through p1). The lint gate is already live and green-on-clean today.
