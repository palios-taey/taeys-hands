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
generic-platform behavior. The existing final Unit 1 compiler in `unit1.py` remains unchanged.

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
present. This preserves the selected candidate as the runtime card target while retaining exclusion-gated
continuation authority.

`ready_for_private_draft` is emitted only after the selected activity exposes one exact mapped post body and a
separately receipted exact thread-open action exposes a complete typed thread. A missing opener is terminal; it
cannot be interpreted as an already-open or zero-comment thread. Every visible comment row has an exact author,
`text` or `media_link_only` kind, exact text, and text digest. The displayed comment count must equal the
typed-row count. Absence is accepted only as exact zero after the thread-open receipt: no count control and no
visible comment row.

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
- the thread count differs from the number of typed visible rows; or
- an action receipt does not prove the exact preceding card and a fresh post-action observation.

Insufficient evidence never becomes `ready`. The preparation compiler does not retry an action, infer a target,
omit an unreadable row, or substitute a human decision.

## Integration boundary

The current public slice ends at the two provider-neutral readiness states. A separate Presence/model adapter
may consume those inputs and return private selection/draft material, but it must preserve the public digests,
must not learn UI primitives, and must not add a human-review requirement. Final public execution continues
through the existing `unit1.py` one-action compiler after a complete private input has been materialized.
