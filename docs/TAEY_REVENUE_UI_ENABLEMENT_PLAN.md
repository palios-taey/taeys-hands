# Taey revenue UI enablement

Status: current execution plan for tracker task `task-21a2f74b`.

This plan extends Taey's existing supervised UI capability to revenue surfaces. It does not restore an old
coordinate script or create another direct UI grammar. `ui_action` remains the only direct model-facing UI
grammar. A routine lane may expose a frozen domain transaction, as `consult_chat` does, only when its driver
compiles to the same observation, primitive, postcondition, and receipt contract; that domain transaction is
not a second locator or action grammar.
Hands owns observation, references, one action, postcondition verification, and receipts. Domain services own
purpose and private state. Presence supplies identity, lease, and authority transport only when the existing
supervised-seat transport cannot do so.

## Machine invariant

Every surface uses the same lifecycle:

```text
fresh scoped observation
-> one snapshot-bound ui_action
-> exact surface-owned postcondition
-> durable receipt
-> next action, or terminal stop
```

One action never implies the next action. A primitive returning success is not a postcondition. A stale,
missing, duplicate, ambiguous, or unknown observation authorizes no mutation. There are no hidden retries,
coordinate locators, fallback selectors, or autonomous model-authored action loops.

The implementation reuses the canonical AT-SPI traversal and existing Hands primitives. Platform adapters may
project a bounded dynamic collection from that tree; they may not introduce a second walker.

## Public and private boundary

Public Git contains everything a downloaded Taey needs to understand and execute the mechanics:

- surface identifiers and display-independent platform adapters;
- exact static element maps and structural anchors;
- the `ui_action` request, authority, effect, postcondition, and receipt schemas;
- bounded private-projection schemas for dynamic page content;
- private-input schemas and fail-loud validation, but no private values;
- runners, service templates, mechanical validators, and production runbooks.

Runtime-injected private state contains:

- credentials, cookies, account and person identifiers;
- saved-search text, URLs, filters, and business targeting policy;
- the selected source/dedup policy and private database connection;
- resumes, cover letters, application answers, drafts, messages, and proposals;
- private output records and full page content when it can identify a person or account.

Public receipts carry schema versions, public commits, policy/input digests, action lineage, postcondition
verdicts, counts, and content hashes. Raw dynamic content is written off-context to the private sink and is
never serialized into the model transcript. Private receipt storage may retain the corresponding values.
Public code never points at an operator-only repository or path.

## Implementation order

### 1. LinkedIn Jobs read-only

Build the smallest complete vertical slice on the existing LinkedIn display:

1. Observe the current LinkedIn surface through the canonical tree.
2. Expose the exact Jobs navigation control as a snapshot-bound reference.
3. Execute one navigation action and require a LinkedIn-Jobs postcondition from a fresh observation.
4. Load one runtime-injected search policy without exposing its value to the public projection.
5. Project the mounted job-card collection into the off-context private sink as bounded structured records
   using the canonical tree; expose only count, shape, and digest to Taey.
6. Open one card with one action and verify selected-card identity before reading detail content.
7. Extract the complete job description and apply-channel facts into the private sink.
8. Emit a public-safe receipt joining the input-policy digest, card identity digest, description hash,
   private-store result, and independent readback result.

The historical implementation is evidence only. Its coordinate clicks, `xdotool` navigation, custom recursive
walker, and implicit multi-action sweep are not copied. The private runtime must select one source/dedup policy;
public mechanics do not silently choose between conflicting historical policies.

Acceptance is one real read-only production unit with:

- one public Hands commit and one exact surface-policy digest;
- no UI mutation without the previous exact postcondition;
- full job detail captured with selected-card identity agreement;
- a non-empty private-store write and independent readback;
- no private values committed to public Git or public receipts;
- a terminal receipt that distinguishes success, valid no-new-results, and technical failure.

### 2. LinkedIn engagement

Restore the six historically working leaves independently: comment, own-post engager capture, messaging,
invitation acceptance, connection invitation, and Jobs. Each leaf keeps its platform-specific surface map and
postcondition. Read-only leaves qualify first. Outward leaves also require their existing content, truth, voice,
and account-policy authority before the single outward action is exposed.

### 3. Sales Navigator, ATS, Upwork, and X

Apply the same machine without sharing platform-specific controls:

- Sales Navigator: search/profile visibility before any connection or message.
- ATS: form visibility and required-field projection before a separately authorized submit.
- Upwork: scan and proposal-form visibility before a separately authorized proposal.
- X: clean public implementation and read-only account-state proof before any public action.

## Qualification and release

Each natural unit is qualified serially on the real display, then repeated with independent Taey workers on
independent displays. Parallel workers share no display lease, browser profile, private payload, receipt root,
or transaction identity. One terminal lane cannot retry or affect another lane.

A production baseline is frozen only after merge to public `main`, deployment from that exact commit, mechanical
receipt verification, and a real production observation. The release record names the public commit, private
input digest, surface-policy digest, production receipt, and remaining unknowns.
