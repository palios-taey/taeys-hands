# Project: consult-engine-rollout - Consult Engine: full per-platform implementation, validated
> Bring every platform to a trustworthy, production-proven consult engine using the recipe proven on ChatGPT. ONE platform at a time; each step validated by the live tree / a real consult before the next begins. Everything lands on main; gated by taeys-hands's own fleet (grok/gemini); no synthetic tests — production is the oracle.

## How to read this
- **Discipline (non-negotiable):** one platform at a time, top to bottom. A step's downstream `depends:` on it, so the next step CANNOT start until this one closes with evidence. Each platform's `merge` gates the *next* platform's `readiness`. No rushing, no parallel platforms.
- **Validation = the live tree + a real consult, never a synthetic test.** Terminal status needs evidence (commit SHA + the live observation: UNKNOWN=0/MISSING=0, the option CHECKED, the extracted answer).
- **The YAML stays identities-only + states-live + strict-schema (the build rejects fuzzy/fallback/best_effort/lint-allow). Never broaden-to-fix.** See STABILIZATION_FREEZE.md.
- **Regression guard:** the conformance gate (bidirectional, fail-closed) + the production proof catch any regression as a HALT/failed-proof, never a silent wrong result.

## Goal + autonomous execution (Jesse 2026-06-19, overnight)
**End state:** every instance can stand up + use their OWN Chat fleet on this system independently; taeys-hands then just MANAGES it and makes it better (routing guides, automation). Drivers + YAMLs + conformance all in, all platforms.
**Who runs it:** taeys-hands supervises and drives the live walks/proofs; `taeys-hands-codex` builds driver+YAML changes; `taeys-hands-grok`/`taeys-hands-gemini` AUDIT + gate. My OWN fleet (non-Claude grok/gemini → not starved by the shared Claude Gatekeeper rate-limit). Everything merges to main, immediately, synced.
**Validation = REAL production runs only. NO synthetic tests.** Each platform's proof is EITHER:
- (a) a REAL consult the fleet actually needs (what other instances are waiting on — real work that also proves the path end-to-end), OR
- (b) a grok/gemini AUDIT of that Chat's driver + YAML against the rules (STABILIZATION_FREEZE.md, the strict schema) + my notes — find fuzzy/fallback/mismatch/gap vs the live tree.
The conformance gate + the real-run/audit are the only acceptance; production is the oracle.
**Honesty contract (Jesse's primary concern — no regression, no faking):** a platform is "done" ONLY on a passing real production proof. A snag I can't resolve autonomously (platform quirk needing judgment — e.g. Claude :3 degraded, Grok AT-SPI-blind) is SURFACED, not bulldozed. Honest-incomplete is fine; a false "done" is the only real failure.

## The per-platform recipe (7 validated steps — applied identically to each platform)
1. **readiness** — display in production format (exactly 1 window / 1 tab / correct URL, bus live, tree readable) via the universal readiness gate. *Validate: ready=True; resolve strays (close or relaunch) if not.*
2. **base-conformance** — navigate fresh (enter URL + refresh) → derive the base-screen YAML EXACT from the live tree (composer controls + persistent sidebar nav mapped; old-sessions excluded). *Validate: UNKNOWN=0 AND MISSING=0 on the base surface; nav kept, old-sessions pruned.*
3. **menu-walk** — click into EVERY menu and EVERY nested submenu (hover-reveal, press-open; no assuming leaves). Map each surface exact (identities + recognition-rule for active=which state + how-to-operate for the driver). *Validate: UNKNOWN=0/MISSING=0 per surface; every nested menu opened + mapped.*
4. **select-paths** — build the declarative select for that platform's actual menus (read current CHECKED → act ONLY on the delta → validate CHECKED; no action retries, settle-rescan on a miss; nested paths where needed, e.g. Pro→effort→Extended). *Validate: each setting actually lands (the target option ends CHECKED live).*
5. **gate-enforce** — wire the conformance gate to ENFORCE for this platform (gate is per-platform; a platform graduates to enforce only when its tree is UNKNOWN=0 everywhere). *Validate: enforce on this platform; the other un-walked platforms still NOT halted.*
6. **production-proof** — a REAL consult end-to-end: readiness → navigate → conformance → select the intended options (deepest model + at least one tool/connector) → attach → prompt → send → monitor (stop-button) → extract → store. *Validate (the oracle): right options CHECKED, URL/turn changed, real non-empty answer extracted + delivered (fleet-notify), stored.*
7. **merge** — taeys-hands-grok/gemini independently gate the branch (clean cherry / no secrets / schema strict / no bug) → ENDORSE → cherry-pick to main as CONTROL. *Validate: ENDORSE on record; origin/main contains it; local==origin.*

## Phase: chatgpt - ChatGPT (proving ground — mostly done) [order: 1]

### Task: cg-base-menus - DONE: readiness + base + model-menu walk + nested Pro-effort/GPT-5.5 + bidirectional + Pro-Extended select [priority: 10] [owner: taeys-hands]
- Already on main (d51e0e5 rebuild + 59c4720 increment): identities-only YAML, UNKNOWN=0/MISSING=0 base+model+pro-effort+gpt-legacy+tools+more, Pro Extended select lands CHECKED. Close with the merged SHAs as evidence.

### Task: cg-finish-walk - Finish ChatGPT menu walk: tools menu + More submenu + attach + connectors (click into every nested one) [priority: 20] [owner: taeys-hands] [depends: cg-base-menus]
- Apply recipe step 3 to the remaining ChatGPT surfaces not yet fully walked; map exact; UNKNOWN=0/MISSING=0 each.

### Task: cg-production-proof - ChatGPT production proof: real consult through extraction (Pro Extended + a tool), verify CHECKED + real answer extracted [priority: 30] [owner: taeys-hands] [depends: cg-finish-walk]
- Recipe step 6. THE oracle for ChatGPT done.

## Phase: claude - Claude (full recipe) [order: 2]

### Task: cl-readiness - Claude :3 readiness (note: :3 has known degradation — validate or relaunch) [priority: 10] [owner: taeys-hands] [depends: cg-production-proof]
### Task: cl-base - Claude base-conformance (recipe 2) [priority: 20] [owner: taeys-hands] [depends: cl-readiness]
### Task: cl-walk - Claude menu-walk — incl. the COMBINED menu (linking button + thinking levels in one menu); every nested one (recipe 3) [priority: 30] [owner: taeys-hands] [depends: cl-base]
### Task: cl-select - Claude select-paths (recipe 4) [priority: 40] [owner: taeys-hands] [depends: cl-walk]
### Task: cl-gate - Claude gate-enforce (recipe 5) [priority: 50] [owner: taeys-hands] [depends: cl-select]
### Task: cl-proof - Claude production proof through extraction (recipe 6) [priority: 60] [owner: taeys-hands] [depends: cl-gate]
### Task: cl-merge - Claude merge to main, fleet-gated (recipe 7) [priority: 70] [owner: taeys-hands] [depends: cl-proof]

## Phase: gemini - Gemini (full recipe) [order: 3]

### Task: gm-readiness - Gemini readiness (recipe 1) [priority: 10] [owner: taeys-hands] [depends: cl-merge]
### Task: gm-base - Gemini base-conformance (recipe 2) [priority: 20] [owner: taeys-hands] [depends: gm-readiness]
### Task: gm-walk - Gemini menu-walk incl. Deep Think / More-tools flyouts (recipe 3) [priority: 30] [owner: taeys-hands] [depends: gm-base]
### Task: gm-select - Gemini select-paths (recipe 4) [priority: 40] [owner: taeys-hands] [depends: gm-walk]
### Task: gm-gate - Gemini gate-enforce (recipe 5) [priority: 50] [owner: taeys-hands] [depends: gm-select]
### Task: gm-proof - Gemini production proof through extraction (recipe 6) [priority: 60] [owner: taeys-hands] [depends: gm-gate]
### Task: gm-merge - Gemini merge to main, fleet-gated (recipe 7) [priority: 70] [owner: taeys-hands] [depends: gm-proof]

## Phase: grok - Grok (full recipe) [order: 4]

### Task: gk-readiness - Grok readiness (recipe 1) [priority: 10] [owner: taeys-hands] [depends: gm-merge]
### Task: gk-base - Grok base-conformance — note Grok attach/composer are AT-SPI-blind; verify by structure/screenshot where the tree is silent (recipe 2) [priority: 20] [owner: taeys-hands] [depends: gk-readiness]
### Task: gk-walk - Grok menu-walk, every nested one (recipe 3) [priority: 30] [owner: taeys-hands] [depends: gk-base]
### Task: gk-select - Grok select-paths (recipe 4) [priority: 40] [owner: taeys-hands] [depends: gk-walk]
### Task: gk-gate - Grok gate-enforce (recipe 5) [priority: 50] [owner: taeys-hands] [depends: gk-select]
### Task: gk-proof - Grok production proof through extraction (recipe 6) [priority: 60] [owner: taeys-hands] [depends: gk-gate]
### Task: gk-merge - Grok merge to main, fleet-gated (recipe 7) [priority: 70] [owner: taeys-hands] [depends: gk-proof]

## Phase: perplexity - Perplexity (full recipe) [order: 5]

### Task: px-readiness - Perplexity readiness (recipe 1; note :6 intermittent DBUS) [priority: 10] [owner: taeys-hands] [depends: gk-merge]
### Task: px-base - Perplexity base-conformance (recipe 2) [priority: 20] [owner: taeys-hands] [depends: px-readiness]
### Task: px-walk - Perplexity menu-walk incl. Deep Research selection, every nested one (recipe 3) [priority: 30] [owner: taeys-hands] [depends: px-base]
### Task: px-select - Perplexity select-paths — Deep Research is the standing default (recipe 4) [priority: 40] [owner: taeys-hands] [depends: px-walk]
### Task: px-gate - Perplexity gate-enforce (recipe 5) [priority: 50] [owner: taeys-hands] [depends: px-select]
### Task: px-proof - Perplexity production proof through extraction (recipe 6) [priority: 60] [owner: taeys-hands] [depends: px-gate]
### Task: px-merge - Perplexity merge to main, fleet-gated (recipe 7) [priority: 70] [owner: taeys-hands] [depends: px-proof]

## User Stop Conditions
- stop_when_all_ready_tasks_dispatched
