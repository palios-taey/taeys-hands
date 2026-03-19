"""Mode/Model Selection — YAML-driven, coordinate-free.

Reads desired model/mode from task assignment, looks up YAML mode_guidance,
uses element_map to find trigger button, clicks trigger, selects from menu.

Per-platform model selection flow:
  ChatGPT: "Model selector, current model is..." → xdotool click → keyboard nav
  Gemini:  "Open mode picker" (model) + "Tools" (Deep think) → AT-SPI do_action → menu items
  Grok:    "Model select" → xdotool click → AT-SPI menu items
  Perplexity: "Model" button (model) + "Add files or tools" (tools) → mixed
  Claude:  Model button → AT-SPI dropdown → select

This module handles the full flow: find trigger → click → select target.
"""

import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import yaml

from core import atspi, input as inp
from core.tree import find_elements, find_menu_items, detect_chrome_y

logger = logging.getLogger(__name__)

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

# Cache
_platform_configs: Dict[str, dict] = {}


def _load_config(platform: str) -> dict:
    if platform not in _platform_configs:
        with open(os.path.join(PLATFORMS_DIR, f'{platform}.yaml')) as f:
            _platform_configs[platform] = yaml.safe_load(f) or {}
    return _platform_configs[platform]


def select_mode_model(platform: str, mode: str = None, model: str = None,
                      doc=None, firefox=None,
                      our_pid: int = None) -> Dict:
    """Select model and/or mode on a platform.

    Args:
        platform: chatgpt, gemini, grok, perplexity, claude
        mode: Mode key from YAML mode_guidance (e.g., 'deep_think', 'pro', 'expert')
        model: Model name (overrides mode if both given)
        doc: AT-SPI document reference (optional, will discover)
        firefox: AT-SPI firefox reference (optional, will discover)
        our_pid: Firefox PID for filtering in multi-instance mode

    Returns:
        Dict with 'success', 'selected_model', 'selected_mode', or 'error'.
    """
    config = _load_config(platform)
    mode_guidance = config.get('mode_guidance', {})
    element_map = config.get('element_map', {})

    # Determine what to select
    target_mode = mode or model
    if not target_mode:
        return {'success': True, 'note': 'No mode/model requested, using platform default'}

    target_mode_lower = target_mode.lower().strip()

    # Look up in mode_guidance
    guidance = mode_guidance.get(target_mode_lower)
    if not guidance:
        # Try partial match
        for key, val in mode_guidance.items():
            if target_mode_lower in key.lower() or key.lower() in target_mode_lower:
                guidance = val
                target_mode_lower = key
                break

    if not guidance:
        return {
            'success': False,
            'error': f"Mode '{target_mode}' not found in {platform} mode_guidance",
            'available_modes': list(mode_guidance.keys()),
        }

    how = guidance.get('how', '')
    timeout = guidance.get('timeout', 1800)

    logger.info(f"[{platform}] Selecting mode: {target_mode_lower} — {how}")

    # If "Default" or "no selection needed", skip
    if 'default' in how.lower() and 'no selection' in how.lower():
        return {
            'success': True,
            'selected_mode': target_mode_lower,
            'note': 'Default mode — no selection needed',
            'timeout': timeout,
        }

    # Get AT-SPI references
    if not firefox:
        firefox = atspi.find_firefox_for_platform(platform, pid=our_pid)
    if not firefox:
        return {'success': False, 'error': 'Firefox not found'}

    if not doc:
        doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {'success': False, 'error': f'{platform} document not found'}

    # Route to platform-specific handler
    result = _select_for_platform(platform, target_mode_lower, guidance, config, doc, firefox)
    if result.get('success'):
        result['timeout'] = timeout
    return result


def _select_for_platform(platform: str, mode_key: str, guidance: dict,
                         config: dict, doc, firefox) -> Dict:
    """Route to platform-specific selection logic."""
    how = guidance.get('how', '')

    if platform == 'chatgpt':
        return _select_chatgpt(mode_key, guidance, config, doc, firefox)
    elif platform == 'gemini':
        return _select_gemini(mode_key, guidance, config, doc, firefox)
    elif platform == 'grok':
        return _select_grok(mode_key, guidance, config, doc, firefox)
    elif platform == 'perplexity':
        return _select_perplexity(mode_key, guidance, config, doc, firefox)
    elif platform == 'claude':
        return _select_claude(mode_key, guidance, config, doc, firefox)
    else:
        return {'success': False, 'error': f'Unknown platform: {platform}'}


