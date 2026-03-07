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
        "ssh": "spark@192.168.100.12",
    },
    "gemini-cli": {
        "machine": "spark1",
        "tmux_session": "gemini",
    },
    "codex-cli": {
        "machine": "spark1",
        "tmux_session": "codex",
    },
}


class CLIAdapter:
    """Sends interrupts to CLI agents via tmux-send."""

    def _send_keys(self, agent_id: str, keys: str, literal: bool = False) -> bool:
        """
        Send keys to an agent's tmux session.

        For remote agents (spark3), uses SSH. For local, direct tmux.
        """
        session_info = AGENT_SESSIONS.get(agent_id)
        if not session_info:
            return False

        tmux_session = session_info["tmux_session"]
        ssh_target = session_info.get("ssh")

        flag = "-l" if literal else ""

        try:
            if ssh_target:
                cmd = (
                    f"ssh -o ConnectTimeout=5 {ssh_target} "
                    f"'tmux send-keys -t {tmux_session} {flag} {repr(keys)}'"
                )
            else:
                cmd = f"tmux send-keys -t {tmux_session} {flag} {repr(keys)}"

            result = subprocess.run(
                cmd, shell=True, capture_output=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _inject_message(self, agent_id: str, message: str) -> bool:
        """
        Inject a message into an agent's tmux session via load-buffer.

        Uses file-based injection (bulletproof, no escaping issues).
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

                scp_cmd = f"scp -o ConnectTimeout=5 {tmp_file} {ssh_target}:{tmp_file}"
                result = subprocess.run(scp_cmd, shell=True, capture_output=True, timeout=15)
                if result.returncode != 0:
                    return False

                paste_cmd = (
                    f"ssh -o ConnectTimeout=5 {ssh_target} "
                    f"'tmux load-buffer {tmp_file} && tmux paste-buffer -t {tmux_session}'"
                )
                result = subprocess.run(paste_cmd, shell=True, capture_output=True, timeout=15)
                if result.returncode != 0:
                    return False

                time.sleep(1)
                enter_cmd = (
                    f"ssh -o ConnectTimeout=5 {ssh_target} "
                    f"'tmux send-keys -t {tmux_session} Enter'"
                )
                subprocess.run(enter_cmd, shell=True, capture_output=True, timeout=10)
                return True
            else:
                # Local injection
                with open(tmp_file, "w") as f:
                    f.write(message)

                paste_cmd = (
                    f"tmux load-buffer {tmp_file} && "
                    f"tmux paste-buffer -t {tmux_session}"
                )
                result = subprocess.run(paste_cmd, shell=True, capture_output=True, timeout=10)
                if result.returncode != 0:
                    return False

                time.sleep(0.5)
                enter_cmd = f"tmux send-keys -t {tmux_session} Enter"
                subprocess.run(enter_cmd, shell=True, capture_output=True, timeout=10)
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
