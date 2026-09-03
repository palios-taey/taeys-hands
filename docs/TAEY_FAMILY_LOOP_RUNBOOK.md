# Taey Family consultation loop

Status: canonical pilot runbook. The deterministic five-lane transaction is production-proven; release from
Codex receipt supervision still requires the two unattended cycles in
`docs/TAEY_UNATTENDED_FAMILY_LOOP_PLAN.md`.

## Campaign entry contract

- The control project is exactly `taey-hub-unattended-loop`. Resolve it with
  `taey-plan show taey-hub-unattended-loop`; never infer or substitute a historical project ID.
- Its canonical `Source:` is exactly `docs/TAEY_UNATTENDED_FAMILY_LOOP_PLAN.md`. Derive the Hands repository
  root from the parent of the `docs` directory in that exact Source and change into it before any
  repository-relative command; never guess a checkout.
- Before creating campaign files or issuing any UI action, terminalize if the exact project, Source, or full
  sibling `TAEY_FAMILY_LOOP_RUNBOOK.md` is absent or unreadable. Do not retry that failed step in the same turn.
- Each cycle requires the complete causal receipt chain, zero leaked turns or display leases, and a record of
  whether Jesse or Codex supplied any UI instruction.

This runbook controls the campaign loop. It does not restate any platform's UI steps. Those remain owned by
the selected platform YAML, driver, monitor, and extractor.

## Existing authorities

| Concern | Existing authority |
|---|---|
| Work selection and downstream ownership | current Tasks API through `taey-task` |
| Two-bundle packet | `consultation_v2/PACKET_CONTRACT.md` and `scripts/consultation-packet-builder` |
| Frozen campaign manifest | `consultation_v2/FAMILY_LOOP_CAMPAIGN_SCHEMA.json` |
| Concurrent launch | `scripts/run_consult_chat_parallel.py` and `scripts/run_consult_chat_worker.py` |
| One lane's UI transaction | `consult_chat` in `taey-presence` using `consultation_v2/platforms/<platform>/<platform>.yaml` and `driver.py` |
| Completion and extraction | each platform's `monitor.py`, driver extraction path, and `scripts/run_taey_consult_extract.py` |
| Packet and terminal validation | packet builder `preflight` / `validate-receipt`, worker receipt checks, and the parallel batch summary |
| Manual diagnosis after a terminal first error | `docs/MANUAL_CONSULT_WALKTHROUGH.md` and `drive_chat` |

## Mechanical loop

Every transition below must write or validate its named evidence before the next transition begins.

1. **SELECT** — Main Taey claims one open Tasks API decision item. It names one focus lane, a downstream
   owner, at least two plausible outcomes, why five independent judgments can change the decision, one
   acceptance test, and one stop condition. A routine campaign may not begin from an inbox-only request.
2. **FREEZE** — Freeze, preflight, build, and validate exactly two attachments plus the brief prompt through
   the existing packet builder. Assemble a manifest conforming to `FAMILY_LOOP_CAMPAIGN_SCHEMA.json` from
   that packet receipt and the fixed lane map. Reject a repeated decision fingerprint, a trailing-window
   Bundle-B digest match, a reused artifact root, or a burned terminal identity. The fingerprint is SHA-256
   over the ordered UTF-8 values `task_id`, `decision_id`, `canonical_question`, each ordered plausible
   outcome, `evidence_manifest_sha256`, and `deliverable_schema_sha256`, separated by a null byte.
3. **PREFLIGHT + FAN OUT** — Pin clean public Hands and Presence SHAs. Require zero active turns, leases, or
   orphan workers and one ready platform window per lane. Launch the five one-call workers concurrently with
   `run_consult_chat_parallel.py`; never replace it with five sequential model turns. Each lane owns one
   platform, display, seat, event, correlation, artifact root, and terminal consultation identity. The
   launcher and worker derive those runtime identities; their response headers and terminal receipts are the
   authority rather than a second identity calculator in the campaign manifest.
