# Supervised UI Seat Design Audit — 2026-08-04

Commit under audit:
`7cdaafb28536747bd544c84f5e8febcf6fe15ebb`
Branch: `ui-sft-supervised-trace-inventory`
Auditor: `taeys-hands` acting independently of the author.

## Scope

Docs-only design commit. No code or YAML files were changed.

Observed diff summary:

- `docs/PUBLIC_SUPERVISED_TAEY_UI_SEAT_PLAN_2026-08-04.md` — `259` insertions, `70`
  deletions; net `+189` lines
- `docs/UI_SFT_REAL_TRACE_INVENTORY_2026-08-04.md` — `42` insertions, `9` deletions;
  net `+33` lines
- `docs/UI_SFT_SUPERVISED_CAPTURE_QUEUE_2026-08-04.jsonl` — `9` insertions, `1`
  deletion

The commit is not on `main`. `origin/main` is five commits ahead and does not contain
this commit.

## Question 1 — Approval model

Observed:

- One model turn may expose only `observe` or `verify`.
- `needs_observe` permits a supervisor request whose live schema permits only
  `observe` or `verify`.
- `proposal_pending` means the supervisor has approved or rejected the exact proposal
  hash and nothing has executed.
- `approved_once` means the one-use approval was consumed by exactly one
  `consultation_v2.seat_actions` request and a replay must fail.
- `proposal_pending`, `action_ready`, and `needs_verify` are distinct.
- A terminal proposal state has no retry and no implicit next turn.

Observed UI constraints:

- The UI can approve or reject one exact proposal.
- The UI cannot replace the ref, operation, argument, revision, tool arguments,
  target sequence, action order, or next action.
- A replacement, omitted, reordered, or mutated field fails loud.
- No "execute after N seconds" or "execute if unanswered" path exists.

Inferred:

- The design correctly makes the proposal immutable after it is issued.
- The design correctly forces an explicit supervisor decision before any
  `execute_approved` path.
- Rejecting a proposal does not create a new model call; it merely removes the
  pending proposal.
- The model cannot request approval and then act while the decision is pending.

Unknown:

- No runtime evidence was observed in this commit because it contains only
  documentation.

## Question 2 — Process restart between proposal and approval

Observed:

- `approved_once` is consumed by exactly one execution request.
- If the hands process restarts before execution, a new `proposal_pending` turn begins.
- A restart cannot reuse a previous approval receipt.
- The UI must display the current proposal again before a new approval can be
  recorded.
- An old approval token cannot authorize an execution after restart.

Inferred:

- This is the correct fail-closed behavior. A restart cannot silently consume a
  human decision made for a different process state.

Unknown:

- No persisted proposal store or durable token implementation is present in this
  commit, so runtime restart semantics were not observed here.

## Question 3 — Action execution, postcondition, and indeterminate outcome

Observed:

- The only mutable action operation is `focus`.
- An action proposal may contain one `focus` and zero other operations.
- `focus` is classified as uncertain until a fresh read proves the state change.
- The postcondition for `focus` is exactly one mandatory fresh `observe`.
- A successful `focus` verification requires a matching ref in
  `STATE_FOCUSABLE`, `STATE_FOCUSSED`, and `STATE_ACTIVE`.
- A failed or unverifiable `focus` is terminal for that proposal.
- An action result never permits a macro, loop, new action branch, implicit
  continuation, retry, or immediate new action.
- `focus` is not `write`, `activate`, `copy`, or `cut`.

Inferred:

- This is a correct and unusually strict treatment of `focus`. It is not treated as
  a free idempotent action.
- The fresh-read requirement prevents a model from claiming an action succeeded
  because it intended it.

Unknown:

- Whether AT-SPI will reliably expose `STATE_ACTIVE` for every target on every
  platform is unknown from this commit alone.

## Question 4 — Capture contract and SFT eligibility

Observed:

- Zero trajectories are admitted by this commit.
- Every queued capture shape has `"status":"blocked"`.
- The canonical tracker tasks are required blockers:
  - `taey-training-program::p0-ui-supervised-seat-build`
  - `taey-training-program::p0-ui-capture-privacy-boundary`
- The build task depends on the reviewed design, but design completion cannot
  substitute for implementation evidence.
