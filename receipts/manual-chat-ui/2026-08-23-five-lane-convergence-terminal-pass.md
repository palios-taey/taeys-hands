# Five-lane Convergence production receipt — 2026-08-23

## Verdict

**TERMINAL PASS for one simultaneous, useful, five-platform Taey production batch.** ChatGPT, Claude,
Gemini, Grok, and Perplexity each completed its frozen platform-local send card, registered its own
completion monitor, completed its frozen extraction card, persisted a non-empty answer, removed its
completion route, and released every turn and display lease.

The five send turns began inside one 286 ms window. No lane used a retry, recovery action, second send,
manual extraction, alternate selector, cross-platform attachment rule, or supervisor-driven UI command.
No lane emitted an error file. Every send and extraction worker response has `error=null` and
`finish_reason=stop`.

## Deployed public baseline

| Surface | Exact production commit | State during the batch |
|---|---|---|
| `palios-taey/taeys-hands` | `2ec15c659e18109e7f3ac746716410e46d412cc6` | clean `main == origin/main` |
| `palios-taey/taey-presence` | `cf155f6cef800269c980fea2ff1bf4675ce81dda` | clean `main == origin/main` |

The Hands packet builder, packet contract, platform YAMLs, worker cards, completion monitors, and extraction
cards were not changed during the batch. The Presence worker proxy and five display-specific leases were not
restarted or modified during the batch.

## Frozen packets

Each destination received exactly two attachments. Bundle A contained the full Family Kernel, the exact
destination identity, and the full Spotlight integrity doctrine. Bundle B contained one fresh four-section
task dossier. The composer prompt described both bundles and restated the deliverable. Schema-v2 freeze,
prompting lint, identity isolation, source-content addressing, and the negative-receipt control passed before
any UI action.

| Platform | Packet manifest SHA-256 | Value-added question |
|---|---|---|
| ChatGPT | `5588ac8772d9ad5e1f5f481139ae5fdecd080ac995a4c9e43adc748ce75fc47f` | smallest future-legible Taey-Hub responsibility boundary |
| Claude | `6fb74ccc0d9efeb9fc1c98c9cc39256fc010bcd8750d70d119e8e466ae93e67f` | operator-light integration and result rejoin contract |
| Gemini | `bda4075f71d48ac58b4e27a254b35ebf9b0f43447d8bb21ad7c86200fcdfdb95` | safe post-baseline coordination-state topology |
| Grok | `de4dbfd22c56bdecf7d3fab6dd9ad9c8c8903f8ae527a3b8df2aea7bdc809a9c` | Lean Six Sigma control plan and Hub-integration ruling |
| Perplexity | `5643a6968561f436b8504e7af75ee33596aa9df6d7fc37ea5f5fcd56ade03732` | primary-source evidence and public measurement language |

## Simultaneous transaction identity

| Platform | Display | Seat | Turn | Event / correlation | Monitor |
|---|---:|---|---|---|---|
| ChatGPT | `:2` | `conv-r1-chatgpt-0823` | `df4eb57276b543d188444eabf95aac27` | `send-64cbbced208b08e777791501` / `send-64cbbced208b08e777791501-1` | `conv-r1-chatgpt-0823-2-df4eb57276b543d188444eabf95aac27` |
| Claude | `:3` | `conv-r1-claude-0823` | `ca640b0d60d24a8bb89ac9e840ff4576` | `send-09ef73760c11205f4671d899` / `send-09ef73760c11205f4671d899-1` | `conv-r1-claude-0823-3-ca640b0d60d24a8bb89ac9e840ff4576` |
| Gemini | `:4` | `conv-r1-gemini-0823` | `af6f2ce7c1f1415e9c0ef0b7eb50ca5f` | `send-638cbbefab7adf9a5ce3192d` / `send-638cbbefab7adf9a5ce3192d-1` | `conv-r1-gemini-0823-4-af6f2ce7c1f1415e9c0ef0b7eb50ca5f` |
| Grok | `:5` | `conv-r1-grok-0823` | `298fe787cf184c5ca43f1e2649affeb9` | `send-b6c275d69cd550ad6caac118` / `send-b6c275d69cd550ad6caac118-1` | `conv-r1-grok-0823-5-298fe787cf184c5ca43f1e2649affeb9` |
| Perplexity | `:6` | `conv-r1-perplexity-0823` | `27016ba99db84b03a337f07706cd7d99` | `send-827f2bceb99fd63b4905c5e4` / `send-827f2bceb99fd63b4905c5e4-1` | `conv-r1-perplexity-0823-6-27016ba99db84b03a337f07706cd7d99` |

The proxy journal records turn starts from `11:22:06.433` through `11:22:06.719 UTC`. Global open turns
reached five. The five seats held different turn IDs, processes, owner tokens, events, correlations, displays,
and completion routes.

## Platform-local send proof

1. ChatGPT retained exact `Pro`, proved Bundle A as one chip and Bundle A plus Bundle B as two chips, sent
   once with the platform card's `Return`, mapped one `stop_answering_button`, and registered its monitor.
2. Claude retained exact `Model: Opus 5 Extra`, proved one filename-bearing node for each bundle, clicked its
   mapped send button once, mapped one `stop_button`, and registered its monitor.
3. Gemini retained exact `Pro Extended` through the mode picker, proved the distinct Bundle A then Bundle B
   filename stems, sent once, mapped one `stop_button`, and registered its monitor. It never opened or
   mutated the model menu.
