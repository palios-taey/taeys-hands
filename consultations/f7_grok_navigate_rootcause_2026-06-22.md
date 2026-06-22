# f7 — Grok @navigate failure on a stale /c/ thread — ROOT-CAUSE diagnosis (route to codex)

**Owner of diagnosis:** taeys-hands (f7-nav-diagnose). **Builder:** taeys-hands-codex. **Gate:** my-fleet r5 + production-validate. **Date:** 2026-06-22.

## Symptom
Grok consult aborts at step 1 `navigate` with `success=False` ("Navigated to Grok target"), before attach/send. Observed in the weaver2 isma-claims-validation run (`/tmp/weaver2_grok.json`).

## Evidence (live, conclusive)
- The driver navigated to `target_url = https://grok.com/` (YAML `urls.fresh`).
- Actual post-nav URL captured in the navigate evidence: `https://grok.com/c/9b26ef16-b85d-4035-bd84-289bae8c79bc?rid=…` — i.e. **grok's SPA restored the last-active conversation thread** ("ISMA-Core Claims Validation Complete", visible at the top of History and as the rendered main-area content).
- The page was otherwise **fully ready**: snapshot shows `input` ("Ask Grok anything", `editable,focusable,enabled`), `attach_trigger` ("Attach", enabled), `model_selector`, `history` — composer usable.
- `consultation_v2/runtime.py:686-700` `navigate(verify_change=True)` then correctly returned `False`: the bare-domain target `grok.com` has no path, and the landed URL `…/c/<thread>` is rejected by design — comment: *"a /c/<thread> URL shares the domain prefix but is NOT the home target … return False so the driver STOPs instead of sending into a polluted composer. Single check — no retry."*

## Root cause (this is NOT a false-negative of a healthy check)
The verify is **doing its job**. The defect is **upstream of it**: navigating to `urls.fresh = https://grok.com/` for a **new** session does **not deterministically open a fresh chat** — grok restores the last-active `/c/<thread>`. If the engine proceeded, the consult's attach+send would land **inside that stale, unrelated thread** (contamination). The verify exists precisely to prevent that, so it fired.

So: `grok @navigate` is a **correct STOP on a wrong navigation target/mechanism**, not a check bug.

## Do NOT patch by relaxing verify
Accepting `/c/<thread>` as a valid new-session landing (e.g. prefix-matching the bare domain, or dropping `verify_navigation`) would **reintroduce the contamination bug** — sending a fresh consult into a prior conversation. That is a banned patch (adds tolerance for the broken state instead of correcting it).

## Root-cause fix shape (codex — simplifies + corrects; for `request.session_url is None` only)
New-session grok navigation must **explicitly start a new chat**, then validate readiness on a **stable element**, not on bare-root URL equality:

1. **Map grok's new-chat affordance** in `consultation_v2/platforms/grok.yaml` `element_map` (exact AT-SPI name+role from the live tree — both are present):
   - sidebar link `name: "New Chat"` / `"New conversation"` (role `link`), and/or
   - the keyboard shortcut grok advertises: **`Ctrl+J`** ("New Chat Ctrl+J" appears in the chrome text). Prefer the mapped element + `do_action` over a keystroke if the link resolves reliably (elements-not-coords).
2. **New-session navigate** = navigate to `urls.fresh` → if the landed URL is a restored `/c/<thread>` (or unconditionally, to be deterministic), trigger the mapped new-chat affordance → `wait_for_page_ready_after_navigation`.
3. **Readiness validation** = the composer is fresh: `input` ("Ask Grok anything") present+editable+**empty** AND no prior assistant/answer content in the document tree (a fresh chat, not a restored thread). This replaces the brittle bare-domain-exact-URL match for the new-session path. Per the determinism contract, readiness is keyed on a **stable element**, never an intrinsically-dynamic SPA URL.
4. **Leave the follow-up path unchanged:** when `request.session_url` is a specific `/c/<thread>` (has a real path), the existing `runtime.py` prefix-match already validates correctly — do not touch it.

(Optional for codex to evaluate during IMPROVE: probe whether grok exposes a canonical fresh-chat URL — e.g. a `?` / path variant — that lands fresh without the affordance click. If one exists and is stable, it's even simpler. If not, the affordance path above is the deterministic choice.)

## Files
- `consultation_v2/drivers/grok.py:82-94` — `navigate()` (new-session branch is where the new-chat affordance + composer-readiness goes)
- `consultation_v2/runtime.py:647-700` — `navigate(verify_change)` (correct as-is; do NOT relax)
- `consultation_v2/platforms/grok.yaml` — `urls`, `element_map` (add the new-chat affordance + composer-empty readiness spec)

## Validation bar (production, taeys-hands)
A real grok new-session consult, dispatched while `:5` is sitting on a prior `/c/<thread>`, lands on a **fresh** chat (empty composer, no restored content), attaches+sends, and the response is NOT appended to the old thread. Zero manual intervention. my-fleet r5 + merge.