def _find_button_by_element_map(doc, element_map_key: str, config: dict,
                                fence_after: list = None) -> Optional[Dict]:
    """Find a button defined in element_map by scanning AT-SPI tree."""
    em = config.get('element_map', {})
    spec = em.get(element_map_key)
    if not spec:
        return None

    fences = config.get('fence_after', [])
    elements = find_elements(doc, fence_after=fences)

    target_name = spec.get('name', '').lower()
    target_name_pattern = spec.get('name_pattern', '').lower()
    target_name_contains = spec.get('name_contains', '')
    if isinstance(target_name_contains, list):
        target_name_contains = [n.lower() for n in target_name_contains]
    elif target_name_contains:
        target_name_contains = [target_name_contains.lower()]
    else:
        target_name_contains = []
    target_role = spec.get('role', '').lower()
    target_role_contains = spec.get('role_contains', '').lower() if spec.get('role_contains') else ''

    for e in elements:
        name = (e.get('name') or '').strip().lower()
        role = (e.get('role') or '').strip().lower()

        # Role match
        if target_role and role != target_role:
            if target_role_contains and target_role_contains not in role:
                continue
            elif not target_role_contains:
                continue
        elif target_role_contains and target_role_contains not in role:
            continue

        # Name match
        if target_name and name == target_name:
            return e
        if target_name_pattern:
            pattern = target_name_pattern
            if '*' in pattern:
                prefix = pattern.split('*')[0]
                if prefix and name.startswith(prefix):
                    return e
            elif name == pattern:
                return e
        if target_name_contains:
            if any(nc in name for nc in target_name_contains):
                return e

    return None


def _click_element(element: Dict, platform: str, config: dict) -> bool:
    """Click an element using the platform's click_strategy."""
    from core.interact import atspi_click
    strategy = config.get('click_strategy', 'xdotool_first')

    if strategy == 'atspi_first':
        if atspi_click(element):
            return True
        # Fallback to xdotool
        x, y = int(element.get('x', 0)), int(element.get('y', 0))
        if x > 0 and y > 0:
            return inp.click_at(x, y)
        return False
    else:  # xdotool_first
        x, y = int(element.get('x', 0)), int(element.get('y', 0))
        if x > 0 and y > 0 and inp.click_at(x, y):
            return True
        return atspi_click(element)


def _select_chatgpt(mode_key: str, guidance: dict, config: dict,
                    doc, firefox) -> Dict:
    """ChatGPT: Click model selector → keyboard nav to item → Enter.

    ChatGPT uses React portal dropdowns — invisible to AT-SPI.
    Must use keyboard navigation after opening.
    """
    # Find model selector button
    button = _find_button_by_element_map(doc, 'model_selector', config)
    if not button:
        return {'success': False, 'error': 'ChatGPT model_selector button not found'}

    # Click to open dropdown
    if not _click_element(button, 'chatgpt', config):
        return {'success': False, 'error': 'Failed to click ChatGPT model selector'}
    time.sleep(1.0)

    # Map mode_key to YAML capabilities.models index
    caps = config.get('capabilities', {})
    models = caps.get('models', [])

    # mode_key mapping to model item
    mode_to_model = {
        'auto': 'Auto',
        'instant': 'Instant',
        'thinking': 'Thinking',
        'pro': 'Pro',
    }
    target_label = mode_to_model.get(mode_key, mode_key.capitalize())

    # Find index in models list
    target_idx = None
    for i, m in enumerate(models):
        m_str = str(m).strip()
        if m_str.lower().startswith(target_label.lower()):
            target_idx = i
            break

    if target_idx is None:
        # Close dropdown
        inp.press_key('Escape')
        return {'success': False, 'error': f"ChatGPT model '{target_label}' not found in YAML capabilities.models"}

    # Keyboard nav: Down * (index+1) → Enter
    for _ in range(target_idx + 1):
        inp.press_key('Down')
        time.sleep(0.15)
    inp.press_key('Return')
    time.sleep(0.5)

    return {
        'success': True,
        'selected_mode': mode_key,
        'selected_via': 'keyboard_nav',
        'platform': 'chatgpt',
        'model_label': target_label,
    }