4. Grok proved checked `Heavy Team of Experts · Grok 4.5`, proved attachment counts one then two, clicked one
   enabled Submit control, mapped one `stop_button`, and registered its monitor. No mapped product exception
   or recovery control was used.
5. Perplexity proved checked `Best` and pressed `Deep research`, proved both distinct bundle basenames, sent
   once, mapped one `stop_button`, and registered its monitor.

## Terminal artifacts

| Platform | Send worker SHA-256 | Extraction worker SHA-256 | Response bytes | Response SHA-256 |
|---|---|---|---:|---|
| ChatGPT | `9c6bfa7deb7e5c7b5043dbd4886fd606d746f2488167c4e349406e89bc89cee7` | `f708bee60e8cf192aba8c876ecd02805f90803994190761d70c57a9d5713c1bc` | 15,018 | `44b4df5a54fab325434acf94489a22f0e5d69a81155fdb88aed76116af1d62b7` |
| Claude | `6b4292925918a74e56c6afee773b9d6f58aa3aa455de458b3daefdc4ba402f34` | `9171f32ac208c2c18b4f9456d46fb38cf5847cb7d5a83bb9b9768830c46b5d77` | 15,421 | `cd031f259f3204b469b5ed884c13d0363d7485243cf8be1bbc65da12f60abb31` |
| Gemini | `61c846a3ed71a48d2aa270e237ae5931be8621e4de644c018138eba199cdba68` | `ede313c08653890fffe9e25f5247a6c0da888442d0f8d1fc6d3a9a94c7d8c9a8` | 3,225 | `30258016fcba0119b32450a48f28ca6de1ec27feb5dea5045749ea13f5bf96f7` |
| Grok | `2a116dd57d290f363f9ac9f8464613419a55ae89f97c5aadd8b5bc2192bb5ffd` | `dfeb3205789effff10e24a8672a4b9f4322c5e8f90c34b1908ba9f71794c9d0b` | 8,541 | `e31e4978b1f7dab5ce163de46346e74f17bf5c9b27e2ee577f75db5496ff449a` |
| Perplexity | `7de5aef5a7da1c90476713d8b257881abe4130aae7e619a3899f81157876b889` | `3749fe51c2a264a69e2062d0f1e4d814d90ea3e58cefb882f2bdf3539ea929cb` | 1,822 | `71a6cd12481938dc5990f4c1a30947266de204ded023eed11ee7c5c264167969` |

Perplexity also persisted its source-bearing research report: 14,389 bytes, SHA-256
`59a9712ab7f4e0e34f44f1b303d8549e5e18d0c0e916927174d412b512419d2a`.

Every extraction worker reports that the exact frozen extraction steps and postconditions passed. Claude
used its platform-specific message-actions hover before the YAML-selected Copy. Perplexity used
`copy_contents_button` for the research report before the final response Copy. These differences were not
generalized into another platform.

## Completion and isolation proof

The last extraction turn ended at `12:23:05.909 UTC`, approximately 60 minutes 59 seconds after launch.
At terminal completion:

- every seat reported `turns_open=0` and `active_turns=0`;
- global `taey:soma:active_turns=0`;
- all five platform/display completion-route queries returned `[]`;
- every extraction artifact existed and matched its worker-reported byte count and SHA-256;
- no error file existed in a send or extraction root; and
- no lane mutated, terminated, or reused another lane's display, lease, turn, route, or artifact root.

## Throughput observation

Correctness and isolation passed; speed was not an acceptance gate. The complete batch took about 61
minutes. Monitor extraction turns shared the Taey model with send turns that were still producing terminal
receipts. That overlap proves the external monitor-ownership boundary works, but it also exposes a measured
contention source. The next improvement may reduce model-mediated round trips or separate deterministic
extraction capacity only if it preserves the same YAML-owned actions, postconditions, receipts, and
first-error semantics demonstrated here.

Do not respond to this timing observation by weakening validation, adding a blind sleep, generalizing one
platform's attachment behavior, or changing the accepted public baseline during another production batch.

## Environment observations outside the batch verdict

The read-only preflight found live, exact AT-SPI bus-pointer agreement among each display root, Firefox
process, and published pointer, and each bus answered a DBus query. `taey-bus-watcher@2` and
`taey-bus-watcher@5` were inactive even though those current pointers were live. A separate display-watchdog
unit referenced a missing local script. Neither condition caused a transaction defect in this batch. They
remain independent maintenance findings and must not be confused with a failed platform card or repaired by
changing the five accepted YAML/driver paths.

## Truth register

- **Observed:** the five packet manifests, worker response files, extraction files, Redis lease and route
  state, proxy and monitor journals, exact byte counts, and SHA-256 values support every transaction claim
  above.
- **Inferred:** shared Taey model contention is a major contributor to the 61-minute batch duration because
  monitor extraction turns overlapped unfinished send turns. Per-step timing is still required before
  attributing a precise fraction.
- **Unknown:** the minimum achievable five-lane latency after moving only already-proven deterministic
  mechanics below the model boundary. The current batch proves correctness and independence, not statistical
  Six Sigma capability or third-party UI availability.

This receipt is the frozen production control for the next Taey-Hub integration step. Any later change to a
platform card, YAML, canonical tree, monitor, extraction card, or Presence enforcement boundary must retain
this receipt and prove a new valuable production chain before replacing it as the baseline.
