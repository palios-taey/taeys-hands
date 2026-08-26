# LinkedIn mounted job-search capture

Status: production-qualified bounded read-only baseline.

This transaction captures the job cards already mounted on one exact LinkedIn Jobs search-results page. It does
not choose or enter search terms, change filters, scroll, open a card, apply, save, dismiss, message, or retry.
The private `search_ref` identifies the already-authorized search policy without exposing that policy to Taey or
public Git.

The public driver consumes only the canonical LinkedIn snapshot. The platform YAML owns the exact route, job-card
role, states, one-action interface shape, direct-child structural prefix, field traversals, and observation
barrier. The driver invokes no UI action. It projects each mounted card into a private record containing its
tree order, exact downstream card target, exact downstream detail title and company, location, showing state,
and digest. Raw card data and the source URL are written only beneath the runtime-injected private root.

The runtime sequence is:

1. Validate an immutable prepared private transaction containing exactly `schema`, `operation`, `search_ref`, and
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

## Canonical operator runbook

Never assemble the transaction topology with individual `mkdir`, copy, or JSON-write commands. Start with a new
public-safe seat and correlation identity and one existing owner-private draft manifest. The draft must be an
owner-owned, nonsymlink, strict UTF-8 JSON regular file with exact mode `0400`, stored beneath an owner-owned
private root with exact mode `0700`. Formatting whitespace, including trailing newlines, is allowed. Duplicate keys,
NaN and other non-JSON constants, non-object roots, extra fields, and wrong field values are refused. Its fields
are exactly:

```json
{"operation":"capture_mounted_job_search","schema":"linkedin_job_search_private_input_v1","search_ref":"PRIVATE_AUTHORIZED_SEARCH_REFERENCE","sink_ref":"ABS_PRIVATE_ROOT/sinks/PUBLIC_SAFE_SEAT/PUBLIC_SAFE_CORRELATION"}
```

`sink_ref` is absolute and must equal the identity-derived sink shown above. The private root and draft path are
environment bindings, not command-line arguments; the private `search_ref` and `sink_ref` never appear on the
command line or in command output.

Run this exact prepare -> preflight -> Taey sequence from the clean deployed public Hands checkout:

```bash
export TAEY_LINKEDIN_JOB_SEARCH_PRIVATE_ROOT=/owner/private/linkedin-job-search
export TAEY_LINKEDIN_JOB_SEARCH_DRAFT=/owner/private/linkedin-job-search/drafts/frozen-search.json

SEAT_ID=PUBLIC_SAFE_NEW_SEAT
CORRELATION_ID=PUBLIC_SAFE_NEW_CORRELATION
DISPLAY_ID=:18
PROXY_URL=http://127.0.0.1:8766
SERVED_MODEL_ID=taey

PREPARATION_JSON="$(
  python3 scripts/prepare_linkedin_job_search.py prepare \
    --seat-id "$SEAT_ID" \
    --correlation-id "$CORRELATION_ID"
)" || exit 1

TRANSACTION_SHA256="$(
  python3 -c 'import json,sys; print(json.load(sys.stdin)["transaction_sha256"])' \
    <<<"$PREPARATION_JSON"
)" || exit 1

python3 scripts/prepare_linkedin_job_search.py preflight \
  --seat-id "$SEAT_ID" \
  --correlation-id "$CORRELATION_ID" \
  --expected-transaction-sha256 "$TRANSACTION_SHA256" || exit 1

test "$(redis-cli EXISTS "taey:plan_active:${DISPLAY_ID}")" = 0 || exit 1
DISPLAY="$DISPLAY_ID" xdpyinfo >/dev/null || exit 1
curl --fail-with-body --silent --show-error --max-time 5 \
  "$PROXY_URL/health" \
  | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"] == "healthy"; assert value["liveness"]["active_turns"] == 0' \
  || exit 1

curl --fail-with-body --silent --show-error --max-time 1850 \
  -H 'Content-Type: application/json' \
  -H "X-Taey-Seat-Id: $SEAT_ID" \
  -H "X-Taey-Event-Id: $CORRELATION_ID" \
  -H "X-Taey-Correlation-Id: $CORRELATION_ID" \
  -H 'X-Taey-Tool-Profile: linkedin-job-search' \
  --data-binary "{\"model\":\"$SERVED_MODEL_ID\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Execute the frozen LinkedIn Job Search transaction on display $DISPLAY_ID.\"}]}" \
  "$PROXY_URL/v1/chat/completions"
```

