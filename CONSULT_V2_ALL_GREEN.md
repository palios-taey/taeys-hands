# Project: consult-v2-all-green - Every Chat works end-to-end + all monitors reliable
> Jesse directive 2026-06-15: do NOT stop until the consultation_v2 engine drives ALL 5 Family platforms (ChatGPT/Claude/Gemini/Grok/Perplexity) through the full 8-step flow (navigate→select model/mode→attach→prompt→send→monitor→extract→store) on real runs, AND the completion monitor works on all 5. Root cause of remaining failures = scan-before-render (premature one-shot snapshot()+find_first() before the element/menu/page rendered) — same class already fixed for grok attach (e3a4615) + perplexity attach (c7037f5) + chatgpt send-validation (16d4f67). Fix the rest with the SAME wait_until settle-poll pattern; validate each on a REAL run (production is the oracle, no tests); use the working Chats (Gemini/Grok/Perplexity) to help diagnose if stuck. Engine is production on main; primary tree on main.

## References
- Proven fix pattern: wrap element resolution in `self.runtime.wait_until(lambda: snapshot().has(key), timeout, interval)` BEFORE find_first, then fail only if still absent. See grok.py attach_files (e3a4615), perplexity.py attach_files (c7037f5).
- Live matrix (Tier-3 a95ad54, 2026-06-15): Gemini✅ Grok✅ Perplexity✅ (full e2e) | Claude❌ switch | ChatGPT❌ select_model. Memory: consult_v2_platform_validation_20260614.
- Per-platform env for a real run: `DISPLAY=:N AT_SPI_BUS_ADDRESS=$(cat /tmp/a11y_bus_:N) PYTHONPATH=. python3 -m consultation_v2.cli --platform <p> ...`; refresh bus from `xprop -display :N -root AT_SPI_BUS` if a11y connect fails; map chatgpt=:2 claude=:3 gemini=:4 grok=:5 perplexity=:6.

## Phase: p0-chatgpt - ChatGPT full e2e green [order: 1]
### Task: cg-select-model - Fix select_model 'Pro Extended not found' — scan-before-render at the model selector. Add the wait_until settle-poll before the model-selector find_first (mirror grok/perplexity attach). Validate: real chatgpt dispatch reaches send. [priority: 95] [owner: taeys-hands]
### Task: cg-send-validate - Validate the already-merged send fix (16d4f67: Stop-button confirm + temporary-chat URL) end-to-end on a real run — confirm a real turn lands (Stop appears) + response extracts. [priority: 90] [owner: taeys-hands] [depends: cg-select-model]

## Phase: p0-claude - Claude full e2e green [order: 2]
### Task: cl-switch - Fix 'Could not switch to Claude tab' — switch/focus reliability on :3 (settle/retry-scan for the window+document, refresh bus if stale). Validate switch passes on a real dispatch. [priority: 92] [owner: taeys-hands]
### Task: cl-effort - Fix effort-select 'Extra item not found' — effort radio items are under a hover-submenu ('Effort Max', trigger_type:hover); add wait_until settle after the hover before scanning the radio items. Validate: claude dispatch sets the requested effort. [priority: 88] [owner: taeys-hands] [depends: cl-switch]

## Phase: p1-engine-hardening - systematic + capture [order: 3]
### Task: eng-route-to-stamp - Stamp route_to/requester on every dispatch's pending_prompt + result so completions can't orphan (the GAIA→tutor orphan). [priority: 80] [owner: taeys-hands]
### Task: eng-chrome-capture - snapshot.py: prune Firefox chrome (menu bar / tool bar / tab bar subtree) so UNKNOWN holds only real page elements (build_snapshot scopes to app-root w/o fence ~line 178; 200-380 chrome nodes flood UNKNOWN). Preserve page menus. [priority: 78] [owner: taeys-hands]

## Phase: p2-acceptance - all-5 green gate [order: 4]
### Task: accept-5platform - Run ONE real consultation per platform (all 5) end-to-end; ACCEPTANCE = every platform completes all 8 steps + the completion monitor (stop-button-gone) fires correctly. Evidence: 5 ok=True result JSONs + extracted responses. [priority: 70] [owner: taeys-hands] [depends: cg-send-validate, cl-effort]
