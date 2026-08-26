# LinkedIn Jobs surface restore

## Status

This document defines the public Hands transaction for restoring one dedicated
LinkedIn browser display to one frozen Jobs search-results URL. The transaction
is an additive candidate until its Presence profile is merged and a real
production receipt is recorded. It does not itself claim deployment or Taey
availability.

The operation is exactly:

```json
{"operation":"restore_linkedin_jobs_surface"}
```

It reuses the existing `linkedin` driver function
`exact_engagement_return()` without changing the LinkedIn YAML, driver,
engagement transaction, Jobs selection transaction, or shared action
behavior.

## Frozen private input

The canonical private transaction contains exactly `schema`, `operation`, and
`return_url`:

```json
{"operation":"restore_linkedin_jobs_surface","return_url":"PRIVATE_EXACT_HTTPS_LINKEDIN_JOBS_SEARCH_RESULTS_URL","schema":"linkedin_jobs_restore_private_input_v1"}
```

`return_url` is private. It must be an exact HTTPS
`www.linkedin.com/jobs/search-results` URL with no credentials, explicit port,
or fragment. A query is allowed and remains part of exact identity. The file is
strict canonical JSON, an owned nonsymlink regular file with mode `0400`, and
must resolve beneath the owner-controlled private root.

## Exact machine

The runner accepts the same immutable lineage envelope as the existing
LinkedIn revenue runners:

```text
scripts/run_linkedin_jobs_restore.py
  --display DISPLAY
  --transaction-file ABS_PRIVATE_JSON
  --expected-transaction-sha256 64HEX
  --receipt-file ABS_NEW_RECEIPT_JSON
  --private-root ABS_PRIVATE_ROOT
  --requester SEAT_ID
  --turn-id TURN_ID
  --correlation-id CORRELATION_ID
  --process-generation 32HEX
  --deadline-seconds 30..1700
```

Before UI work, the runner validates the clean public checkout, private root,
new receipt path, canonical transaction, permanent-claim digest, display, and
lineage. It then acquires the existing per-display `CAREERS` lock with zero
wait.

While holding that lock, the runner:

1. binds the exact display to its published AT-SPI bus;
2. calls `exact_engagement_return(display, return_url, deadline_at)` exactly
   once;
3. accepts only its exact `satisfied` verdict, no failed substep, one Firefox
   process digest, the frozen URL digest, and exactly two required and observed
   stable cycles;
4. releases the lock and writes one immutable mode-`0400` terminal receipt.

The retained driver owns every UI mutation and validation: focus the routed
Firefox PID, `Ctrl+L`, prove the exact focused address entry, select its entire
AT-SPI text range, paste the frozen URL once, prove the pasted text, press
`Return` once, then require two stable exact-route and current-Notifications
observations.

There is no second keypress, alternate selector, Back action, pointer,
coordinate, OCR, screenshot locator, shell UI command, blind retry, or
outward LinkedIn action. The first error is terminal. If a side effect may have
started, the result is indeterminate and the transaction identity must not be
retried.

## Compact result and private receipt

The public result contains exactly:

```text
ok
platform
display
state
failure_code
target_url_sha256
firefox_pid_sha256
restore_proof_sha256
stable_cycles_observed
receipt_sha256
turn_lineage_sha256
```

Success is `state=restored`, `ok=true`, no failure code, five valid digests,
and `stable_cycles_observed=2`. Failure is `state=technical_failure`,
`ok=false`, and exactly one of:

```text
private_input_invalid
display_lock_unavailable
restore_indeterminate
deadline_expired
lock_release_indeterminate
```

The private receipt contains the first failed substep when known, full lock
lineage, exact commit, transaction digests, and the unchanged driver restore
receipt. It contains only the target URL digest, never the raw target URL.

## Intended Taey boundary

The corresponding Presence profile should be named `linkedin-jobs-restore` and
expose only `restore_linkedin_jobs_surface`. Taey receives only:

```json
{"display":":N"}
```

Presence must bind the private transaction and permanent claim before invoking
this runner, return the compact result unchanged, and make the identity
unretryable. Adding that profile is a separate Presence change; it is not part
of this Hands transaction.

## Qualification gate

Before deployment:

1. Run `python3 consultation_v2/validators/validate_linkedin_jobs_restore_contract.py`.
2. Re-run the existing LinkedIn Jobs and mounted-search validators unchanged.
3. Confirm the diff contains only the standalone contract, runner, receipt
   schema, validator, and this runbook.
4. From a clean public checkout and a fresh private identity, execute one real
   restore. Acceptance requires one CAREERS lock acquisition and release, one
   driver call, the exact URL digest, two stable observations, a mode-`0400`
   receipt, and terminal `restored`.
5. Do not retry any failed identity. Diagnose from its first terminal receipt.
