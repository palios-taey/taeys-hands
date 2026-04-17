#!/usr/bin/env python3
"""Subprocess AT-SPI scanner for multi-display MCP server.

Spawned with correct DISPLAY + AT_SPI_BUS_ADDRESS to scan a single
platform's AT-SPI tree. Returns JSON results on stdout.

Usage (called by core/atspi.py, not directly):
    DISPLAY=:2 AT_SPI_BUS_ADDRESS=... python3 core/_atspi_subprocess.py scan <platform>
    DISPLAY=:2 AT_SPI_BUS_ADDRESS=... python3 core/_atspi_subprocess.py find_firefox <platform>
"""
import json
import os
import sys

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from core.platforms import URL_PATTERNS, _EXTRA_URL_PATTERNS


def _get_doc_url(doc):
    try:
        iface = doc.get_document_iface()
        if iface:
            return iface.get_document_attribute_value('DocURL') or ''
    except Exception:
        pass
    return ''


def _detect_platform(url):
    for p, pat in _EXTRA_URL_PATTERNS.items():
        if pat in url:
            return p
    for p, dom in URL_PATTERNS.items():
        if dom in url:
            return p
    return None


def _find_document(node, platform, depth=0):
    if depth > 10:
        return None
    try:
        if node.get_role_name() == 'document web':
            url = _get_doc_url(node)
            if _detect_platform(url) == platform:
                return node
        for i in range(node.get_child_count()):
            child = node.get_child_at_index(i)
            if child:
                found = _find_document(child, platform, depth + 1)
                if found:
                    return found
    except Exception:
        pass
    return None


def find_firefox_info(platform):
    """Find Firefox for platform, return {pid, has_document, url}."""
    desktop = Atspi.get_desktop(0)
    result = {'pid': None, 'has_document': False, 'url': None, 'app_count': 0}

    all_ff = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app and app.get_name() in ('Firefox', 'Mozilla Firefox', 'Firefox Web Browser'):
            all_ff.append(app)

    result['app_count'] = len(all_ff)
    if not all_ff:
        return result

    # Find the one with our platform's document
    for ff in all_ff:
        try:
            pid = ff.get_process_id()
        except Exception:
            pid = None
        for j in range(ff.get_child_count()):
            frame = ff.get_child_at_index(j)
            if frame:
                doc = _find_document(frame, platform)
                if doc:
                    result['pid'] = pid
                    result['has_document'] = True
                    result['url'] = _get_doc_url(doc)
                    return result

    return result


def scan_elements(platform, scan_root='document'):
    desktop = Atspi.get_desktop(0)
    try:
        desktop.clear_cache_single()
    except Exception:
        pass
    all_ff = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app and app.get_name() in ('Firefox', 'Mozilla Firefox', 'Firefox Web Browser'):
            try:
                app.clear_cache_single()
            except Exception:
                pass
            all_ff.append(app)

    if not all_ff:
        return {'error': 'No Firefox found', 'elements': []}

    doc = None
    target_app = None
    for ff in all_ff:
        for j in range(ff.get_child_count()):
            frame = ff.get_child_at_index(j)
            if frame:
                doc = _find_document(frame, platform)
                if doc:
                    target_app = ff
                    break
        if doc:
            break

    if not doc:
        return {'error': f'No {platform} document', 'elements': []}

    scope = target_app if scan_root == 'app' else doc
    if scope:
        try:
            scope.clear_cache_single()
        except Exception:
            pass

    url = _get_doc_url(doc)
    elements = []
    _scan(scope, elements, 0)

    return {
        'url': url,
        'elements': elements,
        'total': len(elements),
    }


