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
        from consultation_v2.yaml_contract import load_platform_yaml
        cfg = load_platform_yaml(args.platform)
        extract_cfg = cfg.get('workflow', {}).get('extract', {})
        if not extract_cfg:
            print(json.dumps({'error': 'workflow.extract missing from YAML'}))
            return 1

        # YAML-driven sequence path (preferred). Drivers hold zero platform
        # knowledge; workflow.extract.sequence is an ordered list of
        # primitive steps the runner executes. After the sequence, we read
        # the variable named in extract.output_var and emit the final
        # `extracted` event + store in Neo4j if session_id is provided.
        sequence = extract_cfg.get('sequence')
        if sequence:
            from consultation_v2.primitives import run_sequence
            output_var = extract_cfg.get('output_var', 'response')
            ctx = {
                'platform': args.platform,
                'runtime': runtime,
                'cfg': cfg,
                'message': '',
                'vars': {},
            }
            res = run_sequence(ctx, sequence, step_name='extract')
            if not res['ok']:
                print(json.dumps({'error': f'extract sequence failed: {res["error"]}'}))
                return 1
            content = ctx['vars'].get(output_var, '')
            if not content or not content.strip():
                print(json.dumps({'error': f'extract sequence output_var {output_var!r} empty'}))
                return 1
            message_id = None
            if args.session_id:
                try:
                    from consultation_v2.store import store_response
                    from consultation_v2.snapshot import build_snapshot
                    _, _, final_snap = build_snapshot(args.platform)
                    message_id = store_response(
                        session_id=args.session_id, response_text=content,
                        url=final_snap.url, extraction_method='yaml_sequence',
                    )
                except Exception as e:
                    print(json.dumps({'store_error': str(e)}), file=sys.stderr)
            print(json.dumps({'extracted': True, 'length': len(content),
                              'strategy': 'yaml_sequence', 'output_var': output_var,
                              'session_id': args.session_id, 'message_id': message_id}))
            print('---CONTENT---')
            print(content)
            return 0

        # Legacy strategy-based path — kept as a bridge while platforms
        # migrate to sequences. Read timing from YAML — no hardcoded sleeps.
        scroll_delay = extract_cfg.get('scroll_delay', None)
        post_click_delay = extract_cfg.get('post_click_delay', None)

        # Step 1: Scroll to bottom (from YAML)
        scroll_key = extract_cfg.get('scroll_before_extract')
        if scroll_key:
            if scroll_delay is None:
                print(json.dumps({'error': 'workflow.extract.scroll_delay missing from YAML'}))
                return 1
            # R10-7: if scroll fails, we extract from the wrong visible area
            # (on platforms where last_by_y picks a Copy button that scrolls
            # into view). Fail closed.
            if not runtime.press(scroll_key):
                print(json.dumps({'error': f'scroll_before_extract keypress {scroll_key!r} failed'}))
                return 1
            import time; time.sleep(scroll_delay)

        if post_click_delay is None:
            print(json.dumps({'error': 'workflow.extract.post_click_delay missing from YAML'}))
            return 1

        # Step 1.5: Optional pre-expand click. Perplexity Deep Research shows
        # a collapsed summary by default and reveals the full report only
        # after clicking "Show full report". Without this the extract picks
        # the Copy button from the collapsed view and gets empty bullets
        # where URLs should be. YAML declares which element to click and how
        # long to wait for the expanded view to render.
        pre_expand_key = extract_cfg.get('pre_expand_click_key')
        if pre_expand_key:
            pre_expand_delay = extract_cfg.get('pre_expand_delay')
            if pre_expand_delay is None:
                print(json.dumps({'error': 'workflow.extract.pre_expand_delay missing from YAML '
                                            '(required when pre_expand_click_key is set)'}))
                return 1
            _, _, pe_snap = build_snapshot(args.platform)
            pe_element = pe_snap.first(pre_expand_key)
            if pe_element:
                pe_strategy = extract_cfg.get('pre_expand_click_strategy') or extract_cfg.get('click_strategy')
                ok = runtime.click(pe_element, strategy=pe_strategy)
                if not ok:
                    print(json.dumps({'error': f'pre_expand_click {pre_expand_key!r} failed'}))
                    return 1
                import time; time.sleep(pre_expand_delay)
            # If the button isn't present, assume the report is already
            # expanded (or the view doesn't need it) and continue. YAML can
            # enforce presence by declaring pre_expand_required: true.
            elif extract_cfg.get('pre_expand_required'):
                print(json.dumps({'error': f'pre_expand_click_key {pre_expand_key!r} not found '
                                            f'and pre_expand_required=true'}))
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
        if strategy not in ('first', 'last_by_y', 'tree_walk'):
            print(json.dumps({'error': f'Unknown extract strategy {strategy!r} — must be first, last_by_y, or tree_walk'}))
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

        # tree_walk: skip clipboard entirely. Perplexity Deep Research
        # responses can't reliably be extracted via the Copy button (the
        # action-bar "Copy" truncates, the "Copy contents" button lives
        # inside a menu that isn't in the default tree). Instead, walk the
        # AT-SPI Text interface of a named response container (declared in
        # YAML via extract.primary_key → element_map[key]) and return the
        # concatenated text. This is the documented pattern for DR mode.
        if strategy == 'tree_walk':
            input_spec = runtime.cfg.get('tree', {}).get('element_map', {}).get(primary_key, {})
            ct_name = input_spec.get('name', '')
            ct_role = input_spec.get('role', '')
            ct_states = input_spec.get('states_include', [])
            if not ct_role:
                print(json.dumps({'error': f'element_map.{primary_key}.role missing from YAML'}))
                return 1
            txt = runtime.read_element_text(ct_name, ct_role, required_states=ct_states)
            if 'error' in txt:
                print(json.dumps({'error': f'tree_walk read failed: {txt["error"]}'}))
                return 1
            content = txt.get('text', '')
            if not content or not content.strip():
                print(json.dumps({'error': 'tree_walk returned empty content'}))
                return 1
            message_id = None
            if args.session_id:
                try:
                    from consultation_v2.store import store_response
                    message_id = store_response(
                        session_id=args.session_id, response_text=content,
                        url=snap.url, extraction_method='tree_walk',
                    )
                except Exception as e:
                    print(json.dumps({'store_error': str(e)}), file=sys.stderr)
            print(json.dumps({'extracted': True, 'length': len(content),
                              'element': element.name, 'strategy': strategy,
                              'x': element.x, 'y': element.y,
                              'session_id': args.session_id, 'message_id': message_id}))
            print('---CONTENT---')
            print(content)
            return 0

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
            # R10-5: fail closed on write failure. External callers that shell
            # out `act clipboard clear` before an extract expect the clipboard
            # to actually be empty afterwards; a spurious {'cleared': True}
            # when xsel failed would let stale content be read as response.
            ok = runtime.write_clipboard("")
            print(json.dumps({'cleared': ok}))
            return 0 if ok else 1
        else:
            ok = runtime.write_clipboard(args.target)
            print(json.dumps({'written': ok, 'length': len(args.target)}))
            return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
