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

## Current observed baseline

- Grok's repeated non-actionable notification loop is fixed; it is not a remaining revenue-UI gate.
- LinkedIn `capture_mounted_job_search` is a production-qualified bounded read-only baseline at Hands
  `e3daab97f59f6cd8d8dfed24912dfbfa5f39bfee` and Presence
  `c42bd319b2fb8ef6b9774b6ef171293baf73e897`: transaction
  `eb06ff6c734f3ce99299374cbd8224e5da30ddbf4a157526f7eca3a0b92ab33e`, 25-card artifact
  `213fccb088ce0437f3d885e4b602c51cfa2cae2ebf6b082c3c6c572620e1a348`, and receipt
  `159f258eb4b7c45ed8fa42218024be83e35a65b1441d96f18583f4aeb862877f`.
- The fresh joined selected-detail leg deterministically used ordinal `1`, the first of six cards with
  `showing=true`: transaction `ff2d6e1a1fa8c84bdd25bc38720c1d1197504214480625b8a3ef3e7b2abba110`, one exact
  `click[0]`, two stable exact-identity cycles, artifact
  `c9205449d21a57517c9791e3ecd1deacf62af3ba03b86cb52a46aea4f585bd49`, and receipt
  `37bd41e250ad66e4a0875d8f9c8471731084434c66bf89bd1b7eb2078de9aa70`.
- Public `taey-apply` `253b882571673ae30d3beadda6f174439755a241` and the deployed Presence adapter consumed
  those exact four sources once: transaction `eab0e62a33ff343f4fd04040af74fb06447ad8bed8d01a97e3dedd5cc3af9960`, receipt
  `d73d96d18932ac45b9f87c1c138f7b4494ebd859923fd1c27fad9745a6645157`, jobs `2239 -> 2240`,
  applications `49 -> 49`, apply runs `593 -> 593`, and SQL `NULL` verdict, score, and applied-at fields.
- The current-main production chain at Hands `e3dfb52fc1b9501db0c850380168b47401fefb9f`, Presence
  `1f8ac7ab3f87a7c3a4ae945bd947cb0882c355b0`, and `taey-apply`
  `f96fa643ee3879e50f5d85991c1c0ecc86ab0444` independently repeated the complete boundary:
  - route restore transaction `c1f63c155838fa44f47be3a33c8e215705074609206a433e7b83994a947b185a` and receipt
    `32466f96bbee574d1afc621783124ea7a39a24d1b07c32d7bbcd4064ec8cb7d7`, with two stable observations;
  - 24-card mounted-search transaction `4d872f2a5104e37ee8b25ab282580291ded2fa6508e648171ee035d2efe6e323`, artifact
    `e2b9844aef2c47a3b764beb305859388a881dfec34af7d43803a671f19d731ec`, and receipt
    `e32a760b710331033688e7b4de825c7dde141d56522edede2c869b77bc09a4a2`;
  - one exact new-card selection transaction `cca4a871ac1608a30c7fafcc6c99d6e0d62cfee0e1e9286e008647551ff26ef6`, artifact
    `3733ea59e90c812177ae0f9298e53c2be825f0a3e750656deb48a90d02f4eae3`, and receipt
    `293b762ef00c47296c2f6e2f3fe6f65352a75a6f127f1a24eb3d660999983a7f`; and
  - intake transaction `e4e357fe777f344b8fad2d4b977fc4e7d7593273f4a1fc77549a80c301647166` and receipt
    `280e173548481fe48b2c4083b34aa19e0f88cb7f7817065862b28171256aaf02`, with jobs `2275 -> 2276`,
    applications `49 -> 49`, apply runs `593 -> 593`, one exact row, and SQL `NULL` verdict, score, and applied-at.
- Before that accepted intake, one preparation identity stopped at `private_input_invalid` because its draft used
  absolute rather than private-root-relative source references. Refusal receipt
  `9b15720edb226eb341bdf34812ab40f877ac80fb77ff23ce64bbe469862a6249` was preserved, the identity was not
  retried, and no UI or database action occurred. The corrected fresh identity passed the public four-source
  pairing validator before Taey was invoked.
- No comment, message, invitation, proposal, application fill, score, ATS action, or submit authority is
  released by the completed joined chain.

**Observed:** the mounted-search -> exact selected-detail -> unclassified intake acceptance chain is complete
from the exact public/deployed commits and immutable receipts above. **Unknown:** scorer one-shot safety, the
first current ATS provider, and whether the captured lead contains enough information to resolve one exact ATS
target.

