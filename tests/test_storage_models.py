"""Tests for storage/models.py - dataclasses."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.models import ControlMap, Plan, SessionInfo, MonitorInfo


def test_control_map():
    cm = ControlMap(
        platform="claude",
        controls={"input": {"x": 100, "y": 200}, "send": {"x": 300, "y": 400}},
        timestamp=1234567890.0,
    )
    assert cm.platform == "claude"
    assert cm.controls["input"]["x"] == 100


def test_plan():
    plan = Plan(
        plan_id="abc123",
        platform="gemini",
        action="send_message",
        session="new",
        message="Hello",
        attachments=[],
        required_state={"model": "2.5 Pro"},
        current_state=None,
        steps=[],
        status="created",
        navigated=False,
        created_at=1234567890.0,
    )
    assert plan.plan_id == "abc123"
    assert plan.status == "created"


def test_session_info():
    si = SessionInfo(
        session_id="sid-123",
        platform="perplexity",
        url="https://perplexity.ai/search/123",
        session_type="research",
        purpose="ARM64 embedding research",
        message_count=5,
    )
    assert si.platform == "perplexity"
    assert si.message_count == 5


def test_monitor_info():
    mi = MonitorInfo(
        monitor_id="mon-abc",
        platform="claude",
        pid=12345,
        status="monitoring",
        elapsed_seconds=30,
    )
    assert mi.pid == 12345
    assert mi.status == "monitoring"