`prepare` first validates the owner-private root and identity-derived paths, then creates or validates the exact
owner-owned `0700` claim parent. That is the accepted-identity boundary. It next creates or validates the `0700`
base and seat directories for transactions, receipts, and sinks; creates the exact empty identity sink at
`0700`; canonicalizes the validated semantic mapping; and freezes exact no-newline transaction bytes at `0400`
with exclusive creation. `preflight` independently rereads and validates the draft, compares its semantic
mapping and canonical digest with the frozen transaction, proves the topology, requires an empty sink, and
requires both claim and receipt to remain absent. Successful commands emit only public-safe seat/correlation
identities and SHA-256 evidence.

After the accepted-identity boundary, every `prepare` or `preflight` refusal atomically creates an immutable
`linkedin_job_search_preparation_terminal_v1` marker at the same claim path Presence derives for the
seat/correlation identity. The marker uses exclusive creation, file and parent `fsync`, exact mode `0400`, and
contains no private search data or paths. Presence treats any existing file at that claim path as already
claimed, so a corrected draft or digest cannot reuse the identity. The refusal reports `identity_spent: true`
and the new marker's SHA-256; an already-existing claim remains spent and is never overwritten. A refusal before
the private root, derived paths, and exact claim parent can be established safely reports an unspent identity
and does not claim an identity whose authoritative path is unknown. Stop on every refusal and use a new
seat/correlation identity only after correcting the underlying defect. A non-successful Taey result likewise
spends its already-claimed identity. The preparation validator is:

```bash
python3 consultation_v2/validators/validate_linkedin_job_search_preparation.py
```

This is deliberately a mounted-batch unit, not a claim that the infinite results list was exhausted. A later
scroll transition requires its own one-action postcondition and production qualification. Each downstream
card-page capture uses the already-qualified `select_and_capture_job` transaction with the exact private card,
title, and company values from this batch.

## Production qualification — 2026-08-26

One fresh joined search -> selected-detail -> application-intake chain passed from clean public production
checkouts:

- Hands `e3daab97f59f6cd8d8dfed24912dfbfa5f39bfee` and Presence
  `c42bd319b2fb8ef6b9774b6ef171293baf73e897` produced the mounted-search transaction SHA-256
  `eb06ff6c734f3ce99299374cbd8224e5da30ddbf4a157526f7eca3a0b92ab33e`, artifact SHA-256
  `213fccb088ce0437f3d885e4b602c51cfa2cae2ebf6b082c3c6c572620e1a348`, and receipt SHA-256
  `159f258eb4b7c45ed8fa42218024be83e35a65b1441d96f18583f4aeb862877f`. The receipt proves 25
  mounted cards, two stable observations, an unchanged fresh post-observation digest and match counts, positive
  CAREERS lock release, and zero residual display lease or turn.
- The deterministic downstream rule selected ordinal `1`, the lowest tree-order card with `showing=true`, from
  six eligible cards. The separate selected-detail transaction SHA-256
  `ff2d6e1a1fa8c84bdd25bc38720c1d1197504214480625b8a3ef3e7b2abba110` produced artifact SHA-256
  `c9205449d21a57517c9791e3ecd1deacf62af3ba03b86cb52a46aea4f585bd49` and receipt SHA-256
  `37bd41e250ad66e4a0875d8f9c8471731084434c66bf89bd1b7eb2078de9aa70`. The receipt proves exactly one
  private target, title, and company match, exactly one `click[0]`, two stable detail cycles, unchanged selected
  content, positive lock release, and zero residual display lease or turn.
- Public `taey-apply` `253b882571673ae30d3beadda6f174439755a241` consumed those exact four immutable sources through
  transaction SHA-256 `eab0e62a33ff343f4fd04040af74fb06447ad8bed8d01a97e3dedd5cc3af9960` and receipt SHA-256
  `d73d96d18932ac45b9f87c1c138f7b4494ebd859923fd1c27fad9745a6645157`. Independent database readback
  proved jobs `2239 -> 2240`, applications `49 -> 49`, apply runs `593 -> 593`, and SQL `NULL` for verdict,
  score, and applied-at classification fields.

The private receipts remain the evidence authority. This qualification covers only the already-mounted batch,
one deterministic exact-card selection, and one unclassified intake row. It grants no search-policy choice,
scroll, scoring, ATS, application, messaging, or other outward authority.
