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

## Current observed status

- Grok's repeated non-actionable notification loop is fixed; it is not a remaining revenue-UI gate.
- LinkedIn `capture_mounted_job_search` and exact `select_and_capture_job` selected-detail capture have real
  successful production receipts. They remain current proven units pending joined qualification and are
  consumed downstream by receipt; adapter work does not modify their YAML, runner, snapshot, lock, or receipt
  contracts.
- Public `palios-taey/taey-apply` main `ee8406f16ac552a8cf557538fd136e7750125564` validates the exact
  paired Hands search and selected artifacts/receipts and writes one unclassified LinkedIn job into the
  existing private jobs database. It does not score, filter, drive an ATS, or submit.
- The Presence intake adapter is the active unfinished unit. No comment, message, invitation, proposal,
  application fill, or submit authority is released by the completed read-only chain.

**Inferred:** the minimum next cut is one Taey-facing Presence call that invokes the frozen public intake
connector and proves exact private readback. **Unknown:** the adapter's merged/deployed commit and production
receipt, scorer one-shot safety, the first current ATS provider, and whether the captured lead contains enough
information to resolve an ATS target.

## Implementation order

### 1. LinkedIn Jobs to unclassified application intake

The source mechanics are current proven units pending joined qualification:

- `capture_mounted_job_search` captures only the cards already mounted on one authorized search-results page;
  it does not enter search terms, change filters, scroll, open, save, dismiss, or apply.
- `select_and_capture_job` performs one exact `click[0]`, requires the private target/title/company and selected
  detail to stabilize for two fresh observations, writes the selected detail once, verifies unchanged content,
  releases the CAREERS lock, and stops.
- The selected record is an application lead: it contains the private search reference, selected source
  URL/current job identity, exact detail heading, and description. Apply-channel facts are not part of the
  captured record and must not be inferred.

The active natural unit is the Presence intake adapter:

1. Expose one empty-input or otherwise opaque Taey-facing call; Taey supplies no paths, job values, IDs,
   policy, or database arguments.
2. Bind the seat/correlation identity to one frozen private transaction containing the exact Hands search
   artifact/receipt, selected artifact/receipt, and card digest.
3. Invoke exact public `taey-apply` commit `ee8406f16ac552a8cf557538fd136e7750125564` once.
4. Require one exact jobs row whose canonical URL, title, company, location, and description match the paired
   capture; a non-identical collision, duplicate identity, digest mismatch, unsafe path, or indeterminate write
   is terminal.
5. Require a new row to retain SQL `NULL` for `verdict`, `score`, and `applied_at`; `applications` and
   `apply_runs` counts remain unchanged. A distinct transaction referencing identical evidence may return
   `already_present` with zero writes.
6. Return only the compact connector/Presence receipt and close the turn. Do not invoke a scorer, ATS, or
   another UI action.

Acceptance requires two production proofs from exact public/deployed commits:

- one existing paired capture with successful receipts ingests or proves identical prior presence with
  independent database readback; and
- one fresh mounted-search -> exact selected-detail -> separate intake transaction joins the Hands and intake
  receipt hashes, ends with zero open turns/leases, and produces no outward effect.

Adapter work must not change the current proven-unit LinkedIn YAML, runners, snapshot traversal, CAREERS lock,
private record shapes, or public result shapes. If the lead later cannot resolve one exact ATS target, add only
the missing read-only target projection under a new frozen contract and requalify it; do not widen search by
assumption.

### 2. LinkedIn engagement

Keep the six historical leaves independent: comment, own-post engager capture, messaging, invitation
acceptance, connection invitation, and Jobs.

- Jobs mounted-search and selected-detail capture are current proven units pending joined qualification; do
  not reopen them for intake-adapter work.
- Own-post engagement currently proves only the `no_new_signal` route/filter/restore result. Full qualification
  still requires one real `captured` write-once receipt followed by a fresh `already_known` receipt; lack of a
  live signal is not a reason to change the map.
- Comment, messaging, invitation acceptance, and connection invitation remain separate outward/account-effect
  leaves. Each requires a fresh read-only map proof, its own frozen transaction and postcondition, and existing
  content, truth, voice, target, dedup, budget, and account-policy authority before one outward action is
  exposed.

No leaf shares a fallback or platform-specific control with another leaf, and no leaf's missing qualification
blocks the Jobs-to-intake slice.

### 3. Sales Navigator, ATS, Upwork, and X

Apply the same machine without sharing platform-specific controls:

- Sales Navigator: search/profile visibility before any connection or message.
- ATS: first name one current provider and public baseline, then qualify exact form identity and required-field
  projection read-only. Field fill is a separately authorized non-submit mutation lane; submit is a further
  separately frozen outward authority. Historical fill/submit evidence is design evidence only and authorizes
  no current action.
- Upwork: scan and proposal-form visibility before a separately authorized proposal.
- X: clean public implementation and read-only account-state proof before any public action.

After the first clean Presence-to-intake production PASS, two read-only lanes may proceed independently:
(a) inspect and expose the narrowest one-shot scorer path with zero ATS/action-task side effects while both
polling loops remain inactive; and (b) measure one current ATS provider's form identity, public-substrate
location, and required-field projection with zero field or submit actions. They join only on the same immutable
intake digest after separate terminal receipts. No provider, score threshold, fill authority, or submit
authority is inferred.

## Qualification and release

Each natural unit is qualified serially on the real display, then repeated with independent Taey workers on
independent displays. Parallel workers share no display lease, browser profile, private payload, receipt root,
or transaction identity. One terminal lane cannot retry or affect another lane.

A production baseline is frozen only after merge to public `main`, deployment from that exact commit, mechanical
receipt verification, and a real production observation. The release record names the public commit, private
input digest, surface-policy digest, production receipt, and remaining unknowns.

A downstream connector or adapter consumes successful Hands receipts from the current proven units and may not
edit their producing YAML, runners, snapshots, locks, or result schemas. Any genuinely shared-path change
invalidates the affected baseline and requires that exact production unit to be re-earned before release.

The Jobs-to-intake critical path remains serial until one fresh end-to-end receipt chain passes. Afterward,
only lanes with separate mutable state may run concurrently; they share immutable digests and public schemas
only, never a display lease, CAREERS lock, browser profile, private root, database write transaction, receipt
root, or turn identity.

Stop immediately on a pairing mismatch, non-exact database identity, non-null new-row classification state,
application-state count change, private-value leak, scorer/ATS activation, or any outward action. No SFT is on
this plan's critical path unless a specific model trajectory defect remains after the deterministic contract
and authority gaps are removed.
