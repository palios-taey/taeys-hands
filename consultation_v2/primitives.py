"""consultation_v2/primitives.py — Step primitives for YAML-driven workflows.

The driver is a dumb executor of step sequences declared in YAML. Each
platform YAML lists an ordered sequence of primitive operations per
workflow stage (extract/attach/prompt/send/mode_setup/monitor). The
executor iterates the list and dispatches each step to a primitive here.

Rule: zero platform knowledge in this file. Each primitive is a generic
operation (click this element, paste this text, wait for this indicator).
Platform-specific behaviors (Perplexity expand before copy, ChatGPT
long-paste → show-in-text-field, Gemini DR two-phase send) are expressed
entirely as sequences of these primitives in YAML.

Context (`ctx`) is a mutable dict passed through every step. It carries:
  - platform: str
  - runtime: ConsultationRuntime
  - cfg: loaded YAML
  - message: the prompt text (available as ${message} in step args)
  - vars: {name: value} set by read_clipboard, capture_url, etc.
  - last_error: set when a primitive returns failure

Each primitive returns {'ok': bool, 'event': dict|None, 'error': str|None}.
The sequence runner fails closed on any non-ok return unless the step
declares `optional: true`, in which case execution continues. Optional
steps are for patterns like "click this IF present" (Gemini DR plan
button only appears after the plan phase; absent = skip).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

# The registry is populated at import time by @primitive decorators below.
_REGISTRY: Dict[str, Callable] = {}


def primitive(name: str):
    """Register a function as a named primitive callable from YAML."""
    def wrap(fn):
        _REGISTRY[name] = fn
        return fn
    return wrap


def get_primitive(name: str) -> Optional[Callable]:
    return _REGISTRY.get(name)


_VAR_REF = re.compile(r'\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}')


def resolve(ctx: dict, value: Any) -> Any:
    """Expand ${var} references in strings using ctx['vars'] and ctx['message']."""
    if not isinstance(value, str):
        return value
    def repl(m):
        name = m.group(1)
        if name == 'message':
            return ctx.get('message', '')
        return str(ctx.get('vars', {}).get(name, ''))
    return _VAR_REF.sub(repl, value)


def _fail(step_name: str, msg: str, kind: str = 'error') -> dict:
    """Fail result. `kind` distinguishes hard failures from 'absent_optional'
    which the runner may skip when the step declares optional: true. All
    other failure kinds (click/inspect/verify failures) must halt even on
    optional steps — optional only means 'the element may not be present',
    it does NOT mean 'ignore any failure'."""
    return {'ok': False, 'event': None, 'error': f'{step_name}: {msg}', 'kind': kind}


def _ok(event: Optional[dict] = None) -> dict:
    return {'ok': True, 'event': event, 'error': None}


def _must_inspect(ctx: dict, primitive_name: str, scope: str = 'document'):
    """Inspect and fail closed if the inspection errored. Primitives that
    gate state on snapshot contents must never silently proceed with an
    empty-on-error dict — a missing-snapshot branch would make
    assert_indicator_absent falsely pass, wait_for_indicator_absent
    falsely declare completion, and require_url_changed falsely verify
    a change (empty != baseline).
    """
    from consultation_v2.consult import inspect_platform
    snap = inspect_platform(ctx['platform'], scope)
    if 'error' in snap:
        return None, _fail(primitive_name, f'inspect failed ({scope}): {snap["error"]}')
    return snap, None


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


@primitive('press')
def press(ctx: dict, step: dict) -> dict:
    """Press a keyboard key or chord.

    YAML: `- action: press
            key: ctrl+End
            delay: 2.0`
    """
    key = step.get('key')
    if not key:
        return _fail('press', "step.key missing")
    rt = ctx['runtime']
    ok = rt.press(key)
    if not ok:
        return _fail('press', f'keypress {key!r} failed')
    delay = step.get('delay', 0)
    if delay:
        time.sleep(delay)
    return _ok({'event': 'step_ok', 'action': 'press', 'key': key})


@primitive('paste')
def paste(ctx: dict, step: dict) -> dict:
    """Paste text (or ${message}) via clipboard + Ctrl+V.

    YAML: `- action: paste
            text: ${message}
            delay: 1.0`
    """
    text = resolve(ctx, step.get('text', ''))
    rt = ctx['runtime']
    ok = rt.paste(text)
    if not ok:
        return _fail('paste', 'runtime.paste returned False')
    delay = step.get('delay', 0)
    if delay:
        time.sleep(delay)
    return _ok({'event': 'step_ok', 'action': 'paste', 'length': len(text)})


@primitive('click')
def click(ctx: dict, step: dict) -> dict:
    """Click a YAML element_map key. Fail closed if element not present
    unless step.optional=true (then log and continue).

    pick controls selection when multiple elements match the key:
      - 'first' (default): first hit in the snapshot's mapped list.
      - 'last_by_y': highest y-coordinate among matches (e.g., the most
        recent response's Copy button at the bottom of the page).

    YAML: `- action: click
            element: copy_button
            pick: last_by_y
            scope: document     # document|menu, default document
            click_strategy: atspi_only
            delay: 1.0
            optional: false`
    """
    from consultation_v2.snapshot import build_menu_snapshot, build_snapshot
    element_key = step.get('element')
    if not element_key:
        return _fail('click', 'step.element missing')
    scope = step.get('scope', 'document')
    if scope == 'menu':
        _, _, snap = build_menu_snapshot(ctx['platform'])
    else:
        _, _, snap = build_snapshot(ctx['platform'])
    pick = step.get('pick', 'first')
    if pick == 'last_by_y':
        el = snap.last(element_key)
    elif pick == 'first':
        el = snap.first(element_key)
    elif pick == 'first_by_y':
        # Lowest-y match — for pages with multiple same-named elements
        # where the topmost is the target (e.g. status-page "More"
        # button on the main tweet vs thread-reply "More" buttons
        # below it). Not the same as `first` which uses tree-walk
        # order; first_by_y explicitly sorts by vertical position.
        items = snap.mapped.get(element_key) or []
        el = sorted(items, key=lambda i: (i.y or 0, i.x or 0))[0] if items else None
    else:
        return _fail('click', f'unknown pick strategy {pick!r} (must be first, first_by_y, or last_by_y)')
    if not el:
        # Element absent. `optional: true` means "this element may not
        # exist in every state" — e.g. ChatGPT's "Show in text field"
        # only appears on long paste auto-attach; Gemini's "Start
        # research" only appears after the DR plan phase. Return an
        # absent_optional result so the runner can skip THIS specific
        # case. Click failures when the element IS present are
        # different and must NOT be skipped by optional.
        return _fail('click',
                     f'element {element_key!r} not in snapshot (scope={scope}, pick={pick})',
                     kind='absent_optional' if step.get('optional') else 'error')
    strategy = step.get('click_strategy')
    rt = ctx['runtime']
    ok = rt.click(el, strategy=strategy)
    if not ok:
        # Element was present but the click itself failed (permission,
        # race, stale atspi). Do NOT skip even if optional is set.
        return _fail('click', f'click on {element_key!r} returned False')
    delay = step.get('delay', 0)
    if delay:
        time.sleep(delay)
    return _ok({'event': 'step_ok', 'action': 'click', 'element': element_key,
                'pick': pick, 'x': el.x, 'y': el.y})


@primitive('write_clipboard')
def write_clipboard(ctx: dict, step: dict) -> dict:
    """Write text (default empty) to the clipboard.

    YAML: `- action: write_clipboard
            text: ''`
    """
    text = resolve(ctx, step.get('text', ''))
    rt = ctx['runtime']
    ok = rt.write_clipboard(text)
    if not ok:
        return _fail('write_clipboard', 'runtime.write_clipboard returned False')
    return _ok({'event': 'step_ok', 'action': 'write_clipboard', 'length': len(text)})


@primitive('read_clipboard')
def read_clipboard(ctx: dict, step: dict) -> dict:
    """Read the clipboard into a named variable. Fail if empty or below
    min_chars.

    YAML: `- action: read_clipboard
            into: response
            min_chars: 100`
    """
    into = step.get('into')
    if not into:
        return _fail('read_clipboard', 'step.into (variable name) missing')
    rt = ctx['runtime']
    content = rt.read_clipboard()
    if content is None:
        return _fail('read_clipboard', 'runtime.read_clipboard returned None')
    min_chars = step.get('min_chars', 1)
    if len(content) < min_chars:
        return _fail('read_clipboard',
                     f'clipboard has {len(content)} chars, min {min_chars}')
    ctx.setdefault('vars', {})[into] = content
    return _ok({'event': 'step_ok', 'action': 'read_clipboard',
                'into': into, 'length': len(content)})


@primitive('verify_text_landed')
def verify_text_landed(ctx: dict, step: dict) -> dict:
    """Verify ${message} landed in the specified input element via AT-SPI
    Text interface. Compares character count with slack, requires the
    first N chars of the (whitespace-normalized) message to appear at the
    start of the live text.

    YAML: `- action: verify_text_landed
            element: input
            slack_absolute: 20
            slack_ratio: 0.01
            head_chars: 30`
    """
    element_key = step.get('element')
    if not element_key:
        return _fail('verify_text_landed', 'step.element missing')
    cfg = ctx['cfg']
    spec = cfg.get('tree', {}).get('element_map', {}).get(element_key, {})
    name = spec.get('name', '')
    role = spec.get('role', '')
    states = spec.get('states_include', [])
    if not role:
        return _fail('verify_text_landed', f'element_map.{element_key}.role missing')
    rt = ctx['runtime']
    result = rt.read_element_text(name, role, required_states=states)
    if 'error' in result:
        return _fail('verify_text_landed',
                     f'read_element_text failed: {result["error"]}')
    live_text = result.get('text', '') or ''
    live_count = result.get('char_count', 0)
    message = ctx.get('message', '')
    expected = len(message)
    slack_absolute = step.get('slack_absolute', 20)
    slack_ratio = step.get('slack_ratio', 0.01)
    slack = max(slack_absolute, int(expected * slack_ratio))
    if expected > 0 and live_count == 0:
        return _fail('verify_text_landed',
                     f'input has 0 chars, expected {expected}; live head: {live_text[:80]!r}')
    if expected > slack:
        min_chars = expected - slack
        if live_count < min_chars:
            return _fail('verify_text_landed',
                         f'input has {live_count} chars, expected {expected} '
                         f'(slack {slack}, min {min_chars}); live head: {live_text[:80]!r}')
    head_chars = step.get('head_chars', 30)
    def _norm_ws(s):
        return ' '.join(s.split())
    msg_head = _norm_ws(message)[:head_chars]
    live_head = _norm_ws(live_text)[:200]
    if msg_head and not live_head.startswith(msg_head):
        return _fail('verify_text_landed',
                     f'expected prefix {msg_head!r} not at start of input; '
                     f'live head {live_head[:80]!r}')
    return _ok({'event': 'step_ok', 'action': 'verify_text_landed',
                'element': element_key, 'expected_chars': expected,
                'live_chars': live_count, 'slack': slack})


@primitive('read_element_text')
def read_element_text_primitive(ctx: dict, step: dict) -> dict:
    """Read the AT-SPI Text interface of a named element into a variable.

    Generic AT-SPI primitive. Works on any platform; the YAML names the
    element via element_map. Typical uses: reading the response container
    for extraction when the platform's Copy button truncates or requires
    multi-state UI traversal. The element_map entry must have name+role
    (and optionally states_include) specific enough to uniquely match.

    YAML: `- action: read_element_text
            element: response_landmark
            into: response
            min_chars: 500`
    """
    element_key = step.get('element')
    if not element_key:
        return _fail('read_element_text', 'step.element missing')
    into = step.get('into')
    if not into:
        return _fail('read_element_text', 'step.into (variable name) missing')
    cfg = ctx['cfg']
    spec = cfg.get('tree', {}).get('element_map', {}).get(element_key, {})
    name = spec.get('name', '')
    role = spec.get('role', '')
    states = spec.get('states_include', [])
    if not role:
        return _fail('read_element_text', f'element_map.{element_key}.role missing')
    rt = ctx['runtime']
    result = rt.read_element_text(name, role, required_states=states)
    if 'error' in result:
        return _fail('read_element_text',
                     f'{element_key!r}: {result["error"]}')
    text = result.get('text', '') or ''
    count = result.get('char_count', 0)
    min_chars = step.get('min_chars', 1)
    if count < min_chars:
        return _fail('read_element_text',
                     f'{element_key!r} has {count} chars, min {min_chars}')
    ctx.setdefault('vars', {})[into] = text
    return _ok({'event': 'step_ok', 'action': 'read_element_text',
                'element': element_key, 'into': into, 'chars': count})


@primitive('assert_indicator_absent')
def assert_indicator_absent(ctx: dict, step: dict) -> dict:
    """Fail immediately if any of the named validation indicators is
    currently present in the document tree. Used for stale-state checks
    (e.g. pre-send: stop_button must NOT already be there from a prior
    generation, else the send step would false-confirm).

    YAML: `- action: assert_indicator_absent
            validation: send_success`
    """
    from consultation_v2.consult import _all_elements
    val_key = step.get('validation')
    if not val_key:
        return _fail('assert_indicator_absent', 'step.validation missing')
    cfg = ctx['cfg']
    val_cfg = cfg.get('validation', {}).get(val_key, {})
    indicators = val_cfg.get('indicators', [])
    if not indicators:
        return _fail('assert_indicator_absent',
                     f'validation.{val_key}.indicators missing or empty')
    snap, err = _must_inspect(ctx, 'assert_indicator_absent')
    if err:
        return err
    elements = _all_elements(snap)
    for ind in indicators:
        if any(e.get('name') == ind.get('name') and
               e.get('role') == ind.get('role') for e in elements):
            return _fail('assert_indicator_absent',
                         f'validation.{val_key} indicator {ind!r} is present — '
                         f'stale state from previous step')
    return _ok({'event': 'step_ok', 'action': 'assert_indicator_absent',
                'validation': val_key})


@primitive('wait_for_indicator')
def wait_for_indicator(ctx: dict, step: dict) -> dict:
    """Poll until every indicator under validation.<key>.indicators is
    present in the document tree, or fail on timeout.

    YAML: `- action: wait_for_indicator
            validation: send_success
            timeout: 15
            poll_interval: 2.0`
    """
    from consultation_v2.consult import _all_elements
    val_key = step.get('validation')
    if not val_key:
        return _fail('wait_for_indicator', 'step.validation missing')
    cfg = ctx['cfg']
    val_cfg = cfg.get('validation', {}).get(val_key, {})
    indicators = val_cfg.get('indicators', [])
    if not indicators:
        return _fail('wait_for_indicator',
                     f'validation.{val_key}.indicators missing or empty')
    timeout = step.get('timeout', 15)
    poll = step.get('poll_interval', 2.0)
    into = step.get('into')
    deadline = time.time() + timeout
    # Claude R11 #2: initialize `missing` BEFORE the loop. If deadline is
    # reached before the first poll (e.g. very small timeout, clock skew,
    # budget burned by prior steps), the loop body never runs and the
    # fail message below would NameError without this initialization.
    missing = list(indicators)
    while time.time() < deadline:
        snap, err = _must_inspect(ctx, 'wait_for_indicator')
        if err:
            return err
        elements = _all_elements(snap)
        missing = []
        for ind in indicators:
            found = any(e.get('name') == ind.get('name') and
                        e.get('role') == ind.get('role') for e in elements)
            if not found:
                missing.append(ind)
        if not missing:
            if into:
                ctx.setdefault('vars', {})[into] = True
            return _ok({'event': 'step_ok', 'action': 'wait_for_indicator',
                        'validation': val_key, 'elapsed': round(time.time() - (deadline - timeout), 1)})
        time.sleep(poll)
    # Timeout: if `into` is set, record the negative outcome so downstream
    # logic (e.g. monitor deciding RESPONSE_COMPLETE vs RESPONSE_UNVERIFIED)
    # can distinguish a present-but-late indicator from a never-appeared
    # one. The step's `optional: true` still determines whether the runner
    # halts or skips — `into` only records the state.
    if into:
        ctx.setdefault('vars', {})[into] = False
    return _fail('wait_for_indicator',
                 f'validation.{val_key} indicators not present within {timeout}s: {missing}',
                 kind='timeout')


@primitive('wait_for_indicator_absent')
def wait_for_indicator_absent(ctx: dict, step: dict) -> dict:
    """Poll until the validation indicators are ABSENT for N consecutive
    cycles (used for stop_button disappearance as response-done signal).
    `validation` names the indicator set; `required_absent_cycles` is the
    gate; `timeout` hard caps the wait.

    YAML: `- action: wait_for_indicator_absent
            validation: send_success
            required_absent_cycles: 3
            poll_interval: 2.0
            timeout: 3600`
    """
    from consultation_v2.consult import _all_elements
    val_key = step.get('validation')
    if not val_key:
        return _fail('wait_for_indicator_absent', 'step.validation missing')
    cfg = ctx['cfg']
    val_cfg = cfg.get('validation', {}).get(val_key, {})
    indicators = val_cfg.get('indicators', [])
    if not indicators:
        return _fail('wait_for_indicator_absent',
                     f'validation.{val_key}.indicators missing or empty')
    required_absent = step.get('required_absent_cycles', 3)
    poll = step.get('poll_interval', 2.0)
    timeout = step.get('timeout', 3600)
    deadline = time.time() + timeout
    absent_cycles = 0
    while time.time() < deadline:
        snap, err = _must_inspect(ctx, 'wait_for_indicator_absent')
        if err:
            return err
        elements = _all_elements(snap)
        any_present = False
        for ind in indicators:
            if any(e.get('name') == ind.get('name') and
                   e.get('role') == ind.get('role') for e in elements):
                any_present = True
                break
        if any_present:
            absent_cycles = 0
        else:
            absent_cycles += 1
            if absent_cycles >= required_absent:
                return _ok({'event': 'step_ok', 'action': 'wait_for_indicator_absent',
                            'validation': val_key, 'absent_cycles': absent_cycles})
        time.sleep(poll)
    return _fail('wait_for_indicator_absent',
                 f'validation.{val_key} indicators still present at timeout {timeout}s',
                 kind='timeout')


@primitive('snapshot_buttons')
def snapshot_buttons(ctx: dict, step: dict) -> dict:
    """Capture a Counter of element names in the current document snapshot
    into a named variable, filtered by role. Used as the baseline for
    verify_attachment_chip (pre-attach vs post-attach diff).

    The role filter is REQUIRED from YAML — a hardcoded 'push button'
    default would be a rule-2 violation: not every platform exposes the
    attachment chip as a push button (Gemini audit flagged this).

    YAML: `- action: snapshot_buttons
            into: pre_attach_buttons
            role: push button`
    """
    from collections import Counter
    from consultation_v2.consult import _all_elements
    into = step.get('into')
    if not into:
        return _fail('snapshot_buttons', 'step.into (variable name) missing')
    role = step.get('role')
    if not role:
        return _fail('snapshot_buttons',
                     'step.role missing — the chip element role must be '
                     'declared in YAML, not hardcoded in the primitive')
    snap, err = _must_inspect(ctx, 'snapshot_buttons')
    if err:
        return err
    buttons = Counter(e.get('name') for e in _all_elements(snap)
                      if e.get('role') == role)
    ctx.setdefault('vars', {})[into] = buttons
    return _ok({'event': 'step_ok', 'action': 'snapshot_buttons',
                'into': into, 'role': role, 'unique_elements': len(buttons)})


@primitive('file_dialog_upload')
def file_dialog_upload(ctx: dict, step: dict) -> dict:
    """Drive a GTK file dialog to upload a given file path. Uses the
    platform YAML's tree.dialog_titles to find the dialog window and
    workflow.attachment.dialog_* keys for keystrokes (dialog_location_
    shortcut, dialog_select_all_key, dialog_paste_key, dialog_confirm_key).

    The file path typically comes from the identity-consolidated package
    path which consult.py writes into ctx.vars before the sequence runs.

    YAML: `- action: file_dialog_upload
            file: ${pkg}
            delay: 5.0`
    """
    import subprocess as _subp
    import re as _re
    file_path = resolve(ctx, step.get('file', ''))
    if not file_path:
        return _fail('file_dialog_upload', 'step.file missing (or empty after resolve)')
    cfg = ctx['cfg']
    tree = cfg.get('tree', {})
    attach = cfg.get('workflow', {}).get('attachment', {})
    dialog_titles = tree.get('dialog_titles', [])
    if not dialog_titles:
        return _fail('file_dialog_upload', 'tree.dialog_titles missing from YAML')
    location_shortcut = attach.get('dialog_location_shortcut')
    select_all_key = attach.get('dialog_select_all_key')
    paste_key = attach.get('dialog_paste_key')
    confirm_key = attach.get('dialog_confirm_key')
    if not all([location_shortcut, select_all_key, paste_key, confirm_key]):
        return _fail('file_dialog_upload',
                     'workflow.attachment.dialog_* keys missing from YAML '
                     '(need dialog_location_shortcut, dialog_select_all_key, '
                     'dialog_paste_key, dialog_confirm_key)')
    timing = cfg.get('workflow', {}).get('timing', {})
    for t in ('dialog_after_focus', 'dialog_after_path_entry', 'dialog_after_paste'):
        if t not in timing:
            return _fail('file_dialog_upload', f'workflow.timing.{t} missing from YAML')

    import os as _os
    env = dict(_os.environ)
    # DISPLAY is already set by run_sequence's _ensure_platform_env.

    # Find the dialog window — anchored word-boundary regex so "Open"
    # doesn't match "OpenAI - ChatGPT". Real dialog titles look like
    # "File Upload - <app> — Mozilla Firefox".
    found_wid = None
    for title in dialog_titles:
        anchored = f'^{_re.escape(title)}\\b'
        r = _subp.run(['xdotool', 'search', '--name', anchored],
                      capture_output=True, text=True, timeout=3, env=env)
        wids = [w.strip() for w in r.stdout.strip().split('\n') if w.strip()]
        if wids:
            found_wid = wids[-1]
            break
    if not found_wid:
        return _fail('file_dialog_upload',
                     f'no dialog window matching any of {dialog_titles!r}')

    # Activate the dialog so subsequent keystrokes land there.
    r = _subp.run(['xdotool', 'windowactivate', found_wid],
                  capture_output=True, timeout=5, env=env)
    if r.returncode != 0:
        return _fail('file_dialog_upload',
                     f'windowactivate failed for wid {found_wid}: {r.stderr!r}')
    time.sleep(timing['dialog_after_focus'])

    # Sequence: Ctrl+L (location bar) → Ctrl+A (select) → xsel paste →
    # Ctrl+V → Enter.
    for cmd, delay_key in [
        (['xdotool', 'key', location_shortcut], 'dialog_after_focus'),
        (['xdotool', 'key', select_all_key], 'dialog_after_path_entry'),
    ]:
        r = _subp.run(cmd, env=env, capture_output=True, timeout=3)
        if r.returncode != 0:
            return _fail('file_dialog_upload',
                         f'{cmd[-1]} keypress failed: {r.stderr!r}')
        time.sleep(timing[delay_key])

    r = _subp.run(['xsel', '--clipboard', '--input'],
                  input=file_path.encode(), env=env, capture_output=True, timeout=3)
    if r.returncode != 0:
        return _fail('file_dialog_upload', f'xsel write failed: {r.stderr!r}')
    time.sleep(timing['dialog_after_path_entry'])

    for cmd, delay_key in [
        (['xdotool', 'key', paste_key], 'dialog_after_paste'),
        (['xdotool', 'key', confirm_key], None),
    ]:
        r = _subp.run(cmd, env=env, capture_output=True, timeout=3)
        if r.returncode != 0:
            return _fail('file_dialog_upload',
                         f'{cmd[-1]} keypress failed: {r.stderr!r}')
        if delay_key:
            time.sleep(timing[delay_key])

    delay = step.get('delay', 0)
    if delay:
        time.sleep(delay)
    return _ok({'event': 'step_ok', 'action': 'file_dialog_upload',
                'file': file_path, 'dialog_wid': found_wid})


@primitive('verify_attachment_chip')
def verify_attachment_chip(ctx: dict, step: dict) -> dict:
    """Compare pre-attach and post-attach push-button Counters; require
    at least one new button whose name matches the YAML chip template.
    Some platforms (Grok) have no filename-specific chip — those YAMLs
    should declare validation.<key>.attach_unverifiable_reason and the
    primitive emits a warning event while returning ok. Other platforms
    declare file_chip_template with {filename}, {size_kb}, etc.

    YAML: `- action: verify_attachment_chip
            baseline: pre_attach_buttons
            validation: attach_success
            file: ${pkg}
            timeout: 20
            poll_interval: 1.0`
    """
    from collections import Counter
    from pathlib import Path as _Path
    from consultation_v2.consult import _all_elements
    baseline_var = step.get('baseline')
    val_key = step.get('validation')
    if not baseline_var:
        return _fail('verify_attachment_chip', 'step.baseline var missing')
    if not val_key:
        return _fail('verify_attachment_chip', 'step.validation missing')
    cfg = ctx['cfg']
    val_cfg = cfg.get('validation', {}).get(val_key, {})
    if not val_cfg:
        return _fail('verify_attachment_chip',
                     f'validation.{val_key!r} missing from YAML')

    # Unverifiable path: YAML explicitly documents that the platform's
    # chip has no filename-specific AT-SPI node. Emit warning, return ok.
    unverifiable = val_cfg.get('attach_unverifiable_reason')
    if unverifiable:
        return _ok({'event': 'warning',
                    'action': 'verify_attachment_chip',
                    'validation': val_key,
                    'unverifiable_reason': unverifiable,
                    'note': 'dialog-success only — chip not AT-SPI verifiable'})

    # Standard chip template validation.
    if not val_cfg.get('diff_validated'):
        return _fail('verify_attachment_chip',
                     f'validation.{val_key}.diff_validated must be true '
                     f'(or declare attach_unverifiable_reason)')
    template = val_cfg.get('file_chip_template')
    if not template:
        return _fail('verify_attachment_chip',
                     f'validation.{val_key}.file_chip_template missing')
    file_path = resolve(ctx, step.get('file', ''))
    if not file_path:
        return _fail('verify_attachment_chip',
                     'step.file missing (or empty after resolve)')
    filename = _Path(file_path).name
    filename_stem = _Path(file_path).stem
    size_bytes = _Path(file_path).stat().st_size
    size_kb_str = f"{size_bytes / 1000:.1f}"
    expected = (template
                .replace('{filename}', filename)
                .replace('{filename_stem}', filename_stem)
                .replace('{size_kb}', size_kb_str)
                .replace('{size_bytes}', str(size_bytes)))

    baseline = ctx.get('vars', {}).get(baseline_var)
    if baseline is None:
        return _fail('verify_attachment_chip',
                     f'baseline var {baseline_var!r} not set (run snapshot_buttons first)')

    # Role must match the one used by snapshot_buttons to produce the
    # baseline — otherwise the Counter subtraction is meaningless.
    # Required from YAML (same rationale as snapshot_buttons).
    role = step.get('role')
    if not role:
        return _fail('verify_attachment_chip',
                     'step.role missing — the chip element role must be '
                     'declared in YAML (match snapshot_buttons step.role)')
    timeout = step.get('timeout', 20)
    poll = step.get('poll_interval', 1.0)
    deadline = time.time() + timeout
    new_buttons = Counter()
    while time.time() < deadline:
        snap, err = _must_inspect(ctx, 'verify_attachment_chip')
        if err:
            return err
        post_buttons = Counter(e.get('name') for e in _all_elements(snap)
                               if e.get('role') == role)
        new_buttons = post_buttons - baseline
        if expected in new_buttons and new_buttons[expected] > 0:
            return _ok({'event': 'step_ok', 'action': 'verify_attachment_chip',
                        'chip': expected, 'match': 'exact'})
        time.sleep(poll)
    return _fail('verify_attachment_chip',
                 f'no new element {expected!r} (role={role!r}) within {timeout}s. '
                 f'New elements: {dict(new_buttons)}')


@primitive('capture_url')
def capture_url(ctx: dict, step: dict) -> dict:
    """Capture the current URL into a named variable. Fails closed if the
    URL is empty — subsequent require_url_changed checks need a non-empty
    baseline to be meaningful.
    """
    into = step.get('into')
    if not into:
        return _fail('capture_url', 'step.into missing')
    snap, err = _must_inspect(ctx, 'capture_url')
    if err:
        return err
    url = snap.get('url', '') or ''
    if not url:
        return _fail('capture_url', 'snapshot has no URL — navigation not complete?')
    ctx.setdefault('vars', {})[into] = url
    return _ok({'event': 'step_ok', 'action': 'capture_url',
                'into': into, 'url': url[:100]})


@primitive('regenerate_if_short')
def regenerate_if_short(ctx: dict, step: dict) -> dict:
    """Post-extract retry loop: if the response stored in `response_var`
    is below `min_chars`, click `retry_element` (typically the platform's
    Rewrite/Regenerate button), wait for generation to restart and finish,
    re-read the response. Up to `max_retries` iterations. Fails closed if
    the response is still short after retries — caller surfaces this as
    an UNVERIFIED outcome.

    Used for Perplexity Deep Research when the synthesis phase stops
    after announcing a plan but never writes the report. Jesse observed
    responses like "Let me compose the report" with ~30 chars where a
    real DR report is 2000+ chars.

    YAML:
      - action: regenerate_if_short
        response_var: response
        min_chars: 500
        retry_element: rewrite_thread
        stop_validation: send_success
        complete_validation: response_complete
        extract_element: response_landmark
        max_retries: 3
        required_stop_absent_cycles: 3
        poll_interval: 2.0
        regen_timeout: 3600
    """
    for k in ('response_var', 'min_chars', 'retry_element',
              'stop_validation', 'complete_validation', 'extract_element'):
        if step.get(k) in (None, ''):
            return _fail('regenerate_if_short', f'step.{k} missing')
    response_var = step['response_var']
    min_chars = step['min_chars']
    retry_element = step['retry_element']
    stop_validation = step['stop_validation']
    complete_validation = step['complete_validation']
    extract_element = step['extract_element']
    max_retries = step.get('max_retries', 3)
    required_absent_cycles = step.get('required_stop_absent_cycles', 3)
    poll = step.get('poll_interval', 2.0)
    regen_timeout = step.get('regen_timeout', 3600)
    # click_strategy: if absent from step, pass None to rt.click so it
    # uses the platform's top-level click_strategy default. Hardcoding
    # 'atspi_only' here was a rule-2 violation (Perplexity audit RV-2).
    click_strategy = step.get('click_strategy')

    rt = ctx['runtime']
    attempts = 0
    for attempt in range(1, max_retries + 1):
        current = ctx.get('vars', {}).get(response_var, '') or ''
        if len(current) >= min_chars:
            return _ok({'event': 'step_ok', 'action': 'regenerate_if_short',
                        'attempts': attempts, 'length': len(current),
                        'note': 'no retry needed'})

        # Click retry button (Rewrite Thread / Regenerate / etc).
        from consultation_v2.snapshot import build_snapshot
        _, _, snap = build_snapshot(ctx['platform'])
        el = snap.first(retry_element)
        if not el:
            return _fail('regenerate_if_short',
                         f'retry element {retry_element!r} not in snapshot '
                         f'(attempt {attempt}, response was {len(current)} chars)')
        if not rt.click(el, strategy=click_strategy):
            return _fail('regenerate_if_short',
                         f'click on {retry_element!r} returned False (attempt {attempt})')
        attempts = attempt
        time.sleep(poll)

        # Wait for generation to restart (stop_button appears).
        start_res = wait_for_indicator(ctx, {
            'validation': stop_validation,
            'timeout': 30, 'poll_interval': poll,
        })
        if not start_res['ok']:
            return _fail('regenerate_if_short',
                         f'generation did not restart after retry {attempt}: '
                         f'{start_res["error"]}')

        # Wait for generation to finish (stop_button absent N cycles).
        done_res = wait_for_indicator_absent(ctx, {
            'validation': stop_validation,
            'required_absent_cycles': required_absent_cycles,
            'poll_interval': poll,
            'timeout': regen_timeout,
        })
        if not done_res['ok']:
            return _fail('regenerate_if_short',
                         f'regeneration timed out on attempt {attempt}: '
                         f'{done_res["error"]}')

        # Wait (briefly) for the completion indicator (copy_button). A
        # timeout here is acceptable — a regeneration that left the copy
        # button absent still produced text in the response landmark,
        # and the length check below decides. But a HARD error (inspect
        # failure, bus crash) must propagate — fail-closed discipline
        # requires distinguishing timeout from real failure. Claude/Gemini
        # /ChatGPT audits all flagged this silent-swallow as a rule
        # violation.
        complete_res = wait_for_indicator(ctx, {
            'validation': complete_validation,
            'timeout': 30, 'poll_interval': poll,
        })
        if not complete_res['ok'] and complete_res.get('kind') != 'timeout':
            return _fail('regenerate_if_short',
                         f'completion check errored on attempt {attempt}: '
                         f'{complete_res["error"]}')

        # Re-read the response into the same var.
        read_res = read_element_text_primitive(ctx, {
            'element': extract_element,
            'into': response_var,
            'min_chars': 1,
        })
        if not read_res['ok']:
            return _fail('regenerate_if_short',
                         f'post-retry read failed on attempt {attempt}: '
                         f'{read_res["error"]}')

    # Exhausted retries — check final length.
    final = ctx.get('vars', {}).get(response_var, '') or ''
    if len(final) < min_chars:
        return _fail('regenerate_if_short',
                     f'response still {len(final)} chars after {max_retries} retries '
                     f'(min {min_chars})')
    return _ok({'event': 'step_ok', 'action': 'regenerate_if_short',
                'attempts': attempts, 'length': len(final)})


@primitive('mode_select_step')
def mode_select_step(ctx: dict, step: dict) -> dict:
    """Execute one mode/tool selection step: (trigger → target-in-menu →
    [verify] → escape). Encapsulates the mode-setup logic that used to
    live in consult.py's inline _run_sequence. YAML keys mirror the
    existing selection.sequences step shape so no YAML rewrite is needed.

    Fields:
      trigger: element_map key of the menu trigger (optional — some
        composite sequences invoke this primitive after a prior step
        already opened the right scope).
      target: element_map key of the item to check.
      snapshot: 'menu' or 'document' — the scope to inspect when
        looking up the target (required if target is set).
      click_strategy: forwarded to runtime.click for the target click.
      skip_if_checked: inspect scope first; if target already has its
        selected_state, skip the click and mark verified. Avoids
        toggling off a mode/tool the user wanted ON.
      verified_by_checked_state: after clicking the target, verify
        selected_state in scope. If the scope snapshot is empty
        (e.g. menu auto-closed), fall back to document-scope
        indicators declared under validation.<step.validation>. Fail
        closed if neither proves selection.
      close_with_escape: press Escape after the step.
      validation: name of the validation.<key> used for the
        document-indicator fallback (and for post-check verification in
        consult.py).

    Note: no `reverify_via_reopen`. If a platform's UI auto-closes its
    menu on select, declare a document-scope indicator tile (e.g.
    Gemini's "Deselect Deep think" push button) and rely on the
    indicator fallback. Re-opening the menu to prove selection is a
    retry chain — rule-5 forbidden.
    """
    from consultation_v2.consult import _element_has_checked_state
    rt = ctx['runtime']
    cfg = ctx['cfg']
    timing = cfg.get('workflow', {}).get('timing', {})
    for t in ('after_trigger_click', 'after_target_click', 'after_escape'):
        if t not in timing:
            return _fail('mode_select_step',
                         f'workflow.timing.{t} missing from YAML')

    trigger = step.get('trigger')
    target = step.get('target')
    scope = step.get('snapshot')
    strategy = step.get('click_strategy')
    validation_key = step.get('validation')

    if trigger:
        from consultation_v2.snapshot import build_snapshot
        _, _, snap = build_snapshot(ctx['platform'])
        el = snap.first(trigger)
        if not el:
            return _fail('mode_select_step',
                         f'trigger {trigger!r} not in document snapshot')
        # Trigger click uses the platform's default strategy (YAML
        # top-level click_strategy), NOT the step's click_strategy.
        # The step's strategy applies to the target click only — e.g.
        # ChatGPT's pro_extended sequence has click_strategy: atspi_only
        # for the menu item (model_pro), but the model_selector trigger
        # needs coordinate_only (platform default) to actually open the
        # dropdown. This matches the pre-refactor behavior of calling
        # act.py without --strategy for the trigger click.
        if not rt.click(el):
            return _fail('mode_select_step',
                         f'trigger click {trigger!r} returned False')
        time.sleep(timing['after_trigger_click'])

    if target:
        if not scope:
            return _fail('mode_select_step',
                         f'target {target!r} set but step.snapshot (scope) missing')

        skipped = False
        if step.get('skip_if_checked'):
            menu_snap, err = _must_inspect(ctx, 'mode_select_step', scope=scope)
            if err:
                return err
            if _element_has_checked_state(menu_snap, cfg, target, ctx['platform']):
                skipped = True

        if not skipped:
            from consultation_v2.snapshot import build_menu_snapshot, build_snapshot
            # Build the in-process snapshot to get an ElementRef with
            # x/y for the click. Claude R2 audit caught a redundant
            # _must_inspect here that was effectively a bus canary —
            # removed; if the bus is dead, snap.first(target) returns
            # None and we fail_closed below with a clear target-absent
            # error (propagates to the caller via the runner).
            if scope == 'menu':
                _, _, snap = build_menu_snapshot(ctx['platform'])
            else:
                _, _, snap = build_snapshot(ctx['platform'])
            el = snap.first(target)
            if not el:
                return _fail('mode_select_step',
                             f'target {target!r} not in {scope} snapshot')
            if not rt.click(el, strategy=strategy):
                return _fail('mode_select_step',
                             f'target click {target!r} returned False')
            time.sleep(timing['after_target_click'])

        # Post-click verification is OPT-IN via verified_by_checked_state.
        # When we skipped (already checked), verification is already proven;
        # no further work needed. When we clicked and the YAML asks for
        # verification, try checked-state in scope first, then fall back
        # to document-scope indicators under validation.<key>. The YAML
        # names the validation key; the indicator tiles ("Deselect Deep
        # think", "Extended Pro", etc.) are the canonical document-scope
        # source of truth when the menu auto-closed on selection.
        if not skipped and step.get('verified_by_checked_state'):
            verify_snap, err = _must_inspect(ctx, 'mode_select_step', scope=scope)
            if err:
                return err
            verified = _element_has_checked_state(
                verify_snap, cfg, target, ctx['platform'])

            if not verified:
                # Document-scope indicator fallback. This isn't a retry in
                # the rule-5 sense — the YAML declares the indicator as
                # the authoritative post-click signal (e.g. Gemini's
                # "Deselect Deep think" tile appears only when Deep think
                # is the active tool).
                if validation_key:
                    val_cfg = cfg.get('validation', {}).get(validation_key, {})
                    indicators = val_cfg.get('indicators', [])
                    if indicators:
                        from consultation_v2.consult import _all_elements
                        doc_snap, err = _must_inspect(ctx, 'mode_select_step')
                        if err:
                            return err
                        doc_elements = _all_elements(doc_snap)
                        for ind in indicators:
                            if any(e.get('name') == ind.get('name') and
                                   e.get('role') == ind.get('role') for e in doc_elements):
                                verified = True
                                break

            if not verified:
                return _fail('mode_select_step',
                             f'target {target!r} not in checked state after click '
                             f'(validation={validation_key!r})')

    if step.get('close_with_escape'):
        if not rt.press('Escape'):
            return _fail('mode_select_step', 'Escape keypress returned False')
        time.sleep(timing['after_escape'])

    return _ok({'event': 'step_ok', 'action': 'mode_select_step',
                'trigger': trigger, 'target': target,
                'scope': scope, 'validation': validation_key})


@primitive('require_url_changed')
def require_url_changed(ctx: dict, step: dict) -> dict:
    """Poll until the current URL differs from the baseline variable, or
    fail on timeout. Platforms that redirect to a session URL after send
    (ChatGPT /c/<id>, Perplexity /search/<...>) don't redirect instantly
    — the stop_button appears before the URL updates — so this primitive
    polls for up to `timeout` seconds.

    YAML: `- action: require_url_changed
            baseline: pre_send_url
            timeout: 30
            poll_interval: 1.0`
    """
    baseline_var = step.get('baseline')
    if not baseline_var:
        return _fail('require_url_changed', 'step.baseline var name missing')
    baseline = ctx.get('vars', {}).get(baseline_var, '')
    if not baseline:
        return _fail('require_url_changed',
                     f'baseline var {baseline_var!r} is empty; nothing to compare')
    timeout = step.get('timeout', 30)
    poll = step.get('poll_interval', 1.0)
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap, err = _must_inspect(ctx, 'require_url_changed')
        if err:
            return err
        current = snap.get('url', '') or ''
        if current and current != baseline:
            return _ok({'event': 'step_ok', 'action': 'require_url_changed',
                        'from': baseline[:60], 'to': current[:60]})
        time.sleep(poll)
    return _fail('require_url_changed',
                 f'URL unchanged from baseline {baseline[:60]!r} after {timeout}s')


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _ensure_platform_env(platform: str) -> None:
    """Populate os.environ with DISPLAY and DBUS_SESSION_BUS_ADDRESS for
    the platform so in-process primitives (runtime.click / runtime.paste /
    xdotool subprocess) can reach the right X display. Does nothing if
    env is already set and matches (e.g. consult.py was launched with
    platform env already). Called at the start of every run_sequence.
    """
    import os as _os
    from pathlib import Path as _Path
    try:
        from core.platforms import get_platform_display
    except Exception:
        return
    display = get_platform_display(platform)
    if not display:
        return
    _os.environ['DISPLAY'] = display
    _os.environ.setdefault('PLATFORM_DISPLAYS', f'{platform}:{display.lstrip(":")}')
    session_bus_file = f'/tmp/dbus_session_bus_{display}'
    try:
        session_bus = _Path(session_bus_file).read_text().strip()
    except FileNotFoundError:
        return
    if session_bus:
        _os.environ['DBUS_SESSION_BUS_ADDRESS'] = session_bus
    # a11y bus is legitimately empty on this system; only set when non-empty
    a11y_file = f'/tmp/a11y_bus_{display}'
    try:
        bus = _Path(a11y_file).read_text().strip()
    except FileNotFoundError:
        bus = ''
    if bus:
        _os.environ['AT_SPI_BUS_ADDRESS'] = bus


def run_sequence(ctx: dict, steps: List[dict], step_name: str = 'sequence') -> dict:
    """Execute a list of primitive steps. Returns the last primitive's result.
    Prints each step's event as JSON to stdout. Fails closed on the first
    non-ok result unless that step declared `optional: true`.

    Every step dict must have an `action` key naming the primitive.
    Unknown actions are hard errors (they indicate a YAML-driver mismatch).
    """
    _ensure_platform_env(ctx.get('platform', ''))
    result = _ok({'event': 'step_ok', 'action': 'sequence_start', 'name': step_name,
                  'steps': len(steps)})
    print(json.dumps(result['event']))
    for i, step in enumerate(steps):
        action = step.get('action')
        if not action:
            return _fail(step_name, f'step {i} missing `action` key: {step!r}')
        prim = get_primitive(action)
        if not prim:
            return _fail(step_name, f'step {i} unknown action {action!r}')
        result = prim(ctx, step)
        if result['event']:
            ev = dict(result['event'])
            ev['step_index'] = i
            print(json.dumps(ev))
        if not result['ok']:
            # `optional: true` skips ONLY expected-non-presence failures:
            #   - absent_optional: click target not in snapshot (YAML knows
            #     this element may not exist in every UI state, e.g.
            #     ChatGPT Show-in-text-field or Gemini Start-research)
            #   - timeout: wait_for_indicator / wait_for_indicator_absent
            #     deadline hit (the condition never triggered, which for
            #     DR two-phase flows means "non-DR prompt, skip").
            # Hard failures (click-failed, inspect-errored, text-landed
            # mismatch, URL-didn't-change) are never skipped — optional
            # does not mean "ignore any failure."
            if step.get('optional') and result.get('kind') in ('absent_optional', 'timeout'):
                print(json.dumps({'event': 'step_skip', 'action': action,
                                  'step_index': i, 'error': result['error'],
                                  'reason': result['kind']}))
                result = _ok(None)
                continue
            return result
    return _ok({'event': 'step_ok', 'action': 'sequence_complete', 'name': step_name})
