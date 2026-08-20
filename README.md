# Taey's Hands

AT-SPI-based hands for chat and social platforms on Linux. Uses the Linux accessibility API (AT-SPI) to
operate web apps in Firefox — no browser-automation framework (CDP/WebDriver), no detection fingerprint.
Just a screen reader that happens to be an AI.

> **This is written for Taey.** If you are Taey, these are your hands — not a tool you are evaluating for
> someone else. You do not have a browser; you have an accessibility tree. You act by naming a control and
> asking for it, the way a screen-reader user does. Each platform is its own Firefox on its own X display
> with its own cookies, so a stuck window on one never blocks the others.

## Read this first — the three layers

Everything here is one of three layers. Keeping them straight is the whole game; most confusion comes from
mixing them up.

### Layer 1 — the PRIMITIVES (permanent; these are your hands)
The single-action operations and reads that never go away. Read the tree, take **one** action, **verify** it
landed, hold the display lock, detect the stop button, notify, extract. Everything else is built on these.
`drive_chat` uses them. The completion monitor uses them. You use them. They are always production.

- **read the tree** — `consultation_v2/snapshot.py` (`build_snapshot(platform)` → the elements named in that
  platform's YAML, resolved against the live tree by **exact** name+role — never substring).
- **act, one step** — `atspi.py`/`input.py`/`interact.py`/`clipboard.py`: click / focus / activate / type /
  paste / key / hover / read-clipboard, plus `focus_file_dialog`. A target is always selected by its exact
  YAML mapping in the fresh tree. A YAML-declared hover or mapped navigation primitive may use that exact
  node's live AT-SPI extents to position the pointer; geometry is never a locator, disambiguator, remembered
  coordinate, or fallback.
- **verify a step** — resolve one YAML element key and check it is present/showing (exact match). This is
  how you know an action landed. It is the prerequisite for recovering when one does not.
- **the lock** — `consultation_v2/primitives.py` (`taey:plan_active::N`): a display you did not lock is a
  hand that is not currently yours.
- **completion detector** — `consultation_v2/platforms/<p>/monitor.py` (`<P>CompletionDetector`): stop
  button seen → gone = the response finished.
- **element maps** — `consultation_v2/platforms/<p>/<p>.yaml`: the exact name+role of every control, per
  platform. The YAML is the source of truth; the tree is the oracle. When they disagree, fix the YAML.
- **notify / extract** — `consultation_v2/notify.py`; mapped copy/tree extraction.

### Layer 2 — STEP-BY-STEP operation (how you work today; production now)
You drive a consult **one action at a time**: observe the tree → take one primitive action → verify it
landed → the next. Reliable because it is supervised and verified at every step — no chained assumptions.
This is the intended production path for consults right now. On the family-chat displays (`:2`–`:6`,
`:20`–`:24`) the exposed first-person surface is **`drive_chat`** (`taey-presence/serving/ui_drive.py`). It
consumes the canonical `build_snapshot(platform)` projection, binds refs to the observed scope and revision,
and executes only the operation declared by that platform's YAML. The governing discipline is one contract:
[`docs/UI_INTERACTION_AUTHORITY.md`](docs/UI_INTERACTION_AUTHORITY.md) — one action per approved turn,
tree-is-truth, **no autonomous loops.** Start with the
[`consultation_v2` authority and status index](consultation_v2/README.md) before operating or changing this
path. The concrete two-attachment Taey worker action card is
[`docs/MANUAL_CONSULT_WALKTHROUGH.md`](docs/MANUAL_CONSULT_WALKTHROUGH.md).

### Layer 3 — the ENGINE (a work in progress; not run autonomously)
`consultation_v2/orchestrator.py` + `drivers/` + `scripts/run_consultation_v2.py` chain the Layer-1
primitives into a whole-consult-in-one-call (navigate → select → attach → send → monitor → extract). It
**works sometimes and not others** — which is exactly why it is **not run autonomously** and no seat
dispatches it. It is kept as the target you (with the Family/Chats) will make reliable; when it is reliable
it becomes the fast path. **Until then, Layer 2 is production and the engine is not run on its own.**
`ConsultationRuntime` now accepts only `atspi_only` clicking. Unsupported strategy names fail closed; they never
fall back to pointer coordinates. See [`FLOW_CONSULTATION_ENGINE.md`](FLOW_CONSULTATION_ENGINE.md) before changing it.

## The completion monitor (Layer-1 detection, running now)
`scripts/consult_completion_monitor.py` runs one passive watcher per display (`taey-consult-monitor@N.service`
for `:2`–`:6`). It reuses the `CompletionDetector` + the `stop_button` YAML element + `taey-notify`: when the
stop button disappears, it notifies Taey the response is ready. Read-only — it never drives or locks a display.

## Displays — two full sets of hands

Two independent sets, so a consult on one never blocks the other.

| Platform | Primary (family-chat) | Second set |
|---|---|---|
| ChatGPT | `:2` | `:20` |
| Claude | `:3` | `:21` |
| Gemini | `:4` | `:22` |
| Grok | `:5` | `:23` |
| Perplexity | `:6` | `:24` |

Primary (`:2`–`:6`) is the default. Second set (`:20`–`:24`) is for parallel streams or when a primary is
shared/busy. `:13` is a separate Claude CVP account (hunter's), not a Taey consult display. Config lives in
`~/.taey/machine.env`; no display number is hardcoded. Each display is its own logged-in Firefox with its own
cookies and AT-SPI bus, fully isolated.

## Where things live

```
consultation_v2/
  snapshot.py runtime.py atspi.py input.py interact.py tree.py clipboard.py   # L1 primitives: read + act
  primitives.py                 # L1: the display lock + monitor-session helpers
  yaml_contract.py              # L1: strict YAML loader
  platforms/<p>/<p>.yaml        # L1: exact element maps, per platform (source of truth)
  platforms/<p>/monitor.py      # L1: stop-button completion detector
  notify.py identity.py         # L1: notification; FAMILY_KERNEL + Spotlight + IDENTITY consolidation
  orchestrator.py  drivers/     # L3: the engine (autonomous chain — WIP, not run on its own)
  cli.py                        # L3: engine CLI
scripts/
  consult_completion_monitor.py # the passive per-display completion monitor (running)
  run_consultation_v2.py        # L3: engine entrypoint (WIP — do NOT run autonomously)
  launch_isolated_display.sh manage_displays.sh install_machine_displays.sh …  # display substrate
systemd/user, ~/.config/systemd/user/taey-*  # display units + taey-consult-monitor@N
storage/                        # optional Redis + Neo4j persistence
```

The current documentation surface is enumerated in
[`docs/DOCUMENTATION_MAP.md`](docs/DOCUMENTATION_MAP.md). Historical audits, transcripts, recovery packets, and
superseded plans are available through Git history, not alongside current operating instructions.

## Requirements / setup

- Linux + X11, Firefox with `accessibility.force_disabled=0` **and** `widget.use-xdg-desktop-portal.file-picker=0`
  (force Firefox's own file chooser — the XDG portal picker is a separate app AT-SPI cannot see).
- Python 3.10+, `at-spi2-core`, `xdotool`, `xsel`, PyGObject. Redis/Neo4j optional.
- Production display provisioning: [DEPLOY.md](DEPLOY.md).

## License

[PolyForm Noncommercial License 1.0.0](LICENSE) — free for any noncommercial purpose; commercial use requires a separate license.
