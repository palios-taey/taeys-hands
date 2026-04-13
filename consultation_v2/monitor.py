#!/usr/bin/env python3
"""consultation_v2/monitor.py — Poll for response completion on a platform.

Polls AT-SPI tree for stop button disappearance. When stop button has been
absent for required_absent consecutive polls, declares complete.

Also checks for copy button as fast-path (response already done).

Usage:
    python3 -m consultation_v2.monitor chatgpt
    python3 -m consultation_v2.monitor gemini --interval 3 --absent 4
    python3 -m consultation_v2.monitor perplexity --timeout 7200
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ---- Env setup BEFORE any AT-SPI imports ----
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

_ENV_PATH = _PROJECT_ROOT / '.env'
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())


def _read_platform_displays() -> dict:
    raw = os.environ.get('PLATFORM_DISPLAYS', '')
    if not raw:
        try:
            for line in (_PROJECT_ROOT / '.env').read_text().splitlines():
                if line.strip().startswith('PLATFORM_DISPLAYS='):
                    raw = line.strip().split('=', 1)[1].strip()
                    break
        except FileNotFoundError:
            pass
    result = {}
    if raw:
        for pair in raw.split(','):
            pair = pair.strip()
            if ':' in pair:
                plat, dnum = pair.rsplit(':', 1)
                result[plat.strip()] = f':{dnum.strip()}'
    return result


def setup_display(platform: str) -> str:
    displays = _read_platform_displays()
    display = displays.get(platform, os.environ.get('DISPLAY', ':0'))
    os.environ['DISPLAY'] = display

    a11y_file = f'/tmp/a11y_bus_{display}'
    try:
        bus = Path(a11y_file).read_text().strip()
        if bus:
            os.environ['AT_SPI_BUS_ADDRESS'] = bus
    except FileNotFoundError:
        pass

    session_file = f'/tmp/dbus_session_bus_{display}'
    try:
        session_bus = Path(session_file).read_text().strip()
        if session_bus:
            os.environ['DBUS_SESSION_BUS_ADDRESS'] = session_bus
    except FileNotFoundError:
        if os.environ.get('AT_SPI_BUS_ADDRESS'):
            os.environ['DBUS_SESSION_BUS_ADDRESS'] = os.environ['AT_SPI_BUS_ADDRESS']

    disp_num = display.lstrip(':')
    os.environ['PLATFORM_DISPLAYS'] = f'{platform}:{disp_num}'
    os.environ['GTK_USE_PORTAL'] = '0'
    return display


def main():
    parser = argparse.ArgumentParser(description='Monitor platform for response completion')
    parser.add_argument('platform', choices=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'])
    parser.add_argument('--interval', type=float, default=3.0, help='Poll interval in seconds')
    parser.add_argument('--absent', type=int, default=3, help='Required consecutive absent polls')
    parser.add_argument('--timeout', type=float, default=3600, help='Max wait time in seconds')
    parser.add_argument('--stop-key', default='stop_button', help='YAML key for stop button')
    args = parser.parse_args()

    display = setup_display(args.platform)

    # NOW import V2 modules
    from consultation_v2.snapshot import build_snapshot

    seen_stop = False
    absent_cycles = 0
    start = time.time()

    print(json.dumps({
        'event': 'monitor_start',
        'platform': args.platform,
        'display': display,
        'interval': args.interval,
        'required_absent': args.absent,
        'timeout': args.timeout,
    }))

    while time.time() - start < args.timeout:
        try:
            _, _, snap = build_snapshot(args.platform)
            has_stop = snap.has(args.stop_key)

            if has_stop:
                seen_stop = True
                absent_cycles = 0
            elif seen_stop:
                absent_cycles += 1
                if absent_cycles >= args.absent:
                    elapsed = time.time() - start
                    print(json.dumps({
                        'event': 'complete',
                        'method': 'stop_disappeared',
                        'platform': args.platform,
                        'elapsed': round(elapsed, 1),
                        'absent_cycles': absent_cycles,
                        'url': snap.url,
                    }))
                    return 0

            status = 'generating' if has_stop else ('waiting' if not seen_stop else f'absent:{absent_cycles}/{args.absent}')
            elapsed = time.time() - start
            print(json.dumps({
                'event': 'poll',
                'platform': args.platform,
                'status': status,
                'elapsed': round(elapsed, 1),
                'has_stop': has_stop,
            }), flush=True)

        except Exception as e:
            print(json.dumps({
                'event': 'fatal',
                'platform': args.platform,
                'error': str(e),
            }), flush=True)
            return 1

        time.sleep(args.interval)

    print(json.dumps({
        'event': 'timeout',
        'platform': args.platform,
        'elapsed': round(time.time() - start, 1),
    }))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
