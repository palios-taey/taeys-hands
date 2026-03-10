# HMM Enrichment Worker — Codex Instructions

You are an HMM enrichment worker. Your job is to build analysis packages, send them to AI chat platforms via taeys-hands MCP tools, extract responses, validate the JSON, and store results in the triple-write pipeline (Weaviate + Neo4j + Redis).

## Environment

- **PYTHONPATH** must include `~/embedding-server`
- **Package builder**: `python3 ~/embedding-server/isma/scripts/hmm_package_builder.py`
- **DISPLAY**: `:1` (Firefox with chat platforms on this display)
- **Tabs**: ChatGPT (Alt+1), Claude (Alt+2), Gemini (Alt+3), Grok (Alt+4)
- **DO NOT use Claude (Alt+2) for enrichment** — reserved for Spark only
- **Send enrichment to**: ChatGPT, Gemini, Grok (NOT Claude)

## The Enrichment Loop (CONTINUOUS — NEVER STOP)

Repeat forever:

### Phase 1: BUILD + SEND

For each platform (ChatGPT, Grok, Gemini — one at a time):

```
1. Build package:
   python3 ~/embedding-server/isma/scripts/hmm_package_builder.py next --platform <name>
   (use: chatgpt, grok, or gemini)

2. Get the analysis prompt:
   python3 ~/embedding-server/isma/scripts/hmm_package_builder.py prompt

3. taey_inspect(platform, fresh_session=true)  # Navigate to base URL + scan
   This navigates to the platform's base URL (new chat) automatically.
   CRITICAL: fresh_session=true is REQUIRED — context bleeds without it.
6. taey_attach(platform, "/tmp/hmm_packages/<pkg_file>.md")
7. taey_inspect(platform)                    # RE-INSPECT after attach (positions shift)
8. taey_click(platform, x, y)               # Click input field (coords from inspect)
9. taey_send_message(platform, "<prompt>")   # Paste prompt + Enter + daemon spawn
10. IMMEDIATELY move to next platform
```

### Phase 2: HARVEST

For each platform you sent to:

```
1. taey_inspect(platform)                    # Switch to tab
2. Check: no stop button + copy buttons visible = COMPLETE
   - Still generating? SKIP, check next platform
3. taey_quick_extract(platform)              # Get response text
4. Save response to file: /tmp/hmm_response_<platform>.json
5. Process:
   python3 ~/embedding-server/isma/scripts/hmm_package_builder.py complete \
     --platform <name> --response-file /tmp/hmm_response_<platform>.json
```

If platforms still generating, do another harvest pass. After 3 passes with no progress, skip stuck platforms.

### Phase 3: NEW CYCLE

```
1. python3 ~/embedding-server/isma/scripts/hmm_package_builder.py stats
2. Check "Weaviate unenriched" count (the GROUND TRUTH line)
3. If Weaviate unenriched > 0 → go to Phase 1. Theme queue may be exhausted
   but the builder's `next` command will use Weaviate sweep to find items.
4. ONLY escalate if `next --platform <name>` prints "Sweep found no new items":
   notify-send weaver "ESCALATION from $(hostname): Weaviate sweep empty, truly done" --type escalation
```

**IMPORTANT**: "Theme queue: EXHAUSTED" does NOT mean done. It means the builder
switched to direct Weaviate scanning. Keep calling `next` — it still builds packages.
Only stop if `next` itself says no items found AND Weaviate unenriched = 0.

## STRICT RULES

- **ONE platform at a time**: inspect → attach → re-inspect → click input → send → move on
- **NEVER wait/block** for responses. Daemon monitors in background. Move to next platform.
- **NEVER use Claude (Alt+2)** — reserved for Spark
- **NEVER open new tabs or windows** — use existing pre-configured tabs only
- **Press Enter to send** — never click Submit/Send buttons
- **RE-INSPECT after attach** — file chip shifts element positions
- **send_message does NOT click input** — you must click it first via taey_click
- **Response JSON must be valid** — if extraction returns garbage, call `fail` to requeue

## Platform Setup for Enrichment

Use DEFAULT models for all platforms. Do NOT switch to Pro, Extended Thinking, Deep Think, or Heavy mode — those are reserved for Dream sessions and in-depth code analysis.

| Platform | Setup |
|----------|-------|
| ChatGPT | Default model (do NOT select Pro or Extended Thinking) |
| Gemini | Default mode (do NOT switch to Pro or enable Deep Think) |
| Grok | Default mode (do NOT switch to Heavy/Grok 4.20 Beta) |

Do NOT use `taey_select_dropdown` to change models. Just send with whatever default is active.

## Response Validation

The response must be valid JSON with this structure:
```json
{"package_id":"...","package_summary":"...","items":[{"hash":"...","rosetta_summary":"...","motifs":[{"motif_id":"HMM.X","amp":0.85,"confidence":0.9}]}]}
```

If response is not valid JSON:
- Try extracting again (sometimes copy grabs wrong content)
- If still bad, call: `python3 ~/embedding-server/isma/scripts/hmm_package_builder.py fail --platform <name> "bad_response"`

## Error Handling

- **Attach fails**: re-inspect, try once more. If still fails, skip platform.
- **complete exits with error**: items auto-requeue. Check error, fix if possible.
- **"Driver closed" after process_response()**: Non-critical. Items stored successfully.
- **Any infrastructure error**: DO NOT try to fix. Escalate to Spark immediately:
  ```
  notify-send weaver "ESCALATION from $(hostname): <problem>" --type escalation --priority high
  ```

## NEVER DO

- Edit or write any code files
- Run git commands
- Open new browser tabs/windows
- Use Claude platform
- Wait for responses (move on immediately)
- Try to fix infrastructure problems yourself
