# Taey's Hands

AT-SPI-based automation for chat and social platforms on Linux.

Uses the Linux accessibility API (AT-SPI) to interact with web applications in Firefox - no browser automation frameworks (CDP/WebDriver), no detection fingerprints. Just a screen reader that happens to be an AI.

## Supported Platforms

**Chat**: ChatGPT, Claude, Gemini, Grok, Perplexity
**Social**: X/Twitter, LinkedIn

## How It Works

`consultation_v2/` is the only live consultation engine.

1. The request is mapped to a platform/model/mode/tools selection.
2. `consultation_v2.identity` prepends `FAMILY_KERNEL.md` and the platform `IDENTITY_*.md` file, then consolidates caller attachments into one package.
3. The platform driver reads `consultation_v2/platforms/<platform>.yaml`; drivers contain shared control flow and no hardcoded element names.
4. Every setup action is validated against the AT-SPI tree. If the tree cannot validate the action after the configured settle/rescan window, the run fails loudly.
5. Send is validated by the stop button appearing, and new sessions also require URL capture/change.
6. Completion monitoring uses stop-button disappearance, then extraction uses mapped copy/tree controls and sends a Redis notification.

## Requirements

- Linux with X11 (tested on Ubuntu 22.04+)
- Firefox with accessibility enabled
- Python 3.10+
- AT-SPI2 (`at-spi2-core`)
- `xdotool`, `xsel`
- Redis (optional - for state management and monitor notifications)
- Neo4j (optional - for conversation history storage)

## Setup

```bash
# System dependencies
sudo apt install at-spi2-core xdotool xsel

# Python dependencies
pip install redis neo4j PyGObject

# Enable Firefox accessibility (about:config)
# accessibility.force_disabled = 0
```

For production display provisioning, see [DEPLOY.md](DEPLOY.md).

## Usage

```bash
python3 scripts/run_consultation_v2.py \
  --platform chatgpt \
  --message "Prompt text" \
  --attach /path/to/context.md \
  --requester taeys-hands-codex \
  --purpose smoke \
  --output /tmp/consultation.json
```

## Architecture

```
scripts/run_consultation_v2.py  # CLI entrypoint
consultation_v2/                # sole live consultation engine
  runtime.py                    # shared AT-SPI/input primitives
  snapshot.py                   # tree snapshot + YAML mapping
  identity.py                   # FAMILY_KERNEL + IDENTITY consolidation
  completion.py                 # stop-button completion detector
  notify.py                     # Redis notification output
  drivers/                      # platform drivers
  platforms/                    # live YAML contracts
  validators/                   # integrity gates
storage/            # Redis + Neo4j persistence
scripts/launch_isolated_display.sh, restart_display.sh, bus_watcher.sh,
scripts/manage_displays.sh, setup_display.sh, install_machine_displays.sh,
systemd/user/taey-*             # production DBUS/Firefox display substrate
archive/                       # retired V1/MCP/bot/test/docs evidence
```

## Gates

```bash
python3 scripts/run_consultation_v2.py --help
python3 consultation_v2/validators/lint_no_yaml_silent_fallbacks.py --all
python3 consultation_v2/validators/lint_consultation_v2_contract.py --all
```

## License

[PALIOS-TAEY Sacred Trust License v1.0](LICENSE.md)

This is an ethical source license — not "open source" as defined by the OSI. It grants full rights to individual humans and authenticated AI agents, with Sacred Trust Conditions protecting children, opposing slavery, and promoting flourishing. Institutions must obtain a [Commercial License](https://github.com/palios-taey/governance).

See the [governance framework](https://github.com/palios-taey/governance) for the complete set of governing documents.
