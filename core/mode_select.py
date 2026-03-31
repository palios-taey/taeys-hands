"""Mode/Model Selection — YAML-driven, tree-verified, no guessing.

All platforms: click trigger → AT-SPI scan for menu items → match by name → click → verify.
No keyboard index counting. No Down+Enter probing.

Per-platform flow:
  ChatGPT: model_selector → AT-SPI items (model_auto/instant/thinking/pro now visible since March 2026)
  Gemini:  mode_picker (model) + tools_button (Deep think) → AT-SPI menu items
  Grok:    model_selector → AT-SPI menu items
  Perplexity: model_selector + attach_trigger → AT-SPI menu items
  Claude:  model_selector / toggle_menu → AT-SPI dropdown items
"""

import logging
import time
from typing import Dict, List, Optional

from core import atspi, input as inp
from core.config import (
    get_platform_config, get_element_spec, get_click_strategy,
    get_mode_guidance, get_validation, get_fence_after,
)
from core.tree import find_elements, find_menu_items, detect_chrome_y

logger = logging.getLogger(__name__)


def select_mode_model(platform: str, mode: str = None, model: str = None,
                      doc=None, firefox=None,
                      our_pid: int = None) -> Dict:
    """Select model and/or mode on a platform.

    All platforms use the same flow:
      1. Look up mode_guidance from YAML
      2. Find the trigger button via element_map
      3. Click trigger to open dropdown/menu
      4. Scan AT-SPI tree for menu items
      5. Match target by name
      6. Click it
      7. Verify selection took effect
    """
    mode_guidance = get_mode_guidance(platform)

    target_mode = mode or model
    if not target_mode:
        return {'success': True, 'note': 'No mode/model requested, using platform default'}

    target_mode_lower = target_mode.lower().strip()

    # Look up in mode_guidance
    guidance = mode_guidance.get(target_mode_lower)
    if not guidance:
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
    steps = guidance.get('steps')

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

    # Multi-step selection (e.g., ChatGPT Pro + Extended Thinking)
    if steps and isinstance(steps, list) and len(steps) > 1:
        result = _multi_step_select(platform, steps, target_mode_lower,
                                     firefox, doc)
        if result.get('success'):
            result['timeout'] = timeout
        return result

    # Single-step selection (standard flow)
    # Determine which trigger button to click from the 'how' text
    trigger_key = _determine_trigger_key(platform, how)
    if not trigger_key:
        return {'success': False, 'error': f"Cannot determine trigger button from: {how}"}

    # Find trigger button in AT-SPI tree
    trigger = _find_button_by_element_map(doc, trigger_key, platform)
    if not trigger:
        return {'success': False, 'error': f'{platform} {trigger_key} button not found in AT-SPI tree'}

    # Click trigger to open dropdown
    if not _click_element(trigger, platform):
        return {'success': False, 'error': f'Failed to click {platform} {trigger_key}'}
    time.sleep(1.0)

    # Scan for menu items — this is the universal approach
    menu_items = find_menu_items(firefox, doc)
    if not menu_items:
        time.sleep(1.0)
        menu_items = find_menu_items(firefox, doc)

    if not menu_items:
        # Fallback: scan entire tree for matching element_map items
        # ChatGPT model items are now AT-SPI push buttons, not menu items
        fences = get_fence_after(platform)
        all_elements = find_elements(doc, fence_after=fences)
        menu_items = _find_model_buttons_in_tree(platform, target_mode_lower, all_elements)

    if not menu_items:
        inp.press_key('Escape')
        return {
            'success': False,
            'error': f'No menu items found after opening {platform} {trigger_key}',
            'platform': platform,
        }

    # Match and click target
    result = _match_and_click(menu_items, target_mode_lower, platform)

    if result.get('success'):
        result['timeout'] = timeout
        # Verify selection
        verification = _verify_selection(platform, target_mode_lower, firefox, doc)
        result['verified'] = verification.get('verified', False)
        if not verification.get('verified'):
            result['verification_note'] = verification.get('note', 'Could not verify')

    return result


