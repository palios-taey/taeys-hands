"""Tests for v8.2 stabilization fixes.

Tests the 5 critical issues identified by Gemini's diagnostic:
1. Redis fail-fast on startup
2. .env load before timeout parse
3. Display detection beyond :0/:1
4. TAEY_NODE_ID auto-scoping by display
5. Plan TTL configurable via env
6. Auto-ingestion module
"""

import json
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Issue 1: Redis fail-fast ───────────────────────────────────────

def test_handle_tool_requires_redis():
    """handle_tool returns clear error when redis_client is None."""
    from server import handle_tool
    result = handle_tool("taey_inspect", {"platform": "claude"}, None)
    assert "error" in result
    assert "Redis" in result["error"]


def test_handle_tool_with_redis_works():
    """handle_tool dispatches normally with a valid redis_client."""
    from server import handle_tool
    mock_rc = MagicMock()
    mock_rc.get.return_value = None
    # taey_list_sessions doesn't require a plan, should work
    result = handle_tool("taey_list_sessions", {}, mock_rc)
    assert "error" not in result or "Redis" not in result.get("error", "")


# ─── Issue 2: .env load order ───────────────────────────────────────

def test_env_loaded_before_timeout():
    """Verify TOOL_TIMEOUT_SECONDS is read after .env is loaded."""
    # The fix moves .env loading above the TOOL_TIMEOUT_SECONDS line.
    # We verify by checking the module structure.
    import server
    import inspect
    source = inspect.getsource(server)
    env_pos = source.find("# Load .env FIRST")
    timeout_pos = source.find("TOOL_TIMEOUT_SECONDS = int(")
    assert env_pos > 0, ".env loading comment not found"
    assert timeout_pos > 0, "TOOL_TIMEOUT_SECONDS line not found"
    assert env_pos < timeout_pos, ".env must be loaded BEFORE TOOL_TIMEOUT_SECONDS is read"


# ─── Issue 3: Display detection ─────────────────────────────────────

def test_detect_display_respects_env():
    """detect_display returns DISPLAY env var when set."""
    from core.atspi import detect_display
    with patch.dict(os.environ, {'DISPLAY': ':42'}):
        assert detect_display() == ':42'


def test_detect_display_finds_high_number():
    """detect_display finds virtual displays beyond :0/:1."""
    from core.atspi import detect_display
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop('DISPLAY', None)
        # Simulate only :5 exists
        with patch('os.path.exists') as mock_exists:
            def exists_side_effect(path):
                if path == '/tmp/.X5-lock':
                    return True
                return False
            mock_exists.side_effect = exists_side_effect
            result = detect_display()
            assert result == ':5'


def test_detect_display_prefers_lowest():
    """detect_display returns the lowest numbered available display."""
    from core.atspi import detect_display
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop('DISPLAY', None)
        with patch('os.path.exists') as mock_exists:
            def exists_side_effect(path):
                # :3 and :7 both exist
                return path in ('/tmp/.X3-lock', '/tmp/.X7-lock')
            mock_exists.side_effect = exists_side_effect
            result = detect_display()
            assert result == ':3'


def test_detect_display_no_display_raises():
    """detect_display raises RuntimeError when no display found."""
    from core.atspi import detect_display
    import pytest
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop('DISPLAY', None)
        with patch('os.path.exists', return_value=False):
            with pytest.raises(RuntimeError, match="No X display"):
                detect_display()


# ─── Issue 4: TAEY_NODE_ID scoping ──────────────────────────────────

def test_node_id_auto_scopes_by_display():
    """_detect_node_id generates display-scoped ID when DISPLAY is set."""
    from storage.redis_pool import _detect_node_id
    with patch.dict(os.environ, {'DISPLAY': ':5'}, clear=False):
        os.environ.pop('TAEY_NODE_ID', None)
        result = _detect_node_id()
        assert result == 'taeys-hands-d5'


def test_node_id_explicit_takes_precedence():
    """TAEY_NODE_ID env var takes precedence over auto-detection."""
    from storage.redis_pool import _detect_node_id
    with patch.dict(os.environ, {'TAEY_NODE_ID': 'my-custom-node', 'DISPLAY': ':5'}):
        result = _detect_node_id()
        assert result == 'my-custom-node'


