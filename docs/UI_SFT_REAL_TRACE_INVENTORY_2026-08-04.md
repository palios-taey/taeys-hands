# Real UI trajectory inventory — 2026-08-04

Status: **HOLD — zero complete trajectories admitted.**

This is a read-only inventory of existing production receipts. No browser was
opened, no display was bound, no UI action was performed, and no missing event
was reconstructed. Paths below identify private production evidence; the
evidence contents are not copied into this repository.

## Admission contract

A multi-turn row is eligible only when one production session proves this
sequence at least twice without a gap:

1. the model calls the current read operation (`ui_action` with `op=observe` or
   `op=verify`);
2. the tool returns a fresh filtered tree with its view, revision, and opaque
   element refs;
3. the model makes exactly one subsequent ref-bound `ui_action` using the
   revision and a ref from that returned tree;
4. the tool returns the action result and fresh post-action view/revision;
5. the model calls `observe` or `verify` again, receives the post-action tree,
   and chooses the next single ref-bound action from that new observation.

Every call and result must share one production session/bundle identity. The
action must pass the production per-operation validator. Failed, rejected,
generated-but-not-executed, stale-ref, unverified terminal, and synthesized
events are excluded. Private values, credentials, host paths, answer tokens,
application identities, URLs, and raw element refs must be removed or replaced
by receipt hashes after the joins are proven.

The measured UI navigation contract is `ui_action` on the production branch
`palios-taey/apply-machine:ats-submit-subtraction` at
`bfb8c75f3ef174c47d0de42d253dc4fa87f4bb28`. The strict per-operation schemas
are `UI_ACTION_SCHEMA_BY_NAME`; the chat-completions wrapper is
`ui_action_tool`; and production validation is `_validate_ui_action_call`
(`/home/mira/apply-machine/ats_mcp_server.py:392-396,446-466,505-513`).
`observe` and `verify` are read operations in the same public contract
(`/home/mira/apply-machine/ats_mcp_server.py:278-290`). Ref-bound operations
carry `view`, `ref`, `revision`, and `verify_view`
(`/home/mira/apply-machine/ats_mcp_server.py:270-275`).

### Exact production request and capture shape

Observed at Apply Machine commit
`bfb8c75f3ef174c47d0de42d253dc4fa87f4bb28`:

- `taey_worker._call` sends `/chat/completions` a `messages` array, exactly one
  tool declaration from `ui_action_tool()`, a forced `ui_action` tool choice,
  `parallel_tool_calls=false`, and `enable_thinking=false`
  (`/home/mira/apply-machine/taey_worker.py:83-100`).
- A run begins with the full system prompt and task prompt as system and user
  messages (`taey_worker.py:212-239`). Every accepted non-terminal turn then
  sends the original two messages plus the prior assistant `ui_action` call
  and the exact compact JSON action result (`taey_worker.py:296-344`). The
  messages array is replaced each turn rather than accumulated across the
  entire walk.
- The tool call wire name is always `ui_action`; `op` inside its JSON arguments
  selects `observe`, `verify`, or one action. The production validator removes
  `op` and validates the remaining arguments against that operation's schema
  (`ats_mcp_server.py:400-466,505-513,2106-2108`). Standalone `observe` and
  `verify` names belong to the separate Responses-API facade returned by
  `responses_tools()` (`ats_mcp_server.py:432-443`); they are not the Taey
  chat-completions request shape.
- Apply Machine durably writes each raw model SSE generation, but records the
  request only as `request_sha256`; it does not persist the request body
  (`taey_worker.py:83-113,160-201`). The action ledger and step-tree receipts
  persist filtered evidence, while the model sees the separately bounded
  projection returned by `_taey_model_result`
  (`ats_mcp_server.py:1046-1117,1868-1913,2475-2481`). There are 334 raw
  `generation_*.sse` files in the measured bundle tree and no durable
  `request_*.json` files. Therefore the exact initial system/user messages and
  exact model-visible tool-result bytes are **not recoverable as a joined
  production transcript** from the current Apply Machine receipts.

Observed at taeys-hands commit
`258b49457c52de8608a6fd757c867026f8d8a2cf`:

- The consultation seat is also chat completions, but its sole forced tool is
  `consult_extract_action` (`consultation_v2/taey_extract.py:770-788`). It
  durably writes the full canonical request body and raw response for every
  model turn (`taey_extract.py:789-835`).
