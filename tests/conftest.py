"""Shared test fixtures and mocks."""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_redis():
    """Mock Redis client with basic get/set/delete."""
    client = MagicMock()
    store = {}
    expiries = {}

    def mock_get(key):
        return store.get(key)

    def mock_set(key, value):
        store[key] = value

    def mock_setex(key, ttl, value):
        store[key] = value
        expiries[key] = ttl

    def mock_delete(*keys):
        for item in keys:
            store.pop(item, None)
            expiries.pop(item, None)

    def mock_sadd(key, value):
        bucket = store.setdefault(key, set())
        bucket.add(value)

    def mock_smembers(key):
        return set(store.get(key, set()))

    def mock_srem(key, value):
        bucket = store.get(key)
        if isinstance(bucket, set):
            bucket.discard(value)

    def mock_ttl(key):
        return expiries.get(key, -1)

    def mock_scan(cursor, match=None, count=100):
        if match:
            prefix = match.split('*', 1)[0]
            keys = [k for k in store if k.startswith(prefix)]
        else:
            keys = list(store)
        return (0, keys)

    def mock_lpop(key):
        return None

    def mock_rpush(key, value):
        pass

    client.get = mock_get
    client.set = mock_set
    client.setex = mock_setex
    client.delete = mock_delete
    client.sadd = mock_sadd
    client.smembers = mock_smembers
    client.srem = mock_srem
    client.ttl = mock_ttl
    client.scan = mock_scan
    client.lpop = mock_lpop
    client.rpush = mock_rpush
    client._store = store
    return client


@pytest.fixture
def mock_neo4j():
    """Mock Neo4j module."""
    mod = MagicMock()
    mod.create_session.return_value = "test-session-id"
    mod.add_message.return_value = "test-message-id"
    mod.get_active_sessions.return_value = []
    return mod
