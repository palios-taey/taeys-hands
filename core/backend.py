"""
Platform backend abstraction layer.

Auto-detects OS and provides the correct accessibility, input,
and clipboard implementations:
- Linux: AT-SPI + xdotool + xsel
- macOS: AXUIElement + AppleScript + pbcopy/pbpaste

Tools import from this module instead of platform-specific ones.
"""

import sys
import logging

logger = logging.getLogger(__name__)

IS_MACOS = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')


def get_browser_module():
    """Get the browser discovery module for the current OS.

    Returns module with:
        find_browser() -> browser object or None
        get_platform_document(browser, platform) -> document or None
        get_document_url(doc) -> str or None
        detect_platform_from_url(url) -> str or None
        is_file_dialog_open(browser) -> bool
    """
    if IS_MACOS:
        from core import ax_browser
        return ax_browser
    else:
        from core import atspi
        return atspi


def get_tree_module():
    """Get the tree traversal module for the current OS.

    Returns module with:
        find_elements(scope, ...) -> List[Dict]
        filter_useful_elements(elements, ...) -> List[Dict]
        find_copy_buttons(elements) -> List[Dict]
        find_menu_items(browser, doc) -> List[Dict]
        detect_chrome_y(doc) -> int
        compute_structure_hash(elements, ...) -> str
        compute_tree_hash(elements) -> str
    """
    if IS_MACOS:
        from core import ax_tree
        return ax_tree
    else:
        from core import tree
        return tree


def get_interact_module():
    """Get the element interaction module for the current OS.

    Returns module with:
        cache_elements(platform, elements)
        extend_cache(platform, elements)
        find_element_at(platform, x, y, tolerance) -> Dict or None
        atspi_click(element, ...) / ax_click(element, ...) -> bool
        atspi_focus(element) / ax_focus(element) -> bool
        is_defunct(element) -> bool
        strip_atspi_obj(elements) / strip_ax_ref(elements) -> List[Dict]
    """
    if IS_MACOS:
        from core import ax_interact
        return ax_interact
    else:
        from core import atspi_interact
        return atspi_interact


def get_input_module():
    """Get the keyboard/mouse input module for the current OS.

    Returns module with:
        press_key(key, ...) -> bool
        click_at(x, y, ...) -> bool
        type_text(text, ...) -> bool
        focus_browser(...) -> bool
        switch_to_platform(platform) -> bool
        scroll_to_bottom()
        scroll_to_top()
        scroll_page_down()
        scroll_page_up()
        clipboard_paste(text, ...) -> bool
    """
    if IS_MACOS:
        from core import input_mac
        return input_mac
    else:
        from core import input as inp
        return inp


def get_clipboard_module():
    """Get the clipboard module for the current OS.

    Returns module with:
        read() -> str or None
        clear()
        write_marker(text)
    """
    if IS_MACOS:
        from core import clipboard_mac
        return clipboard_mac
    else:
        from core import clipboard
        return clipboard
