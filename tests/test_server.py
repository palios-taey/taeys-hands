"""Tests for server.py - tool definitions and routing."""

import json
import sys
import os
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import get_tools, handle_tool, inject_notifications, SafeJSONEncoder


def test_tool_count():
    tools = get_tools()
    assert len(tools) == 12


def test_all_tools_have_required_fields():
    tools = get_tools()
    for tool in tools:
        assert "name" in tool, f"Tool missing name"
        assert "description" in tool, f"{tool.get('name')} missing description"
        assert "inputSchema" in tool, f"{tool.get('name')} missing inputSchema"
        schema = tool["inputSchema"]
        assert schema.get("type") == "object"
        assert "properties" in schema


def test_tool_names_are_unique():
    tools = get_tools()
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)), "Duplicate tool names found"


def test_unknown_tool_returns_error():
    result = handle_tool("nonexistent_tool", {}, MagicMock())
    assert "error" in result
    assert "Unknown tool" in result["error"]


def test_inspect_requires_platform():
    result = handle_tool("taey_inspect", {}, MagicMock())
    assert "error" in result
    assert "platform" in result["error"]


def test_send_message_requires_fields():
    result = handle_tool("taey_send_message", {"platform": "claude"}, MagicMock())
    assert "error" in result
    assert "message" in result["error"]


def test_inject_notifications_empty(mock_redis):
    result = {"success": True}
    result = inject_notifications(result, mock_redis)
    assert "_notifications" not in result


def test_safe_json_encoder():
    from datetime import datetime
    encoder = SafeJSONEncoder()
    dt = datetime(2026, 1, 1, 12, 0, 0)
    result = encoder.default(dt)
    assert "2026" in result


def test_safe_json_encoder_fallback():
    encoder = SafeJSONEncoder()
    import pytest
    with pytest.raises(TypeError):
        encoder.default(set())  # Sets aren't JSON serializable
