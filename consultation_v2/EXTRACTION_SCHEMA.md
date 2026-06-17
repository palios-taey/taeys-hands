# Extraction-by-output-type YAML Schema — consultation_v2 (p4-extraction-yaml-schema)

> Defines the ONLY legal grammar for the `extraction:` section of
> `consultation_v2/platforms/*.yaml`. Enforced at load by the strict loader
> (`consultation_v2/yaml_contract.py`) — any violation raises a `ValueError`
> at load (fail loud), with line-pinned findings, the same way the
> `element_map` / `validation` grammar already does. Governed by
> `FLOW_CONSULTATION_ENGINE.md` §2 (intake `output_type`) and §11 (Extraction
> Contract), and the exact-match rules of `YAML_SCHEMA.md`.

This is the SCHEMA + load-validation + typed-representation layer ONLY. It
declares, per platform, how each supported output type is extracted. It does
NOT implement the browser extraction logic — that is the downstream
`p4-assistant-text` / `p4-research-report` / `p4-artifact` tasks, which will
refactor each driver's `extract_primary` to consume this declarative section
instead of the legacy `workflow.extract` / `workflow.extra_extract` keys.

---

## 1. The `extraction:` section — output type → ordered workflow

```yaml
extraction:
  assistant_text:
    steps:
      - { action: scroll_to_bottom, element: attach_trigger }
      - { action: copy_element, element: copy_button, select: last }
      - { action: read_clipboard, validation: response_complete }
  research_report:
    steps:
      - { action: scroll_into_view, element: copy_contents_button }
      - { action: copy_element, element: copy_contents_button }
      - { action: read_clipboard }
      - { action: read_tree_text, validation: response_complete }
    validate_markers: ["#"]
```

Each top-level key under `extraction:` MUST be one of the five contract output
types (`FLOW_CONSULTATION_ENGINE.md` §2 / §11):

- `assistant_text`
- `research_report`
- `artifact`
- `downloaded_file`
- `attachment_echo`

Any other key is rejected at load. **An output type the platform cannot serve
is simply NOT listed** (cannot-lie: the section never claims an unproven path).
A request for an output type absent from a platform's `extraction:` section must
fail loud at dispatch — the engine never downgrades an unsupported type to
another, and never falls back. The set of supported types per platform is
therefore exactly the keys present in its `extraction:` section.

Each output-type value is a mapping with:

- `steps:` (REQUIRED) — a non-empty ordered list of extraction steps.
- `validate_markers:` (optional) — a non-empty list of exact marker strings the
  extracted content must carry for this output type (e.g. a report heading
  marker). Used by `research_report`/`artifact` to reject summary-only grabs.

## 2. Step grammar — exact, ordered, no loose matchers

A step is a mapping. Allowed keys: `action`, `element`, `select`, `validation`.
Any other key is rejected at load. Element references are exact `element_map`
KEYS (resolved against the platform's `element_map`, never a substring of a
visible name) — the same exact-match discipline as `YAML_SCHEMA.md`. No
`*_contains` / `name_pattern` / regex / fuzzy anywhere; the whole-document
forbidden-matcher sweep already covers it, and this section adds per-step
structural validation on top.

### `action` (required)
One of the enumerated step verbs. Each maps to a shared runtime primitive the
driver invokes; no platform strings, no fuzzy discovery:

| action | meaning | `element` |
|---|---|---|
| `scroll_to_bottom` | scroll the conversation to the final answer (anchor on the named composer control) | required (anchor) |
| `scroll_into_view` | bring a specific report/artifact control on-screen | required |
| `click` | activate a mapped trigger/menu element via AT-SPI element action (e.g. open a Share/Export popover) | required |
| `copy_element` | activate a mapped copy control (the clipboard-producing button) | required |
| `read_clipboard` | read the clipboard the prior `copy_element` populated | forbidden |
| `read_tree_text` | collect report text from bounded AT-SPI tree text nodes when a mapped copy control is absent or empty | forbidden |
| `open_panel` | open an artifact/canvas/report panel via a mapped control | required |
| `download` | invoke a mapped export/download control producing a file | required |
| `verify_against_source` | verify extracted content against a source attachment hash | forbidden |

Actions in the "required" column MUST name an exact `element_map` key via
`element:`. `read_clipboard`, `read_tree_text`, and `verify_against_source`
MUST NOT carry `element:`.