def _select_gemini(mode_key: str, guidance: dict, config: dict,
                   doc, firefox) -> Dict:
    """Gemini: mode_picker for model selection, tools_button for Deep think/Deep research.

    Two separate interaction paths:
    - Mode (Fast/Thinking/Pro): Click "Open mode picker" → radio menu items
    - Tools (Deep think/Deep research): Click "Tools" → check menu items
    """
    how = guidance.get('how', '')

    if 'mode picker' in how.lower() or 'open mode picker' in how.lower():
        # Mode selection via mode_picker
        button = _find_button_by_element_map(doc, 'mode_picker', config)
        if not button:
            return {'success': False, 'error': 'Gemini mode_picker button not found'}

        if not _click_element(button, 'gemini', config):
            return {'success': False, 'error': 'Failed to click Gemini mode picker'}
        time.sleep(1.0)

        # AT-SPI menu items should now be visible
        menu_items = find_menu_items(firefox, doc)
        if not menu_items:
            time.sleep(1.0)
            menu_items = find_menu_items(firefox, doc)

        return _select_from_menu(menu_items, mode_key, 'gemini', config)

    elif 'tools' in how.lower():
        # Tool selection via tools_button
        button = _find_button_by_element_map(doc, 'tools_button', config)
        if not button:
            return {'success': False, 'error': 'Gemini tools_button not found'}

        if not _click_element(button, 'gemini', config):
            return {'success': False, 'error': 'Failed to click Gemini Tools button'}
        time.sleep(1.0)

        menu_items = find_menu_items(firefox, doc)
        if not menu_items:
            time.sleep(1.0)
            menu_items = find_menu_items(firefox, doc)

        return _select_from_menu(menu_items, mode_key, 'gemini', config)

    return {'success': False, 'error': f'Unknown Gemini selection method: {how}'}


def _select_grok(mode_key: str, guidance: dict, config: dict,
                 doc, firefox) -> Dict:
    """Grok: Click "Model select" → AT-SPI menu items visible → click target."""
    button = _find_button_by_element_map(doc, 'model_selector', config)
    if not button:
        return {'success': False, 'error': 'Grok model_selector button not found'}

    if not _click_element(button, 'grok', config):
        return {'success': False, 'error': 'Failed to click Grok Model select'}
    time.sleep(1.0)

    # Grok React portal — items visible in AT-SPI after xdotool click
    menu_items = find_menu_items(firefox, doc)
    if not menu_items:
        time.sleep(1.0)
        menu_items = find_menu_items(firefox, doc)

    return _select_from_menu(menu_items, mode_key, 'grok', config)


def _select_perplexity(mode_key: str, guidance: dict, config: dict,
                       doc, firefox) -> Dict:
    """Perplexity: Model button for model, Add files or tools for tools."""
    how = guidance.get('how', '')

    if 'model' in how.lower() and 'button' in how.lower():
        button = _find_button_by_element_map(doc, 'model_selector', config)
        if not button:
            return {'success': False, 'error': 'Perplexity Model button not found'}

        if not _click_element(button, 'perplexity', config):
            return {'success': False, 'error': 'Failed to click Perplexity Model button'}
        time.sleep(1.0)

        menu_items = find_menu_items(firefox, doc)
        return _select_from_menu(menu_items, mode_key, 'perplexity', config)

    elif 'add files' in how.lower() or 'tools' in how.lower():
        button = _find_button_by_element_map(doc, 'attach_trigger', config)
        if not button:
            return {'success': False, 'error': 'Perplexity attach_trigger not found'}

        if not _click_element(button, 'perplexity', config):
            return {'success': False, 'error': 'Failed to click Perplexity tools button'}
        time.sleep(1.0)

        menu_items = find_menu_items(firefox, doc)
        return _select_from_menu(menu_items, mode_key, 'perplexity', config)

    elif 'sidebar' in how.lower() or 'computer' in how.lower():
        # Computer mode — click sidebar link
        fences = config.get('fence_after', [])
        elements = find_elements(doc, fence_after=fences)
        for e in elements:
            name = (e.get('name') or '').strip().lower()
            if name == 'computer' and 'link' in (e.get('role') or ''):
                if _click_element(e, 'perplexity', config):
                    time.sleep(2.0)
                    return {'success': True, 'selected_mode': mode_key, 'platform': 'perplexity'}
        return {'success': False, 'error': 'Perplexity Computer sidebar link not found'}

    return {'success': False, 'error': f'Unknown Perplexity selection method: {how}'}


