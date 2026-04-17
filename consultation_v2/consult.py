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
import re
import subprocess
import sys
import time
from collections import Counter
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
    if scope not in ('document', 'menu'):
        return {'error': f'Invalid scope {scope!r} — must be document or menu'}
    args = [platform]
    if scope == 'menu':
        args += ['--scope', 'menu']
    cmd = _ACT + ['inspect'] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=str(_PROJECT_ROOT))
    if r.returncode != 0:
        return {'error': f'inspect failed (exit {r.returncode}): {r.stderr.strip()[:200]}'}
    if not r.stdout.strip():
        return {'error': 'inspect returned no output'}
    try:
        return json.loads(r.stdout)
    except (json.JSONDecodeError, TypeError):
        return {'error': f'inspect returned invalid JSON: {r.stdout.strip()[:200]}'}


def has_key(snap: dict, key: str) -> bool:
    """Check if a YAML key has mapped elements in snapshot."""
    return key in snap.get('_summary', {}).get('mapped_keys', [])


def must_inspect(platform: str, step: str, scope: str = 'document') -> dict:
    """Inspect and fail closed if the subprocess/inspection errored.

    Callers that drive validation decisions from the snapshot must never
    silently proceed with an empty-on-error dict — doing so would make diffs
    and has_key checks spuriously pass/fail. Use this instead of
    inspect_platform() anywhere the result gates a fail/proceed choice.
    """
    snap = inspect_platform(platform, scope)
    if 'error' in snap:
        fail(step, f'inspect failed ({scope}): {snap["error"]}', platform)
    return snap


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
    """Flatten snapshot into a single list of elements including sidebar."""
    return (snap.get('unknown', []) +
            snap.get('sidebar', []) +
            [e for v in snap.get('mapped', {}).values() for e in v])


def detect_ui_drift(snap: dict, cfg: dict, platform: str) -> dict:
    """Compare live AT-SPI tree against YAML element_map.

    Returns dict with:
      - missing_keys: YAML element_map keys that had no matching element in tree
      - unknown_elements: tree elements not in YAML element_map or sidebar_nav or exclude
      - count: total unknown elements

    Does NOT fail — just reports. Drift is informational.
    """
    tree_cfg = cfg.get('tree', {})
    element_map = tree_cfg.get('element_map', {})
    exclude_names = set(tree_cfg.get('exclude', {}).get('names', []))
    exclude_roles = set(tree_cfg.get('exclude', {}).get('roles', []))
    sidebar_nav = tree_cfg.get('sidebar_nav', [])
    sidebar_keys = {(s.get('name'), s.get('role')) for s in sidebar_nav}

    # Build set of declared (name, role) pairs from element_map
    declared = set()
    for key, spec in element_map.items():
        role = spec.get('role', '')
        names = spec.get('names') or ([spec.get('name')] if 'name' in spec else [])
        for name in names:
            declared.add((name, role))

    # Which element_map keys are REQUIRED on the fresh page and missing?
    # Drift is checked immediately after navigate, so only keys that MUST
    # be present on a fresh idle composer qualify. send_button, stop_button,
    # and copy_button all appear later in the pipeline (after paste, after
    # send, after generation) — they are not drift on a fresh page.
    #
    # Keys required post-navigate on the fresh page:
    #   - prompt.input                  (the composer must exist)
    #   - attachment.trigger            (the attach/+ button must exist)
    # Keys that appear LATER and are not drift at this stage:
    #   - send.trigger (send_button)    — appears after text is pasted
    #   - send.confirmation_key (stop)  — appears after send
    #   - monitor.complete_key (copy)   — appears after response
    mapped_keys = set(snap.get('_summary', {}).get('mapped_keys', []))
    workflow = cfg.get('workflow', {})
    critical_keys = set()
    prompt_input = workflow.get('prompt', {}).get('input')
    if prompt_input:
        critical_keys.add(prompt_input)
    attach_trigger = workflow.get('attachment', {}).get('trigger')
    if attach_trigger:
        critical_keys.add(attach_trigger)
    missing_keys = sorted(critical_keys - mapped_keys)

    # Firefox chrome roles/names that are never platform-specific
    FIREFOX_CHROME_ROLES = {
        'frame', 'menu bar', 'menu', 'tool bar', 'landmark',
        'section', 'heading', 'internal frame', 'panel', 'scroll pane',
        'window', 'application',
    }

    # Which tree elements are NOT in element_map, sidebar_nav, or exclude?
    unknown_elements = []
    for el in snap.get('unknown', []):
        name = el.get('name', '')
        role = el.get('role', '')
        if role in exclude_roles:
            continue
        if role in FIREFOX_CHROME_ROLES:
            continue
        if name in exclude_names:
            continue
        if (name, role) in sidebar_keys:
            continue
        if (name, role) in declared:
            continue
        if not name:  # Skip unnamed generic containers
            continue
        unknown_elements.append({'name': name, 'role': role,
                                  'x': el.get('x'), 'y': el.get('y')})

    return {
        'platform': platform,
        'missing_keys': missing_keys,
        'unknown_elements': unknown_elements[:20],  # Cap at 20 for readability
        'unknown_count': len(unknown_elements),
    }


