# ChatGPT manual-chat-ui production send receipt — 2026-08-20

## Verdict

**PASS for the ChatGPT send phase through completion-monitor registration.** A Taey worker, not the
supervisor, navigated a fresh ChatGPT thread on `:2`, attached exactly two frozen files, pasted the frozen
prompt from disk, sent once, proved the mapped Stop control, and registered the external completion monitor.
The worker then stopped all UI calls.

Completion monitoring and response extraction were not part of this worker turn and are not claimed by this
receipt.

## Deployed public artifacts

| Surface | Exact production commit | Relevant public changes |
|---|---|---|
| `palios-taey/taeys-hands` | `f61d7614d0cec55550f68f94de7db2af86f72d21` | PR `#82`: canonical worker card, ChatGPT native-dialog contract, semantic menu-operation contract |
| `palios-taey/taey-presence` | `e5bda7f6a5b240c1e23ea0c65023432a09635b7d` | PRs `#167`–`#170`: semantic menu open, native-observe projection, stale-generation lease takeover, Escape-to-browser transition |

Both SHAs were the checked-out public `main` revisions consumed by production before the accepted turn.

## Transaction identity

| Field | Value |
|---|---|
| platform / display | `chatgpt` / `:2` |
| seat | `infra-codex-chatgpt-send-r4-20260820` |
| event / correlation | `chatgpt-send-r4-20260820` |
| turn | `1ba8c92389864d939dca19629d674ce3` |
| tool profile | `manual-chat-ui` |
| proxy HTTP result | `200 OK` |
| worker finish reason | `stop` |
| full response SHA-256 | `60d81755f8581f031e81063541cd8a1607d480b446bf3ed2c989db420a50ab93` |
| response-header SHA-256 | `5526637ea8517e1f3c4a721e7609c554ca3b41a271ffb8eeaf14614467be9e41` |

The response headers returned the same seat, event, correlation, and turn identities. The private thread URL
is intentionally omitted; its SHA-256 is
`23e033db411f40d748872897d3401e9b07b414e8b22d6fc9357ee12a9417499a`.

## Unbroken action-and-validation chain

1. Taey read only the canonical public worker card and ChatGPT YAML.
2. `navigate` opened the exact YAML `urls.fresh`; a fresh base observation proved ChatGPT, the composer, no
   mapped auth/capacity exception, and no running response.
3. The base tree already recognized model `Pro`; no model mutation was made.
4. Bundle A:
   - fresh base observe;
   - one `operate` on `attach_trigger`, returning `performed_primitive=focus_and_key_open`;
   - fresh `app_root_snapshot` mapped exactly one `tool_upload`;
   - one `operate` on that ref opened the chooser;
   - `focus_dialog`, native observe, `ctrl+l`, observe, `ctrl+a`, observe, exact absolute-path type, observe,
     `Return`, browser observe;
   - attachment count changed from zero to one.
5. Bundle B repeated the independent sequence; the final browser observation proved exactly two chips and
   two remove controls.
6. A fresh composer ref was clicked once. `paste` used the frozen prompt file and reported
   `pasted_chars=428`. The next observation preserved both attachment controls and mapped the enabled Send
   control.
7. Taey sent once with `key Return`.
8. The single post-send base observation changed the URL from the fresh root to a thread URL, mapped exact
   `stop_answering_button`, and registered monitor
   `infra-codex-chatgpt-send-r4-20260820-2-1ba8c92389864d939dca19629d674ce3`.
9. Taey returned its section-6 receipt and made no further UI calls.

The accepted worker turn contained 37 `drive_chat` calls across tool rounds 3–39. No failed action, mutation
retry, duplicate send, extraction call, or post-send polling occurred in that turn.

## Attachment and prompt proof

The pre-send revision `0391b128633928873fac31c1dbf3b293bf6adbc2d5d607e48bba0da7f07e1d2a`
mapped:

- `attachment_chip_1`: `bundle_a_chatgpt(3).md`, with `Remove file 1`;
- `attachment_chip_2`: `bundle_b_chatgpt_worker_handoff.md`, with `Remove file 2`;
- the enabled Send control after the 428-character file paste.

The post-send revision `6c8d9b027c25ab8e75333c362ac41ce6c86dbddee0dc69a396836bb95a1783d2`
mapped `stop_answering_button` and carried the monitor-registration receipt.

## Truth register

- **Observed:** Taey executed the complete chain above; the two attachments were mapped; the frozen prompt
  was pasted from its file; one send occurred; Stop was mapped; the monitor registered; identity headers
  matched; the worker stopped.
- **Inferred:** ChatGPT added `(3)` to Bundle A's displayed filename because of its duplicate-name handling.
  The chooser observation proved the typed source path before submission, so this did not change the selected
  input file.
- **Unknown at send receipt time:** completion debounce result, response extraction, output-attachment
  harvesting, and ISMA ingestion. Those require the monitor notification and a separate extraction turn.

