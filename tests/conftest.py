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

    def mock_get(key):
        return store.get(key)

    def mock_set(key, value):
        store[key] = value

    def mock_setex(key, ttl, value):
        store[key] = value

    def mock_delete(key):
        store.pop(key, None)

    def mock_scan(cursor, match=None, count=100):
        keys = [k for k in store if k.startswith(match.replace('*', ''))] if match else list(store)
        return (0, keys)

    def mock_lpop(key):
        return None

    def mock_rpush(key, value):
        pass

    client.get = mock_get
    client.set = mock_set
    client.setex = mock_setex
    client.delete = mock_delete
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
