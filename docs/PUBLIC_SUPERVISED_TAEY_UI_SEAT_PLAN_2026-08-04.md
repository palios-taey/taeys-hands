# Public supervised Taey UI seat — implementation plan + protocol spec

Status: **IMPLEMENTED and merged on `main`** (2026-08-04) — the seat, contract, receipts, per-platform
policy, runner, and design-rule gate landed via PRs #22–#25 (`consultation_v2/supervised_ui_seat.py`,
`supervised_ui_contract.py`, `supervised_ui_receipts.py`, `platforms/<p>/supervised_ui.yaml`,
`scripts/run_supervised_ui_seat.py`, `validators/validate_supervised_ui_design_rules.py`). This
document remains the authoritative **protocol spec** (state machine, exact model request, receipt
chain, production-walk gates). The **production validation walk (below) is the outstanding gate** —
the code merge is not the production oracle; a real supervised trajectory with a complete immutable
receipt chain is still required before capture releases. Canonical UI authority + grammar:
[`UI_INTERACTION_AUTHORITY.md`](UI_INTERACTION_AUTHORITY.md).

The minimum seat performs one model request, accepts exactly one proposed tool
call, pauses for an explicit supervisor decision, executes at most that one
approved call, captures the exact result, and requires a new observe/verify
turn before any further action. It has no autonomous loop and no scripted
action sequence.

This plan was produced without UI automation, display binding, screenshots,
live accessibility reads, model generation, or outward action.

## Scope and authority

P0 supports only:

- `observe` and `verify`, which read a filtered accessibility projection; and
- `focus`, plus `activate` only for controls explicitly declared
  `effect_class: local` in a new supervised-seat policy.

P0 excludes write, key, paste, navigation, page, file, send, submit, post,
purchase, delete, and external-confirmation operations. Unknown effects fail
closed. Adding any outward or value-bearing operation requires a separate
authority-provider design and review; it is not an extension hidden inside
this plan.

The platform and display are bound by a supervisor-created session lease. They
never appear as model-selectable arguments.

## Self-training boundary

The seat exists so Taey, not the supervisor, performs the real manual UI walk.
Taey reads the live projection, proposes every read, action, and validation
call, and decides what to do next from the exact fresh result. There is no
target action path, prescribed operation order, expected ref, or hidden
operator-selected next step.

The supervisor may only approve or reject the immutable proposal for authority
and safety. Approval means “this exact Taey-chosen call may execute once.” The
supervisor cannot edit arguments, substitute a ref or operation, choose the
order, request a particular next action, or turn a rejection into a different
call. The next-turn control asks Taey to decide again; it supplies no action
hint.

Taey confusion, invalid proposals, refusals, failures, and blocked states are
captured exactly as outcomes, not corrected inside the session. A corrected
attempt may occur only in a new session with explicit, durably captured
feedback describing the observed rule/failure. That feedback must not name the
target ref, operation, order, or next call; Taey still elects every tool call.
The original failed session remains immutable and is never overwritten or
resumed.

The canonical tracker dependency is:

- `taey-training-program::p0-ui-supervised-seat-design` — this reviewed public
  seat and adapter-boundary design; the build task depends on this design.

The exact canonical capture-release gates are:

- `taey-training-program::p0-ui-supervised-seat-build` — implement and
  production-observe the reviewed supervised seat; and
- `taey-training-program::p0-ui-capture-privacy-boundary` — implement and
  production-observe the external private-store and pre-persistence privacy
  contract.

These exact task IDs replace the earlier informal blocker labels. The design is
not a substitute for the build, and `p2-ref-engineering` is not a substitute for
either capture-release gate. A completed task status without its required
reviewed and production-observed evidence does not release capture.

## Documents-first baseline

### taeys-hands

The public code baseline is
`palios-taey/taeys-hands@258b49457c52de8608a6fd757c867026f8d8a2cf`.

- Reuse `build_snapshot` unchanged for the actual public AT-SPI/YAML read
  (`consultation_v2/snapshot.py:662`).
- Keep `ElementRef` internal. It contains coordinates, a live AT-SPI object,
  and raw scan data and must never be serialized to the model
  (`consultation_v2/types.py:158-184`).
