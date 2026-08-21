# Post-action observation barrier

The barrier is a Hands-owned boundary between one receipted UI mutation and any later mutation.
It does not perform the action, retry it, drive a monitor, or authorize a sequence. The caller may
consider another mutation only when the returned receipt says both `verdict: PASS` and
`next_mutation_authorized: true`.

The first candidate declaration is Grok's production-observed `usage_limit_updated` recovery. Its existing
`workflow.post_send.exceptions.usage_limit_updated.recovery` mapping remains the single source for
the click, target, one-attempt ceiling, expected Stop control, and URL prefix. The additive
`workflow.post_action_transitions.usage_limit_retry` declaration owns only the observation surface,
scope, refresh policy, timing, and number of independent exact matches.

This commit does not claim production enforcement. The current production integration boundary is
Presence `serving/ui_drive.py::_dispatch`, immediately after its successful Grok
`click retry_button` mutation. Until that call site invokes this barrier and terminalizes a HALT,
the declaration and library are mechanically qualified framework material, not a production pilot.

The transaction shape is:

1. Resolve and validate the declaration before the mutation is authorized.
2. Accept one immutable action receipt bound to the pre-action revision and lineage.
3. Acquire a fresh read-only sample using the declaration's scope-specific refresh policy.
4. Project only the exact YAML-mapped expected control, URL gate, and mapped alternate exception.
5. Require the declared number of consecutive identical happy projections.
6. Return a terminal PASS or HALT receipt. Observation failure, duplicate or state-drifted controls,
   ambiguity, a mapped alternate, and timeout all leave `next_mutation_authorized` false.

Refresh policy is coupled exactly to scope:

- `snapshot` -> `invalidate_reacquire`
- `menu_snapshot` -> `invalidate_reacquire_menu`
- `app_root_snapshot` -> `live_reacquire_no_clear`
- `native_dialog_snapshot` -> `native_invalidate_reacquire`

The barrier's mandatory browser and menu invalidation failures are receipted and raised; they are
not silently swallowed.
The app-root policy intentionally performs no clear because clearing can dismiss transient React
portals. Screenshots, full-tree equality, universal clearing, action retries, and fixed sleeps are
not evidence for this barrier.

Run the deterministic mechanical gate with:

```bash
python3 scripts/verify_post_action_barrier.py
```

The gate checks the declaration resolver, two-sample PASS, mapped-exception HALT,
duplicate-control HALT, timeout HALT, and refresh-failure HALT. It is not production observation and
does not replace a supervised run on the target display.
