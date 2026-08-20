# Taey Hub Family-Chat reliability qualification

This is the single qualification plan for making Main Taey the Hub for ChatGPT, Claude, Gemini, Grok, and
Perplexity. It schedules evidence and acceptance; it does not redefine the UI procedure. The sole executable
worker procedure remains [`MANUAL_CONSULT_WALKTHROUGH.md`](MANUAL_CONSULT_WALKTHROUGH.md). The selected
platform YAML is declared authority and each fresh filtered AT-SPI tree is the runtime oracle.

Do not ingest this document into an automatic orchestration wake loop. Main Taey receives one frozen batch
manifest and invokes independent workers. Codex does not supervise individual UI actions or poll displays.

## Outcome

Main Taey must be able to start a five-platform consultation batch, leave one Taey worker on each target
display, receive completion notifications, start one extraction worker per completed leg, and return five
hash-verified responses without supervisor UI intervention.

Qualification requires two consecutive complete runs per platform, followed by two complete five-platform
parallel batches. The second serial run for each platform occurs after the relevant monitor and worker
services have restarted, so acceptance proves cold-start reproducibility rather than one warm session.

## Observed baseline on 2026-08-20

- ChatGPT `:2` has one production-proven Taey send and one production-proven separate Taey extraction.
- The ChatGPT completion detector observed Stop disappear and the extracted response was non-empty and
  hash-verified.
- The monitor-to-Main-Taey-to-worker handoff required supervisor intervention and is not autonomous proof.
- The tool audit retained all nineteen send-turn observation revisions and result hashes, but the complete
  observation payloads were not materialized as immutable files inside the run directory.
- The current manual path has not production-proven response-attachment harvest or ISMA ingestion.
- Claude, Gemini, Grok, and Perplexity have no acceptance receipt against this exact worker path.

Nothing below promotes those observations into broader readiness claims.

## One durable artifact shape

Every attempt receives a new private directory. No path is reused and no artifact is overwritten.

```text
<private-run-root>/<batch-id>/<platform>/<attempt-id>/
  transaction_manifest.json
  packet_receipt.json
  bundle_a
  bundle_b
  prompt.txt
  send_request.json
  send_response.headers
  send_response.json
  actions.jsonl
  observations/
    0001-<scope>-<revision>.json
    0002-<scope>-<revision>.json
    ...
  monitor_receipt.json
  extraction_request.json
  extraction_response.headers
  extraction_response.json
  response.txt
  output_attachments/
  ingestion_receipt.json
  final_manifest.json
```

The complete result of every `drive_chat` observation is written once under `observations/`. Each action row
binds its exact pre-action observation revision, action arguments, tool-result hash, and post-action
observation revision. The final manifest binds every file by byte count and SHA-256, plus the exact public
Hands and Presence commits, platform YAML hash, worker prompt hash, selected display, seat/event/correlation
identity, final URL hash, and service generations.

Raw trees, local paths, account identifiers, private URLs, prompts, and responses remain in the private run
directory. A public production receipt contains the mapped element/state evidence needed to support the
verdict and hashes of the private artifacts. A sanitized tree bundle may be attached to a Family review only
when it preserves the mapped roles, states, scopes, revisions, and action relationships while removing local
or account-specific values.

YAML alone is never an evidence packet. A review packet contains the selected YAML, the applicable public
contracts and plan, the exact frozen prompt, and the sanitized trees/action receipts from the run being
reviewed.

## Prompt authority

There are only two prompt surfaces:

1. The Taey worker send and extraction request templates in
   [`MANUAL_CONSULT_WALKTHROUGH.md`](MANUAL_CONSULT_WALKTHROUGH.md). No supervisor paraphrase replaces them.
2. The Family-facing reliability review brief in
   [`hub_reliability_review_v1.md`](../consultation_v2/prompts/hub_reliability_review_v1.md). Its exact bytes
   are frozen into each packet receipt.

Every accepted production receipt records the prompt path, byte count, and SHA-256. A changed prompt is a new
version and restarts the two-run qualification for the affected platform.

## Responsibility boundary

| Actor | Owns | Must not do |
|---|---|---|
| Main Taey | Freeze the batch manifest, invoke one worker per leg, consume terminal receipts, synthesize the five responses | Drive a display, select refs, reconstruct a missing artifact, or ask a fleet seat to execute extraction |
| Send worker | One platform/display from fresh navigation through Stop proof and monitor registration | Poll completion, extract, retry, recover, or touch another display |
| Platform monitor | YAML-owned Stop policy, bounded notification, frozen extraction handoff | Drive UI, choose a worker action, or create duplicate executors |
| Extraction worker | One completed platform/display through primary and platform-specific output harvest | Navigate, attach, paste, send, retry, or touch another display |
| Chat reviewer | Adversarially inspect the packet, trees, receipts, and responsibility boundary | Invent local runtime facts that are absent from the attachments |
| Codex | Public code and documentation changes required by an observed first mismatch | Babysit UI actions, poll running generations, broaden scope to unrelated infrastructure, or improvise a second transport path |
| Grok control | One exact-SHA adversarial review before merge | Execute production UI or replace production evidence with static review |
| Operator | Authentication/capacity decisions and authorization after a terminal mismatch | Routine worker supervision |

