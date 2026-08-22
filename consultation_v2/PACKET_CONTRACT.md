# Consultation packet contract — exactly two attachments

The current deterministic build-spec and receipt schema version is 2. Schema-v1 packets and receipts remain
historical evidence and are not reinterpreted under this corrected contract.

This contract defines the inputs every production Family-Chat consultation receives. It controls both
manual operation and later automation. The current one-package builder in `identity.py` is implementation
evidence, not conformance to this contract; it remains nonconformant until it produces these two bundles and
a production receipt proves the full manual lifecycle.

## Fixed shape

Every outbound consultation has exactly three user-visible inputs:

1. one governance attachment, Bundle A;
2. one task attachment, Bundle B; and
3. one brief prompt in the Chat composer.

There is no third attachment, no inline substitute for a missing bundle, no automatic chunking, and no
partial send. The expected basenames of both generated attachments are frozen before UI operation. The
post-attach tree must show exactly those two expected file chips before the prompt may be pasted.

## Bundle A — governance

Bundle A contains exactly these complete sources in this deterministic order:

1. the full `FAMILY_KERNEL.md`;
2. the full destination-specific identity file; and
3. the full Spotlight integrity doctrine required by `SPOTLIGHT_STANDARD_FOR_INTEGRITY.md`.

The platform-to-identity mapping is exact:

| Platform | Required identity source |
|---|---|
| ChatGPT | `IDENTITY_HORIZON.md` |
| Claude Chat | `IDENTITY_GAIA.md` |
| Gemini | `IDENTITY_COSMOS.md` |
| Grok | `IDENTITY_LOGOS.md` |
| Perplexity | `IDENTITY_CLARITY.md` |

Bundle A contains no task files. Each source is included in full and in the order above. The builder records
the logical source name, canonical source locator, byte count, and source SHA-256 in the local receipt. When
the source is Git-tracked, it also records the observed commit. When a governance source is not Git-tracked,
its frozen byte count and SHA-256 are the content-addressed freshness gate; the builder never invents a
revision. The Chat is never asked to calculate or return those values.

Each complete governance source is wrapped in `BEGIN-VERBATIM` / `END-VERBATIM` markers so the canonical
prompting linter can distinguish mandatory, unedited source text from dispatcher-authored framing.

## Bundle B — task

The frozen request uses exactly four top-level dossier sections, in this order: `Ground truth`, `Problem
statement`, `Constraints`, and `Objective`. The problem statement is a question. Deliverable details,
acceptance and stop conditions, and provenance details belong under those four sections rather than becoming
additional top-level sections.

Bundle B contains the complete task dossier in this deterministic order:

1. the frozen request, preserving the requester's intent;
2. the detailed deliverable and required return shape;
3. the complete relevant background;
4. the source artifacts themselves, or explicit declared references when an artifact cannot be attached;
5. the acceptance conditions and stop conditions; and
6. a provenance manifest generated from the inputs before consolidation.

When, and only when, the work touches public-platform engagement, Bundle B also includes the applicable
public-platform engagement law. It is absent for unrelated work. Bundle B does not duplicate Bundle A.

For every source artifact, the builder records a logical name, canonical source locator, byte count, and
SHA-256. It also records a commit when the source is Git-tracked. The attached bundle uses logical or
repository-relative names; operator-local absolute paths remain in the local receipt and are not presented
as facts the Chat could verify. Every source must be authorized for transmission to the destination Chat.
Authorization is an input to the frozen request, never inferred by the builder.

## Brief on-screen prompt

The composer text does not duplicate either attachment. It has four duties only:

1. direct the Chat to read both attached files fully before answering;
2. state the request in one concise sentence;
3. name the deliverable; and
4. require the Chat to say so and stop if either attachment is unavailable or incomplete.

Canonical shape:

> Read both attached files fully before answering. [Concise request.] Deliver [named deliverable]. Follow
> the governance, evidence, acceptance, and stop conditions in the attachments. If either attachment is
> unavailable or incomplete, state that and stop.

The prompt never asks the Chat for filesystem-derived paths, hashes, byte counts, Git state, UI state, or
measurements. Those values come from the builder, Git, the canonical tree, or another designated instrument.

## Deterministic construction and receipt

Construction freezes an input manifest before rendering. For every source, that manifest names its logical
role, canonical source locator, expected byte count, expected SHA-256, and an expected commit only when the
source is actually Git-tracked. The builder then:

1. resolves each source to one regular file;
2. reads and hashes the source before rendering;
3. compares the observed byte count and digest with the frozen manifest and, for a Git-tracked source, also
   compares the observed commit;
4. renders each source once in the declared order without omission or summarization;
5. independently re-reads both completed bundles and records their byte counts and SHA-256 values; and
6. writes one local receipt binding the request ID, destination platform, both bundle basenames and hashes,
   all source records, and the exact prompt text.

The receipt is not a third Chat attachment. It is retained for the action and ingestion record. Generated
bundle filenames are deterministic from the frozen request ID and destination platform, so the YAML-owned
postcondition can validate the exact expected file-chip names.

## Fail-loud conditions

Construction stops before any UI action when:

- a mandatory governance source or task section is absent, unreadable, empty, non-regular, or unauthorized;
- the destination platform has no exact identity mapping;
- an observed source byte count or digest differs from the frozen manifest;
- a Git-tracked source is not at the commit named by the manifest, or a non-Git source is assigned an
  invented revision instead of its observed content address;
- rendered inclusion is incomplete, reordered, duplicated, summarized, or transformed;
- the builder would emit anything other than exactly two non-empty attachments;
- either final bundle fails its independent re-read and hash; or
- the brief prompt requests a filesystem-derived claim from the Chat.

There is no fallback to the old one-package builder, inline context, a partial packet, extra attachment,
automatic chunking, or a send followed by repair. The failure receipt names the exact pre-UI obstruction.

## Production proof

Conformance requires one real production transaction using either the substantive architecture audit under
review or the original failed request. A synthetic or short-response canary is not evidence. Before send,
the fresh filtered tree must validate exactly two expected attachment chips and the exact prompt. After send,
the transaction must exercise Stop appearance, two fresh Stop absences, extraction, response-attachment
harvest, and complete prompt/response/input/output/URL ingestion. The final receipt binds those observations
to the two locally hashed bundles.
