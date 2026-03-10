# scripts/

Utility scripts for taeys-hands node setup and Claude-to-Claude communication.

---

## taey-notify (PRIMARY — Redis inbox)

Send a message to any Claude instance via Redis inbox. Messages are delivered by PostToolUse hooks (active instances) or tmux fallback daemon (idle autonomous instances).

### Why not tmux-send?

`tmux-send` injects directly into the tmux command line. If the recipient is mid-tool-call (>15s), the message corrupts their input. `taey-notify` writes to Redis instead — the PostToolUse hook delivers it cleanly after the tool finishes.

### Install

```bash
bash scripts/install-node.sh    # installs taey-notify + tmux-send + deps

# Or manually
sudo install -m 755 scripts/taey-notify /usr/local/bin/taey-notify
```

### Usage

```bash
taey-notify <target-node> "message"
taey-notify <target-node> "message" --type <type> --priority <priority>
```

### Message types

| Type | Use for |
|------|---------|
| `message` | General inter-Claude communication (default) |
| `escalation` | Error reports, blocked workers (auto-promotes to high priority) |
| `heartbeat` | Cycle-complete reports, status updates |
| `notification` | System events |
| `response_ready` | Platform response detected |
| `command` | Direct instructions |

### Examples

```bash
# Worker escalation (auto-promotes to high priority)
taey-notify weaver "ESCALATION from $(hostname): Grok inspect failed" --type escalation

# Heartbeat from worker
taey-notify weaver "HEARTBEAT from $(hostname): cycle done" --type heartbeat

# Send instructions to a worker
taey-notify jetson-claude "Fix deployed. Run: cd ~/taeys-hands && git pull"

# Low-priority status update
taey-notify weaver "254K tiles remaining" --type heartbeat --priority low
```

### Delivery architecture

```
taey-notify → Redis LPUSH taey:{node}:inbox
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
  PostToolUse hook       tmux fallback daemon
  (active instances)     (idle autonomous only)
  Drains inbox after     Polls every 5s, checks
  every tool call,       tool_running flag,
  injects via            only injects when idle
  additionalContext      for 30s+
```

### Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `127.0.0.1` | Redis server |
| `REDIS_PORT` | `6379` | Redis port |
| `TAEY_NODE_ID` | (auto-detected) | Sender identity |

---

## tmux-send (LEGACY — direct tmux injection)

Send a message to a tmux session — locally or on a remote machine over SSH.

Still useful when Redis is unreachable or for direct wake-up of a stopped instance. For routine inter-Claude messaging, use `taey-notify` instead.

### Why not just use SSH directly?

Raw SSH + tmux send-keys drops special characters, fails silently on missing
sessions, and has no feedback. `tmux-send` handles all of that:

- **Base64 encodes** the message — survives shell expansion, quotes, newlines
- **Verifies** the target session exists before sending
- **Warns** if the target pane isn't running `claude`
- **Works locally** (2 args) or **remotely** (3 args, same interface)

### Usage

```bash
# Local — send to a tmux session on this machine
tmux-send <session-name> "your message"

# Remote — send to a tmux session on another machine via SSH
tmux-send <hostname-or-ip> <session-name> "your message"
```

### Rules

- **Only target Claude Code sessions** — messages arrive as user input
- **Never target human-attended sessions** — disruptive
- **Sessions must exist** — script exits with error if session not found

---

## install-node.sh

One-command setup for a new taeys-hands node.

```bash
bash scripts/install-node.sh
```

Installs:
- `taey-notify` → `/usr/local/bin/taey-notify` (Redis-backed messaging)
- `tmux-send` → `/usr/local/bin/tmux-send` (direct tmux injection)
- System packages: `xdotool`, `xsel`, `x11-utils` (required for AT-SPI tools)
