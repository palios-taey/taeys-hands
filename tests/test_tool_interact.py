"""Tests for tools/interact.py - set_map, click, click_at."""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.interact import handle_set_map, handle_click, get_map


def test_set_map_stores_controls(mock_redis):
    controls = {
        "input": {"x": 100, "y": 200},
        "send": {"x": 300, "y": 400},
    }
    result = handle_set_map("claude", controls, mock_redis)
    assert result["platform"] == "claude"
    assert len(result["controls_stored"]) == 2


def test_set_map_validates_coordinates(mock_redis):
    controls = {
        "input": {"x": 100},  # Missing y
    }
    result = handle_set_map("claude", controls, mock_redis)
    # Should fail - missing y coordinate
    assert "error" in result
    assert "missing" in result["error"].lower()


def test_get_map_returns_stored(mock_redis):
    controls = {"input": {"x": 100, "y": 200}}
    handle_set_map("claude", controls, mock_redis)
    stored = get_map("claude", mock_redis)
    assert stored is not None
    assert stored["platform"] == "claude"


def test_get_map_returns_none_when_empty(mock_redis):
    stored = get_map("claude", mock_redis)
    assert stored is None


def test_click_requires_map(mock_redis):
    result = handle_click("claude", "send", mock_redis)
    assert "error" in result
    assert "No current map" in result["error"]


def test_click_requires_valid_target(mock_redis):
    controls = {"input": {"x": 100, "y": 200}}
    handle_set_map("claude", controls, mock_redis)
    result = handle_click("claude", "nonexistent", mock_redis)
    assert "error" in result
    assert "not found" in result["error"]
