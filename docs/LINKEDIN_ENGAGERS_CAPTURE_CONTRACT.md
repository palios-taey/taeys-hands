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
`source_ref`, `sink_ref`, `notifications_name`, and `return_url`.
`notifications_name` is a nonempty bounded private live label; runtime exact
AT-SPI equality and a match count of one are the authority. `return_url` must
be the exact HTTPS LinkedIn Jobs search-results URL occupied at the start.

While holding one CAREERS lock, Hands:

1. Proves the exact private Jobs URL and one exact Notifications link, then
   requires exactly the YAML-owned `jump` action at index `0` and invokes it
   once.
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
artifacts. This contract is not a production qualification claim; qualification
requires exact-SHA R5 approval and real before/engagement/after receipts from a
clean display `:18` deployment.