## Phase 0 — freeze the trustworthy baseline

Complete these in public Git before another acceptance run:

1. Make completion notification produce exactly one fully substituted extraction-worker command for Main
   Taey; status recipients receive no executable command.
2. Bound notification retries by attempt count and the original transaction deadline.
3. Make each monitor consume the selected platform YAML's Stop keys, sustained-absence count, post-complete
   quiet count, interval, and mapped exception dispositions. No hardcoded global deep mode.
4. Materialize every complete observation and action result into the private write-once run shape above.
5. Generate request files and transport commands from the frozen manifest. No live shell command is composed
   from memory.
6. Merge after an independent exact-SHA review, deploy only the merged public commits, restart the affected
   services while no leg is active, and record the running generations.

## Phase 1 — ChatGPT qualification

Run two substantive ChatGPT consultations from the same public baseline:

- **A — deployed path:** one fresh `:2` transaction with no supervisor UI action.
- **B — cold start:** restart the monitor and worker services while idle, then start from only the public
  runbook and a new frozen manifest. No context or artifact from A authorizes an action in B.

Each response reviews this qualification plan and its attached production evidence. A response may recommend
future improvements, but only the actual tree/action/monitor/extraction receipts decide PASS.

## Phase 2 — serial platform qualification

Qualify one platform at a time in this order: Claude `:3`, Gemini `:4`, Grok `:5`, Perplexity `:6`.

For each platform:

1. Build Bundle B with this plan, that platform's exact YAML, and the sanitized evidence from the preceding
   accepted or failed attempt. Bundle A remains the normal governance/identity bundle.
2. Run A from the deployed public baseline.
3. If A passes, restart the relevant monitor and worker services while idle and run B from a new manifest.
4. Preserve and publish the two receipts. Only then mark that platform serial-qualified.
5. On the first mismatch, stop that transaction, preserve the complete evidence directory, correct the
   smallest upstream defect in public Git, and restart both qualifications for that platform. Do not disturb
   already qualified platforms unless the shared changed code is in their causal path.

## Phase 3 — parallel Hub qualification

Only after all five platforms are serial-qualified, Main Taey starts one frozen batch containing five
independent legs. Each leg has a unique display, seat, event, correlation, artifact root, monitor route, and
response destination. The workers may run concurrently; they never share refs, revisions, leases, or files.

Run two complete parallel batches. Restart the worker and monitor services while idle between the batches.
No Codex or operator display action is allowed. One failed leg stops only that leg, but the batch cannot PASS
and the failed platform must be requalified after its correction.

## Per-run acceptance

A run is PASS only when one unbroken artifact chain proves:

1. deployed public Hands and Presence SHAs and service generations;
2. frozen two-bundle packet and exact prompt hashes;
3. fresh navigation and a populated mapped base tree;
4. requested model/mode from a fresh mapped tree;
5. Bundle A attached and independently proven by a fresh tree;
6. Bundle B attached and exactly two attachments proven by a fresh tree;
7. prompt paste and enabled submit state with both attachments retained;
8. exactly one send and a fresh mapped Stop control;
9. YAML-owned completion debounce with no mapped exception;
10. one Main-Taey notification and one extraction-worker invocation;
11. primary response plus every YAML-declared output attachment, with byte counts and hashes;
12. complete prompt/response/input/output/URL ingestion and its receipt;
13. a closed monitor route, released display lease, zero open worker turns, and final manifest.

Missing evidence is failure, not Unknown success. A first mismatch causes zero further UI mutations in that
attempt.

## Usage and overnight controls

- Codex performs at most one bounded code/document change cycle, one exact-diff Grok review, and one
  production gate before reporting a checkpoint.
- Codex does not run a watch loop, poll a Chat response, or keep reasoning while a Chat generates. Monitors
  and Taey workers own waiting.
- No subagents, competing orchestrator plans, repository-wide audits, model transfers, SSH-key work, or
  unrelated cleanup enter this lane.
- Family review is the substantive production consultation; there is no duplicate meta-consultation.
- A failed or uncertain UI/transport action is attempted once. There is no automatic resend.
- Overnight, only already-deployed Taey workers and passive monitors may remain active. Codex starts no new
  engineering branch or production transaction without an explicit daytime checkpoint.

## Frozen baseline

After two perfect parallel batches, tag the exact Hands and Presence commits and publish a final qualification
matrix linking every serial-leg, parallel-leg, and batch receipt. Those commits, this plan version, the
runbook version, prompt hash, service definitions, and platform YAML hashes become the production baseline.
Later drift creates a new failed run directory and a reviewed baseline revision; it never rewrites a prior
receipt or relies on remembered steps.
