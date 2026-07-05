# Project: consult-engine-followups - Consult Engine Post-Migration Follow-ups
> Tracked follow-ups surfaced during the platform-independence migration (per-platform packages). Decommission-phase work — none block the migration itself; each is a real gap/hardening to land after retire-shared-base. Filed per conductor 2026-07-05 so they survive as tasks, not just ledger lines.

## Phase: followups - Deferred fixes + hardening [order: 1]

### Task: fu-claude-artifact-extract - Map the live Claude right-panel artifact Copy control [priority: 20] [owner: taeys-hands-codex] [depends: consult-platform-independence::p2-decommission]
- pkg-claude val proved `extract_additional` fails: "no configured control yielded artifact content". Claude puts the real deliverable in a right-panel ARTIFACT; the package's mapped artifact_copy_keys + AT-SPI candidates don't resolve the live Copy control. Confirmed PRE-EXISTING (main's blind-coord helper was condemned HIGH#8, removed w2d) — behavior-parity, so it merged; but artifact-bearing consults lose the artifact (prose extract_primary works). FIX: map the live right-panel artifact Copy control (same class as the perplexity `Copy contents`→`Copy` UI-drift). Verify with a real artifact-producing Claude consult.

### Task: fu-perplexity-export-markdown-fallback - Add Export-as-Markdown 0-control extract fallback [priority: 20] [owner: taeys-hands-codex] [depends: consult-platform-independence::p2-decommission]
- Perplexity UI drifted: the extractor's mapped `copy_contents_button` ("Copy contents") is GONE; the answer copy is now a plain `Copy` push button, and some DR layouts expose neither mapped control → extract_primary fails "no mapped extraction control present". Manual recovery that works: the response `...` menu → "Export as Markdown" → full-content download. FIX: (a) remap the answer-extract to the current plain `Copy` control; (b) add "Export as Markdown" (via `...` menu) as a fallback extract for the 0-control DR-report case.

### Task: fu-gemini-profile-aware-element-names - Profile-aware Gemini element names for 2-set parallelism [priority: 30] [owner: taeys-hands-codex] [depends: consult-platform-independence::p2-decommission]
- The 2nd Gemini display-set profile (`ff-profile-mira-gemini-2`, :22, "Ultra" account) has a DIFFERENT model menu ("3.1 Pro"/"3.5 Thinking", NO "Deep Think") than the 1st profile — gemini.yaml element names don't match → select fails on :22, forcing all gemini lanes to :4. FIX: profile-aware element names (or a 2nd-profile YAML variant) so gemini runs on both display sets for full 2-set parallelism.

### Task: fu-routing-parent-pkg-error-translation - Fix routing.py error-translation for a missing PARENT pkg [priority: 40] [owner: taeys-hands-codex] [depends: consult-platform-independence::p2-decommission]
- routing.py:16-18 error-translation is broken for a missing PARENT package (exc.name is the parent → the teaching-RuntimeError branch is skipped, raw ModuleNotFoundError propagates). Still fail-loud + unreachable from prod, so cheap. FIX: handle the parent-pkg case in the error translation.

### Task: fu-osresource-find-firefox-race - Per-package find-Firefox window/bus concurrency assertion [priority: 40] [owner: taeys-hands-codex] [depends: consult-platform-independence::p2-decommission]
- The shared `_routing_core` + AT-SPI/DBus bus + Firefox process tree are OS-level shared-mutable resources; per-package binding is CONFIG-level only (dedicated DISPLAY + PID file). Runtime serialization comes from the display-keyed dispatch lock (5de5c6dd), not the routing layer — lint-clean ≠ runtime-race-free under concurrent/rapid dispatch. FIX: add a per-package concurrency assertion that each find-Firefox binds its OWN window/bus (no cross-bind), exercised by concurrent/rapid-sequential dispatch across ≥2 packages.

## User Stop Conditions
- stop_when_all_ready_tasks_dispatched
