#!/usr/bin/env python3
"""consultation_v2/act.py — Click/inspect a single element on any platform display.

Usage (as subprocess with correct env — called by parent or CLI):
    python3 -m consultation_v2.act inspect chatgpt
    python3 -m consultation_v2.act click chatgpt send_button
    python3 -m consultation_v2.act click chatgpt --name "Send prompt" --role "push button"
    python3 -m consultation_v2.act navigate chatgpt https://chatgpt.com/
    python3 -m consultation_v2.act paste chatgpt "Hello world"
    python3 -m consultation_v2.act press chatgpt Return

Display and bus are resolved from PLATFORM_DISPLAYS + /tmp/a11y_bus_* files.
AT-SPI is initialized AFTER env setup, so each invocation connects to the right bus.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ---- Env setup BEFORE any AT-SPI imports ----

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env
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

    # Bus discovery contract:
    # - /tmp/a11y_bus_{display}  : dedicated AT-SPI bus address. On this
    #   system it is legitimately empty (AT-SPI rides on the session bus);
    #   we still require the FILE to exist as an explicit "we looked and
    #   there is no separate a11y bus" signal. Empty contents = skip.
    # - /tmp/dbus_session_bus_{display} : session bus address, ALWAYS
    #   required. Missing file or empty contents = fail closed. We do NOT
    #   reuse the a11y bus as a session bus fallback.
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


def main():
    parser = argparse.ArgumentParser(description='V2 single-action tool')
    parser.add_argument('action', choices=['inspect', 'click', 'navigate', 'paste', 'press', 'clipboard', 'extract'])
    _platforms = sorted(p.stem for p in (_PROJECT_ROOT / 'consultation_v2' / 'platforms').glob('*.yaml'))
    parser.add_argument('platform', choices=_platforms)
    parser.add_argument('target', nargs='?', default=None,
                        help='Element key (for click), URL (for navigate), text (for paste), key (for press)')
    parser.add_argument('--name', default=None, help='Exact element name (alternative to key)')
    parser.add_argument('--role', default=None, help='Exact element role')
    parser.add_argument('--session-id', default=None, help='ChatSession UUID for Neo4j storage on extract')
    parser.add_argument('--strategy', default=None, help='Click strategy override')
    parser.add_argument('--scope', default='document', choices=['document', 'menu'],
                        help='Scan scope (default: document)')
    args = parser.parse_args()

    display = setup_display(args.platform)

    # NOW import V2 modules
    from consultation_v2.runtime import ConsultationRuntime
    from consultation_v2.snapshot import build_snapshot, build_menu_snapshot

    runtime = ConsultationRuntime(args.platform)

    if args.action == 'inspect':
        if args.scope == 'menu':
            _, _, snap = build_menu_snapshot(args.platform)
        else:
            _, _, snap = build_snapshot(args.platform)
        out = snap.serializable()
        # Add summary
        out['_summary'] = {
            'display': display,
            'mapped_keys': list(k for k, v in snap.mapped.items() if v),
            'unknown_count': len(snap.unknown),
            'sidebar_count': len(snap.sidebar),
        }
        print(json.dumps(out, indent=2, default=str))
        return 0

    if args.action == 'click':
        if args.scope == 'menu':
            _, _, snap = build_menu_snapshot(args.platform)
        else:
            _, _, snap = build_snapshot(args.platform)

        element = None
        if args.target:
            # Look up by YAML key
            element = snap.first(args.target)
            if not element:
                print(json.dumps({'error': f'Key {args.target!r} not found in snapshot',
                                  'available': list(k for k, v in snap.mapped.items() if v)}))
                return 1
        elif args.name is not None:
            # Find by exact name (and optionally role)
            all_els = []
            for items in snap.mapped.values():
                all_els.extend(items)
            all_els.extend(snap.unknown)
            all_els.extend(snap.sidebar)
            for el in all_els:
                if el.name == args.name and (not args.role or el.role == args.role):
                    element = el
                    break
            if not element:
                print(json.dumps({'error': f'Element {args.name!r} not found'}))
                return 1
        else:
            print(json.dumps({'error': 'click requires target key or --name'}))
            return 1

        ok = runtime.click(element, strategy=args.strategy)
        print(json.dumps({'clicked': ok, 'element': element.name, 'role': element.role,
                          'x': element.x, 'y': element.y}))
        return 0 if ok else 1

    if args.action == 'navigate':
        if not args.target:
            print(json.dumps({'error': 'navigate requires URL as target'}))
            return 1
        runtime.switch()
        ok = runtime.navigate(args.target)
        print(json.dumps({'navigated': ok, 'url': args.target}))
        return 0 if ok else 1

    if args.action == 'paste':
        if not args.target:
            print(json.dumps({'error': 'paste requires text as target'}))
            return 1
        ok = runtime.paste(args.target)
        print(json.dumps({'pasted': ok, 'length': len(args.target)}))
        return 0 if ok else 1

    if args.action == 'press':
        if not args.target:
            print(json.dumps({'error': 'press requires key as target'}))
            return 1
        ok = runtime.press(args.target)
        print(json.dumps({'pressed': ok, 'key': args.target}))
        return 0 if ok else 1

    if args.action == 'extract':
        # Mechanical extraction: scroll to bottom, find copy button by YAML strategy, click, read clipboard
        from consultation_v2.yaml_contract import load_platform_yaml
        cfg = load_platform_yaml(args.platform)
        extract_cfg = cfg.get('workflow', {}).get('extract', {})
        if not extract_cfg:
            print(json.dumps({'error': 'workflow.extract missing from YAML'}))
            return 1

        # Read timing from YAML — no hardcoded sleeps
        scroll_delay = extract_cfg.get('scroll_delay', None)
        post_click_delay = extract_cfg.get('post_click_delay', None)

        # Step 1: Scroll to bottom (from YAML)
        scroll_key = extract_cfg.get('scroll_before_extract')
        if scroll_key:
            if scroll_delay is None:
                print(json.dumps({'error': 'workflow.extract.scroll_delay missing from YAML'}))
                return 1
            runtime.press(scroll_key)
            import time; time.sleep(scroll_delay)

        if post_click_delay is None:
            print(json.dumps({'error': 'workflow.extract.post_click_delay missing from YAML'}))
            return 1

        # Step 2: Find the copy button by strategy
        primary_key = extract_cfg.get('primary_key')
        if not primary_key:
            print(json.dumps({'error': 'workflow.extract.primary_key missing from YAML'}))
            return 1

        strategy = extract_cfg.get('strategy')
        if not strategy:
            print(json.dumps({'error': 'workflow.extract.strategy missing from YAML'}))
            return 1
        if strategy not in ('first', 'last_by_y'):
            print(json.dumps({'error': f'Unknown extract strategy {strategy!r} — must be first or last_by_y'}))
            return 1
        click_strategy = extract_cfg.get('click_strategy')

        _, _, snap = build_snapshot(args.platform)

        # Select element by YAML strategy
        if strategy == 'last_by_y':
            element = snap.last(primary_key)
        else:
            element = snap.first(primary_key)

        if not element:
            print(json.dumps({'error': f'No {primary_key!r} found in snapshot'}))
            return 1

        # Step 3: Clear clipboard BEFORE click. Without this, a silently-failed
        # click leaves stale content in the clipboard (commonly the prompt text
        # just pasted), which the extractor would accept as the response.
        # Fail closed if the clear itself failed — otherwise stale content
        # remains and the next read would silently accept it.
        if not runtime.write_clipboard(""):
            print(json.dumps({'error': 'write_clipboard("") failed before extract — '
                                        'stale clipboard would be read as response'}))
            return 1

        # Step 4: Click the copy button
        ok = runtime.click(element, strategy=click_strategy)
        if not ok:
            print(json.dumps({'error': f'Click on {primary_key!r} failed', 'element': element.name}))
            return 1

        import time; time.sleep(post_click_delay)

        # Step 5: Read clipboard — fail if empty (click was a no-op)
        content = runtime.read_clipboard()
        if not content or not content.strip():
            print(json.dumps({'error': 'Clipboard empty after copy click — extraction failed'}))
            return 1

        # Step 5: Store in Neo4j if session_id provided
        message_id = None
        if args.session_id and content:
            try:
                from consultation_v2.store import store_response
                message_id = store_response(
                    session_id=args.session_id,
                    response_text=content,
                    url=snap.url,
                    extraction_method=f'{strategy}_{click_strategy or "default"}',
                )
            except Exception as e:
                print(json.dumps({'store_error': str(e)}), file=sys.stderr)

        print(json.dumps({'extracted': True, 'length': len(content), 'element': element.name,
                          'strategy': strategy, 'x': element.x, 'y': element.y,
                          'session_id': args.session_id, 'message_id': message_id}))
        print('---CONTENT---')
        print(content)
        return 0

    if args.action == 'clipboard':
        if args.target == 'read' or args.target is None:
            content = runtime.read_clipboard()
            print(content)
            return 0
        elif args.target == 'clear':
            runtime.write_clipboard("")
            print(json.dumps({'cleared': True}))
            return 0
        else:
            # Write to clipboard
            runtime.write_clipboard(args.target)
            print(json.dumps({'written': True, 'length': len(args.target)}))
            return 0


if __name__ == '__main__':
    raise SystemExit(main())
