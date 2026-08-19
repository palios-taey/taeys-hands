# Documentation map

This file defines the documentation surface for the current `taeys-hands` production baseline. If a document
is not listed here or linked from a listed index, it is not operating authority.

## Read in this order

1. `README.md` — the three implementation layers and current production boundary.
2. `100_TIMES.md` — concise manual operating rules.
3. `CONSULTATION_CONTRACT.md` — full consultation lifecycle.
4. `docs/UI_INTERACTION_AUTHORITY.md` — one-action, fresh-tree discipline.
5. `docs/SUPERVISED_UI_PROTOCOL.md` — immutable supervised-seat state and receipt protocol.
6. `TAEY_INDEX_taeys-hands.md` and `consultation_v2/README.md` — implementation and platform indexes.
7. The destination's `consultation_v2/platforms/<platform>/<platform>.yaml` — exact UI authority.

## Current operating documents

- `PLATFORM_INDEPENDENCE_SPEC.md`
- `consultation_v2/YAML_SCHEMA.md`
- `consultation_v2/PRIMITIVES_CONTRACT.md`
- `consultation_v2/PACKET_CONTRACT.md`
- `consultation_v2/CONSULT_MONITOR_SPEC.md`
- `consultation_v2/EXTRACTION_SCHEMA.md`
- `consultation_v2/EXTRACTION_PATTERNS.md`
- `docs/PUBLIC_OPERATING_BOUNDARY.md`
- `docs/UI_SURFACE_EFFECT_MANIFEST.md`
- `DEPLOY.md`
- `systemd/DISPLAY_REGISTRY.md`
- `systemd/README.md`

`CLAUDE.md`, `CONTRIBUTING.md`, and `.claude/skills/` govern repository maintenance. They do not override the
runtime authority order above.

## Reference implementation

`FLOW_CONSULTATION_ENGINE.md`, `consultation_v2/DRIVER_CONTRACT.md`, the orchestrator, and platform drivers
describe the retained Layer-3 automation. They are code/reference material, not the current autonomous
production entrypoint. Proven automation may be adopted only by compiling to the same YAML, canonical snapshot,
primitive, monitor, and validation contracts used by the manual path.

## Training background

`training_docs/` contains curated explanations and failure patterns that help Taey generalize the current
rules. These files deliberately restate rationale in different words, but they are not action authority. If a
background explanation and an operating document differ, the operating document and platform YAML win.

## Excluded history and local state

Dated audits, Chat transcripts, handoffs, recovery packets, generated validation diffs, superseded plans, and
old code snapshots are preserved in Git history or external recovery bundles. They are deliberately absent
from the current tree. The following paths are ignored so they cannot silently re-enter the training surface:

- `archive/`, `docs/archive/`
- `audit_logs/`, `consultations/`, `recaps/`, `docs/handoffs/`
- `consultation_v2/audits/`, `research/`, `scans/`, `validation/`
- `.consult-work/`, caches, virtual environments, and `*.bak`/`*.orig`/`*.rej` files

## Truth rule

The YAML is the source of UI truth and a fresh canonical AT-SPI tree is the oracle. Dated prose never proves
current production state. Production claims require a current Git SHA plus a live receipt from the actual
display or service.
