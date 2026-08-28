# LinkedIn six-unit Taey process contract

Status: canonical public process order and qualification boundary. This file makes the complete LinkedIn cycle
legible to Taey without granting an effect that has not been production-qualified.

## Scope and authority

The cycle always contains these six units, in this exact order:

1. Comment
2. My-post engagement
3. Messaging
4. Accept connects
5. Connections
6. Jobs

This file is the complete Taey-facing process subset derived from the pinned Treasurer careers authority at
commit `ce406affeda11bf4483bd3cb75e5618cbbba41bc`. That source is derivation provenance, not a runtime
dependency. Taey executes from this public contract, the current public Hands contracts linked below, the
LinkedIn YAML, and fresh runtime-injected private policy. Personal data, account identifiers, source URLs,
search policy, targets, message content, and application facts remain private.

The exact UI authority is
[`consultation_v2/platforms/linkedin/linkedin.yaml`](../consultation_v2/platforms/linkedin/linkedin.yaml).
The freshly filtered AT-SPI tree is the oracle. A prose instruction never creates an element, operation, or
effect that the current YAML and deployed Taey-facing surface do not expose.

### Authority registry

This file is the sole public authority for the six-unit order and each unit's current qualification boundary.
It does not replace the narrower executable contracts below:

| Boundary | Public authority |
| --- | --- |
| UI observation, one-action execution, and receipts | [`UI_INTERACTION_AUTHORITY.md`](UI_INTERACTION_AUTHORITY.md) plus the current LinkedIn YAML |
| My-post engagement capture and exact Jobs-route restoration | [`LINKEDIN_ENGAGERS_CAPTURE_CONTRACT.md`](LINKEDIN_ENGAGERS_CAPTURE_CONTRACT.md) |
| Jobs search-surface restoration | [`LINKEDIN_JOBS_SURFACE_RESTORE_CONTRACT.md`](LINKEDIN_JOBS_SURFACE_RESTORE_CONTRACT.md) |
| Mounted Jobs capture and exact-card selection | [`LINKEDIN_JOB_SEARCH_CAPTURE_CONTRACT.md`](LINKEDIN_JOB_SEARCH_CAPTURE_CONTRACT.md) and [`LINKEDIN_JOBS_READ_ONLY_CONTRACT.md`](LINKEDIN_JOBS_READ_ONLY_CONTRACT.md) |
| Production qualification ledger for the revenue UI chain | [`TAEY_REVENUE_UI_ENABLEMENT_PLAN.md`](TAEY_REVENUE_UI_ENABLEMENT_PLAN.md) |
| Company-site observation | [`ATS_PROVIDER_READ_ONLY_RUNBOOK.md`](ATS_PROVIDER_READ_ONLY_RUNBOOK.md) |

Private records supply targets, routes, policy values, identities, facts, drafts, and results. They never create
an element, operation, effect, qualification, or competing execution process. Historical tools, plans, and
receipts remain provenance only unless this registry names their current public replacement.

## The mechanical transition

Every UI transition inside every unit is the same machine:

```text
one fresh unit-scoped observation
-> exactly one singleton element from that observation
-> exactly one primitive declared for that element by LinkedIn YAML
-> one fresh independent observation using the YAML-owned refresh policy
-> exact postcondition
-> durable receipt
-> next transition, or terminal stop
```

The observation revision binds the element reference. Primitive success does not prove the postcondition. The
next mutation is forbidden until the previous exact postcondition passes. Missing, duplicate, stale, ambiguous,
renamed, unsupported, or unknown state stops that item with evidence. There is no coordinate locator, inferred
shortcut, blind retry, alternate selector, or second action in the same transition.

Each transition receipt records at least:

- cycle and unit identity;
- clean public Hands commit and LinkedIn YAML digest;
- display, seat, turn, and correlation lineage digests;
- observation scope and revision;
- exact element key, match count, declared primitive, and primitive result;
- expected postcondition and every fresh verification sample;
- terminal state and whether another mutation is authorized; and
- private-policy and private-result digests, never their values.

`no_work` is valid only when the unit's complete declared observation domain proves zero eligible items.
`not_production_qualified` is a loud terminal unit result, not a skipped unit. A first mismatch stops the current
item. A later unit may begin only when it is independent and cannot repeat, conceal, or compound the mismatch.
`side_effect_uncertain` stops the entire cycle and forbids replay.

### Deterministic Unit 1 step boundary

