# Grok Package Omission Manifest

Pinned implementation commit: `81d3d921`.

Observed omissions in this branch:

- Other platform drivers are not migrated into package directories. This slice is Grok-only build-ahead work.
- `consultation_v2/drivers/base.py` and `consultation_v2/completion.py` are not deleted globally because ChatGPT, Claude, Gemini, and Perplexity still use them. Grok does not import them through its package.
- `consultation_v2/input.py` and `consultation_v2/atspi.py` still contain platform-routing residue. The residue is documented in `RESIDUE_AUDIT.md` rather than represented as eliminated.
- No live browser consultation was dispatched from this branch. Verification is syntax, loader smoke, and package/contract lint only.
- No CI workflow change is included. Existing validators were expanded only enough to include nested package YAML paths.

Inferred risk:

- External code outside this repository could still import `consultation_v2.drivers.grok`; the shim preserves that path and points it at the package-owned implementation.

Unknowns:

- Whether CONTROL wants the unresolved `input.py` / `atspi.py` residue split in this same PR or a follow-up PR. This artifact makes the gap explicit.
