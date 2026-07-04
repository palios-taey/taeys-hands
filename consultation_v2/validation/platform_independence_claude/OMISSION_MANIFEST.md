# Claude Package Omission Manifest

Pinned source SHA: `a04da10a4154247f122ef68cb0c3db65f1c0a26d`.

| Item | Disposition | Reason |
| --- | --- | --- |
| `consultation_v2/drivers/base.py` | Retained in place | ChatGPT still uses the legacy shared base until its package slice lands. Claude does not import it. |
| `consultation_v2/completion.py` | Retained in place | ChatGPT legacy driver still imports it. Claude owns its copied monitor. |
| `consultation_v2/drivers/claude.py` | Retired to shim | Compatibility import remains for callers that still import the legacy path. |
| `consultation_v2/platforms/_routing_core.py` | Retained shared mechanics | Residue-split routing core is package-parameterized and classified as leaf; Claude owns `platforms/claude/routing.py` data. |
| `consultation_v2/runtime.py`, `snapshot.py`, `primitives.py`, `storage_policy.py`, `planner.py` | Retained shared mechanics | These are data-driven shared mechanics allowed by `PLATFORM_INDEPENDENCE_SPEC.md`; this slice only tightens planner handling for non-resettable follow-up menus. |
| Live production run | Not performed by this worker | Local work verifies syntax, imports, lints, YAML validation, method-body parity, and artifact-preservation evidence. Supervisor CONTROL must run/observe a real Claude opus+max consultation before final task closure. |