def perform_action(platform, scan_root, name, role, x, y):
    """Find element by exact name+role and perform AT-SPI action (click via accessibility API)."""
    desktop = Atspi.get_desktop(0)
    try:
        desktop.clear_cache_single()
    except Exception:
        pass
    all_ff = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app and app.get_name() in ('Firefox', 'Mozilla Firefox', 'Firefox Web Browser'):
            try:
                app.clear_cache_single()
            except Exception:
                pass
            all_ff.append(app)

    doc = None
    target_app = None
    for ff in all_ff:
        for j in range(ff.get_child_count()):
            frame = ff.get_child_at_index(j)
            if frame:
                doc = _find_document(frame, platform)
                if doc:
                    target_app = ff
                    break
        if doc:
            break

    if not doc:
        return {'success': False, 'error': f'No {platform} document'}

    scope = target_app if scan_root == 'app' else doc
    if scope:
        try:
            scope.clear_cache_single()
        except Exception:
            pass

    best_node = None
    best_dist = float('inf')

    def _find(node, depth):
        nonlocal best_node, best_dist
        if depth > 50:
            return
        try:
            n_name = (node.get_name() or '').strip()
            n_role = node.get_role_name() or ''
            if n_name[:200] == name and n_role == role:
                try:
                    ext = node.get_extents(0)
                    cx = ext.x + ext.width // 2
                    cy = ext.y + ext.height // 2
                    if x is not None and y is not None:
                        dist = (cx - x)**2 + (cy - y)**2
                        if dist < best_dist:
                            best_dist = dist
                            best_node = node
                    else:
                        best_node = node
                        best_dist = 0
                except Exception:
                    if best_node is None:
                        best_node = node
            for i in range(node.get_child_count()):
                child = node.get_child_at_index(i)
                if child:
                    _find(child, depth + 1)
        except Exception:
            pass

    _find(scope, 0)
    if best_node:
        try:
            action = best_node.get_action_iface()
            if action and action.get_n_actions() > 0:
                action.do_action(0)
                return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        return {'success': False, 'error': 'No action interface'}
    return {'success': False, 'error': 'Element not found'}


def read_element_text(platform, scan_root, name, role, required_states=None):
    """Read text content of an element by (name, role, states) via AT-SPI Text.

    Returns {'text': <str>, 'char_count': <int>} on success, or {'error': ...}.

    required_states is a list of AT-SPI state names (e.g., ['editable',
    'multi-line']) that the matched element MUST have. Required for inputs
    with name="" (Grok section, Perplexity entry) where many unrelated
    elements share the role — the state filter is what makes the match
    unambiguous. If the YAML element_map specifies states_include, they
    MUST be passed here; failing to do so falls back to first-match-wins
    which silently picks the wrong element.
    """
    required_states = required_states or []
    desktop = Atspi.get_desktop(0)
    try:
        desktop.clear_cache_single()
    except Exception:
        pass
    all_ff = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app and app.get_name() in ('Firefox', 'Mozilla Firefox', 'Firefox Web Browser'):
            try:
                app.clear_cache_single()
            except Exception:
                pass
            all_ff.append(app)

    doc = None
    target_app = None
    for ff in all_ff:
        for j in range(ff.get_child_count()):
            frame = ff.get_child_at_index(j)
            if frame:
                doc = _find_document(frame, platform)
                if doc:
                    target_app = ff
                    break
        if doc:
            break
    if not doc:
        return {'error': f'No {platform} document'}

    scope = target_app if scan_root == 'app' else doc
    try:
        scope.clear_cache_single()
    except Exception:
        pass

    def _node_states(node):
        try:
            ss = node.get_state_set()
        except Exception:
            return set()
        found = set()
        for sn in ['showing', 'focused', 'editable', 'focusable',
                   'enabled', 'checked', 'pressed', 'expanded',
                   'selected', 'multi-line']:
            se = getattr(Atspi.StateType, sn.upper().replace('-', '_'), None)
            if se and ss.contains(se):
                found.add(sn)
        return found

    matches = []

    def _find(node, depth):
        if depth > 50:
            return
        try:
            n_name = (node.get_name() or '').strip()
            n_role = node.get_role_name() or ''
            # Match the scan's 200-char truncation: YAML names come from
            # scan output which truncates at 200 chars, so compare up to
            # the same bound. perform_action uses the same pattern.
            if n_name[:200] == name and n_role == role:
                if required_states:
                    n_states = _node_states(node)
                    if all(s in n_states for s in required_states):
                        matches.append(node)
                else:
                    matches.append(node)
            for i in range(node.get_child_count()):
                child = node.get_child_at_index(i)
                if child:
                    _find(child, depth + 1)
        except Exception:
            pass

    _find(scope, 0)
    if not matches:
        return {'error': f'Element (name={name!r}, role={role!r}, '
                         f'states_include={required_states!r}) not found'}
    if len(matches) > 1:
        return {'error': f'Element (name={name!r}, role={role!r}, '
                         f'states_include={required_states!r}) matched {len(matches)} '
                         f'candidates — ambiguous, cannot safely verify paste'}
    match = matches[0]

    # Proper AT-SPI Text API: call Atspi.Text module-level functions on the
    # Accessible, NOT the deprecated Accessible.get_text() (which takes only
    # self). The module-level function takes (accessible, start, end).
    def _read_text(node):
        try:
            n = Atspi.Text.get_character_count(node)
        except Exception:
            return None
        if n is None:
            return None
        try:
            txt = Atspi.Text.get_text(node, 0, n) if n > 0 else ''
        except Exception:
            txt = ''
        return (txt, n)

    # Collect text from the element AND all descendants. ProseMirror-based
    # composers (ChatGPT, Claude) expose U+FFFC (object replacement char, '￼')
    # as the input's own text because content lives in child paragraph /
    # section nodes. Native `entry` elements (Gemini) expose their text
    # directly. Walk the subtree and concatenate. The descendant text is
    # what actually matches the pasted content.
    PLACEHOLDER = '\ufffc'
    collected = []
    total_chars = 0

    def _walk(node, depth=0):
        nonlocal total_chars
        if depth > 8:
            return
        result = _read_text(node)
        if result is not None:
            txt, n = result
            # Strip the U+FFFC placeholder that ProseMirror uses at the
            # composer root — it's not real content.
            real = txt.replace(PLACEHOLDER, '') if txt else ''
            if real:
                collected.append(real)
                total_chars += len(real)
        try:
            for i in range(node.get_child_count()):
                ch = node.get_child_at_index(i)
                if ch:
                    _walk(ch, depth + 1)
        except Exception:
            pass

    _walk(match)
    if total_chars == 0:
        return {'text': '', 'char_count': 0}
    full = '\n'.join(collected)
    return {'text': full, 'char_count': total_chars}