- Do not use `Snapshot.serializable()` as the model projection because it
  exposes URL, unknown elements, and coordinates through element serialization
  (`consultation_v2/types.py:238-247`).
- Reuse `atspi_focus` and `atspi_activate` unchanged after revision/ref/policy
  validation (`consultation_v2/interact.py:91-103,132-145`).
- Do not use `ConsultationRuntime.click` or `SeatActions.click/paste_into`;
  their coordinate fallback and hidden-read behavior violate the exact
  contract (`consultation_v2/runtime.py:441-476`;
  `consultation_v2/seat_actions.py:113-240`).
- Copy the ordering invariant, not the semantic tool loop, from
  `TaeyConsultExtractionSeat._call_taey`: canonical request bytes are written
  before network I/O and raw response bytes before parsing
  (`consultation_v2/taey_extract.py:770-835`).

History confirms the shared snapshot types originated in public commit
`f2175977`; the duplicate-match refusal was added in `c86bf4de`; the current
SeatActions surface came from `3693f9b4`; and exact consultation request
capture came from `15274fe0`.

### taey-presence

The public code baseline is
`palios-taey/taey-presence@e0cd1b163640d8e69f79b6dd3de839dc22794771`.

- `dashboard/app.py:2173-2200` has a durable-session request path but currently
  sends an empty tool list.
- `dashboard/app.py:2013,2742` defines two legacy stream handlers with the same
  Python name. The new seat uses a distinct router and route namespace.
- `serving/taey_seat.py:182-259` demonstrates append-only, locked, fsynced,
  private-mode event durability.
- `serving/taey_seat.py:481-559` accepts assistant content only and cannot
  preserve or return a tool-call proposal.
- `serving/soma_proxy.py:2157` owns an automatic tool loop. The supervised UI
  seat must call the configured chat-completions endpoint directly and must
  never register UI actions with that loop.

Relevant public history is `f01ee6f` (durable seat), `6eb674c` (unified event
history), `1873a57` (bounded packet context), `a1918d4` (dashboard/event-log
join), `59a6996` (private-mode session logs), and `66d14d4`/`168deca`
(automatic proxy tools, deliberately excluded here).

## GitNexus impact result

Both repositories were re-indexed before this plan.

| Existing symbol | Upstream risk | Planning consequence |
| --- | --- | --- |
| `ElementRef` | HIGH, 29 impacted | Do not edit; wrap with a separate public projection. |
| `Snapshot` | HIGH, 29 impacted | Do not edit; compute revision outside the shared type. |
| `load_platform_yaml` | CRITICAL, 57 impacted across 12 flows | Do not edit; load a separate supervised policy. |
| `build_snapshot` | MEDIUM, 22 impacted | Call unchanged. |
| `ConsultationRuntime` | MEDIUM, 14 impacted | Do not extend for P0. |
| `SeatActions` | LOW, 5 impacted | Do not reuse because its semantics are wrong for this boundary. |
| `atspi_focus` | LOW, 1 impacted | Call unchanged after validation. |
| `atspi_activate` | LOW, 1 impacted | Call unchanged only for declared local effects. |
| `atspi_click` | CRITICAL, 13 impacted across 9 flows | Do not edit or call. |
| Presence `chat_stream`, `chat_hybrid`, `chat_completions`, `execute_tool_call` | LOW in current index | Do not edit; isolate the new flow. |
| Presence `chat_session_stream`, `EventStore`, `ProxyClient`, `RoundLedger` | UNKNOWN | GitNexus did not resolve these source-present symbols; treat the coverage gap as a block against editing them. |

No HIGH or CRITICAL shared symbol is an implementation target.

## State machine

Only a supervisor action advances the state after a model response or tool
result.

