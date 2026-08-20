# Taey worker action cards for Family-Chat consultations

This is the compact instruction surface for a Taey worker driving one real consultation on one Chat display.
The packet, two bundles, prompt file, display services, browser profiles, platform YAML, `drive_chat`, and
completion monitor already exist. A worker does not rebuild any of them. Its job is only to execute and
validate the UI transaction.

The governing contracts are [`100_TIMES.md`](../100_TIMES.md),
[`CONSULTATION_CONTRACT.md`](../CONSULTATION_CONTRACT.md),
[`UI_INTERACTION_AUTHORITY.md`](UI_INTERACTION_AUTHORITY.md), and the selected platform YAML. This card
turns those contracts into a small worker handoff. The platform YAML remains mutable UI authority and each
fresh `drive_chat` observation remains the runtime oracle.

This file is the sole executable supervisor-to-worker procedure for this manual lane. The linked contracts
define its invariants; they are not alternate launch procedures.

## Give one worker only these inputs

```text
PLATFORM=<chatgpt|claude|gemini|grok|perplexity>
DISPLAY=<:2|:3|:4|:5|:6>
BUNDLE_A=<absolute path to the governance bundle>
BUNDLE_B=<absolute path to the task bundle>
PROMPT_FILE=<absolute path to the brief prompt>
RESPONSE_FILE=<new absolute path for the verbatim response>
```

Send one platform leg per worker turn. Do not ask one worker to read all five YAMLs, hold all five identities,
or drive several displays. Bundle A, Bundle B, and the prompt are frozen before the worker starts. The worker
does not edit, summarize, rebuild, lint, or reinterpret them.

## Start one ChatGPT worker

This is the canonical current-path invocation for the first platform leg. The ChatGPT send phase through
Stop proof and monitor registration is production-proven by the
[`2026-08-20 manual-chat-ui receipt`](../receipts/manual-chat-ui/2026-08-20-chatgpt-send.md). Completion and
extraction remain separate acceptance gates and must not be inferred from the send receipt.

First write one frozen request JSON file, replacing only the five uppercase fields in `content`:

```json
{
  "model": "taey",
  "stream": false,
  "max_tokens": 8192,
  "chat_template_kwargs": {"enable_thinking": false},
  "messages": [
    {
      "role": "user",
      "content": "Read RUNBOOK. Execute the ChatGPT send phase only on DISPLAY with BUNDLE_A, BUNDLE_B, and PROMPT_FILE. Use drive_chat only and follow the runbook exactly. Stop after the section 6 send receipt or the first mismatch. Do not extract, retry, or recover in this turn."
    }
  ]
}
```

Then replace the six uppercase command fields and invoke the worker exactly once:

```bash
curl -sS --max-time 3600 \
  -D RESPONSE_HEADERS \
  -o RESPONSE_JSON \
  -H 'Content-Type: application/json' \
  -H 'X-Taey-Seat-Id: SEAT_ID' \
  -H 'X-Taey-Event-Id: EVENT_ID' \
  -H 'X-Taey-Correlation-Id: CORRELATION_ID' \
  -H 'X-Taey-Tool-Profile: manual-chat-ui' \
  --data-binary @WORKER_REQUEST_JSON \
  http://127.0.0.1:8767/v1/chat/completions
```

`SEAT_ID`, `EVENT_ID`, and `CORRELATION_ID` must be unique, stable identifiers for this one transaction and
must match their values in the returned response headers. `RESPONSE_HEADERS` and `RESPONSE_JSON` must be new
paths. A curl error, non-200 response, missing/mismatched identity header, malformed response, worker stop
report, or missing section 6 send receipt ends the transaction. Never resend the request after an uncertain
transport result.

## Exact `drive_chat` vocabulary

The following argument names are exact. A different name is a terminal refusal for the turn.

| Action | Exact arguments after `display` and `action` |
|---|---|
| `observe` | optional `scope`; valid values are `base`, `menu_snapshot`, `app_root_snapshot` |
| `navigate` | `url` |
| `click`, `focus`, `activate`, `hover`, `operate` | `ref` |
| `type` | `text` |
| `paste` | `text_file` for a frozen prompt; `text` only for short inline text |
| `key` | `key` |
| `focus_dialog` | no additional argument |
| `read_clipboard` | `output_file` |

