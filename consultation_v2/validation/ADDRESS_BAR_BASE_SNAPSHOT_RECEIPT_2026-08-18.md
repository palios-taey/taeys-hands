# Address-bar base-snapshot production receipt — 2026-08-18

Scope: read-only AT-SPI observation of the live ChatGPT Firefox seat on `DISPLAY=:2`.
No UI action, navigation, send, retry, service restart, or production-file mutation occurred.

## Authority

- Production checkout before change: `/home/mira/taeys-hands`
- Public-main source commit before change: `c800567101846d0d1fe2469e1fcc73a2a4b7e0c3`
- Candidate checkout: `/home/mira/.peer-worktrees/infra-codex-taeys-hands-reconcile`
- Candidate branch: `agent/codex-canonical-address-bar`
- UI oracle: fresh AT-SPI tree reached through `/tmp/a11y_bus_:2`

## Before — public main

The observer was run from `/tmp` with `PYTHONPATH=/home/mira/taeys-hands`. The reported module path
was `/home/mira/taeys-hands/consultation_v2/snapshot.py`.

```json
{
  "raw_count": 140,
  "sidebar_count": 0,
  "toolbar_descendants": []
}
```

Observed: the existing filtered snapshot contained no browser-toolbar descendant, including no
address bar.

## After — candidate code against the same live seat

The observer was run from `/tmp` with the candidate checkout as `PYTHONPATH`. The reported module
path was the candidate checkout's `consultation_v2/snapshot.py`.

```json
{
  "app_root_address_bar_key_count": 0,
  "dynamic_greetings": [],
  "menu_address_bar_key_count": 0,
  "raw_count": 141,
  "sidebar_count": 0,
  "toolbar_descendants": [
    {
      "bucket": "mapped",
      "key": "address_bar",
      "name": "Search with Google or enter address",
      "role": "entry"
    }
  ]
}
```

Observed: the base snapshot added exactly one node. It is the exact YAML-owned address bar beneath
the exact `Navigation` / `tool bar` ancestor. No other toolbar descendant entered the projection.
Sidebar/history remained absent, the dynamic greeting remained absent, and neither menu nor noisy
app-root projection acquired the shared key.

## Discarded observations

Two harness attempts are not evidence:

1. The first attempt exported the bus value as `DBUS_SESSION_BUS_ADDRESS`; route binding failed
   before any UI read.
2. A two-root comparison launched from the candidate worktree caused Python's current directory to
   shadow `PYTHONPATH`; both lines loaded candidate code. The comparison was discarded and rerun
   from `/tmp`, with each loaded module path included in the valid observation.
