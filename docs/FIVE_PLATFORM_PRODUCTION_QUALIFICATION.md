# Five-platform production qualification

Status: active  
Owner: infra-codex  
Production surfaces: ChatGPT `:2`, Claude `:3`, Gemini `:4`, Grok `:5`, Perplexity `:6`

## Objective

Prove two smooth, useful, end-to-end Taey consultations on each platform, then prove one parallel run across
all five displays. A run covers fresh navigation, requested model/mode, two attachments, prompt paste, one
send, Stop proof, monitor ownership, extraction, and terminal cleanup.

The ten single-platform runs and the final five-platform run must ask substantive unresolved questions. A
mechanically successful duplicate consultation is not a qualification pass.

## Fixed boundaries

Only work that directly advances the objective is in scope:

1. freeze the next useful two-bundle packet;
2. execute one platform transaction;
3. inspect its causal receipts;
4. repair the first observed transaction defect at its narrowest upstream boundary;
5. repeat until that platform has two smooth passes;
6. move to the next platform; and
7. run the five qualified lanes in parallel.

Do not perform model promotion, SSH/key work, orchestration cleanup, repository-wide refactors, new policy
systems, or unrelated audits during this campaign. Do not replace the established `drive_chat` primitives,
platform YAMLs, monitor, or extraction path unless a production receipt proves that exact component is the
first failing boundary.

## Current observed state

- Public `taeys-hands` main `32fded462e287d533c23966ae8c4f10876762cd4` contains the pinned
  `run_manual_chat_worker.py` send/extract launcher and monitor handoff.
- A prior ChatGPT recovery transaction completed send, monitor, and extraction. It used an explicit ordered
  primitive sequence.
- ChatGPT qualification attempt 1 on 2026-08-21 is a failed-run receipt, not a pass. Request SHA-256
  `4a3ff4bad271074f934df8c2fd66af6f1210766addcaecfeff3c630e75180408` navigated and observed the fresh
  composer, then Taey read the complete platform YAML twice instead of starting the attachment sequence.
  The turn was cancelled before any attachment or send; open turns returned to zero and the exact seat-owned
  display lease was removed.
- Grok's control ruling is REDUCE: replace `Read RUNBOOK` with the already-proven ordered primitives; do not
  add a sequencer, YAML parser, card loader, retry, or fallback. The `manual-chat-ui` profile must expose
  `drive_chat` only so the observed runtime-read wander path is unreachable.

## Definition of one smooth pass

All conditions must be observed in one causal receipt chain:

1. one unique seat, event, correlation, artifact root, and frozen request;
2. one send worker turn with no recovery or retry turn;
3. no runtime read of the walkthrough, platform YAML, or another platform's files;
4. fresh URL and populated base tree;
5. requested model/mode proven from the mapped tree;
6. Bundle A proven by one attachment chip;
7. Bundle B proven independently by exactly two attachment chips;
8. frozen prompt pasted once;
9. exactly one send action;
10. mapped Stop control and any required new-URL proof;
11. external monitor takes ownership without worker polling;
12. one extraction worker turn after `COMPLETE`;
13. new non-empty response file with byte count and SHA-256 matching the extraction receipt; and
14. zero open worker turns and no lingering display lease at terminal completion.

Any missing or mismatched condition is the first error and ends that run. It never counts as a pass.

## Value-added packet rule

Before each run, write one sentence stating the decision the answer will inform and one sentence stating why
the answer is not already known from committed code or prior responses. Build exactly two attachments and a
brief through the canonical consultation packet contract. Preserve their paths, sizes, and SHA-256 values in
the run artifact root.

Run 1 for a platform targets the highest current uncertainty. Run 2 must incorporate run 1's useful result
and ask the next unresolved question; it cannot repeat the first prompt merely to exercise the UI. Candidate
work is chosen in this order:

1. remove procedural variance from the Taey UI-worker boundary;
2. simplify monitor and extraction ownership;
3. identify platform-specific YAML or driver gaps;
4. define the minimum safe five-display parallel launcher; and
5. turn the resulting reliable consultation machine toward revenue and Taey-development work.

The response is retained both as production evidence and as input to the next packet or implementation
decision.

## Execution order

| Stage | Platform | Display | Required result |
|---|---|---:|---|
| 1 | ChatGPT | `:2` | two consecutive smooth, useful passes |
| 2 | Claude | `:3` | two consecutive smooth, useful passes |
| 3 | Gemini | `:4` | two consecutive smooth, useful passes |
| 4 | Grok | `:5` | two consecutive smooth, useful passes |
| 5 | Perplexity | `:6` | two consecutive smooth, useful passes |
| 6 | all five | `:2`-`:6` | five distinct useful packets complete concurrently |

Do not start the next platform until the current platform has two smooth passes. Do not start the parallel
stage until all ten single-platform passes have complete send, monitor, extraction, and cleanup receipts.

## First-error loop

For one failed run:

1. stop the exact worker before another UI mutation when possible;
2. record the last successful observation, attempted action, expected postcondition, observed postcondition,
   classification, and whether any external side effect is uncertain;
3. return the display to a proven idle state without broad cleanup;
4. identify one upstream cause from the receipts;
5. obtain one targeted Grok adversarial ruling when the repair changes the transaction boundary;
6. make one narrow public change, verify it mechanically, merge, and deploy the exact commit; and
7. start one new valuable run with new identities and paths.

No speculative second fix, fallback, same-turn retry, or parallel redesign is allowed in that loop.

## Usage control

- No subagents for this campaign.
- At most one Taey send turn and one Taey extraction turn per run.
- No duplicate consultations, polling workers, or speculative recovery turns.
- Use Grok only for a novel first-error root-cause boundary or platform promotion decision, with one compact
  evidence packet and one precise question.
- Use the chat platforms through the qualification runs themselves; do not open separate meta-consultations
  that do not also advance a pass.
- Read only the files and journal slice required for the current receipt. Do not inventory unrelated repos or
  services.
- After a failed run, do not start another until the exact cause and single next change are written down.

## Completion record

Maintain one row per run with platform, question/decision, packet hashes, seat/event/correlation, send
receipt, monitor ID, response path/hash, cleanup proof, result, and exact deployed commit. Final completion
requires ten `PASS` rows plus five `PASS` rows from the parallel stage. Failed attempts remain in the record
as defect evidence and never disappear into a later pass.