def _select_claude(mode_key: str, guidance: dict, config: dict,
                   doc, firefox) -> Dict:
    """Claude: Model button → dropdown → select."""
    how = guidance.get('how', '')

    if 'toggle menu' in how.lower():
        button = _find_button_by_element_map(doc, 'toggle_menu', config)
        if not button:
            return {'success': False, 'error': 'Claude toggle_menu not found'}

        if not _click_element(button, 'claude', config):
            return {'success': False, 'error': 'Failed to click Claude Toggle menu'}
        time.sleep(1.0)

        menu_items = find_menu_items(firefox, doc)
        return _select_from_menu(menu_items, mode_key, 'claude', config)

    elif 'model button' in how.lower() or 'model selector' in how.lower():
        button = _find_button_by_element_map(doc, 'model_selector', config)
        if not button:
            return {'success': False, 'error': 'Claude model_selector not found'}

        if not _click_element(button, 'claude', config):
            return {'success': False, 'error': 'Failed to click Claude model selector'}
        time.sleep(1.0)

        menu_items = find_menu_items(firefox, doc)
        return _select_from_menu(menu_items, mode_key, 'claude', config)

    return {'success': False, 'error': f'Unknown Claude selection method: {how}'}


def _select_from_menu(menu_items: list, mode_key: str, platform: str,
                      config: dict) -> Dict:
    """Try to find and click a matching menu item."""
    if not menu_items:
        inp.press_key('Escape')
        return {'success': False, 'error': f'No menu items found after opening {platform} dropdown'}

    # Map mode_key to expected item names
    mode_key_lower = mode_key.lower().strip()

    # Build search terms
    search_terms = [mode_key_lower]
    # Common aliases
    aliases = {
        'deep_think': ['deep think'],
        'deep_research': ['deep research'],
        'extended_thinking': ['extended thinking', 'extended'],
        'expert': ['expert'],
        'heavy': ['heavy'],
        'thinking': ['thinking'],
        'pro': ['pro'],
        'fast': ['fast'],
        'normal': ['fast', 'auto'],
        'web_search': ['web search'],
        'research': ['research'],
    }
    search_terms.extend(aliases.get(mode_key_lower, []))

    from core.interact import atspi_click

    for item in menu_items:
        item_name = (item.get('name') or '').strip().lower()
        if not item_name:
            continue

        for term in search_terms:
            if term in item_name or item_name.startswith(term):
                # Match found — click it
                logger.info(f"[{platform}] Menu match: '{item.get('name')}' for mode '{mode_key}'")

                clicked = False
                if item.get('atspi_obj'):
                    clicked = atspi_click(item)
                if not clicked:
                    x, y = int(item.get('x', 0)), int(item.get('y', 0))
                    if x > 0 and y > 0:
                        clicked = inp.click_at(x, y)

                if clicked:
                    time.sleep(0.5)
                    return {
                        'success': True,
                        'selected_mode': mode_key,
                        'selected_item': item.get('name', ''),
                        'platform': platform,
                    }
                else:
                    return {
                        'success': False,
                        'error': f"Found '{item.get('name')}' but failed to click",
                    }

    # No match — close dropdown and report
    inp.press_key('Escape')
    available = [item.get('name', '') for item in menu_items if item.get('name')]
    return {
        'success': False,
        'error': f"No menu item matched '{mode_key}' in {platform}",
        'available_items': available[:10],
    }
