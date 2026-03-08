#!/usr/bin/env python3
"""Debug handle_inspect with tab switching (scroll=bottom)."""
from __future__ import annotations
import sys, os, json, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class MockRedis:
    def __init__(self):
        self._store = {}
    def get(self, key):
        return self._store.get(key)
    def set(self, key, val, **kw):
        self._store[key] = val
    def setex(self, key, ttl, val):
        self._store[key] = val
    def rpush(self, key, val):
        pass
    def lrange(self, key, start, end):
        return []

try:
    from tools.inspect import handle_inspect

    # Test 1: scroll=bottom (default) — switches tab + scrolls
    print("=== Testing handle_inspect('claude', scroll='bottom') ===")
    result = handle_inspect('claude', MockRedis(), scroll='bottom')
    print(f"success: {result.get('success')}")
    print(f"error: {result.get('error')}")
    print(f"url: {result.get('url', '')[:80]}")
    print(f"elements: {result.get('state', {}).get('element_count', 0)}")

    # Test 2: scroll=none on the switched-to platform
    print("\n=== Testing handle_inspect('claude', scroll='none') ===")
    result2 = handle_inspect('claude', MockRedis(), scroll='none')
    print(f"success: {result2.get('success')}")
    print(f"error: {result2.get('error')}")
    print(f"url: {result2.get('url', '')[:80]}")
    print(f"elements: {result2.get('state', {}).get('element_count', 0)}")

except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
