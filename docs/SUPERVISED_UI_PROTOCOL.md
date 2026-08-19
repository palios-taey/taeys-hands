# Supervised UI protocol

Status: current protocol for the implemented local-effect `ui_action` seat. This protocol is separate from the
outward-capable `drive_chat` manual consultation lane described in `UI_INTERACTION_AUTHORITY.md`.

## Scope

The supervised seat permits `observe` and `verify`, plus `focus` and `activate` only for controls declared
`effect_class: local` in the selected platform's `supervised_ui.yaml`. Write, key, paste, navigation, page, file,
send, submit, post, purchase, delete, external confirmation, and unknown effects fail closed. A new effect class
requires a separate reviewed authority decision.

The platform and display are fixed by a supervisor-created lease and never become model-selectable arguments.
Taey proposes every call from the current projection. A supervisor may approve or reject the exact proposal but
cannot edit its operation, ref, arguments, order, or next step. Approval and execution are separate actions.

## Public projection and proposal

`consultation_v2/supervised_ui_contract.py` loads the platform's supervised policy and projects only unique mapped
controls. The model-visible projection contains an opaque lease-bound ref, policy-authored control ID and label,
allowlisted role and non-value states, permitted operations, and effect class. Runtime names, coordinates, URLs,
text values, raw dictionaries, AT-SPI objects, duplicate mappings, and unknown controls are not exposed.

A revision hashes the canonical projection inside the session lease domain. The state-specific `ui_action` schema
allows only `observe` in `needs_observe`, only `verify` in `needs_verify`, or the exact current revision/ref/operation
intersection in `action_ready`. Extra fields, parallel calls, stale refs, mismatched proposal bytes, and changed
effect classes fail closed.

## State machine

| State | Only permitted transition |
|---|---|
| `needs_observe` | Taey proposes one observe call; exact proposal waits for approval. |
| `proposal_pending` | Supervisor approves or rejects the unchanged proposal hash; nothing executes. |
| `approved_once` | Approval is bound to proposal, lease, Presence/Hands incarnations, expiry, and one execution ID. |
| `approval_spent` | Hands durably records the one-use spend before any UI primitive. |
| `execution_started` | Hands durably records start, then invokes at most one permitted primitive. |
| `observation_captured` | Fresh public projection and revision become the only live refs. |
| `action_ready` | Taey may propose one currently permitted local-effect action. |
| `action_succeeded` | A durably recorded primitive success requires a separate fresh verify turn. |
| `needs_verify` | Only a new observe/verify proposal is allowed; its approved result replaces prior refs. |
| `rejected`, `failed`, `stale`, `replayed`, `cancelled`, `indeterminate` | Terminal; no retry, resume, or implicit next turn. |

There is no backend model/action loop. A tool result never launches another model request. Restart changes the
process incarnation and invalidates every unspent prior approval. A spend or execution start without a durable
terminal outcome recovers as `indeterminate`, never as safe-to-retry.

## Execution boundary

`SupervisedUiSeat.execute_approved` captures a fresh canonical snapshot immediately before action, recomputes the
projection, revalidates revision/ref/policy/incarnations, and refuses prior spend or execution records. Only after
`approval_spent` and `execution_started` are fsynced may it invoke one `atspi_focus` or permitted local
`atspi_activate`. A durable successful outcome moves to `needs_verify`; false, stale, missing, duplicate, expired,
replayed, timeout, process loss, or persistence failure is terminal.

## Immutable receipt chain

The external receipt root must be absolute, owned by the worker, mode `0700`, nonsymlinked, and outside every public
repository. Event and exact-byte artifacts are create-once mode `0600`, no-follow, file-fsynced, directory-fsynced,
sequence-addressed, and hash-chained. Every event carries stable session, process-incarnation, turn, observation,
proposal, approval, and execution lineage as applicable.

A successful read records the session/worker handshake, exact model settings and tool declaration, exact request and
raw response bytes, pending proposal, approval, dispatch, spend, start, outcome, exact observation, and exact tool
result. An action adds the action result and `needs_verify`; the mandatory next read adds the fresh post-action
observation and verification verdict causally bound to the action. A missing exact artifact, sequence gap, hash
mismatch, replay, or noncanonical bytes makes the session inadmissible.

## Production gate

Merged code is not production proof. Release requires an authorized harmless local-effect walk in which Taey chooses
the read/action/verify proposals without a target hint; no accessibility read or action precedes approve plus execute;
only one approved primitive runs; the post-action verify uses a fresh revision; restarts reject old approvals; and the
complete out-of-repository receipt chain passes independent rehashing. Until that receipt exists, the seat is
implemented but not a proven production capture source.
