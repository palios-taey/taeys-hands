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
            # R10-1: check windowactivate return. If the WM rejects activation
            # (race where dialog closed between search and activate, or stale
            # window ID), an unchecked fail here means Ctrl+L hits the
            # Firefox address bar instead of the dialog's location bar, and
            # the file path gets typed into the URL.
            r_act = subprocess.run(['xdotool', 'windowactivate', wids[-1]],
                                   capture_output=True, timeout=5, env=env)
            if r_act.returncode != 0:
                return False
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


def run_consultation(platform: str, message: str, file_path: str | None = None):
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
    # Driver stays dumb: it synthesizes a list of YAML-declared mode/tool
    # steps and hands them to the primitive runner. Each step is a
    # `mode_select_step` primitive call with fields sourced from
    # workflow.selection.sequences[X] (multi-step sequences like
    # Gemini deep_think) OR from workflow.selection.mode_*/mode_targets
    # (simple one-trigger-one-target cases like Grok heavy). No
    # platform-specific branching here.
    mode = defaults.get('mode')
    tools = defaults.get('tools', [])
    validation = cfg.get('validation', {})
    selection = workflow.get('selection', {})

    if 'sequences' not in selection:
        fail('setup', 'workflow.selection.sequences missing from YAML', platform)
    sequences = selection['sequences']
    checked_state_keys = set()  # Per-key tracking, not global boolean

    def _synth_simple_mode_step(mode_name):
        """Build a mode_select_step dict from selection.mode_* defaults +
        mode_targets[mode_name]. Used when the mode has no named sequence
        (the simple one-trigger-one-target path)."""
        mode_targets = selection.get('mode_targets', {})
        target_key = mode_targets.get(mode_name)
        trigger_key = selection.get('mode_trigger')
        if not (trigger_key and target_key):
            fail('mode_setup',
                 f'mode_trigger or mode_targets[{mode_name!r}] missing from YAML',
                 platform)
        if 'mode_snapshot' not in selection:
            fail('mode_setup', 'workflow.selection.mode_snapshot missing from YAML', platform)
        mode_vals = selection.get('mode_validations', {})
        if mode_name not in mode_vals:
            fail('mode_setup',
                 f'No validation key for mode {mode_name!r} in selection.mode_validations',
                 platform)
        return {
            'action': 'mode_select_step',
            'trigger': trigger_key,
            'target': target_key,
            'snapshot': selection['mode_snapshot'],
            'click_strategy': selection.get('mode_click_strategy'),
            'skip_if_checked': selection.get('mode_skip_if_checked'),
            'verified_by_checked_state': selection.get('mode_verified_by_checked_state'),
            'reverify_via_reopen': selection.get('mode_reverify_via_reopen'),
            'close_with_escape': selection.get('mode_close_with_escape'),
            'validation': mode_vals[mode_name],
        }

    # Resolve validation keys for pre-check and post-verify. Sequences
    # declare one validation key per step; the simple-target path uses
    # mode_validations[mode].
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

    # Pre-check: if every validation indicator is already present in the
    # current doc snapshot, skip setup entirely. Avoids toggling an
    # already-on setting off (Claude Adaptive, Perplexity Incognito) or
    # clicking radios whose post-click state AT-SPI won't verify.
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

    if not pre_satisfied:
        # Build the combined mode + tools sequence. Sequences from YAML are
        # action-less dicts (historical shape) — inject action name here.
        combined_steps = []
        if mode:
            if mode in sequences and sequences[mode]:
                for s in sequences[mode]:
                    if 'snapshot' not in s:
                        fail('mode_setup', f'Mode {mode!r} sequence step missing snapshot scope', platform)
                    combined_steps.append({**s, 'action': 'mode_select_step'})
            else:
                combined_steps.append(_synth_simple_mode_step(mode))
        for tool in (tools or []):
            for s in sequences[tool]:
                if 'snapshot' not in s:
                    fail('mode_setup', f'Tool {tool!r} sequence step missing snapshot scope', platform)
                combined_steps.append({**s, 'action': 'mode_select_step'})

        if combined_steps:
            from consultation_v2.runtime import ConsultationRuntime
            from consultation_v2.primitives import run_sequence
            rt = ConsultationRuntime(platform)
            ctx = {'platform': platform, 'runtime': rt, 'cfg': cfg,
                   'message': message, 'vars': {}}
            res = run_sequence(ctx, combined_steps, step_name='mode_setup')
            if not res['ok']:
                fail('mode_setup', res['error'], platform)
            # Every step of mode_select_step either skipped-because-checked
            # or clicked-then-verified, so all declared val keys are verified
            # via checked_state for the purposes of the post-check below.
            checked_state_keys.update(mode_val_keys)
            for t in (tools or []):
                if t in tool_val_keys:
                    checked_state_keys.update(tool_val_keys[t])
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

    # ── Step 3: Attach identity package (HARD RULE — always) ──
    # EVERY session gets the identity package (FAMILY_KERNEL + platform
    # IDENTITY file). No caller gets to skip this. Consolidation happens
    # here (not inside a primitive) because it's setup — compute the
    # package path, then run the YAML attach sequence with pkg in ctx.
    from consultation_v2.identity import consolidate_attachments
    caller_files = [file_path] if file_path else []
    pkg = consolidate_attachments(platform, caller_files)
    if not pkg:
        fail('attach', 'Identity consolidation failed — cannot send without identity package', platform)

    attach_cfg = workflow.get('attachment', {})
    attach_sequence = attach_cfg.get('sequence')
    if not attach_sequence:
        fail('attach', 'workflow.attachment.sequence missing from YAML', platform)

    from consultation_v2.primitives import run_sequence
    from consultation_v2.runtime import ConsultationRuntime as _Rt
    _rt = _Rt(platform)
    ctx = {'platform': platform, 'runtime': _rt, 'cfg': cfg, 'message': message,
           'vars': {'pkg': pkg}}
    res = run_sequence(ctx, attach_sequence, step_name='attach')
    if not res['ok']:
        fail('attach', res['error'], platform)

    # ── Step 4: Prompt (YAML-driven sequence) ──
    # workflow.prompt.sequence is a list of primitives executed by the
    # runner. Each platform declares exactly what to do: click input,
    # paste ${message}, click auxiliary buttons (e.g. ChatGPT's
    # "Show in text field" for long pastes), verify text landed, wait
    # for prompt_ready indicator. No driver branching on platform.
    prompt_cfg = workflow.get('prompt', {})
    prompt_sequence = prompt_cfg.get('sequence')
    if not prompt_sequence:
        fail('prompt', 'workflow.prompt.sequence missing from YAML', platform)
    from consultation_v2.primitives import run_sequence
    from consultation_v2.runtime import ConsultationRuntime as _Rt
    _rt = _Rt(platform)
    ctx = {'platform': platform, 'runtime': _rt, 'cfg': cfg, 'message': message, 'vars': {}}
    res = run_sequence(ctx, prompt_sequence, step_name='prompt')
    if not res['ok']:
        fail('prompt', res['error'], platform)

    # ── Step 5: Send (YAML-driven sequence) ──
    # Each platform declares its own send sequence: capture URL baseline,
    # assert no stale stop-button, click send button or press Return,
    # wait for send_success indicators, optionally require_url_changed.
    send_cfg = workflow.get('send', {})
    send_sequence = send_cfg.get('sequence')
    if not send_sequence:
        fail('send', 'workflow.send.sequence missing from YAML', platform)
    res = run_sequence(ctx, send_sequence, step_name='send')
    if not res['ok']:
        fail('send', res['error'], platform)
    # Re-snap to capture the post-send URL for dispatched-event logging
    # and Neo4j storage. This is the URL that identifies the thread the
    # monitor will watch.
    post_send_snap = must_inspect(platform, 'send')
    url = post_send_snap.get('url', '')

    # ── Step 6: Monitor (always) ──
    # Monitor spawn is mandatory. Without it there is no RESPONSE_COMPLETE
    # notification and no gate on when the response is actually done —
    # skipping it would be a fallback that lets the caller proceed as if
    # the work were complete when it isn't.
    #
    # The monitor is a thin runner for workflow.monitor.sequence (YAML).
    # All polling intervals, cycles, timeouts, and stop/complete element
    # keys live in the sequence itself — consult.py passes only the
    # platform name and the monitor loads everything from YAML.
    mon_cfg = workflow.get('monitor', {})
    if not mon_cfg:
        fail('monitor', 'workflow.monitor missing from YAML', platform)
    if not mon_cfg.get('sequence'):
        fail('monitor', 'workflow.monitor.sequence missing from YAML', platform)
    monitor_cmd = _MONITOR + [platform]
    log_path = f'/tmp/monitor_{platform}_{int(time.time())}.log'
    with open(log_path, 'w') as log_f:
        proc = subprocess.Popen(monitor_cmd, stdout=log_f, stderr=subprocess.STDOUT,
                                cwd=str(_PROJECT_ROOT))
    print(json.dumps({'event': 'step_ok', 'step': 'monitor', 'pid': proc.pid, 'log': log_path}))

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
    args = parser.parse_args()

    return run_consultation(
        platform=args.platform,
        message=args.message,
        file_path=args.file,
    )


if __name__ == '__main__':
    raise SystemExit(main())