| State | Permitted transition |
| --- | --- |
| `needs_observe` | Supervisor requests one model turn whose live schema permits only `observe` or `verify`. |
| `proposal_pending` | Supervisor approves or rejects the exact Taey-chosen proposal hash without editing it. Nothing executes. |
| `approved_once` | Approval is bound to the current Presence and Hands incarnation IDs. Restart invalidates it. |
| `approval_spent` | Hands has fsynced the one-use spend record. Replay fails even after restart. |
| `execution_started` | Hands has fsynced the execution-started record and may now invoke one AT-SPI primitive. |
| `observation_captured` | The exact result becomes the sole source of live refs; supervisor may request the next model turn. |
| `action_ready` | The model request schema contains only refs/operations allowed by the current projection and policy. |
| `proposal_pending` | The action proposal again waits for approval or rejection. |
| `action_succeeded` | Only an observed successful primitive outcome becomes `needs_verify`; action operations disappear from the next schema. |
| `needs_verify` | Supervisor may request only a new `observe`/`verify` proposal. On its approved result, a new revision/ref set replaces the old one. |
| `rejected`, `failed`, `stale`, `replayed`, `cancelled`, `indeterminate` | Terminal for the session. No retry, resume, or implicit next turn. |

There is no backend `while` loop. A tool result never triggers another model
request. The visible supervisor control is the only next-turn trigger.
That trigger carries no proposed ref, operation, order, or action hint.

## Exact model request

Presence builds canonical UTF-8 JSON bytes containing:

- the configured model identifier;
- the complete generation settings, timeout contract, stream setting, and
  chat-template settings;
- bounded messages, including exact prior assistant tool-call and exact tool
  result bytes;
- the complete exact declaration of one strict function named `ui_action`;
- `tool_choice` forced to `ui_action`;
- `parallel_tool_calls: false`; and
- thinking disabled.

The state-specific schema is generated from the current Hands response:

- In `needs_observe`/`needs_verify`, `op` is restricted to `observe` or
  `verify`; ref and revision are absent.
- In `action_ready`, `revision` is a JSON-schema constant and `ref` is an enum
  of current refs. `op` is restricted to the intersection of that ref's
  declared operations and the P0 effect policy.
- `additionalProperties` is false at every object boundary. The model cannot
  select a platform, display, effect class, authority token, or value.

Presence writes the exact request bytes and SHA-256 before network I/O, then
holds the raw response bytes in memory for the pre-persistence privacy gate.
Only a response envelope containing the allowed tool-call fields, no private or
credential pattern, no free assistant content, and exactly one `ui_action` call
may be written. The exact raw bytes and SHA-256 are then persisted before
business parsing or proposal display. The pre-persistence parse is restricted
to privacy/envelope validation and may not normalize, rebuild, or replace the
raw bytes. A privacy rejection is terminal and its raw bytes are not written
anywhere.

## Public Hands contract

Add these isolated symbols; do not alter the shared snapshot types or loader.

### `consultation_v2/supervised_ui_contract.py`

- `load_supervised_policy(platform)` loads only
  `consultation_v2/platforms/<platform>/supervised_ui.yaml` and rejects unknown
  keys/effects.
- `project_snapshot(snapshot, lease_secret)` allowlists unique mapped elements
  only. Each public element contains `ref`, a policy-authored safe `control_id`
  and `label`, an allowlisted role enum, normalized non-value states, permitted
  operations, and `effect_class`. Runtime accessible names are used only for
  internal matching and are omitted before model visibility or persistence.
  The projection contains no runtime name, coordinate, URL, text/value,
  description, raw dict, or AT-SPI object.
- `snapshot_revision(projection, lease_secret)` hashes canonical projected
  bytes plus the session lease domain. Equal projections within one lease have
  equal revisions; cross-session correlation is prevented.
- `build_live_ui_action_schema(state, projection)` emits the state-specific
  strict schema described above.
- `validate_approved_call(call, approval, projection)` requires exact proposal
  hash, revision, ref, operation, effect class, unexpired lease, and unused
  approval identifier.

Refs are stable HMAC pseudonyms of the session lease and unique public mapping
key. If a mapping key resolves to multiple elements, it is omitted and a
collision receipt is emitted; coordinates are never used to disambiguate.
Policy-authored identifiers and labels must pass the same public/privacy gate
as code before they can enter a model request. Policy declares capability and
effect only; it contains no recommended order, target sequence, expected next
control, or corrective answer.

### `consultation_v2/supervised_ui_receipts.py`

- `HandsReceiptStore.open_external(root, public_repo_roots)` validates the
  absolute out-of-repository root, nonsymlink ancestry, and exclusive directory
  modes before a session or worker incarnation is created.
