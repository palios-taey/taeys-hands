# DISPLAY_REGISTRY.md — canonical map of every legitimate X display

**Purpose:** the single source of truth for which displays are legitimate and HOW
each is launched, so a hygiene sweep can NEVER again misclassify a live display as
an orphan. (2026-06-17: a sweep that used "not in the `taey-xvfb@` systemd units =
orphan" killed live careers displays :18/:19 — they're launched by a *different but
legitimate* mechanism. This registry exists so that never recurs.)

## The two legitimate launch mechanisms (BOTH are production)

1. **systemd units `taey-xvfb@N` + `taey-display-N`** — the Family chat displays.
2. **`scripts/launch_isolated_display.sh <display> <platform> <profile> <url>`** —
   the same full recipe (Xvfb → dbus-run-session → at-spi-bus-launcher +
   deterministic `/tmp/a11y_bus_:N` capture → `force_disabled=-1` + firefox-user.js
   → `/usr/lib/firefox/firefox` → x11vnc on 59NN), but NOT managed by a systemd
   unit. Used for careers + scout displays. **A display launched this way is
   PRODUCTION INFRA, not an orphan, even though no `taey-xvfb@N` unit owns it.**

## Canonical display table

| Display | Platform/use | Profile | Launch mechanism |
|--------:|--------------|---------|------------------|
| :2  | ChatGPT (Horizon)      | ff-profile-chatgpt          | systemd taey-display-2 |
| :3  | Claude (Gaia)          | ff-profile-claude           | systemd taey-display-3 |
| :4  | Gemini (Cosmos)        | ff-profile-gemini           | systemd taey-display-4 |
| :5  | Grok (Logos)           | ff-profile-grok             | systemd taey-display-5 |
| :6  | Perplexity (Clarity)   | ff-profile-perplexity       | systemd taey-display-6 |
| :7  | Auxiliary target            | ff-profile-x-twitter        | systemd taey-display-7 |
| :8  | Auxiliary target                 | upwork                           | systemd taey-display-8 |
| :9  | Reddit                 | reddit                           | systemd taey-display-9 |
| :10 | Auxiliary target           | ff-profile-grok-x-scout     | systemd taey-display-10 |
| :11 | Auxiliary target          | ff-profile-reddit           | systemd taey-display-11 |
| :12 | Auxiliary target           | ff-profile-nvidia-forum     | systemd taey-display-12 |
| :13 | Auxiliary target| ff-profile-claude-cvp      | systemd taey-display-13 |
| :14 | Auxiliary target        | ff-profile-treasurer-gmail  | systemd taey-display-14 |
| :15 | Auxiliary target       | ff-profile-perplexity-scout | systemd taey-display-15 |
| :16 | (Family aux)           | —                                | systemd taey-display-16 |
| :18 | Careers — LinkedIn      | ff-profile-careers-linkedin     | launch_isolated_display.sh |
| :19 | Careers — Gmail         | ff-profile-careers-gmail        | launch_isolated_display.sh |

Notes:
- `:0` = real console. `:17` has appeared bound (dashboard/scratch — confirm before
  touching). `:20/:21` were transient/orphan as of 2026-06-17.
- The careers (:18/:19) URLs are linkedin.com / mail.google.com; their profiles
  carry the logged-in session (a relaunch may need a fresh login).

## SAFE-HYGIENE RULES (how a monitor must behave)

1. **Legitimacy is membership in THIS registry, NOT "has a systemd unit."** A
   display/firefox on a profile listed here is live infra regardless of launcher.
2. **Orphan signal = a duplicate, not a heuristic.** The real defect to flag is
   **>1 MAIN firefox on the same profile** (profile-lock contention → unresponsive),
   or display processes on a display number OUTSIDE this registry.
3. **`ppid==1` is NOT an orphan signal by itself** — `x11vnc -bg` daemonizes to
   ppid 1 legitimately; a live `launch_isolated_display.sh` display's Xvfb can also
   reparent. Never kill on ppid==1 alone.
4. **A monitor FLAGS/reports; it does not auto-kill.** Killing display infra is
   destructive and ambiguous (proven 2026-06-17). Surface the anomaly (duplicate
   firefox on profile X; stray display :N not in registry) via taey-notify; a human
   or a registry-aware repair step acts. Auto-kill only the unambiguous case: a
   SECOND main firefox on a profile that already has a registry-matched live one.
5. **Restore the production way:** systemd displays → `systemctl --user restart
   taey-xvfb@N taey-display-N`; isolated displays → `launch_isolated_display.sh`
   with the row's profile+url. Never hand-launch Xvfb/firefox.