def _multi_step_select(platform: str, steps: list, target_mode: str,
                        firefox, doc) -> Dict:
    """Execute a multi-step mode selection (e.g., ChatGPT Pro + Extended Thinking).

    Each step has:
      trigger: element_map key to click (or null to skip trigger, reuse current dropdown)
      select: mode name to match and click in the resulting menu

    Between steps, the UI updates (dropdown closes, new options appear).
    We re-scan the AT-SPI tree after each step.
    """
    from core.interact import atspi_click

    completed_steps = []

    for i, step in enumerate(steps):
        trigger_key = step.get('trigger')
        select_target = str(step.get('select', '')).lower().strip()

        if not select_target:
            return {'success': False, 'error': f'Step {i+1}: no select target specified'}

        logger.info(f"[{platform}] Multi-step {i+1}/{len(steps)}: "
                    f"trigger={trigger_key}, select='{select_target}'")

        # Click trigger if specified (step 1 opens model dropdown)
        if trigger_key:
            trigger = _find_button_by_element_map(doc, trigger_key, platform)
            if not trigger:
                return {
                    'success': False,
                    'error': f'Step {i+1}: {trigger_key} button not found in AT-SPI tree',
                    'completed_steps': completed_steps,
                }
            if not _click_element(trigger, platform):
                return {
                    'success': False,
                    'error': f'Step {i+1}: failed to click {trigger_key}',
                    'completed_steps': completed_steps,
                }
            time.sleep(1.0)

        # Scan for matching items.
        # For steps with a trigger: look for dropdown menu items first.
        # For steps without trigger (null): the options may be tiles/buttons
        # visible in the page (e.g., ChatGPT Extended/Standard after Pro selection).
        menu_items = []

        if trigger_key:
            # Dropdown was opened — look for menu items
            menu_items = find_menu_items(firefox, doc)
            if not menu_items:
                time.sleep(1.0)
                doc = atspi.get_platform_document(firefox, platform) or doc
                menu_items = find_menu_items(firefox, doc)

        if not menu_items:
            # Fallback: scan full tree for element_map buttons AND any matching elements
            fences = get_fence_after(platform)
            all_elements = find_elements(doc, fence_after=fences)
            menu_items = _find_model_buttons_in_tree(platform, select_target, all_elements)

        if not menu_items:
            # Last resort: find ANY visible button/element matching the select target
            # This catches tiles in the input area (ChatGPT Extended/Standard)
            fences = get_fence_after(platform)
            all_elements = find_elements(doc, fence_after=fences)
            for e in all_elements:
                ename = (e.get('name') or '').strip().lower()
                erole = e.get('role', '')
                if erole in ('push button', 'toggle button', 'button', 'radio button') and \
                   select_target in ename:
                    menu_items = [e]
                    logger.info(f"[{platform}] Found '{e.get('name')}' ({erole}) via tree scan")
                    break

        if not menu_items:
            inp.press_key('Escape')
            return {
                'success': False,
                'error': f'Step {i+1}: no items found for "{select_target}"',
                'completed_steps': completed_steps,
            }

        # Match and click
        step_result = _match_and_click(menu_items, select_target, platform)
        if not step_result.get('success'):
            step_result['step'] = i + 1
            step_result['completed_steps'] = completed_steps
            return step_result

        completed_steps.append({
            'step': i + 1,
            'trigger': trigger_key,
            'selected': step_result.get('selected_item', select_target),
        })

        # Wait for UI to update between steps
        if i < len(steps) - 1:
            time.sleep(1.5)
            # Re-get doc for next step
            doc = atspi.get_platform_document(firefox, platform) or doc

    # All steps completed
    last_selected = completed_steps[-1]['selected'] if completed_steps else target_mode
    return {
        'success': True,
        'selected_mode': target_mode,
        'selected_item': last_selected,
        'platform': platform,
        'multi_step': True,
        'completed_steps': completed_steps,
    }


def _determine_trigger_key(platform: str, how: str) -> Optional[str]:
    """Map mode_guidance 'how' text to element_map trigger key."""
    how_lower = how.lower()

    # Direct mappings from 'how' text to element_map keys
    if 'model selector' in how_lower or 'model button' in how_lower or 'click model' in how_lower:
        return 'model_selector'
    if 'mode picker' in how_lower or 'open mode picker' in how_lower:
        return 'mode_picker'
    if 'tools' in how_lower and ('button' in how_lower or 'select' in how_lower):
        return 'tools_button'
    if 'toggle menu' in how_lower:
        return 'toggle_menu'
    if 'add files' in how_lower:
        return 'attach_trigger'
    if 'sidebar' in how_lower:
        # Sidebar links are not trigger buttons — handled separately
        return None

    # Platform-specific defaults
    _DEFAULT_TRIGGERS = {
        'chatgpt': 'model_selector',
        'claude': 'model_selector',
        'gemini': 'mode_picker',
        'grok': 'model_selector',
        'perplexity': 'model_selector',
    }
    return _DEFAULT_TRIGGERS.get(platform)


def _find_button_by_element_map(doc, element_key: str, platform: str) -> Optional[Dict]:
    """Find a button defined in element_map by scanning AT-SPI tree."""
    spec = get_element_spec(platform, element_key)
    if not spec:
        return None

    config = get_platform_config(platform)
    fences = config.get('fence_after', [])
    elements = find_elements(doc, fence_after=fences)

    # Import inspect's matching logic
    from tools.inspect import _match_element

    for e in elements:
        if _match_element(e, spec):
            return e
    return None