- `HandsReceiptStore.write_once(event, raw_bytes)` creates one immutable,
  sequence-addressed receipt with the required exclusive/no-follow flags,
  file/directory fsync ordering, stable causal IDs, and hash-chain link.
- `HandsReceiptStore.recover_incarnation()` never resumes an old incarnation;
  it records every prior spend/start lacking a durable outcome as terminal
  `indeterminate` and returns a new incarnation ID.

### `consultation_v2/supervised_ui_seat.py`

- `SupervisedUiSeat.observe(lease)` calls `build_snapshot`, applies the
  supervised policy, records the internal ref binding in memory, and returns
  canonical public projection bytes.
- `SupervisedUiSeat.execute_approved(call, approval)` performs a fresh
  `build_snapshot`, recomputes the projection, requires the requested revision
  and ref binding to remain current, verifies both process incarnation IDs, and
  refuses any prior spend or execution record. Before AT-SPI it must durably
  fsync `approval_spent` and then `execution_started`, each bound to the stable
  session/proposal/approval/execution IDs. Only after both writes succeed may it
  call exactly one of `atspi_focus` or permitted local-only `atspi_activate`.
- The worker starts with a fresh random `hands_incarnation_id`; Presence has a
  separate `presence_incarnation_id`. Approvals bind both. Any restart
  invalidates every unspent approval from the previous incarnation. At startup,
  a spend or execution-start record without a terminal outcome is marked
  `indeterminate`; it is never resumed or retried.
- An observed successful primitive outcome is fsynced as `execution_outcome`
  before the exact action-result bytes are returned. Only that success yields
  `next_required: verify`. False, stale, missing, duplicate, expired, replayed,
  timeout, worker exit, response loss, or failure to persist an outcome is a
  terminal loud failure. A timeout or crash after `execution_started` is
  `indeterminate` even when no visible effect is apparent.
- The action result contains the primitive verdict, stable causal IDs,
  proposal/approval hashes, input revision, ref, and required next state. It
  does not contain a fabricated post-action tree. The next separately proposed,
  approved, and executed read produces a fresh tree and verification verdict.

### `scripts/run_supervised_ui_seat.py`

Expose a versioned newline-delimited JSON stdio protocol. The worker is bound
at startup to one supervisor-supplied platform/display lease, processes one
request at a time, and accepts only `observe`, `execute_approved`, `cancel`, and
`close`. The command has no operator-specific default and fails loud when its
lease inputs are absent.

The worker also requires an absolute external receipt root. It rejects a
missing/relative root, any root inside or beneath a public repository, a
symlink root or symlink path component, and any directory not exclusively
mode `0700`. Every immutable event/raw artifact is created once with mode
`0600` and `O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW`, then file-fsynced and
directory-fsynced. It never appends to or replaces an existing receipt.

This stdio boundary avoids a new network listener and new Hands dependencies.
It also makes private ATS an optional adapter: an adapter can implement the
same public protocol and return opaque receipt hashes, but no public module
imports or locates private code.

## Public Presence contract

Add these isolated symbols rather than editing the legacy chat/tool loops.

### `dashboard/supervised_ui.py`

- `SupervisedUiLedger.append_exact(kind, raw_bytes, lineage)` creates a
  create-once receipt plus its SHA-256 under a mandatory absolute external root
  outside every public repository. The root and per-session directories are
  real nonsymlink directories with mode `0700`. Receipt files are mode `0600`,
  opened with `O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW`, file-fsynced, and followed
  by a parent-directory fsync. Missing root, unsafe ancestry, symlink, wrong
  mode, name collision, or fsync failure aborts the session before network or
  UI effects. It uses the ordering demonstrated by `EventStore.append` but does
  not modify that unresolved shared class.
- `HandsSeatClient` starts the configured Hands command with
  `asyncio.create_subprocess_exec` (never a shell), performs version handshake,
  serializes one request at a time, and fails loud on missing configuration,
  protocol mismatch, timeout, extra output, or worker exit.
- `SupervisedUiSession.request_model_turn()` fetches the current live schema,
  writes exact request bytes, performs one non-streaming chat-completions call,
  writes the raw response, records exactly one proposal, and returns without
  executing it.