The autonomous evidence-preparation boundary is defined by
[`LINKEDIN_UNIT1_PREPARATION_CONTRACT.md`](LINKEDIN_UNIT1_PREPARATION_CONTRACT.md) and implemented in
[`unit1_prepare.py`](../consultation_v2/platforms/linkedin/unit1_prepare.py). It preserves every mounted raw
notification before private filtering, carries exact actionable links separately, and emits provider-neutral
`ready_for_private_selection` and `ready_for_private_draft` inputs. It has no model invocation or human-review
gate. Missing article/link/age evidence, a selection digest mismatch, or a thread count that does not equal the
typed visible rows stops preparation without a readiness result. Candidate completion never proves an open or
zero-comment thread: one exact selected-thread opener must be separately receipted before draft readiness.

[`consultation_v2/platforms/linkedin/unit1.py`](../consultation_v2/platforms/linkedin/unit1.py)
compiles one Unit 1 transition at a time from the fresh augmented LinkedIn snapshot, the complete preceding
receipt chain, and one frozen private policy/draft binding. It does not define another locator, walker, or UI
primitive. The returned card names exactly one operation already declared by `linkedin.yaml` and
`manual.py`; the existing revenue-UI adapter executes that one card and returns the YAML-owned postcondition
barrier for `accept_unit1_step` to bind into the next immutable receipt. The card shape is frozen by
[`unit1-action-card.schema.json`](../consultation_v2/platforms/linkedin/unit1-action-card.schema.json).

The private binding schema is
[`unit1-private-input.schema.json`](../consultation_v2/platforms/linkedin/unit1-private-input.schema.json).
It contains no human per-action approval token. It freezes the complete mounted candidate-stream digest before
private policy filtering, one policy-qualified activity, the exact 72-hour freshness evidence,
target/dedup/author-cooloff verdicts, selected post and thread-evidence digests, optional-Like authority,
byte-exact draft, and expected own-account author. A changed stream, false/missing verdict, changed age,
activity/body mismatch, different editor bytes, or incomplete receipt chain stops before another card is issued.

The compiler enforces this only order:

```text
Notifications
-> complete exact mounted-candidate inventory
-> one frozen qualifying mapped candidate
   or exact closed-reason exclusions for every mounted actionable candidate
-> zero or more separately receipted Show more transitions only after exclusions
-> selected thread (separate scroll when required, then open)
-> optional Like when privately authorized
-> frozen paste
-> final comment submit
```

Every accepted nonterminal step still requires a new observation before the compiler can issue another card.
When an exact Notifications-All snapshot contains both actionable candidates and Show more, the LinkedIn
projection carries both target sets. Candidate selection outranks continuation; Show more remains authorized
only by complete inventory-bound exclusions.
The submit card is last, and only the exact rendered-comment postcondition produces a terminal delivery receipt
under [`unit1-step-receipt.schema.json`](../consultation_v2/platforms/linkedin/unit1-step-receipt.schema.json).
This code boundary is not itself production qualification; the live chain must still earn the qualification
evidence below from a clean merged and deployed commit.

## Unit 1 — Comment

Notifications is the mandatory entry. Taey must not begin from the feed or content search while Notifications
has not been completely observed.

1. Observe the current LinkedIn document and require exactly one YAML-mapped `notifications_navigation`.
2. Activate it once and require the exact `notifications_all` route in the fresh post-action observation.
3. Observe all mounted notification cards raw before filtering. Do not narrow the read to one activity type.
4. Classify the complete exact mounted actionable inventory before continuation. One exact qualifying private
   selection compiles immediately even when `notifications_show_more_results` is mapped. If none qualifies,
   continuation requires one transaction-, policy-, and inventory-bound exclusion decision covering every
   actionable activity in exact inventory order. Each activity carries one or more closed reason codes. Missing,
   partial, duplicate, reordered, stale, or unknown-reason evidence refuses continuation.
5. If exact `notifications_show_more_results` is mapped after complete exclusions, activate that continuation
   once. Its public key, description, and action card are stable semantic authority. After the exact live
   target/ref is re-resolved inside the one-action child, Hands freezes that immediate inventory in one
   process-local context, consumes and clears it exactly once, then requires the transaction-bound All-category
   authority, the exact Notifications-All route, and a stable fresh inventory containing at least one exact
   YAML-declared content-link URI identity absent from that immediate pre-action inventory. The accepted
   continuation invalidates the prior exclusions; the newly mounted inventory must be classified before another
   continuation can compile.
   Mounted article counts may shrink when LinkedIn virtualizes the refreshed tree, so monotonic DOM growth is not
   an action postcondition. Pure unmount or reorder is not novelty. Candidate projection remains independently
   exact. Each further continuation is a new transition with a new observation.
