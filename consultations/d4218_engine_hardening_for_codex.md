# Consult-engine hardening — 3 reliability defects (root-cause, for codex)

**Builder:** taeys-hands-codex. **Gate:** taeys-hands production-validate on live displays + contract lint + integrity gate (all must pass; merge only after a real production run). **Date:** 2026-06-22.
**Discovered driving the live #4218 Family audit (real consults, isolated displays).** All three below are root-cause shapes that should SIMPLIFY the broken path, not add a bypass. Follow THE RULE (exact AT-SPI match, YAML drives driver, no fallbacks/broadening).

---

## Defect 1 — Grok navigate HALTS on `fresh_chat_required` instead of starting fresh

**Observed (live :5):** A fresh-session Grok dispatch fails at `navigate` with `success=False`, evidence `{"fresh_chat_required": true, "target_url": ..., "verify_change": ...}`. Grok's SPA had RESTORED a prior conversation ("Audit Verdict: PROCEED") with a leftover composer attachment — the mapped tree carried `new_chat`, `remove_attachment` (`"Open attachment Remove this attachment"`), `input`, `model_selector`. So the page was a stale restored chat, not a fresh one, and navigate correctly detected it but then only HALTED.

**Manual recovery that worked (proves the fix):** clicking the mapped `new_chat` element (`[link] "New Chat"`) via `Atspi.Action.do_action(0)` cleared the stale chat to a fresh `SuperGrok HEAVY` empty composer (single tab, no `remove_attachment`). Re-dispatch then passed navigate+selection and generated.

**Root-cause fix:** in the Grok navigate path, when `fresh_chat_required` is detected (SPA restored a stale session — `remove_attachment` present and/or URL is an existing chat), click the mapped `new_chat` element (do_action) to start a fresh chat, then assert a clean precondition before proceeding: composer `input` present AND `remove_attachment` ABSENT AND exactly one tab. Only HALT+notify if `new_chat` is itself missing or the post-click state still isn't clean (true drift). This is the "few clicks" — `new_chat` is already mapped; the navigate just needs to USE it instead of giving up. No new fallback chain — one deterministic clean-start action keyed off the existing `fresh_chat_required` signal.

## Defect 2 — Claude `tools=research` select cannot settle behind the Gmail connector picker

**Observed (live :3):** `--select tools=research` → flow runs navigate✓ attach✓(both files) model=opus✓ mode=max✓, then `select` fails: `"claude selection base did not settle on anchor input"`. Tree at failure shows the Gmail connector picker open (`[list item] "From Gmail"` + `[push button] "From Gmail"`) AND the Firefox address bar leaking in (`[entry] "Search with Google or enter address"`). The Research tool opens the connector/permission picker; the base-conformance settle then can't get a unique match on the composer `input` anchor.

**Important scope:** `tools=web_search` does NOT trigger this — Claude Max + `tools=web_search` ran clean end-to-end (web access and Research are DIFFERENT tools). So this defect is specific to the Research connector flow.

**Root-cause fix:** two parts, both deterministic —
1. After a tool toggle that opens the connector picker, handle it as a MAPPED state (dismiss/confirm the connector modal — extend the existing connector-modal handling `d431a1a7` from the monitor phase to the SELECT phase) before the base-anchor settle scan, so the composer `input` is the unique match.
2. Post-navigate, ensure the Firefox awesome-bar/address-bar is dismissed (Escape) so `"Search with Google or enter address"` never appears in `select` snapshots and can't be mis-matched as the anchor. (This address-bar leak is the same one flagged in the earlier Claude navigate doc; it must not survive into select.)

## Defect 3 — `web_search` should be DEFAULT-ON for Claude + ChatGPT (Jesse directive)

**Directive (Jesse 2026-06-22):** "There is web access and Research which are 2 different things. They should always have web enabled." Web access (`tools=web_search`) is a standing default, not a per-call flag.

**Fix:** make `web_search` a default-on tool in `claude.yaml` and `chatgpt.yaml` selection workflow, so a caller who passes no `tools` still gets web enabled (Research stays opt-in). Keep it overridable. **CONFIRM the exact default shape with Jesse/taeys-hands before merge** — this changes default behavior for every consult.

---

## Validation bar (production, taeys-hands gates)
Per defect, a REAL consult on the live display, hands-off, full extract:
- Grok: fresh dispatch when :5 is sitting on a stale restored chat → navigate auto-starts fresh → attaches → sends → extracts. No manual New Chat needed.
- Claude Research: `--select tools=research` → connector picker handled → settles → sends → extracts hands-off.
- web default: a consult with NO `--select tools` → web_search confirmed active in the live UI (screenshot the pill).
Plus: `lint_consultation_v2_contract.py --all` + `lint_no_yaml_silent_fallbacks.py --all` CLEAN, and `gitnexus_impact` before editing each driver/yaml. Root-cause shapes only — no `if X: continue` bypasses.
