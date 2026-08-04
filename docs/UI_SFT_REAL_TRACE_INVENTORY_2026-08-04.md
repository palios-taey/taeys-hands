# Real UI trajectory inventory — 2026-08-04

Status: **BLOCKED — zero trajectories admitted.**

This inventory records the evidence gap without publishing private topology,
operator paths, application identities, or raw UI values. The associated
capture queue is blocked on the exact tracker tasks
`taey-training-program::p0-ui-supervised-seat-build` and
`taey-training-program::p0-ui-capture-privacy-boundary`. The build task depends
on the reviewed `taey-training-program::p0-ui-supervised-seat-design`; design
completion cannot substitute for implementation.

No browser was opened, no display was bound, no live accessibility tree was
read, and no UI action or model generation was performed while producing this
document.

## Truth register

### Observed — public source

At `palios-taey/taeys-hands@258b49457c52de8608a6fd757c867026f8d8a2cf`:

- `ElementRef` retains internal coordinates, an AT-SPI object, and raw scan
  data; its public serializer has no opaque ref or revision
  (`consultation_v2/types.py:158-184`).
- `Snapshot` serializes the platform, URL, mapped/unknown/sidebar elements, and
  menu items; it has no revision (`consultation_v2/types.py:211-247`).
- `build_snapshot` is the real public AT-SPI/YAML observation primitive
  (`consultation_v2/snapshot.py:662`).
- `SeatActions.find` performs hidden re-observations, and its click/paste paths
  may use coordinate fallbacks (`consultation_v2/seat_actions.py:113-240`). It
  is not a revision-bound supervised contract.
- `atspi_focus` and `atspi_activate` are exact no-coordinate primitives that
  return a success verdict (`consultation_v2/interact.py:91-103,132-145`).
- The consultation extraction seat persists exact canonical request bytes
  before network I/O and raw response bytes before parsing
  (`consultation_v2/taey_extract.py:770-835`). Its tool is semantic extraction,
  not a UI ref/revision tool, so those receipts cannot be relabeled as UI
  trajectories.

At `palios-taey/taey-presence@e0cd1b163640d8e69f79b6dd3de839dc22794771`:

- The durable dashboard chat path currently sends `tools: []`
  (`dashboard/app.py:2173-2200`).
- The file contains two handlers named `chat_session_stream`
  (`dashboard/app.py:2013,2742`), so the supervised seat must use a distinct
  router and route namespace rather than silently modifying either legacy
  handler.
- `EventStore.append` provides a useful append/fsync/private-mode durability
  pattern (`serving/taey_seat.py:182-259`), while `ProxyClient.ask` sends a
  content-only request and rejects tool-call-only responses
  (`serving/taey_seat.py:481-559`). Neither is the required supervised tool
  transcript.
- `serving/soma_proxy.py:2157` owns an automatic tool loop. It is explicitly
  excluded because execution there occurs without the required per-call human
  approval boundary.

### Observed — private control measurement

A private trace audit, represented here only by the document-local opaque
handle `control-note:2026-08-04/ui-transcript-gap`, measured 334 response SSE
artifacts and zero durable request bodies. The model request loop that produced
those responses is tombstoned. It must not be revived.

The pre-existing atomic-row builder produced 91 action rows and rejected 93;
the reproduced output SHA-256 is
`9ebf2b7d6c809cb52f2eba4ea4b60a48264975c338973d1709aefb429dcac6fb`.
Those rows do not contain a model-issued read, the exact request body, or a
mandatory post-action read. They remain atomic evidence only.

The measured operation ledger contained 184 events: 48 activate, 40 focus, 1
key, 29 navigate, 19 observe, 8 page, and 39 write. One isolated
read/action/post-read cycle existed; no session contained two consecutive
complete cycles. These counts are private measurement results, not a
distributable corpus.

### Inferred

