# p2 Cutover Shape Decision And Contract Reconcile

Task: `consultation-clean-main::p2-cutover-shape-decision`
Date: 2026-06-17

## Decision

Decision: repair `consultation_v2` in place. Do not create a new
`consultation_clean` package.

Final supported entrypoint after cutover:

- `consultation_v2/cli.py` is the canonical user/API CLI.
- `scripts/run_consultation_v2.py` remains only as the production bus-binding
  wrapper that sets `DISPLAY`, `AT_SPI_BUS_ADDRESS`, and
  `DBUS_SESSION_BUS_ADDRESS` before importing `consultation_v2.cli`.
- Old root V1/MCP/direct/bot paths become archived paths, fail-loud stubs, or
  pure forwarders after migration.

Evidence:

- `consultations/inventory/p1_entrypoint_inventory.md:58-71` identifies
  `consultation_v2` as the best architectural candidate.
- `consultations/inventory/p1_yaml_driver_gap_map.md:22-51` shows current root
  chat YAML has zero forbidden loose matcher keys and V2 has 18 bounded matcher
  debts.
- `consultations/inventory/p1_yaml_driver_gap_map.md:73-127` says the blocker is
  V2 strict-loader/matcher permissiveness and platform YAML remapping, not a
  broad driver rewrite.
- `consultations/inventory/p1_extraction_inventory.md:34-91` shows plain
  assistant extraction is wired across all five V2 platforms.
- `consultations/inventory/p1_extraction_inventory.md:93-119` line-pins V1-only
  extraction knowledge to migrate into V2.

## Contract Reconcile

Canonical home:

- `FLOW_CONSULTATION_ENGINE.md` in this taeys-hands repo is the only canonical
  flow contract.
- `CONSULTATION_CLEAN_MAIN_PLAN.md` in this taeys-hands repo is the tracker
  source plan.
- The orchestrator commit `19320d6` copy is historical input only.

Delta note:

| Source section | Disposition in reconciled `FLOW_CONSULTATION_ENGINE.md` |
|---|---|
| Truth Register from 387-line version | Preserved and expanded under `Truth Register`. |
| Source Evidence from 387-line version | Preserved under `Source Evidence`; p1 inventory evidence added. |
| Canonical Lifecycle from 387-line version | Merged into sections `0. Scope`, `2. Request Intake`, `3. Routing`, `4. Identity`, `6. Setup`, `8. Send`, `9. Monitor`, `11. Extraction`, and `12. Storage`. |
| Production Display Substrate from both versions | Preserved under `5. Display, DBUS, And Firefox Preconditions`; p1 display retain-list referenced. |
| Concurrency Model from 387-line version | Preserved under `10. Concurrency Model`. |
| YAML And Driver Boundary from 387-line version | Preserved under `7. YAML And Matching Contract`; local exact-match language retained. |
| Extraction Contract from both versions | Preserved under `11. Extraction Contract`; output types expanded from the 387-line version and platform examples retained from the 340-line version. |
| Archive And Cutover Rule from 387-line version | Preserved under `13. Archive And Cutover Rule`; local cleanup target merged. |
| Manual Recovery from both versions | Preserved under `14. Manual Recovery`. |
| Done Evidence from 387-line version | Preserved under `16. Done Evidence`; local acceptance gate retained under `15. Current Acceptance Gate`. |
| 340-line active-root-path statement | Preserved as historical production reference in `Truth Register`; superseded by p2 decision to repair V2 in place. |
| 340-line current acceptance gates | Preserved and expanded under `15. Current Acceptance Gate`. |

Orphan handling:

- `<OPERATOR_HOME>/claude-code-fleet-orchestrator` main currently has no root
  `FLOW_CONSULTATION_ENGINE.md` or `CONSULTATION_CLEAN_MAIN_PLAN.md`.
- The old orchestrator branch containing commit `19320d6` remains historical
  git history only. The tracker is re-ingested from this repo so workers receive
  the in-repo taeys-hands contract.

## Re-Audit Gate

Status before re-audit: pending. No p2 runtime code is authorized until Gemini
cross-check and Grok adversarial audit are recorded against the final committed
contract and p0-reconcile is re-closed.
