# LinkedIn comment private materialization

Status: canonical public preparation contract for one owner-approved LinkedIn
comment transaction.

This contract creates the two immutable private artifacts consumed by the
revenue-UI Presence boundary. It does not choose a post, draft a comment,
evaluate a gate, inspect the browser, or authorize a UI mutation. An authorized
owner or retained approval system supplies one exact private approval source;
the producer validates that source, derives all hashes and output paths, writes
the gate receipt first, writes the transaction last, and rereads both before it
reports success.

All personal values remain outside public Git. Public Git contains only the
schema, producer, validator, and this path contract.

## Private path contract

`TAEY_REVENUE_UI_PRIVATE_ROOT` must name an absolute, owner-owned, nonsymlink
directory outside the public repository at exact mode `0700`.

The approval source path comes from
`TAEY_LINKEDIN_COMMENT_APPROVAL_SOURCE`. It must be beneath that private root,
under only owner-owned mode-`0700` directories, and must be an owner-owned,
nonsymlink regular file at exact mode `0400`. Its schema is
[`comment-approval-source.schema.json`](../consultation_v2/platforms/linkedin/comment-approval-source.schema.json).
Formatting whitespace is accepted; duplicate keys, non-JSON constants, extra
fields, failed gates, duplicate gate names, a missing passed `cannot_lie` gate,
identity mismatch, and unknown values are refused.

For public-safe `SEAT_ID` and `CORRELATION_ID`, the only emitted paths are:

```text
$TAEY_REVENUE_UI_PRIVATE_ROOT/gate-receipts/$SEAT_ID/$CORRELATION_ID.json
$TAEY_REVENUE_UI_PRIVATE_ROOT/transactions/$SEAT_ID/$CORRELATION_ID.json
```

Both files are owner-owned, nonsymlink, canonical UTF-8 JSON at exact mode
`0400`. Their parents are mode `0700`. Neither file is overwritten. If either
derived output already exists, the identity is spent and a new correlation
identity is required.

The gate receipt contains exactly the source action and activity identity, the
source-artifact digest, the approved gate rows, the normalized-text digest, and
the fixed `linkedin_gate_signoff_v1` / `comment` / `feed_comment` / `signoff`
contract values. The transaction contains exactly the Presence consumer fields,
including the byte-exact text digest and the gate-receipt path and digest.
Neither emitted file is public.

## Approval source

Create the source through the retained owner approval process, not through this
producer. This structural example contains placeholders only:

```json
{
  "schema": "taey_linkedin_private_comment_approval_v1",
  "operation": "comment",
  "platform": "linkedin",
  "display": ":N",
  "seat_id": "PUBLIC_SAFE_SEAT",
  "event_id": "PUBLIC_SAFE_EVENT",
  "correlation_id": "PUBLIC_SAFE_CORRELATION",
  "action_id": "PUBLIC_SAFE_ACTION",
  "selected_activity": "PRIVATE_NUMERIC_ACTIVITY",
  "selected_post_body_sha256": "LOWERCASE_SHA256",
  "source_artifact_sha256": "LOWERCASE_SHA256",
  "like_authorized": false,
  "expected_author_name": "PRIVATE_EXPECTED_AUTHOR",
  "text": "PRIVATE_APPROVED_COMMENT",
  "gates": [
    {
      "gate": "cannot_lie",
      "passed": true,
      "ev": {
        "PRIVATE_EVIDENCE": "PRIVATE_VALUE"
      }
    }
  ]
}
```

Every gate row is an owner assertion already earned by the approval process.
The producer requires each row to pass, but it does not independently recreate
or substitute for that process.

## One deterministic preparation

From one clean public Hands checkout, bind the private paths through the
environment. Do not put private values or paths on the command line:

```bash
export TAEY_REVENUE_UI_PRIVATE_ROOT=/owner/private/revenue-ui
export TAEY_LINKEDIN_COMMENT_APPROVAL_SOURCE=/owner/private/revenue-ui/approvals/frozen-comment.json

SEAT_ID=PUBLIC_SAFE_SEAT
EVENT_ID=PUBLIC_SAFE_EVENT
CORRELATION_ID=PUBLIC_SAFE_CORRELATION

PREPARATION_JSON="$(
  python3 scripts/prepare_linkedin_comment.py prepare \
    --seat-id "$SEAT_ID" \
    --event-id "$EVENT_ID" \
    --correlation-id "$CORRELATION_ID"
)" || exit 1

GATE_RECEIPT_SHA256="$(
  python3 -c 'import json,sys; print(json.load(sys.stdin)["gate_receipt_sha256"])' \
    <<<"$PREPARATION_JSON"
)" || exit 1

TRANSACTION_SHA256="$(
  python3 -c 'import json,sys; print(json.load(sys.stdin)["transaction_sha256"])' \
    <<<"$PREPARATION_JSON"
)" || exit 1

python3 scripts/prepare_linkedin_comment.py preflight \
  --seat-id "$SEAT_ID" \
  --event-id "$EVENT_ID" \
  --correlation-id "$CORRELATION_ID" \
  --expected-gate-receipt-sha256 "$GATE_RECEIPT_SHA256" \
  --expected-transaction-sha256 "$TRANSACTION_SHA256" || exit 1
```

`prepare` returns only the three public-safe identities, artifact digests,
state, and a topology digest. `preflight` independently rereads the approval
source and both immutable outputs, reconstructs the expected canonical bytes,
checks the pinned digests, and returns `ready`. It emits no text, author,
activity, evidence, or private path.

Presence must use the same private root and exact seat, event, and correlation
identities. Its consumer derives the transaction path; Taey supplies none of
the private fields in a model-facing call.

## Mechanical gate

Run:

```bash
python3 -m py_compile \
  scripts/prepare_linkedin_comment.py \
  consultation_v2/validators/validate_linkedin_comment_materialization.py
ruff check \
  scripts/prepare_linkedin_comment.py \
  consultation_v2/validators/validate_linkedin_comment_materialization.py
python3 consultation_v2/validators/validate_linkedin_comment_materialization.py
```

The validator uses synthetic private fixtures only. It proves exact schemas,
canonical hashes, mode-`0400` artifacts, mode-`0700` parents, no overwrite,
identity binding, preflight digest binding, and absence of private values from
arguments and compact results. It performs no UI action.

Preparation and preflight do not grant the next mutation. The live revenue-UI
sequence still requires one fresh observation, one exact semantic action, and
the exact YAML-owned postcondition before any later action.
