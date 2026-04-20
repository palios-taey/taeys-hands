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

    # If the input element isn't in the snapshot, the composer may be
    # holding a residual draft from a prior consultation that HALTed
    # mid-paste (e.g., verify_text_landed slack trip). ChatGPT and
    # Claude persist composer drafts client-side — the URL reloads but
    # the draft state and the composer's AT-SPI exposure both depend
    # on its focus/content state. Recovery: press Escape (close any
    # modal), nudge focus into the content with F6, then clear via
    # Ctrl+A + Delete. Re-inspect. If input is STILL missing, the
    # YAML or UI has genuinely drifted — fail closed as before.
    if not has_key(snap, input_key):
        import subprocess as _subp
        env = _platform_env(platform)
        for keys in ('Escape', 'F6', 'ctrl+a', 'Delete'):
            _subp.run(['xdotool', 'key', keys], env=env,
                      capture_output=True, timeout=3)
            time.sleep(0.3)
        time.sleep(1.0)
        snap = inspect_platform(platform)
        if not has_key(snap, input_key):
            fail('navigate',
                 f'Input key {input_key!r} not found after navigation '
                 f'(attempted composer-clear recovery — no effect). '
                 f'YAML may be stale or platform UI changed.',
                 platform)
        print(json.dumps({'event': 'step_ok', 'step': 'navigate_recovered',
                          'note': 'composer had residual state; cleared via Escape+F6+Ctrl+A+Delete'}))

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
            # Per-step checked-state credit. Only add a step's validation
            # key to checked_state_keys when the step ACTUALLY verified
            # (either skip_if_checked skipped because target was already
            # checked, OR verified_by_checked_state made the primitive
            # verify post-click). A step with neither flag is just a blind
            # click — we do NOT claim verification for it, and the
            # post-check below must find the document indicator or an
            # unverifiable_reason to succeed. R2 audit caught this
            # false-positive in the old bulk-update. (Gemini R2 §2.A)
            for s in combined_steps:
                val_key = s.get('validation')
                if not val_key:
                    continue
                if s.get('skip_if_checked') or s.get('verified_by_checked_state'):
                    checked_state_keys.add(val_key)
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
    # consolidate_attachments raises if FAMILY_KERNEL or the platform
    # IDENTITY file is missing — HARD RULE enforcement happens there.
    # Catch and surface through the standard fail() path so the caller
    # sees a structured HALT event instead of a raw traceback.
    try:
        pkg = consolidate_attachments(platform, caller_files)
    except Exception as e:
        fail('attach', f'Identity consolidation failed — {e}', platform)

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
        # Record the actual consolidated package that was uploaded (the
        # /tmp/taey_package_*.md), not just the caller's file — audit
        # provenance needs the FAMILY_KERNEL + IDENTITY artifact that
        # went to the platform. Caller file is recoverable from pkg
        # section headers. (ChatGPT audit bug 4.)
        attachments = [pkg]
        if file_path and file_path != pkg:
            attachments.append(file_path)
        session_id = store_consultation(
            platform=platform,
            prompt=message,
            mode=mode,
            tools=tools,
            attachments=attachments,
            url=url,
        )
        print(json.dumps({'event': 'step_ok', 'step': 'store', 'session_id': session_id}))
    except Exception as e:
        print(json.dumps({'event': 'step_warn', 'step': 'store', 'error': str(e)}))

    print(json.dumps({'event': 'dispatched', 'platform': platform, 'url': url[:80],
                       'session_id': session_id,
                       'msg': 'Send confirmed, monitor spawned. Response NOT yet complete.'}))
    return 0