def _find_model_buttons_in_tree(platform: str, target_mode: str,
                                 elements: list) -> list:
    """Find model/mode buttons directly in the AT-SPI tree.

    ChatGPT model items (model_auto, model_instant, etc.) are now
    regular push buttons visible in the AT-SPI tree, not menu items.
    """
    config = get_platform_config(platform)
    emap = config.get('element_map', {})

    # Look for element_map keys that start with 'model_' or 'mode_' or 'tool_'
    candidates = []
    for key, spec in emap.items():
        if not isinstance(spec, dict):
            continue
        if key.startswith(('model_', 'mode_', 'tool_', 'thinking_')):
            from tools.inspect import _match_element
            for e in elements:
                if _match_element(e, spec):
                    candidates.append(e)
                    break

    return candidates


def _click_element(element: Dict, platform: str) -> bool:
    """Click an element using the platform's click_strategy."""
    from core.interact import atspi_click
    strategy = get_click_strategy(platform)

    if strategy == 'atspi_first':
        if atspi_click(element):
            return True
        x, y = int(element.get('x', 0)), int(element.get('y', 0))
        if x > 0 and y > 0:
            return inp.click_at(x, y)
        return False
    else:  # xdotool_first
        x, y = int(element.get('x', 0)), int(element.get('y', 0))
        if x > 0 and y > 0 and inp.click_at(x, y):
            return True
        return atspi_click(element)


def _match_and_click(items: list, mode_key: str, platform: str) -> Dict:
    """Find matching item by name and click it."""
    from core.interact import atspi_click

    mode_key_lower = mode_key.lower().strip()

    # Build search terms including common aliases
    search_terms = [mode_key_lower]
    _ALIASES = {
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
        'auto': ['auto'],
        'instant': ['instant'],
    }
    search_terms.extend(_ALIASES.get(mode_key_lower, []))

    for item in items:
        item_name = (item.get('name') or '').strip().lower()
        if not item_name:
            continue

        for term in search_terms:
            if term in item_name or item_name.startswith(term):
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
    available = [item.get('name', '') for item in items if item.get('name')]
    return {
        'success': False,
        'error': f"No menu item matched '{mode_key}' in {platform}",
        'available_items': available[:10],
    }


def _verify_selection(platform: str, mode_key: str,
                       firefox, doc) -> Dict:
    """Verify selection took effect by re-reading the AT-SPI tree."""
    time.sleep(0.5)

    validation = get_validation(platform)
    model_val = validation.get('model_selected', {})

    if not model_val:
        return {'verified': False, 'note': 'No validation config for this platform'}

    # Re-scan tree
    config = get_platform_config(platform)
    fences = config.get('fence_after', [])

    try:
        # Re-get doc for fresh state
        doc = atspi.get_platform_document(firefox, platform) or doc
        elements = find_elements(doc, fence_after=fences)
    except Exception as e:
        return {'verified': False, 'note': f'Tree rescan failed: {e}'}

    # Read from the specified element
    read_from = model_val.get('read_from')
    if not read_from:
        return {'verified': False, 'note': 'No read_from in validation config'}

    spec = get_element_spec(platform, read_from)
    if not spec:
        return {'verified': False, 'note': f'Element spec {read_from} not found'}

    from tools.inspect import _match_element

    for e in elements:
        if _match_element(e, spec):
            button_name = (e.get('name') or '').lower()
            mode_lower = mode_key.lower()

            # Check if button name contains the mode/model key
            _VERIFY_TERMS = {
                'auto': ['auto'],
                'instant': ['instant'],
                'thinking': ['thinking'],
                'pro': ['pro'],
                'expert': ['expert'],
                'heavy': ['heavy'],
                'fast': ['fast'],
                'deep_think': ['deep think'],
                'deep_research': ['deep research'],
                'extended_thinking': ['extended'],
            }
            terms = _VERIFY_TERMS.get(mode_lower, [mode_lower])
            if any(t in button_name for t in terms):
                return {'verified': True, 'button_name': e.get('name', '')}

            # If reopen_to_verify is set (Grok), we can't easily verify
            if model_val.get('reopen_to_verify'):
                return {'verified': False, 'note': 'Platform requires reopening dropdown to verify (skipped)'}

            return {
                'verified': False,
                'note': f"Button name '{e.get('name')}' doesn't contain '{mode_key}'",
                'button_name': e.get('name', ''),
            }

    return {'verified': False, 'note': f'Element {read_from} not found in tree after selection'}
