# Layer-3 consultation engine reference

Status: retained implementation reference; not the current autonomous production entrypoint.

The Layer-3 engine composes consultation steps that are currently exercised through the manual `drive_chat`
path. It remains in the repository because working automation may be promoted after production evidence, but
it does not define UI names, operations, completion, extraction, or fallback behavior.

## Authority

The engine must consume, without reinterpretation:

1. `CONSULTATION_CONTRACT.md` for the consultation lifecycle.
2. `docs/UI_INTERACTION_AUTHORITY.md` for one-action and fresh-observation discipline.
3. `consultation_v2/PACKET_CONTRACT.md` for the two input bundles and brief prompt.
4. `consultation_v2/CONSULT_MONITOR_SPEC.md` for passive Stop-button completion monitoring.
5. `consultation_v2/EXTRACTION_SCHEMA.md` and `EXTRACTION_PATTERNS.md` for output handling.
6. Exactly one destination platform YAML for every platform-specific element, operation, state, and timing value.

Shared engine code may provide genuine primitives, canonical snapshot construction, receipts, durable run state,
and notification transport. It may not contain platform UI strings, coordinates, pixels, OCR, substring or fuzzy
matching, hidden fallbacks, automatic action retries, or a second accessibility-tree reader.

## Current execution boundary

The production path is manual Taey operation through `drive_chat`: fresh canonical observation, one YAML-authorized
action, and a fresh validation before the next decision. After a validated send, the platform monitor—not Taey
polling—waits for Stop to disappear twice. Manual assistant-text extraction scrolls to the absolute bottom and uses
the last exact mapped Copy control.

The retained orchestrator, platform drivers, and `consultation_v2/cli.py` are reference code until a platform-specific
production gate promotes them. A successful historical run does not grant current authority.

## Promotion gate

Automation is promotable one platform at a time only when a real production transaction proves that it:

- uses the same platform YAML and canonical snapshot as the manual path;
- preserves one action followed by a fresh independent observation;
- fails closed on zero, duplicate, stale, or contradictory matches;
- uses the existing monitor and platform extraction contract;
- produces prompt, bundle, URL, completion, extraction, and ingestion receipts; and
- leaves manual recovery available at the first mismatch.

Promotion removes or makes unreachable the older competing path in the same change. It never adds a fallback.
