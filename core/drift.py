"""YAML Drift Detection — Detect platform UI changes via structure_hash.

After each successful cycle, computes a structural fingerprint of the UI.
At the start of each cycle, compares against the stored hash.
If changed → halt_platform() with old vs new element lists for diff analysis.

The element_filter in YAML already classifies elements:
  - element_map: known controls we interact with
  - exclude: noise, never show
  - sidebar_nav: known sidebar items
  - Anything else: flagged as NEW → YAML needs updating
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

import yaml

from core.tree import compute_structure_hash

logger = logging.getLogger(__name__)

PLATFORMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'platforms')

# Cache loaded YAML configs
_yaml_cache: Dict[str, dict] = {}


def _load_yaml(platform: str) -> dict:
    """Load and cache platform YAML."""
    if platform not in _yaml_cache:
        path = os.path.join(PLATFORMS_DIR, f'{platform}.yaml')
        with open(path) as f:
            _yaml_cache[platform] = yaml.safe_load(f) or {}
    return _yaml_cache[platform]


def _invalidate_yaml_cache(platform: str = None):
    """Clear YAML cache (after YAML update)."""
    if platform:
        _yaml_cache.pop(platform, None)
    else:
        _yaml_cache.clear()


def store_structure_hash(platform: str, elements: List[Dict],
                         redis_client) -> str:
    """Compute and store structure hash after successful cycle.
    Returns the hash.
    """
    hash_val = compute_structure_hash(elements)
    if redis_client:
        try:
            redis_client.set(f'taey:structure_hash:{platform}', hash_val)
            redis_client.set(
                f'taey:structure_hash:{platform}:elements',
                json.dumps(_summarize_elements(elements)),
            )
            redis_client.set(f'taey:structure_hash:{platform}:ts', str(time.time()))
        except Exception as e:
            logger.warning(f"Failed to store structure hash for {platform}: {e}")
    return hash_val


def check_structure_drift(platform: str, elements: List[Dict],
                          redis_client) -> Optional[dict]:
    """Compare current structure hash against stored.

    Returns None if no drift detected (or no baseline yet).
    Returns drift_data dict if drift detected:
      {
        'old_hash': '...',
        'new_hash': '...',
        'new_elements': [...],
        'unknown_elements': [...]  # elements not in YAML element_map/exclude
      }
    """
    if not redis_client:
        return None

    try:
        stored_hash = redis_client.get(f'taey:structure_hash:{platform}')
    except Exception:
        return None

    if not stored_hash:
        # No baseline — first run. Store and continue.
        store_structure_hash(platform, elements, redis_client)
        return None

    # Decode if bytes
    if isinstance(stored_hash, bytes):
        stored_hash = stored_hash.decode()

    current_hash = compute_structure_hash(elements)

    if current_hash == stored_hash:
        return None

    # Drift detected — build diff data
    logger.warning(f"[{platform}] Structure drift detected: {stored_hash} → {current_hash}")

    # Load old elements summary
    old_elements_raw = redis_client.get(f'taey:structure_hash:{platform}:elements')
    old_elements = []
    if old_elements_raw:
        try:
            if isinstance(old_elements_raw, bytes):
                old_elements_raw = old_elements_raw.decode()
            old_elements = json.loads(old_elements_raw)
        except Exception:
            pass

    # Find unknown elements (not in YAML element_map or exclude)
    unknown = classify_unknown_elements(platform, elements)

    return {
        'old_hash': stored_hash,
        'new_hash': current_hash,
        'old_element_count': len(old_elements),
        'new_element_count': len(elements),
        'unknown_elements': unknown,
        'timestamp': time.time(),
    }


def classify_unknown_elements(platform: str, elements: List[Dict]) -> List[Dict]:
    """Find elements that are NOT in YAML element_map, exclude, or sidebar_nav.

    These are NEW elements the platform added — they need to be classified
    and added to YAML.
    """
    try:
        config = _load_yaml(platform)
    except Exception:
        return []

    ef = config.get('element_filter', {})
    exclude = ef.get('exclude', {})
    element_map = config.get('element_map', {}) if 'element_map' not in ef else ef.get('element_map', {})
    # element_map is at top level in our YAMLs
    element_map = config.get('element_map', {})
    sidebar_nav = config.get('sidebar_nav', [])

    # Build sets of known names and roles
    exclude_names = set(n.lower() for n in exclude.get('names', []))
    exclude_contains = [s.lower() for s in exclude.get('name_contains', [])]
    exclude_roles = set(r.lower() for r in exclude.get('roles', []))

    known_element_names = set()
    known_element_patterns = []
    for key, spec in element_map.items():
        if 'name' in spec:
            known_element_names.add(spec['name'].lower())
        if 'name_contains' in spec:
            nc = spec['name_contains']
            if isinstance(nc, list):
                for n in nc:
                    known_element_patterns.append(n.lower())
            else:
                known_element_patterns.append(str(nc).lower())
        if 'name_pattern' in spec:
            # Simple glob — just check the static prefix
            pattern = spec['name_pattern'].lower()
            if '*' in pattern:
                prefix = pattern.split('*')[0]
                if prefix:
                    known_element_patterns.append(prefix)

    sidebar_names = set()
    for item in sidebar_nav:
        if 'name' in item:
            sidebar_names.add(item['name'].lower())
        if 'name_pattern' in item:
            pattern = item['name_pattern'].lower()
            if '*' in pattern:
                prefix = pattern.split('*')[0]
                if prefix:
                    known_element_patterns.append(prefix)

    unknown = []
    for e in elements:
        name = (e.get('name') or '').strip()
        role = (e.get('role') or '').strip()
        name_lower = name.lower()

        if not name or not role:
            continue

        # Skip excluded
        if name_lower in exclude_names:
            continue
        if role.lower() in exclude_roles:
            continue
        if any(c in name_lower for c in exclude_contains):
            continue

        # Skip known element_map entries
        if name_lower in known_element_names:
            continue
        if any(p in name_lower for p in known_element_patterns):
            continue

        # Skip known sidebar nav
        if name_lower in sidebar_names:
            continue

        # This element is unknown
        unknown.append({
            'name': name,
            'role': role,
            'x': e.get('x'),
            'y': e.get('y'),
            'states': e.get('states', []),
        })

    return unknown


def _summarize_elements(elements: List[Dict]) -> List[Dict]:
    """Create a serializable summary of elements (no atspi_obj)."""
    return [
        {
            'name': (e.get('name') or '')[:100],
            'role': e.get('role', ''),
            'x': e.get('x'),
            'y': e.get('y'),
        }
        for e in elements
        if e.get('role') and e.get('name')
    ]