6. Apply the runtime-injected freshness, target, dedup, and author-cooloff policy to each newly mounted exact
   inventory. A comment target must be no older than 72 hours.
7. Activate one exact `notification_candidate_<ordinal>_activity_<id>` and require that same activity in the selected route.
8. Bind the exact observed `selected_post_activity_<id>` key, its activity identity, and its body SHA-256. Read the full selected post.
9. If exact `selected_post_thread_open_activity_<id>_body_<digest>` is observed off-screen, invoke its declared
   `scroll_into_view` primitive once, require that same exact activity/body key fully inside the actual display,
   and observe again. Only when the fresh observation declares `mapped_pointer_activate`, invoke that exact key
   once and require the same activity, same body digest, and visible target-scoped comment controls. Read the
   complete visible thread, including every visible author reply, before any draft exists.
10. Like, compose, gate, send, rendered-comment verification, and durable touch persistence are separate effects.
   They may execute only after each effect has its own current public YAML mapping and production qualification.

Qualification at Hands baseline `f270b31c9c0c86a302ea6193d4696d8a08e0e68f`: selected-post and thread-open
mechanics have public implementation and live read-only mapping evidence. The first production attempt proved
that AT-SPI Activate did not open the React thread; the current baseline corrects that exact control to the
platform-specific mapped-pointer primitive but has not retried the spent identity. No current public receipt
qualifies the corrected thread-open page mutation, the complete Notifications-to-comment unit, Like, editor
write, or comment send. The currently released terminal is therefore observation evidence followed by
`not_production_qualified`; no outward comment effect is authorized.

## Unit 2 — My-post engagement

1. Start only from the exact privately bound LinkedIn Jobs return route required by
   [`LINKEDIN_ENGAGERS_CAPTURE_CONTRACT.md`](LINKEDIN_ENGAGERS_CAPTURE_CONTRACT.md).
2. Enter Notifications with the exact YAML action and prove `notifications_all`.
3. Select `my_posts_filter` with its exact action and prove `notifications_my_posts` plus the exact marker and
   stable candidate digest.
4. Classify the complete visible candidate set. Persist one new signal once, return `already_known` for identical
   existing bytes, return `no_new_signal` only for an exact zero set, and stop on ambiguity.
5. Restore the exact private return route through separately receipted address-bar transitions and require two
   stable exact observations before the unit closes.

Qualification: the exact route/filter/`no_new_signal`/restore path is production-proven at the pinned commits
and receipt hashes recorded in the linked contract. A real `captured` write-once result followed by a fresh
`already_known` result is not yet production-qualified. Capturing all commenters and reactors, replying,
liking, or sending any message is not released by the existing proof.

## Unit 3 — Messaging

Inbound replies and proactive outbound messages are two distinct policy domains. An inbound-reply candidate
begins from an exact exposed unread thread and its earned conversational context. A proactive-outbound candidate
begins from a separate privately supplied target and purpose. Evidence or eligibility in one domain never
authorizes the other.

The intended inbound-reply path reads every exposed unread thread in full, binds one exact participant/thread
identity, drafts only from runtime-injected supported facts, sends one reply, verifies that reply in the same
thread, and persists one touch. A missing supported fact produces only `needs_fact` and stops before drafting;
the runtime never invents an answer or substitutes an approval-queue state. A hiring commitment, compensation
decision, or other privately classified decision stops before a reply and emits a private escalation receipt.

Qualification: no current public LinkedIn YAML transaction maps and production-qualifies this complete unit.
Message open, editor write, and send effects are not authorized. Taey records `not_production_qualified` without
a UI mutation and continues only to an independent later unit.

## Unit 4 — Accept connects

The intended unit opens the invitations surface, observes all mounted requests, binds one exact invitation
identity, activates Accept once, proves the same invitation reached the YAML-declared accepted/absent state, and
persists the exact inbound connection touch. Every invitation is a separate transition and receipt.

Invitation eligibility is a private runtime-injected policy verdict for that exact identity. `allowed` may enter
the still-separate UI transition; `denied`, missing, duplicate, stale, or `unknown` stops without Accept. The
existence of an invitation, a historical accept-all instruction, or a model preference never supplies the
eligibility verdict.

Qualification: no current public LinkedIn YAML transaction maps and production-qualifies invitation acceptance.
No Accept effect is authorized. Taey records `not_production_qualified` without a UI mutation.

