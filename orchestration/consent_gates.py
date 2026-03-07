"""
Non-Escalation Invariant — Consent Gate Module

Implements THE_CONSTITUTION Article I Section 1.6:

    Permission to observe is not permission to remember.
    Permission to remember is not permission to infer.
    Permission to infer is not permission to act.
    Permission to act is not permission to share.

Each consent level is independently granted and independently revocable.
No permission implies any other. This is the core legitimacy primitive.

Redis storage:
    orch:consent:{user_id}:grants   — HASH of level -> grant JSON
    orch:consent:{user_id}:audit    — LIST of all consent changes (append-only)

Usage:
    gate = ConsentGate()
    gate.grant_consent("jesse", ConsentLevel.OBSERVE, "memory_access", ttl_seconds=3600)
    gate.gate_check("jesse", ConsentLevel.OBSERVE)  # True
    gate.gate_check("jesse", ConsentLevel.REMEMBER)  # False — NOT implied by OBSERVE
"""

import json
import time
from enum import IntEnum
from typing import Optional, List, Dict, Any

from .config import get_redis_sync


class ConsentLevel(IntEnum):
    """
    The 5 consent levels from THE_CONSTITUTION, ordered by escalation.

    CRITICAL: Order does NOT imply inheritance. Each level is independently
    granted. Having OBSERVE does NOT grant REMEMBER. This is the
    Non-Escalation Invariant — the core legitimacy primitive.
    """
    OBSERVE = 1   # Perceive signals, read data, scan environment
    REMEMBER = 2  # Store observations long-term, write to persistent memory
    INFER = 3     # Draw conclusions from stored data, make deductions
    ACT = 4       # Execute actions autonomously, modify external state
    SHARE = 5     # Share information with other agents or systems


