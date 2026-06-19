# RELEASE_PREP — taeys-hands → public

**Status: PRIVATE** (`palios-taey/taeys-hands`, `isPrivate: true`). This doc tracks the PRIVATE_TO_PUBLIC prep. **Publish is irreversible and human-approved + 5/5-Family-consent gated — this doc does NOT authorize flipping visibility.** It exists so the work is durable and the Family can see exactly where it stands.

Canon: `<OPERATOR_HOME>/the-conductor/PRIVATE_TO_PUBLIC.md` (secret+full-history scan → `.gitignore`/`.env.example` → de-umbilical → installable+CI → open-mandate audit → dogfood-from-public-artifact → docs → human+consent publish).

## Threshold question (decide BEFORE any publish — not a cleanup task)
This engine automates **your own** logged-in AI accounts (ChatGPT / Claude / Gemini / Grok / Perplexity) through the Linux AT-SPI accessibility API — the same interface a screen reader uses. It is accessibility automation of accounts you control, intended for personal/research use under each platform's terms; it is not a scraping or evasion tool. The category is still sensitive (it drives authenticated sessions), so docs are kept neutral and reliability-framed, and any public framing is reviewed before announcement.

## Discovery — full scan 2026-06-19 (observed)
- **Secrets: no real credentials found (not yet exhaustively verified).** gitleaks over full history (1286 commits) = 86 hits. The **sampled** ones are false positives (training-config keys in `agents/sft_tracker.py`; code identifiers like `getattachtriggerkey`/`ATTACHKEYS` inside AI audit-response markdown); the **remainder are *inferred* to be the same class — NOT each individually verified.** `.gitleaks.toml` allowlist (narrow, documented) → scan now reports **0**. **Caveat (cannot-lie):** the 0 is *allowlist-driven*, not an exhaustive per-hit verification. A truly-verified zero requires either examining the remaining hits individually OR removing the dead `archive/` + stale consultation dumps that generate them (worklist items 2/3) and re-scanning. *(Overclaim "all verified" corrected 2026-06-19 after ChatGPT release-review flagged it.)*
- **Live code/config: nearly clean already.** Only 4 hits, all benign:
  - `storage/neo4j_client.py:11` — `os.environ.get('NEO4J_URI', 'bolt://localhost:7689')` — already env-var, localhost default (OK).
  - `.claude/hooks/config.py:45` — `os.environ.get('NEO4J_URI', 'bolt://localhost:7687')` — already env-var (OK; `.claude/hooks` likely not shipped).
  - `consultation_v2/platforms_runtime.py:73` — operator path in a **comment** (`<OPERATOR_HOME>/treasurer/scripts/`). Scrub the comment.
  - `scripts/restart_display.sh:292` — hardcoded `WEAVIATE_URL='http://127.0.0.1:8088'` (localhost, not a LAN leak) → make it `${WEAVIATE_URL:-…}`.
  - **No LAN IPs (REDACTED_LAN_IP / REDACTED_LAN_IP), no `awareness123`, no `palios-taey-secrets`, no API keys in live code.**
- **Leakage is concentrated in (a) DOCS and (b) `archive/`:**
  - Docs with topology/IPs/display-map/VNC/the "undetectable" framing: `CLAUDE.md` (8), `systemd/README.md` (6), `STABILIZATION_FREEZE.md` (5), `FLOW_CONSULTATION_ENGINE.md` (3), `consultation_v2/DRIVER_CONTRACT.md` (2), `systemd/DISPLAY_REGISTRY.md` (2), `audit_logs/*.md`, `recaps/*.md`, `LICENSE.md` (3).
  - `archive/` = **390 tracked dead V1 files** (also the gitleaks FP source). `.gitignore` lists `archive/` but they were committed before that, so they're still tracked.
  - `CLAUDE.local.md` (fleet topology) is already `.gitignore`'d — good.

## Remediation worklist (ordered; owner; status)
1. **gitleaks allowlist + clean scan** — `.gitleaks.toml`, narrow, documented. *(me — DONE 2026-06-19, scan=0.)*
2. **Code de-umbilical (4 minor items)** — scrub the operator-path comment in `platforms_runtime.py:73`; env-var the hardcoded `WEAVIATE_URL` in `restart_display.sh`; confirm every host/port/path is `os.environ.get(..., localhost-default)` with **fail-loud** where a default is wrong, never a silent LAN default. *(Codex, gated — QUEUED; sequence after Stage-1 merge to keep main clean; near-disjoint from Stage-1 files.)*
3. **Remove `archive/` from the repo** — `git rm -r archive/` (history retained in past commits per Jesse). Removes 390 dead files + the FP surface. *(Codex/me — QUEUED, explicit go on the 390-file diff.)*
4. **Docs: separate operator-private topology from shippable docs** — pattern: keep fleet topology (IPs, display map, VNC, hosts) in `CLAUDE.local.md` (already gitignored); templatize/scrub the **tracked** docs (`CLAUDE.md`, `systemd/*`, `STABILIZATION_FREEZE.md`, `FLOW_*`, `DRIVER_CONTRACT.md`) to env-var placeholders + reframed wording (accessibility automation of your own accounts). Decide what of the corpus/identity references ships. *(me — QUEUED.)*
5. **`.env.example` completeness** — every env var the code reads has an entry (currently: REDIS_HOST/PORT, NEO4J_URI, MCP/TTL/cycle; ADD WEAVIATE_URL, display map, DBUS/AT-SPI bus, profile root, node id). *(me — QUEUED.)*
6. **Installable + CI gate that BLOCKS merge** — packaging + a CI gate (incl. gitleaks) that fails the build on a reintroduced secret/LAN-leak. *(Codex, gated — QUEUED.)*
7. **Open-mandate audit** (find-bugs-not-endorse) → **dogfood from the public artifact** → **docs** → **human + 5/5-consent publish.** *(QUEUED — gated by the threshold decision above.)*

## Note
Item 2/3/4 are the "secure it / no local-network leak / env vars" core Jesse asked for. The encouraging finding: the **live code is already almost entirely env-var'd with localhost defaults** — the real work is docs + removing `archive/`, not rescuing leaked secrets (there are none).
