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


def _push_redis(platform: str, event_type: str, body: str, url: str | None = None):
    """Push a notification to Redis inbox. Logs errors to stderr instead of swallowing."""
    try:
        import redis
        r = redis.Redis(
            host=os.environ.get('REDIS_HOST', '127.0.0.1'),
            port=int(os.environ.get('REDIS_PORT', '6379')),
            decode_responses=True,
        )
        msg = {
            'from': 'monitor',
            'type': event_type,
            'body': body,
            'platform': platform,
        }
        if url is not None:
            msg['url'] = url
        r.lpush('taey:taeys-hands:inbox', json.dumps(msg))
    except Exception as e:
        print(json.dumps({'event': 'redis_error', 'error': str(e)}), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Monitor platform for response completion')
    _platforms = sorted(p.stem for p in (Path(__file__).resolve().parents[1] / 'consultation_v2' / 'platforms').glob('*.yaml'))
    parser.add_argument('platform', choices=_platforms)
    parser.add_argument('--interval', type=float, default=3.0, help='Poll interval in seconds')
    parser.add_argument('--absent', type=int, default=3, help='Required consecutive absent polls')
    parser.add_argument('--timeout', type=float, default=3600, help='Max wait time in seconds')
    parser.add_argument('--stop-key', default='stop_button', help='YAML key for stop button')
    args = parser.parse_args()

    display = setup_display(args.platform)

    # Load platform YAML — values as defaults, CLI args override
    from consultation_v2.yaml_contract import load_platform_yaml
    cfg = load_platform_yaml(args.platform)
    mon_cfg = cfg.get('workflow', {}).get('monitor', {})

    interval = args.interval if args.interval != parser.get_default('interval') else mon_cfg.get('poll_interval', 3.0)
    required_absent = args.absent if args.absent != parser.get_default('absent') else mon_cfg.get('required_stop_absent_cycles', 3)
    stop_key = args.stop_key if args.stop_key != parser.get_default('stop_key') else mon_cfg.get('stop_key', 'stop_button')
    complete_key = mon_cfg.get('complete_key', None)
    timeout = args.timeout if args.timeout != parser.get_default('timeout') else mon_cfg.get('timeout', 3600)

    # NOW import V2 modules
    from consultation_v2.snapshot import build_snapshot

    seen_stop = False
    absent_cycles = 0
    start = time.time()

    print(json.dumps({
        'event': 'monitor_start',
        'platform': args.platform,
        'display': display,
        'interval': interval,
        'required_absent': required_absent,
        'stop_key': stop_key,
        'complete_key': complete_key,
        'timeout': timeout,
    }))

    while time.time() - start < timeout:
        try:
            _, _, snap = build_snapshot(args.platform)

            # Fast-path: response already complete before we saw stop.
            # Only trigger after at least one full poll interval to avoid
            # false positives from pre-existing copy buttons on the page.
            elapsed = time.time() - start
            if complete_key and not seen_stop and elapsed >= interval and snap.has(complete_key):
                result = {
                    'event': 'complete',
                    'method': 'fast_path_complete_key',
                    'platform': args.platform,
                    'elapsed': round(elapsed, 1),
                    'url': snap.url,
                }
                print(json.dumps(result))
                _push_redis(args.platform, 'RESPONSE_COMPLETE',
                            f'{args.platform} response complete via fast-path ({round(elapsed)}s). URL: {snap.url}',
                            snap.url)
                return 0

            has_stop = snap.has(stop_key)

            if has_stop:
                seen_stop = True
                absent_cycles = 0
            elif seen_stop:
                absent_cycles += 1
                if absent_cycles >= required_absent:
                    # If complete_key defined, verify it's present before declaring complete
                    if complete_key and not snap.has(complete_key):
                        # Stop disappeared but complete_key not yet visible — keep waiting
                        elapsed = time.time() - start
                        print(json.dumps({
                            'event': 'poll',
                            'platform': args.platform,
                            'status': f'stop_gone_awaiting_complete_key',
                            'elapsed': round(elapsed, 1),
                            'has_stop': False,
                        }), flush=True)
                        time.sleep(interval)
                        continue

                    elapsed = time.time() - start
                    result = {
                        'event': 'complete',
                        'method': 'stop_disappeared',
                        'platform': args.platform,
                        'elapsed': round(elapsed, 1),
                        'absent_cycles': absent_cycles,
                        'url': snap.url,
                    }
                    print(json.dumps(result))
                    _push_redis(args.platform, 'RESPONSE_COMPLETE',
                                f'{args.platform} response complete ({round(elapsed)}s). URL: {snap.url}',
                                snap.url)
                    return 0

            status = 'generating' if has_stop else ('waiting' if not seen_stop else f'absent:{absent_cycles}/{required_absent}')
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

        time.sleep(interval)

    result = {
        'event': 'timeout',
        'platform': args.platform,
        'elapsed': round(time.time() - start, 1),
    }
    print(json.dumps(result))
    _push_redis(args.platform, 'MONITOR_TIMEOUT',
                f'{args.platform} monitor timed out after {round(time.time() - start)}s')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
