# scripts/

Utility scripts for taeys-hands node setup and Claude-to-Claude communication.

---

## tmux-send

Send a message to a tmux session — locally or on a remote machine over SSH.

This is the backbone of multi-Claude coordination: when you have multiple
Claude Code instances running (on the same machine or across different nodes),
`tmux-send` lets them pass instructions to each other reliably.

### Why not just use SSH directly?

Raw SSH + tmux send-keys drops special characters, fails silently on missing
sessions, and has no feedback. `tmux-send` handles all of that:

- **Base64 encodes** the message — survives shell expansion, quotes, newlines
- **Verifies** the target session exists before sending
- **Warns** if the target pane isn't running `claude`
- **Works locally** (2 args) or **remotely** (3 args, same interface)

### Install

```bash
# On any node — installs tmux-send + system dependencies
bash scripts/install-node.sh

# Or manually
sudo install -m 755 scripts/tmux-send /usr/local/bin/tmux-send
```

### Usage

```bash
# Local — send to a tmux session on this machine
tmux-send <session-name> "your message"

# Remote — send to a tmux session on another machine via SSH
tmux-send <hostname-or-ip> <session-name> "your message"
```

### Examples

```bash
# Wake up a Claude instance in another window
tmux-send claude-worker "Resume the task from where you left off"

# Send from Spark to a remote worker node
tmux-send 192.168.1.20 worker-claude "Fix deployed. Run: cd ~/taeys-hands && git pull"

# Escalate a problem to a supervisor Claude
tmux-send supervisor "ESCALATION from worker: Neo4j connection failed, cannot continue"

# Send a multi-word message (all args after session are joined)
tmux-send my-session this entire sentence is the message
```

### Multi-Claude pattern

The typical setup for multi-node taeys-hands operation:

```
[Coordinator node]          [Worker node 1]         [Worker node 2]
  tmux: supervisor            tmux: worker-1          tmux: worker-2
  Claude Code (orchestrates)  Claude Code (executes)  Claude Code (executes)

Coordinator → worker:  tmux-send worker-host worker-1 "Next task: process batch 4"
Worker → coordinator:  tmux-send coord-host supervisor "DONE: batch 4 complete"
Worker → coordinator:  tmux-send coord-host supervisor "ESCALATION: attach failed, need fix"
```

The coordinator (supervisor) handles code changes and decisions.
Workers execute tasks and escalate when blocked.

### SSH requirements

Remote use requires passwordless SSH access to the target machine.
The target user's `tmux` must be running with the named session active.

```bash
# Check if target is reachable and session exists
ssh <host> "tmux ls"
```

### Rules

- **Only target Claude Code sessions** — messages arrive as user input, so
  sending to a human's terminal is disruptive and wrong
- **Use tmux-send for all Claude-to-Claude messages** — never raw SSH
- **Sessions must exist** — script exits with error if session not found

---

## install-node.sh

One-command setup for a new taeys-hands node.

```bash
bash scripts/install-node.sh
```

Installs:
- `tmux-send` → `/usr/local/bin/tmux-send`
- System packages: `xdotool`, `xsel`, `x11-utils` (required for AT-SPI tools)
