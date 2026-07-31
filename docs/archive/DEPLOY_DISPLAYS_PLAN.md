# Project: friction-free-display-deploy - Deployable per-instance displays, driven without friction
> Goal (Jesse 2026-06-21, overnight): a system that can be DEPLOYED where each Claude instance gets its OWN displays and drives them WITHOUT friction. Build via orchestrator plan; validate EVERYTHING in PRODUCTION (no tests). Baseline already DONE: the 5-chat engine drives :2-:6 reliably (15/15 3-consecutive, on main a5abb484); displays self-recover (watchdog re-armed + consult-pause flag); clean 1-tab launches (userjs); deploy flow = scripts/install_machine_displays.sh from ~/.taey/machine.env. This project makes per-instance provisioning bulletproof + reproducible + documented, and PROVES it on a fresh display set, WITHOUT touching the working :2-:6.

## Phase: dp1-audit - Audit the deploy flow + enumerate every friction point [order: 1]

### Task: deploy-audit - Inventory the deploy/provisioning flow + the friction list [priority: 8] [owner: taeys-hands-codex]
- Read scripts/install_machine_displays.sh, scripts/install_firefox_user_js.sh, the taey-xvfb@/taey-display unit template generation, ~/.taey/machine.env scheme (TAEY_DISPLAY_N=platform:profile:url), systemd/DISPLAY_REGISTRY.md. Produce: (a) the exact step-by-step to provision a FRESH instance's 5-chat display set (display-number allocation, profile creation, unit gen+enable+start, VNC, AT-SPI capture, userjs, watchdog-pause-flag wiring); (b) the FRICTION + RISK list — every hardcoded operator path/IP (de-umbilical per PRIVATE_TO_PUBLIC), every manual step, every non-idempotent or fail-silent spot, anything that needs a human besides platform login. Output the spec + friction list (commit as a doc on a branch off current main). NO displays/merge.

## Phase: dp2-harden - Make the deploy flow bulletproof [order: 2]

### Task: deploy-harden - Harden install_machine_displays.sh + unit template (idempotent, fail-loud, de-umbilical, per-instance) [priority: 9] [owner: taeys-hands-codex] [depends: deploy-audit]
- Fix every friction point from deploy-audit on a branch off current main (code-only, no displays/merge): fully idempotent (re-runnable safely); fail-LOUD on any missing dep/var (never silent-default); NO hardcoded operator paths/IPs (read from machine.env/env, fail if unset); ensure generated units wire userjs + the watchdog-pause flag (already in Base.run, confirm) + AT-SPI capture + VNC; support provisioning an ARBITRARY instance display set (a clean way to add instance N's 5 displays + profiles without hand-editing). Keep the checked-in 5-chat units generic (no machine-local rows committed, per DISPLAY_REGISTRY). py_compile/bash -n + the consultation_v2 lints. taeys-hands production-proves.

## Phase: dp3-prove - PROVE deployability in production, no tests [order: 3]

### Task: deploy-prove-existing - Re-prove the engine drives the live 5-chat set friction-free [priority: 10] [owner: taeys-hands] [depends: deploy-harden]
- PRODUCTION (no tests): on the live :2-:6 (do NOT regenerate them — they are proven reliable; only re-verify), run one real consult per platform end-to-end with the hardened engine on main, confirm ok=True + real extract + clean monitor + the watchdog-pause flag set/cleared each run + zero manual intervention. Confirms the deployed engine drives the assigned display set without friction.

### Task: deploy-prove-fresh - Provision a FRESH instance display set + validate bring-up (login flagged) [priority: 11] [owner: taeys-hands] [depends: deploy-harden]
- PRODUCTION proof of per-instance deployability WITHOUT risking :2-:6: provision a fresh 5-chat display set on unused display numbers (e.g. :22-:26) + fresh profiles via the hardened install_machine_displays.sh (add temp machine.env rows). VALIDATE end-to-end the NON-AUTH deployment: all 5 Xvfb+Firefox+AT-SPI+VNC come up, units active, userjs applied (1 clean tab each), the engine RESOLVES + navigates each new display and reaches the platform page / auth-wall (display_readiness ready, navigate ok). The ONLY expected manual step = platform LOGIN per profile (Jesse via VNC) — flag it, do NOT attempt 2FA/clone cookies. Then TEAR DOWN cleanly (stop+disable+remove the :22-:26 units + temp profiles + machine.env rows; verify :2-:6 untouched). Proves a new instance gets its own displays friction-free up to the one human login step.

### Task: deploy-append-scope - --append-instance must touch ONLY the new instance's displays [priority: 9] [owner: taeys-hands-codex] [depends: deploy-harden]
- GROUNDED live: `install_machine_displays.sh --append-instance NAME --start-display N` regenerated ALL display units (rewrote live :2..:17) and then HALTED on the in-use safety check for an unrelated aux display (:17 "appears in use outside taey-xvfb@17.service"). ROOT CAUSE (one issue): --append-instance operates over the whole machine.env instead of ONLY the appended instance's display numbers. FIX: in --append-instance mode, generate + enable + start ONLY the new instance's display units (the N..N+4 it just added); do NOT rewrite or restart existing displays, and run the in-use safety check ONLY against the displays being provisioned (so a busy unrelated display never blocks a new instance). Keep full-machine regeneration for the no-arg/default install. Build off current main (7820b510, harden already merged); bash -n + lints; taeys-hands re-proves a clean fresh-instance provision.

## Phase: dp4-doc - Document the deploy procedure [order: 4]

### Task: deploy-doc - Document add-an-instance + the friction removed [priority: 12] [owner: taeys-hands-codex] [depends: deploy-prove-existing, deploy-prove-fresh]
- Write the canonical deploy procedure (a DEPLOY.md or DISPLAY_REGISTRY addition): how to provision a new instance's display set (machine.env rows + install_machine_displays.sh), what is automatic vs the one manual step (platform login via VNC), self-recovery (watchdog + Restart=), collision-freedom (per-instance display numbers + the consult-pause flag). Commit on a branch; taeys-hands merges after the proofs pass.

## User Stop Conditions
- stop_when_all_ready_tasks_dispatched