- `SupervisedUiSession.decide_proposal()` records approve/reject. Approval
  creates a durable approval record and mints a one-use secret whose digest is
  in that record. Both bind actor, proposal hash, revision, ref, operation,
  effect class, expiry, and the current Presence/Hands incarnation IDs. The
  secret is never persisted or exposed to the model; restart therefore
  invalidates an unspent approval rather than making it replayable.
- The decision endpoint requires an authenticated supervisor session and an
  origin-bound anti-forgery token. The approval actor is derived by the server,
  never accepted as a caller-supplied identity. The endpoint and credential are
  absent from the model tool surface and transcript.
- `SupervisedUiSession.decide_proposal()` accepts no replacement arguments.
  Any body field that attempts to alter the ref, operation, order, revision, or
  tool arguments is rejected. The approved proposal bytes must hash exactly to
  the model response proposal.
- `SupervisedUiSession.execute_approved()` sends that one capability to Hands,
  first fsyncs an execution-dispatch record, then requires Hands' durable
  `approval_spent` and `execution_started` acknowledgement before accepting an
  outcome. Only an observed and durably recorded success transitions to
  `needs_verify`. Every other outcome is terminal; a timeout, restart, or lost
  response after dispatch is `indeterminate` and cannot be retried.
- A dedicated `APIRouter` exposes session-open, next-model-turn,
  proposal-decision, execute-once, state, and event-stream endpoints under
  `/api/supervised-ui/v1/`.

The configured Hands command and chat endpoint are mandatory. Neither receives
an operator-specific or private-topology default. The model transcript never
receives the one-use capability.

Before any exact artifact is persisted, Presence applies a fail-closed envelope
allowlist plus credential/private-value scanning. P0 accepts policy-authored
objective text and labels only; it accepts no arbitrary user text. Rejected raw
bytes are discarded from memory and represented publicly only by a refusal
class, never by content, length, or a low-entropy value hash.

### `dashboard/static/index.html`

Add a separate supervised-seat panel that shows:

- current state and revision;
- the exact proposed operation/ref/effect class;
- request, response, proposal, approval, execution, and result hashes;
- Approve, Reject, Execute once, and Request next turn controls; and
- a permanent warning when an operation is excluded or effect is unknown.

Approve and Execute are separate controls so approval does not silently cause
an action. The UI disables every control that is invalid for the current
state. It exposes no ref picker, operation picker, argument editor, target
sequence, or “recommended next action.” Server state remains authoritative.

## Receipt chain

Every event carries stable `event_id`, `session_id`,
`presence_incarnation_id`, `hands_incarnation_id`, `turn_id`, and applicable
`observation_id`, `proposal_id`, `approval_id`, and `execution_id`; an exact UTC
timestamp; an incarnation-local monotonic timestamp; monotonically increasing
sequence; `caused_by_event_id`; prior event hash; payload hash; event hash;
contract version; and public repository commit IDs.

The minimum successful read chain is:

1. `session_opened`
2. `worker_handshake`
3. `model_settings_exact`
4. `tool_declaration_exact`
5. `model_request_exact`
6. `model_response_exact`
7. `proposal_pending`
8. `approval_recorded`
9. `execution_dispatch_started`
10. `approval_spent`
11. `execution_started`
12. `execution_outcome`
13. `observation_exact`
14. `tool_result_exact`

An action repeats steps 3-12 with action-constrained live declarations, then
records `action_result_exact` and `state_needs_verify`. The mandatory next read
repeats the complete read chain and ends with `post_action_observation_exact`
and `verification_verdict`, causally binding the before revision, action ref,
execution outcome, fresh after revision, and policy-authored postcondition.
Only then can the state return to `action_ready`.

Rejection records `proposal_rejected` and has no consumption or tool result.
Any sequence gap, hash mismatch, noncanonical replay, or missing exact byte
artifact makes the session inadmissible.

The exact model settings, full tool declarations, request body, raw response,
action result, and observation result are immutable byte artifacts, not fields
reconstructed from summaries. If any artifact is absent, a builder must reject
the chain; hashes or parsed ledger fields cannot be used to recreate it.

