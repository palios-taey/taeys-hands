#!/usr/bin/env python3
"""Dump complete AT-SPI tree for a display. Raw data for YAML rebuilds.

Usage:
    python3 scan_tree.py --display :3 --label claude_home
    python3 scan_tree.py --display :3 --label claude_dropdown --scope menu

Outputs to yaml-rebuild/scans/<label>.txt
"""

import argparse
import os
import sys

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi


IMPORTANT_STATES = [
    Atspi.StateType.SHOWING,
    Atspi.StateType.VISIBLE,
    Atspi.StateType.FOCUSED,
    Atspi.StateType.CHECKED,
    Atspi.StateType.SELECTED,
    Atspi.StateType.ENABLED,
    Atspi.StateType.EDITABLE,
    Atspi.StateType.FOCUSABLE,
    Atspi.StateType.EXPANDED,
    Atspi.StateType.MULTI_LINE,
]

STATE_NAMES = {
    Atspi.StateType.SHOWING: 'showing',
    Atspi.StateType.VISIBLE: 'visible',
    Atspi.StateType.FOCUSED: 'focused',
    Atspi.StateType.CHECKED: 'checked',
    Atspi.StateType.SELECTED: 'selected',
    Atspi.StateType.ENABLED: 'enabled',
    Atspi.StateType.EDITABLE: 'editable',
    Atspi.StateType.FOCUSABLE: 'focusable',
    Atspi.StateType.EXPANDED: 'expanded',
    Atspi.StateType.MULTI_LINE: 'multi-line',
}

# Roles worth recording (skip internal containers with no semantic meaning)
SKIP_ROLES = {'redundant object', 'unknown', 'invalid', 'filler', 'table cell'}


def get_states(obj):
    try:
        ss = obj.get_state_set()
        return [STATE_NAMES[s] for s in IMPORTANT_STATES if ss.contains(s)]
    except Exception:
        return []


def get_extents(obj):
    try:
        comp = obj.get_component_iface()
        if comp:
            ext = comp.get_extents(Atspi.CoordType.SCREEN)
            return ext.x, ext.y, ext.width, ext.height
    except Exception:
        pass
    return None, None, None, None


def get_description(obj):
    try:
        desc = obj.get_description()
        return desc if desc else None
    except Exception:
        return None


def dump_tree(obj, out, depth=0, max_depth=20):
    if depth > max_depth:
        return
    try:
        role = obj.get_role_name() or ''
        name = obj.get_name() or ''

        if role in SKIP_ROLES:
            # Still recurse children
            for j in range(obj.get_child_count()):
                child = obj.get_child_at_index(j)
                if child:
                    dump_tree(child, out, depth, max_depth)
            return

        x, y, w, h = get_extents(obj)
        states = get_states(obj)
        desc = get_description(obj)

        # Only output elements with a name OR a meaningful role
        has_name = bool(name.strip())
        meaningful_role = role in {
            'push button', 'toggle button', 'check menu item',
            'radio menu item', 'menu item', 'menu', 'menu bar',
            'link', 'entry', 'heading', 'page tab', 'page tab list',
            'section', 'panel', 'image', 'separator', 'list item',
            'tool tip', 'combo box', 'check box', 'radio button',
            'dialog', 'alert', 'frame', 'scroll bar',
        }

        if has_name or meaningful_role:
            indent = '  ' * depth
            pos_str = f'@ ({x},{y}) size=({w}x{h})' if x is not None else '@ (no position)'
            state_str = f'  states=[{", ".join(states)}]' if states else ''
            desc_str = f'  desc="{desc}"' if desc else ''
            name_display = f'"{name}"' if name else '(unnamed)'
            out.write(f'{indent}[{role}] {name_display} {pos_str}{state_str}{desc_str}\n')

        count = obj.get_child_count()
        for j in range(count):
            child = obj.get_child_at_index(j)
            if child:
                dump_tree(child, out, depth + 1, max_depth)

    except Exception as e:
        out.write(f'{"  " * depth}[ERROR] {e}\n')


def find_firefox(desktop):
    """Find Firefox app in AT-SPI desktop."""
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app:
            name = app.get_name() or ''
            if 'firefox' in name.lower() or 'Mozilla' in name:
                return app
    return None