Never pass `element`, `snapshot`, `path`, a raw accessible name, or coordinates. A `ref` is usable only from
the immediately preceding fresh observation in the same scope. If a mapped item reports
`declared_operation`, call `operate` with its ref; otherwise use only the direct action authorized by the
selected platform card.

`declared_operation.primitives` describes how the runtime implements the semantic operation. For
`focus_and_key_open`, one `operate` call focuses the exact fresh ref, verifies focus, and sends the exact YAML
`open_key`. Require `performed_primitive="focus_and_key_open"`, then observe the declared menu scope and prove
the exact YAML target. Taey never issues separate focus and key calls for this method.

## The invariant for every worker turn

```text
fresh observe -> one mutation -> fresh observe -> validate
```

The only exception is the first `navigate`, which accepts the exact YAML `urls.fresh` value and then still
requires a fresh base observation. After any failed, refused, absent, duplicate, or unexpected result, stop
the leg immediately and report the first mismatch. Do not press Escape, close a menu, retry, recover, switch
displays, or invent a fallback in that turn.

## Platform card

| Member | Platform/display | YAML | Requested selection | Attachment menu observation | Submit |
|---|---|---|---|---|---|
| Horizon | ChatGPT `:2` | `consultation_v2/platforms/chatgpt/chatgpt.yaml` | `model=pro` | `app_root_snapshot` | focus composer, `key Return` |
| Gaia | Claude `:3` | `consultation_v2/platforms/claude/claude.yaml` | `model=opus`, `mode=extended_thinking` | `app_root_snapshot` | `operate`/`click` exact `send_button` ref |
| Cosmos | Gemini `:4` | `consultation_v2/platforms/gemini/gemini.yaml` | `model=pro`, `mode=deep_think` | YAML `workflow.attachment.scope`, otherwise `base` | `operate` exact `send_button` ref |
| Logos | Grok `:5` | `consultation_v2/platforms/grok/grok.yaml` | `model=heavy` | YAML `workflow.attachment.scope`, otherwise `base` | `operate`/`click` exact `send_button` ref |
| Clarity | Perplexity `:6` | `consultation_v2/platforms/perplexity/perplexity.yaml` | `mode=deep_research` | YAML `workflow.attachment.scope`, otherwise `base` | `operate`/`click` exact `submit_button` ref |

At the start of the leg, inspect only the executable parts of that one YAML:

```bash
sed -n '/^urls:/,/^tree_filter:/p; /^workflow:/,/^settle:/p' \
  consultation_v2/platforms/<platform>/<platform>.yaml
```

Use `urls.fresh`, `workflow.full_consult`, `workflow.selection`, `workflow.attachment`, `workflow.prompt`,
`workflow.send`, `workflow.monitor`, and `workflow.extract`. Do not read another platform's YAML and do not
carry a scope, control, shortcut, or postcondition across platforms.

## Worker procedure

### 1. Open a fresh thread

```text
drive_chat(display=DISPLAY, action="navigate", url=<this YAML's exact urls.fresh>)
drive_chat(display=DISPLAY, action="observe", scope="base")
```

Require the expected platform, populated mapped tree, `workflow.full_consult.steps.composer_input`, no auth
wall, no usage/capacity exception, and no already-running response. Record the fresh URL. A near-empty tree
or wrong platform is a stop.

### 2. Select the requested model and mode

For each row in `workflow.full_consult.select_mode`:

1. From a fresh base observation, find the menu's `workflow.selection.menus.<menu>.operate.trigger`.
2. If the current trigger already satisfies the YAML `active_recognition`, record that and do not mutate it.
3. Otherwise inspect the menu's `operate.open_method` and the fresh trigger's `declared_operation`.
4. When `open_method` is absent, require the trigger has no `declared_operation`, then use direct `click` on
   the exact fresh trigger ref once. This is the driver's existing default menu-open action.
5. For `open_method: click`, require `allowed_now=["click"]` and `operate` the fresh trigger ref once.
6. For `open_method: focus_and_key_open`, `operate` the fresh trigger ref once and require the receipt's
   `performed_primitive` is `focus_and_key_open`.
