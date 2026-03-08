#!/usr/bin/env python3
"""Debug full handle_inspect flow on macOS."""
from __future__ import annotations
import sys, os, json, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock redis client that stores in-memory
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
    print("=== Testing handle_inspect('chatgpt') ===")
    result = handle_inspect('chatgpt', MockRedis(), scroll='none')

    print(f"success: {result.get('success')}")
    print(f"error: {result.get('error')}")
    print(f"url: {result.get('url')}")
    print(f"state: {result.get('state')}")

    controls = result.get('controls', [])
    print(f"controls count: {len(controls)}")
    if controls:
        print("First 5 elements:")
        for e in controls[:5]:
            print(f"  {e.get('role')}: {e.get('name','')[:60]} @ ({e.get('x')},{e.get('y')})")

    print(f"\nattachments: {result.get('attachments')}")
    print(f"structure_change: {result.get('structure_change')}")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
