# ChatGPT Package Omission Manifest

Pinned source SHA: `599074da8dde0f4f3337f32275da15d252c60e95`.

| Item | Disposition | Reason |
| --- | --- | --- |
| `consultation_v2/drivers/base.py` | Retained in place until `retire-shared-base` | ChatGPT no longer imports it; package owns copied lifecycle behavior. The file stays for the final decommission task and historical compatibility. |
| `consultation_v2/completion.py` | Retained in place until `retire-shared-base` | ChatGPT owns `ChatGPTCompletionDetector`; shared detector retires only when the shared base is removed from the live path. |
| `consultation_v2/drivers/chatgpt.py` | Retired to compatibility shim | Imports `ChatGPTConsultationDriver` from `consultation_v2.platforms.chatgpt.driver` so external import paths do not change. |
| `consultation_v2/platforms/chatgpt.yaml` | Moved | New owner path is `consultation_v2/platforms/chatgpt/chatgpt.yaml`; `platform_yaml_path()` already prefers package-local YAML. |
| `consultation_v2/runtime.py` | Retained shared leaf mechanics | Adds generic W2E `focus_and_key_open`; no platform branch. |
| `consultation_v2/planner.py` / `yaml_contract.py` | Retained shared fail-closed selection/YAML mechanics | Adds W2E typeahead and postcondition schema/plan propagation so package YAML can express the live-validated ChatGPT menu path. |
| `consultation_v2/input.py`, `atspi.py`, `platforms_runtime.py`, `platforms/routing.py` | Retained residue-split/shared routing surface | ChatGPT routing data is package-owned in `platforms/chatgpt/routing.py`; driver uses `platforms.routing` rather than stale moved AT-SPI symbols. |
| `consultation_v2/cli.py` / `orchestrator.py` ChatGPT identity branch | Pushed down | Shared code calls a generic optional package hook; ChatGPT owns fresh-run inline identity construction. |
| Live production run | Not performed by this worker | Local work verified syntax, imports, lints, YAML validation, package hook dry-run, planner typeahead, constant sweep, and artifact parity. Supervisor CONTROL must run/observe a real ChatGPT attach+Deep Research consultation before final task closure. |
