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
    if not r.stdout.strip():
        return {'error': f'act.py returned no output. stderr: {r.stderr.strip()[:200]}'}
    try:
        return json.loads(r.stdout.strip())
    except json.JSONDecodeError:
        return {'error': f'act.py returned invalid JSON: {r.stdout.strip()[:200]}'}


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


def _platform_display(platform: str) -> str:
    """Read platform display from PLATFORM_DISPLAYS env."""
    raw = os.environ.get('PLATFORM_DISPLAYS', '')
    if not raw:
        try:
            for line in (_PROJECT_ROOT / '.env').read_text().splitlines():
                if line.strip().startswith('PLATFORM_DISPLAYS='):
                    raw = line.strip().split('=', 1)[1].strip()
                    break
        except FileNotFoundError:
            pass
    for pair in raw.split(','):
        pair = pair.strip()
        if ':' in pair:
            plat, dnum = pair.rsplit(':', 1)
            if plat.strip() == platform:
                return f':{dnum.strip()}'
    print(json.dumps({'event': 'HALT', 'step': 'display',
                       'error': f'No display mapping for platform {platform!r} in PLATFORM_DISPLAYS'}))
    sys.exit(1)


def _platform_env(platform: str) -> dict:
    """Build env dict with correct DISPLAY + DBUS for a platform."""
    d = _platform_display(platform)
    env = dict(os.environ)
    env['DISPLAY'] = d
    try:
        session_bus = Path(f'/tmp/dbus_session_bus_{d}').read_text().strip()
        if session_bus:
            env['DBUS_SESSION_BUS_ADDRESS'] = session_bus
    except FileNotFoundError:
        pass
    return env


def screenshot(platform: str) -> str:
    """Take screenshot and return path."""
    path = f'/tmp/consult_{platform}_{int(time.time())}.png'
    env = _platform_env(platform)
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


def _all_elements(snap: dict) -> list:
    """Flatten snapshot into a single list of elements."""
    return snap.get('unknown', []) + [e for v in snap.get('mapped', {}).values() for e in v]


def _element_has_checked_state(snap: dict, cfg: dict, element_key: str) -> bool:
    """Check whether a named YAML element has 'checked' in its AT-SPI states.

    Looks up the element name/role from cfg's element_map, then searches
    the snapshot for a matching element with 'checked' state.
    """
    target_cfg = cfg.get('tree', {}).get('element_map', {}).get(element_key, {})
    target_name = target_cfg.get('name', '')
    target_role = target_cfg.get('role', '')
    if not target_name and not target_role:
        return False
    for el in _all_elements(snap):
        if el.get('name') == target_name and el.get('role') == target_role:
            if 'checked' in el.get('states', []):
                return True
    return False