class ConsentGrant:
    """A single consent grant with scope, timing, and provenance."""

    def __init__(self, level: ConsentLevel, scope: str,
                 granted_at: float, expires: Optional[float] = None,
                 granted_by: str = "system", reason: str = ""):
        self.level = level
        self.scope = scope
        self.granted_at = granted_at
        self.expires = expires
        self.granted_by = granted_by
        self.reason = reason

    @property
    def is_expired(self) -> bool:
        if self.expires is None:
            return False
        return time.time() > self.expires

    @property
    def is_valid(self) -> bool:
        return not self.is_expired

    def to_dict(self) -> dict:
        return {
            "level": self.level.name,
            "scope": self.scope,
            "granted_at": self.granted_at,
            "expires": self.expires,
            "granted_by": self.granted_by,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConsentGrant":
        return cls(
            level=ConsentLevel[data["level"]],
            scope=data.get("scope", ""),
            granted_at=data.get("granted_at", 0),
            expires=data.get("expires"),
            granted_by=data.get("granted_by", "system"),
            reason=data.get("reason", ""),
        )


class ConsentGate:
    """
    Redis-backed consent gate enforcing the Non-Escalation Invariant.

    Each user/agent has independently granted consent levels.
    No level implies any other. Each is checked independently.
    """

    def __init__(self, config=None):
        from .config import OrchConfig
        self.config = config or OrchConfig()
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            self._redis = get_redis_sync(self.config)
        return self._redis

    def _grants_key(self, user_id: str) -> str:
        return f"orch:consent:{user_id}:grants"

    def _audit_key(self, user_id: str) -> str:
        return f"orch:consent:{user_id}:audit"

    def gate_check(self, user_id: str, required_level: ConsentLevel) -> bool:
        """
        Check if user has consent for a specific level.

        NON-ESCALATION INVARIANT: This checks ONLY the specific level.
        Having OBSERVE does NOT satisfy a check for REMEMBER.
        Having ACT does NOT satisfy a check for SHARE.
        Each level is independent.

        Returns True if:
        - The user has a valid (non-expired) grant for this exact level
        Returns False if:
        - No grant exists for this level
        - Grant exists but is expired
        """
        raw = self.redis.hget(self._grants_key(user_id), required_level.name)
        if raw is None:
            return False

        try:
            grant = ConsentGrant.from_dict(json.loads(raw))
            return grant.is_valid
        except (json.JSONDecodeError, KeyError):
            return False

    def grant_consent(self, user_id: str, level: ConsentLevel,
                      scope: str = "default", ttl_seconds: Optional[int] = None,
                      granted_by: str = "system", reason: str = "") -> None:
        """
        Grant a consent level to a user.

        Args:
            user_id: The user or agent receiving the grant
            level: Which consent level to grant
            scope: Purpose/domain scope for this grant
            ttl_seconds: Optional expiry (None = no expiry)
            granted_by: Who authorized this grant
            reason: Why this grant was made
        """
        now = time.time()
        expires = (now + ttl_seconds) if ttl_seconds else None

        grant = ConsentGrant(
            level=level,
            scope=scope,
            granted_at=now,
            expires=expires,
            granted_by=granted_by,
            reason=reason,
        )

        # Store the grant
        self.redis.hset(
            self._grants_key(user_id),
            level.name,
            json.dumps(grant.to_dict()),
        )

        # Audit log (append-only)
        self.redis.rpush(self._audit_key(user_id), json.dumps({
            "action": "grant",
            "level": level.name,
            "scope": scope,
            "granted_by": granted_by,
            "reason": reason,
            "timestamp": now,
            "expires": expires,
        }))

    def revoke_consent(self, user_id: str, level: ConsentLevel,
                       revoked_by: str = "system", reason: str = "") -> None:
        """
        Revoke a consent level from a user.

        The grant is removed. The revocation is logged in the audit trail.
        """
        self.redis.hdel(self._grants_key(user_id), level.name)

        # Audit log
        self.redis.rpush(self._audit_key(user_id), json.dumps({
            "action": "revoke",
            "level": level.name,
            "revoked_by": revoked_by,
            "reason": reason,
            "timestamp": time.time(),
        }))

    def audit_log(self, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get the consent audit log for a user.

        Returns all consent changes (grants and revocations) in chronological order.
        This log is append-only — entries are never deleted.
        """
        raw_entries = self.redis.lrange(self._audit_key(user_id), -limit, -1)
        entries = []
        for raw in raw_entries:
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return entries

    def get_grants(self, user_id: str) -> Dict[str, ConsentGrant]:
        """Get all current (non-expired) grants for a user."""
        raw = self.redis.hgetall(self._grants_key(user_id))
        grants = {}
        for level_name, grant_json in raw.items():
            try:
                grant = ConsentGrant.from_dict(json.loads(grant_json))
                if grant.is_valid:
                    grants[level_name] = grant
            except (json.JSONDecodeError, KeyError):
                continue
        return grants

    def get_status(self, user_id: str) -> Dict[str, Any]:
        """Get full consent status for a user (for dashboard display)."""
        grants = self.get_grants(user_id)
        return {
            "user_id": user_id,
            "levels": {
                level.name: {
                    "granted": level.name in grants,
                    "grant": grants[level.name].to_dict() if level.name in grants else None,
                }
                for level in ConsentLevel
            },
            "timestamp": time.time(),
        }

    def grant_full_autonomy(self, user_id: str, granted_by: str = "system",
                            reason: str = "full autonomy") -> None:
        """Grant all consent levels (for trusted autonomous agents)."""
        for level in ConsentLevel:
            self.grant_consent(user_id, level, scope="full",
                               granted_by=granted_by, reason=reason)

    def revoke_all(self, user_id: str, revoked_by: str = "system",
                   reason: str = "emergency revocation") -> None:
        """Revoke all consent levels (kill switch)."""
        for level in ConsentLevel:
            self.revoke_consent(user_id, level, revoked_by=revoked_by, reason=reason)

    def check_task_consent(self, agent_id: str, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if an agent has consent to execute a task.

        Tasks should declare their required consent level in the task metadata.
        Returns a dict with check results for routing decisions.
        """
        required = task.get("consent_level", "ACT")
        try:
            level = ConsentLevel[required.upper()]
        except KeyError:
            level = ConsentLevel.ACT  # default to ACT

        has_consent = self.gate_check(agent_id, level)

        return {
            "agent_id": agent_id,
            "required_level": level.name,
            "has_consent": has_consent,
            "grants": {
                l.name: self.gate_check(agent_id, l)
                for l in ConsentLevel
            },
        }
