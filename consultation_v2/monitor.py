#!/usr/bin/env python3
"""consultation_v2/monitor.py — Run the platform's monitor sequence to
detect response completion, then push the result to the Redis inbox.

The monitor is a separate process spawned by consult.py after send-confirm.
It runs workflow.monitor.sequence (YAML-declared) which typically waits
for stop_button absence and then verifies complete_key presence. All
platform-specific behavior lives in YAML primitive steps; this process
is a thin runner that dispatches the sequence and emits the appropriate
RESPONSE_COMPLETE / RESPONSE_UNVERIFIED notification.

Usage:
    python3 -m consultation_v2.monitor chatgpt
    python3 -m consultation_v2.monitor gemini --timeout 7200
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

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
    if platform not in displays:
        print(json.dumps({'error': f'Platform {platform!r} not in PLATFORM_DISPLAYS'}))
        sys.exit(1)
    display = displays[platform]
    os.environ['DISPLAY'] = display

    a11y_file = f'/tmp/a11y_bus_{display}'
    try:
        bus = Path(a11y_file).read_text().strip()
    except FileNotFoundError:
        print(json.dumps({'error': f'AT-SPI bus file missing: {a11y_file}'}))
        sys.exit(1)
    if bus:
        os.environ['AT_SPI_BUS_ADDRESS'] = bus

    session_file = f'/tmp/dbus_session_bus_{display}'
    try:
        session_bus = Path(session_file).read_text().strip()
    except FileNotFoundError:
        print(json.dumps({'error': f'Session bus file missing: {session_file}. '
                                    f'Reusing the AT-SPI bus as the session bus is a fallback — disabled.'}))
        sys.exit(1)
    if not session_bus:
        print(json.dumps({'error': f'Session bus file empty: {session_file}'}))
        sys.exit(1)
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = session_bus

    disp_num = display.lstrip(':')
    os.environ['PLATFORM_DISPLAYS'] = f'{platform}:{disp_num}'
    os.environ['GTK_USE_PORTAL'] = '0'
    return display


def _push_redis(platform: str, event_type: str, body: str, url: str | None = None):
    """Push a notification to the taeys-hands Redis inbox. Logs errors
    to stderr; never swallow silently."""
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
    parser = argparse.ArgumentParser(description='Run platform monitor sequence to detect response completion')
    _platforms = sorted(p.stem for p in (Path(__file__).resolve().parents[1] / 'consultation_v2' / 'platforms').glob('*.yaml'))
    parser.add_argument('platform', choices=_platforms)
    args = parser.parse_args()

    display = setup_display(args.platform)

    from consultation_v2.yaml_contract import load_platform_yaml
    cfg = load_platform_yaml(args.platform)
    mon_cfg = cfg.get('workflow', {}).get('monitor', {})
    mon_sequence = mon_cfg.get('sequence')
    if not mon_sequence:
        print(json.dumps({'event': 'fatal', 'error': 'workflow.monitor.sequence missing from YAML'}))
        _push_redis(args.platform, 'MONITOR_FATAL', 'workflow.monitor.sequence missing')
        return 1

    from consultation_v2.primitives import run_sequence
    from consultation_v2.runtime import ConsultationRuntime
    rt = ConsultationRuntime(args.platform)

    print(json.dumps({
        'event': 'monitor_start',
        'platform': args.platform,
        'display': display,
        'steps': len(mon_sequence),
    }), flush=True)

    start = time.time()
    ctx = {
        'platform': args.platform,
        'runtime': rt,
        'cfg': cfg,
        'message': '',
        'vars': {},
    }
    result = run_sequence(ctx, mon_sequence, step_name='monitor')
    elapsed = round(time.time() - start, 1)

    # The monitor sequence typically ends in wait_for_indicator on
    # response_complete indicators. If that step succeeded, generation
    # finished AND the complete indicator is live → RESPONSE_COMPLETE.
    # If the terminal complete-indicator check was optional (skipped
    # via absent_optional / timeout), generation stopped but completion
    # isn't verified → RESPONSE_UNVERIFIED. YAML sets `into: complete_key_present`
    # on the final wait step OR the platform YAML can declare the
    # contract differently.
    complete = ctx['vars'].get('complete_key_present', None)
    if not result['ok']:
        # Non-ok means a hard failure in the sequence (e.g. inspect error).
        _push_redis(args.platform, 'MONITOR_FATAL',
                    f'{args.platform} monitor sequence failed: {result["error"]}')
        print(json.dumps({'event': 'fatal', 'error': result['error'],
                          'elapsed': elapsed}), flush=True)
        return 1

    # Final URL for the notification body
    try:
        from consultation_v2.consult import inspect_platform
        snap = inspect_platform(args.platform)
        url = snap.get('url', '') or ''
    except Exception:
        url = ''

    if complete is False:
        # Explicit unverified — sequence set complete_key_present=False
        # (e.g., scroll-retry primitive couldn't find the complete key).
        _push_redis(args.platform, 'RESPONSE_UNVERIFIED',
                    f'{args.platform} response stopped; completion unverified '
                    f'({elapsed}s, complete_key absent). URL: {url}',
                    url)
        print(json.dumps({'event': 'completion_unverified', 'elapsed': elapsed, 'url': url}),
              flush=True)
        return 2

    _push_redis(args.platform, 'RESPONSE_COMPLETE',
                f'{args.platform} response complete ({elapsed}s). URL: {url}', url)
    print(json.dumps({'event': 'complete', 'elapsed': elapsed, 'url': url}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
