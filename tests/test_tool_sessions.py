"""Tests for tools/sessions.py - list sessions."""

import json
import sys
import os
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.sessions import handle_list_sessions
from storage.redis_pool import node_key


def test_list_sessions_empty(mock_redis):
    with patch('tools.sessions.neo4j_client') as mock_neo4j:
        mock_neo4j.get_active_sessions.return_value = []
        result = handle_list_sessions(None, mock_redis)
        assert result["success"] is True
        assert result["sessions"] == []


def test_list_sessions_with_pending(mock_redis):
    mock_redis._store[node_key("pending_prompt:claude")] = json.dumps({
        "sent_at": "2026-01-01T00:00:00",
        "content": "Test message",
    })
    with patch('tools.sessions.neo4j_client') as mock_neo4j:
        mock_neo4j.get_active_sessions.return_value = []
        result = handle_list_sessions(None, mock_redis)
        assert len(result["waiting_on"]) == 1
        assert result["waiting_on"][0]["platform"] == "claude"


def test_list_sessions_recommendation(mock_redis):
    with patch('tools.sessions.neo4j_client') as mock_neo4j:
        mock_neo4j.get_active_sessions.return_value = []
        result = handle_list_sessions(None, mock_redis)
        assert result["recommendation"] is not None
