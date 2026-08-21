# Grok monitor-direct production receipt — 2026-08-21

## Verdict

**PASS for one complete, valuable Grok `manual-chat-ui` transaction.** A Taey send worker selected Heavy,
attached exactly two frozen files, pasted the 714-character prompt once, sent once, proved the mapped Stop
control, and registered the completion route. The restarted per-display monitor required the existing
two-cycle Stop-absent proof, directly launched the frozen extraction worker, persisted a substantive
5,452-byte response, notified Main Taey with no failure, removed the route, and released the display lease.

No supervisor drove the display. Main Taey did not poll, launch extraction, or issue a UI command. This is
the first production proof of the monitor-direct boundary deployed by PR 109.

## Deployed public baseline

| Surface | Exact production commit | Relevant change |
|---|---|---|
| `palios-taey/taeys-hands` | `d4953eea473976fa4f0017171b2f784f9333fb28` | PR 109: monitor-direct extraction, persisted terminal outcome, result-only Main Taey notification, no redundant post-monitor Stop recheck |

The canonical checkout was clean and `HEAD == refs/heads/main == origin/main`. All five monitor services were
restarted idle on the deployed file at `13:19:04 UTC`; Grok `:5` ran PID `3024680`. Before restart there
were zero active completion routes, display leases, or launcher processes.

## Packet provenance

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Bundle A: full `FAMILY_KERNEL.md` + `IDENTITY_LOGOS.md` + `SPOTLIGHT_STANDARD_FOR_INTEGRITY.md` | 44,927 | `2ce621adb56cadb9dc0979aa5e52689c24d2e8169a687d9744ab67b4d2039a39` |
| Bundle B: deployed facts, failure receipt, constraints, and eight-part parallel-Hub deliverable | 7,655 | `2818c3ae397fc3987eb11a255f5374326041ea9164ed9545625688b1aa4a740d` |
| Prompt | 714 | `00d533aedda5170409bc6259be222d50f3ed28c2b3cdb323e804bfa7fc3361ef` |
| Packet receipt | — | `a14216347e76f29c36497bd9270a81298224e9b1f2a1d68390efb3b4eefb1d4a` |

The question was value-added: define the smallest existing-component manifest/runner/result contract for
five concurrent Family-Chat lanes. The exact batch schema, concurrency boundary, and terminal aggregation
rule were not already frozen or production-proven.

## Transaction identity

| Field | Value |
|---|---|
| platform / display | `grok` / `:5` |
| send seat | `infra-codex-grok-monitor-direct-value-pass1b-20260821` |
| send event / correlation | `send-861762d0f312b77f7c1b8b5a` / `send-861762d0f312b77f7c1b8b5a-1` |
| monitor | `infra-codex-grok-monitor-direct-value-pass1b-20260821-5-cf500d7757564c069db28faeabf8d4a8` |
| thread URL SHA-256 | `90df4b822f4d4c7348235651a1b9839bc5be052e381fb0c5f8ea9176111d8e0b` |
| send request SHA-256 | `4853a1c6e30af14e7253c93fcbb1e345d8fd86034301bb89c4e0cdc178ca53fe` |
| send headers SHA-256 | `acec5518fe3393db6ddc3ece25d5b71f1dd99f993944a99dcd3eab2b8fbaa63c` |
| send response JSON SHA-256 | `9e93ea0f4758ae1cf7e3faa336468af25b806684550e0e3c544523121db70afc` |

The private thread URL is intentionally omitted. Its hash is recorded above.

## Unbroken UI and monitor chain

1. Taey navigated once to the fresh Grok root and proved a populated mapped base tree.
2. Taey operated the model selector, observed the declared application-root menu, clicked the singleton
   `Heavy Team of Experts · Grok 4.5`, and returned to the mapped base tree.
3. Bundle A was selected through the native chooser. The browser tree then proved one attachment chip and
   one remove control.
4. For Bundle B, Taey focused Attach, independently observed the focused state, pressed Space, mapped the
   singleton `Upload a file`, and used the chooser. The browser tree then proved exactly two attachment
   chips and two remove controls. The focus highlight was the expected midpoint of the frozen
   `focus -> observe -> Space` sequence, not a failed click.
