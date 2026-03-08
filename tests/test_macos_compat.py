"""Tests for macOS compatibility — verify module aliasing works."""

import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_clipboard_mac_module_exists():
    """Verify clipboard_mac module can be imported."""
    from core import clipboard_mac
    assert hasattr(clipboard_mac, 'read')
    assert hasattr(clipboard_mac, 'clear')
    assert hasattr(clipboard_mac, 'write_marker')
    assert hasattr(clipboard_mac, 'set_display')


def test_ax_browser_module_exists():
    """Verify ax_browser module can be imported (syntax check)."""
    # On Linux, pyobjc isn't available, but the module should still parse
    from core import ax_browser
    assert hasattr(ax_browser, 'find_browser')
    assert hasattr(ax_browser, 'find_firefox')  # Alias
    assert hasattr(ax_browser, 'get_platform_document')
    assert hasattr(ax_browser, 'get_document_url')
    assert hasattr(ax_browser, 'detect_platform_from_url')


def test_ax_tree_module_exists():
    """Verify ax_tree module can be imported."""
    from core import ax_tree
    assert hasattr(ax_tree, 'find_elements')
    assert hasattr(ax_tree, 'filter_useful_elements')
    assert hasattr(ax_tree, 'find_copy_buttons')
    assert hasattr(ax_tree, 'find_menu_items')
    assert hasattr(ax_tree, 'compute_tree_hash')
    assert hasattr(ax_tree, 'compute_structure_hash')


def test_ax_interact_module_exists():
    """Verify ax_interact module can be imported."""
    from core import ax_interact
    assert hasattr(ax_interact, 'cache_elements')
    assert hasattr(ax_interact, 'extend_cache')
    assert hasattr(ax_interact, 'find_element_at')
    assert hasattr(ax_interact, 'ax_click')
    assert hasattr(ax_interact, 'atspi_click')  # Alias
    assert hasattr(ax_interact, 'strip_atspi_obj')  # Alias
    assert hasattr(ax_interact, 'strip_ax_ref')


def test_input_mac_module_exists():
    """Verify input_mac module can be imported."""
    from core import input_mac
    assert hasattr(input_mac, 'press_key')
    assert hasattr(input_mac, 'click_at')
    assert hasattr(input_mac, 'type_text')
    assert hasattr(input_mac, 'focus_browser')
    assert hasattr(input_mac, 'focus_firefox')  # Alias
    assert hasattr(input_mac, 'switch_to_platform')
    assert hasattr(input_mac, 'clipboard_paste')
    assert hasattr(input_mac, 'scroll_to_bottom')
    assert hasattr(input_mac, 'scroll_to_top')


def test_backend_module_exists():
    """Verify backend module provides all getters."""
    from core import backend
    assert hasattr(backend, 'get_browser_module')
    assert hasattr(backend, 'get_tree_module')
    assert hasattr(backend, 'get_interact_module')
    assert hasattr(backend, 'get_input_module')
    assert hasattr(backend, 'get_clipboard_module')
    assert hasattr(backend, 'IS_MACOS')
    assert hasattr(backend, 'IS_LINUX')


def test_platforms_cross_platform():
    """Verify platforms.py has macOS screen detection."""
    from core import platforms
    assert hasattr(platforms, '_detect_screen_size_macos')
    assert hasattr(platforms, '_detect_screen_size_linux')


def test_module_aliasing_on_linux():
    """On Linux, core imports should give native AT-SPI modules."""
    if sys.platform == 'darwin':
        return  # Skip on macOS
    from core import atspi
    assert atspi.__name__ == 'core.atspi'  # Native module


def test_url_detection():
    """URL detection works on both platforms (no OS dependency)."""
    from core.ax_browser import detect_platform_from_url
    assert detect_platform_from_url('https://chatgpt.com/c/abc') == 'chatgpt'
    assert detect_platform_from_url('https://claude.ai/chat/def') == 'claude'
    assert detect_platform_from_url('https://gemini.google.com/app/ghi') == 'gemini'
    assert detect_platform_from_url('https://grok.com/c/jkl') == 'grok'
    assert detect_platform_from_url('https://perplexity.ai/search/mno') == 'perplexity'
    assert detect_platform_from_url('https://x.com/home') == 'x_twitter'
    assert detect_platform_from_url(None) is None
    assert detect_platform_from_url('https://google.com') is None
