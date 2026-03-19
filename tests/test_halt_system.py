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


def test_halt_global_sets_flag():
    from core.halt import halt_global, check_halt, clear_halt
    redis = FakeRedis()

    # No halt initially
    assert check_halt('chatgpt', redis) is None

    # Set global halt
    halt_global("Firefox crashed", redis, 'chatgpt')

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


def test_halt_platform_only_blocks_that_platform():
    from core.halt import halt_platform, check_halt, clear_platform_halt
    redis = FakeRedis()

    halt_platform('chatgpt', "UI changed", redis)

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


def test_no_redis_doesnt_crash():
    from core.halt import halt_global, halt_platform, check_halt
    # None redis should not raise
    halt_global("test", None)
    halt_platform("test", "test", None)
    assert check_halt("test", None) is None
