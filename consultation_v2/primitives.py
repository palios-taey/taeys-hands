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


def _fail(step_name: str, msg: str) -> dict:
    return {'ok': False, 'event': None, 'error': f'{step_name}: {msg}'}


def _ok(event: Optional[dict] = None) -> dict:
    return {'ok': True, 'event': event, 'error': None}


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

    YAML: `- action: click
            element: show_full_report_button
            scope: document     # document|menu, default document
            click_strategy: atspi_only
            delay: 3.0
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
    el = snap.first(element_key)
    if not el:
        if step.get('optional'):
            return _ok({'event': 'step_ok', 'action': 'click', 'element': element_key,
                        'skipped': True, 'reason': 'absent and optional'})
        return _fail('click', f'element {element_key!r} not in snapshot (scope={scope})')
    strategy = step.get('click_strategy')
    rt = ctx['runtime']
    ok = rt.click(el, strategy=strategy)
    if not ok:
        return _fail('click', f'click on {element_key!r} returned False')
    delay = step.get('delay', 0)
    if delay:
        time.sleep(delay)
    return _ok({'event': 'step_ok', 'action': 'click', 'element': element_key,
                'x': el.x, 'y': el.y})


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


@primitive('wait_for_indicator')
def wait_for_indicator(ctx: dict, step: dict) -> dict:
    """Poll until every indicator under validation.<key>.indicators is
    present in the document tree, or fail on timeout.

    YAML: `- action: wait_for_indicator
            validation: send_success
            timeout: 15
            poll_interval: 2.0`
    """
    from consultation_v2.consult import inspect_platform, _all_elements
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
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = inspect_platform(ctx['platform'])
        elements = _all_elements(snap)
        missing = []
        for ind in indicators:
            found = any(e.get('name') == ind.get('name') and
                        e.get('role') == ind.get('role') for e in elements)
            if not found:
                missing.append(ind)
        if not missing:
            return _ok({'event': 'step_ok', 'action': 'wait_for_indicator',
                        'validation': val_key, 'elapsed': round(time.time() - (deadline - timeout), 1)})
        time.sleep(poll)
    return _fail('wait_for_indicator',
                 f'validation.{val_key} indicators not present within {timeout}s: {missing}')


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
    from consultation_v2.consult import inspect_platform, _all_elements
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
        snap = inspect_platform(ctx['platform'])
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
                 f'validation.{val_key} indicators still present at timeout {timeout}s')


@primitive('capture_url')
def capture_url(ctx: dict, step: dict) -> dict:
    """Capture the current URL into a named variable."""
    from consultation_v2.consult import inspect_platform
    into = step.get('into')
    if not into:
        return _fail('capture_url', 'step.into missing')
    snap = inspect_platform(ctx['platform'])
    ctx.setdefault('vars', {})[into] = snap.get('url', '') or ''
    return _ok({'event': 'step_ok', 'action': 'capture_url',
                'into': into, 'url': ctx['vars'][into][:100]})


@primitive('require_url_changed')
def require_url_changed(ctx: dict, step: dict) -> dict:
    """Fail if current URL equals the baseline URL captured earlier."""
    from consultation_v2.consult import inspect_platform
    baseline_var = step.get('baseline')
    if not baseline_var:
        return _fail('require_url_changed', 'step.baseline var name missing')
    baseline = ctx.get('vars', {}).get(baseline_var, '')
    snap = inspect_platform(ctx['platform'])
    current = snap.get('url', '') or ''
    if not baseline:
        return _fail('require_url_changed',
                     f'baseline var {baseline_var!r} is empty; nothing to compare')
    if current == baseline:
        return _fail('require_url_changed',
                     f'URL unchanged from baseline {baseline[:60]!r}')
    return _ok({'event': 'step_ok', 'action': 'require_url_changed',
                'from': baseline[:60], 'to': current[:60]})


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_sequence(ctx: dict, steps: List[dict], step_name: str = 'sequence') -> dict:
    """Execute a list of primitive steps. Returns the last primitive's result.
    Prints each step's event as JSON to stdout. Fails closed on the first
    non-ok result unless that step declared `optional: true`.

    Every step dict must have an `action` key naming the primitive.
    Unknown actions are hard errors (they indicate a YAML-driver mismatch).
    """
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
            if step.get('optional'):
                print(json.dumps({'event': 'step_skip', 'action': action,
                                  'step_index': i, 'error': result['error'],
                                  'reason': 'optional'}))
                result = _ok(None)
                continue
            return result
    return _ok({'event': 'step_ok', 'action': 'sequence_complete', 'name': step_name})
