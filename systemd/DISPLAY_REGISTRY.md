# DISPLAY_REGISTRY.md — generic X display map

**Purpose:** document the public, generic display layout for the five chat
consultation platforms. Machine-local auxiliary displays, authenticated account
targets, profile names, and URLs belong only in `~/.taey/machine.env`.

## Launch Mechanism

The checked-in systemd units use `taey-xvfb@N` + `taey-display-N` for the five
chat platforms. The same recipe can be reused locally for other displays, but
those rows must stay in local machine configuration.

## Canonical Display Table

| Display | Platform/use | Profile | Launch mechanism |
|--------:|--------------|---------|------------------|
| :2 | ChatGPT | ff-profile-chatgpt | systemd taey-display-2 |
| :3 | Claude | ff-profile-claude | systemd taey-display-3 |
| :4 | Gemini | ff-profile-gemini | systemd taey-display-4 |
| :5 | Grok | ff-profile-grok | systemd taey-display-5 |
| :6 | Perplexity | ff-profile-perplexity | systemd taey-display-6 |

Notes:
- `:0` is the real console.
- Any additional display numbers, profiles, URLs, or authenticated targets are
  local operational configuration and should not be committed.

## Safe Hygiene Rules

1. **Legitimacy is membership in this registry or local machine config, not only
   "has a systemd unit."** A display/firefox on a configured profile is live
   infra regardless of launcher.
2. **Orphan signal = a duplicate, not a heuristic.** The real defect to flag is
   **more than one main Firefox on the same profile**, or display processes on a
   display number outside the registry/local config.
3. **`ppid==1` is not an orphan signal by itself.** `x11vnc -bg` daemonizes to
   ppid 1 legitimately; a live isolated-display Xvfb can also reparent.
4. **A monitor flags/reports; it does not auto-kill.** Killing display infra is
   destructive and ambiguous. Surface the anomaly via notification; a human or a
   registry-aware repair step acts.
5. **Restore the production way:** systemd displays use
   `systemctl --user restart taey-xvfb@N taey-display-N`; isolated displays use
   `launch_isolated_display.sh` with local profile and URL values. Never
   hand-launch Xvfb/firefox.
