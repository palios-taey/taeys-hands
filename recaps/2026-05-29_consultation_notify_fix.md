## 2026-05-29 Consultation Notify Fix

### Scope

- Repo: `<OPERATOR_HOME>/taeys-hands`
- File changed: `scripts/consultation.py`
- Defect: synchronous consultation extraction saved `/tmp/...response.md` but never notified the requester that the file had landed.

### Root Cause

- Observed: `scripts/consultation.py` completed extraction, wrote the response file, and returned success.
- Observed: there was no post-save `taey-notify` step in the success path.
- Inferred: requesters could block indefinitely waiting for inbox delivery even though the response file already existed on disk.

### Change

- Added `--requester` to `scripts/consultation.py`.
- Added requester resolution from explicit arg first, then caller session env / tmux session name.
- Added fail-loud behavior when no requester can be resolved.
- Added immediate `taey-notify ... --type response_ready --from taeys-hands` after the response file is written.
- Added fail-loud behavior if `taey-notify` itself fails.

### Syntax Verification

- Observed: `python3 -m py_compile <OPERATOR_HOME>/taeys-hands/scripts/consultation.py` passed.

### Production Verification

Real consultation run:

```bash
python3 <OPERATOR_HOME>/taeys-hands/scripts/consultation.py \
  --platform gemini \
  --message "Reply with exactly NOTIFYFIX-20260529 and nothing else." \
  --requester conductor-codex \
  --output /tmp/family_audit_gemini_response.md \
  --timeout 600 \
  --no-neo4j \
  --no-isma
```

Observed consultation log:

- `21:42:27` `Step 7: Waiting for response...`
- `21:42:39` `Response complete (10s)`
- `21:42:44` `Response saved to /tmp/family_audit_gemini_response.md (18 chars)`
- `21:42:44` `Step 9a: Notifying requester`
- `21:42:44` `Requester notified: OK: sent to conductor-codex [response_ready] from taeys-hands`

Observed output file:

- Path: `/tmp/family_audit_gemini_response.md`
- Size: `18 bytes`
- Content:

```text
NOTIFYFIX-20260529
```

Observed script result JSON:

```json
{
  "platform": "gemini",
  "success": true,
  "requester": "conductor-codex",
  "output_path": "/tmp/family_audit_gemini_response.md",
  "content_length": 18,
  "requester_notified": true
}
```

Observed requester-side delivery:

- During verification, the fleet notification surfaced:

```text
[RESPONSE_READY from taeys-hands]: Family Chat consultation response from GEMINI landed at /tmp/family_audit_gemini_response.md (18 bytes). Review + acknowledge.
```

- Observed `redis-cli LLEN taey:conductor-codex:inbox` was `0` both before and after manual inspection because the inbox hook consumed the message immediately after delivery.
- Inferred from the surfaced notification plus the script log that the notify gap is closed end-to-end.

### Verdict

- PASS: response files still land on disk.
- PASS: requester notification now fires immediately on the same success path.
- PASS: no silent save-without-notify behavior remained in the verified synchronous consultation flow.