## Implementation order

### 1. LinkedIn Jobs to unclassified application intake

The source mechanics:

- `select_and_capture_job` is a retained production baseline: one exact YAML-owned `click`, private target/title/company
  and selected detail stable for two fresh observations, one selected-detail write, unchanged content, CAREERS
  lock released, then stop.
- `capture_mounted_job_search` is now a retained production baseline. It captures only the cards already mounted
  on one authorized search-results page; it does not enter search terms, change filters, scroll, open, save,
  dismiss, or apply.
- The selected record is an application lead: it contains the private search reference, selected source
  URL/current job identity, exact detail heading, and description. Apply-channel facts are not part of the
  qualified record and must not be inferred.

The completed natural unit is the Presence intake adapter:

1. Expose one empty-input or otherwise opaque Taey-facing call; Taey supplies no paths, job values, IDs,
   policy, or database arguments.
2. Bind the seat/correlation identity to one frozen private transaction containing the exact Hands search
   artifact/receipt, selected artifact/receipt, and card digest.
3. Invoke exact public `taey-apply` commit `253b882571673ae30d3beadda6f174439755a241` once.
4. Require one exact jobs row whose canonical URL, title, company, location, and description match the paired
   capture; a non-identical collision, duplicate identity, digest mismatch, unsafe path, or indeterminate write
   is terminal.
5. Require a new row to retain SQL `NULL` for `verdict`, `score`, and `applied_at`; `applications` and
   `apply_runs` counts remain unchanged. A distinct transaction referencing identical evidence may return
   `already_present` with zero writes.
6. Return only the compact connector/Presence receipt and close the turn. Do not invoke a scorer, ATS, or
   another UI action.

The fresh joined-chain acceptance proof from exact public/deployed commits is now complete:

- mounted search captured 24 cards with stable pre/post evidence and zero residual turn/lease;
- deterministic ordinal `1` selection executed one exact YAML-owned click, stabilized exact title/company identity twice,
  captured one unchanged detail record, and released the lock; and
- the separate intake transaction joined all four Hands source hashes, inserted exactly one unclassified row,
  preserved applications and apply-runs counts, and produced no outward effect.

Adapter work must not change the LinkedIn YAML, runners, snapshot traversal, CAREERS lock, private
record shapes, or public result shapes. If the lead later cannot resolve one exact ATS target, add only the
missing read-only target projection under a new frozen contract and requalify it; do not widen search by
assumption.

### 2. LinkedIn engagement

Keep the six historical leaves independent: comment, own-post engager capture, messaging, invitation
acceptance, connection invitation, and Jobs.

- Jobs selected-detail capture is a retained production baseline; do not reopen it for intake-adapter work.
  Mounted-search is also a retained production baseline from the joined search-select-intake chain.
- Own-post engagement currently proves only the `no_new_signal` route/filter/restore result. Full qualification
  still requires one real `captured` write-once receipt followed by a fresh `already_known` receipt; lack of a
  live signal is not a reason to change the map.
- The engagement transaction requires an exact LinkedIn Jobs search-results start surface and a matching frozen
  return URL. A display left on the selected-detail surface by the joined Jobs chain is the wrong start surface;
  do not launch engagement there or repurpose that display by assumption. Use a separately preflighted display
  already on the required surface, or qualify an explicit return transition first.
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
  no current action. The public mechanical candidate is now Greenhouse-only and observe-only; its specs,
  primitive bindings, stop conditions, and canary procedure are in `ATS_PROVIDER_READ_ONLY_RUNBOOK.md`.
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

A downstream connector or adapter consumes qualified Hands receipts and may not edit their producing YAML,
runners, snapshots, locks, or result schemas. Any genuinely shared-path change invalidates the affected
baseline and requires that exact production unit to be re-earned before release.

The Jobs-to-intake critical path passed one fresh end-to-end receipt chain. Subsequent lanes may run concurrently
only when they have separate mutable state; they share immutable digests and public schemas only, never a display
lease, CAREERS lock, browser profile, private root, database write transaction, receipt root, or turn identity.

Stop immediately on a pairing mismatch, non-exact database identity, non-null new-row classification state,
application-state count change, private-value leak, scorer/ATS activation, or any outward action. No SFT is on
this plan's critical path unless a specific model trajectory defect remains after the deterministic contract
and authority gaps are removed.
