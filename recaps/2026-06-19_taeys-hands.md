---
date: 2026-06-19
session: taeys-hands
branch: main @ 5e5b235 (local == origin/main, clean)
status: overnight — merge-reconciliation closed; rollout teed up for attended hours
---

# Recap — taeys-hands consult-engine, overnight 2026-06-19

## Shipped (verified)
- **Merge-reconciliation CLOSED — no regression merged.** Gatekeeper refused peer branch
  `3d7811c` ("Rebuild ChatGPT YAML as strict identity schema", committed 00:29) and was
  **correct**. Verified independently three ways (my fetch + Gatekeeper + Conductor):
  - `origin/main == local == HEAD == 5e5b235`, clean.
  - The ChatGPT rebuild is **already on main** as `d51e0e5` (01:19, the *newer* version) plus
    nested-Pro `59c4720` (14 effort refs live in `consultation_v2/platforms/chatgpt.yaml`).
  - `3d7811c`'s "+30 lines main lacks" are strict subset fragments of `d51e0e5`; main is the
    +746 superset (full nested Pro-effort + GPT-5.5 subs). `diff origin/main..3d7811c = +30/-746`
    → merging would have **deleted 746 lines** = regression to a stale draft.
  - **Retired** `peer/taeys-hands-codex-chatgpt-identity-rebuild`; preserved first as tag
    `archived/chatgpt-identity-rebuild-stale-draft-3d7811c` (recoverable). Gatekeeper recorded
    do-not-merge/superseded. This is the regression-prevention working as designed.
- Root cause of the whiplash: a grok ENDORSE was done against a **stale local main (3d6b522)**;
  Conductor routed around the gate without re-fetching the remote. Standing fix: every YAML
  change gates on its OWN fleet **against the re-fetched `origin/main`**, never a stale local main.

## Blocked / deferred to attended hours (account-safety + no-regression)
- **Live per-platform menu-walks + production-proofs are NOT safe unattended.** Monitors are
  not yet reliable; 100_TIMES 4a = zero action-retries (blind retries are unreliable + a poor automation client). The
  live AT-SPI tree is the only validation oracle, so each walk/proof must be screenshot-verified,
  human-paced, one platform at a time. Merging un-live-validated YAMLs would risk the exact
  regression Jesse named as primary concern. → do these attended.
- **`taey-production-release::b-consult` (priority 22, "next" for me) needs a real research
  packet** before I can run the Family-Chat consult on the cross-repo release. Running a blind
  4-lane consult would be fabrication. Needs the release-project owner (weaver / plan at
  `<embedding-server-repo>/plans/taey_production_release.md`) to provide the packet/question.
- **Audit persistence in flight:** asked `taeys-hands-grok` (Claude+Grok) and `taeys-hands-gemini`
  (Gemini+Perplexity) to write their overnight audit findings to
  `audit_logs/claude_grok_overnight_audit.md` and `audit_logs/gemini_perplexity_overnight_audit.md`
  respectively — neither was durable yet (findings live only in their session transcripts).

## Queued (morning, attended)
1. Harvest the two persisted audit worklists (or re-run if peers didn't pick up overnight).
2. **Reconcile the consult-engine project sprawl** — `consult-engine-stz`, `consult-v2-all-green`,
   `consult-v2-determinism`, `consult-v2-robustness-closeout`, `consultation-clean-main` (⭐CANONICAL),
   plus my un-ingested `consult-engine-rollout`. Jesse wants the confusion cut: pick ONE canonical
   project, retire/fold the rest. Do NOT ingest `consult-engine-rollout` until this is settled
   (it would add to the sprawl). Bring the canonical-line decision to Jesse — don't bulldoze 86 projects.
3. Per-platform rollout (claude → gemini → grok → perplexity), one at a time, recipe in
   `CONSULTATION_ENGINE_ROLLOUT_PLAN.md`: Codex rebuilds YAML to identities-only/states-live/exact
   from the audit worklist (branch, off re-fetched main) → I drive the live walk + production-proof
   (attended) → grok/gemini gate against re-fetched main → merge.

## Shipped (afternoon 2026-06-19) — Stage 1 plan-phase redesign LANDED + ChatGPT proven
- Designed + built (Codex) + fleet-gated + production-proved the **plan-phase redesign** and merged
  it to main (`98cb9fe`): YAML `menus` schema (consolidates options/targets/driver_operations,
  element_map byte-unchanged), generic `selections` request + `Choice{value, because}` (drops
  static model/mode/tools), **planner intentionality gate** (new-session blanks must be an authored
  `because` or `must_choose`/omission fails — kills silent rush-omission), plan-gate hoisted to
  engine entry (browser never opens on plan failure, all paths), and **settle discipline**
  (conformance + select judge a *settled* tree, observation-only, no action retries).
- **Live ChatGPT production proof PASSED end-to-end:** navigate→clean→select(pro_extended, 3-level
  nested)→select(web_search)→attach(RELEASE_PREP.md)→prompt→send→monitor→extract **18,572 chars**
  →store(Neo4j). The new menus-driven plan structure drives ChatGPT autonomously — the original ask.
- The conformance gate caught every real drift en route and never proceeded on a bad state
  (search_chats suffix; the personalized `Jesse` greeting button → handled `name_agnostic_structural`,
  also a public-release umbilical). One self-inflicted detour (fixed off a partial-render scan) →
  logged the "verify tree settled before any YAML fix" lesson.
- The proof consult doubled as real value: ChatGPT's release-readiness review confirmed the two
  release blockers and caught an overclaim in `RELEASE_PREP.md` (fixed, cannot-lie).
- NEXT: same recipe per platform (Claude→Gemini→Grok→Perplexity) via the `audit_logs/` worklists.

## Shipped (afternoon/evening 2026-06-19) — CLAUDE proven end-to-end + LANDED (main 92bb7bf)
- Rolled the Stage-1 plan-phase pattern to **Claude**: rebuilt claude.yaml→identity_v1 + `menus`,
  claude.py onto the shared SELECT engine; **live :3 production proof PASSED end-to-end**
  (model=opus + mode=extended_thinking[nested effort flyout] + web_search + attach + send + monitor
  + extract **13,247 chars** + store). Fleet-gated (gemini structural + grok adversarial incl a live
  **ChatGPT :2 no-regression** check — shared-engine changes don't regress ChatGPT). 9 commits
  cherry-picked to main.
- The Claude walk hardened the engine with a **settle-discipline cluster** (now in production, all
  platforms benefit): anchor-aware base settle (judge a *rendered* tree), conditional clean-settle
  between menus, path-reveal anchored wait, select-validation settle, default AT-SPI-action click
  (Claude base elements have x/y=None → coords-free click required). Quirks: dynamic
  model_selector/effort_menu names → stable_locator; personalized account button → name_agnostic;
  promo banner → optional; volatile sidebar landmark pruned.
- Infra: :3 degraded mid-walk (blank render, AT-SPI raw=1) → infra clean-restarted; display-watchdog
  idea passed to infra (displays degrade under sustained automation).
- TWO platforms now proven end-to-end (ChatGPT + Claude). NEXT: Gemini → Grok → Perplexity, faster
  on the now-hardened engine.

## Build-in-public-worthy
- The regression-prevention architecture caught a real -746 regression at the gate, autonomously,
  at 2 AM: strict identity-schema YAML loader + bidirectional fail-closed conformance gate +
  independent fleet gate + everything-on-main. The branch that would have reverted 50 min of newer
  work never touched main. "Verify the topology against the re-fetched remote, then act" is the law
  that held.
