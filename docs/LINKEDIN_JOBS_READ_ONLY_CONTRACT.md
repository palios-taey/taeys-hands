# LinkedIn Jobs read-only transaction

Status: selected-job capture is production-qualified; exact job-card selection is implemented pending production qualification.

## Frozen boundary

The first unit reads one job already selected in LinkedIn Jobs. The second unit activates one private exact job-card name, requires the private exact detail title and company across two fresh canonical observations, then performs the same proven capture. Neither unit searches, applies, messages, saves, retries, or chooses policy. The platform-local driver consumes the same canonical `consultation_v2.snapshot.build_snapshot()` output used by the rest of Hands. LinkedIn-specific roles, states, action, and observation-barrier policy remain in `consultation_v2/platforms/linkedin/linkedin.yaml`; dynamic job identity remains private and off model context.

The transaction is:

1. Validate a Presence-injected owner-controlled private root and the transaction, receipt, and sink placement beneath it.
2. Acquire the canonical CAREERS display lock and refuse its fail-open path.
3. Bind the display and build one fresh canonical LinkedIn snapshot under a bounded internal deadline.
4. Require exactly one `About the job` heading, then resolve the YAML-owned relative path `parent(section) -> child[1](paragraph) -> child[0](section)` and read only that node's AT-SPI Text interface.
5. Compile `capture_selected_job` to one write-once private-sink action.
6. Build one fresh canonical LinkedIn snapshot while holding the same lock.
7. Require the selected-job content digest, exact heading count, and exact description-path count to be unchanged.
8. Release the lock, require the positive release verdict for success, then write the immutable terminal receipt and return counts, state, and digests only.

For `select_and_capture_job`, steps 3–4 begin with one additional frozen transition: require exactly one private exact target card with the YAML-owned `push button` role and states, activate it once through AT-SPI, then require the private exact detail-title link, company link, `About the job` heading, and description path to stabilize for two consecutive cache-invalidating canonical observations. A zero/duplicate target, failed action, or unsettled exact postcondition stops the transaction before the sink action. There is no second UI action or retry.

The raw record contains the private search reference, selected source URL, exact detail heading, and text from the one YAML-declared description node reached from the canonical snapshot anchor. This is deliberately narrower than navigation or application. Later units require their own exact maps and production qualification.

## Public request and result

The Hands platform request is exactly one of:

```json
{"operation":"capture_selected_job"}
{"operation":"select_and_capture_job"}
```

`consultation_v2/platforms/linkedin/request.schema.json` rejects all other Hands operations and fields. The distinct Taey-facing tool request remains exactly `{"display":":N"}`. The private transaction selects the operation. Search and sink references, paths, exact job-card/detail identity, lineage, and deadlines are Presence-injected private inputs, not model-authored arguments.

The internal one-shot runner interface is:

```text
scripts/run_linkedin_jobs.py --display DISPLAY --transaction-file ABS_PRIVATE_JSON --expected-transaction-sha256 64HEX --receipt-file ABS_NEW_RECEIPT_JSON --private-root ABS_PRIVATE_ROOT --requester SEAT_ID --turn-id TURN_ID --correlation-id CORRELATION_ID --process-generation 32HEX --deadline-seconds 30..1700
```

Standard output is one compact JSON object with exactly `ok`, `platform`, `display`, `state`, `failure_code`, `records_observed`, `records_written`, `content_digest`, `receipt_sha256`, and `turn_lineage_sha256`. Raw fields, references, paths, URLs, policy, turn IDs, correlation IDs, and process generations are never written to standard output.

Nontechnical states have exact facts: `captured` is observed `1`, written `1`, with a digest; `already_captured` is `1`, `0`, with a digest; `no_selected_job` is `0`, `0`, with a null digest; and `postcondition_failed` is observed `1`, written `0` or `1`, with a digest. Technical failures are either pre-selection `0/0/null` or post-selection `1/(0|1)/digest`, retaining the facts established before their phase failed. A sink timeout or exception is uniquely `sink_write_indeterminate` with observed `1`, written `null`, and a digest; it is never retried or reported as zero writes, and a simultaneous unproven lock release remains recorded in the receipt without replacing that primary failure code.

## Private input and storage

The required private root is an owner-controlled, nonsymlink, exact-mode `0700` directory that does not overlap the public repository. The transaction file must resolve beneath it as an owner-controlled, nonsymlink, exact-mode `0400` JSON file with exactly `schema`, `operation`, `search_ref`, and `sink_ref`. Presence supplies the digest bound to its permanent claim; immediately after its one private-file read, Hands requires the actual byte digest to match that claim before acquiring a lock or touching the UI or sink. The new receipt path and the owner-controlled, nonsymlink, exact-mode `0700` sink directory must resolve beneath that same root. Presence derives transaction and receipt locations from its private root, seat, and correlation ID; Hands independently enforces containment.

Raw records and receipts are created once with exclusive creation, synced, changed to exact mode `0400`, and read back by digest. An existing record is an `already_captured` terminal state only when its bytes match the selected-job digest. Every normal terminal outcome, including no exact selected job, lock collision, pre-observation failure, sink indeterminacy, and postcondition failure, writes the requested compact receipt. If the receipt itself cannot be created, the runner emits no model-facing result.

Receipts bind both claimed and actual transaction digests, requester, combined turn-lineage digest, correlation-ID digest, internal deadline, exact clean Hands commit, CAREERS request ID, lock acquisition and release verdicts, hashed lock-owner token, wait time, exact pre/post heading and description-path counts, hashed private selection identities and their exact match counts, stable observation cycles, sink-action verdict, fixed failure code, and postcondition verdict. The combined lineage digest is canonical JSON over requester, turn ID, correlation ID, and process generation. The CAREERS request ID is canonical JSON over the verified transaction and lineage digests. Before any display binding or sink action, the runner rejects a checkout with either tracked or untracked changes, so the receipt commit identifies the bytes that executed. `no_selected_job` is a non-success terminal with a null content digest and a non-null receipt digest.

The internal deadline is shorter than Presence's outer subprocess timeout. Its alarm is canceled before receipt finalization, allowing a deadline terminal to release the lock and persist a receipt. A missing positive release verdict demotes any otherwise-successful outcome to `technical_failure` with `lock_release_indeterminate`, while retaining the action and observation facts.

## Provenance and qualification

Observed design evidence:

- `4e73344b` is Jesse-authored public guidance for stable structural anchors and action → fresh scan → persistent postcondition.
- `68a12f3d` defines the public revenue UI rollout boundary.
- `353a3258` requires dynamic revenue content to remain off-context in a private sink.

The older screenshot, clipboard, and coordinate fallbacks are not authority for this lane and are not implemented. The already-selected capture was production-qualified on display `:18` at Hands commit `d24730a34dcf665fb4cc7196444982802785821b`: one record observed and written, exact pre/post counts `1/1`, stable content digest, positive lock release, and durable redacted receipt SHA-256 `66172f12ec60f3f8340627c3224caa2a4890f0baedcccf524f871f16d5d43ef9`. Exact-card selection requires its own production receipt before qualification.