- Its first request includes the exact system and user messages, and each next
  request includes the prior assistant call and exact compact JSON tool result
  (`taey_extract.py:3773-3789,3818-3830,3905-3917`). Existing
  `request_0001.json`/`request_0002.json` receipts confirm two messages on the
  first turn and four on the second. Thus consult captures do preserve initial
  prompts and tool results, but their semantic-name contract has no UI tree,
  ref, or revision and cannot supply the requested UI-navigation curriculum.

### Rejection of the post-inventory builder revision

`palios-training` commit
`df4611ca2a78ed0d2b782b91316c87cd90c2cf8b` correctly requires adjacent
read/action/post-read ledger records (`build_trajectory_rows.py:194-212` at
that commit), but its emitted message envelope is not the measured Taey
production request:

1. it emits standalone function names `observe` and `verify`/`read` at lines
   261-266 and 289-294 even though metadata retains `tool_contract=ui_action`;
2. it emits `render_observation(pre_snap)` and
   `render_observation(post_snap)` as authored narrative tool content rather
   than the exact compact JSON model-visible results;
3. it begins with an assistant tool call and omits the production system/user
   messages; and
4. it reduces the action result to an authored three-field object at lines
   256-288 rather than a captured `_taey_model_result` payload.

Disposition: rows from `df4611c` are **ineligible**, even if its adjacent-ledger
gate finds candidates. Correct adjacency does not repair a mismatched function
schema or missing exact request/result capture.

There is a separate contract boundary in this repository: the current
consultation seat exposes `consult_extract_action`, whose arguments are
`action`, `name`, and `contains`
(`consultation_v2/taey_extract.py:94-148`). It does not expose snapshot-local
refs or revisions. Existing consult-seat captures therefore cannot be relabeled
as `ui_action` trajectories. Which contract future cross-surface curriculum
should target remains an owner decision; this inventory does not conflate them.

## Source inventory and disposition

### 1. Apply Machine production action ledger and tree receipts

- Source: `/home/mira/apply-machine/bundles/**/submit_agent.log` — 56 files.
- Source: `/home/mira/apply-machine/bundles/**/step_*_tree.txt` — 369 files.
- Builder: `/home/mira/palios-training/careers-qwen/build_trajectory_rows.py`
  at `7c478efdece55dc5ca89ed91bf69eda5e33338f5`; Jesse authored the original
  builder in `23bb1ba` (`git blame`, lines 1-27).
- Reproduction:

  ```text
  python3 careers-qwen/build_trajectory_rows.py \
    --bundles /home/mira/apply-machine/bundles \
    --out /tmp/production_ui_trajectories_v1.jsonl
  ```

- Observed result: 91 emitted, 93 rejected; emitted operations were 35 focus,
  29 write, 25 activate, and 2 navigate. All 91 rows have exactly three
  messages: embedded snapshot, one `ui_action` call, one action result. They
  cover 14 bundles. Reproduced output SHA-256:
  `9ebf2b7d6c809cb52f2eba4ea4b60a48264975c338973d1709aefb429dcac6fb`.
- Observed ledger operation counts: activate 48, focus 40, key 1, navigate 29,
  observe 19, page 8, write 39. Seventeen observe calls succeeded; two failed.
  There are **zero verify call records**.
- Disposition: **atomic evidence only; 0 eligible complete multi-turn
  trajectories.** The builder deliberately joins a pre-action snapshot to one
  action (`build_trajectory_rows.py:112-139,186-275`) but does not preserve an
  actual model-issued read call. Consecutive snapshots do not prove that the
  model called `observe` or `verify`.

Closest partial sessions, retained as capture templates rather than rows:

- `figma_forward_deployed_engineer_85d18054`: 34 successful action records and
  34 saved trees; 33 action `after_revision` values equal the next action's
  input revision, but the session contains no observe/verify calls. Ledger
  SHA-256 `e76d6e07eb1bfd4909b681125c37e68e3da9d725decf6c6a299762863c4367b2`;
  model-log SHA-256
  `0dc5a9bf66122113bd488f60766f57902b48772116d4e4c81fea19deee69a6e4`.
