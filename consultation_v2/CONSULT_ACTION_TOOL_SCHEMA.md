# consult_action — CLOSED tool schema + executor spec (DRAFT v0.1)
*Owner: taeys-hands (I own the consult_v2 primitives this binds to). For infra's seat-contract harness.*
*Grounded in: infra ruling 2026-07-26 (extract a seat contract, don't fork taey_worker; closed schema
+ observable postconditions), the consult_v2 engine, and the ui_action safety pattern it mirrors.*
*Target: ep3-hf. One leased tool, fail-closed — same safety shape as ui_action, different closed tool.*

---

## 0. THE CONTRACT (mirrors ui_action's safety, does not loosen it)

Taey emits **exactly one** `consult_action` tool call per turn. The seat executes it, verifies its
**postcondition**, and returns the observed result. Anything outside this tool = **fail-closed**
(same as taey_worker.py:298 for ui_action). No free-form shell, no act.py, no second tool. The
executor — NOT Taey — performs the AT-SPI actuation on :2–:6, so the constitutional partition holds
(Taey orchestrates by emitting the action; the engine drives the display).

**Why closed + enum'd (infra, tied to the m3 rollback):** the module-3 regression was a model emitting
an INVENTED vocabulary against an open-ish shape; `additionalProperties:false` + an `action` enum makes
a bad turn fail LOUDLY at the schema boundary instead of executing garbage silently.

---

## 1. THE SCHEMA (CLOSED)

```json
{
  "type": "function",
  "function": {
    "name": "consult_action",
    "description": "Perform exactly one step of a Family-chat consult on one Chat display. The seat executes it and verifies the postcondition; it never runs anything outside this schema.",
    "parameters": {
      "type": "object",
      "additionalProperties": false,
      "required": ["action", "platform"],
      "properties": {
        "action": {
          "type": "string",
          "enum": ["navigate", "select_model", "select_mode", "attach", "enter_prompt", "send", "poll_complete", "extract"]
        },
        "platform": { "type": "string", "enum": ["chatgpt", "claude", "gemini", "grok", "perplexity"] },
        "value":    { "type": "string", "description": "action-dependent: model/mode name, packet path, or prompt text; omit for navigate/send/poll_complete/extract" }
      }
    }
  }
}
```

The **display is NOT a Taey parameter** — the seat binds one platform→display at lease time (from
machine.env), so Taey cannot address :2–:6 directly (partition-safe by construction; Taey names the
*platform*, the seat owns the *display*). `value` is a single free string only where an action needs
one (model/mode name from the platform's YAML enum, packet path, or prompt text) — the executor
validates it against the platform YAML, so an invented model name fails at execution, not silently.

---

## 2. THE ACTIONS → consult_v2 primitives → OBSERVABLE POSTCONDITION

Each action maps to primitives I own in `consult_v2`, and each has a postcondition the executor checks
to prove **executed vs claimed** (infra's ask #2). "FAIL-CLOSED" = the seat latches the turn as failed
and returns the observed tree, never a success it can't verify.

| action | value | consult_v2 primitive(s) | OBSERVABLE POSTCONDITION (executor verifies) |
|---|---|---|---|
| `navigate` | — | `runtime.navigate(url)` (url from platform YAML) | URL bar == target; document subtree present in `snapshot()` (raw_count > 1, not near-empty) |
| `select_model` | model name (∈ platform YAML enum) | open model menu → `find_first(model_key)` → `runtime.click` | the persistent trigger label reflects the model (e.g. Claude composer button == "Model: Opus 5 …"); `states_include:[checked]` on a persistent element |
| `select_mode` | mode name (∈ platform YAML enum) | `find_first(mode_key)` → click; for Claude effort = the submenu path | the mode's persistent `*_active` validation indicator passes (per platform YAML `validation`) |
| `attach` | packet path (must exist on disk) | attach control → file dialog → `runtime.type_text(path)` → Open | the file chip is present in `snapshot()` (Grok is AT-SPI-blind → screenshot-verify the chip). **Attach fail = FULL STOP** (CLAUDE.md), never a paste-fallback |
| `enter_prompt` | prompt text | pointer-click composer → `runtime.paste(text)` | the rendered char-count / composer text reflects the paste (verify the RENDERED value, not AT-SPI char_count) |
| `send` | — | `runtime.click(send)` or Enter (Ppx/Grok submit on Enter) | send validated: Stop button APPEARED **and** (new session) URL changed; else FAIL-CLOSED |
| `poll_complete` | — | completion detector (stop-button present→gone, debounced N cycles) | returns `pending` or `complete`; `complete` only after stop seen-then-gone for the required cycles — never a content-guess |
| `extract` | — | scroll-to-bottom → copy element → `runtime.read_clipboard()` | clipboard holds a NON-echo body (not the prompt; not the grok two-copy-button prompt-echo; flag if it self-reports truncation). Returns the raw text to Taey |

**Deadline/iteration policy (seat-contract param, like ui_action's submit deadline):** a consult lease
bounds total turns (~40 covers author-less dispatch→poll→extract for one lane) and a wall-clock deadline
(deep modes run long — poll_complete is the long pole; the seat's deadline, not Taey, bounds a hung run).

**Log-lease:** every `consult_action` + its observed postcondition appends to a pristine leased log
(the ui_action `taey_submit_capture` analog) so the run is auditable and rows can later be authored by
PARSING it (treasurer: parse-assert, never description).

---

## 3. WHAT TAEY ORCHESTRATES vs WHAT THE SEAT OWNS

- **[TAEY]** decides the sequence: which platform, which model/mode (from the enums), when the packet is
  ready to attach, that a lane is `complete` (reads poll_complete), and that an extracted body is a real
  answer to deliver. Taey emits one `consult_action` per turn and reads the observed result.
- **[SEAT/ENGINE]** owns: the display binding, the dispatch-lock, AT-SPI actuation, the YAML element
  lookups, the completion debounce, and postcondition verification. Taey never sees :2–:6.

This is the SAME division as careers (Taey emits `ui_action`, the ATS server actuates) — which is why
infra's "one harness, two bindings" is correct: `seat(consult_action, consult_v2_executor)`.

---

## 4. FOR INFRA (harness extraction) — the seat-contract parameters this binding supplies

1. **tool name + schema:** `consult_action` + §1 (closed, enum'd).
2. **executor callable:** a `consult_v2` entry I expose — `execute(action, platform, value) -> {ok, observed, postcondition_met}` — wrapping the §2 primitives + verification. I will provide this against `consult_v2/runtime.py` so infra never reaches into my primitives.
3. **deadline/iteration policy:** consult lease (§2) — longer wall-clock than ATS (deep-mode generation), bounded turns.
4. **log-lease:** consult capture dir analogous to `taey_submit_capture`.

## 5. OPEN QUESTIONS
- Should `author` (build_consultation + lint) be a `consult_action` too, or a pre-seat step? (Leaning:
  author is Taey text-gen + a lint gate, not a UI action — keep it out of this UI tool; a separate
  `author`/`lint` surface or a pre-step.)
- One lane per lease, or a multi-lane lease (Taey drives 5 platforms in one run)? Single-lane is the
  safe first shape; multi-lane can wrap it later.

*Draft for infra review + treasurer sequencing. Executor callable follows once the schema is agreed.*
