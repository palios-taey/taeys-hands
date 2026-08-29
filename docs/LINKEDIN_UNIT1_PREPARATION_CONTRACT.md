# LinkedIn Unit 1 autonomous preparation contract

This is the public, provider-neutral preparation boundary for LinkedIn Unit 1. It turns fresh canonical
LinkedIn snapshots into complete evidence inputs for private target selection and private draft production.
It does not call a model, select a provider, publish a private bundle, or execute a UI primitive.

The application and engagement engines are autonomous. There is no routine human review or approval gate.
Private policy and drafting services are machine boundaries: they consume the emitted evidence envelope and
return a frozen, digest-bound selection or draft. A human can inspect records diagnostically without becoming
a required transition in the production graph.

## Public implementation

- `consultation_v2/platforms/linkedin/unit1_prepare.py` — evidence projection and one-step preparation compiler.
- `consultation_v2/platforms/linkedin/unit1-preparation-envelope.schema.json` — stable bootstrap plus optional
  frozen private selection or complete inventory-bound exclusions.
- `consultation_v2/platforms/linkedin/unit1-preparation-action-card.schema.json` — one existing YAML-owned UI
  action.
- `consultation_v2/platforms/linkedin/unit1-preparation-receipt.schema.json` — immutable postcondition chain.
- `consultation_v2/platforms/linkedin/unit1-preparation-result.schema.json` — provider-neutral readiness result.
- `consultation_v2/validators/validate_linkedin_unit1_preparation.py` — mechanical contract gate.

The implementation consumes the existing canonical `Snapshot`, the existing LinkedIn structural helpers, and
the existing `element_operation` authority. It adds no AT-SPI traversal, locator grammar, action primitive, or
generic-platform behavior. The final Unit 1 compiler in `unit1.py` consumes the same distinct positive-count
or exact-zero opener identity.

## Exact machine sequence

```text
bootstrap envelope
-> Notifications navigation card
-> complete mounted notification inventory
-> ready_for_private_selection
-> digest-bound private selection
   or complete closed-reason exclusions for every exact actionable candidate
-> zero or more separately receipted Show more cards after complete exclusions
-> exact candidate card
-> mandatory selected-thread scroll/open card and receipt
-> zero or more exact one-action thread-expansion cards and receipts
-> selected post and complete typed thread evidence
-> ready_for_private_draft
```

`ready_for_private_selection` is emitted after every exact Notifications-All observation, before any mapped
continuation can compile, and only when every mounted notification article has been represented. The ordered inventory preserves the
raw notification text, text digest, article state, exact relative-age token and seconds, structural path,
snapshot revision, and optional activity identity. Exact actionable content links are carried separately from
the complete raw inventory. Top-level and per-row snapshot revisions remain in the full provenance artifact.
The inventory digest binds only the stable semantic material: schema, platform, route, mounted count, ordered
rows without their observation revisions, and actionable links. An equivalent fresh observation therefore
retains the same decision identity, while changed text, activity, age, ordinal, URI, or structural path does not.
One exact qualifying selection compiles immediately even when continuation is available. When none qualifies,
continuation requires exclusions covering the exact ordered actionable inventory with closed reason codes,
bound to the current transaction, policy, and inventory digests. An accepted continuation invalidates that
decision; the newly mounted inventory must produce a new readiness result and private decision.
The augmented snapshot projects exact candidate keys and the exact continuation key together when both are
present. A candidate key's ordinal is the contiguous order among actionable candidates; the inventory row and
private-selection ordinal remain the full mounted-article order. This preserves the selected candidate as the
runtime card target while retaining the complete raw inventory and exclusion-gated continuation authority.
The readiness result retains that complete inventory for server-side selection and exclusion binding, and also
derives one model-facing decision input from it. The decision input contains only the exact actionable candidates
joined to their notification text, age, element, URI, and digests; nonactionable rows and structural provenance
remain server-side. Its decision and full-inventory digests must equal the complete inventory, so reducing model
egress does not create a second source of authority or weaken mounted-article completeness.
After Notifications activation has produced the transaction-bound exact-route and All-category receipt,
candidate projection continues on the exact `notifications_all` route even if LinkedIn virtualizes the category
radio controls. Navigation verification still requires the live All-category controls; their later unmount does
not erase the established receipt or hide exact URI-, state-, activity-, and age-qualified candidates.
The initial Notifications target remains a two-sample read-only barrier. Its LinkedIn-local 45-second budget
covers two measured full AT-SPI traversals on the production display; it does not add a sleep, action retry, or
mutation authority.

