# Public supervised Taey UI seat — implementation plan

Status: **documents-first plan; implementation blocked pending adversarial
review.**

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
| `proposal_pending` | Supervisor approves or rejects the exact proposal hash. Nothing executes. |
| `approved_once` | The one-use approval is consumed by exactly one Hands request. Replay fails. |
| `observation_captured` | The exact result becomes the sole source of live refs; supervisor may request the next model turn. |
| `action_ready` | The model request schema contains only refs/operations allowed by the current projection and policy. |
| `proposal_pending` | The action proposal again waits for approval or rejection. |
| `action_captured` | State becomes `needs_verify`; action operations disappear from the next schema. |
| `needs_verify` | Supervisor may request only a new `observe`/`verify` proposal. On its approved result, a new revision/ref set replaces the old one. |
| `rejected`, `failed`, `stale`, `cancelled` | Terminal for that proposal. No retry or implicit next turn. |

There is no backend `while` loop. A tool result never triggers another model
request. The visible supervisor control is the only next-turn trigger.

## Exact model request

Presence builds canonical UTF-8 JSON bytes containing:

- the configured model identifier;
- bounded messages, including exact prior assistant tool-call and exact tool
  result bytes;
- exactly one strict function named `ui_action`;
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
writes the raw response bytes and SHA-256 before parsing. A response is valid
only when it contains one assistant `ui_action` call and no second call. The
proposal is recorded durably before it is shown for approval.

## Public Hands contract

Add these isolated symbols; do not alter the shared snapshot types or loader.

### `consultation_v2/supervised_ui_contract.py`

- `load_supervised_policy(platform)` loads only
  `consultation_v2/platforms/<platform>/supervised_ui.yaml` and rejects unknown
  keys/effects.
- `project_snapshot(snapshot, lease_secret)` allowlists unique mapped elements
  only. Each public element contains `ref`, `key`, `role`, `name`, normalized
  states, permitted operations, and `effect_class`. It contains no coordinate,
  URL, text/value, description, raw dict, or AT-SPI object.
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

### `consultation_v2/supervised_ui_seat.py`

- `SupervisedUiSeat.observe(lease)` calls `build_snapshot`, applies the
  supervised policy, records the internal ref binding in memory, and returns
  canonical public projection bytes.
- `SupervisedUiSeat.execute_approved(call, approval)` performs a fresh
  `build_snapshot`, recomputes the projection, requires the requested revision
  and ref binding to remain current, consumes the one-use approval, and calls
  exactly one of `atspi_focus` or permitted local-only `atspi_activate`.
- The action result contains the operation verdict, proposal/approval hashes,
  input revision, ref, and `next_required: verify`. It does not include a
  fabricated post-action tree. The next explicit read produces that tree.
- An uncertain, false, stale, missing, duplicate, expired, or replayed request
  is a terminal loud failure.

### `scripts/run_supervised_ui_seat.py`

Expose a versioned newline-delimited JSON stdio protocol. The worker is bound
at startup to one supervisor-supplied platform/display lease, processes one
request at a time, and accepts only `observe`, `execute_approved`, `cancel`, and
`close`. The command has no operator-specific default and fails loud when its
lease inputs are absent.

This stdio boundary avoids a new network listener and new Hands dependencies.
It also makes private ATS an optional adapter: an adapter can implement the
same public protocol and return opaque receipt hashes, but no public module
imports or locates private code.

## Public Presence contract

Add these isolated symbols rather than editing the legacy chat/tool loops.

### `dashboard/supervised_ui.py`

- `SupervisedUiLedger.append_exact(kind, raw_bytes, lineage)` creates a
  private-mode, append-only, locked, fsynced receipt plus its SHA-256. It uses
  the durability ordering demonstrated by `EventStore.append` but does not
  modify that unresolved shared class.
