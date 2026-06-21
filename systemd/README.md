# Taey Display Systemd Units

Stable AT-SPI-isolated browser dispatch displays. The installer is the
canonical deploy path; checked-in units are generic examples and must not be
hand-copied as machine-local configuration.

For the full add-an-instance procedure, including per-instance runtime envs and
the VNC login gate, see [../DEPLOY.md](../DEPLOY.md).

## Install

```bash
mkdir -p ~/.taey
cp systemd/machine.env.template ~/.taey/machine.env
$EDITOR ~/.taey/machine.env
chmod 600 ~/.taey/machine.env

./scripts/install_machine_displays.sh
```

Required local values live in `~/.taey/machine.env`:

- `TAEY_REPO`
- `TAEY_FIREFOX_BIN`
- `TAEY_AT_SPI_BUS_LAUNCHER`
- `TAEY_AT_SPI_REGISTRYD`
- `TAEY_USE_SOFTWARE_GL`
- `TAEY_VNC_PASSWORD`, unless installing with `--no-vnc`
- one or more `TAEY_DISPLAY_N="platform:profile:url"` rows

The installer fails if a required dependency, path, variable, malformed display
row, duplicate platform, duplicate profile, or unmanaged display collision is
found.

## Installer Options

Generate and enable units without starting them:

```bash
./scripts/install_machine_displays.sh --no-start
```

Generate display units without VNC:

```bash
./scripts/install_machine_displays.sh --no-vnc
```

Append a five-chat display set without hand-editing rows:

```bash
./scripts/install_machine_displays.sh --append-instance worker1 --start-display 20 --no-start
```

The `default` instance preserves platform names `chatgpt`, `claude`,
`gemini`, `grok`, and `perplexity`. Any other instance name prefixes platform
names, for example `worker1_chatgpt`, so multiple display sets can coexist in
one machine env without platform-key collisions.

Print the rows instead of editing `machine.env`:

```bash
./scripts/install_machine_displays.sh --print-instance-env worker1 --start-display 20
```

Use a non-default machine env file:

```bash
./scripts/install_machine_displays.sh --machine-env /path/to/machine.env
```

## Boot Persistence

User services survive logout only when user lingering is enabled:

```bash
loginctl enable-linger "$USER"
```

## VNC Access

Each display uses VNC port `5900 + display_number`.

- `:2` -> `5902` (ChatGPT)
- `:3` -> `5903` (Claude)
- `:4` -> `5904` (Gemini)
- `:5` -> `5905` (Grok)
- `:6` -> `5906` (Perplexity)

The installer writes `~/.taey/vnc_passwd` from `TAEY_VNC_PASSWORD` without
printing the password. Re-running the installer rotates the stored VNC password.

## Architecture

Each generated `taey-display-N.service`:

1. Depends on `taey-xvfb@N.service`.
2. Reads `~/.taey/machine.env`.
3. Starts `scripts/display_unit_runner.sh` under `dbus-run-session`.
4. Fails if AT-SPI bus capture does not produce `/tmp/a11y_bus_:N`.
5. Installs the repo-owned Firefox `user.js` into the configured profile.
6. Launches Firefox with the configured URL and profile.
7. Starts x11vnc when VNC is enabled.
8. Writes `/tmp/firefox_pid_:N` for runtime consumers.

`taey-bus-watcher@N.service` keeps `/tmp/a11y_bus_:N` current while the display
is running. The consultation runtime pauses the display watchdog through
`~/.taey/display_watchdog_pause_<platform>` and
`~/.taey/display_watchdog_pause_<display>` from `Base.run`.

## Profiles

Firefox profiles live at `~/.taey/profiles/<profile-name>/`. The `user.js`
template at `systemd/user/firefox-user.js` is installed into each profile by
`scripts/install_firefox_user_js.sh`; that installer removes stale session
restore files and fails if the profile policy cannot be replaced.