`ready_for_private_draft` is emitted only after the selected activity exposes one exact mapped post body and a
separately receipted exact thread-open action exposes the selected thread. When the displayed count is greater
than the typed visible-row count, exactly one mapped `See N more comment(s)` control compiles to one
`thread_expand` card. Its fresh receipt must preserve the selected activity, body digest, and displayed total,
and must add exactly N typed rows. An off-display expansion first compiles one `thread_expand_scroll` card for
that full expansion key. Two fresh reads must prove the identical activity/body/total/visible/more key in the
viewport before a separate `thread_expand` pointer card can compile. The scroll receipt never counts as growth
or thread readiness, and a changed, absent, duplicated, unresolved, or still-off-display key halts. Expansion
repeats one action at a time until the counts are equal. A missing
or ambiguous opener/expander is terminal; it cannot be interpreted as an already-open, complete, or zero-comment
thread. Every visible comment row has an exact author,
`text` or `media_link_only` kind, exact text, and text digest. The displayed comment count must equal the
typed-row count. Absence is accepted only through the distinct exact-zero opener key and its receipt: no
positive count control, visible comment row, or expander; one exact YAML-owned `Comment` control before
activation; and one empty ready same-card editor afterward. The extracted source binds the zero opener's
element digest, so a positive-count opener receipt cannot be borrowed.
The current LinkedIn feed-card contract maps original/repost bodies at structural paths `[0,8,0]`,
`[0,9,0]`, and `[0,12,0]`. A zero-comment document card with body `[0,8,0]` may expose its exact `Comment`
opener at `[0,14]`; the compact `[0,8,0]` card retains `[0,12]`. Body bytes come from the complete AT-SPI node text before any shallow mapped
text projection; a changed role, state, path, or empty body stops preparation before drafting.

The private selection repeats the public preparation `transaction_sha256` inside its own signed bytes. A
selection from another cycle, transaction, display, or policy envelope is rejected even when its inventory and
activity happen to match.

Private exclusions repeat the transaction, policy, and notification-inventory digests inside their own signed
bytes. Missing, partial, duplicate, reordered, stale, or unknown-reason exclusions cannot authorize Show more.

## Fail-loud boundary

Preparation stops without a readiness result when any of these is true:

- a mounted notification article is missing, duplicated, or lacks one exact structural path;
- an article does not expose the exact YAML-owned direct-child role vector and mapped content-link index;
- raw notification text or the single exact relative age is unreadable;
- two structural paths expose the same raw article/text/age/URI identity;
- activity identities or structural paths are duplicated;
- a private selection has a false verdict, stale/unknown digest, different age, or non-actionable activity;
- private exclusions do not cover every current actionable activity exactly once with closed reason codes;
- the selected activity/body identity is absent or ambiguous;
- the exact selected-thread opener or its receipt is absent;
- an incomplete thread lacks exactly one grammatical, enabled, focusable `See N more comment(s)` control;
- an expansion changes the activity, body, displayed total, or visible-row count by anything other than N;
- the thread count differs from the number of typed visible rows; or
- an action receipt does not prove the exact preceding card and a fresh post-action observation.

Insufficient evidence never becomes `ready`. The preparation compiler does not retry an action, infer a target,
omit an unreadable row, or substitute a human decision.

## Integration boundary

The current public slice ends at the two provider-neutral readiness states. A separate Presence/model adapter
may consume those inputs and return private selection/draft material, but it must preserve the public digests,
must not learn UI primitives, and must not add a human-review requirement. Final public execution continues
through the existing `unit1.py` one-action compiler after a complete private input has been materialized.