### `element` (conditionally required)
Exact `element_map` KEY of the control the step touches. Validated against the
platform's `element_map` at load — an unknown key is rejected.

### `select` (optional)
How to disambiguate when several elements match the same exact `element_map`
key. One of `first` / `last` (matching `Snapshot.first` / `Snapshot.last`).
`last` selects the lowest-on-page match (the final response). Defaults to `last`
when omitted.

### `validation` (optional)
An exact `validation:` KEY (must reference an entry in the platform's
`validation:` section) that gates this step's result — reusing the existing
validation grammar rather than inventing a parallel one.

## 3. What the loader enforces (fail loud at load)

`load_platform_yaml` calls `_validate_extraction_specs` for chat platforms when
an `extraction:` section is present. It raises `ValueError` (with line-pinned
findings) when:

- an `extraction:` top-level key is not one of the five contract output types,
- `extraction:` is present but not a non-empty mapping,
- an output-type value is not a mapping,
- an output-type value carries a key other than `steps` / `validate_markers`,
- `steps:` is missing, or is not a non-empty list,
- a step is not a mapping, or carries a key other than
  `action` / `element` / `select` / `validation`,
- a step `action:` is missing or not in the enumerated action set,
- a step `element:` is present but not an exact `element_map` key,
- an action that requires an element has no `element:`,
- `select:` is present but not `first` / `last`,
- `validation:` is present but not an exact `validation:` key,
- `validate_markers:` is present but not a non-empty list of exact strings,
- any forbidden loose-matcher key appears anywhere in the document (covered by
  the whole-document forbidden-matcher sweep that already runs).

The `extraction:` section is OPTIONAL at this schema layer — platforms migrate
per the downstream p4 tasks — but when present it is validated in full. The
legacy `workflow.extract` / `workflow.extra_extract` keys remain untouched until
the per-platform extractor tasks consume this section and retire them.

## 4. Typed representation the drivers will consume

`yaml_contract.py` exposes:

- `get_extraction(platform) -> Dict[str, ExtractionWorkflow]` — the parsed,
  validated map keyed by output type (empty dict when no `extraction:` section).
- `get_extraction(platform, output_type) -> ExtractionWorkflow | None`.

`ExtractionWorkflow` is a frozen dataclass `{ output_type, steps:
tuple[ExtractionStep, ...], validate_markers: tuple[str, ...] }`.
`ExtractionStep` is a frozen dataclass `{ action, element, select, validation
}`. These mirror, in code, exactly the grammar this schema validates.

## 5. Downstream interaction — NOTE for p4 extractor tasks

Drivers today read `workflow.extract.primary_key` (+ `workflow.extra_extract.*`)
and hardcode the scroll/copy/validate sequence inside each
`extract_primary`/`extract_secondary`. Concretely (per
`consultations/inventory/p1_extraction_inventory.md`):

- ChatGPT `consultation_v2/drivers/chatgpt.py` extract_primary: scroll-anchor
  on `attach_trigger`, `copy_button` last-by-y. `assistant_text` only (Canvas/DR
  not wired — NOT listed in its `extraction:` section).
- Claude `consultation_v2/drivers/claude.py` extract_primary: raw-scan for
  visible `Copy`, lowest-by-y. `assistant_text` only (artifacts not wired).
- Gemini `consultation_v2/drivers/gemini.py`: normal = `copy_button`; Deep
  Research = `share_export` -> `copy_content_item` popover. Both listed.
- Grok `consultation_v2/drivers/grok.py`: `copy_button` to-bottom. Image
  download is YAML-documented under `imagine:` but NOT executed by V2 —
  `downloaded_file` is NOT listed (cannot-lie).
- Perplexity `consultation_v2/drivers/perplexity.py`: `copy_contents_button`
  first (full report), else `copy_button`. `assistant_text` + `research_report`.

These p4 extractor tasks should refactor each driver's `extract_primary` to read
`get_extraction(platform, request.output_type or 'assistant_text')` and execute
the declared steps through shared runtime primitives, then retire
`workflow.extract` / `workflow.extra_extract`. THIS schema task does NOT change
any driver and does NOT remove the legacy `workflow.extract*` keys — doing so
without the driver refactor would break extraction. The legacy keys and the new
`extraction:` section coexist until the extractor tasks land.
