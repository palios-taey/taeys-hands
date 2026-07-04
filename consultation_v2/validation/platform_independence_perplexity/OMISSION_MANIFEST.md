# Perplexity Package Omission Manifest

Pinned source SHA: `0aac0047dd9d0d83772d9344f95eb731f1f2aa8c`.

| Item | Disposition | Reason |
| --- | --- | --- |
| `consultation_v2/drivers/base.py` | Retained in place | ChatGPT, Claude, and Gemini still use the legacy shared base until their package slices land. Perplexity does not import it. |
| `consultation_v2/completion.py` | Retained in place | Legacy shared drivers still import it. Perplexity owns its copied monitor. |
| `consultation_v2/platforms/routing.py` | Retained in place | Shared runtime dispatcher from the prior residue split; Perplexity package owns only its `routing.py` data module. |
| `consultation_v2/runtime.py`, `snapshot.py`, `planner.py`, `primitives.py`, `storage_policy.py` | Retained shared mechanics | These are data-driven shared mechanics allowed by `PLATFORM_INDEPENDENCE_SPEC.md`; this slice only touched `snapshot.py` for ordinal support required by Perplexity YAML. |
| Live production run | Not performed by this worker | Local work verified syntax, imports, lints, and YAML loading. Supervisor CONTROL must run/observe a real Perplexity consultation before final task completion. |
