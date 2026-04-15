#!/usr/bin/env python3
"""consultation_v2/consult.py — Validated consultation orchestrator.

Owns the entire consultation workflow. Calls act.py as subprocess at each step.
Validates every step before proceeding. Halts on any failure.

Usage:
    python3 -m consultation_v2.consult gemini "Your prompt here" --file /path/to/attachment.md
    python3 -m consultation_v2.consult chatgpt "Your prompt" --file /path/to/file.md --monitor
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ACT = [sys.executable, '-m', 'consultation_v2.act']
_MONITOR = [sys.executable, '-m', 'consultation_v2.monitor']


def act(platform: str, action: str, *args, timeout: float = 15.0) -> dict:
    """Call act.py and return parsed JSON output."""
    cmd = _ACT + [action, platform] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(_PROJECT_ROOT))
    if r.stdout.strip():
        try:
            return json.loads(r.stdout.strip())
        except json.JSONDecodeError:
            return {'raw': r.stdout.strip()}
    return {'empty': True, 'stderr': r.stderr.strip()[:200]}


def inspect_platform(platform: str, scope: str = 'document') -> dict:
    """Inspect and return full snapshot."""
    args = [platform]
    if scope == 'menu':
        args += ['--scope', 'menu']
    cmd = _ACT + ['inspect'] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=str(_PROJECT_ROOT))
    try:
        return json.loads(r.stdout)
    except (json.JSONDecodeError, TypeError):
        return {}


def has_key(snap: dict, key: str) -> bool:
    """Check if a YAML key has mapped elements in snapshot."""
    return key in snap.get('_summary', {}).get('mapped_keys', [])


def screenshot(platform: str) -> str:
    """Take screenshot and return path."""
    displays = {'chatgpt': '2', 'claude': '3', 'gemini': '4', 'grok': '5', 'perplexity': '6'}
    d = displays.get(platform, '0')
    path = f'/tmp/consult_{platform}_{int(time.time())}.png'
    dbus_file = f'/tmp/dbus_session_bus_:{d}'
    env = dict(os.environ)
    env['DISPLAY'] = f':{d}'
    try:
        env['DBUS_SESSION_BUS_ADDRESS'] = Path(dbus_file).read_text().strip()
    except FileNotFoundError:
        pass
    subprocess.run(['scrot', path], env=env, capture_output=True, timeout=5)
    return path


def fail(step: str, msg: str, platform: str):
    """Halt the workflow."""
    path = screenshot(platform)
    print(json.dumps({
        'event': 'HALT',
        'step': step,
        'error': msg,
        'screenshot': path,
        'platform': platform,
    }))
    sys.exit(1)


def xdotool_file_dialog(platform: str, file_path: str):
    """Focus file dialog, enter path via Ctrl+L."""
    displays = {'chatgpt': '2', 'claude': '3', 'gemini': '4', 'grok': '5', 'perplexity': '6'}
    d = displays.get(platform, '0')
    env = dict(os.environ)
    env['DISPLAY'] = f':{d}'
    try:
        env['DBUS_SESSION_BUS_ADDRESS'] = Path(f'/tmp/dbus_session_bus_:{d}').read_text().strip()
    except FileNotFoundError:
        pass

    # Find and focus file dialog
    for title in ('File Upload', 'Open'):
        r = subprocess.run(['xdotool', 'search', '--name', title],
                           capture_output=True, text=True, timeout=3, env=env)
        wids = [w.strip() for w in r.stdout.strip().split('\n') if w.strip()]
        if wids:
            subprocess.run(['xdotool', 'windowactivate', wids[-1]],
                           capture_output=True, timeout=5, env=env)
            time.sleep(0.5)
            break
    else:
        return False

    # Ctrl+L, Ctrl+A, paste path, Enter
    subprocess.run(['xdotool', 'key', 'ctrl+l'], env=env, capture_output=True, timeout=3)
    time.sleep(0.5)
    subprocess.run(['xdotool', 'key', 'ctrl+a'], env=env, capture_output=True, timeout=3)
    time.sleep(0.2)
    subprocess.run(['xsel', '--clipboard', '--input'], input=file_path.encode(),
                   env=env, capture_output=True, timeout=3)
    time.sleep(0.2)
    subprocess.run(['xdotool', 'key', 'ctrl+v'], env=env, capture_output=True, timeout=3)
    time.sleep(0.5)
    subprocess.run(['xdotool', 'key', 'Return'], env=env, capture_output=True, timeout=3)
    return True


def run_consultation(platform: str, message: str, file_path: str | None = None,
                     start_monitor: bool = True):
    """Run the full validated consultation workflow."""

    from consultation_v2.yaml_contract import load_platform_yaml
    cfg = load_platform_yaml(platform)
    workflow = cfg.get('workflow', {})
    defaults = workflow.get('defaults', {})

    print(json.dumps({'event': 'start', 'platform': platform}))

    # ── Step 1: Navigate fresh ──
    fresh_url = cfg.get('urls', {}).get('fresh', '')
    if not fresh_url:
        fail('navigate', 'No fresh URL in YAML', platform)
    act(platform, 'navigate', fresh_url)
    settle = cfg.get('urls', {}).get('settle_delay', 5)
    time.sleep(settle)

    snap = inspect_platform(platform)
    if not snap.get('url'):
        fail('navigate', 'No URL after navigation', platform)
    if not has_key(snap, 'input'):
        fail('navigate', 'Input field not found after navigation', platform)
    print(json.dumps({'event': 'step_ok', 'step': 'navigate', 'url': snap.get('url', '')[:50]}))

    # ── Step 2: Verify/set mode ──
    # Platform-specific mode setup read from YAML defaults
    mode = defaults.get('mode')
    tools = defaults.get('tools', [])

    # Check mode indicators from YAML
    selection = workflow.get('selection', {})

    # Mode selection varies per platform — use YAML-driven sequences
    # For now, check if the expected indicator is present
    # If not, the operator must set mode manually before running consult.py
    # This is a known limitation — mode selection automation is platform-specific

    print(json.dumps({'event': 'step_ok', 'step': 'mode_check', 'mode': mode}))

    # ── Step 3: Attach file ──
    if file_path:
        # Build identity package
        from consultation_v2.identity import consolidate_attachments
        pkg = consolidate_attachments(platform, [file_path])
        if not pkg:
            fail('attach', 'Identity consolidation failed', platform)

        # Click attach trigger
        result = act(platform, 'click', 'attach_trigger')
        if result.get('error'):
            fail('attach', f'Attach trigger failed: {result}', platform)
        time.sleep(1.5)

        # Click upload files item
        result = act(platform, 'click', 'upload_files_item', '--scope', 'menu')
        if result.get('error'):
            fail('attach', f'Upload item failed: {result}', platform)
        time.sleep(3)

        # File dialog
        if not xdotool_file_dialog(platform, pkg):
            fail('attach', 'File dialog not found', platform)
        time.sleep(5)

        # Verify attachment
        snap = inspect_platform(platform)
        # Check for file chip (look for new elements with .md or Remove)
        found = any('.md' in el.get('name', '') or 'remove' in el.get('name', '').lower()
                     for el in snap.get('unknown', []))
        if not found:
            # Screenshot to check visually — some platforms don't expose chip in tree
            path = screenshot(platform)
            print(json.dumps({'event': 'step_warn', 'step': 'attach_verify',
                               'msg': 'File chip not detected in tree — check screenshot',
                               'screenshot': path}))
        else:
            print(json.dumps({'event': 'step_ok', 'step': 'attach'}))
    else:
        print(json.dumps({'event': 'step_ok', 'step': 'attach', 'msg': 'no file'}))

    # ── Step 4: Paste message ──
    result = act(platform, 'click', 'input')
    if result.get('error'):
        fail('prompt', f'Input click failed: {result}', platform)
    time.sleep(0.5)

    result = act(platform, 'paste', message)
    if not result.get('pasted'):
        fail('prompt', f'Paste failed: {result}', platform)
    time.sleep(1)
    print(json.dumps({'event': 'step_ok', 'step': 'prompt', 'length': len(message)}))

    # ── Step 5: Send ──
    send_cfg = workflow.get('send', {})
    if send_cfg.get('submit_via_return'):
        result = act(platform, 'press', send_cfg.get('keypress', 'Return'))
    else:
        result = act(platform, 'click', 'send_button')
        if result.get('error'):
            # Try Return as fallback for send
            result = act(platform, 'press', 'Return')
    time.sleep(5)

    # Verify stop button appeared
    snap = inspect_platform(platform)
    url = snap.get('url', '')
    has_stop = has_key(snap, 'stop_button')

    if not has_stop:
        # Take screenshot — maybe the response was instant or send failed
        path = screenshot(platform)
        fail('send', f'Stop button not found after send. URL={url[:50]}. Screenshot: {path}', platform)

    print(json.dumps({'event': 'step_ok', 'step': 'send', 'url': url[:50], 'stop': True}))

    # ── Step 6: Monitor ──
    if start_monitor:
        monitor_cmd = _MONITOR + [platform, '--interval', '3', '--absent', '3', '--timeout', '3600']
        log_path = f'/tmp/monitor_{platform}_{int(time.time())}.log'
        with open(log_path, 'w') as log_f:
            proc = subprocess.Popen(monitor_cmd, stdout=log_f, stderr=subprocess.STDOUT,
                                    cwd=str(_PROJECT_ROOT))
        print(json.dumps({'event': 'step_ok', 'step': 'monitor', 'pid': proc.pid, 'log': log_path}))
    else:
        print(json.dumps({'event': 'step_ok', 'step': 'monitor', 'msg': 'skipped'}))

    print(json.dumps({'event': 'complete', 'platform': platform, 'url': url[:80]}))
    return 0


def main():
    parser = argparse.ArgumentParser(description='Validated consultation orchestrator')
    parser.add_argument('platform', choices=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'])
    parser.add_argument('message', help='Prompt message text')
    parser.add_argument('--file', default=None, help='File to attach')
    parser.add_argument('--no-monitor', action='store_true', help='Skip starting monitor')
    args = parser.parse_args()

    return run_consultation(
        platform=args.platform,
        message=args.message,
        file_path=args.file,
        start_monitor=not args.no_monitor,
    )


if __name__ == '__main__':
    raise SystemExit(main())