def _element_has_checked_state(snap: dict, cfg: dict, element_key: str,
                                platform: str = '') -> bool:
    """Check whether a named YAML element is in its 'active/selected' AT-SPI state.

    Invariants enforced:
    - The element_map entry MUST have a non-empty name or names list. Empty-string
      names would match ANY element whose AT-SPI name is also empty (Perplexity's
      `input` element deliberately has name: "" — if such a key were ever passed
      here, it would silently match a wrong element of matching role with 'checked'
      state). Fail closed.
    - Exactly ONE element must match (name, role) in the snapshot. Zero = not
      present (return False as before). Two or more = the label appears in multiple
      scopes (stale portal, multiple tabs, feature promos) — return False and
      emit a warning so the caller falls through to its fail path instead of
      trusting an arbitrary first match.

    The state is YAML-driven via element_map[key].selected_state (defaults to
    'checked'). Gemini's menu items use 'focused' (Material Design pattern:
    opening the menu focuses the currently-selected item). Radio menus use
    'checked'.
    """
    target_cfg = cfg.get('tree', {}).get('element_map', {}).get(element_key, {})
    target_names = target_cfg.get('names', [])
    if not target_names:
        single_name = target_cfg.get('name')
        if single_name is not None:
            target_names = [single_name]
    target_role = target_cfg.get('role', '')
    selected_state = target_cfg.get('selected_state', 'checked')

    # Guard against empty-name specs being used for state checks.
    if not target_names or all((n == '' or n is None) for n in target_names):
        fail('mode_setup',
             f'Element {element_key!r} has no name — cannot safely check selected state. '
             f'Empty names match any unnamed element of the same role.',
             platform)
    if not target_role:
        return False

    matches = [el for el in _all_elements(snap)
               if el.get('role') == target_role and el.get('name', '') in target_names]
    if len(matches) == 0:
        return False
    if len(matches) > 1:
        print(json.dumps({'event': 'warning', 'step': 'checked_state',
                          'element': element_key,
                          'match_count': len(matches),
                          'note': 'multiple instances — cannot safely verify'}))
        return False
    return selected_state in matches[0].get('states', [])


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

    # Find and focus file dialog.
    #
    # Dialog window titles on this system look like:
    #   "File Upload - ChatGPT — Mozilla Firefox"
    #   "Open - Gemini — Mozilla Firefox"
    # So the YAML dialog_titles entries ("File Upload", "Open", "Open File")
    # are PREFIXES of the real title. A bare substring regex would wrongly
    # match a main-tab title like "OpenAI - ChatGPT — Mozilla Firefox"
    # because "OpenAI" contains "Open" as a prefix.
    #
    # Use a start-anchored word-boundary regex: "^<title>\b". This requires
    # the title to appear at the start AND be followed by a non-word char
    # (space, dash, em-dash) or end of string. "OpenAI..." fails because
    # "A" after "Open" is a word char. "Open - ..." passes.
    for title in dialog_titles:
        anchored = f'^{re.escape(title)}\\b'
        r = subprocess.run(['xdotool', 'search', '--name', anchored],
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

    # ── UI drift detection — fail closed on critical drift ──
    # detect_ui_drift's `missing_keys` is already scoped to workflow-critical
    # keys (attachment.trigger, prompt.input, send.trigger/confirmation_key,
    # monitor.stop_key). If any of those aren't in the live tree, the workflow
    # cannot proceed — fail rather than halt with a confusing error later.
    # Unknown elements + blocker patterns come from the YAML drift policy.
    drift = detect_ui_drift(snap, cfg, platform)
    if drift['missing_keys'] or drift['unknown_count'] > 0:
        print(json.dumps({'event': 'ui_drift', **drift}))

    if drift['missing_keys']:
        fail('navigate',
             f'UI drift: workflow-critical YAML keys missing from live tree: '
             f'{drift["missing_keys"]}. Either the YAML is wrong or the platform '
             f'UI changed. Fix before proceeding.',
             platform)

    # Optional blocker-name policy: YAML can declare names that, if present on
    # the fresh page, indicate a modal/banner is covering the UI and
    # coordinate clicks would land on it.
    drift_policy = cfg.get('tree', {}).get('drift', {})
    blocker_names = set(drift_policy.get('fail_on_blocker_names', []))
    if blocker_names:
        for el in drift.get('unknown_elements', []):
            if el.get('name') in blocker_names:
                fail('navigate',
                     f'UI drift: blocker element present on fresh page: '
                     f'{el.get("name")!r} ({el.get("role")}). '
                     f'Declared in tree.drift.fail_on_blocker_names.',
                     platform)
    max_unknown = drift_policy.get('max_unknown_elements')
    if max_unknown is not None and drift['unknown_count'] > max_unknown:
        fail('navigate',
             f'UI drift: {drift["unknown_count"]} unknown elements exceeds '
             f'tree.drift.max_unknown_elements={max_unknown}. '
             f'Platform UI may have changed.',
             platform)

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
        """Run a named sequence (e.g., deep_think). Returns None.

        Every per-step failure calls fail() which sys.exit(1)s, so normal
        return means every step succeeded. The old `all_steps_ok = True`
        return value was always True and callers treated it as meaningful
        — that was misleading and a refactoring hazard.
        """
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
                    if _element_has_checked_state(menu_snap, cfg, target, platform):
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
                    if not _element_has_checked_state(verify_snap, cfg, target, platform):
                        # Menu auto-closed after click (Gemini): scope='menu' is empty.
                        # Fall back to indicator-based verification in document scope
                        # using the step's validation key. This is not a fallback in the
                        # "try multiple guesses" sense — it's using the authoritative
                        # indicator the YAML declared for this step.
                        step_val_key = step.get('validation')
                        indicator_verified = False
                        if step_val_key:
                            doc_snap = inspect_platform(platform)
                            val_cfg = validation.get(step_val_key, {})
                            indicators = val_cfg.get('indicators', [])
                            doc_elements = _all_elements(doc_snap)
                            for ind in indicators:
                                for el in doc_elements:
                                    if el.get('name') == ind.get('name') and el.get('role') == ind.get('role'):
                                        indicator_verified = True
                                        break
                                if indicator_verified:
                                    break
                        if not indicator_verified:
                            fail('mode_setup',
                                 f'Sequence step {i}: target {target!r} not in checked state and '
                                 f'no document-scope validation indicator found for {step_val_key!r}',
                                 platform)

            if step.get('close_with_escape'):
                act(platform, 'press', 'Escape')
                time.sleep(timing['after_escape'])
        return None

    # Resolve ALL validation keys from ALL sequence steps (not just last)
    mode_val_keys = []
    if mode:
        if mode in sequences and sequences[mode]:
            for step in sequences[mode]:
                if 'validation' in step:
                    mode_val_keys.append(step['validation'])
            if not mode_val_keys:
                fail('mode_check', f'Sequence {mode!r} has no validation fields on any step', platform)
        else:
            mode_vals = selection.get('mode_validations', {})
            if mode not in mode_vals:
                fail('mode_check', f'No validation key for mode {mode!r} in selection.mode_validations', platform)
            mode_val_keys.append(mode_vals[mode])

    tool_val_keys = {}
    for tool in (tools or []):
        if tool in sequences and sequences[tool]:
            keys = [step['validation'] for step in sequences[tool] if 'validation' in step]
            if not keys:
                fail('mode_check', f'Tool sequence {tool!r} has no validation fields on any step', platform)
            tool_val_keys[tool] = keys
        else:
            fail('setup', f'Tool {tool!r} has no sequence in workflow.selection.sequences', platform)

    # Pre-check: if mode/tool indicators are ALL already present, skip setup entirely.
    # This is the "check first, don't touch if already active" rule — avoids toggling
    # off a setting (Claude Adaptive, Perplexity Incognito) or clicking radios that
    # AT-SPI doesn't verify post-click (Gemini Pro).
    all_required_val_keys = list(mode_val_keys)
    for _t in (tools or []):
        if _t in tool_val_keys:
            all_required_val_keys.extend(tool_val_keys[_t])

    def _all_indicators_present(val_keys, snapshot):
        if not val_keys:
            return False
        elements = _all_elements(snapshot)
        for val_key in val_keys:
            val_cfg = validation.get(val_key, {})
            indicators = val_cfg.get('indicators', [])
            if not indicators:
                return False  # No indicators defined — cannot pre-verify
            found = False
            for indicator in indicators:
                ind_name = indicator.get('name')
                ind_role = indicator.get('role')
                if ind_name is None or ind_role is None:
                    return False
                for el in elements:
                    if el.get('name') == ind_name and el.get('role') == ind_role:
                        found = True
                        break
                if found:
                    break
            if not found:
                return False
        return True

    pre_satisfied = _all_indicators_present(all_required_val_keys, snap)
    if pre_satisfied:
        print(json.dumps({'event': 'step_ok', 'step': 'mode_preverify',
                          'mode': mode, 'tools': tools,
                          'note': 'all indicators already present — setup skipped'}))

    # Step 2a: Set mode (via sequence or simple target)
    mode_set = False
    if pre_satisfied:
        pass  # Skip — already in target state
    elif mode and mode in sequences:
        # _run_sequence fails closed on any step failure (sys.exit). If we
        # return here, every step succeeded — so mark all declared validation
        # keys verified via checked_state.
        _run_sequence(sequences[mode])
        checked_state_keys.update(mode_val_keys)
        mode_set = True
        snap = must_inspect(platform, 'mode_setup')
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
                if _element_has_checked_state(menu_snap, cfg, target_key, platform):
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

                # Verify checked state after clicking — fail closed.
                # Some platforms (Gemini) auto-close the menu on selection, so the
                # post-click menu snapshot is empty. For those, re-trigger the menu
                # to bring the target back into scope, verify, then close.
                if selection.get('mode_verified_by_checked_state'):
                    verify_snap = inspect_platform(platform, scope=scope)
                    verified = _element_has_checked_state(verify_snap, cfg, target_key, platform)
                    if not verified and selection.get('mode_reverify_via_reopen'):
                        # Re-open menu for verification (menu auto-closed on selection)
                        result = act(platform, 'click', trigger_key)
                        if result.get('error'):
                            fail('mode_setup',
                                 f'Re-open trigger {trigger_key!r} failed during verification: {result}',
                                 platform)
                        time.sleep(timing['after_trigger_click'])
                        verify_snap = inspect_platform(platform, scope=scope)
                        verified = _element_has_checked_state(verify_snap, cfg, target_key, platform)
                    if verified:
                        checked_state_keys.update(mode_val_keys)
                    else:
                        fail('mode_setup',
                             f'Mode {mode!r} target {target_key!r} not in selected state after click. '
                             f'AT-SPI verification required by mode_verified_by_checked_state=true.',
                             platform)

                if selection.get('mode_close_with_escape'):
                    act(platform, 'press', 'Escape')
                    time.sleep(timing['after_escape'])
            else:
                # Skipped because already checked — verified for THIS mode only
                checked_state_keys.update(mode_val_keys)

            snap = inspect_platform(platform)
        else:
            fail('mode_setup', f'mode_trigger or mode_targets[{mode!r}] missing from YAML', platform)

    # Step 2b: Set tools (via sequences, independent of mode)
    if not pre_satisfied:
        for tool in (tools or []):
            if tool in sequences:
                _run_sequence(sequences[tool])
                if tool in tool_val_keys:
                    checked_state_keys.update(tool_val_keys[tool])
                snap = must_inspect(platform, 'mode_setup')

    # Build check_keys from pre-resolved validation keys (deduplicated)
    check_keys_set = set()
    check_keys_set.update(mode_val_keys)
    for tool in (tools or []):
        if tool in tool_val_keys:
            check_keys_set.update(tool_val_keys[tool])
    check_keys = list(check_keys_set)

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

    # YAML-documented unverifiable states: the platform UI has no AT-SPI indicator
    # for the current mode/tool (e.g., Grok's model selector shows the name visually
    # but exposes only "Model select" in the tree). Accept these only when YAML
    # provides an explicit 'unverifiable_reason' documenting the gap. This is not
    # a fallback — the YAML is asserting that the click is the only available signal.
    for val_key in check_keys:
        if val_key not in verified_keys:
            val_cfg = validation.get(val_key, {})
            reason = val_cfg.get('unverifiable_reason')
            if reason:
                verified_keys.add(val_key)
                print(json.dumps({'event': 'warning', 'step': 'mode_check',
                                  'val_key': val_key, 'unverifiable_reason': reason}))

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
            # Fail closed on inspect errors — an empty pre-buttons Counter would
            # make the later diff treat every post-attach button as new.
            pre_attach_snap = must_inspect(platform, 'attach')

        result = act(platform, 'click', attach_trigger_key)
        if result.get('error'):
            fail('attach', f'Attach trigger {attach_trigger_key!r} failed: {result}', platform)
        time.sleep(timing['after_trigger_click'])

        # Click upload files item — scope MUST come from YAML (no default).
        if 'menu_target_scope' not in attach_cfg:
            fail('attach', 'workflow.attachment.menu_target_scope missing from YAML', platform)
        menu_scope = attach_cfg['menu_target_scope']
        result = act(platform, 'click', attach_menu_key, '--scope', menu_scope)
        if result.get('error'):
            fail('attach', f'Upload item {attach_menu_key!r} failed: {result}', platform)
        time.sleep(timing['after_attach_menu'])

        # File dialog
        if not xdotool_file_dialog(platform, pkg, cfg=cfg, timing=timing):
            fail('attach', 'File dialog not found', platform)
        time.sleep(timing['after_file_dialog'])

        # Verify attachment — STRICT: YAML-driven template + Counter multiset diff
        if pre_attach_snap and attach_validation.get('diff_validated'):
            # YAML-documented unverifiable: the platform's chip does not expose
            # a stable filename-containing AT-SPI name (Grok shows only "Remove"
            # which is a generic button that could exist elsewhere). In that case
            # the file-dialog Return keypress returning no error is the only
            # available signal. YAML must declare this explicitly.
            if attach_validation.get('attach_unverifiable_reason'):
                print(json.dumps({'event': 'warning', 'step': 'attach',
                                  'unverifiable_reason': attach_validation['attach_unverifiable_reason']}))
                print(json.dumps({'event': 'step_ok', 'step': 'attach',
                                  'note': 'dialog-success only — chip not AT-SPI verifiable'}))
                # Skip chip diff verification for this platform
                # Fall through to end of attach block
                attach_validation_done = True
            else:
                attach_validation_done = False

            # YAML-driven chip name template: {filename} or {filename_stem} or literal
            chip_template = attach_validation.get('file_chip_template')
            if not attach_validation_done and not chip_template:
                fail('attach',
                     f'YAML validation.{attach_val_key}.file_chip_template missing — required for diff_validated',
                     platform)

            if not attach_validation_done:
                filename = Path(pkg).name  # e.g., "taey_package_claude_1776440164.md"
                filename_stem = Path(pkg).stem  # e.g., "taey_package_claude_1776440164"
                # Size in KB, one decimal (matches Perplexity chip format "148.2 KB")
                size_bytes = Path(pkg).stat().st_size
                size_kb_str = f"{size_bytes / 1000:.1f}"
                expected_name = (chip_template
                                 .replace('{filename}', filename)
                                 .replace('{filename_stem}', filename_stem)
                                 .replace('{size_kb}', size_kb_str)
                                 .replace('{size_bytes}', str(size_bytes)))

                # Counter-based multiset diff — catches duplicates that set() subtraction masks
                pre_buttons = Counter(e.get('name') for e in _all_elements(pre_attach_snap)
                                       if e.get('role') == 'push button')
                chip_found = False
                new_buttons = Counter()
                for _ in range(20):
                    post_attach_snap = inspect_platform(platform)
                    post_buttons = Counter(e.get('name') for e in _all_elements(post_attach_snap)
                                            if e.get('role') == 'push button')
                    new_buttons = post_buttons - pre_buttons
                    # EXACT string match (==) — no substring, no .lower()
                    if expected_name in new_buttons and new_buttons[expected_name] > 0:
                        chip_found = True
                        break
                    time.sleep(1)
                if not chip_found:
                    path = screenshot(platform)
                    fail('attach',
                         f'diff_validated: no new push button {expected_name!r} after 20s. '
                         f'Screenshot: {path}. New buttons: {dict(new_buttons)}',
                         platform)
                print(json.dumps({'event': 'step_ok', 'step': 'attach',
                                  'chip': expected_name, 'match': 'exact'}))
        else:
            fail('attach',
                 f'validation.{attach_val_key}.diff_validated must be true — no pass_through allowed',
                 platform)
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

    # Prove the pasted text actually landed in the composer. runtime.paste()
    # returning True only proves the clipboard write + Ctrl+V subprocess
    # succeeded, not that the text reached the input element (focus could
    # have been on a modal, a different focused entry, etc.). Use the AT-SPI
    # Text interface on the input element to verify character count.
    input_spec = cfg.get('tree', {}).get('element_map', {}).get(input_key, {})
    input_name = input_spec.get('name', '')
    input_role = input_spec.get('role', '')
    input_states = input_spec.get('states_include', [])
    if not input_role:
        fail('prompt', f'element_map.{input_key}.role missing from YAML', platform)

    from consultation_v2.runtime import ConsultationRuntime
    _rt = ConsultationRuntime(platform)
    txt_result = _rt.read_element_text(input_name, input_role, required_states=input_states)
    if 'error' in txt_result:
        fail('prompt',
             f'Cannot verify paste landed in {input_key!r}: {txt_result["error"]}. '
             f'No way to prove text reached the composer.',
             platform)
    live_text = txt_result.get('text', '') or ''
    live_count = txt_result.get('char_count', 0)
    # Accept small deltas: some platforms normalize whitespace, ProseMirror
    # may collapse trailing newlines, etc. Require at least 80% of the
    # expected character count — enough to catch wholesale-missing paste but
    # tolerate minor tokenization. Also require the first 30 chars match.
    expected = len(message)
    threshold = max(20, int(expected * 0.8))
    if live_count < threshold:
        fail('prompt',
             f'Paste did not land: input has {live_count} chars, expected ~{expected} '
             f'(threshold {threshold}). Live text head: {live_text[:80]!r}',
             platform)
    head_len = min(30, len(message.strip()))
    if head_len > 0 and message.strip()[:head_len] not in live_text:
        fail('prompt',
             f'Paste corrupted: expected prefix {message.strip()[:head_len]!r} '
             f'not found in live input text head {live_text[:80]!r}',
             platform)
    print(json.dumps({'event': 'step_ok', 'step': 'prompt_text_verified',
                      'expected_chars': expected, 'live_chars': live_count}))

    # Validate prompt_ready — read validation key from YAML workflow.prompt.validation
    prompt_val_key = prompt_cfg.get('validation')
    if not prompt_val_key:
        fail('prompt', 'workflow.prompt.validation missing from YAML', platform)
    prompt_validation = validation.get(prompt_val_key, {})
    # No pass_through — every platform must define indicators
    indicators = prompt_validation.get('indicators')
    if not indicators:
        fail('prompt', f'validation.{prompt_val_key}.indicators missing or empty — required', platform)
    prompt_snap = must_inspect(platform, 'prompt')
    prompt_elements = _all_elements(prompt_snap)
    for indicator in indicators:
        found = any(
            e.get('name') == indicator.get('name') and e.get('role') == indicator.get('role')
            for e in prompt_elements
        )
        if not found:
            fail('prompt', f'prompt_ready indicator not found: {indicator}', platform)
    print(json.dumps({'event': 'step_ok', 'step': 'prompt_ready'}))

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

    # Capture pre-send URL for accurate change detection. Fail closed on
    # inspect errors — a silently-empty snap makes the stale-stop-button
    # check at line below pass spuriously.
    pre_send_snap = must_inspect(platform, 'send')
    pre_send_url = pre_send_snap.get('url', '')

    # Fail closed if stop_button already present — send would false-confirm on stale state
    if has_key(pre_send_snap, confirmation_key):
        fail('send',
             f'Confirmation key {confirmation_key!r} already present before send — '
             f'stale state from previous generation',
             platform)

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

    # Enforce workflow.send.validation indicators against the current snap.
    # Previously this YAML field was declared but never read — the indicators
    # could drift silently. Now they must match the live tree at send-confirm.
    send_val_key = send_cfg.get('validation')
    if not send_val_key:
        fail('send', 'workflow.send.validation missing from YAML', platform)
    send_validation = validation.get(send_val_key, {})
    if not send_validation:
        fail('send', f'validation.{send_val_key!r} missing from YAML', platform)
    send_indicators = send_validation.get('indicators', [])
    if not send_indicators:
        fail('send', f'validation.{send_val_key}.indicators missing or empty', platform)
    send_elements = _all_elements(snap)
    for ind in send_indicators:
        ind_name = ind.get('name')
        ind_role = ind.get('role')
        if ind_name is None or ind_role is None:
            fail('send', f'Malformed indicator in validation.{send_val_key}: {ind}', platform)
        found = any(e.get('name') == ind_name and e.get('role') == ind_role for e in send_elements)
        if not found:
            fail('send', f'send_success indicator not found in live tree: {ind}', platform)

    # has_stop guaranteed True here (fail() exits if False)
    print(json.dumps({'event': 'step_ok', 'step': 'send', 'url': url[:50], 'stop': True,
                       'url_changed': url_changed,
                       'validation': send_val_key}))

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
        # Send step already confirmed stop_button was present. Pass --seen-stop
        # so the monitor doesn't need to rediscover that from the tree (which
        # could race with stop disappearing if generation was very fast) and
        # can't be fooled by a pre-existing copy_button into declaring complete.
        monitor_cmd = _MONITOR + [platform, '--interval', interval, '--absent', absent,
                                  '--timeout', timeout, '--stop-key', stop_key_val, '--seen-stop']
        log_path = f'/tmp/monitor_{platform}_{int(time.time())}.log'
        with open(log_path, 'w') as log_f:
            proc = subprocess.Popen(monitor_cmd, stdout=log_f, stderr=subprocess.STDOUT,
                                    cwd=str(_PROJECT_ROOT))
        print(json.dumps({'event': 'step_ok', 'step': 'monitor', 'pid': proc.pid, 'log': log_path}))
    else:
        print(json.dumps({'event': 'step_ok', 'step': 'monitor', 'msg': 'skipped'}))

    # ── Step 7: Store in Neo4j ──
    session_id = None
    try:
        from consultation_v2.store import store_consultation
        session_id = store_consultation(
            platform=platform,
            prompt=message,
            mode=mode,
            tools=tools,
            attachments=[file_path] if file_path else [],
            url=url,
        )
        print(json.dumps({'event': 'step_ok', 'step': 'store', 'session_id': session_id}))
    except Exception as e:
        print(json.dumps({'event': 'step_warn', 'step': 'store', 'error': str(e)}))

    print(json.dumps({'event': 'dispatched', 'platform': platform, 'url': url[:80],
                       'session_id': session_id,
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
