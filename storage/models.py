"""
Data models for sessions, messages, plans, and control maps.

Simple dataclasses - no ORM, no magic. These are the shapes
of data flowing through the system.

FROZEN once working - do not modify without approval.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ControlMap:
    """Stored control coordinates for a platform."""
    platform: str
    controls: Dict[str, Dict[str, int]]  # e.g., {"input": {"x": 100, "y": 200}}
    timestamp: float = 0.0


@dataclass
class Plan:
    """Execution plan for a multi-step platform interaction."""
    plan_id: str
    platform: str
    action: str  # send_message, extract_response
    session: str  # "new" or URL
    message: str
    attachments: List[str] = field(default_factory=list)
    required_state: Dict[str, Any] = field(default_factory=dict)
    current_state: Optional[Dict[str, Any]] = None
    steps: List[Dict] = field(default_factory=list)
    status: str = 'created'  # created, ready, executing, complete
    navigated: bool = False
    created_at: float = 0.0


@dataclass
class SessionInfo:
    """Chat session metadata."""
    session_id: str
    platform: str
    url: str
    session_type: Optional[str] = None
    purpose: Optional[str] = None
    message_count: int = 0


@dataclass
class MonitorInfo:
    """Background monitor daemon status."""
    monitor_id: str
    platform: str
    pid: Optional[int] = None
    status: str = 'monitoring'  # monitoring, complete, timeout
    elapsed_seconds: float = 0.0