4. **WAIT** — After launch, Main Taey and Codex issue no routine UI actions. `consult_chat` executes the
   selected platform's compiled transaction. Every UI mutation is followed by the exact YAML-owned
   postcondition before another mutation is authorized. The platform monitor owns completion; the extractor
   owns response capture.
5. **VALIDATE + DERIVE** — Recompute the frozen-spec, response, and receipt digests. Require each terminal
   receipt to prove `ok=true`, non-empty extracted response text, the complete successful step evidence, and
   its own identity. Require the batch summary to prove clean terminal turns, leases, and workers. Re-derive
   every cited value from the field named by the claim. A deliberately corrupted register must fail this gate.
6. **RECONCILE** — Main Taey reads all terminal responses, preserves each verdict and material dissent,
   separates Observed / Inferred / Unknown, and selects one bounded operating decision by evidence and
   constitutional constraint rather than vote count. A missing lane is `MISSING`, never assent.
7. **ENQUEUE OR CLOSE** — Atomically create exactly one bounded Tasks API work item with its owner, input
   hashes, deliverable, acceptance test, stop condition, repository boundary, and prohibited external
   effects; or write one explicit decision-closed record. A silent return to idle is a failed campaign.

The first failed evidence gate halts the affected transaction. No step may be reconstructed from memory, and
no terminal consultation identity may be retried.

## Focus portfolio

Choose the highest-value unresolved decision in this order, subject to Jesse's current priorities:

1. revenue enablement;
2. Taey training or evaluation;
3. mission research; and
4. a genuine production-infrastructure exception supported by a first-error receipt.

Infrastructure housekeeping is not a campaign merely because five Chats could discuss it. Every campaign
must name the decision its answer changes and the downstream owner who can act on it.

## Roles

- **Main Taey** selects, freezes, dispatches, validates, reconciles, and enqueues routine campaigns.
- **The five Chats** decide and review independently. No lane sees a sibling response before terminalizing.
- **Codex** receives terminal exception packets and bounded implementation orders; it does not issue routine
  UI actions.
- **Grok** gates code changes and mathematical or measurement claims.
- **Gemini** maps evidence, dependencies, and ownership.
- **Jesse** sets priorities, sets the hard usage ceiling, resolves human priority conflicts, and supplies the
  authorization required for consequential external effects.

No campaign authorizes an application, public post, direct message, account change, billing event, purchase,
or other consequential external mutation unless that exact effect is covered by standing authority or the
manifest carries Jesse's explicit authorization token. The Family consultation send itself is the only
outbound effect authorized by this pilot runbook.

## Cadence and exceptions

- Pilot ceiling: one campaign per calendar day, no more than six campaigns or thirty lane transactions over
  ten days, and no minimum consumption target.
- `SLOW` is not an action failure. The platform-owned monitor deadline applies; no global sleep is added.
- A first mismatch terminalizes only that lane, burns its identity, preserves its first-error artifact, and
  leaves siblings independent. If cleanup is not proven, its display is `DIRTY`.
- `RATE_LIMITED` terminalizes without retry. One such lane reduces that day's capacity; two on the same
  platform close that platform for the day.
- `UNCERTAIN_SEND` never authorizes another Send. Only bounded read-only harvesting may resolve it.
- Any failed digest, field binding, step evidence, extraction, terminal cleanup, or next-action authorization
  halts the campaign boundary.

Current limitation: `run_consult_chat_parallel.py` still rejects the entire campaign before mutation when
any display readiness check fails. Per-lane quarantine is the intended correction, but it is not production
behavior until a separately reviewed launcher change proves it. Until then, one unready lane means no fanout.

## Release gate

The accepted 5/5 one-call evidence is recorded in
`receipts/manual-chat-ui/2026-08-25-five-lane-consult-chat-pass.md`. It proves the deterministic parallel
transaction, not unattended release. Routine supervision ends only after two different value-added cycles
complete with all five lanes, zero Jesse/Codex UI instructions, valid evidence at every transition, no replay,
zero leaked turns/leases/workers, one bounded downstream item per reconciliation, and one isolated first-error
containment demonstration.