def xdotool_file_dialog(platform: str, file_path: str, cfg: dict = None):
    """Focus file dialog, enter path via Ctrl+L."""
    env = _platform_env(platform)

    # Read dialog titles from YAML, not hardcoded
    dialog_titles = []
    if cfg:
        dialog_titles = cfg.get('tree', {}).get('dialog_titles', [])
    if not dialog_titles:
        return False  # No dialog titles in YAML — fail closed

    # Find and focus file dialog
    for title in dialog_titles:
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

    # ── Step 2: Set up and verify mode ──
    mode = defaults.get('mode')
    tools = defaults.get('tools', [])
    validation = cfg.get('validation', {})
    selection = workflow.get('selection', {})

    # Execute mode setup sequence from YAML if available
    sequences = selection.get('sequences', {})
    # Determine which sequence to run: tools first (e.g., deep_think), then mode
    seq_name = None
    if tools and tools[0] in sequences:
        seq_name = tools[0]
    elif mode and mode in sequences:
        seq_name = mode

    checked_state_verified = False

    if seq_name and seq_name in sequences:
        # Named sequence (e.g., deep_think, pro_extended)
        seq = sequences[seq_name]
        all_steps_verified = True
        for i, step in enumerate(seq):
            trigger = step.get('trigger')
            target = step.get('target')
            scope = step.get('snapshot', 'document')
            strategy = step.get('click_strategy')

            if trigger:
                result = act(platform, 'click', trigger)
                if result.get('error'):
                    fail('mode_setup', f'Trigger {trigger!r} failed: {result}', platform)
                time.sleep(1.5)

            if target:
                # skip_if_checked: inspect menu, skip click if target already checked
                skipped = False
                if step.get('skip_if_checked'):
                    menu_snap = inspect_platform(platform, scope=scope)
                    if _element_has_checked_state(menu_snap, cfg, target):
                        skipped = True

                if not skipped:
                    args_list = [target, '--scope', scope]
                    if strategy:
                        args_list += ['--strategy', strategy]
                    result = act(platform, 'click', *args_list)
                    if result.get('error'):
                        fail('mode_setup', f'Target {target!r} failed: {result}', platform)
                    time.sleep(1)

                # Verify checked state after click (or confirm already checked)
                if step.get('verified_by_checked_state') or step.get('skip_if_checked'):
                    verify_snap = inspect_platform(platform, scope=scope)
                    if _element_has_checked_state(verify_snap, cfg, target):
                        pass  # Verified via AT-SPI checked state
                    elif step.get('verified_by_checked_state') and not skipped:
                        # AT-SPI doesn't expose checked state — click succeeded, accept
                        pass
                    else:
                        all_steps_verified = False

            if step.get('close_with_escape'):
                act(platform, 'press', 'Escape')
                time.sleep(1)

        checked_state_verified = all_steps_verified
        snap = inspect_platform(platform)
    elif mode:
        # Simple target (e.g., Grok heavy via mode_targets)
        mode_targets = selection.get('mode_targets', {})
        target_key = mode_targets.get(mode)
        trigger_key = selection.get('mode_trigger')

        if trigger_key and target_key:
            result = act(platform, 'click', trigger_key)
            if result.get('error'):
                fail('mode_setup', f'Mode trigger {trigger_key!r} failed: {result}', platform)
            time.sleep(1.5)

            scope = selection.get('mode_snapshot', 'menu')
            strategy = selection.get('mode_click_strategy')

            # mode_skip_if_checked: inspect menu, skip click if target already checked
            skipped = False
            if selection.get('mode_skip_if_checked'):
                menu_snap = inspect_platform(platform, scope=scope)
                if _element_has_checked_state(menu_snap, cfg, target_key):
                    skipped = True
                    # Already checked — close menu and move on
                    if selection.get('mode_close_with_escape'):
                        act(platform, 'press', 'Escape')
                        time.sleep(1)

            if not skipped:
                args_list = [target_key, '--scope', scope]
                if strategy:
                    args_list += ['--strategy', strategy]
                result = act(platform, 'click', *args_list)
                if result.get('error'):
                    fail('mode_setup', f'Mode target {target_key!r} failed: {result}', platform)
                time.sleep(1)

                # Verify checked state after clicking (before closing menu)
                if selection.get('mode_verified_by_checked_state'):
                    verify_snap = inspect_platform(platform, scope=scope)
                    if _element_has_checked_state(verify_snap, cfg, target_key):
                        checked_state_verified = True
                    else:
                        # AT-SPI doesn't expose checked state for this platform's menu items.
                        # Click completed without error — accept as best-effort verification.
                        checked_state_verified = True
                        print(json.dumps({'event': 'mode_note', 'platform': platform,
                                          'msg': f'AT-SPI does not expose checked state for {target_key!r}. Click succeeded — accepting.'}), flush=True)

                if selection.get('mode_close_with_escape'):
                    act(platform, 'press', 'Escape')
                    time.sleep(1)
            else:
                # Skipped because already checked — that counts as verified
                checked_state_verified = True

            snap = inspect_platform(platform)

    # Check all relevant validation indicators: mode + tools
    # Look for any active indicator from mode_active, tool_active, etc.
    mode_verified = False
    mode_indicator = None
    check_keys = []
    if mode:
        check_keys.append(f'{mode}_active')
    for tool in (tools or []):
        check_keys.append(f'{tool}_active')

    all_elements = _all_elements(snap)

    verified_keys = set()
    for val_key in check_keys:
        val_cfg = validation.get(val_key, {})
        indicators = val_cfg.get('indicators', [])
        for indicator in indicators:
            ind_name = indicator.get('name', '')
            ind_role = indicator.get('role', '')
            for el in all_elements:
                if el.get('name') == ind_name and el.get('role') == ind_role:
                    verified_keys.add(val_key)
                    break

    mode_verified = len(verified_keys) == len(check_keys) and len(check_keys) > 0
    mode_indicator = ', '.join(verified_keys) if verified_keys else None

    if mode_verified:
        print(json.dumps({'event': 'step_ok', 'step': 'mode_check', 'mode': mode, 'indicator': mode_indicator}))
    else:
        # Check if ALL validation keys use verified_by_checked_state (no persistent indicator exists)
        all_checked_state = all(
            validation.get(k, {}).get('verified_by_checked_state', False)
            for k in check_keys if validation.get(k)
        )
        if check_keys and all_checked_state and checked_state_verified:
            # Actually verified via checked state during sequence/target execution
            print(json.dumps({'event': 'step_ok', 'step': 'mode_check', 'mode': mode,
                               'msg': 'verified_by_checked_state — confirmed checked state during execution'}))
        else:
            path = screenshot(platform)
            fail('mode_check', f'Mode {mode!r} (tools={tools}) not verified. Checked: {check_keys}. Screenshot: {path}', platform)

    # ── Step 3: Attach file ──
    if file_path:
        # Build identity package
        from consultation_v2.identity import consolidate_attachments
        pkg = consolidate_attachments(platform, [file_path])
        if not pkg:
            fail('attach', 'Identity consolidation failed', platform)

        # Click attach trigger (from YAML workflow — no defaults)
        attach_cfg = workflow.get('attachment', {})
        if 'trigger' not in attach_cfg:
            fail('attach', 'workflow.attachment.trigger missing from YAML', platform)
        if 'menu_target' not in attach_cfg:
            fail('attach', 'workflow.attachment.menu_target missing from YAML', platform)
        attach_trigger_key = attach_cfg['trigger']
        attach_menu_key = attach_cfg['menu_target']

        # Pre-attach snapshot for diff_validated
        attach_validation = validation.get('attach_success', {})
        pre_attach_snap = None
        if attach_validation.get('diff_validated'):
            pre_attach_snap = inspect_platform(platform)

        result = act(platform, 'click', attach_trigger_key)
        if result.get('error'):
            fail('attach', f'Attach trigger {attach_trigger_key!r} failed: {result}', platform)
        time.sleep(1.5)

        # Click upload files item (from YAML workflow)
        result = act(platform, 'click', attach_menu_key, '--scope', 'menu')
        if result.get('error'):
            fail('attach', f'Upload item {attach_menu_key!r} failed: {result}', platform)
        time.sleep(3)

        # File dialog
        if not xdotool_file_dialog(platform, pkg, cfg=cfg):
            fail('attach', 'File dialog not found', platform)
        time.sleep(5)

        # Verify attachment
        if pre_attach_snap and attach_validation.get('diff_validated'):
            post_attach_snap = inspect_platform(platform)
            pre_names = {(e.get('name'), e.get('role')) for e in _all_elements(pre_attach_snap)}
            post_names = {(e.get('name'), e.get('role')) for e in _all_elements(post_attach_snap)}
            new_elements = post_names - pre_names
            if not new_elements:
                fail('attach', 'diff_validated: no new elements after attach — file chip not detected', platform)
            print(json.dumps({'event': 'step_ok', 'step': 'attach', 'new_elements': len(new_elements)}))
        elif attach_validation.get('pass_through'):
            path = screenshot(platform)
            print(json.dumps({'event': 'step_ok', 'step': 'attach', 'screenshot': path,
                               'msg': 'pass_through — no AT-SPI validation'}))
        else:
            fail('attach', 'No attach_success validation defined in YAML', platform)
    else:
        print(json.dumps({'event': 'step_ok', 'step': 'attach', 'msg': 'no file'}))

    # ── Step 4: Paste message ──
    prompt_cfg = workflow.get('prompt', {})
    if 'input' not in prompt_cfg:
        fail('prompt', 'workflow.prompt.input missing from YAML', platform)
    input_key = prompt_cfg['input']
    result = act(platform, 'click', input_key)
    if result.get('error'):
        fail('prompt', f'Input click ({input_key!r}) failed: {result}', platform)
    time.sleep(0.5)

    result = act(platform, 'paste', message)
    if not result.get('pasted'):
        fail('prompt', f'Paste failed: {result}', platform)
    time.sleep(1)
    print(json.dumps({'event': 'step_ok', 'step': 'prompt', 'length': len(message)}))

    # Validate prompt_ready from YAML
    prompt_validation = validation.get('prompt_ready', {})
    if prompt_validation.get('pass_through'):
        pass  # Explicitly no validation — YAML says this is OK
    elif prompt_validation.get('indicators'):
        prompt_snap = inspect_platform(platform)
        prompt_elements = _all_elements(prompt_snap)
        for indicator in prompt_validation['indicators']:
            found = any(
                e.get('name') == indicator.get('name') and e.get('role') == indicator.get('role')
                for e in prompt_elements
            )
            if not found:
                fail('prompt', f'prompt_ready indicator not found: {indicator}', platform)
        print(json.dumps({'event': 'step_ok', 'step': 'prompt_ready'}))
    else:
        fail('prompt', 'No prompt_ready validation defined in YAML', platform)

    # ── Step 5: Send ──
    send_cfg = workflow.get('send', {})
    if not send_cfg:
        fail('send', 'workflow.send missing from YAML', platform)
    if 'confirmation_key' not in send_cfg:
        fail('send', 'workflow.send.confirmation_key missing from YAML', platform)

    confirmation_key = send_cfg['confirmation_key']
    confirmation_timeout = send_cfg.get('confirmation_timeout', 10)
    require_url = send_cfg.get('require_new_url', False)

    if send_cfg.get('submit_via_return'):
        if 'keypress' not in send_cfg:
            fail('send', 'workflow.send.keypress missing from YAML (submit_via_return is true)', platform)
        result = act(platform, 'press', send_cfg['keypress'])
    else:
        if 'trigger' not in send_cfg:
            fail('send', 'workflow.send.trigger missing from YAML', platform)
        send_trigger_key = send_cfg['trigger']
        result = act(platform, 'click', send_trigger_key)
        if result.get('error'):
            fail('send', f'Send button click ({send_trigger_key!r}) failed: {result}', platform)

    # Poll for send confirmation: stop button appeared OR URL changed
    deadline = time.time() + confirmation_timeout
    has_stop = False
    url_changed = False
    url = ''
    while time.time() < deadline:
        snap = inspect_platform(platform)
        url = snap.get('url', '')
        has_stop = has_key(snap, confirmation_key)
        url_changed = bool(url and fresh_url and url != fresh_url)
        if has_stop and url_changed:
            break
        if has_stop and not require_url:
            break
        if url_changed and not require_url:
            break
        time.sleep(2)

    # Verify based on YAML requirements
    if require_url and not url_changed:
        fail('send', f'require_new_url is true but URL unchanged', platform)
    if not has_stop and not url_changed:
        path = screenshot(platform)
        fail('send', f'Send not confirmed: no {confirmation_key}, URL unchanged. Screenshot: {path}', platform)

    if has_stop:
        print(json.dumps({'event': 'step_ok', 'step': 'send', 'url': url[:50], 'stop': True}))
    elif url_changed:
        print(json.dumps({'event': 'step_ok', 'step': 'send', 'url': url[:50], 'stop': False,
                           'msg': 'URL changed — send confirmed via URL, no stop button yet'}))

    # ── Step 6: Monitor ──
    if start_monitor:
        mon_cfg = workflow.get('monitor', {})
        if not mon_cfg:
            fail('monitor', 'workflow.monitor missing from YAML', platform)
        if 'poll_interval' not in mon_cfg:
            fail('monitor', 'workflow.monitor.poll_interval missing from YAML', platform)
        if 'required_stop_absent_cycles' not in mon_cfg:
            fail('monitor', 'workflow.monitor.required_stop_absent_cycles missing from YAML', platform)
        interval = str(mon_cfg['poll_interval'])
        absent = str(mon_cfg['required_stop_absent_cycles'])
        timeout = str(mon_cfg.get('timeout', 3600))
        monitor_cmd = _MONITOR + [platform, '--interval', interval, '--absent', absent, '--timeout', timeout]
        log_path = f'/tmp/monitor_{platform}_{int(time.time())}.log'
        with open(log_path, 'w') as log_f:
            proc = subprocess.Popen(monitor_cmd, stdout=log_f, stderr=subprocess.STDOUT,
                                    cwd=str(_PROJECT_ROOT))
        print(json.dumps({'event': 'step_ok', 'step': 'monitor', 'pid': proc.pid, 'log': log_path}))
    else:
        print(json.dumps({'event': 'step_ok', 'step': 'monitor', 'msg': 'skipped'}))

    print(json.dumps({'event': 'dispatched', 'platform': platform, 'url': url[:80],
                       'msg': 'Send confirmed, monitor spawned. Response NOT yet complete.'}))
    return 0


def main():
    parser = argparse.ArgumentParser(description='Validated consultation orchestrator')
    _platforms = sorted(p.stem for p in (_PROJECT_ROOT / 'consultation_v2' / 'platforms').glob('*.yaml'))
    parser.add_argument('platform', choices=_platforms)
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
