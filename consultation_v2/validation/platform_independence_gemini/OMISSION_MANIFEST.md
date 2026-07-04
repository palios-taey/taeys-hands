# Gemini Package Omission Manifest

Pinned source SHA: `ddc55dc89538bffddd9622ae03103cbcc48a133a`.

| Item | Disposition | Reason |
| --- | --- | --- |
| `consultation_v2/drivers/base.py` | Retained in place | ChatGPT and Claude still use the legacy shared base until their package slices land. Gemini does not import it. |
| `consultation_v2/completion.py` | Retained in place | Legacy shared drivers still import it. Gemini owns its copied monitor. |
| `consultation_v2/platforms/routing.py` | Retained in place | Shared runtime dispatcher from the residue split; Gemini package owns only its `routing.py` data module. |
| `consultation_v2/runtime.py`, `snapshot.py`, `planner.py`, `primitives.py`, `storage_policy.py` | Retained shared mechanics | These are data-driven shared mechanics allowed by `PLATFORM_INDEPENDENCE_SPEC.md`; this slice does not move them. |
| Live production run | Not performed by this worker | Local work verified syntax, imports, lints, YAML validation, and artifact parity. Supervisor CONTROL must run/observe a real Gemini Deep Think consultation before final task closure. |
