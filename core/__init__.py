# Core accessibility primitives for browser automation.
# Linux: AT-SPI + xdotool + xsel
# macOS: AXUIElement + AppleScript + pbcopy/pbpaste
#
# On macOS, we inject AX modules so that existing tool imports like
# `from core import atspi` and `from core.tree import find_elements`
# transparently resolve to the macOS equivalents.

import sys

if sys.platform == 'darwin':
    # Import macOS modules
    from core import ax_browser, ax_tree, ax_interact, input_mac, clipboard_mac

    # Package-level aliases so `from core import atspi` works
    atspi = ax_browser
    tree = ax_tree
    atspi_interact = ax_interact
    input = input_mac
    clipboard = clipboard_mac

    # Also inject into sys.modules for `from core.tree import X` etc.
    sys.modules['core.atspi'] = ax_browser
    sys.modules['core.tree'] = ax_tree
    sys.modules['core.atspi_interact'] = ax_interact
    sys.modules['core.input'] = input_mac
    sys.modules['core.clipboard'] = clipboard_mac
