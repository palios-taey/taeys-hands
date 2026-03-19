"""Tests for YAML drift detection."""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeRedis:
    def __init__(self):
        self._store = {}

    def set(self, key, value):
        self._store[key] = value

    def get(self, key):
        return self._store.get(key)

    def delete(self, key):
        self._store.pop(key, None)

    def setex(self, key, ttl, value):
        self._store[key] = value


def _make_elements(names_roles):
    """Create element dicts from (name, role, y) tuples."""
    return [
        {'name': n, 'role': r, 'x': 100, 'y': y, 'states': []}
        for n, r, y in names_roles
    ]


def test_first_run_stores_baseline():
    from core.drift import store_structure_hash, check_structure_drift
    redis = FakeRedis()

    elements = _make_elements([
        ('Send', 'push button', 900),
        ('Copy', 'push button', 500),
        ('Input', 'entry', 950),
    ])

    # First call: no baseline yet, should store and return None
    drift = check_structure_drift('chatgpt', elements, redis)
    assert drift is None
    assert redis.get('taey:structure_hash:chatgpt') is not None


def test_same_structure_no_drift():
    from core.drift import store_structure_hash, check_structure_drift
    redis = FakeRedis()

    elements = _make_elements([
        ('Send', 'push button', 900),
        ('Copy', 'push button', 500),
        ('Input', 'entry', 950),
    ])

    # Store baseline
    store_structure_hash('chatgpt', elements, redis)

    # Same elements — no drift
    drift = check_structure_drift('chatgpt', elements, redis)
    assert drift is None


def test_changed_structure_detects_drift():
    from core.drift import store_structure_hash, check_structure_drift
    redis = FakeRedis()

    elements_v1 = _make_elements([
        ('Send', 'push button', 900),
        ('Copy', 'push button', 500),
        ('Input', 'entry', 950),
    ])
    elements_v2 = _make_elements([
        ('Send', 'push button', 900),
        ('Copy', 'push button', 500),
        ('Input', 'entry', 950),
        ('New Feature', 'toggle button', 300),  # New button!
    ])

    store_structure_hash('chatgpt', elements_v1, redis)
    drift = check_structure_drift('chatgpt', elements_v2, redis)

    assert drift is not None
    assert drift['old_hash'] != drift['new_hash']


def test_classify_unknown_elements():
    from core.drift import classify_unknown_elements

    # These elements should be classified against chatgpt.yaml
    elements = _make_elements([
        ('Model selector, current model is Pro', 'push button', 100),  # Known
        ('Copy', 'push button', 500),  # Known
        ('Brand New Button', 'push button', 300),  # Unknown!
        ('Home', 'link', 50),  # Known sidebar nav
    ])

    unknown = classify_unknown_elements('chatgpt', elements)
    unknown_names = [e['name'] for e in unknown]

    # "Brand New Button" should be unknown
    assert 'Brand New Button' in unknown_names
    # Known items should NOT be in unknown
    assert not any('Copy' in n for n in unknown_names)


def test_no_redis_doesnt_crash():
    from core.drift import store_structure_hash, check_structure_drift
    elements = _make_elements([('Send', 'push button', 900)])

    # None redis should not raise
    store_structure_hash('chatgpt', elements, None)
    drift = check_structure_drift('chatgpt', elements, None)
    assert drift is None
