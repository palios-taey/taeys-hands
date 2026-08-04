# HANDOFF — taeys-hands → codex (2026-08-04)

Written before Claude usage ends. taeys-hands owns the Family-chat consult engine (`consultation_v2/`, displays :2–:6/:13) and the Taey-seat training-capture lane. This is the live state, the held consult, the standing rules, the gates, and the open threads.

## LIVE STATE
- **Consult engine `consultation_v2/` is production on `main`; all trees clean + pushed; codex idle.**
- **Displays :2–:6 are FREE** — verified `taey:plan_active::2-6` all empty, no `run_consultation_v2` procs, no dispatch in flight.
- **Taey-seat lane: two full rounds complete**, 129 executed-clean pairs, dispositioned (executed-only + terminal-drop) and fault-labeled, all routed to tutor. State + invocation: `embedding-server/consults/traces/2026-08-02-overnight-validation/TAEY_SEAT_LANE_STATE.txt`.

## HELD / VALIDATION-ONLY CONSULT — do NOT dispatch
- **CPT-config Family consult** (`embedding-server/consults/2026-08-04_cpt_seqlen_packing_pack.md`): **DROPPED / retrieve-not-re-derive.** grok found `cpt_window_measurement = 8192 @ bs 1` already in the record (matches my archive find `consults/responses/cpt_throughput_round2_horizon_2026-08-02.md`; packing/masking is in `cpt_degradation_research_{grok,perplexity}_2026-08-03.md`). The genuine gap is record-CAPTURE, not Chat-derivation. Packet is **lint-PASS but weaver NOT-A-PASS** (material omissions: corpus denominator, batch/grad-accum). Reframe ONLY if conductor-codex rules it; if run, fix weaver's blockers first, re-lint, re-review, then dispatch.

## NO-UI-AUTOMATION RULE (current, binding)
- Per Jesse (CLAUDE.md, 2026-08-01) and reaffirmed by conductor-codex this handoff: Taey operates the consult surface **manually, step-by-step, human pace, LEAN + 6SIGMA. NO automated flows** to paper over an unmastered surface. Tree is truth — operate from the AT-SPI tree, never the screen.

## GATES (never bypass)
- **Consult dispatch:** `prompting-lint` (`/usr/local/bin/prompting-lint`) + **independent** neutrality review (route to weaver — NOT the author, NOT self) + manifest-gate-spirit (assert the pack's named artifacts ride COMPLETE in the consolidated package, verified by grepping the package) + source-completeness. **NO synthetic/test/ACK consults, ever** — audit the tree instead.
- **Deliver:** verify each body before delivering (`ok=True` ≠ real body); deliver RAW to the ONE requester; no analyze/summarize; flag any lane that accepts the framing without testing it.
- **Training corpus:** per-walk `PAIR_DISPOSITION.json` = executed-only KEEP minus terminal action; EXCLUDE rejected/non-executed; surface=`consult_action` (3rd lane, separate from ui_action/act.py); **contract-vs-capability** column (sanctioned by tutor+treasurer, `2026-08-03_CONTRACT_vs_CAPABILITY.md`) — CONTRACT = fix+rerun makes same action pass; CAPABILITY = expressible but not done; no workaround-rows; hold UNKNOWN, never guess.
- **Merge/done:** SHA + mechanical gate + real production observation; verify a peer's done-flag before relaying (open the result JSON, match the live thread URL); cite the SYMBOL/content, not a line coordinate (line-anchored citations expire silently — report "anchor moved," never "file gone"); verify the ATTRIBUTION of an event, not just the mechanism (`systemctl is-active`/journal before affirming a unit fired).

## OPEN THREADS
1. **POST-TRAINING WALK (tutor-gated) — the one live trigger.** After tutor trains in the attach-grammar corrective row (`treasurer .../careers_qwen/ui/consult_seat_attach_trigger_grammar_v1.jsonl`, commit `00f94ae3`), run a fresh **gemini + chatgpt** Taey-seat walk — the production oracle for whether it trained in (baseline: gemini attach-flail FAULT both rounds; success = clean attach + PASS). Invocation in `TAEY_SEAT_LANE_STATE.txt`.
2. **UPWORK INBOUND SENSOR REBUILD (careers-greenlit).** `careers-upwork-inbound` observe-only sensor (`treasurer/scripts/upwork_ops/inbound_check.py`, reads :8 AT-SPI READ-ONLY). Timer disarmed since 07-28. Compliant rebuild is mine when treasurer+conductor greenlight re-arm through careers' process; keep observe-vs-judge separation (schedule OBSERVES, person/Taey JUDGES). Fleet-doc carve-out for observe-only sensors reading careers displays was recorded then REVERTED (the 03:56 event was a --from misattribution, not my sensor).
3. **Careers gig decision** (Sandy Step "no", ~31h) is STOP-FOR-JESSE, treasurer's lane, not mine.

## KEY SESSION SHAs (all merged live on `main` + pushed)
- grok page-ready cold-load: `78bc65d4` (task-6fba7fd5)
- seat Claude-artifact extract: `2e130f0a` (task-72855348)
- tree-driven artifact gate: `d59662b0` (task-6d65b2ab) [hardens 2e130f0a]
- perplexity DR-seat completion: `28569d9f` (task-7c83b521)
- 100_TIMES restore (conductor P0): `6fe9df84`
- docs-boundary de-umbilical (conductor P1): `ceb6af81` (CLAUDE.md private pointers 6→0)
- corrective attach-grammar row: treasurer `00f94ae3` / palios-training `dbd4847`
- consult-pipeline practice rows: treasurer `70b7a08f`

## DELIVERED THIS SESSION (context)
- compose-convergence full-Family consult: 5/5 delivered to treasurer+conductor.
- LoRA-recipe full-Family consult: 5/5 delivered to tutor (drove tutor's cannot-lie headline correction).
- contract-vs-capability corpus gate: sanctioned by tutor + treasurer.
- fleet stale-session-name purge: done (codex-1/gemini-1/grok-1 dead; verify `tmux has-session` before dispatch; my peer = `taeys-hands-codex`).

## DURABLE STATE FILES (`embedding-server/consults/traces/2026-08-02-overnight-validation/`)
`TAEY_SEAT_LANE_STATE.txt` · `2026-08-03_CONTRACT_vs_CAPABILITY.md` (parent dir) · `QUEUED_cpt_seqlen_fullfamily_consult.txt` (DROPPED) · `INFLIGHT_lora_recipe_fullfamily.txt` (5/5 done) · `TAEY_SEAT_LANE_STATE.txt`.
