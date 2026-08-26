# LinkedIn My Posts new-engagement capture

This is the third operation in the existing public LinkedIn transaction
machine:

```json
{"operation":"capture_visible_new_engagement_signal"}
```

It uses the same `linkedin` platform YAML, driver, CAREERS lock, private
transaction envelope, and `scripts/run_linkedin_jobs.py` runner as the two
qualified Jobs operations. There is no second platform or runner.

## Exact machine

The private canonical transaction contains exactly `schema`, `operation`,
`source_ref`, `sink_ref`, and `return_url`. `return_url` must be the exact HTTPS
LinkedIn Jobs search-results URL occupied at the start. The Notifications
authority is public and platform-owned: exactly one showing, enabled link with
the exact normalized LinkedIn Notifications URI, the exact `jump` action at
index `0`, and a nearest `document web` ancestor whose URL equals the current
platform document. LinkedIn's separate `/preload/` document is not authority,
and the mutable unread count in the accessible name is never transaction input.

While holding one CAREERS lock, Hands:

1. Proves the exact private Jobs URL and one current-platform-document
   Notifications link, then invokes its already-proven YAML-owned `jump` action
   at index `0` once.
2. Requires two fresh cache-invalidating observations of the exact
   `/notifications?filter=all` route and one exact `My posts` radio control.
3. Requires exactly the YAML-owned `press` action at index `0`, invokes it
   once, then requires two fresh observations of
   `/notifications?filter=my_posts_all`, one `My posts’ filters` marker,
   and the same candidate-set digest.
4. Classifies only showing links named with the observation-only prefix
   `Unread notification.` and an HTTPS LinkedIn `/feed/` or `/posts/`
   path. Zero candidates is `no_new_signal`; more than one is terminal
   `ambiguous_signal`; one is written once to the private sink.
5. Derives the stable signal record and digest only from schema, notification
   name, and notification URI. `source_ref` remains hashed receipt provenance
   and cannot change the stable identity. An already-present artifact with
   matching bytes is successful `already_known`, never an indeterminate sink
   failure.
6. Before any success, resolves the routed Firefox PID, focuses that exact PID,
   sends `Ctrl+L` once, proves the exact address bar is focused, selects its
   complete AT-SPI Text range, pastes the private return URL once, proves the
   exact text, sends `Return` once, and requires two stable observations of
   the exact return URL and exactly one current Notifications target by the
   YAML-owned role, states, and exact Notifications URI. Its full current
   state digest must remain unchanged for both observations; the mutable unread
   count in its label is not restoration identity.

There is no Back action, pointer action, coordinate, shell UI command, default
action, alternate focus, alternate selector, blind retry, or outward social
action.

## Boundary and result

Taey sees only `{"display":":N"}`. Presence binds the private transaction and
invokes:

```text
scripts/run_linkedin_jobs.py --display DISPLAY --transaction-file ABS_PRIVATE_JSON --expected-transaction-sha256 64HEX --receipt-file ABS_NEW_RECEIPT_JSON --private-root ABS_PRIVATE_ROOT --requester SEAT_ID --turn-id TURN_ID --correlation-id CORRELATION_ID --process-generation 32HEX --deadline-seconds 30..1700
```

The public result has exactly eleven keys: `ok`, `platform`, `display`,
`state`, `failure_code`, `records_observed`, `records_written`,
`content_digest`, `receipt_sha256`, `turn_lineage_sha256`, and
`restore_verified`. Successful facts are:

- `captured`: `1/1/digest`, restored;
- `already_known`: `1/0/digest`, restored;
- `no_new_signal`: `0/0/null`, restored.

Jobs operations retain their existing exact ten-key public result. Raw labels,
URLs, notification text, references, paths, and records remain in
owner-controlled mode-`0700` private roots and immutable mode-`0400`
artifacts.

## Canonical preparation and preflight

Never assemble an engagement transaction, claim, receipt, or sink with
individual directory or JSON-write commands. Start with a wholly new
public-safe seat and correlation identity and one existing owner-private draft
manifest. The draft must be an owner-owned, nonsymlink, strict UTF-8 JSON
regular file at exact mode `0400` beneath an owner-owned private root at exact
mode `0700`. Its semantic fields are exactly the existing engagement private
input contract:

```json
{"operation":"capture_visible_new_engagement_signal","return_url":"https://www.linkedin.com/jobs/search-results/?PRIVATE_QUERY","schema":"linkedin_engagement_private_input_v2","sink_ref":"ABS_PRIVATE_ROOT/sinks/PUBLIC_SAFE_SEAT/PUBLIC_SAFE_CORRELATION","source_ref":"PRIVATE_AUTHORIZED_SOURCE_REFERENCE"}
```