7. Only after the complete open receipt, observe exactly the menu's `operate.scope`.
8. Require exactly one mapped ref for the requested option element.
9. `operate` that option ref when it advertises `declared_operation`; otherwise use its YAML-authorized direct
   action once.
10. Observe again and require the YAML active state. If active state is visible only inside the opened menu,
   reopen once through the same observe/action discipline solely to validate it.

Never silently downgrade. If the requested option is unavailable, report the exact observed state and stop
that leg before attaching files.

### 3. Attach Bundle A

Start from a fresh base observation and record the current attachment-chip/remove-control count.

```text
observe base
operate <fresh attachment trigger ref>
require performed_primitive == "focus_and_key_open"
observe using <workflow.attachment.scope, otherwise base>
operate or authorized direct action on <workflow.attachment.menu_target fresh ref>
observe
focus_dialog
observe
key ctrl+l
observe
key ctrl+a
observe
type BUNDLE_A
observe
key Return
observe
```

The observations between native-dialog primitives are ordinary `drive_chat(..., action="observe")` calls;
the tool routes them to the native chooser until Return closes it. Require the chooser title after
`focus_dialog`. The final browser observation must show the YAML `workflow.full_consult.attachment_present`
state increased from zero to one. An opened chooser is not an attachment.

### 4. Attach Bundle B independently

Repeat section 3 with `BUNDLE_B`. The final fresh browser observation must prove exactly two attachment
chips/remove controls. Do not infer Bundle B from Bundle A's success and do not continue with one attachment.

### 5. Paste the frozen brief

From a fresh base observation, require both attachments and exactly one mapped
`workflow.full_consult.steps.composer_input` ref.

```text
click <fresh composer ref>
observe
paste text_file=PROMPT_FILE
observe
```

Validate arrival behaviorally: the YAML submit control becomes mapped/enabled while both attachment states
remain present. Do not require a framework-rendered composer to echo the prompt text into the accessibility
tree.

### 6. Send once

Use the Submit action in the platform card. Immediately make one fresh base observation.

Require at least one exact key named by `workflow.send`/`workflow.monitor` as the Stop control. Where the
YAML requires a new URL, also require that the URL changed from the recorded fresh URL. This Stop-proven
observation registers the external completion monitor.

Return a send receipt containing platform, display, final URL, two-attachment proof, actual model/mode,
mapped Stop key, and monitor registration. Then stop all UI calls on that display. The worker never polls for
completion.

### 7. Extract only after the completion notification

Use a new worker turn after the monitor reports completion:

```text
drive_chat(display=DISPLAY, action="observe", scope="base")
drive_chat(display=DISPLAY, action="key", key="ctrl+End")
drive_chat(display=DISPLAY, action="observe", scope="base")
operate or authorized direct action on <last workflow.extract.primary_key ref>
drive_chat(display=DISPLAY, action="observe", scope="base")
drive_chat(display=DISPLAY, action="read_clipboard", output_file=RESPONSE_FILE)
```

Require a newly created non-empty file and record its byte count and SHA-256 from the tool receipt. Reject an
unchanged clipboard, the sent prompt, a prompt prefix, or text that does not answer the task. Never overwrite
an existing response path.

Platform-specific extra output remains separate from the primary answer:

- Claude: inspect `workflow.extra_extract` and capture any generated artifact through its exact mapped
  artifact Copy/Download control to a second new output path.
- Gemini: inspect `workflow.extra_extract` for Share/Export `copy_content_item` when the primary answer is a
  report surface.
- Perplexity Deep Research: inspect `workflow.extract.deep_research` and prefer the mapped Markdown download
  for the report artifact while also retaining the primary response.

## Required stop report

```text
platform/display:
YAML path and section:
current URL:
last successful observation scope and revision:
one action attempted:
tool result/error:
expected postcondition:
observed postcondition:
classification: YAML DRIFT | AUTH/CAP | ARGUMENT ERROR | INFRASTRUCTURE | UNKNOWN
```

The stop report is the result of that worker turn. Recovery is a new, explicitly authorized turn after the
instruction, YAML, environment, or primitive is corrected.
