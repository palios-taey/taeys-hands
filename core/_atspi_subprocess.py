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
    url_lower = url.lower()
    for p, pat in _EXTRA_URL_PATTERNS.items():
        if pat in url_lower:
            return p
    for p, dom in URL_PATTERNS.items():
        if dom in url_lower:
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
        if app and 'firefox' in (app.get_name() or '').lower():
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

    # Fallback: return first Firefox
    try:
        result['pid'] = all_ff[0].get_process_id()
    except Exception:
        pass
    return result


def scan_elements(platform):
    """Full element scan for platform. Returns list of element dicts."""
    desktop = Atspi.get_desktop(0)
    all_ff = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app and 'firefox' in (app.get_name() or '').lower():
            all_ff.append(app)

    if not all_ff:
        return {'error': 'No Firefox found', 'elements': []}

    # Find document
    doc = None
    for ff in all_ff:
        for j in range(ff.get_child_count()):
            frame = ff.get_child_at_index(j)
            if frame:
                doc = _find_document(frame, platform)
                if doc:
                    break
        if doc:
            break

    if not doc:
        return {'error': f'No {platform} document', 'elements': []}

    url = _get_doc_url(doc)

    # Get chrome Y
    try:
        ext = doc.get_extents(0)
        chrome_y = ext.y if ext else 120
    except Exception:
        chrome_y = 120

    # Scan tree
    elements = []
    _scan(doc, elements, 0)
    elements = [e for e in elements if e.get('y', 0) > chrome_y]

    # Copy buttons
    copy_count = sum(1 for e in elements
                     if 'copy' in e.get('name', '').lower()
                     and e.get('role') in ('push button',))

    return {
        'url': url,
        'elements': elements,
        'copy_button_count': copy_count,
        'total': len(elements),
    }


def _scan(node, elements, depth):
    if depth > 30:
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
    platform = sys.argv[2] if len(sys.argv) > 2 else 'chatgpt'

    if cmd == 'find_firefox':
        print(json.dumps(find_firefox_info(platform)))
    elif cmd == 'scan':
        print(json.dumps(scan_elements(platform)))
    else:
        print(json.dumps({'error': f'Unknown command: {cmd}'}))
