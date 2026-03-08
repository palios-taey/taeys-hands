#!/usr/bin/env python3
"""Debug get_platform_document — run on macOS to trace the failure."""
from __future__ import annotations
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ax_browser import _get_chrome_tabs_jxa, find_browser, get_platform_document
from core.platforms import URL_PATTERNS

print("=== Debug get_platform_document ===")

# Step 1: Check JXA tab listing
tabs = _get_chrome_tabs_jxa()
print(f"\n1. _get_chrome_tabs_jxa() returned {len(tabs)} tabs:")
for t in tabs:
    print(f"   win={t.get('window')} tab={t.get('tab')} url={t.get('url','')[:80]}")

# Step 2: Check URL pattern matching
print(f"\n2. URL_PATTERNS: {URL_PATTERNS}")
for platform, pattern in URL_PATTERNS.items():
    for tab in tabs:
        url = (tab.get('url') or '').lower()
        if pattern in url:
            print(f"   MATCH: {platform} -> {url[:80]}")

# Step 3: Check find_browser
browser = find_browser()
print(f"\n3. find_browser() = {browser}")

# Step 4: Check get_platform_document for each platform
for platform in ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity']:
    doc = get_platform_document(browser, platform)
    print(f"\n4. get_platform_document('{platform}') = {doc}")

print("\n=== Done ===")
