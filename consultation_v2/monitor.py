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
    if platform not in displays:
        print(json.dumps({'error': f'Platform {platform!r} not in PLATFORM_DISPLAYS'}))
        sys.exit(1)
    display = displays[platform]
    os.environ['DISPLAY'] = display

    # Bus discovery contract (see consultation_v2/act.py setup_display):
    # - a11y_bus_{display}: file required, contents may be empty (a11y rides
    #   on the session bus on this system). Empty = skip setting the env var.
    # - dbus_session_bus_{display}: always required, must be non-empty.
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
    parser.add_argument('--interval', type=float, default=None, help='Poll interval override')
    parser.add_argument('--absent', type=int, default=None, help='Required absent polls override')
    parser.add_argument('--timeout', type=float, default=None, help='Max wait time override')
    parser.add_argument('--stop-key', default=None, help='YAML key for stop button override')
    parser.add_argument('--seen-stop', action='store_true',
                        help='Caller confirmed stop_button was present at send-confirmation. '
                             'Without this flag the monitor requires stop_key on the first poll '
                             'or fails fatal — this prevents a pre-existing copy_button (chat '
                             'history, homepage) from being misread as completion.')
    args = parser.parse_args()

    display = setup_display(args.platform)

    # Load platform YAML — values as defaults, CLI args override
    from consultation_v2.yaml_contract import load_platform_yaml
    cfg = load_platform_yaml(args.platform)
    mon_cfg = cfg.get('workflow', {}).get('monitor', {})

    # stop_key
    if args.stop_key is not None:
        stop_key = args.stop_key
    elif 'stop_key' in mon_cfg:
        stop_key = mon_cfg['stop_key']
    else:
        print(json.dumps({'event': 'fatal', 'error': 'workflow.monitor.stop_key missing from YAML'}))
        return 1

    # interval
    if args.interval is not None:
        interval = args.interval
    elif 'poll_interval' in mon_cfg:
        interval = mon_cfg['poll_interval']
    else:
        print(json.dumps({'event': 'fatal', 'error': 'workflow.monitor.poll_interval missing from YAML'}))
        return 1

    # required_absent
    if args.absent is not None:
        required_absent = args.absent
    elif 'required_stop_absent_cycles' in mon_cfg:
        required_absent = mon_cfg['required_stop_absent_cycles']
    else:
        print(json.dumps({'event': 'fatal', 'error': 'workflow.monitor.required_stop_absent_cycles missing from YAML'}))
        return 1

    # timeout
    if args.timeout is not None:
        timeout = args.timeout
    elif 'timeout' in mon_cfg:
        timeout = mon_cfg['timeout']
    else:
        print(json.dumps({'event': 'fatal', 'error': 'workflow.monitor.timeout missing from YAML'}))
        return 1

    # complete_key (already fails closed)
    if 'complete_key' not in mon_cfg:
        print(json.dumps({'event': 'fatal', 'error': 'workflow.monitor.complete_key missing from YAML'}))
        return 1
    complete_key = mon_cfg['complete_key']

    # Pre-flight: validate stop_key and complete_key exist in element_map
    element_map = cfg.get('tree', {}).get('element_map', {})
    if stop_key not in element_map:
        print(json.dumps({'event': 'fatal', 'error': f'stop_key {stop_key!r} not in element_map'}))
        _push_redis(args.platform, 'MONITOR_FATAL', f'stop_key {stop_key!r} not in element_map')
        return 1
    if complete_key not in element_map:
        print(json.dumps({'event': 'fatal', 'error': f'complete_key {complete_key!r} not in element_map'}))
        _push_redis(args.platform, 'MONITOR_FATAL', f'complete_key {complete_key!r} not in element_map')
        return 1

    # Load monitor.validation (response_complete) and enforce cross-check
    # against element_map[complete_key]. Previously this YAML block was
    # declared in every platform but never consumed — its indicators could
    # drift silently. Now every indicator name/role must correspond to the
    # live meaning of complete_key at monitor start.
    mon_val_key = mon_cfg.get('validation')
    if not mon_val_key:
        print(json.dumps({'event': 'fatal', 'error': 'workflow.monitor.validation missing from YAML'}))
        _push_redis(args.platform, 'MONITOR_FATAL', 'workflow.monitor.validation missing')
        return 1
    mon_validation = cfg.get('validation', {}).get(mon_val_key, {})
    if not mon_validation:
        print(json.dumps({'event': 'fatal', 'error': f'validation.{mon_val_key!r} missing from YAML'}))
        _push_redis(args.platform, 'MONITOR_FATAL', f'validation.{mon_val_key!r} missing')
        return 1
    mon_indicators = mon_validation.get('indicators', [])
    if not mon_indicators:
        print(json.dumps({'event': 'fatal',
                          'error': f'validation.{mon_val_key}.indicators missing or empty'}))
        _push_redis(args.platform, 'MONITOR_FATAL',
                    f'validation.{mon_val_key}.indicators missing')
        return 1

    # Cross-check: every indicator must be consistent with element_map[complete_key].
    ck_spec = element_map[complete_key]
    ck_names = ck_spec.get('names') or ([ck_spec.get('name')] if ck_spec.get('name') is not None else [])
    ck_role = ck_spec.get('role')
    for ind in mon_indicators:
        ind_name = ind.get('name')
        ind_role = ind.get('role')
        if ind_role != ck_role or ind_name not in ck_names:
            print(json.dumps({'event': 'fatal',
                              'error': f'validation.{mon_val_key} indicator {ind!r} inconsistent with '
                                       f'element_map[{complete_key!r}] '
                                       f'(names={ck_names}, role={ck_role!r})'}))
            _push_redis(args.platform, 'MONITOR_FATAL',
                        f'response_complete indicator drift: {ind!r} vs complete_key spec')
            return 1

    # NOW import V2 modules
    from consultation_v2.snapshot import build_snapshot
    from core import input as inp

    # consult.py confirms `stop_button` present at send-confirmation before
    # spawning the monitor. We inherit that fact via --seen-stop so the first
    # poll can distinguish "response still generating" from "response finished
    # between send-confirm and first poll" without falling for a pre-existing
    # copy button (chat history, homepage cards, etc.).
    seen_stop = args.seen_stop
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
        'seen_stop_at_start': seen_stop,
    }))

    # Pre-flight: if the caller did NOT pass --seen-stop, the monitor has no
    # ground truth that generation actually started. In that case, require the
    # first snapshot to show stop_key; otherwise fail fatal. This eliminates
    # the old fast-path false positive where a pre-existing copy_button was
    # interpreted as completion.
    if not seen_stop:
        _, _, first_snap = build_snapshot(args.platform)
        if not first_snap.has(stop_key):
            print(json.dumps({'event': 'fatal',
                              'error': f'{stop_key!r} not present at monitor start and --seen-stop not passed. '
                                       f'Caller must confirm send before spawning monitor.'}))
            _push_redis(args.platform, 'MONITOR_FATAL',
                        f'{stop_key!r} absent at monitor start — cannot confirm generation started')
            return 1
        seen_stop = True

    while time.time() - start < timeout:
        try:
            _, _, snap = build_snapshot(args.platform)
            elapsed = time.time() - start
            has_stop = snap.has(stop_key)

            if has_stop:
                seen_stop = True
                absent_cycles = 0
            elif seen_stop:
                absent_cycles += 1
                if absent_cycles >= required_absent:
                    # Stop button disappeared for required cycles — generation
                    # has stopped. That alone is not proof of a SUCCESSFUL
                    # response (abort / error / network drop can also remove
                    # stop). Confirm with a live check of complete_key from
                    # the validation.response_complete indicators. If the copy
                    # button is off-screen, scroll-to-bottom once and retry
                    # before declaring complete. If still absent, emit
                    # completion_unverified so callers know the UI state
                    # doesn't match a healthy finished response.
                    elapsed = time.time() - start
                    has_complete = snap.has(complete_key)
                    if not has_complete:
                        try:
                            inp.press_key('ctrl+End')
                            time.sleep(2.0)
                            _, _, scroll_snap = build_snapshot(args.platform)
                            has_complete = scroll_snap.has(complete_key)
                            snap = scroll_snap
                        except Exception as e:
                            print(json.dumps({'event': 'warning',
                                              'msg': f'scroll-to-end failed: {e}'}))

                    method = 'stop_disappeared_and_complete_key' if has_complete \
                             else 'stop_disappeared_only'
                    result = {
                        'event': 'complete' if has_complete else 'completion_unverified',
                        'method': method,
                        'platform': args.platform,
                        'elapsed': round(elapsed, 1),
                        'absent_cycles': absent_cycles,
                        'complete_key_present': has_complete,
                        'url': snap.url,
                    }
                    print(json.dumps(result))
                    notif = 'RESPONSE_COMPLETE' if has_complete else 'RESPONSE_UNVERIFIED'
                    suffix = '' if has_complete else ' (complete_key absent)'
                    _push_redis(args.platform, notif,
                                f'{args.platform} response complete ({round(elapsed)}s){suffix}. URL: {snap.url}',
                                snap.url)
                    return 0 if has_complete else 2

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
            _push_redis(args.platform, 'MONITOR_FATAL', f'{args.platform} monitor fatal: {str(e)}')
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
