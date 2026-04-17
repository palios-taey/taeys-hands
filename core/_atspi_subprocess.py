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


def read_element_text(platform, scan_root, name, role):
    """Read text content of an element by (name, role) via AT-SPI Text interface.

    Returns {'text': <str>, 'char_count': <int>} on success, or {'error': ...}.

    Used to verify prompt paste landed in the composer. The Text interface
    returns rendered text including the pasted content for editable entries
    and contenteditable sections. If the element does not implement Text,
    falls back to attempting Value (used by some sliders/controls; harmless here).
    """
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

    match = None

    def _find(node, depth):
        nonlocal match
        if match is not None or depth > 50:
            return
        try:
            n_name = (node.get_name() or '').strip()
            n_role = node.get_role_name() or ''
            if n_name == name and n_role == role:
                match = node
                return
            for i in range(node.get_child_count()):
                child = node.get_child_at_index(i)
                if child:
                    _find(child, depth + 1)
        except Exception:
            pass

    _find(scope, 0)
    if match is None:
        return {'error': f'Element (name={name!r}, role={role!r}) not found'}

    try:
        text_iface = match.get_text_iface()
    except Exception:
        text_iface = None
    if text_iface is not None:
        try:
            n = text_iface.get_character_count()
            text = text_iface.get_text(0, n) if n > 0 else ''
            return {'text': text, 'char_count': n}
        except Exception as e:
            return {'error': f'Text interface error: {e}'}

    # Some platforms (ProseMirror div) don't expose Text directly on the
    # section; recurse children looking for the first descendant with Text.
    def _walk(node, depth=0):
        if depth > 6:
            return None
        try:
            ti = node.get_text_iface()
        except Exception:
            ti = None
        if ti is not None:
            try:
                n = ti.get_character_count()
                txt = ti.get_text(0, n) if n > 0 else ''
                if txt or n > 0:
                    return {'text': txt, 'char_count': n}
            except Exception:
                pass
        try:
            for i in range(node.get_child_count()):
                ch = node.get_child_at_index(i)
                if ch:
                    res = _walk(ch, depth + 1)
                    if res:
                        return res
        except Exception:
            pass
        return None

    res = _walk(match)
    if res:
        return res
    return {'error': 'Element has no Text interface and no text-bearing children'}


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
        # Read the AT-SPI Text / Value interface of an element, used to prove
        # pasted prompt text actually landed in the composer rather than going
        # to some other focused element. name may be '' (Perplexity/Grok input
        # has no accessible name); role + position selects the right instance.
        platform = sys.argv[2]
        scan_root = sys.argv[3]
        name = sys.argv[4]
        role = sys.argv[5]
        print(json.dumps(read_element_text(platform, scan_root, name, role)))
    else:
        print(json.dumps({'error': f'Unknown command: {cmd}'}))
