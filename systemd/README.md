# Taey Display Systemd Units

Stable AT-SPI-isolated browser dispatch displays. Each unit launches Xvfb +
isolated AT-SPI bus + Firefox with a persistent profile + x11vnc for remote
debugging.

## Install

```bash
# 1. Copy units to user systemd dir
cp systemd/user/*.service ~/.config/systemd/user/

# 2. Copy machine.env template and customize per-machine
mkdir -p ~/.taey
cp systemd/machine.env.template ~/.taey/machine.env
$EDITOR ~/.taey/machine.env

# 3. Reload systemd + enable + start
systemctl --user daemon-reload
systemctl --user enable taey-display-{2..6}.service
systemctl --user start taey-display-{2..6}.service
```

## VNC access

Each display has its own VNC port: `5900 + display_number`
- :2 → 5902 (ChatGPT)
- :3 → 5903 (Claude)
- :4 → 5904 (Gemini)
- :5 → 5905 (Grok)
- :6 → 5906 (Perplexity)
- :13 → 5913 (CVP Claude)
- :16 → 5916 (Huntr submission)

Default password: `<TAEY_VNC_PASSWORD>` (stored at `~/.taey/vnc_passwd`).

## Architecture

Each `taey-display-N.service`:
1. Depends on `taey-xvfb@N.service` (Xvfb instance for the display)
2. Launches `dbus-run-session` to create an isolated session bus
3. Spawns `at-spi-bus-launcher` + `at-spi2-registryd` for the isolated AT-SPI bus
4. Writes the AT-SPI bus address to `/tmp/a11y_bus_:N` for consumers
5. Launches Firefox with the configured profile + URL
6. Starts x11vnc on port 5900+N
7. Has a watchdog loop that re-captures the AT-SPI bus if it changes (Firefox restarts can rotate it)

## Why this architecture

Per `<OPERATOR_HOME>/.claude/projects/-home-mira-taeys-hands/memory/feedback_isolated_atspi.md`:
multiple Firefox instances MUST use isolated AT-SPI buses via dbus-run-session.
Shared bus = 40%+ failures. This is the operational invariant for reliable
multi-display browser dispatch.

## Profiles

Firefox profiles live at `~/.taey/profiles/<profile-name>/`. The `user.js`
template at `systemd/user/firefox-user.js` is copied into each profile at
display launch to set `accessibility.force_disabled = -1` (force AT-SPI on).