5. Taey pasted the frozen prompt from disk once. The tool reported `pasted_chars=714`; the next observation
   retained exactly two attachments and mapped one enabled Submit control.
6. Taey clicked Submit exactly once. One post-send observation proved a new conversation URL, one mapped
   `stop_button` named `Stop model response`, and the monitor registration above. The send worker then made
   no further UI calls.
7. The Grok monitor activated at `13:41:40 UTC`. It retained the unchanged three-second poll and two-cycle
   Stop-absent detector.
8. The monitor prepared the extraction request at `13:42:54 UTC` and directly invoked the existing
   `run_manual_chat_worker.py extract` launcher. There was no Main-Taey command relay.
9. The extraction worker observed the conversation URL, scrolled to the bottom, mapped exactly one final
   `copy_button` named `Copy response` through YAML `last_by_y`, clicked once, and wrote `response.txt` at
   `13:45:23 UTC`.
10. The extraction worker finalized at `13:46:43 UTC`; the monitor logged `failures=none` and
    `route_removed=True` at the same second. The seat reported zero open turns and `taey:plan_active::5` was
    absent.

## Extraction and answer proof

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| extraction request JSON | 1,501 | `573cef260b90c2e408558d09fbb603034014c4ff9acc4aa0f5de20bfe9f643b3` |
| extraction headers | 395 | `2427118f7ee1038f63de3804bbaca9950b41af5094f850d5a8248dabd238f844` |
| extraction worker JSON | 1,482 | `d2b52285e65188f00786171c913a205e318883a271ee17958bce8b41d702dfd7` |
| extracted Grok response | 5,452 | `49845540a8156215173fc792749b2d28febbf4b778008dd0627f8be4b9886bb6` |

The response is substantive and answers all eight requested parts. Its decision is that the deployed
boundary is sufficient for parallel Hub qualification with zero new runtime components: freeze exactly five
existing launcher legs with unique identities and paths, let the five existing monitors extract, collect one
uniform terminal result per leg, and mark the batch terminal only when all five legs are terminal. The only
remaining unknown it identifies is measured host contention under five simultaneous browser/extraction
loads.

## Latency register

Correctness passed; speed was not an acceptance gate for this run.

| Boundary | Observation |
|---|---|
| frozen send request created | `13:23:35 UTC` |
| monitor route activated | `13:41:40 UTC` |
| send worker terminal receipt | `13:45:39 UTC` |
| monitor-created extraction request | `13:42:54 UTC` |
| clipboard response persisted | `13:45:23 UTC` |
| extraction and route cleanup terminal | `13:46:43 UTC` |

The send worker's receipt generation overlapped monitor/extraction work after Stop registration, which proves
the external ownership boundary is real. The observed latency is primarily the local model's many
observe/action rounds and terminal-receipt generation. It is a later CTQ: measure per-round latency after
serial and parallel correctness qualification, then move only proven deterministic compound actions below
the model boundary without changing YAML authority or first-error containment.

## Refused preflight, before UI

The first launcher invocation was refused because its artifact root had been pre-created. The canonical
launcher requires a nonexistent write-once send root. It exited before contacting Taey or touching `:5`;
the directory was empty, the display lease was absent, and the completion route list was empty. The accepted
transaction used a new seat and a new, initially nonexistent root. No directory was deleted or reused.

## Truth register

- **Observed:** every UI, monitor, extraction, artifact, hash, notification, route-cleanup, turn, and lease
  fact stated above is present in the worker receipts, filesystem metadata, Redis state, or system journal.
  The operator independently observed Bundle A attached and the second Attach control focused during the
  slow turn.
- **Inferred:** most latency is local-model deliberation between already-specified primitives; exact
  per-tool-round attribution still requires the audit timestamps.
- **Unknown:** five-lane simultaneous resource contention and the safe minimum latency after correctness
  qualification.

This is Grok monitor-direct qualification pass 1. A second useful Grok pass is still required before Grok is
serial-qualified under this shared production baseline.
