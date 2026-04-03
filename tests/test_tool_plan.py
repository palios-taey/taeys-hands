"""Tests for tools/plan.py - plan create/get/update."""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.dropdown import handle_prepare
from tools.plan import handle_plan


def test_create_plan_requires_all_fields(mock_redis):
    result = handle_plan("claude", "send_message", {}, mock_redis)
    assert result["success"] is False
    assert "Missing required fields" in result["error"]


def test_create_plan_success(mock_redis):
    params = {
        "session": "new",
        "message": "Hello Claude",
        "model": "Sonnet 4.5",
        "mode": "default",
        "tools": "none",
        "attachments": [],
    }
    result = handle_plan("claude", "send_message", params, mock_redis)
    assert result["success"] is True
    assert result["platform"] == "claude"
    assert "plan_id" in result
    assert result["consultation_defaults"] == {
        "model": "opus",
        "mode": "extended_thinking",
        "attach_method": "atspi_menu",
        "extract_method": "last_copy_button",
    }


def test_prepare_includes_consultation_defaults(mock_redis):
    result = handle_prepare("perplexity", mock_redis)
    assert result["consultation_defaults"] == {
        "model": None,
        "mode": "deep_research",
        "attach_method": "keyboard_nav",
        "extract_method": "copy_contents",
    }


def test_get_plan(mock_redis):
    params = {
        "session": "new",
        "message": "Test",
        "model": "GPT-4o",
        "mode": "default",
        "tools": "none",
        "attachments": [],
    }
    create_result = handle_plan("chatgpt", "send_message", params, mock_redis)
    plan_id = create_result["plan_id"]

    get_result = handle_plan("chatgpt", "get", {"plan_id": plan_id}, mock_redis)
    assert get_result["success"] is True
    assert get_result["plan"]["message"] == "Test"


def test_update_plan_stores_current_state(mock_redis):
    params = {
        "session": "new",
        "message": "Hello",
        "model": "Sonnet",
        "mode": "default",
        "tools": "none",
        "attachments": ["/tmp/file.txt"],
    }
    create_result = handle_plan("claude", "send_message", params, mock_redis)
    plan_id = create_result["plan_id"]

    update_result = handle_plan("claude", "update", {
        "plan_id": plan_id,
        "current_state": {"model": "Haiku", "mode": "default"},
    }, mock_redis)
    assert update_result["success"] is True
    assert update_result["status"] == "created"
    # Verify the current_state was stored in the plan
    get_result = handle_plan("claude", "get", {"plan_id": plan_id}, mock_redis)
    assert get_result["plan"]["current_state"] == {"model": "Haiku", "mode": "default"}


def test_unknown_action(mock_redis):
    result = handle_plan("claude", "invalid_action", {}, mock_redis)
    assert result["success"] is False


def test_create_plan_no_redis():
    result = handle_plan("claude", "send_message", {"message": "test"}, None)
    assert result["success"] is False
    assert "Redis" in result["error"]
