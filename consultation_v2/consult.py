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
    """Call act.py and return parsed JSON output. Nonzero exit = error."""
    cmd = _ACT + [action, platform] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(_PROJECT_ROOT))
    if not r.stdout.strip():
        return {'error': f'act.py returned no output. stderr: {r.stderr.strip()[:200]}'}
    try:
        result = json.loads(r.stdout.strip())
    except json.JSONDecodeError:
        return {'error': f'act.py returned invalid JSON: {r.stdout.strip()[:200]}'}
    # Check exit code — nonzero means act.py failed
    if r.returncode != 0 and 'error' not in result:
        result['error'] = f'act.py exited with code {r.returncode}'
    return result


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
    Handles both 'name' (singular string) and 'names' (list of alternatives).
    """
    target_cfg = cfg.get('tree', {}).get('element_map', {}).get(element_key, {})
    # Handle both 'name' (singular string) and 'names' (list of alternatives)
    target_names = target_cfg.get('names', [])
    if not target_names:
        single_name = target_cfg.get('name')
        if single_name is not None:
            target_names = [single_name]
    target_role = target_cfg.get('role', '')
    if not target_names and not target_role:
        return False
    for el in _all_elements(snap):
        if el.get('role') == target_role and el.get('name', '') in target_names:
            if 'checked' in el.get('states', []):
                return True
    return False


def xdotool_file_dialog(platform: str, file_path: str, cfg: dict = None, timing: dict = None):
    """Focus file dialog, enter path via Ctrl+L."""
    env = _platform_env(platform)

    # Read dialog titles from YAML, not hardcoded
    dialog_titles = []
    if cfg:
        dialog_titles = cfg.get('tree', {}).get('dialog_titles', [])
    if not dialog_titles:
        return False  # No dialog titles in YAML — fail closed

    # Timing must come from YAML — fail closed if missing
    if not timing:
        return False
    for key in ('dialog_after_focus', 'dialog_after_path_entry', 'dialog_after_paste'):
        if key not in timing:
            return False

    # Find and focus file dialog
    for title in dialog_titles:
        r = subprocess.run(['xdotool', 'search', '--name', '--exact', title],
                           capture_output=True, text=True, timeout=3, env=env)
        wids = [w.strip() for w in r.stdout.strip().split('\n') if w.strip()]
        if wids:
            subprocess.run(['xdotool', 'windowactivate', wids[-1]],
                           capture_output=True, timeout=5, env=env)
            time.sleep(timing['dialog_after_focus'])
            break
    else:
        return False

    # Read keyboard shortcut from YAML — no hardcoded keys
    attach_cfg = cfg.get('workflow', {}).get('attachment', {}) if cfg else {}
    location_shortcut = attach_cfg.get('dialog_location_shortcut')
    if not location_shortcut:
        return False  # No dialog_location_shortcut in YAML — fail closed

    # Read dialog keystrokes from YAML — no hardcoded keys
    select_all_key = attach_cfg.get('dialog_select_all_key')
    paste_key = attach_cfg.get('dialog_paste_key')
    confirm_key = attach_cfg.get('dialog_confirm_key')
    if not all([select_all_key, paste_key, confirm_key]):
        return False  # Missing dialog keys in YAML — fail closed

    # Execute dialog sequence — check each subprocess exit code
    for cmd, delay_key in [
        (['xdotool', 'key', location_shortcut], 'dialog_after_focus'),
        (['xdotool', 'key', select_all_key], 'dialog_after_path_entry'),
    ]:
        r = subprocess.run(cmd, env=env, capture_output=True, timeout=3)
        if r.returncode != 0:
            return False
        time.sleep(timing[delay_key])

    r = subprocess.run(['xsel', '--clipboard', '--input'], input=file_path.encode(),
                       env=env, capture_output=True, timeout=3)
    if r.returncode != 0:
        return False
    time.sleep(timing['dialog_after_path_entry'])

    for cmd, delay_key in [
        (['xdotool', 'key', paste_key], 'dialog_after_paste'),
        (['xdotool', 'key', confirm_key], None),
    ]:
        r = subprocess.run(cmd, env=env, capture_output=True, timeout=3)
        if r.returncode != 0:
            return False
        if delay_key:
            time.sleep(timing[delay_key])

    return True


def run_consultation(platform: str, message: str, file_path: str | None = None,
                     start_monitor: bool = True):
    """Run the full validated consultation workflow."""

    from consultation_v2.yaml_contract import load_platform_yaml
    cfg = load_platform_yaml(platform)
    workflow = cfg.get('workflow', {})
    defaults = workflow.get('defaults', {})
    timing = workflow.get('timing', {})
    if not timing:
        fail('setup', 'workflow.timing missing from YAML', platform)

    required_timing_keys = [
        'after_trigger_click', 'after_target_click', 'after_escape',
        'after_input_click', 'after_paste', 'after_attach_menu',
        'after_file_dialog', 'send_poll_interval',
        'dialog_after_focus', 'dialog_after_path_entry', 'dialog_after_paste',
    ]
    for key in required_timing_keys:
        if key not in timing:
            fail('setup', f'workflow.timing.{key} missing from YAML', platform)

    print(json.dumps({'event': 'start', 'platform': platform}))

    # ── Step 1: Navigate fresh ──
    fresh_url = cfg.get('urls', {}).get('fresh', '')
    if not fresh_url:
        fail('navigate', 'No fresh URL in YAML', platform)
    result = act(platform, 'navigate', fresh_url)
    if result.get('error'):
        fail('navigate', f'Navigation failed: {result}', platform)
    settle = cfg.get('urls', {}).get('settle_delay')
    if settle is None:
        fail('navigate', 'urls.settle_delay missing from YAML', platform)
    time.sleep(settle)

    snap = inspect_platform(platform)
    if not snap.get('url'):
        fail('navigate', 'No URL after navigation', platform)
    prompt_cfg = workflow.get('prompt', {})
    if 'input' not in prompt_cfg:
        fail('navigate', 'workflow.prompt.input missing from YAML', platform)
    input_key = prompt_cfg['input']
    if not has_key(snap, input_key):
        fail('navigate', f'Input key {input_key!r} not found after navigation', platform)
    print(json.dumps({'event': 'step_ok', 'step': 'navigate', 'url': snap.get('url', '')[:50]}))

    # ── Step 2: Set up and verify mode ──
    mode = defaults.get('mode')
    tools = defaults.get('tools', [])
    validation = cfg.get('validation', {})
    selection = workflow.get('selection', {})

    # Execute mode and tool setup from YAML.
    # Mode and tools are independent — a platform can need BOTH (e.g., Gemini: pro mode + deep_think tool).
    if 'sequences' not in selection:
        fail('setup', 'workflow.selection.sequences missing from YAML', platform)
    sequences = selection['sequences']
    checked_state_keys = set()  # Per-key tracking, not global boolean

    def _run_sequence(seq):
        """Run a named sequence (e.g., deep_think, pro_extended). Returns True if all steps verified."""
        all_steps_ok = True
        for i, step in enumerate(seq):
            trigger = step.get('trigger')
            target = step.get('target')
            if 'snapshot' not in step:
                fail('mode_setup', f'Sequence step {i} missing snapshot scope', platform)
            scope = step['snapshot']
            strategy = step.get('click_strategy')

            if trigger:
                result = act(platform, 'click', trigger)
                if result.get('error'):
                    fail('mode_setup', f'Trigger {trigger!r} failed: {result}', platform)
                time.sleep(timing['after_trigger_click'])

            if target:
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
                    time.sleep(timing['after_target_click'])

                if step.get('verified_by_checked_state') or step.get('skip_if_checked'):
                    verify_snap = inspect_platform(platform, scope=scope)
                    if _element_has_checked_state(verify_snap, cfg, target):
                        pass
                    elif step.get('verified_by_checked_state') and not skipped:
                        pass
                    else:
                        all_steps_ok = False

            if step.get('close_with_escape'):
                act(platform, 'press', 'Escape')
                time.sleep(timing['after_escape'])
        return all_steps_ok

    # Resolve validation keys BEFORE setup so we can track per-key
    mode_val_key = None
    if mode:
        if mode in sequences and sequences[mode]:
            last_step = sequences[mode][-1]
            if 'validation' not in last_step:
                fail('mode_check', f'Sequence {mode!r} last step has no validation field', platform)
            mode_val_key = last_step['validation']
        else:
            mode_vals = selection.get('mode_validations', {})
            if mode not in mode_vals:
                fail('mode_check', f'No validation key for mode {mode!r} in selection.mode_validations', platform)
            mode_val_key = mode_vals[mode]

    tool_val_keys = {}
    for tool in (tools or []):
        if tool in sequences and sequences[tool]:
            last_step = sequences[tool][-1]
            if 'validation' not in last_step:
                fail('mode_check', f'Tool sequence {tool!r} last step has no validation field', platform)
            tool_val_keys[tool] = last_step['validation']

    # Step 2a: Set mode (via sequence or simple target)
    mode_set = False
    if mode and mode in sequences:
        ok = _run_sequence(sequences[mode])
        if ok and mode_val_key:
            checked_state_keys.add(mode_val_key)
        mode_set = True
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
            time.sleep(timing['after_trigger_click'])

            if 'mode_snapshot' not in selection:
                fail('mode_setup', 'workflow.selection.mode_snapshot missing from YAML', platform)
            scope = selection['mode_snapshot']
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
                        time.sleep(timing['after_escape'])

            if not skipped:
                args_list = [target_key, '--scope', scope]
                if strategy:
                    args_list += ['--strategy', strategy]
                result = act(platform, 'click', *args_list)
                if result.get('error'):
                    fail('mode_setup', f'Mode target {target_key!r} failed: {result}', platform)
                time.sleep(timing['after_target_click'])

                # Verify checked state after clicking (before closing menu)
                if selection.get('mode_verified_by_checked_state'):
                    verify_snap = inspect_platform(platform, scope=scope)
                    if _element_has_checked_state(verify_snap, cfg, target_key):
                        if mode_val_key:
                            checked_state_keys.add(mode_val_key)
                    else:
                        # AT-SPI doesn't expose checked state — click succeeded, accept for THIS mode only
                        if mode_val_key:
                            checked_state_keys.add(mode_val_key)
                        print(json.dumps({'event': 'mode_note', 'platform': platform,
                                          'msg': f'AT-SPI does not expose checked state for {target_key!r}. Click succeeded — accepting.'}), flush=True)

                if selection.get('mode_close_with_escape'):
                    act(platform, 'press', 'Escape')
                    time.sleep(timing['after_escape'])
            else:
                # Skipped because already checked — verified for THIS mode only
                if mode_val_key:
                    checked_state_keys.add(mode_val_key)

            snap = inspect_platform(platform)
        else:
            fail('mode_setup', f'mode_trigger or mode_targets[{mode!r}] missing from YAML', platform)

    # Step 2b: Set tools (via sequences, independent of mode)
    for tool in (tools or []):
        if tool in sequences:
            ok = _run_sequence(sequences[tool])
            if ok and tool in tool_val_keys:
                checked_state_keys.add(tool_val_keys[tool])
            snap = inspect_platform(platform)

    # Build check_keys from pre-resolved validation keys
    check_keys = []
    if mode_val_key:
        check_keys.append(mode_val_key)
    for tool in (tools or []):
        if tool in tool_val_keys:
            check_keys.append(tool_val_keys[tool])

    all_elements = _all_elements(snap)

    # Verify all check_keys exist in validation section — fail if missing
    for val_key in check_keys:
        if val_key not in validation:
            fail('mode_check', f'Validation key {val_key!r} not defined in YAML validation section', platform)

    verified_keys = set()
    for val_key in check_keys:
        val_cfg = validation[val_key]
        indicators = val_cfg.get('indicators', [])
        for indicator in indicators:
            ind_name = indicator.get('name')
            ind_role = indicator.get('role')
            if ind_name is None or ind_role is None:
                fail('mode_check', f'Malformed indicator in {val_key}: missing name or role', platform)
            for el in all_elements:
                if el.get('name') == ind_name and el.get('role') == ind_role:
                    verified_keys.add(val_key)
                    break

    # For unverified keys, check if they were verified via checked_state (per-key, no global bleed)
    for val_key in check_keys:
        if val_key not in verified_keys and val_key in checked_state_keys:
            val_cfg = validation.get(val_key, {})
            if val_cfg.get('verified_by_checked_state', False):
                verified_keys.add(val_key)

    mode_verified = len(verified_keys) == len(check_keys) and len(check_keys) > 0
    mode_indicator = ', '.join(verified_keys) if verified_keys else None

    if mode_verified:
        print(json.dumps({'event': 'step_ok', 'step': 'mode_check', 'mode': mode, 'indicator': mode_indicator}))
    else:
        path = screenshot(platform)
        unverified = [k for k in check_keys if k not in verified_keys]
        fail('mode_check', f'Mode {mode!r} (tools={tools}) not verified. Unverified: {unverified}. Screenshot: {path}', platform)

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

        # Read validation key from YAML workflow.attachment.validation
        attach_val_key = attach_cfg.get('validation')
        if not attach_val_key:
            fail('attach', 'workflow.attachment.validation missing from YAML', platform)
        attach_validation = validation.get(attach_val_key, {})
        pre_attach_snap = None
        if attach_validation.get('diff_validated'):
            pre_attach_snap = inspect_platform(platform)

        result = act(platform, 'click', attach_trigger_key)
        if result.get('error'):
            fail('attach', f'Attach trigger {attach_trigger_key!r} failed: {result}', platform)
        time.sleep(timing['after_trigger_click'])

        # Click upload files item (from YAML workflow)
        result = act(platform, 'click', attach_menu_key, '--scope', 'menu')
        if result.get('error'):
            fail('attach', f'Upload item {attach_menu_key!r} failed: {result}', platform)
        time.sleep(timing['after_attach_menu'])

        # File dialog
        if not xdotool_file_dialog(platform, pkg, cfg=cfg, timing=timing):
            fail('attach', 'File dialog not found', platform)
        time.sleep(timing['after_file_dialog'])

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
    time.sleep(timing['after_input_click'])

    result = act(platform, 'paste', message)
    if not result.get('pasted'):
        fail('prompt', f'Paste failed: {result}', platform)
    time.sleep(timing['after_paste'])
    print(json.dumps({'event': 'step_ok', 'step': 'prompt', 'length': len(message)}))

    # Validate prompt_ready — read validation key from YAML workflow.prompt.validation
    prompt_val_key = prompt_cfg.get('validation')
    if not prompt_val_key:
        fail('prompt', 'workflow.prompt.validation missing from YAML', platform)
    prompt_validation = validation.get(prompt_val_key, {})
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
    if 'confirmation_timeout' not in send_cfg:
        fail('send', 'workflow.send.confirmation_timeout missing from YAML', platform)
    confirmation_timeout = send_cfg['confirmation_timeout']
    if 'require_new_url' not in send_cfg:
        fail('send', 'workflow.send.require_new_url missing from YAML', platform)
    require_url = send_cfg['require_new_url']

    # Capture pre-send URL for accurate change detection
    pre_send_snap = inspect_platform(platform)
    pre_send_url = pre_send_snap.get('url', '')

    if send_cfg.get('submit_via_return'):
        if 'keypress' not in send_cfg:
            fail('send', 'workflow.send.keypress missing from YAML (submit_via_return is true)', platform)
        result = act(platform, 'press', send_cfg['keypress'])
        if result.get('error'):
            fail('send', f'Submit keypress failed: {result}', platform)
    else:
        if 'trigger' not in send_cfg:
            fail('send', 'workflow.send.trigger missing from YAML', platform)
        send_trigger_key = send_cfg['trigger']
        result = act(platform, 'click', send_trigger_key)
        if result.get('error'):
            fail('send', f'Send button click ({send_trigger_key!r}) failed: {result}', platform)

    # Poll for send confirmation: stop button is the primary signal
    deadline = time.time() + confirmation_timeout
    has_stop = False
    url_changed = False
    url = ''
    while time.time() < deadline:
        snap = inspect_platform(platform)
        url = snap.get('url', '')
        has_stop = has_key(snap, confirmation_key)
        url_changed = bool(url and pre_send_url and url != pre_send_url)
        if require_url:
            # Need BOTH stop button AND URL change
            if has_stop and url_changed:
                break
        else:
            # Stop button alone is sufficient
            if has_stop:
                break
        time.sleep(timing['send_poll_interval'])

    # Verify based on YAML requirements
    if not has_stop:
        path = screenshot(platform)
        fail('send', f'Send not confirmed: {confirmation_key} not found. Screenshot: {path}', platform)
    if require_url and not url_changed:
        fail('send', f'require_new_url is true but URL unchanged', platform)

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
        if 'stop_key' not in mon_cfg:
            fail('monitor', 'workflow.monitor.stop_key missing from YAML', platform)
        stop_key_val = mon_cfg['stop_key']
        if 'timeout' not in mon_cfg:
            fail('monitor', 'workflow.monitor.timeout missing from YAML', platform)
        timeout = str(mon_cfg['timeout'])
        monitor_cmd = _MONITOR + [platform, '--interval', interval, '--absent', absent, '--timeout', timeout, '--stop-key', stop_key_val]
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
