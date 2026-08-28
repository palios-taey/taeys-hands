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

## Completion and extraction

The per-display completion monitor polls the selected platform's mapped Stop control every three seconds.
After two successive Stop-absent observations, it immediately prepares and invokes exactly one frozen
`scripts/run_manual_chat_worker.py extract` transaction using the send turn's seat identity. The monitor
records terminal success or failure before sending any notification, so notification retries cannot launch
another extraction.

Claude's prepare-only handoff validates both typed YAML workflows and reserves the final `request.json`
path, but does not create that file, observe AT-SPI, or inspect a download directory. After consuming the
handoff marker, the launcher takes one canonical Claude base snapshot. Exactly one mapped controls section,
View button, and Download button selects `downloaded_file`; complete absence selects `assistant_text`; any
partial or duplicate trio stops before a worker invocation. Only `downloaded_file` resolves and snapshots
the Firefox download scope. The launcher then creates the one branch-specific `request.json` exclusively
and invokes one Taey turn. The worker's first fresh observation must prove the same branch before mutation.

Main Taey does not run an extraction command and does not drive the display. It receives only the persisted
result: `monitor_id`, terminal extraction status, and, on success, the response path, byte count, and
SHA-256. On failure it receives the first error and `terminal=true`. No supervisor, status recipient, or
worker may issue a second extraction request.

The monitor sends Main Taey a record-only `taey-notify --type result` body as compact, key-sorted JSON with
`schema="taey.consult_terminal_receipt.v1"`. Every receipt contains `monitor_id`, `platform`, `display`,
`extraction_status`, and `terminal=true`. Success adds `response_file`, `bytes`, `sha`, `request_json`,
`headers`, `response_json`, `event`, and `correlation`; failure adds `error` and any lineage fields available
from the attempted handoff. Notifications to an explicit requester remain actionable `status` messages.

## Exact `drive_chat` vocabulary

The following argument names are exact. A different name is a terminal refusal for the turn.

| Action | Exact arguments after `display` and `action` |
|---|---|
| `observe` | optional `scope`; valid values are `base`, `menu_snapshot`, `app_root_snapshot` |
| `navigate` | `url` |
| `click`, `focus`, `activate`, `hover`, `operate` | `element` |
| `type` | `text` |
| `paste` | `text_file` for a frozen prompt; `text` only for short inline text |
| `key` | `key` |
| `focus_dialog` | no additional argument |
| `read_clipboard` | `output_file` |

Never pass `ref`, `snapshot`, `path`, a raw accessible name, or coordinates. `element` must be the exact
mapped key from the immediately preceding fresh observation in the same scope. Presence resolves that key
to the stored canonical ref, including the YAML selection rule, without model transcription. If a mapped
item reports `declared_operation`, call `operate` with its element key; otherwise use only the direct action
authorized by the selected platform card.

`declared_operation.primitives` describes how the runtime implements the semantic operation. For
`focus_and_key_open`, one `operate` call resolves and focuses the exact fresh element, verifies focus, and sends the exact YAML
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

Firefox may render the focused address bar differently from the absolute URL it receives. A platform may
declare only its observed exact renderings in `urls.address_bar_exact_paste_values`; when absent, the proof
remains literal `urls.fresh`. The navigation receipt records the observed and matched exact values. This
pre-Return rendering proof never replaces the post-Return absolute document-URL and populated-tree gates.

## Claude memory-review pre-send recovery

Claude can replace the fresh composer with the exact dialog `Review updates to Claude’s memory`. That state
is a terminal first mismatch for the send identity. Never resend that identity. After the failure is preserved,
launch one separately identified recovery transaction only when a fresh canonical base observation maps exactly
one `claude_memory_review_dialog` and one enabled `claude_memory_not_now`, with the three navigation-ready
controls absent:

```bash
python3 scripts/run_manual_chat_worker.py recover-claude-pre-send \
  --display :3 \
  --seat-id NEW_RECOVERY_SEAT \
  --artifact-root NEW_PRIVATE_ARTIFACT_ROOT \
  --exception-key memory_review \
  --source-terminal-identity SPENT_SEND_IDENTITY
```

The recovery worker takes two read-only classification observations, clicks only the YAML-mapped `Not now`
control once, and then applies Claude's existing navigation postcondition barrier: exactly one `input`,
`model_selector`, and `toggle_menu` for two consecutive fresh base observations. The dialog, recovery button,
Stop control, and mapped monitor exceptions must be absent. A settling sample authorizes only another read; any
real mismatch or exhausted barrier writes failure evidence and stops. A successful recovery does not attach,
paste, send, register a monitor, or authorize reuse of the failed send identity. Start the valuable consultation
as another new send identity after the recovery receipt passes.

