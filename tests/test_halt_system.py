"""Tests for 6-sigma halt system."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeRedis:
    """Minimal Redis mock for testing."""
    def __init__(self):
        self._store = {}

    def set(self, key, value):
        self._store[key] = value

    def get(self, key):
        return self._store.get(key)

    def delete(self, key):
        self._store.pop(key, None)

    def exists(self, key):
        return key in self._store

    def setex(self, key, ttl, value):
        self._store[key] = value

    def ping(self):
        return True


@pytest.fixture(autouse=True)
def isolated_notify_transport(monkeypatch):
    import core.halt as halt

    calls = {'post': [], 'run': []}

    class FakeResponse:
        status_code = 200

    class FakeCompletedProcess:
        returncode = 0
        stdout = b''
        stderr = b''

    def fake_post(url, **kwargs):
        calls['post'].append({'url': url, **kwargs})
        return FakeResponse()

    def fake_run(args, **kwargs):
        calls['run'].append({'args': args, **kwargs})
        return FakeCompletedProcess()

    monkeypatch.setenv('TAEY_NODE_ID', 'taeys-hands')
    monkeypatch.delenv('NOTIFY_TARGET', raising=False)
    monkeypatch.setattr(halt, 'ORCH_KEY', '')
    monkeypatch.setattr(halt.requests, 'post', fake_post)
    monkeypatch.setattr(halt.subprocess, 'run', fake_run)
    yield calls


def test_halt_global_sets_flag(isolated_notify_transport):
    from core.halt import halt_global, check_halt, clear_halt
    redis = FakeRedis()

    # No halt initially
    assert check_halt('chatgpt', redis) is None

    # Set global halt
    halt_global("Firefox crashed", redis, 'chatgpt')
    assert isolated_notify_transport['post'] == []
    assert isolated_notify_transport['run'][0]['args'][1] == 'taeys-hands'
    assert isolated_notify_transport['run'][0]['args'][1] != 'weaver'

    # Should block ALL platforms
    halt = check_halt('chatgpt', redis)
    assert halt is not None
    assert halt['level'] == 'global'
    assert 'Firefox crashed' in halt['reason']

    halt = check_halt('gemini', redis)
    assert halt is not None  # Global blocks all

    # Clear
    clear_halt(redis)
    assert check_halt('chatgpt', redis) is None


def test_halt_platform_only_blocks_that_platform(isolated_notify_transport):
    from core.halt import halt_platform, check_halt, clear_platform_halt
    redis = FakeRedis()

    halt_platform('chatgpt', "UI changed", redis)
    assert isolated_notify_transport['post'] == []
    assert isolated_notify_transport['run'][0]['args'][1] == 'taeys-hands'

    # ChatGPT should be halted
    halt = check_halt('chatgpt', redis)
    assert halt is not None
    assert halt['platform'] == 'chatgpt'

    # Gemini should NOT be halted
    assert check_halt('gemini', redis) is None

    # Clear
    clear_platform_halt('chatgpt', redis)
    assert check_halt('chatgpt', redis) is None


def test_halt_with_drift_data():
    from core.halt import halt_platform, check_halt
    redis = FakeRedis()

    drift = {
        'old_hash': 'abc123',
        'new_hash': 'def456',
        'unknown_elements': [{'name': 'New Button', 'role': 'push button'}],
    }
    halt_platform('grok', "Structure drift", redis, drift_data=drift)

    halt = check_halt('grok', redis)
    assert halt is not None
    assert 'drift_data' in halt
    assert halt['drift_data']['old_hash'] == 'abc123'


def test_no_redis_doesnt_crash(isolated_notify_transport):
    from core.halt import halt_global, halt_platform, check_halt
    # None redis should not raise
    halt_global("test", None)
    halt_platform("test", "test", None)
    assert check_halt("test", None) is None
    assert len(isolated_notify_transport['run']) == 2
    assert {call['args'][1] for call in isolated_notify_transport['run']} == {'taeys-hands'}


def test_display_node_routes_to_operator(monkeypatch, isolated_notify_transport):
    from core.halt import halt_platform

    monkeypatch.setenv('TAEY_NODE_ID', 'taeys-hands-d6')
    halt_platform('perplexity', "proof", FakeRedis())

    assert isolated_notify_transport['run'][0]['args'][1] == 'taeys-hands'


def test_explicit_notify_target_override(monkeypatch, isolated_notify_transport):
    from core.halt import halt_global

    monkeypatch.setenv('NOTIFY_TARGET', 'gatekeeper')
    halt_global("proof", FakeRedis(), 'chatgpt')

    assert isolated_notify_transport['run'][0]['args'][1] == 'gatekeeper'


def test_api_notify_transport_is_stubbed(monkeypatch, isolated_notify_transport):
    import core.halt as halt

    monkeypatch.setattr(halt, 'ORCH_KEY', 'dummy-key')
    halt.halt_platform('gemini', "api proof", FakeRedis())

    assert isolated_notify_transport['run'] == []
    assert len(isolated_notify_transport['post']) == 1
    post = isolated_notify_transport['post'][0]
    assert post['url'] == 'https://orch-api.taey.ai/api/notify'
    assert post['json']['target'] == 'taeys-hands'
    assert post['json']['target'] != 'weaver'


def test_cli_notify_failure_raises(monkeypatch):
    import core.halt as halt

    class FailedProcess:
        returncode = 7
        stdout = b''
        stderr = b'notify failed'

    monkeypatch.setattr(halt.subprocess, 'run', lambda *args, **kwargs: FailedProcess())

    with pytest.raises(RuntimeError, match='taey-notify failed'):
        halt.halt_global("proof", FakeRedis(), 'chatgpt')
