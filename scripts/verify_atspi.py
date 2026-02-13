#!/usr/bin/env python3
"""
Verify AT-SPI + Firefox accessibility is working.

Run: python3 scripts/verify_atspi.py
"""

import os
import sys

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.atspi import detect_display, find_firefox, get_platform_document
from core.platforms import URL_PATTERNS, TAB_SHORTCUTS


def main():
    display = detect_display()
    os.environ['DISPLAY'] = display
    print(f"DISPLAY: {display}")

    firefox = find_firefox()
    if not firefox:
        print("FAIL: Firefox not found in AT-SPI desktop tree")
        print("  - Is Firefox running?")
        print("  - Is accessibility enabled? (about:config -> accessibility.force_disabled = 0)")
        sys.exit(1)

    print(f"OK: Firefox found - {firefox.get_name()}")

    # Check for platform documents
    found = []
    for platform, pattern in URL_PATTERNS.items():
        doc = get_platform_document(firefox, platform)
        if doc:
            found.append(platform)
            print(f"OK: {platform} tab found (shortcut: {TAB_SHORTCUTS.get(platform, 'N/A')})")

    if not found:
        print("\nWARN: No platform tabs found. Open some chat platforms in Firefox.")
    else:
        print(f"\nSummary: {len(found)}/{len(URL_PATTERNS)} platforms detected")

    print("\nAT-SPI verification complete.")


if __name__ == '__main__':
    main()
