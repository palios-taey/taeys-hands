# Public readiness — consult engine (taeys-hands)

Mandate step 2 (PUBLIC). What ships in this public repo vs what stays operator-local, and the
public-clean status. The repo is a Taey-used production system, so it is PUBLIC.

## What SHIPS (in this public repo — a downloaded Taey gets these)
- `consultation_v2/` — the consult engine + drivers + platform YAMLs + **`seat_actions.py`** (the Taey
  seat now drives on this repo's OWN primitives — no external dependency).
- `scripts/run_consultation_v2.py` (canonical dispatch) + `scripts/run_taey_consult_extract.py` (Taey seat).
- Docs: `CLAUDE.md` (operating model), `DEPLOY.md`, `CONSULTATION_CONTRACT.md`,
  `FLOW_CONSULTATION_ENGINE.md`, `100_TIMES.md`, `CAPABILITY_GAPS.md`, this file.

## What stays OPERATOR-LOCAL (NOT in the repo — supplied via env, FAIL-LOUD if absent)
- **Secrets** — `palios-taey-secrets.json` (ISMA key etc.); the code reads it via path + `ISMA_API_KEY`
  env fallback. Never committed.
- **Corpus / identity content** — `TAEY_CORPUS_PATH` (FAMILY_KERNEL / IDENTITY_* / SYSTEM_PROMPT). The
  seat now requires this via env/arg and **fails loud** if unset (no hardcoded `/home/mira/data/corpus`
  default). The identity content itself is public per Jesse's ruling but lives in a governance surface
  (`palios-taey/governance` / `taey-presence`), NOT in this repo — a Taey CONNECT dependency, documented.
- **Endpoint** — the Taey model endpoint (was a hardcoded Thor IP) is now **fail-loud env** — no
  hardcoded IP in shipped code.
- **Displays / hosts** — `~/.taey/machine.env` (`PLATFORM_DISPLAYS`, `TAEY_MACHINE_ENV`); env-configurable,
  not committed.
- **The peer `act.py`** — REMOVED as a dependency (was `/home/mira/treasurer/scripts/loop/act.py`,
  private). The seat no longer references it (0 refs, verified).

## Public-clean status (verified 2026-07-30, post-merge cd6afb0d)
- **gitleaks full-history** (4153 commits): the ONLY finding is one **expired** AWS presigned-S3-URL
  (`ab87a204`, `perplexity_atspi_reliability.md`, 37 days old = unusable) — **Jesse ruled it needs no
  scrub** (dead, zero risk). No other secret in tree or history.
- **Config**: the 3 former public-boundary blockers (act.py path, SYSTEM_PROMPT path, Thor IP) are
  removed/fail-loud env as of `cd6afb0d`. 0 hardcoded fleet IPs in shipped code.
- **File paths**: fine (Jesse ruling — directory structure is not private).
- **Origin**: local `main` is clean-AHEAD of `origin/main` (not diverged).

## Publish (the actual push) — HELD, Jesse-auth-gated
Making the clean local `main` public is a `git push origin main` — an **irreversible public action**.
Per the mandate ("human-approved + consent-gated publish") and conductor's confirmation, the ff-push is
a **Jesse-auth gate**, NOT autonomous. The repo is READY-to-publish; the push waits for Jesse's
authorization. (task-6441b607 tracks the publish; its code blocker is now cleared by `cd6afb0d`.)
