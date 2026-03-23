"""Pipeline regression tests — anchors working behavior against accidental breakage.

These tests run WITHOUT a display, Firefox, or live AT-SPI. They verify the
control flow logic (plan gates, audit gates, tool registration) using mocks.
"""
import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Test 1: Plan create sets Redis key ──────────────────────────────────────

def test_plan_create_sets_redis_key(mock_redis):
    """Creating a plan must set plan:current:{platform} in Redis."""
    from tools.plan import handle_plan

    result = handle_plan('claude', 'send_message', {
        'session': 'new',
        'message': 'test',
        'model': 'N/A',
        'mode': 'N/A',
        'tools': ['none'],
        'attachments': [],
    }, mock_redis)

    assert result.get('success') is True
    plan_id = result.get('plan_id')
    assert plan_id

    # The plan:current:claude key must be set
    found = False
    for k, v in mock_redis._store.items():
        if 'plan:current:claude' in k:
            found = True
            assert v == plan_id
            break
    assert found, f"plan:current:claude not found in Redis. Keys: {list(mock_redis._store.keys())}"


# ── Test 2: Audit blocks send without audit_passed ──────────────────────────

def test_audit_blocks_send_without_audit_passed(mock_redis):
    """send_message must be blocked when audit_passed is not True."""
    from tools.send import _check_audit_gate
    from tools.plan import handle_plan

    # Create a plan but do NOT audit it
    result = handle_plan('claude', 'send_message', {
        'session': 'new',
        'message': 'test',
        'model': 'N/A',
        'mode': 'N/A',
        'tools': ['none'],
        'attachments': [],
    }, mock_redis)
    assert result.get('success')

    # Audit gate should block
    error = _check_audit_gate('claude', mock_redis)
    assert error is not None
    assert 'audit' in error.lower()


# ── Test 3: Audit passes send with audit_passed ─────────────────────────────

def test_audit_passes_send_with_audit_passed(mock_redis):
    """send_message must NOT be blocked by audit gate when audit_passed=True."""
    from tools.send import _check_audit_gate
    from tools.plan import handle_plan

    # Create and audit a plan
    result = handle_plan('claude', 'send_message', {
        'session': 'new',
        'message': 'test',
        'model': 'N/A',
        'mode': 'N/A',
        'tools': ['none'],
        'attachments': [],
    }, mock_redis)
    plan_id = result['plan_id']

    # Manually set audit_passed in the plan data
    for k, v in list(mock_redis._store.items()):
        if plan_id in k and 'current' not in k and 'plan:claude' not in k:
            plan = json.loads(v)
            plan['audit_passed'] = True
            mock_redis._store[k] = json.dumps(plan)

    # Audit gate should pass
    error = _check_audit_gate('claude', mock_redis)
    assert error is None


# ── Test 4: Grok fresh_session triggers F5 on stale URL ────────────────────

def test_grok_fresh_session_triggers_reload():
    """When fresh_session=True and Grok AT-SPI URL contains /c/, F5 must fire."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    with patch('tools.inspect.inp') as mock_inp, \
         patch('tools.inspect.atspi') as mock_atspi:

        # switch_to_platform succeeds
        mock_inp.switch_to_platform.return_value = True
        mock_inp.clipboard_paste.return_value = True
        mock_inp.press_key.return_value = True

        # AT-SPI returns a stale conversation URL
        mock_ff = MagicMock()
        mock_atspi.find_firefox_for_platform.return_value = mock_ff
        mock_doc = MagicMock()
        mock_atspi.get_platform_document.return_value = mock_doc
        mock_atspi.get_document_url.return_value = 'https://grok.com/c/old-convo-id'
        mock_atspi.detect_display.return_value = ':0'

        from tools.inspect import handle_inspect
        handle_inspect('grok', mock_redis, fresh_session=True)

        # F5 must have been called
        f5_calls = [c for c in mock_inp.press_key.call_args_list if c == call('F5')]
        assert len(f5_calls) > 0, (
            f"F5 not called. press_key calls: {mock_inp.press_key.call_args_list}"
        )


# ── Test 5: All 12 tool names are registered ───────────────────────────────

def test_tool_names_stable():
    """All 12 expected MCP tool names must be present in get_tools()."""
    from server import get_tools

    tools = get_tools()
    tool_names = {t['name'] for t in tools}

    expected = {
        'taey_inspect', 'taey_click', 'taey_prepare', 'taey_plan',
        'taey_send_message', 'taey_quick_extract', 'taey_extract_history',
        'taey_attach', 'taey_select_dropdown', 'taey_list_sessions',
        'taey_monitors', 'taey_respawn_monitor',
    }

    missing = expected - tool_names
    assert not missing, f"Missing tools: {missing}. Found: {sorted(tool_names)}"
