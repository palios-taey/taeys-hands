#!/usr/bin/env python3
"""Live AT-SPI element discovery test across platforms.

Tests that Taey's Hands can discover, map, and interact with
elements on ChatGPT, Gemini, Grok, and Perplexity without login.

Run: source /tmp/atspi_env.sh && python3 tests/test_live_atspi.py
"""
import json
import os
import sys
import time
import subprocess
import yaml

# Ensure correct paths
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

os.environ.setdefault('DISPLAY', ':99')

# Load AT-SPI env
if os.path.exists('/tmp/atspi_env.sh'):
    with open('/tmp/atspi_env.sh') as f:
        for line in f:
            if line.startswith('export '):
                key, _, val = line.strip().replace('export ', '', 1).partition('=')
                val = val.strip("'\"")
                os.environ[key] = val

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

from core import atspi as atspi_mod
from core import input as inp
from core.tree import find_elements, detect_chrome_y
from core.platforms import CHAT_PLATFORMS, URL_PATTERNS

# Test URLs that don't require login
PLATFORM_URLS = {
    'chatgpt': 'https://chatgpt.com/?temporary-chat=true',
    'gemini': 'https://gemini.google.com/',
    'grok': 'https://grok.com/',
    'perplexity': 'https://www.perplexity.ai/',
}

RESULTS = {}


def get_firefox_app():
    """Find Firefox in AT-SPI tree."""
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app and 'firefox' in (app.get_name() or '').lower():
            return app
    return None


def navigate_to(url: str, wait: int = 8):
    """Navigate Firefox to URL via Ctrl+L."""
    inp.press_key('ctrl+l')
    time.sleep(0.5)
    inp.press_key('ctrl+a')
    time.sleep(0.1)
    inp.type_text(url, delay_ms=5)
    time.sleep(0.3)
    inp.press_key('Return')
    time.sleep(wait)


def walk_tree(node, depth=0, max_depth=8, elements=None):
    """Walk AT-SPI tree and collect elements."""
    if elements is None:
        elements = []
    if depth > max_depth:
        return elements
    
    try:
        name = node.get_name() or ''
        role = node.get_role_name() or ''
        
        # Get position
        try:
            comp = node.get_component_iface()
            if comp:
                rect = comp.get_extents(Atspi.CoordType.SCREEN)
                x, y, w, h = rect.x, rect.y, rect.width, rect.height
            else:
                x = y = w = h = 0
        except:
            x = y = w = h = 0
        
        if name or role in ('push button', 'entry', 'text', 'menu item', 'toggle button'):
            elements.append({
                'name': name,
                'role': role,
                'depth': depth,
                'x': x, 'y': y, 'w': w, 'h': h,
            })
        
        count = node.get_child_count()
        for i in range(count):
            try:
                child = node.get_child_at_index(i)
                if child:
                    walk_tree(child, depth + 1, max_depth, elements)
            except:
                pass
    except:
        pass
    
    return elements


def load_yaml_config(platform: str) -> dict:
    """Load platform YAML config."""
    config_path = os.path.join(_ROOT, 'platforms', f'{platform}.yaml')
    if os.path.exists(config_path):
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def check_platform(platform: str) -> dict:
    """Test AT-SPI element discovery on a platform."""
    result = {
        'platform': platform,
        'url': PLATFORM_URLS[platform],
        'status': 'unknown',
        'elements_found': 0,
        'known_elements': [],
        'unknown_elements': [],
        'input_field': None,
        'attach_button': None,
        'send_button': None,
        'errors': [],
    }
    
    print(f"\n{'='*60}")
    print(f"  Testing: {platform.upper()}")
    print(f"{'='*60}")
    
    # Navigate
    print(f"  Navigating to {PLATFORM_URLS[platform]}...")
    navigate_to(PLATFORM_URLS[platform], wait=10)
    
    # Get Firefox document
    firefox = get_firefox_app()
    if not firefox:
        result['status'] = 'FAIL'
        result['errors'].append('Firefox not found in AT-SPI tree')
        return result
    
    # Walk the tree
    print("  Walking AT-SPI tree...")
    try:
        # Get document frame
        frame = None
        for i in range(firefox.get_child_count()):
            child = firefox.get_child_at_index(i)
            if child and child.get_role_name() == 'frame':
                frame = child
                break
        
        if not frame:
            result['errors'].append('No frame found')
            result['status'] = 'WARN'
        else:
            elements = walk_tree(frame, max_depth=10)
            result['elements_found'] = len(elements)
            print(f"  Found {len(elements)} elements")
    except Exception as e:
        result['errors'].append(f'Tree walk error: {e}')
        elements = []
    
    # Load YAML config for this platform
    config = load_yaml_config(platform)
    element_map = config.get('element_map', {})
    exclude_patterns = config.get('exclude_patterns', [])
    
    # Match elements against YAML
    for elem in elements:
        name = (elem.get('name') or '').lower()
        role = elem.get('role', '')
        
        # Check if it's a known element from YAML
        matched = False
        for yaml_name, yaml_info in element_map.items():
            if yaml_name.lower() in name or name in yaml_name.lower():
                result['known_elements'].append({
                    'name': elem['name'],
                    'role': role,
                    'yaml_key': yaml_name,
                })
                matched = True
                break
        
        if not matched and name and not any(p.lower() in name for p in (exclude_patterns or [])):
            result['unknown_elements'].append({
                'name': elem['name'][:80],
                'role': role,
            })
        
        # Identify key elements
        if 'entry' in role or ('text' in role and ('message' in name or 'prompt' in name or 'ask' in name)):
            result['input_field'] = {'name': elem['name'][:60], 'role': role, 'x': elem['x'], 'y': elem['y']}
        
        if ('attach' in name or 'upload' in name or 'add files' in name) and 'button' in role:
            result['attach_button'] = {'name': elem['name'][:60], 'role': role}
        
        if ('send' in name or 'submit' in name) and 'button' in role:
            result['send_button'] = {'name': elem['name'][:60], 'role': role}
    
    # Determine status
    if result['input_field'] or result['elements_found'] > 10:
        result['status'] = 'OK'
    elif result['elements_found'] > 0:
        result['status'] = 'PARTIAL'
    else:
        result['status'] = 'FAIL'
    
    # Print summary
    print(f"  Status: {result['status']}")
    print(f"  Elements: {result['elements_found']} total, {len(result['known_elements'])} known, {len(result['unknown_elements'])} unknown")
    print(f"  Input field: {result['input_field']}")
    print(f"  Attach button: {result['attach_button']}")
    print(f"  Send button: {result['send_button']}")
    if result['errors']:
        print(f"  Errors: {result['errors']}")
    
    return result


