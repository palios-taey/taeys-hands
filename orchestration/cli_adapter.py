"""
CLI Adapter

Wraps tmux-send for agent communication + SSH for cross-machine (Spark 3).
Ported from v4 coordination/buddy_system.py.

Gemini's insight: tmux-send is ONLY for interrupts (near-100% loss if terminal
in wrong state). All data transfer uses Redis Streams.

Usage:
  adapter = CLIAdapter()
  adapter.send_interrupt("claude-weaver", "STOP - file conflict detected")
  adapter.send_continue("codex-cli")
"""

import subprocess
import time
from typing import Dict, Optional


# Agent session mapping
AGENT_SESSIONS: Dict[str, Dict[str, str]] = {
    "claude-taeys-hands": {
        "machine": "spark1",
        "tmux_session": "taeys-hands",
    },
    "claude-weaver": {
        "machine": "spark1",
        "tmux_session": "weaver",
    },
    "claude-claw": {
        "machine": "spark3",
        "tmux_session": "claw",
        "ssh": "spark@10.0.0.10",
    },
    "conductor-gemini": {
        "machine": "spark1",
        "tmux_session": "conductor-gemini",
    },
    "conductor-codex": {
        "machine": "spark1",
        "tmux_session": "conductor-codex",
    },
    "weaver-gemini": {
        "machine": "spark1",
        "tmux_session": "weaver-gemini",
    },
    "weaver-codex": {
        "machine": "spark1",
        "tmux_session": "weaver-codex",
    },
    "qwen-local": {
        "machine": "thor",
        "tmux_session": "thor-claude",
        "ssh": "thor@10.0.0.197",
    },
}


class CLIAdapter:
    """Sends interrupts to CLI agents via tmux-send."""

    def _send_keys(self, agent_id: str, keys: str, literal: bool = False) -> bool:
        """
        Send keys to an agent's tmux session.

        For remote agents (spark3), uses SSH. For local, direct tmux.
        Uses subprocess list args (no shell=True) to prevent command injection.
        """
        session_info = AGENT_SESSIONS.get(agent_id)
        if not session_info:
            return False

        tmux_session = session_info["tmux_session"]
        ssh_target = session_info.get("ssh")

        try:
            tmux_cmd = ["tmux", "send-keys", "-t", tmux_session]
            if literal:
                tmux_cmd.append("-l")
            tmux_cmd.append(keys)

            if ssh_target:
                cmd = ["ssh", "-o", "ConnectTimeout=5", ssh_target] + tmux_cmd
            else:
                cmd = tmux_cmd

            result = subprocess.run(cmd, capture_output=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def _inject_message(self, agent_id: str, message: str) -> bool:
        """
        Inject a message into an agent's tmux session via load-buffer.

        Uses file-based injection (bulletproof, no escaping issues).
        No shell=True — all subprocess calls use list args.
        """
        session_info = AGENT_SESSIONS.get(agent_id)
        if not session_info:
            return False

        tmux_session = session_info["tmux_session"]
        ssh_target = session_info.get("ssh")

        try:
            tmp_file = f"/tmp/orch_msg_{agent_id}.txt"

            if ssh_target:
                # Write locally, SCP, paste remotely
                with open(tmp_file, "w") as f:
                    f.write(message)

                result = subprocess.run(
                    ["scp", "-o", "ConnectTimeout=5", tmp_file, f"{ssh_target}:{tmp_file}"],
                    capture_output=True, timeout=15,
                )
                if result.returncode != 0:
                    return False

                # Remote: load-buffer then paste-buffer (two separate SSH calls)
                result = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", ssh_target,
                     "tmux", "load-buffer", tmp_file],
                    capture_output=True, timeout=15,
                )
                if result.returncode != 0:
                    return False

                result = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", ssh_target,
                     "tmux", "paste-buffer", "-t", tmux_session],
                    capture_output=True, timeout=15,
                )
                if result.returncode != 0:
                    return False

                time.sleep(1)
                subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", ssh_target,
                     "tmux", "send-keys", "-t", tmux_session, "Enter"],
                    capture_output=True, timeout=10,
                )
                return True
            else:
                # Local injection
                with open(tmp_file, "w") as f:
                    f.write(message)

                result = subprocess.run(
                    ["tmux", "load-buffer", tmp_file],
                    capture_output=True, timeout=10,
                )
                if result.returncode != 0:
                    return False

                result = subprocess.run(
                    ["tmux", "paste-buffer", "-t", tmux_session],
                    capture_output=True, timeout=10,
                )
                if result.returncode != 0:
                    return False

                time.sleep(0.5)
                subprocess.run(
                    ["tmux", "send-keys", "-t", tmux_session, "Enter"],
                    capture_output=True, timeout=10,
                )
                return True

        except Exception:
            return False

    def send_interrupt(self, agent_id: str, message: str) -> bool:
        """Send Ctrl+C then inject a message. Use sparingly - interrupts only."""
        self._send_keys(agent_id, "C-c")
        time.sleep(0.5)
        return self._inject_message(agent_id, message)

    def send_continue(self, agent_id: str, message: str = "Continue working on pending tasks.") -> bool:
        """Inject a continue prompt into an agent's session."""
        return self._inject_message(agent_id, message)

    def send_task(self, agent_id: str, task_description: str) -> bool:
        """Inject a task description into an agent's session."""
        return self._inject_message(agent_id, task_description)

    def is_session_alive(self, agent_id: str) -> bool:
        """Check if an agent's tmux session exists."""
        session_info = AGENT_SESSIONS.get(agent_id)
        if not session_info:
            return False

        tmux_session = session_info["tmux_session"]
        ssh_target = session_info.get("ssh")

        try:
            if ssh_target:
                cmd = f"ssh -o ConnectTimeout=5 {ssh_target} 'tmux has-session -t {tmux_session}'"
            else:
                cmd = f"tmux has-session -t {tmux_session}"

            result = subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def get_session_status(self) -> Dict[str, bool]:
        """Check all known agent sessions. Returns {agent_id: is_alive}."""
        return {agent_id: self.is_session_alive(agent_id)
                for agent_id in AGENT_SESSIONS}
