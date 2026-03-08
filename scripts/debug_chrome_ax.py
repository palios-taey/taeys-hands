#!/usr/bin/env python3
"""Debug Chrome's AX tree on macOS — discover tabs, windows, and structure."""
import sys
sys.path.insert(0, '.')

try:
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
    )
    from AppKit import NSWorkspace
except ImportError:
    print("ERROR: pyobjc not available")
    sys.exit(1)

# Find Chrome PID
pid = None
ws = NSWorkspace.sharedWorkspace()
for app in ws.runningApplications():
    if app.localizedName() == 'Google Chrome':
        pid = app.processIdentifier()
        break

if not pid:
    print("ERROR: Chrome not running")
    sys.exit(1)

print(f"Chrome PID: {pid}")

ax_app = AXUIElementCreateApplication(pid)

def _get(el, attr):
    err, val = AXUIElementCopyAttributeValue(el, attr, None)
    return val if err == 0 else None

# List windows
err, windows = AXUIElementCopyAttributeValue(ax_app, 'AXWindows', None)
print(f"\n=== WINDOWS ({len(windows) if windows else 0}) ===")
if windows:
    for i, win in enumerate(windows):
        title = _get(win, 'AXTitle') or '(no title)'
        focused = _get(win, 'AXFocused')
        main = _get(win, 'AXMain')
        print(f"  Window {i}: '{title}' (focused={focused}, main={main})")

# Get focused window
err, focused_win = AXUIElementCopyAttributeValue(ax_app, 'AXFocusedWindow', None)
if err == 0 and focused_win:
    fw_title = _get(focused_win, 'AXTitle') or '(no title)'
    print(f"\nAXFocusedWindow: '{fw_title}'")
else:
    print(f"\nAXFocusedWindow: not found (err={err})")

# Find tabs (AXRadioButton inside AXTabGroup)
print(f"\n=== TABS ===")
tab_count = 0

def find_tabs(el, depth=0, max_depth=6):
    global tab_count
    if depth > max_depth:
        return
    role = _get(el, 'AXRole') or ''

    if role == 'AXTabGroup':
        children = _get(el, 'AXChildren') or []
        for child in children:
            crole = _get(child, 'AXRole') or ''
            if crole == 'AXRadioButton':
                title = _get(child, 'AXTitle') or '(no title)'
                selected = _get(child, 'AXValue')
                print(f"  Tab {tab_count}: '{title}' (selected={selected})")
                tab_count += 1
        return  # Don't recurse into tab group children

    children = _get(el, 'AXChildren') or []
    for child in children:
        find_tabs(child, depth + 1)

find_tabs(ax_app)
if tab_count == 0:
    print("  No tabs found via AXTabGroup/AXRadioButton")
    # Try alternative: check window children directly
    print("\n=== WINDOW CHILDREN (depth 0-3) ===")
    if windows:
        for i, win in enumerate(windows[:1]):  # First window only
            title = _get(win, 'AXTitle') or '(no title)'
            print(f"  Window '{title}':")
            def dump(el, depth=0, max_depth=3, indent="    "):
                if depth > max_depth:
                    return
                role = _get(el, 'AXRole') or ''
                name = _get(el, 'AXTitle') or _get(el, 'AXDescription') or ''
                if role or name:
                    print(f"{indent}{'  ' * depth}{role}: '{name[:60]}'")
                children = _get(el, 'AXChildren') or []
                for child in children[:10]:
                    dump(child, depth + 1, max_depth, indent)
            dump(win)

print("\nDone.")
