"""Tests for orchestrator integration — payload construction and API interface."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_ingest_transcript_payload():
    """Verify ISMA ingestion payload is correctly constructed."""
    from core.orchestrator import ingest_transcript
    import unittest.mock as mock

    metadata = {
        'batch_id': 'batch_42',
        'tile_hash': 'abc123def456',
        'model': 'deep_think',
        'platform': 'gemini',
    }

    # Mock the requests.post to capture the payload
    with mock.patch('core.orchestrator.requests.post') as mock_post:
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'status': 'accepted',
            'content_hash': 'd7ace856cc31cb23',
            'exchange_count': 1,
        }
        mock_post.return_value = mock_resp

        result = ingest_transcript(
            platform='gemini',
            response_content='This is the AI response...',
            package_metadata=metadata,
            prompt_content='Analyze the following...',
        )

        assert result['success'] is True
        assert result['content_hash'] == 'd7ace856cc31cb23'

        # Verify the payload
        call_args = mock_post.call_args
        payload = call_args.kwargs.get('json') or call_args[1].get('json')
        assert payload['platform'] == 'gemini'
        assert 'hmm_batch_42_gemini_abc123def456' == payload['conversation_id']
        assert len(payload['exchanges']) == 1
        assert payload['exchanges'][0]['prompt'] == 'Analyze the following...'
        assert payload['exchanges'][0]['response'] == 'This is the AI response...'


def test_heartbeat_payload():
    """Verify heartbeat sends correct agent_id."""
    from core.orchestrator import heartbeat
    import unittest.mock as mock

    with mock.patch('core.orchestrator.requests.post') as mock_post:
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = heartbeat(status='active', current_task='cycle_5')
        assert result is True

        call_args = mock_post.call_args
        payload = call_args.kwargs.get('json') or call_args[1].get('json')
        assert payload['status'] == 'active'
        assert payload['current_task'] == 'cycle_5'


def test_report_completion_payload():
    """Verify completion report structure."""
    from core.orchestrator import report_completion
    import unittest.mock as mock

    with mock.patch('core.orchestrator.requests.post') as mock_post:
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = report_completion(
            task_id='hmm-12345',
            result='Extracted 5000 chars from gemini',
            status='completed',
            metadata={'platform': 'gemini', 'chars': 5000},
        )
        assert result is True


def test_notify_agent_payload():
    """Verify notify sends correct payload."""
    from core.orchestrator import notify_agent
    import unittest.mock as mock

    with mock.patch('core.orchestrator.requests.post') as mock_post:
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = notify_agent(
            to='claude-main',
            text='Deploy unified_bot to Mira',
        )
        assert result is True

        call_args = mock_post.call_args
        payload = call_args.kwargs.get('json') or call_args[1].get('json')
        assert payload['to'] == 'claude-main'
        assert 'Deploy' in payload['text']


def test_platform_name_mapping():
    """Verify platform → ISMA platform mapping."""
    from core.orchestrator import ingest_transcript
    import unittest.mock as mock

    for platform, expected in [
        ('chatgpt', 'chatgpt'),
        ('gemini', 'gemini'),
        ('claude', 'claude_chat'),
        ('grok', 'grok'),
        ('perplexity', 'perplexity'),
    ]:
        with mock.patch('core.orchestrator.requests.post') as mock_post:
            mock_resp = mock.Mock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {'content_hash': 'test'}
            mock_post.return_value = mock_resp

            ingest_transcript(platform, 'response', {'batch_id': '1', 'tile_hash': 'x'})

            payload = mock_post.call_args.kwargs.get('json') or mock_post.call_args[1].get('json')
            assert payload['platform'] == expected, f"{platform} → {payload['platform']}, expected {expected}"