- `HandsSeatClient` starts the configured Hands command with
  `asyncio.create_subprocess_exec` (never a shell), performs version handshake,
  serializes one request at a time, and fails loud on missing configuration,
  protocol mismatch, timeout, extra output, or worker exit.
- `SupervisedUiSession.request_model_turn()` fetches the current live schema,
  writes exact request bytes, performs one non-streaming chat-completions call,
  writes the raw response, records exactly one proposal, and returns without
  executing it.
- `SupervisedUiSession.decide_proposal()` records approve/reject. Approval
  mints an in-memory, one-use capability bound to actor, proposal hash,
  revision, ref, operation, effect class, and expiry.
- `SupervisedUiSession.execute_approved()` sends that one capability to Hands,
  persists the exact tool-result bytes, consumes the capability regardless of
  outcome, and transitions to `needs_verify` after any action attempt.
- A dedicated `APIRouter` exposes session-open, next-model-turn,
  proposal-decision, execute-once, state, and event-stream endpoints under
  `/api/supervised-ui/v1/`.

The configured Hands command and chat endpoint are mandatory. Neither receives
an operator-specific or private-topology default. The model transcript never
receives the one-use capability.

### `dashboard/static/index.html`

Add a separate supervised-seat panel that shows:

- current state and revision;
- the exact proposed operation/ref/effect class;
- request, response, proposal, approval, execution, and result hashes;
- Approve, Reject, Execute once, and Request next turn controls; and
- a permanent warning when an operation is excluded or effect is unknown.

Approve and Execute are separate controls so approval does not silently cause
an action. The UI disables every control that is invalid for the current
state. Server state remains authoritative.

## Receipt chain

Every event carries `session_id`, monotonically increasing `sequence`, prior
event hash, event hash, contract version, and public repository commit IDs.
The minimum successful chain is:

1. `session_opened`
2. `hands_schema_captured`
3. `model_request_exact`
4. `model_response_exact`
5. `proposal_pending`
6. `approval_recorded`
7. `approval_consumed`
8. `tool_result_exact`
9. `state_needs_verify`
10. a new sequence from `hands_schema_captured` through `tool_result_exact`

Rejection records `proposal_rejected` and has no consumption or tool result.
Any sequence gap, hash mismatch, noncanonical replay, or missing exact byte
artifact makes the session inadmissible.

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
5. Let Taey propose one `focus`. Before approval, confirm the UI is unchanged.
   Approve and execute once; confirm one AT-SPI focus result and state
   `needs_verify`.
6. Confirm the next schema again exposes only `observe`/`verify`. Approve one
   read and verify the new result is hash-chained to the focus result.
7. From the new tree, allow a second independently proposed local-only action
   only if a distinct safe control is explicitly declared by public policy.
   Approve once, execute once, and require another explicit read. If the live
   surface lacks such a control, stop and record `blocked`; do not invent or
   pre-script it.
8. Inspect the production receipt chain: exact request and response bytes,
   proposal/approval equality, single-use capability consumption, tree/action
   ref equality, revision equality, mandatory post-action reads, and zero
   outward effects.

The production oracle is the real receipt chain and observed UI state. No
generated fixture can substitute for it.

## Mechanical and adversarial gates

Before implementation is authorized:

- a fresh peer must try to find a path that executes without approval, replays
  an approval, uses a stale ref, leaks raw/private data, invokes a coordinate
  fallback, enters the automatic proxy loop, or generates an implicit next
  turn;
- the owner must resolve the Presence duplicate-route ambiguity and confirm
  the new distinct namespace is registered exactly once; and
- the owner must approve the initial per-platform local-effect policy.

Before the production walk:

- GitNexus impact must be rerun for every actually edited existing symbol;
- staged change detection must show only the reviewed supervised-seat surface;
- public-tree scans must contain no credential, private topology, operator
  path, or private application identity; and
- both processes must fail loud with missing contract, endpoint, display,
  platform, lease, or policy configuration.

Implementation remains blocked until this adversarial review returns a written
verdict and all findings are resolved.