def _scan(node, elements, depth):
    if depth > 100:
        return
    try:
        name = (node.get_name() or '').strip()
        role = node.get_role_name() or ''

        interactive = {
            'push button', 'toggle button', 'check box', 'radio button',
            'combo box', 'entry', 'text', 'link', 'menu item',
            'editable', 'document web', 'list item', 'check menu item',
            'radio menu item', 'section',
        }

        if role in interactive or (name and role in ('label', 'heading', 'paragraph', 'panel')):
            try:
                ext = node.get_extents(0)
                x, y, w, h = ext.x, ext.y, ext.width, ext.height
                if w > 0 and h > 0:
                    states = []
                    try:
                        ss = node.get_state_set()
                        for sn in ['showing', 'focused', 'editable', 'focusable',
                                   'enabled', 'checked', 'pressed', 'expanded',
                                   'selected', 'multi-line']:
                            se = getattr(Atspi.StateType, sn.upper().replace('-', '_'), None)
                            if se and ss.contains(se):
                                states.append(sn)
                    except Exception:
                        pass
                    elements.append({
                        'name': name[:200],
                        'role': role,
                        'x': x + w // 2,
                        'y': y + h // 2,
                        'states': states,
                    })
            except Exception:
                pass

        for i in range(node.get_child_count()):
            child = node.get_child_at_index(i)
            if child:
                _scan(child, elements, depth + 1)
    except Exception:
        pass


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'find_firefox'

    if cmd == 'find_firefox':
        if len(sys.argv) < 3:
            print(json.dumps({'error': 'platform argument required'}))
            sys.exit(1)
        platform = sys.argv[2]
        print(json.dumps(find_firefox_info(platform)))
    elif cmd == 'scan':
        if len(sys.argv) < 3:
            print(json.dumps({'error': 'platform argument required'}))
            sys.exit(1)
        platform = sys.argv[2]
        scan_root = sys.argv[3] if len(sys.argv) > 3 else 'document'
        print(json.dumps(scan_elements(platform, scan_root)))
    elif cmd == 'click':
        platform = sys.argv[2]
        scan_root = sys.argv[3]
        name = sys.argv[4]
        role = sys.argv[5]
        x_str = sys.argv[6]
        y_str = sys.argv[7]
        x = float(x_str) if x_str != 'None' else None
        y = float(y_str) if y_str != 'None' else None
        print(json.dumps(perform_action(platform, scan_root, name, role, x, y)))
    elif cmd == 'read_text':
        # Read the AT-SPI Text interface of an element, used to prove pasted
        # prompt text actually landed in the composer rather than going to
        # some other focused element. name may be '' (Perplexity/Grok input
        # has no accessible name); the states argument (comma-separated)
        # MUST be passed if the YAML element_map specifies states_include,
        # otherwise first-match-wins picks the wrong unnamed element.
        platform = sys.argv[2]
        scan_root = sys.argv[3]
        name = sys.argv[4]
        role = sys.argv[5]
        states_arg = sys.argv[6] if len(sys.argv) > 6 else ''
        required_states = [s for s in states_arg.split(',') if s]
        print(json.dumps(read_element_text(platform, scan_root, name, role, required_states)))
    else:
        print(json.dumps({'error': f'Unknown command: {cmd}'}))