def _rate_limit_wait(platform: str, cfg: dict, overrides: dict) -> None:
    """Enforce per-platform rate limit via Redis-backed action log.

    Reads config from workflow/top-level rate_limit block:
      max_actions_per_hour, min_delay_seconds, jitter_seconds [min,max],
      defer_warn_threshold_seconds.

    CLI overrides dict can provide max_per_hour / min_delay to tighten
    the YAML-declared defaults. If the required wait would exceed the
    defer_warn threshold (default 600s), logs a WARN event before
    sleeping — dispatcher can catch it and back off upstream rather
    than silently sleeping 30+ min.
    """
    rl = cfg.get('rate_limit') or cfg.get('workflow', {}).get('rate_limit')
    if not rl:
        return
    import random
    try:
        import redis
    except ImportError:
        print(json.dumps({'event': 'warning', 'step': 'rate_limit',
                          'note': 'redis module not available; rate limit disabled'}))
        return

    max_per_hour = overrides.get('max_per_hour') or rl.get('max_actions_per_hour', 3)
    min_delay = overrides.get('min_delay') or rl.get('min_delay_seconds', 60)
    jitter = rl.get('jitter_seconds', [0, 0])
    warn_threshold = rl.get('defer_warn_threshold_seconds', 600)

    r = redis.Redis(host=os.environ.get('REDIS_HOST', '127.0.0.1'),
                    port=int(os.environ.get('REDIS_PORT', '6379')),
                    decode_responses=True)
    key = f'taey:rate:{platform}'
    now = int(time.time())
    hour_ago = now - 3600

    # Trim old entries + get current action log.
    # zrangebyscore without withscores=True returns MEMBERS (unique ms+rand
    # suffix strings stored below); we need the SCORES (unix seconds)
    # to compute wait times. Treasurer caught this 2026-04-20: the old
    # code read members as if they were seconds, producing wait values
    # of ~1.77e12 seconds and OverflowError on time.sleep().
    r.zremrangebyscore(key, 0, hour_ago)
    recent_scored = r.zrangebyscore(key, hour_ago, '+inf', withscores=True)
    recent = [int(score) for _member, score in recent_scored]
    in_last_hour = len(recent)
    last_action_ts = max(recent) if recent else 0

    # Compute required wait
    hour_wait = 0
    if in_last_hour >= max_per_hour:
        oldest_in_window = min(recent)
        hour_wait = (oldest_in_window + 3600) - now
    delay_wait = max(0, (last_action_ts + min_delay) - now) if last_action_ts else 0
    base_wait = max(hour_wait, delay_wait)

    if jitter and len(jitter) == 2 and jitter[1] > 0:
        jitter_add = random.uniform(jitter[0], jitter[1])
    else:
        jitter_add = 0
    total_wait = int(base_wait + jitter_add)

    if total_wait > warn_threshold:
        print(json.dumps({'event': 'warning', 'step': 'rate_limit',
                          'platform': platform,
                          'wait_seconds': total_wait,
                          'warn_threshold': warn_threshold,
                          'in_last_hour': in_last_hour,
                          'max_per_hour': max_per_hour,
                          'note': f'rate-limit defer >{warn_threshold}s — dispatcher should back off'}))
    if total_wait > 0:
        print(json.dumps({'event': 'step_ok', 'step': 'rate_limit_wait',
                          'platform': platform, 'wait_seconds': total_wait,
                          'in_last_hour': in_last_hour, 'max_per_hour': max_per_hour}))
        time.sleep(total_wait)
    # Record this action's timestamp
    r.zadd(key, {str(int(time.time()) * 1000 + random.randint(0, 999)): int(time.time())})
    # Keep 24h of history (TTL-safe)
    r.expire(key, 86400)