A qualifying trajectory cannot be recovered from current receipts. New
supervised production capture must occur through the public seat described in
`docs/PUBLIC_SUPERVISED_TAEY_UI_SEAT_PLAN_2026-08-04.md` after its adversarial
review and implementation gates pass.

### Unknown

- No current public receipt proves that a live Taey request carried a
  revision-bound accessibility schema and paused before execution.
- No current public receipt proves an approval bound to the exact proposed
  call, snapshot revision, and one-use execution capability.
- No current evidence establishes a safe second action for a future production
  walk. The live public policy and observed tree must establish that at run
  time; absence is a loud block.

## Admission contract

A row is eligible only when one production session contains at least two
complete cycles, each proving:

1. the exact canonical model request includes the live `ui_action` schema;
2. the raw model response proposes exactly one `ui_action` call;
3. a supervisor approval receipt binds the proposal hash, current revision,
   ref, operation, effect class, both process incarnation IDs, and one-use
   capability;
4. `approval_spent` and `execution_started` are immutably fsynced before the
   AT-SPI call, and an explicit outcome follows;
5. only an observed, durably recorded success reaches `needs_verify`; crash,
   timeout, false, stale, replay, or lost outcome is terminal and never retried;
6. the next model request exposes only `observe` or `verify`;
7. the exact fresh post-action observation and verification verdict bind the
   before revision, action, result, and after revision; and
8. the next action is independently proposed from that new result.

Taey must choose every read, action, and validation call. Supervisor approval
is only an authority/safety verdict on the immutable proposal; it cannot select
or edit a ref, operation, order, argument, or next action. Confusion and failure
are exact terminal captures. A corrected attempt starts a new session with
explicit non-prescriptive feedback and new incarnation/causal IDs; the prior
session remains immutable.

Rejected, failed, stale-ref, unverified-terminal, synthesized, or
generated-but-not-executed events are excluded. A missing receipt ends the
capture; no builder may reconstruct it.

## Public/private boundary

The canonical seat is entirely public:

- `palios-taey/taeys-hands` owns accessibility observation, public projection,
  policy-authored safe labels, refs, revisions, live action schema, approval
  validation, durable pre-effect spend/start, and one execution. Runtime
  accessible names never enter the public projection or persistent receipt.
- `palios-taey/taey-presence` owns exact model request/response capture,
  complete settings/tool declarations, proposal state, supervisor
  approval/rejection, process-incarnation binding, and the visible transcript.

Private ATS code is an optional adapter and trace source only. Public code must
not import it, assume its filesystem layout, or expose its identities. An
adapter may cross the boundary only through the versioned public contract and
opaque receipt hashes.

Exact artifacts are written only after a pre-persistence privacy gate, under a
mandatory absolute external root outside every public repository. The root and
session directories must be nonsymlink mode-`0700` directories; immutable
files must be created once as mode `0600` with exclusive/no-follow semantics,
then file- and directory-fsynced. Missing or unsafe configuration fails before
network or UI effects.

## Ref pseudonymization order

Raw/internal refs are not simply deleted. The admission builder must first
prove, inside the private boundary, that:

- the action ref equals a ref in the immediately preceding model-visible tree;
- the action input revision equals that tree revision;
- the next read revision has the declared relation to the action result; and
- the session, proposal, approval, execution, and result receipts form one
  contiguous chain.

Only after those joins pass may the builder replace the session identifier and
refs with row-local pseudonyms. The same raw ref receives the same pseudonym
within a row, different raw refs remain different, and revision equality or
inequality is preserved. Raw values, URLs, credentials, paths, free text, and
application identities never cross the boundary.

## Disposition

All five requested capture shapes remain in
`docs/UI_SFT_SUPERVISED_CAPTURE_QUEUE_2026-08-04.jsonl` with status `blocked`.
No canonical SFT batch is emitted. The queue cannot fire until the two named
canonical tasks are evidence-closed and the production walk yields an exact,
contiguous, restart-safe, supervisor-approved receipt chain with fresh
post-action observation and verification verdict.
