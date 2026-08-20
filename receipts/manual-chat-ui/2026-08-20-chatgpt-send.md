# ChatGPT manual-chat-ui production send receipt — 2026-08-20

## Verdict

**PASS for the ChatGPT send and extraction UI phases.** A Taey worker, not the
supervisor, navigated a fresh ChatGPT thread on `:2`, attached exactly two frozen files, pasted the frozen
prompt from disk, sent once, proved the mapped Stop control, and registered the external completion monitor.
The worker then stopped all UI calls. The monitor later detected completion and a new Taey worker turn copied
the response to a new, hash-verified file.

**The Hub handoff itself required one supervisor intervention and is not claimed as autonomous.** The first
monitor notification hit a transient fleet-notify readiness refusal. A later delivery succeeded, but Main
Taey interpreted `delegate extraction` as `send_message` to the `infra` fleet session instead of invoking its
`:8767` worker. No UI action occurred in that failed handoff. The supervisor then started the separate Taey
extraction turn once using the now-canonical request shape. The monitor retry and exact Main-Taey invocation
are corrected by the commit carrying this receipt; a later production consultation must prove that corrected
handoff without intervention.

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

## Completion and extraction identity

| Field | Value |
|---|---|
| completion detected | `2026-08-20 21:59 UTC` |
| monitor outcome | Stop absent after debounce; phase first became `notification_failed` |
| notification retry | delivered to `taey` at `2026-08-20 22:06 UTC` |
| extraction event / correlation | `chatgpt-extract-r4-20260820` / `chatgpt-extract-r4-20260820-1` |
| extraction turn | `33f6f08513b444b08be8d4cc56831870` |
| extraction proxy result | `200 OK`, `finish_reason=stop` |
| extraction request SHA-256 | `941f9e76d9947422c96e9ed9bd31527ebb6fe9e652f4c40a869ee5d9d1406b50` |
| extraction headers SHA-256 | `ec3c0982de389b9ce96252da1c46373a4ce42bf2e6714722cec21b77cf68e22a` |
| extraction JSON SHA-256 | `4a43d3d6ea08e5a27ecaf614581a994670d667ed76e6b4ccea04ceb57766946b` |
| response bytes / characters | `14,041` / `13,919` |
| response SHA-256 | `a5b8f595a471c7c6dfa53befc8d460db8bc7829794ecb7d6bd3b47e20b64e495` |

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
10. The external monitor observed the mapped Stop control disappear and declared completion after its
    debounce.
11. The first notification failed readiness and preserved the exact route as `notification_failed`; it did
    not discard the completion proof.
12. The same fleet notification later delivered successfully and Main Taey claimed it.
13. Main Taey sent the extraction task to `infra` instead of invoking `:8767`. This was the handoff mismatch;
    it made no UI call.
14. A new Taey extraction turn made a fresh base observation, sent `ctrl+End`, and made another fresh base
    observation.
15. Taey clicked the last mapped `copy_button` once and observed the post-click base tree.
16. Taey called `read_clipboard` with a new output path. The tool created a 14,041-byte file and returned the
    SHA-256 recorded above.
17. Taey read the response head, verified that it was a substantive memorandum answering the frozen task and
    not the 428-character prompt or a prompt prefix, returned its section-7 receipt, and stopped UI calls.

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

- **Observed:** Taey executed the send and extraction UI chains above; the two attachments were mapped; the
  frozen prompt was pasted from its file; one send occurred; Stop was mapped; the monitor registered and
  detected completion; the separate extraction turn produced the non-empty hash-verified response file;
  identity headers matched; both worker turns stopped.
- **Inferred:** ChatGPT added `(3)` to Bundle A's displayed filename because of its duplicate-name handling.
  The chooser observation proved the typed source path before submission, so this did not change the selected
  input file.
- **Unknown:** whether the corrected automatic notification retry plus exact Main-Taey `run_command` handoff
  will close without supervisor intervention on the next consultation; output-attachment harvesting on the
  other platforms; and ISMA ingestion.
