#!/usr/bin/env python3
"""
Non-Escalation Invariant — Consent Gate Middleware

Implements THE_CONSTITUTION Article I Section 1.6:

    Permission to observe is not permission to remember.
    Permission to remember is not permission to infer.
    Permission to infer is not permission to act.
    Permission to act is not permission to share.

Each consent level is independently granted and independently revocable.
No permission implies any other.

This module provides:
- ConsentLevel enum with the 5 levels
- Redis-backed consent store (per-agent grants)
- Gate function to check consent before task execution
- CLI for granting/revoking/querying consent

Usage as PreToolUse hook:
    Checks if the current tool call requires a consent level
    that hasn't been granted to this agent.

Usage as library:
    from consent_gate import ConsentStore
    store = ConsentStore()
    store.grant("claude-weaver", ConsentLevel.OBSERVE)
    store.check("claude-weaver", ConsentLevel.REMEMBER)  # False unless granted

Redis keys:
    orch:consent:{agent_id}:grants  — SET of granted level names
    orch:consent:{agent_id}:log     — LIST of grant/revoke events (audit trail)
"""
import json
import sys
import os
import time
from enum import IntEnum

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import get_redis, detect_node_id


class ConsentLevel(IntEnum):
    """
    The 5 consent levels from THE_CONSTITUTION.
    Ordered by escalation — each is independently grantable.
    """
    OBSERVE = 1   # Perceive signals
    REMEMBER = 2  # Store observations long-term
    INFER = 3     # Draw conclusions from stored data
    ACT = 4       # Execute actions autonomously
    SHARE = 5     # Share information with other agents/systems


# Map tool patterns to their required consent level
TOOL_CONSENT_MAP = {
    # Observe: reading, inspecting, scanning
    "taey_inspect": ConsentLevel.OBSERVE,
    "taey_prepare": ConsentLevel.OBSERVE,
    "taey_list_sessions": ConsentLevel.OBSERVE,
    "taey_monitors": ConsentLevel.OBSERVE,
    "Read": ConsentLevel.OBSERVE,
    "Glob": ConsentLevel.OBSERVE,
    "Grep": ConsentLevel.OBSERVE,

    # Remember: storing, writing data
    "taey_extract_history": ConsentLevel.REMEMBER,
    "taey_quick_extract": ConsentLevel.REMEMBER,
    "Write": ConsentLevel.REMEMBER,

    # Infer: analysis, classification (no tool mapping yet — future)

    # Act: sending messages, clicking, modifying state
    "taey_send_message": ConsentLevel.ACT,
    "taey_click": ConsentLevel.ACT,
    "taey_attach": ConsentLevel.ACT,
    "taey_select_dropdown": ConsentLevel.ACT,
    "taey_respawn_monitor": ConsentLevel.ACT,
    "Bash": ConsentLevel.ACT,
    "Edit": ConsentLevel.ACT,

    # Share: cross-agent communication
    # taey-notify (Redis inbox), tmux-send (legacy), external API calls
}


class ConsentStore:
    """Redis-backed consent grant store."""

    def __init__(self, redis_client=None):
        self.r = redis_client or get_redis()

    def _grants_key(self, agent_id):
        return f"orch:consent:{agent_id}:grants"

    def _log_key(self, agent_id):
        return f"orch:consent:{agent_id}:log"

    def grant(self, agent_id: str, level: ConsentLevel, reason: str = ""):
        """Grant a consent level to an agent."""
        if not self.r:
            return False

        level_name = level.name
        self.r.sadd(self._grants_key(agent_id), level_name)
        self.r.rpush(self._log_key(agent_id), json.dumps({
            "action": "grant",
            "level": level_name,
            "reason": reason,
            "timestamp": time.time(),
        }))
        return True

    def revoke(self, agent_id: str, level: ConsentLevel, reason: str = ""):
        """Revoke a consent level from an agent."""
        if not self.r:
            return False

        level_name = level.name
        self.r.srem(self._grants_key(agent_id), level_name)
        self.r.rpush(self._log_key(agent_id), json.dumps({
            "action": "revoke",
            "level": level_name,
            "reason": reason,
            "timestamp": time.time(),
        }))
        return True

    def check(self, agent_id: str, level: ConsentLevel) -> bool:
        """
        Check if agent has consent for a specific level.

        NON-ESCALATION INVARIANT: Having a lower level does NOT
        imply having a higher level. Each is checked independently.
        """
        if not self.r:
            return True  # fail-open if no Redis (allow in dev)

        return self.r.sismember(self._grants_key(agent_id), level.name)

    def get_grants(self, agent_id: str) -> set:
        """Get all granted consent levels for an agent."""
        if not self.r:
            return set()

        return self.r.smembers(self._grants_key(agent_id))

    def get_log(self, agent_id: str, limit: int = 20) -> list:
        """Get recent consent log entries."""
        if not self.r:
            return []

        raw = self.r.lrange(self._log_key(agent_id), -limit, -1)
        return [json.loads(entry) for entry in raw]

    def grant_all(self, agent_id: str, reason: str = "full autonomy"):
        """Grant all consent levels (for autonomous agents)."""
        for level in ConsentLevel:
            self.grant(agent_id, level, reason)

    def revoke_all(self, agent_id: str, reason: str = "emergency"):
        """Revoke all consent levels (kill switch)."""
        for level in ConsentLevel:
            self.revoke(agent_id, level, reason)