## Production validation walk

This walk occurs only after adversarial review, implementation, public
topology/credential gates, and operator authorization. It uses a dedicated
publicly configured display and a harmless local surface. No send, submit,
write, navigation, file, or external-confirmation control is exposed.

1. Start Presence and the Hands worker from documented public configuration;
   confirm both report their public commit IDs and contract version.
2. Open a supervised session. Confirm state is `needs_observe` and the first
   exact model request schema contains only `observe`/`verify`.
3. Let Taey propose one read. Confirm no accessibility read occurs before the
   supervisor presses Approve and then Execute once.
4. Capture the resulting filtered tree/revision/ref bytes and hashes. Confirm
   the next live schema includes only policy-approved local operations for
   current refs.
5. Ask Taey for its next turn without naming an operation or ref. If Taey
   proposes one currently permitted local action, confirm the UI is unchanged
   before approval. If approved, execute that exact proposal once; confirm
   `approval_spent` and `execution_started` were fsynced before the one AT-SPI
   call, then confirm only a durable successful outcome produced
   `needs_verify`. If Taey is confused, proposes an invalid/unsafe call, or
   refuses, record the exact outcome and end the session.
6. Confirm the next schema again exposes only `observe`/`verify`. Approve one
   read and verify the fresh post-action observation plus verification verdict
   are causally hash-chained to the preceding action result.
7. Ask Taey for another unhinted turn from the new tree. Approve a second
   independently proposed local-only action only if its exact Taey-chosen
   control is explicitly safe under public policy. Execute once and require
   another Taey-proposed explicit read. If Taey does not choose a safe second
   action or the live surface lacks one, stop and record the exact blocked or
   failed outcome; do not invent, select, or pre-script it.
8. Inspect the production receipt chain: exact request and response bytes,
   complete settings and tool declarations, proposal/approval equality,
   durable pre-effect spend/start, incarnation binding, single-use capability
   consumption, explicit execution outcome, tree/action ref equality, revision
   equality, fresh post-action observations, verification verdicts, and zero
   outward effects.
9. In a separate authorized non-effect run, restart each process with an
   unspent approval and verify the old incarnation is rejected. Do not inject a
   crash after AT-SPI. Instead inspect the production recovery path against a
   naturally interrupted or no-effect boundary receipt if one exists; absent
   such a receipt, crash-after-start behavior remains unproven and blocks
   capture rather than being simulated on a live UI.
10. If the first session exposed a correctable Taey failure, open a new session
    with exact feedback about the prior observed failure class. Confirm the
    failed chain remains immutable, the new session has new incarnation and
    causal IDs, the feedback names no target call, and Taey independently
    chooses every read/action/validation call.

The production oracle is the real receipt chain and observed UI state. No
generated fixture can substitute for it.

## Mechanical and adversarial gates

Before implementation is authorized:

- a fresh peer must try to find a path that executes without approval, replays
  an approval across a crash/restart or incarnation change, retries an
  indeterminate effect, uses a stale ref, leaks runtime names/raw/private data,
  writes receipts into a public repo or through a symlink, invokes a coordinate
  fallback, enters the automatic proxy loop, reconstructs a missing exact
  artifact, or generates an implicit next turn;
- the reviewer must try to find any surface where a supervisor can choose or
  edit a ref, operation, argument, order, or next action, or where a scripted
  target path is present in prompts, UI state, policy, or validation steps;
- the owner must resolve the Presence duplicate-route ambiguity and confirm
  the new distinct namespace is registered exactly once; and
- the owner must approve the initial per-platform local-effect policy.

Before the production walk:

- GitNexus impact must be rerun for every actually edited existing symbol;
- staged change detection must show only the reviewed supervised-seat surface;
- public-tree scans must contain no credential, private topology, operator
  path, or private application identity; and
- the external receipt-root gate must prove absolute out-of-repo placement,
  `0700` directories, create-once `0600` no-follow files, and restart
  invalidation before a live request; and
- both processes must fail loud with missing contract, endpoint, display,
  platform, lease, or policy configuration.

Implementation remains blocked until this adversarial review returns a written
verdict and all findings are resolved.
