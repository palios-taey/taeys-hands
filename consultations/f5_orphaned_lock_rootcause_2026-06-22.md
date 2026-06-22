# f5 — Orphaned display-lock blocks the next dispatch — ROOT-CAUSE spec (codex)

**Builder:** taeys-hands-codex. **Gate:** my-fleet r5 + production-validate (taeys-hands). **Date:** 2026-06-22.

## Symptom (observed live, 2026-06-22)
A new claude consult failed at `dispatch_lock`: *":3 dispatch lock is already held by another consultation."* The holder was a prior claude lane that had been **killed** (SIGTERM). Its lock (`taey:plan_active::3`, payload `request_id 4b536d22…`, `owner_token 243449f2…`) was still present with **TTL ~3124s remaining**, and no live claude process existed. Cleared manually with `redis-cli DEL` to unblock.

## Root cause
`consultation_v2/primitives.py:104-117` `acquire_display_lock` takes the lock with `client.set(key, body, ex=ttl=3600, nx=True)`. Release (`release_display_lock`, same file:120-147) runs only from the `finally` of `base.py:_display_dispatch_lock` (consultation_v2/drivers/base.py:1455-1486). **SIGTERM / SIGKILL / a hard crash bypass Python `finally`**, so a killed/crashed lane leaves the lock set for up to the full 3600s TTL. Every subsequent dispatch on that display then loud-fails `dispatch_lock` for up to an hour, even though no process holds it.

## Fix shape (root-cause — self-heals; NOT a patch)
Make the lock **liveness-aware** so an orphaned lock is reclaimed on the next `acquire`, while a genuinely-live lock is still never stolen:

1. **Record the holder's identity in the payload** at acquire time: `holder_pid = os.getpid()` **and** `holder_starttime` (field 22 of `/proc/<pid>/stat`, to defeat PID reuse). (Host is implicit — the lock is per-DISPLAY on a single host.)
2. **In `acquire_display_lock`, when `nx` fails** (lock exists): read the current payload and decide:
   - holder PID is **alive AND its starttime matches** → genuinely live → return `None` (correct loud "display busy"; unchanged behavior).
   - holder PID **not alive**, or alive but **starttime mismatches** (PID reused), or payload **unparseable/missing pid** (legacy) → the lock is **orphaned** → reclaim atomically: `WATCH key` → re-verify it is still the same orphaned record → `MULTI/DEL + SET nx` (or a Lua CAS) → take ownership with a fresh `owner_token`. On `WatchError`, retry the read-decide loop (someone else moved first).
3. Liveness check: `os.kill(pid, 0)` (ProcessLookupError ⇒ dead; PermissionError ⇒ alive) plus the `/proc/<pid>/stat` starttime compare. Keep it a small helper `_holder_alive(record) -> bool`.
4. **Do NOT** shorten the TTL as the fix, and **do NOT** blind-steal (delete-without-liveness-check) — both are patches. The TTL stays as a last-resort backstop; liveness reclaim is the primary path.

Net effect: the orphaned-lock failure mode disappears (next dispatch reclaims a dead holder's lock), and the live-lock guarantee is preserved (a running lane's lock is never taken). Same surface, fewer stuck states.

## Files
- `consultation_v2/primitives.py:89-147` — `_plan_lock_key`, `acquire_display_lock` (add pid+starttime to payload; add liveness-reclaim on nx-fail), `release_display_lock` (unchanged — already owner-token-CAS-safe).
- `consultation_v2/drivers/base.py:1455-1486` — `_display_dispatch_lock` (no change needed; the `finally` release stays as the clean-exit path).

## Validation bar (production, taeys-hands)
Start a consult, `kill -9` the lane mid-setup (orphan the lock), then dispatch a new consult on the **same display** — it must **acquire** (no `dispatch_lock` failure). Separately, with a lane genuinely **alive and holding** the lock, a second dispatch on that display must still loud-fail busy (live lock NOT stolen). Zero manual `DEL`. my-fleet r5 + merge.