- A completed task status without reviewed and production-observed evidence does
  not release capture.

Observed capture requirements:

- exact canonical request bytes before network IO
- exact raw response bytes before parsing
- exact proposal bytes before approval
- exact tool-call bytes before execution
- exact post-action observation bytes before the next turn
- immutable hash-chain receipts
- causal parent-child event IDs
- monotonic sequence numbers
- strict schema validation
- rejection of synthesized, repaired, or reconstructed artifacts

Observed privacy constraints:

- no raw AT-SPI trees or accessibility names may enter training text
- no private host paths, credentials, tokens, session IDs, or application
  identities may enter training text
- the public training example may contain only sanitized opaque refs, schema
  names, operation names, state names, status enums, policy labels, and verifier
  labels
- exact artifact bytes may remain in private receipts, but they are not training
  text
- an allowlist plus a denylist is required; overlapping or ambiguous fields must
  fail closed

Inferred:

- This is a correct capture-while-building design. It can produce useful SFT rows
  from ordinary supervised production use without a special data-generation
  campaign.
- It is also deliberately conservative. Many production events will fail
  eligibility, and that conservatism is the correct default for material that can
  affect model behavior.

Unknown:

- Whether the final private sanitization projection will preserve enough structural
  signal for useful UI-behavior training remains unknown until real captures exist.

## Question 5 — Remaining risks and unresolved design questions

1. **`activate` is absent from the action vocabulary.**
   Observed: the inventory explicitly states that `focus` is not `activate`.
   Inferred risk: some widgets will accept input after `focus`, but others require
   an activation or menu-open primitive. The current design cannot express that
   second primitive, so Taey may propose `focus` and then correctly observe that
   the expected menu did not appear.

2. **No explicit menu-open or portal-reveal primitive.**
   Observed: the only action is `focus`.
   Inferred risk: a combobox, listbox, or overflow menu cannot be opened by
  `focus` alone on every platform. The design requires the next action to be
   independently derived from a fresh read, but it does not provide a second safe
   primitive for revealing options.

3. **`STATE_ACTIVE` may not distinguish "selected" from "active/pressed."**
   Observed: verification requires `STATE_ACTIVE`.
   Inferred risk: AT-SPI role/state semantics vary by toolkit. A validator that
   conflates pressed/active with selected may accept the wrong proof for a
   list-item choice.

4. **Text and value are completely absent from the action model.**
   Observed: `write` is not permitted and values are out of scope.
   Inferred benefit: this sharply reduces the blast radius.
   Inferred risk: the seat cannot train editable-value workflows until a later
   reviewed contract exists.

5. **Ref stability across reads is unspecified.**
   Observed: refs are opaque and bound to one snapshot revision.
   Inferred risk: if the same element receives a different ref after a
   tree-invalidation, the model cannot correlate "the field I just focused" with
   "the field in the new tree." That is probably desirable for freshness, but it
   may make multi-step sequences harder to learn than expected.

6. **Timeouts, display readiness, and attach/upload flows are not modeled.**
   Observed: these shapes are absent from the public contract.
   Inferred risk: a model trained only on the current admissible shapes may learn
   to avoid or refuse operations it cannot represent, which is reasonable, but it
   also limits the useful UI vocabulary.

7. **The inventory states no live walk was performed for this commit.**
   Observed: no browser was opened, no display was bound, and no AT-SPI tree was
   read while producing this artifact.
   Inferred: this is correct for a design/audit turn, but it means every
   AT-SPI-specific assertion remains a design claim until the build and production
   observation phases execute.

## Final verdict

Observed:

- The commit is docs-only.
- It does not modify the current live path.
- It correctly blocks new capabilities, capture, and SFT eligibility behind
  reviewed implementation plus production observation.
- It prevents a pending approval from silently becoming an action.
- It requires exact pre/post artifacts before a trajectory can be admitted.

Inferred verdict:

- **Conditionally advisable to merge after the record is made externally
  self-contained.**
- Do not treat this as implementation, validation, or proof of capability.
- Do not train from this branch.
- The next task should be the implementation plus at least one complete
  production-observed Taey-driven `observe -> focus -> observe` sequence on a real
  public widget.
