# Consult path — production validation suite (mandate step 5, VALIDATE)

Surface: the consult engine (`consultation_v2/`). Engine SHA under test: **`333a265d`** (main; includes
the merged seat fix `5f9a89cd`). Every item below is conductor-re-runnable. Production is the oracle —
no synthetic tests.

## A. Mechanical gates (deterministic; re-run on `333a265d`)
| gate | command | result |
|---|---|---|
| contract lint | `python3 consultation_v2/validators/lint_consultation_v2_contract.py --all` | CLEAN — 53 files, 0 findings |
| no-YAML-silent-fallbacks | `python3 consultation_v2/validators/lint_no_yaml_silent_fallbacks.py --all` | CLEAN — 53 files, 0 findings |
| platform isolation | `python3 consultation_v2/validators/lint_platform_independence.py --all` | CLEAN — 5 packages, 12 leaves, 0 findings |
| exact-match | `python3 consultation_v2/validators/lint_exact_match.py` | PASS — 7 files, 0 loose matchers |
| py_compile | `python3 -m py_compile consultation_v2/*.py consultation_v2/platforms/*/*.py scripts/run_consultation_v2.py scripts/run_taey_consult_extract.py` | PASS |

## B. Per-platform config resolution (all 5 load + resolve; fail-loud on missing required select)
`python3 scripts/run_consultation_v2.py --platform <p> --message v [--select model=..] --dry-run`
| platform | result |
|---|---|
| chatgpt | OK (would_call=False) |
| claude | OK with `--select model=opus --select mode=extended_thinking` (fail-loud requires `model` — correct) |
| gemini | OK (would_call=False) |
| grok | OK with `--select model=heavy` (fail-loud requires `model` — correct) |
| perplexity | OK (would_call=False) |

## C. Real production execution observations (both consult entry points, multiple platforms)

### C1 — Taey SEAT, autonomous, ChatGPT (independent taeys-hands reproduction on `5f9a89cd`)
- `run_taey_consult_extract.py --platform chatgpt` — Taey (ep3@10.0.0.8) authored **20 actions**
  navigate→upload(dedup-suffix `CONSULT_ENGINE_MAP(3).md` accepted)→composer→paste→select_mode→submit→completion(stop_seen)→extract.
- ok=true, attachment_verified=true, completed=true, stop_seen=true, neutral_reset all true; **2224-char** grounded answer.
- Re-checkable: thread `https://chatgpt.com/c/6a6c008c-7770-83ea-a6e5-e96ff8c09590`; receipt committed at `eaf1dab2`:
  `receipts/consult-engine/usage.jsonl` (+ `usage-2026-07-31-chatgpt-turns.jsonl`, fsync'd per-turn audit trail with `answer_body_sha256`).

### C2 — Taey SEAT, autonomous, Gemini Deep Research (codex production PASS on `5f9a89cd`)
- `run_taey_consult_extract.py --platform gemini` — navigate-fresh, upload+focus_and_key submit, Deep Research,
  app-root export. ok=true, attach_verified=true, completed+stop_seen=true, neutral_reset all true; **28,454-char** answer.
- Receipt: `/tmp/task-baa85ff4-gemini-5f9a89cd.jYGtBl/result.json`. Verify: the `jq` in task-baa85ff4 (PASS both platforms).

### C3 — Deterministic ENGINE, ChatGPT pro_extended, real requester (tutor r12)
- `run_consultation_v2.py --platform chatgpt --select model=pro_extended --attach <r12 packet> --requester tutor` —
  navigate-fresh path. ok=true, **14884-char** grounded ruling; delivered raw to tutor.
- Re-checkable: thread `https://chatgpt.com/c/6a6be242-7ae0-83ea-95e3-8e84872a1074`;
  durable answer `.consult-work/tutor-r12-chatgpt-ANSWER.md`.

## Coverage summary
- Both entry points proven in production: the Taey **seat** (autonomous, C1+C2) and the deterministic **engine** (C3).
- End-to-end on **ChatGPT** (seat + engine) and **Gemini** (seat, Deep Research); all 5 platform configs resolve (B).
- All mechanical gates clean on the merged SHA (A).
- Not claimed: fresh end-to-end on Grok / Perplexity / Claude this cycle (configs resolve; Grok usage-cap + Perplexity's
  careers-shared display make a fresh run costly). Honest scope — the consult PATH is validated; per-platform breadth
  is incremental.