def main():
    parser = argparse.ArgumentParser(description='Dump AT-SPI tree')
    parser.add_argument('--display', required=True, help='X display (e.g. :3)')
    parser.add_argument('--label', required=True, help='Output label (e.g. claude_home)')
    parser.add_argument('--scope', default='all', choices=['all', 'menu', 'document'],
                        help='all=full tree, menu=app root (portals), document=page only')
    parser.add_argument('--max-depth', type=int, default=20)
    args = parser.parse_args()

    # Set environment
    bus_file = f'/tmp/a11y_bus_{args.display}'
    if os.path.exists(bus_file):
        with open(bus_file) as f:
            bus = f.read().strip()
        os.environ['AT_SPI_BUS_ADDRESS'] = bus
        os.environ['DBUS_SESSION_BUS_ADDRESS'] = bus
    os.environ['DISPLAY'] = args.display

    Atspi.init()
    desktop = Atspi.get_desktop(0)

    firefox = find_firefox(desktop)
    if not firefox:
        print(f'ERROR: Firefox not found on display {args.display}')
        sys.exit(1)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scans')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f'{args.label}.txt')

    # Take screenshot too
    screenshot_path = os.path.join(out_dir, f'{args.label}.png')
    os.system(f'DISPLAY={args.display} scrot {screenshot_path} 2>/dev/null')

    with open(out_path, 'w') as out:
        out.write(f'# AT-SPI Tree Scan\n')
        out.write(f'# Display: {args.display}\n')
        out.write(f'# Label: {args.label}\n')
        out.write(f'# Scope: {args.scope}\n')
        out.write(f'# Screenshot: {os.path.basename(screenshot_path)}\n')
        out.write(f'#\n')
        out.write(f'# Format: [role] "name" @ (x,y) size=(WxH) states=[...] desc="..."\n')
        out.write(f'# Indentation shows parent-child relationships.\n')
        out.write(f'#\n\n')

        if args.scope == 'all':
            out.write(f'=== FULL TREE (Firefox app root) ===\n\n')
            dump_tree(firefox, out, max_depth=args.max_depth)
        elif args.scope == 'document':
            # Find the document web element
            def find_doc(obj, depth=0):
                if depth > 10:
                    return None
                try:
                    if obj.get_role_name() == 'document web':
                        return obj
                    for j in range(obj.get_child_count()):
                        child = obj.get_child_at_index(j)
                        if child:
                            r = find_doc(child, depth + 1)
                            if r:
                                return r
                except Exception:
                    pass
                return None
            doc = find_doc(firefox)
            if doc:
                out.write(f'=== DOCUMENT SUBTREE ===\n\n')
                dump_tree(doc, out, max_depth=args.max_depth)
            else:
                out.write('ERROR: No document web element found\n')
        elif args.scope == 'menu':
            # Dump everything that's NOT inside a document web
            out.write(f'=== MENU/PORTAL ELEMENTS (non-document) ===\n\n')
            def dump_non_doc(obj, out, depth=0):
                if depth > args.max_depth:
                    return
                try:
                    role = obj.get_role_name() or ''
                    if role == 'document web':
                        out.write(f'{"  " * depth}[document web] (SKIPPED)\n')
                        return
                    name = obj.get_name() or ''
                    x, y, w, h = get_extents(obj)
                    states = get_states(obj)
                    if name.strip() or role in {'menu', 'menu item', 'radio menu item',
                                                 'check menu item', 'popup menu', 'dialog'}:
                        indent = '  ' * depth
                        pos_str = f'@ ({x},{y})' if x is not None else ''
                        state_str = f'  [{", ".join(states)}]' if states else ''
                        out.write(f'{indent}[{role}] "{name}" {pos_str}{state_str}\n')
                    for j in range(obj.get_child_count()):
                        child = obj.get_child_at_index(j)
                        if child:
                            dump_non_doc(child, out, depth + 1)
                except Exception:
                    pass
            dump_non_doc(firefox, out)

    print(f'Scan saved: {out_path}')
    print(f'Screenshot: {screenshot_path}')


if __name__ == '__main__':
    main()