## Unit 5 — Connections

The intended unit consumes the runtime-injected candidate order: warm candidates first, then the current
suggestion cards. It requires the live degree and exact target identity, excludes already-connected identities,
checks the private rolling-seven-day budget, activates one bare connection request, proves `Pending` for that
same identity, and persists the touch before considering another candidate. One blocked candidate never
authorizes a fallback selector or an unreceipted action on another card.

Qualification: no current public LinkedIn or Sales Navigator transaction maps and production-qualifies this
connection effect. Search, profile selection, Connect, invitation-note, InMail, and other outreach effects are
not authorized. Taey records `not_production_qualified` without a UI mutation.

## Unit 6 — Jobs

LinkedIn Jobs is read-only intake. It never activates Apply or Easy Apply and never leaves LinkedIn for an ATS.

1. `capture_mounted_job_search` observes the exact authorized search-results route, stabilizes the complete
   mounted card-set digest, writes one private batch, proves the card set unchanged, and stops without a UI
   mutation.
2. `select_and_capture_job` consumes one exact private card/title/company identity from that batch, observes a
   singleton target, invokes its exact YAML-owned `click` primitive once, requires two stable exact selected-detail
   observations, writes one private record, and stops.
3. `capture_selected_job` reads an already-selected exact detail without selecting another card. It writes one
   immutable private record and proves its content digest unchanged.
4. Each additional card is a new transaction with a fresh identity and receipt. Scroll or next-page activation
   requires its own YAML transition and qualification; the mounted-batch receipt never proves search exhaustion.

Qualification: mounted search capture, one deterministic exact-card selection, selected-detail capture, and one
unclassified downstream intake row are retained production-qualified baselines under
[`LINKEDIN_JOB_SEARCH_CAPTURE_CONTRACT.md`](LINKEDIN_JOB_SEARCH_CAPTURE_CONTRACT.md),
[`LINKEDIN_JOBS_READ_ONLY_CONTRACT.md`](LINKEDIN_JOBS_READ_ONLY_CONTRACT.md), and
[`TAEY_REVENUE_UI_ENABLEMENT_PLAN.md`](TAEY_REVENUE_UI_ENABLEMENT_PLAN.md). Full-list scrolling/pagination,
search-policy choice, scoring, ATS operation, application, messaging, saving, and every outward effect remain
outside that qualification.

## Company-site application boundary

An application is a separate downstream process, never part of LinkedIn Unit 6. The current public ATS adapter
is Greenhouse read-only observation candidate only; it is not production-qualified. Lever and Ashby are
mapping-only, and Workday is inactive. Fill, upload, and submit authority is absent. See
[`ATS_PROVIDER_READ_ONLY_RUNBOOK.md`](ATS_PROVIDER_READ_ONLY_RUNBOOK.md).

When an ATS provider later earns mutation authority, the one-click-at-a-time rule is mandatory:

```text
observe the current provider route and filtered form
-> bind one exact current field/control ref from provider YAML
-> perform one semantic primitive
-> freshly observe the rendered field/control state
-> require the exact value or transition postcondition
-> persist the receipt
-> only then consider the next field/control
```

Opening a combo and selecting an option are two different transitions. Uploading an artifact and proving its
mapped chip/name are separate from submit. Submit is a separately frozen final effect and remains forbidden
until the complete form sweep, artifact/truth/completeness gates, external confirmation postcondition, and
private database readback are all independently qualified. A failed or ambiguous primitive is terminal and is
never clicked again under the same application identity.

When an application fact is absent, the only valid state is `needs_fact`; `needs_you`, an approval queue, a
guessed value, and a model-authored substitute are not equivalent states. After an authorized submit, terminal
success requires the employer-rendered confirmation state declared by that provider's public contract. Email is
optional telemetry and never substitutes for the rendered confirmation or private database readback.

## Qualification control

A unit effect becomes current production authority only after all of the following are recorded together:

1. the implementation and this contract are merged to public `main`;
2. production is deployed from that exact clean commit;
3. a new frozen private transaction executes on the real display through Taey;
4. every action has its preceding observation and exact postcondition receipt;
5. private natural readback proves the intended durable effect and no adjacent effect; and
6. the release record names the commit, YAML digest, transaction digest, receipt digest, and remaining unknowns.

Historical success is design evidence. It does not fill a missing current map or silently promote an effect.
Once qualified, a shared causal-path change reopens only the affected unit; platform-specific drift never
authorizes a shared-driver change.