The absolute `sink_ref` must equal the sink derived from the seat and
correlation identity. Formatting whitespace and a trailing newline in the
draft are allowed; duplicate fields, non-JSON constants, extra or missing
fields, unsafe paths, an inexact return route, and every other semantic
change are refused. Private fields and paths are environment bindings and
never appear in arguments or compact command results.

From the clean deployed public Hands checkout, run exactly:

```bash
export TAEY_LINKEDIN_ENGAGEMENT_PRIVATE_ROOT=/owner/private/linkedin-engagement
export TAEY_LINKEDIN_ENGAGEMENT_DRAFT=/owner/private/linkedin-engagement/drafts/frozen-engagement.json

SEAT_ID=PUBLIC_SAFE_NEW_SEAT
CORRELATION_ID=PUBLIC_SAFE_NEW_CORRELATION

PREPARATION_JSON="$(
  python3 scripts/prepare_linkedin_engagement.py prepare \
    --seat-id "$SEAT_ID" \
    --correlation-id "$CORRELATION_ID"
)" || exit 1

TRANSACTION_SHA256="$(
  python3 -c 'import json,sys; print(json.load(sys.stdin)["transaction_sha256"])' \
    <<<"$PREPARATION_JSON"
)" || exit 1

python3 scripts/prepare_linkedin_engagement.py preflight \
  --seat-id "$SEAT_ID" \
  --correlation-id "$CORRELATION_ID" \
  --expected-transaction-sha256 "$TRANSACTION_SHA256" || exit 1
```

`prepare` establishes the accepted-identity boundary at the exact claim
parent, creates the identity-derived transaction, receipt, and sink topology
at `0700`, canonicalizes the semantic draft, writes the no-newline transaction
once at `0400`, and leaves claim and receipt absent. `preflight` independently
rereads both the draft and frozen transaction, proves their semantic and digest
identity, requires an empty exact sink, and requires claim and receipt to remain
absent.

After the claim parent is safely established, every preparation or preflight
refusal spends the identity with one immutable `0400`
`linkedin_engagement_preparation_terminal_v1` marker at the exact claim path.
It contains only public-safe identity, command, state, and failure code. It is
never overwritten or deleted; corrected input requires a wholly new identity.
The mechanical validator is:

```bash
python3 consultation_v2/validators/validate_linkedin_engagement_preparation.py
```

Preparation proves only the immutable private transaction topology. It does
not inspect the UI, satisfy the existing Jobs-search start gate, restore a
selected-detail surface, authorize a retry, or qualify a production run. Do
not invoke the engagement runner unless Taey has separately established the
exact required Jobs-search start surface. The currently observed
selected-detail surface is not an accepted start state; production
qualification therefore waits for an explicit Taey restore transaction or a
separately preflighted CAREERS display.

## Production qualification — 2026-08-26

The display-`:18` Taey sequence passed from clean public production checkouts:

- Hands `673702160424eaf45910aa21f8673c0907df6615`;
- Presence `56aede9a064c808ee205e213469692d177923c29`;
- Jobs-before receipt SHA-256
  `25567fb65e82126c632f49b7abe8907bde32cecbc5cc7369dd60dc343476ca7e`:
  exact action, stable `2`, private sink `1/1`, lock acquired and released;
- engagement receipt SHA-256
  `aa98208e4adc6d2e2be48f65fd0ac8ccb5fe2ffba9bc036d49052cfc6f59213f`:
  exact `jump[0]`, stable `2`, exact `press[0]`, stable `2`,
  `no_new_signal` `0/0`, return stable `2`, lock acquired and released;
- Jobs-after receipt SHA-256
  `c7e608caeb470e2bf50e3337dbbae1e9a9ebb871df0fc7ac9972d711c860f3b4`:
  exact action, stable `2`, private sink `1/1`, lock acquired and released.

The first engagement identity terminated without retry at receipt SHA-256
`f17279e99add79045907bf99d3635c2632db12c39eef87720088ee2b1aa5dc65`.
It proved the exact return URL but exposed the mutable-unread-label defect fixed
by PR `#222`; the fresh post-fix identity produced the successful chain above.
The private receipts remain the evidence authority. This public record exposes
only their hashes and non-personal terminal facts.

The v1 transaction and receipt schemas remain frozen for historical
verification. The label-free preparer emits only
`linkedin_engagement_private_input_v2`, and the runner emits only
`linkedin_engagement_receipt_v2`. An authorized operator can prove the exact
private prod2 receipt remains valid without publishing it:

```bash
python3 consultation_v2/validators/validate_linkedin_engagement_history.py \
  --prod2-receipt "$AUTHORIZED_PRIVATE_PROD2_RECEIPT"
```

The qualification above remains historical evidence for its pinned commits.
It is not evidence for later transaction preparation: an accepted private draft
must not freeze the mutable unread-count label. Current qualification therefore
requires the current-platform-document URI/action authority described above and
a wholly new transaction identity.
