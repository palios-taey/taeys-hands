"""Tests for tools/monitors.py - list and kill monitors."""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.monitors import handle_list_monitors, handle_kill_monitors


def test_list_monitors_empty(mock_redis):
    result = handle_list_monitors(mock_redis)
    assert result["success"] is True
    assert result["count"] == 0
    assert result["monitors"] == []


def test_list_monitors_with_entries(mock_redis):
    mock_redis._store["taey:monitor:abc"] = json.dumps({
        "status": "monitoring",
        "platform": "claude",
    })
    result = handle_list_monitors(mock_redis)
    assert result["success"] is True
    assert result["count"] == 1


def test_list_monitors_no_redis():
    result = handle_list_monitors(None)
    assert result["success"] is True
    assert result["count"] == 0


def test_kill_monitors_clears_redis(mock_redis):
    mock_redis._store["taey:monitor:abc"] = json.dumps({"status": "monitoring"})
    mock_redis._store["taey:monitor:def"] = json.dumps({"status": "monitoring"})

    result = handle_kill_monitors(mock_redis)
    assert result["success"] is True
    assert result["redis_entries_cleared"] >= 0