def run_action(platform: str, action_name: str, message: str,
               url_override: str | None = None,
               rate_overrides: dict | None = None) -> int:
    """Run a single action sequence (post / reply / etc) instead of the
    full consultation flow. Used by action-based platforms (x_twitter).

    Action-based platforms declare workflow.actions.<name> with a
    sequence and an identity_attach flag. No mode_setup, no attach,
    no monitor, no extract — just navigate + action.sequence.
    """
    from consultation_v2.yaml_contract import load_platform_yaml
    cfg = load_platform_yaml(platform)
    actions = cfg.get('workflow', {}).get('actions', {})
    if action_name not in actions:
        fail('action', f'action {action_name!r} not in workflow.actions for {platform}', platform)
    action_cfg = actions[action_name]

    print(json.dumps({'event': 'start', 'platform': platform, 'action': action_name}))

    # Rate limit before the action fires.
    _rate_limit_wait(platform, cfg, rate_overrides or {})

    # Navigate to URL. Action may require a URL override (e.g. reply
    # needs the status URL). Otherwise use urls.fresh from YAML.
    if action_cfg.get('requires_url') and not url_override:
        fail('navigate', f'action {action_name!r} requires --url', platform)
    target_url = url_override or cfg.get('urls', {}).get('fresh', '')
    if not target_url:
        fail('navigate', 'No URL to navigate to (no --url and no urls.fresh)', platform)
    result = act(platform, 'navigate', target_url)
    if result.get('error'):
        fail('navigate', f'Navigation failed: {result}', platform)
    settle = cfg.get('urls', {}).get('settle_delay', 5)
    time.sleep(settle)

    snap = inspect_platform(platform)
    if not snap.get('url'):
        fail('navigate', 'No URL after navigation', platform)
    print(json.dumps({'event': 'step_ok', 'step': 'navigate', 'url': snap.get('url', '')[:80]}))

    # HARD RULE amendment (approved by treasurer 2026-04-20): action-
    # based platforms may opt out of identity attach. x_twitter post/
    # reply actions set identity_attach: false because attaching
    # FAMILY_KERNEL+IDENTITY to a public tweet is unsafe. Other
    # platforms can adopt per-action. When identity_attach is true
    # (or absent with default), we'd invoke consolidate_attachments —
    # but no current action needs it, so we skip the full path here.
    if action_cfg.get('identity_attach', True):
        fail('action',
             f'action {action_name!r} requested identity_attach: true but '
             f'run_action has no attach pipeline — implement or set false',
             platform)

    # Run the action sequence via the primitive runner.
    sequence = action_cfg.get('sequence')
    if not sequence:
        fail('action', f'workflow.actions.{action_name}.sequence missing', platform)

    from consultation_v2.runtime import ConsultationRuntime
    from consultation_v2.primitives import run_sequence
    rt = ConsultationRuntime(platform)
    ctx = {'platform': platform, 'runtime': rt, 'cfg': cfg,
           'message': message, 'vars': {}}
    res = run_sequence(ctx, sequence, step_name=f'action:{action_name}')
    if not res['ok']:
        fail('action', res['error'], platform)

    # Capture the post-action URL for logs.
    post_snap = inspect_platform(platform)
    final_url = post_snap.get('url', '') or ''
    print(json.dumps({'event': 'dispatched', 'platform': platform,
                      'action': action_name,
                      'url': final_url[:100],
                      'msg': f'{action_name} action complete.'}))
    return 0


def main():
    parser = argparse.ArgumentParser(description='Validated consultation orchestrator')
    _platforms = sorted(p.stem for p in (_PROJECT_ROOT / 'consultation_v2' / 'platforms').glob('*.yaml'))
    parser.add_argument('platform', choices=_platforms)
    parser.add_argument('message', help='Prompt message text (or content for post/reply)')
    parser.add_argument('--file', default=None, help='File to attach (consultation only)')
    parser.add_argument('--action', default=None,
                        help='Action name for action-based platforms (x_twitter: post, reply). '
                             'Default: full consultation flow.')
    parser.add_argument('--url', default=None,
                        help='URL override for navigate (e.g. reply target status URL)')
    parser.add_argument('--urls-file', default=None,
                        help='Batch reply: JSON list of {url, message} objects. Iterates with '
                             'rate limiting between each.')
    parser.add_argument('--max-per-hour', type=int, default=None,
                        help='Override rate_limit.max_actions_per_hour')
    parser.add_argument('--min-delay', type=int, default=None,
                        help='Override rate_limit.min_delay_seconds')
    args = parser.parse_args()

    # If --urls-file given, iterate batch. Each entry is a separate
    # action dispatch — rate limiter applies between them.
    if args.urls_file:
        if not args.action:
            fail('cli', '--urls-file requires --action', args.platform)
        with open(args.urls_file) as f:
            batch = json.load(f)
        rate_overrides = {'max_per_hour': args.max_per_hour, 'min_delay': args.min_delay}
        exit_codes = []
        for entry in batch:
            url = entry.get('url')
            msg = entry.get('message') or args.message
            code = run_action(args.platform, args.action, msg, url, rate_overrides)
            exit_codes.append(code)
        return 0 if all(c == 0 for c in exit_codes) else 1

    # Single dispatch.
    if args.action:
        return run_action(
            platform=args.platform,
            action_name=args.action,
            message=args.message,
            url_override=args.url,
            rate_overrides={'max_per_hour': args.max_per_hour, 'min_delay': args.min_delay},
        )

    # Default: consultation flow.
    return run_consultation(
        platform=args.platform,
        message=args.message,
        file_path=args.file,
    )


if __name__ == '__main__':
    raise SystemExit(main())
