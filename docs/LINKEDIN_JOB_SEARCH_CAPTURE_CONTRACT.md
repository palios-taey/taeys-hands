# LinkedIn mounted job-search capture

Status: bounded read-only production candidate.

This transaction captures the job cards already mounted on one exact LinkedIn Jobs search-results page. It does
not choose or enter search terms, change filters, scroll, open a card, apply, save, dismiss, message, or retry.
The private `search_ref` identifies the already-authorized search policy without exposing that policy to Taey or
public Git.

The public driver consumes only the canonical LinkedIn snapshot. The platform YAML owns the exact route, job-card
role, states, one-action interface shape, direct-child structural prefix, field traversals, and observation
barrier. The driver invokes no UI action. It projects each mounted card into a private record containing its
tree order, exact downstream card target, exact downstream detail title and company, location, showing state,
and digest. Raw card data and the source URL are written only beneath the runtime-injected private root.

The sequence is:

1. Validate an immutable private transaction containing exactly `schema`, `operation`, `search_ref`, and
   `sink_ref`.
2. Acquire the canonical CAREERS display lock and bind the exact display bus.
3. Rebuild canonical LinkedIn snapshots until the YAML-owned card-set projection has the same digest for two
   consecutive observations.
4. Write the complete mounted batch once to the private sink and read it back by SHA-256.
5. Rebuild one fresh canonical snapshot and require the exact card-set digest and match counts to remain
   unchanged.
6. Release the lock, write one immutable private receipt, and return only compact batch/card counts, digests,
   state, and lineage.

The operation is `capture_mounted_job_search`. Its internal runner is:

```text
scripts/run_linkedin_job_search.py --display DISPLAY --transaction-file ABS_PRIVATE_JSON --expected-transaction-sha256 64HEX --receipt-file ABS_NEW_RECEIPT_JSON --private-root ABS_PRIVATE_ROOT --requester SEAT_ID --turn-id TURN_ID --correlation-id CORRELATION_ID --process-generation 32HEX --deadline-seconds 30..1700
```

The private input schema is `linkedin_job_search_private_input_v1`. The sink and receipt remain private;
public output never contains the URL, search policy, card text, title, company, location, account data, or paths.

This is deliberately a mounted-batch unit, not a claim that the infinite results list was exhausted. A later
scroll transition requires its own one-action postcondition and production qualification. Each downstream
card-page capture uses the already-qualified `select_and_capture_job` transaction with the exact private card,
title, and company values from this batch.
