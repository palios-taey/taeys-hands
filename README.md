# Taey's Hands

AT-SPI-based automation for chat and social platforms on Linux.

Uses the Linux accessibility API (AT-SPI) to interact with web applications in Firefox - no browser automation frameworks (CDP/WebDriver), no detection fingerprints. Just a screen reader that happens to be an AI.

## Supported Platforms

**Chat**: ChatGPT, Claude, Gemini, Grok, Perplexity
**Social**: X/Twitter, LinkedIn

## How It Works

Taey's Hands provides 14 MCP (Model Context Protocol) tools that Claude Code uses to:

1. **Inspect** - Read the accessibility tree to see what's on screen
2. **Navigate** - Switch between platform tabs using keyboard shortcuts
3. **Interact** - Click buttons, type messages, attach files
4. **Extract** - Copy response text via clipboard
5. **Monitor** - Background daemon detects when AI finishes responding

## Requirements

- Linux with X11 (tested on Ubuntu 22.04+)
- Firefox with accessibility enabled
- Python 3.10+
- AT-SPI2 (`at-spi2-core`)
- `xdotool`, `xclip`
- Redis (for state management)
- Neo4j (for conversation storage)

## Setup

```bash
# System dependencies
sudo apt install at-spi2-core xdotool xclip

# Python dependencies
pip install redis neo4j PyGObject

# Verify AT-SPI is working
python3 scripts/verify_atspi.py

# Enable Firefox accessibility (about:config)
# accessibility.force_disabled = 0
```

## Usage

The server runs as an MCP stdio server, configured in `.mcp.json`:

```json
{
  "mcpServers": {
    "taeys-hands": {
      "type": "stdio",
      "command": "/usr/bin/python3",
      "args": ["server.py"],
      "cwd": "/path/to/taeys-hands"
    }
  }
}
```

## Architecture

```
server.py           # MCP router (JSON-RPC over stdio)
core/               # AT-SPI primitives (frozen)
  atspi.py          # Firefox/desktop discovery
  tree.py           # Accessibility tree traversal
  clipboard.py      # System clipboard via xclip
  input.py          # Keyboard/mouse via xdotool
  platforms.py      # Platform registry
storage/            # Redis + Neo4j persistence
tools/              # MCP tool handlers (one per file)
monitor/            # Background response detection daemon
platforms/          # Platform configs (YAML)
```

## Tests

```bash
python3 -m pytest tests/ -v
```

## License

MIT