def check_orchestrator_connectivity():
    """Test ISMA/Orchestrator API connectivity."""
    import urllib.request
    
    print(f"\n{'='*60}")
    print("  Testing API Connectivity")
    print(f"{'='*60}")
    
    results = {}
    
    # Test ISMA
    try:
        req = urllib.request.Request(
            'https://isma-api.taey.ai/health',
            headers={'X-API-Key': 'i-_6xNSFMyYc2Zs8_VFVVw_X-rdjvBnGzALNWVaUAOI'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            results['isma'] = {'status': 'OK', 'code': resp.status}
            print(f"  ISMA: OK ({resp.status})")
    except Exception as e:
        results['isma'] = {'status': 'FAIL', 'error': str(e)}
        print(f"  ISMA: FAIL ({e})")
    
    # Test Orchestrator
    try:
        req = urllib.request.Request(
            'https://orch-api.taey.ai/health',
            headers={'X-API-Key': 'xXzgL-sIMEYI-JNABd-wcsMOyiSHPQUXRUOZq9ZBZZM'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            results['orchestrator'] = {'status': 'OK', 'code': resp.status}
            print(f"  Orchestrator: OK ({resp.status})")
    except Exception as e:
        results['orchestrator'] = {'status': 'FAIL', 'error': str(e)}
        print(f"  Orchestrator: FAIL ({e})")
    
    # Test ISMA search endpoint
    try:
        import urllib.parse
        params = urllib.parse.urlencode({'q': 'test', 'scale': 'full_4096', 'limit': 1})
        req = urllib.request.Request(
            f'https://isma-api.taey.ai/search?{params}',
            headers={'X-API-Key': 'i-_6xNSFMyYc2Zs8_VFVVw_X-rdjvBnGzALNWVaUAOI'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            results['isma_search'] = {'status': 'OK', 'results': len(data.get('results', data.get('tiles', [])))}
            print(f"  ISMA Search: OK ({results['isma_search']['results']} results)")
    except Exception as e:
        results['isma_search'] = {'status': 'FAIL', 'error': str(e)}
        print(f"  ISMA Search: FAIL ({e})")
    
    return results


def main():
    print("\n" + "=" * 60)
    print("  TAEY'S HANDS — Live AT-SPI Test Suite")
    print("=" * 60)
    
    # Verify AT-SPI
    desktop = Atspi.get_desktop(0)
    child_count = desktop.get_child_count()
    print(f"\nAT-SPI Desktop: {child_count} children")
    for i in range(child_count):
        app = desktop.get_child_at_index(i)
        if app:
            print(f"  [{i}] {app.get_name()} ({app.get_role_name()})")
    
    if child_count == 0:
        print("\nFATAL: No AT-SPI applications found. Firefox not connected to accessibility bus.")
        sys.exit(1)
    
    # Test each platform
    for platform in ['chatgpt', 'gemini', 'grok', 'perplexity']:
        try:
            RESULTS[platform] = check_platform(platform)
        except Exception as e:
            RESULTS[platform] = {
                'platform': platform,
                'status': 'ERROR',
                'error': str(e),
            }
            print(f"  ERROR: {e}")
    
    # Test API connectivity
    api_results = check_orchestrator_connectivity()
    RESULTS['api'] = api_results
    
    # Final summary
    print(f"\n{'='*60}")
    print("  FINAL RESULTS")
    print(f"{'='*60}")
    for platform in ['chatgpt', 'gemini', 'grok', 'perplexity']:
        r = RESULTS.get(platform, {})
        status = r.get('status', 'UNKNOWN')
        elements = r.get('elements_found', 0)
        inp_field = 'YES' if r.get('input_field') else 'NO'
        attach = 'YES' if r.get('attach_button') else 'NO'
        print(f"  {platform:12s} | {status:8s} | {elements:4d} elements | input={inp_field} attach={attach}")
    
    for api_name, api_r in api_results.items():
        print(f"  {api_name:12s} | {api_r.get('status', 'UNKNOWN'):8s}")
    
    # Save results
    results_path = os.path.join(_ROOT, 'tests', 'live_atspi_results.json')
    with open(results_path, 'w') as f:
        json.dump(RESULTS, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")
    
    # Exit code based on results
    failures = sum(1 for p in ['chatgpt', 'gemini', 'grok', 'perplexity'] 
                   if RESULTS.get(p, {}).get('status') in ('FAIL', 'ERROR'))
    if failures > 0:
        print(f"\n{failures} platform(s) failed")
        sys.exit(1)
    else:
        print("\nAll platforms accessible")
        sys.exit(0)


if __name__ == '__main__':
    main()