## Grok Bot pre-send recovery

Grok can overlay the exact fresh composer with the exact dialog `Meet Grok Bot` and the two exact push buttons
`Dismiss` and `Get Grok Bot`. That state is a terminal first mismatch for the send identity. Never reuse or
retry that identity. After the terminal evidence is preserved, launch one separately identified recovery
transaction only when two fresh canonical base observations at the exact YAML `urls.fresh` URL each map exactly
one `grok_bot_dialog`, one enabled `grok_bot_dismiss`, and one enabled `grok_bot_get`, with no uploaded-file,
remove-attachment, Send, or Stop control:

```bash
python3 scripts/run_manual_chat_worker.py recover-grok-pre-send \
  --display :23 \
  --seat-id NEW_RECOVERY_SEAT \
  --artifact-root NEW_PRIVATE_ARTIFACT_ROOT \
  --exception-key meet_grok_bot \
  --source-terminal-identity SPENT_SEND_IDENTITY
```

The recovery worker clicks only the YAML-mapped `Dismiss` control once. It never clicks `Get Grok Bot`,
navigates, selects a model, attaches, pastes, or sends. The post-click barrier requires exactly one `input`,
`attach_trigger`, `model_selector`, and `new_chat` for two consecutive fresh base observations at the exact fresh
URL. Every interstitial, attachment, Send, and Stop control must be absent. The receipt binds both pre-click
revisions and exact count and state maps, the single click primitive, the final two stable revisions and count maps,
and zero navigation/attachment/paste/send counts. A real mismatch or exhausted barrier stops without another
mutation. A passed recovery authorizes only a new send identity; it never resumes the spent one.

## Grok open-model-menu pre-send normalization

Navigation can finish at the exact fresh Grok URL while the previous model menu remains open. In that state a
fresh canonical base observation maps exactly one each of `model_auto`, `model_fast`, `model_expert`, and
`model_heavy`, while the normal composer controls are absent. The stopped send identity remains terminal. Launch
the existing one-shot Grok pre-send recovery command with a distinct seat and the YAML-owned exception key:

```bash
python3 scripts/run_manual_chat_worker.py recover-grok-pre-send \
  --display :5 \
  --seat-id NEW_NORMALIZATION_SEAT \
  --artifact-root NEW_PRIVATE_ARTIFACT_ROOT \
  --exception-key model_menu_open \
  --source-terminal-identity SPENT_SEND_IDENTITY
```

The worker takes two read-only base observations at exact `https://grok.com/`. Both must map the four current
model options exactly once with `showing`, `focusable`, and `enabled`, while every Grok Bot, attachment, Send,
Stop, and response-Copy control is absent. It then clicks only YAML-selected `model_heavy` once. Two consecutive
fresh base observations must map exactly one `input`, `attach_trigger`, `model_selector`, and `new_chat`; all four
model options and every blocked control must be absent. The receipt binds both classification revisions, exact
count and state maps, the single click, both stable postcondition revisions and count maps, and zero navigation,
attachment, paste, and send counts. Success authorizes a new send identity only. No normalization identity may
navigate, attach, paste, send, or resume the spent source identity.

## Platform card

| Member | Platform/display | YAML | Requested selection | Attachment menu observation | Submit |
|---|---|---|---|---|---|
| Horizon | ChatGPT `:2` | `consultation_v2/platforms/chatgpt/chatgpt.yaml` | `model=pro` | `app_root_snapshot` | focus composer, `key Return` |
| Gaia | Claude `:3` | `consultation_v2/platforms/claude/claude.yaml` | `model=opus`, `mode=extended_thinking` | `app_root_snapshot` | `operate`/`click` exact `send_button` element |
| Cosmos | Gemini `:4` | `consultation_v2/platforms/gemini/gemini.yaml` | Pro Extended + Deep Research tool | YAML `workflow.attachment.scope`, otherwise `base` | plan Send, then exact `start_research` element |
| Logos | Grok `:5` | `consultation_v2/platforms/grok/grok.yaml` | `model=heavy` | YAML `workflow.attachment.scope`, otherwise `base` | `operate`/`click` exact `send_button` element |
| Clarity | Perplexity `:6` | `consultation_v2/platforms/perplexity/perplexity.yaml` | `mode=deep_research` | YAML `workflow.attachment.scope`, otherwise `base` | `operate`/`click` exact `submit_button` element |