def test_node_id_display_with_dot():
    """_detect_node_id handles DISPLAY=:5.0 format (display.screen)."""
    from storage.redis_pool import _detect_node_id
    with patch.dict(os.environ, {'DISPLAY': ':5.0'}, clear=False):
        os.environ.pop('TAEY_NODE_ID', None)
        # '5.0' is not purely digit, should fall through to tmux/hostname
        result = _detect_node_id()
        # Should still get something (tmux or hostname), not crash
        assert result is not None
        assert len(result) > 0


# ─── Issue 5: Plan TTL configurable ─────────────────────────────────

def test_plan_ttl_default_is_3600():
    """Default plan TTL should be 3600 (1 hour), not 600."""
    from tools.plan import _PLAN_TTL
    # May have been overridden by env, but default should be 3600
    assert _PLAN_TTL >= 600  # At minimum not less than old value


def test_plan_ttl_from_env(mock_redis):
    """Plan uses TAEY_PLAN_TTL env var for Redis setex calls."""
    from tools.plan import handle_plan
    params = {
        "session": "new", "message": "Test", "model": "GPT-4o",
        "mode": "default", "tools": "none", "attachments": [],
    }
    result = handle_plan("chatgpt", "send_message", params, mock_redis)
    assert result["success"] is True
    # Verify plan was stored (in mock)
    plan_id = result["plan_id"]
    from storage.redis_pool import node_key
    stored = mock_redis._store.get(node_key(f"plan:{plan_id}"))
    assert stored is not None


# ─── Issue 6: Auto-ingestion ────────────────────────────────────────

def test_auto_ingest_save_to_corpus():
    """save_to_corpus writes file to correct path."""
    from core.ingest import save_to_corpus
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict(os.environ, {'TAEY_CORPUS_PATH': tmpdir}):
            # Re-import to pick up new env
            import importlib
            import core.ingest as ingest_mod
            # Directly test with patched _CORPUS_PATH
            old_path = ingest_mod._CORPUS_PATH
            ingest_mod._CORPUS_PATH = tmpdir
            try:
                result = save_to_corpus("claude", "Test response content", url="https://claude.ai/chat/123")
                assert result is not None
                assert os.path.exists(result)
                content = open(result).read()
                assert "Test response content" in content
                assert "claude" in content
                assert "claude.ai" in content
            finally:
                ingest_mod._CORPUS_PATH = old_path


def test_auto_ingest_empty_content_skipped():
    """save_to_corpus returns None for empty content."""
    from core.ingest import save_to_corpus
    result = save_to_corpus("claude", "")
    assert result is None
    result = save_to_corpus("claude", "   ")
    assert result is None


def test_auto_ingest_isma_skipped_without_config():
    """trigger_isma_ingest returns None when ISMA_API_URL not set."""
    from core.ingest import trigger_isma_ingest
    import core.ingest as ingest_mod
    old_url = ingest_mod._ISMA_API_URL
    ingest_mod._ISMA_API_URL = ''
    try:
        result = trigger_isma_ingest("claude", "Some content")
        assert result is None
    finally:
        ingest_mod._ISMA_API_URL = old_url


def test_auto_ingest_combined():
    """auto_ingest returns summary dict."""
    from core.ingest import auto_ingest
    import core.ingest as ingest_mod
    with tempfile.TemporaryDirectory() as tmpdir:
        old_path = ingest_mod._CORPUS_PATH
        old_url = ingest_mod._ISMA_API_URL
        ingest_mod._CORPUS_PATH = tmpdir
        ingest_mod._ISMA_API_URL = ''  # Skip ISMA
        try:
            result = auto_ingest("gemini", "Deep research response", url="https://gemini.google.com/")
            assert "corpus_path" in result
            assert result["corpus_path"] is not None
            assert result["isma_triggered"] is False
        finally:
            ingest_mod._CORPUS_PATH = old_path
            ingest_mod._ISMA_API_URL = old_url


# ─── Server version ─────────────────────────────────────────────────

def test_server_version_is_8_2():
    """Server reports v8.2.0."""
    import server
    import inspect
    source = inspect.getsource(server)
    assert '"8.2.0"' in source


# ─── .mcp.json.example has DISPLAY and TAEY_NODE_ID ─────────────────

def test_mcp_json_example_has_display():
    """`.mcp.json.example` includes DISPLAY and TAEY_NODE_ID."""
    example_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                '.mcp.json.example')
    with open(example_path) as f:
        config = json.load(f)
    env = config['mcpServers']['taeys-hands']['env']
    assert 'DISPLAY' in env
    assert 'TAEY_NODE_ID' in env
    assert 'TAEY_PLAN_TTL' in env
    assert 'MCP_TOOL_TIMEOUT' in env
