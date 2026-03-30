"""Shared platform YAML config loader — single cache, used everywhere.

Every module that needs platform config should:
    from core.config import get_platform_config
    config = get_platform_config('chatgpt')

No more per-module YAML loading or PLATFORMS_DIR constants.
"""

import os
import logging
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

PLATFORMS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms'
)

_cache: Dict[str, dict] = {}


def get_platform_config(platform: str, *, reload: bool = False) -> dict:
    """Load and cache platform YAML config.

    Raises FileNotFoundError for known platforms if YAML is missing.
    Returns empty dict for unknown platforms.
    """
    if not reload and platform in _cache:
        return _cache[platform]

    yaml_path = os.path.join(PLATFORMS_DIR, f'{platform}.yaml')
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        _KNOWN = {'chatgpt', 'claude', 'gemini', 'grok', 'perplexity'}
        if platform in _KNOWN:
            raise
        logger.warning("No YAML for platform %s, using empty config", platform)
        data = {}

    _cache[platform] = data
    return data


def get_element_spec(platform: str, element_key: str) -> Optional[dict]:
    """Get a specific element_map entry from platform YAML.

    Returns None if the key doesn't exist.
    """
    config = get_platform_config(platform)
    return config.get('element_map', {}).get(element_key)


def get_attach_trigger_key(platform: str) -> Optional[str]:
    """Get the element_map key for the attach trigger button.

    Each platform defines its attach trigger differently:
      chatgpt: attach_trigger ("Add files and more")
      claude:  toggle_menu ("Toggle menu")
      gemini:  upload_menu ("Open upload file menu")
      grok:    attach_trigger ("Attach")
      perplexity: attach_trigger ("Add files or tools")

    Returns the element_map key name, or None if not found.
    """
    config = get_platform_config(platform)
    emap = config.get('element_map', {})

    # Explicit mapping of which element_map key is the attach trigger
    _ATTACH_KEYS = {
        'chatgpt': 'attach_trigger',
        'claude': 'toggle_menu',
        'gemini': 'upload_menu',
        'grok': 'attach_trigger',
        'perplexity': 'attach_trigger',
    }
    key = _ATTACH_KEYS.get(platform)
    if key and key in emap:
        return key

    # Fallback: look for any key with 'attach' or 'upload' in it
    for k in emap:
        if 'attach' in k or 'upload' in k:
            return k
    return None


def get_upload_item_key(platform: str) -> Optional[str]:
    """Get the element_map key for the 'upload file' menu item.

    After clicking the attach trigger, a dropdown may appear.
    This returns the key for the specific "upload a file" item.

    Returns None if the platform opens a file dialog directly (no dropdown).
    """
    config = get_platform_config(platform)
    emap = config.get('element_map', {})

    _UPLOAD_KEYS = {
        'chatgpt': 'tool_upload',       # "Add photos" button
        'claude': 'upload_files_item',    # "Add files or photos" / "Add content" menu item
        'gemini': 'upload_files_item',   # "Upload files..." menu item
        'grok': None,                    # keyboard_nav opens file dialog directly
        'perplexity': 'upload_files_item',  # "Upload files or images" menu item
    }
    key = _UPLOAD_KEYS.get(platform)
    if key and key in emap:
        return key
    return None


def get_click_strategy(platform: str) -> str:
    """Get click strategy: 'atspi_first' or 'xdotool_first'."""
    config = get_platform_config(platform)
    return config.get('click_strategy', 'xdotool_first')


def get_attach_method(platform: str) -> str:
    """Get attach method: 'keyboard_nav', 'atspi_menu', or 'none'."""
    config = get_platform_config(platform)
    return config.get('attach_method', 'atspi_menu')


def get_dropdown_method(platform: str) -> str:
    """Get dropdown method: 'keyboard_nav' or 'atspi_enum'."""
    config = get_platform_config(platform)
    return config.get('dropdown_method', 'atspi_enum')


def get_stop_patterns(platform: str) -> List[str]:
    """Get stop button patterns for response monitoring."""
    config = get_platform_config(platform)
    return config.get('stop_patterns', ['stop'])


def get_fence_after(platform: str) -> List[dict]:
    """Get fence_after rules for tree traversal."""
    config = get_platform_config(platform)
    return config.get('fence_after', [])


def get_capabilities(platform: str) -> dict:
    """Get capabilities (models, modes, tools, sources)."""
    config = get_platform_config(platform)
    return config.get('capabilities', {})


def get_mode_guidance(platform: str) -> dict:
    """Get mode_guidance for model/mode selection."""
    config = get_platform_config(platform)
    return config.get('mode_guidance', {})


def get_validation(platform: str) -> dict:
    """Get validation expectations for post-action verification."""
    config = get_platform_config(platform)
    return config.get('validation', {})


def scan_platform_tree(platform: str) -> tuple:
    """Scan the AT-SPI tree for a platform via direct AT-SPI.

    Returns (elements: list[dict], url: str|None, error: str|None).

    Multi-display is handled by per-display workers — each worker
    has the correct DISPLAY/AT-SPI bus, so this always uses the
    direct local path.

    Elements are raw dicts with name/role/x/y/states — no atspi_obj
    (stripped for serialization safety).
    """
    from core import atspi
    from core.tree import find_elements
    from core.interact import strip_atspi_obj

    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        return [], None, f'Firefox not found for {platform}'

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return [], None, f'{platform} document not found'

    url = atspi.get_document_url(doc)
    config = get_platform_config(platform)
    fences = config.get('fence_after', [])
    all_elements = find_elements(doc, fence_after=fences)
    return strip_atspi_obj(all_elements), url, None