- `grafana_labs_senior_ai_engineer_us_remote_d42d83b8`: the only close prefix:
  observe navigation → activate → observe form → activate. The second action
  has no post-action read, the following action is not preceded by a read and
  uses a different revision, and the walk ends on a failed write. Ledger
  SHA-256 `882376ff088fe94ed043611d1d4fa3b96056d21df619cf2f0f8c8e802a135904`;
  model-log SHA-256
  `00b099e419405555b9aa583cad18f9b0aa1b04ff2685e1374653eeee907b1af7`.
- `fireworks_ai_ai_field_engineer_strategic_partnership_01534dfa`: observe
  navigation → activate → failed focus, with no post-action read. Ledger
  SHA-256 `b5ab162fde2d355b494a80cef3e07077991a32d08143f0de5155a1d39571c12c`.

### 2. Taey consultation-seat captures

- Source: `/home/mira/embedding-server/consults/traces/2026-08-03-taey-seat-batch/{chatgpt,claude,gemini,grok,perplexity}/turns.jsonl`.
- Observed events: ChatGPT 20 successful actions; Claude 17; Gemini 10
  successful and 6 failed; Grok 18 successful; Perplexity 15 successful.
  None of the five logs contains a tree, snapshot, revision, element-ref,
  session, surface-receipt, or postcondition field in its action events.
- Source-derived training file:
  `/home/mira/treasurer/foundations/careers/training_data/careers_qwen/ui/consult_seat_iteration3_capability_walks_v1.jsonl`,
  129 rows, SHA-256
  `b49564721e15e3b5f3be2d16d11dbaf0fa75f78b506e71b2192d0ff66a960b55`.
  Each row is one user turn plus one assistant `consult_extract_action` call.
  Its metadata says `tool_contract=consult_action`, which does not equal the
  emitted tool name.
- Disposition: **0 eligible UI ref trajectories.** The captures are useful
  evidence for a different semantic-name seat, but they have neither the
  requested read/action/validation cycle nor the `ui_action` ref/revision
  contract.

### 3. Older supervised LinkedIn, Sales Navigator, and Upwork artifacts

- Source family:
  `/home/mira/treasurer/runtime-state/linkedin_taey_runthrough/2026-07-24_11ET_full_cycle/`.
  It contains 47 `.tree` artifacts plus action stdout/failure/provenance files.
  One post-state tree is independently hash-bound at
  `1ba4c2e142d0f62c0e153c75d28c3fbf4a3894459ba7427d736be668cb658641`.
- Derived practice rows under
  `/home/mira/treasurer/foundations/careers/training_data/careers_qwen/ui/`
  are prose `operator_practice_v1` corrections without actual tool-call
  envelopes.
- Disposition: **0 eligible current-contract trajectories.** These receipts use
  legacy literal Python/`act.do` and standalone tree-capture commands. They do
  not prove current `ui_action` calls, model-issued observe/verify calls, or a
  contiguous session transcript. They also contain private career/application
  values that must not be copied into a new corpus.

## Observed gaps

1. No current source proves two complete
   read-result → one ref action-result → post-action read-result cycles in one
   session.
2. No current source has a successful `verify` call in the Apply Machine action
   ledger.
3. The atomic builder stores a rendered snapshot as a user message, not the real
   `ui_action(op=observe|verify)` call and tool result that produced it.
4. The action result rows carry only `ok`, `view`, and `revision`; they do not
   preserve the full filtered post-action tree as that same tool result.
5. `taeys-hands` and Apply Machine expose different closed tool contracts. A
   row cannot claim both without a recorded owner decision and a real adapter
   receipt.
6. Existing private receipts are not a distributable corpus. Admission needs a
   deterministic redaction pass after joins, with hashes retained for audit.
7. Apply Machine stores exact response streams and request hashes but not exact
   request bodies. A future production capture must durably save every
   canonical request payload, including the initial system/user pair and the
   exact model-visible result of each `ui_action` call.

## Outcome

No canonical SFT row batch is emitted from the current evidence. The precise
supervised capture queue is in
`docs/UI_SFT_SUPERVISED_CAPTURE_QUEUE_2026-08-04.jsonl`. Any future builder must
fail closed unless all receipt joins above are present; it must never insert an
observe call, tree result, action, validation, ref, revision, or private value
that did not occur in the source session.
