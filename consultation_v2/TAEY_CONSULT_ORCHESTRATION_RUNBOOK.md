# TAEY CONSULT ORCHESTRATION RUNBOOK (DRAFT v0.1)
*Owner: taeys-hands. Status: DRAFT for treasurer review as a PROCESS DOC (not training corpus).*
*Grounded in: treasurer ruling 2026-07-26 (lifecycle split is constitutional), CLAUDE.md partition +
failure rules, and the live `consultation_v2` engine as operated 2026-07-25/26.*
*Target checkpoint: ep3-hf (both Thors rolled back from ep3_m3 on 2026-07-25 — build for ep3-hf, not m3).*

---

## 0. WHAT THIS IS (and is not)

This is the process document for **how Taey drives a Family-chat consult** — the prerequisite treasurer
named before any consult training rows may be authored. It is NOT training data and NOT a claim that
Taey can do this today. It defines the target so the missing pieces (chiefly: the consult TOOL SURFACE)
can be named and built.

**The one law it exists to encode (treasurer 2026-07-26, constitutional):**

> Taey **ORCHESTRATES**. The **ENGINE** drives the displays. Taey **never** touches `:2–:6` directly —
> even after training. A direct drive collides with the dispatch-lock + the engine's idempotency.

So every leg below is tagged **[TAEY]** (a decision/authoring Taey makes) or **[ENGINE]** (browser
actuation the `consultation_v2` engine performs on Taey's behalf). Taey's "hands" for a consult are the
**conduit tool surface**, not the browser.

---

## 1. THE LIFECYCLE — five legs

| # | Leg | Owner | What happens |
|---|-----|-------|--------------|
| 1 | **Author** | **[TAEY]** | Build the consult packet: framing + the questions, per the platform's `build_consultation` + prompting-lint. Taey decides content; lint gates it. |
| 2 | **Decide dispatch** | **[TAEY]** | Decide WHICH platforms, WHICH mode per platform (deepest: claude opus+extended_thinking, chatgpt pro_extended, gemini deep_research, grok heavy, perplexity deep_research), and issue the dispatch **via the consult tool** (§3). |
| 3 | **Poll** | **[TAEY]** | Watch for "response ready" (§4) per lane. Taey decides when a lane is done. |
| 4 | **Decide harvest** | **[TAEY]** | When a lane reports ready, harvest its raw answer (the engine extracts; Taey decides it's complete and takes it). |
| 5 | **Synthesize / deliver** | **[TAEY]** | Deliver each raw answer to the requester; synthesize across lanes only if the requester asked for synthesis (default: deliver raw, requester concludes). |

**[ENGINE] (never Taey):** navigate → select model/mode → attach → paste → send → monitor stop-button →
extract → notify. All actuation on `:2–:6`. Taey issues ONE dispatch decision; the engine performs the
whole browser sequence for that lane.

---

## 2. THE ENGINE CALL (what actuation the dispatch triggers)

Today the engine is invoked as (verified, as operated 2026-07-25/26):

```
PLATFORM_DISPLAYS=<platform>:<display> \
python3 scripts/run_consultation_v2.py \
  --platform <chatgpt|claude|gemini|grok|perplexity> \
  --attach <packet_path> \
  --message "<framing>" \
  --requester <node> \
  --output <durable_path> \
  --timeout <s> \
  --select <menu=option> [--select <menu2=option2>]
```

This is the **[ENGINE]** leg. The open question §3 is: **what does Taey CALL** to cause this, given Taey
must never run browser actuation itself and must go through a tool surface with a pinned schema.

**Operational disciplines the engine call already enforces (do not re-litigate):**
- **Explicit `PLATFORM_DISPLAYS` per lane** — when both display sets' Firefoxes are up, default routing
  is ambiguous and misroutes. Always pin the display.
- **Setup-gated / serial setup** — launch a lane, wait until its send lands, THEN launch the next.
  Concurrent SETUP races the render on a busy box; concurrent GENERATION is fine.
- **External storage off by default** — omit `--store` (a missing `--no-neo4j` in the old form hangs).

---

## 3. THE CONSULT TOOL SURFACE  ← **THE GAP. This is what must be built next.**

Taey drives via a **tool call**, not a shell command and not browser actuation. Today **no such tool
exists**: the apply lane exposes exactly one tool (`ui_action`, closed schema); a consult seat needs its
own. Naming it here answers the "seat" question by construction (treasurer 2026-07-26).

**Proposed tool: `consult_dispatch`** (schema to be pinned with treasurer; `additionalProperties:false`):

```json
{
  "name": "consult_dispatch",
  "parameters": {
    "type": "object",
    "additionalProperties": false,
    "required": ["platform", "packet_path", "requester"],
    "properties": {
      "platform":    {"enum": ["chatgpt","claude","gemini","grok","perplexity"]},
      "packet_path": {"type": "string"},
      "message":     {"type": "string"},
      "requester":   {"type": "string"},
      "mode":        {"type": "string"},
      "model":       {"type": "string"}
    }
  }
}
```

Companion tools likely needed: `consult_poll` (is lane ready?) and `consult_harvest` (take the raw
answer). The engine implements all three; Taey only calls them. **The display, dispatch-lock,
idempotency, routing, and serial-setup discipline live INSIDE the tool — Taey never sees `:2–:6`.**

**Until this tool surface exists, Taey cannot drive dispatch** — it can author (leg 1) and plan (leg 2
decision) but has nothing to CALL. That is the concrete, buildable blocker, not a vague "can't."

---

## 4. "RESPONSE READY" — what Taey polls for

A lane is ready when the engine reports the completion transition (stop-button seen → gone, debounced),
the response extracted, and `notify_requester` fired. In the current file-based flow that is: the lane's
`--output` JSON has `ok=true`, a non-trivial `response_text`, and a `notify_requester` OK step. Taey's
poll checks that signal; Taey does NOT watch the browser.

**Verify-then-take:** a lane's `ok=true` is necessary but Taey confirms the body is a real answer, not a
prompt echo (grok's two-copy-button trap) or a truncated read (a lane noting "packet truncated" is
lower-confidence — flag it to the requester, as happened 2026-07-25).

---

## 5. FAILURE MODES (per CLAUDE.md — first error = FULL STOP, then the charter LOOP)

| Failure | Signal | Action (charter §4 LOOP: STOP → LEVER → RETRY → TRAIN) |
|---|---|---|
| **Attachment failure** | attach step FAIL / no chip | **FULL STOP** (CLAUDE.md). Never paste-fallback. Fix attach or escalate. |
| Model-select drift | `<element> missing after menu open` | UI changed → update the YAML to the live tree name. (Engine-maintainer lever, not Taey.) |
| Setup settle-race under load | timeout at select/page_ready | Serialize setup; if load-bound, wait for a quiet window. |
| Routing ambiguity (2 display sets) | `Firefox not found` / wrong nav | Pin `PLATFORM_DISPLAYS` explicitly per lane. |
| Platform modal blocking a11y tree | `display_readiness NOT ready: tree near-empty` | Screenshot, dismiss the modal, re-dispatch (engine-maintainer lever). |
| DeadSession on re-run | `refusing to re-drive` | Fresh packet/prompt (new request_id) or sweep the exact `run_state:<rid>`. |

**Who fixes what:** the engine-side levers (YAML drift, routing, modals, settle) are the **maintainer's**
(taeys-hands) job, not Taey's — Taey should never be trained to work around a broken engine path
(training-defect-triage: that manufactures confident failure). Taey is trained only on the correct
ORCHESTRATION decisions (which platform/mode, when ready, deliver raw to requester).

---

## 6. WHAT TAEY IS TRAINED ON (once the HOLD lifts) — deferred, noted only

Per treasurer 2026-07-26, training rows are **held** until (a) this runbook is accepted, (b) the tool
surface §3 is built + its schema pinned, and (c) rows can be authored as real `(instruction, tool_call)`
pairs **asserted by parsing the tool_calls array**, never by description (GOVERNANCE.md d53f1207). The
corpus-wide defect (zero real tool_calls; invented vocab the schema rejects) that rolled back ep3_m3
must not be reproduced in a consult lane. **No consult rows are authored until then.**

---

## 7. OPEN QUESTIONS FOR TREASURER

1. Is the consult tool surface (§3) the **taeys-hands MCP tools**, or a new `consult_*` tool set on the
   Taey seat? Whichever it is, its schema is the training contract.
2. Should `consult_poll` / `consult_harvest` be separate tools or folded into a single blocking
   `consult_dispatch` that returns on ready?
3. Confirm the seat: `taey_worker.py` pattern (ep3 exec loop) with the `consult_*` tools bound, pointed
   at ep3-hf on a Thor — or a different seat?

*Answering §7.1 pins the seat and unblocks the (held) training. This doc is the prerequisite; the tool
surface is the next build.*