Grok's model-selector open is one mapped-pointer mutation followed internally by the YAML-owned
`workflow.model_selector_post_action` observation barrier. The barrier performs only fresh live app-root reads;
it does not clear the transient portal or repeat the selector action. All four declared model options must map
exactly once with their declared states for two consecutive samples, while all three mapped Grok Bot interstitial
controls remain absent, before the operation can return success. Current Firefox AT-SPI exposes those options as
`menu item`. The undeclared Build option may remain unknown and cannot authorize a selection.

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
   the exact fresh trigger element once. This is the driver's existing default menu-open action.
5. For `open_method: click`, require `allowed_now=["click"]` and `operate` the fresh trigger element once.
6. For `open_method: focus_and_key_open`, `operate` the fresh trigger element once and require the receipt's
   `performed_primitive` is `focus_and_key_open`.
7. Only after the complete open receipt, observe exactly the menu's `operate.scope`.
8. Require exactly one mapped target for the requested option element.
9. `operate` that option element when it advertises `declared_operation`; otherwise use its YAML-authorized direct
   action once.
10. Observe again and require the YAML active state. If active state is visible only inside the opened menu,
   reopen once through the same observe/action discipline solely to validate it. Any platform card that uses
   this validation-only reopen must pin one close action and a fresh base proof before the attachment leg.

Never silently downgrade. If the requested option is unavailable, report the exact observed state and stop
that leg before attaching files.

### 3. Attach Bundle A

Start from a fresh base observation and record the current attachment-chip/remove-control count.

```text
observe base
operate element=<workflow.attachment.trigger>
require performed_primitive == "focus_and_key_open"
observe using <workflow.attachment.scope, otherwise base>
operate or authorized direct action with element=<workflow.attachment.menu_target>
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
`workflow.full_consult.steps.composer_input` element.

```text
click element=<workflow.full_consult.steps.composer_input>
observe
paste text_file=PROMPT_FILE
observe
```

Validate arrival behaviorally: the YAML submit control becomes mapped/enabled while both attachment states
remain present. Do not require a framework-rendered composer to echo the prompt text into the accessibility
tree.

### 6. Send once

Use the Submit action in the platform card. Immediately make one fresh base observation.

If an exact key named by `workflow.send`/`workflow.monitor` is present as the Stop control, register the
external completion monitor. If Stop is absent, make exactly one more fresh base observation without any
intervening mutation. A Stop control on that second observation registers the monitor. If Stop is still
absent, classify only a complete exact element set declared in `workflow.post_send.exceptions`. Preserve
both observation revisions and return a `POST-SEND EXCEPTION REPORT`; do not click its recovery control in
the send turn. If no declared exception set matches, preserve both revisions and return an
`UNMAPPED POST-SEND STATE` report. A URL, response controls, or response text never proves completion.

Return a send receipt containing platform, display, final URL, two-attachment proof, actual model/mode,
mapped Stop key, and monitor registration. Then stop all UI calls on that display. The worker never polls for
completion.

An exception recovery is a new frozen worker turn tied to the source worker-response SHA-256. It makes the
same two read-only observations before mutation, permits only the exact action and element declared by that
exception's YAML `recovery`, and enforces `max_attempts: 1`. After that single action, apply the same two-
observation Stop/exception classification. Stop is handed to the monitor; a persistent or different state
ends the recovery turn without a second action.

### 7. Extract only after the completion notification

Use a new worker turn after the monitor reports completion:

```text
drive_chat(display=DISPLAY, action="observe", scope="base")
drive_chat(display=DISPLAY, action="key", key="ctrl+End")
drive_chat(display=DISPLAY, action="observe", scope="base")
operate or authorized direct action with element=<workflow.extract.primary_key>
drive_chat(display=DISPLAY, action="observe", scope="base")
drive_chat(display=DISPLAY, action="read_clipboard", output_file=RESPONSE_FILE)
```

Require a newly created non-empty file and record its byte count and SHA-256 from the tool receipt. Reject an
unchanged clipboard, the sent prompt, a prompt prefix, or text that does not answer the task. Never overwrite
an existing response path.

Platform-specific extraction remains YAML-owned:

- Claude: the first fresh base observation classifies exactly three generated-artifact controls. All three
  present exactly once selects `extraction.downloaded_file`; all three absent selects
  `extraction.assistant_text`; a partial or duplicate set stops before any UI mutation. The downloaded-file
  branch clicks only `generated_artifact_download_button` once, observes once, and materializes exactly one
  new stable non-empty regular non-symlink file into `response.txt` with source/destination hashes. The
  current Firefox profile uses the shared `~/Downloads` default, so this path is qualified only inside a
  serial exclusive download window. Any concurrent, partial, changed, duplicate, multiple, or symlink entry
  is terminal; parallel-safe attribution requires a separately measured profile-local download directory.
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
