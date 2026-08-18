# 100_TIMES.md — current manual Family-Chat rules

This file is the short operating checklist. The authority order is
[`consultation_v2/README.md`](consultation_v2/README.md). The manual lifecycle is
[`CONSULTATION_CONTRACT.md`](CONSULTATION_CONTRACT.md), and direct UI interaction is governed by
[`docs/UI_INTERACTION_AUTHORITY.md`](docs/UI_INTERACTION_AUTHORITY.md). If a historical note conflicts with
those documents, the current authorities win.

## 1. The YAML is the source of truth; the filtered AT-SPI tree is the oracle

- Everything needed to operate the current UI is represented in the tree. There are zero pixel, OCR,
  coordinate, screenshot-as-truth, remembered-shortcut, or guessed-control exceptions.
- Browser chrome is excluded except the address bar. The complete sidebar/chat-history block and dynamic
  non-actionable text such as greetings are excluded. The current document, actionable controls, and the
  currently opened menu, submenu, or dialog remain visible.
- There is no `name_contains`, substring, regex, fuzzy, wildcard, or list-of-guesses control matching.
  Every actionable element is an exact YAML-owned name, role, scope, state, and disambiguator.
- If a required element is absent, the observation is stale, the scope/filter/environment is wrong, or the
  platform changed. Correct that root cause or update the YAML from a fresh tree. Never add a fallback.

## 2. One platform owns one complete map

- Each Chat platform owns one YAML, one thin driver, and one passive monitor.
- The YAML owns element identities, structural pruning, menu attachment points, states, action grammar,
  routing hints, and settle intervals. Drivers contain no platform UI strings or hidden sequences.
- Every base state, menu, submenu, dialog, generating state, completed state, exception state, and extraction
  state is reconciled against a current production tree before it is claimed current.

## 3. Taey operates manually, one action at a time

- Read a fresh canonical tree, choose exactly one YAML-authorized action, execute it once, then read a fresh
  independent tree and validate the declared postcondition before choosing another action.
- AT-SPI can refresh late. One YAML-owned settle followed by one fresh read is allowed. That is observation,
  not an action retry.
- A failed action is repeated zero times. Do not spam a UI with retries. Preserve the tree and transaction
  state, stop that UI transaction, and perform root-cause recovery engineering.

## 4. The manual lifecycle is fixed

1. Reconcile the filtered base tree.
2. Navigate the existing tab to a fresh session and capture the resulting URL.
3. Select and validate model, mode, and tool through their actual YAML-mapped dropdowns.
4. Attach and validate exactly two files.
5. Focus the composer, paste the brief prompt, and validate it.
6. Send once, preferably with Enter while the composer is focused, and prove submission by Stop appearing.
7. Monitor until Stop is absent in two consecutive fresh trees separated by the YAML-owned interval, with no
   mapped exception state.
8. Extract, harvest response attachments, persist the complete receipt, and ingest the session to ISMA.

Each file-dialog operation—focus, location entry, file selection, and dialog submission—is its own action and
gets its own fresh-tree validation. Gemini Deep Research includes its mapped research-plan confirmation as a
separate action.

## 5. A consultation has exactly two input attachments

- Bundle A contains the full `FAMILY_KERNEL`, the destination's full identity, and the full Spotlight doctrine.
- Bundle B contains the complete request, background, evidence, deliverable, acceptance criteria, and
  provenance.
- The on-screen prompt is brief: orient the reviewer and state the deliverable. It does not replace either
  attachment. Missing or partial mandatory context stops packet construction.

## 6. Stop is the lifecycle signal

- Stop appearing proves the send landed and generation began. For a new chat, capture the new URL as part of
  the same validation.
- Stop absent once is only a candidate completion. Stop absent twice in fresh trees, separated by the
  YAML-owned completion interval and with no mapped exception, proves completion.
- If Stop never appears, do not assume a fast answer and do not extract.

## 7. Extraction and ingestion are part of the same transaction

- For an ordinary response, scroll all the way to the bottom, activate the exact mapped Copy control, and
  validate that the captured response is the assistant's final turn rather than the prompt.
- Platform-specific report and artifact extraction is YAML/driver-owned and must harvest every response
  attachment.
- Persist prompt, response, both input attachments, all output attachments, final URL, action/tree receipts,
  and provenance. The transaction is not complete until the session is ingested to ISMA and receipted.

## 8. First error stops the UI transaction, not the engineering work

- Preserve the exact fresh tree, state, URL, intended YAML key, and observed mismatch.
- Diagnose with the standing premise that the element exists in the tree when scope, filtering, environment,
  and YAML are correct.
- Fix the upstream projection, mapping, or primitive. Do not create another observer, driver, matcher, or
  fallback path.

## 9. Production is the oracle

- Validate incrementally on the real production display as soon as a change can be observed safely.
- Read-only tree and menu audits come before a send.
- Sent validation uses a substantive architecture audit or the original failed request. Do not use synthetic
  or short-response canaries; they do not exercise the real Stop/monitor/extract lifecycle.

## 10. Track everything in Git

- Contracts, YAML changes, runtime changes, production receipts, and corrections are committed and reviewed.
- The live checkout is not an experimentation branch. Work in an isolated worktree, merge through a reviewed
  PR, deploy from the merged commit, and record the production observation against that commit.
