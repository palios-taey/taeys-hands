# Display Deploy Procedure

This is the canonical procedure for adding a fresh 5-chat browser instance on
one machine without disturbing existing displays.

## What Is Automatic

`scripts/install_machine_displays.sh` automates the display substrate:

- appends the new instance display rows to the host machine env
- writes display-specific systemd units for only the requested display range
- enables and starts only those new display units
- starts Xvfb, an isolated D-Bus session, AT-SPI, Firefox, profile `user.js`,
  and x11vnc
- stores or rotates `~/.taey/vnc_passwd` from `TAEY_VNC_PASSWORD` without
  printing the password
- leaves existing `taey-display-*` units untouched when `--append-instance` is
  used

The only manual step after a fresh instance comes up is platform login in each
new Firefox profile via VNC. Do not clone cookies. Do not automate 2FA.

## Required Host Configuration

The host systemd units read `~/.taey/machine.env` by default. Start from
`systemd/machine.env.template`:

```bash
mkdir -p ~/.taey
cp systemd/machine.env.template ~/.taey/machine.env
chmod 600 ~/.taey/machine.env
$EDITOR ~/.taey/machine.env
```

Required values:

- `TAEY_MACHINE`
- `TAEY_REPO`
- `TAEY_REDIS_HOST`
- `TAEY_REDIS_PORT`
- `TAEY_FIREFOX_BIN`
- `TAEY_AT_SPI_BUS_LAUNCHER`
- `TAEY_AT_SPI_REGISTRYD`
- `TAEY_USE_SOFTWARE_GL`
- `TAEY_VNC_PASSWORD`, unless installing with `--no-vnc`

The installer fails loudly when a required variable, binary, malformed display
row, duplicate platform, duplicate profile, or target display collision is
found.

## Add One Instance

Pick a contiguous unused display block. A 5-chat instance uses exactly five
displays:

- `N` for ChatGPT
- `N+1` for Claude
- `N+2` for Gemini
- `N+3` for Grok
- `N+4` for Perplexity

Provision the display set:

```bash
./scripts/install_machine_displays.sh --append-instance worker1 --start-display 20
```

In `--append-instance` mode, the installer scopes display-specific work to
`20..24` in this example. It does not rewrite, restart, enable, or collision
check unrelated existing display units.

The host env rows generated for non-default instances use prefixed platform
names such as `worker1_chatgpt`. That keeps one shared host machine env
collision-free when several instances coexist.

Use `--no-start` for a staged install:

```bash
./scripts/install_machine_displays.sh --append-instance worker1 --start-display 20 --no-start
```

Preview rows without editing the env:

```bash
./scripts/install_machine_displays.sh --print-instance-env worker1 --start-display 20
```

## Runtime Env Per Driver Instance

The consultation engine resolves `platform -> display` from
`TAEY_MACHINE_ENV`, falling back to `~/.taey/machine.env`.

For a driver instance, use a separate env file with unprefixed platform names.
That lets the normal CLI keep using `--platform chatgpt`, `--platform claude`,
and so on even when the host env uses prefixed names to avoid collisions.

Example for `worker1` on displays `20..24`:

```bash
mkdir -p ~/.taey/instances
cat > ~/.taey/instances/worker1.env <<'EOF'
TAEY_DISPLAY_20="chatgpt:ff-profile-worker1-chatgpt:https://chatgpt.com/"
TAEY_DISPLAY_21="claude:ff-profile-worker1-claude:https://claude.ai/new"
TAEY_DISPLAY_22="gemini:ff-profile-worker1-gemini:https://gemini.google.com/app"
TAEY_DISPLAY_23="grok:ff-profile-worker1-grok:https://grok.com/"
TAEY_DISPLAY_24="perplexity:ff-profile-worker1-perplexity:https://perplexity.ai/"
EOF
chmod 600 ~/.taey/instances/worker1.env
```

Run a consultation against that instance:

```bash
TAEY_MACHINE_ENV=$HOME/.taey/instances/worker1.env \
python3 scripts/run_consultation_v2.py \
  --platform chatgpt \
  --message "Smoke prompt" \
  --requester taeys-hands \
  --purpose deploy-smoke \
  --output /tmp/worker1-chatgpt.json
```

`scripts/run_consultation_v2.py` initializes AT-SPI bus environment before
calling the V2 CLI. Direct `consultation_v2/cli.py` usage must preserve that
same environment invariant.

## Login Via VNC

Each display's VNC port is `5900 + display_number`.

For the `worker1` example:

- display `:20` -> VNC port `5920`
- display `:21` -> VNC port `5921`
- display `:22` -> VNC port `5922`
- display `:23` -> VNC port `5923`
- display `:24` -> VNC port `5924`

Use the password stored in `~/.taey/vnc_passwd`. Log into each platform once in
its fresh profile. The expected unauthenticated stopping point is the platform
page or auth wall; the deployment is still valid up to that human login gate.

## Self-Recovery

Generated display units run under systemd user services:

- `taey-display-N.service` uses `Restart=always`
- `taey-bus-watcher@N.service` uses `Restart=always`
- `taey-xvfb@N.service` uses `Restart=on-failure`

`taey-bus-watcher@N.service` keeps `/tmp/a11y_bus_:N` current while the display
is running. Consultation runs pause the display watchdog through files under
`~/.taey/`:

- `display_watchdog_pause_<platform>`
- `display_watchdog_pause_<display_number>`

The pause files are created and refreshed by `Base.run` during a consultation,
then removed when the run exits. This prevents the watchdog from racing a live
consultation while still allowing recovery after the guarded operation ends.

## Collision-Freedom Rules

- Allocate a unique contiguous display block per instance.
- Keep one Firefox profile per display row.
- Use prefixed platform names in the shared host env when several instances
  coexist.
- Use unprefixed platform names in each driver instance env.
- Use `--append-instance NAME --start-display N` for new instances; use the
  no-arg installer only when intentionally regenerating the full machine set.

If the installer reports a target display collision, stop and inspect the
existing X lock/socket and systemd owner. Do not bypass the collision check.