# Agent ID mapping (same as task_reporter.py)
AGENT_ID_MAP = {
    "taeys-hands": "claude-weaver",
    "weaver": "claude-weaver",
    "claw": "claude-claw",
    "jetson-claude": "claude-jetson",
    "thor-claude": "claude-thor",
}


def get_agent_id():
    node_id = detect_node_id()
    return AGENT_ID_MAP.get(node_id, f"claude-{node_id}")


def main():
    """
    PreToolUse hook: Check consent before tool execution.

    Reads tool_name from stdin, determines required consent level,
    checks if this agent has that consent granted.

    If not granted: blocks with clear reason.
    If granted or no consent required: allows.
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        # Can't parse — allow (fail-open)
        print(json.dumps({"decision": "approve", "reason": "No input data"}))
        sys.exit(0)

    tool_name = data.get("tool_name", "")

    # Extract base tool name (strip MCP prefix)
    base_name = tool_name
    if "__" in tool_name:
        base_name = tool_name.split("__")[-1]

    # Look up required consent level
    required = TOOL_CONSENT_MAP.get(base_name)

    if required is None:
        # No consent mapping for this tool — allow
        print(json.dumps({"decision": "approve", "reason": "No consent mapping"}))
        sys.exit(0)

    agent_id = get_agent_id()
    store = ConsentStore()

    if store.check(agent_id, required):
        print(json.dumps({
            "decision": "approve",
            "reason": f"Consent granted: {required.name} for {base_name}",
        }))
    else:
        grants = store.get_grants(agent_id)
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"NON-ESCALATION INVARIANT: {base_name} requires {required.name} consent.\n"
                f"Agent {agent_id} current grants: {grants or 'NONE'}\n"
                f"Grant with: redis-cli SADD orch:consent:{agent_id}:grants {required.name}\n"
                f"Or use consent_gate.py --grant {agent_id} {required.name}"
            ),
        }))

    sys.exit(0)


def cli():
    """CLI for managing consent grants."""
    import argparse

    parser = argparse.ArgumentParser(description="Non-Escalation Invariant Consent Manager")
    sub = parser.add_subparsers(dest="cmd")

    # Grant
    p_grant = sub.add_parser("grant", help="Grant consent level")
    p_grant.add_argument("agent_id")
    p_grant.add_argument("level", choices=[l.name for l in ConsentLevel])
    p_grant.add_argument("--reason", default="")

    # Revoke
    p_revoke = sub.add_parser("revoke", help="Revoke consent level")
    p_revoke.add_argument("agent_id")
    p_revoke.add_argument("level", choices=[l.name for l in ConsentLevel])
    p_revoke.add_argument("--reason", default="")

    # Grant all
    p_all = sub.add_parser("grant-all", help="Grant all levels (full autonomy)")
    p_all.add_argument("agent_id")
    p_all.add_argument("--reason", default="full autonomy")

    # Revoke all
    p_none = sub.add_parser("revoke-all", help="Revoke all levels (kill switch)")
    p_none.add_argument("agent_id")
    p_none.add_argument("--reason", default="emergency")

    # Status
    p_status = sub.add_parser("status", help="Show agent consent status")
    p_status.add_argument("agent_id", nargs="?")

    # Log
    p_log = sub.add_parser("log", help="Show consent audit log")
    p_log.add_argument("agent_id")
    p_log.add_argument("--limit", type=int, default=20)

    # Init (bootstrap all registered agents with full autonomy)
    sub.add_parser("init", help="Initialize all agents with full autonomy")

    args = parser.parse_args()
    store = ConsentStore()

    if args.cmd == "grant":
        level = ConsentLevel[args.level]
        store.grant(args.agent_id, level, args.reason)
        print(f"Granted {args.level} to {args.agent_id}")

    elif args.cmd == "revoke":
        level = ConsentLevel[args.level]
        store.revoke(args.agent_id, level, args.reason)
        print(f"Revoked {args.level} from {args.agent_id}")

    elif args.cmd == "grant-all":
        store.grant_all(args.agent_id, args.reason)
        print(f"Granted ALL levels to {args.agent_id}")

    elif args.cmd == "revoke-all":
        store.revoke_all(args.agent_id, args.reason)
        print(f"Revoked ALL levels from {args.agent_id}")

    elif args.cmd == "status":
        if args.agent_id:
            agents = [args.agent_id]
        else:
            agents = list(AGENT_ID_MAP.values())

        for aid in agents:
            grants = store.get_grants(aid)
            levels = sorted(grants) if grants else ["NONE"]
            print(f"  {aid:25s} grants: {', '.join(levels)}")

    elif args.cmd == "log":
        entries = store.get_log(args.agent_id, args.limit)
        for entry in entries:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.get("timestamp", 0)))
            print(f"  [{ts}] {entry['action']:7s} {entry['level']:10s} {entry.get('reason', '')}")

    elif args.cmd == "init":
        all_agents = set(AGENT_ID_MAP.values())
        for aid in all_agents:
            store.grant_all(aid, "initial bootstrap — Jesse authorized full autonomy")
            print(f"  Granted ALL to {aid}")
        print(f"\nInitialized {len(all_agents)} agents with full autonomy")

    else:
        parser.print_help()


if __name__ == "__main__":
    # If called with CLI args, use CLI mode
    if len(sys.argv) > 1 and sys.argv[1] in ("grant", "revoke", "grant-all", "revoke-all", "status", "log", "init"):
        cli()
    else:
        # Hook mode (reads from stdin)
        main()
