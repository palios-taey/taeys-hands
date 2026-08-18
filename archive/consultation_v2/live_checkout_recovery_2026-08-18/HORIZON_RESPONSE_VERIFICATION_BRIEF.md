# Verification brief — provenance-back a response to ChatGPT (Horizon) re: the cross-repo split-brain seam

Jesse-directed 2026-08-14. READ-ONLY. No code changes. Goal: every claim in the response to Horizon
carries a git/file:line/live receipt, labelled Observed / Inferred / Unknown. Report to taeys-hands.

## Already CONFIRMED by taeys-hands (build on, do not re-derive)
- taeys-hands tip = 6e1446cd. `consultation_v2/drive_chat_adapter.py` extract() returns
  `{response_text, artifacts, steps, ...}` (lines 10-15) — NOT an AT-SPI element. Observed.
- taey-presence/main = 3370aa4b; its `serving/ui_drive.py` exposes NO scroll/attach/extract. Observed.
- Production runs from branch `infra/verify-attachment` (HEAD 72ab62d0) = PR #102 (OPEN, base main,
  title "ui_drive: verify-attachment — reuse the engine's proven chip rule"). Observed.
- PR #102 `serving/ui_drive.py` _extract: `target = drive_chat_adapter.extract(platform)` then reads
  target.name/role/x/y/atspi_obj + scroll_element_into_view + click. CONTRACT MISMATCH (extract()
  already returns the completed result; those keys do not exist). Observed (ui_drive.py ~321-334).
- soma_proxy `text_file` paste (exact bytes) supported (soma_proxy.py:872). Observed.
- passive completion monitor exists (`scripts/consult_completion_monitor.py`), @2 active. Observed.
- Dashboard URL is :5001 (soma_proxy.py:68 MIRA_DASHBOARD_URL default 127.0.0.1:5001). Proxy binds
  0.0.0.0:8766 (soma_proxy.py:2913). Observed.

## GAPS to verify (needed for cannot-lie)
1. Does soma_proxy REFUSE generated inline pastes over ~800 chars? Find the exact threshold + line, or
   report it does NOT exist (I did not find "800" in soma_proxy.py).
2. Does the DASHBOARD service itself bind 0.0.0.0:5001 (not just the URL)? Find the bind line + file.
3. Full PR #102 diff: enumerate EVERYTHING it bundles (grammar migration to element keys, attachment
   verify, composer verify, prompt changes, display watchdog, adapter wiring). Confirm it is a mixed
   change (one seam repair + several new authorities), per the response's "reject as-is" claim.
4. Is the proposed two-file connector patch (ui_drive.py add scroll/attach/extract delegating to the
   adapter; soma_proxy expose them; extract returns response_text, NEVER click the return) correct and
   sufficient, touching NO platform driver or YAML? Confirm feasibility from the current code.

## Adversarial pass (grok)
Try to BREAK the response's diagnosis: is "split-brain seam" accurate or overstated? Is the contract
mismatch real or a misread? Are the freeze commits (taeys-hands 6e1446cd, taey-presence 3370aa4b)
the correct tips? Is anything in the response factually wrong? Cite receipts.
