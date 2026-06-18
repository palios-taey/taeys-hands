#!/usr/bin/env python3
"""Validate that a consultation display is ready before browser automation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from consultation_v2.display_readiness import available_platforms, check


def main() -> int:
    platforms = available_platforms()
    if len(sys.argv) not in {2, 3} or sys.argv[1] not in platforms:
        print(f'usage: {sys.argv[0]} <{"|".join(platforms)}> [--json]')
        return 64

    verdict = check(sys.argv[1])
    if len(sys.argv) == 3:
        if sys.argv[2] != '--json':
            print(f'usage: {sys.argv[0]} <{"|".join(platforms)}> [--json]')
            return 64
        print(json.dumps(verdict, indent=2, sort_keys=True))
    else:
        print(
            f"READINESS [{verdict['platform']} {verdict['display']}] "
            f"ready={verdict['ready']} windows={verdict['windows']} "
            f"tabs={verdict['tabs']} tree={verdict['tree']} "
            f"url={verdict['url']} expected_host={verdict['expected_host']}"
        )
        for issue in verdict['issues']:
            print('  ISSUE:', issue)
        for resolution in verdict.get('resolutions') or []:
            print('  RESOLUTION:', resolution)
    return 0 if verdict['ready'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
