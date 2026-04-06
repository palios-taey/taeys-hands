from __future__ import annotations

import fnmatch
from typing import Any, Dict, Iterable, List, Tuple

from core import atspi
from core.tree import find_elements, find_menu_items

from .types import ElementRef, Snapshot
from .yaml_contract import load_platform_yaml


_MENU_ROLES = {'menu item', 'radio menu item', 'check menu item', 'list item', 'option'}


def _listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def matches_spec(element: Dict[str, Any] | ElementRef, spec: Dict[str, Any]) -> bool:
    if not spec:
        return False
    name = ((element.name if isinstance(element, ElementRef) else element.get('name')) or '').strip()
    role = (element.role if isinstance(element, ElementRef) else element.get('role')) or ''
    states = set(s.lower() for s in ((element.states if isinstance(element, ElementRef) else element.get('states')) or []))
    name_lower = name.lower()
    role_lower = role.lower()

    if 'name' in spec and name_lower != str(spec['name']).strip().lower():
        return False
    if 'name_contains' in spec:
        probes = [str(item).lower() for item in _listify(spec['name_contains'])]
        if not any(probe in name_lower for probe in probes):
            return False
    if 'name_pattern' in spec:
        patterns = [str(item).lower() for item in _listify(spec['name_pattern'])]
        if not any(fnmatch.fnmatch(name_lower, pattern) for pattern in patterns):
            return False
    if 'role' in spec and role_lower != str(spec['role']).strip().lower():
        return False
    if 'role_contains' in spec:
        probes = [str(item).lower() for item in _listify(spec['role_contains'])]
        if not any(probe in role_lower for probe in probes):
            return False
    if 'states_include' in spec:
        needed = {str(item).lower() for item in _listify(spec['states_include'])}
        if not needed.issubset(states):
            return False
    return True


def _is_excluded(element: Dict[str, Any], tree_cfg: Dict[str, Any]) -> bool:
    exclude = dict(tree_cfg.get('exclude', {}))
    name = (element.get('name') or '').strip()
    role = (element.get('role') or '').strip()
    name_lower = name.lower()
    role_lower = role.lower()

    if name and name in set(_listify(exclude.get('names'))):
        return True
    if role and role_lower in {str(item).lower() for item in _listify(exclude.get('roles'))}:
        return True
    for probe in [str(item).lower() for item in _listify(exclude.get('name_contains'))]:
        if probe and probe in name_lower:
            return True
    return False


def _to_ref(key: str | None, element: Dict[str, Any]) -> ElementRef:
    return ElementRef(
        key=key,
        name=(element.get('name') or '').strip(),
        role=(element.get('role') or '').strip(),
        x=element.get('x'),
        y=element.get('y'),
        states=list(element.get('states') or []),
        text=element.get('text'),
        description=element.get('description'),
        atspi_obj=element.get('atspi_obj'),
        raw=dict(element),
    )


def _classify_elements(platform: str, elements: Iterable[Dict[str, Any]], menu_items: List[Dict[str, Any]] | None = None) -> Snapshot:
    cfg = load_platform_yaml(platform)
    tree_cfg = dict(cfg.get('tree') or {})
    element_map = dict(tree_cfg.get('element_map') or {})
    sidebar_nav = _listify(tree_cfg.get('sidebar_nav'))
    snapshot = Snapshot(platform=platform, url=None, raw_count=0)
    mapped: Dict[str, List[ElementRef]] = {key: [] for key in element_map}
    unknown: List[ElementRef] = []
    sidebar: List[ElementRef] = []

    for element in elements:
        snapshot.raw_count += 1
        if _is_excluded(element, tree_cfg):
            continue
        matched = False
        for key, spec in element_map.items():
            if matches_spec(element, spec):
                mapped.setdefault(key, []).append(_to_ref(key, element))
                matched = True
        if matched:
            continue
        if any(matches_spec(element, spec) for spec in sidebar_nav if isinstance(spec, dict)):
            sidebar.append(_to_ref(None, element))
            continue
        unknown.append(_to_ref(None, element))

    snapshot.mapped = mapped
    snapshot.unknown = unknown
    snapshot.sidebar = sidebar
    if menu_items:
        snapshot.menu_items = [_to_ref(None, item) for item in menu_items]
    return snapshot


def build_snapshot(platform: str, scan_root: str = 'auto') -> Tuple[Any, Any, Snapshot]:
    """Build AT-SPI snapshot.

    scan_root controls where to scan:
      'auto' — scan from document (default, most platforms)
      'app'  — scan from Firefox app root (needed for React portals like ChatGPT model dropdown)
    """
    cfg = load_platform_yaml(platform)
    tree_cfg = dict(cfg.get('tree') or {})
    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        raise RuntimeError(f'Firefox not found for {platform}')
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        # Document not found — page may have navigated (e.g., Perplexity Deep Research toggle).
        # Fall back to scanning from Firefox app root.
        scan_root = 'app'
    url = atspi.get_document_url(doc) if doc else None

    # Some platforms (ChatGPT) have elements outside the document (React portals).
    # fence_after: [] means "no fence" — scan full app tree to catch portals.
    # Other platforms use fence_after to cut sidebar — scan from doc only.
    fence = tree_cfg.get('fence_after') or []
    if scan_root == 'app' or (scan_root == 'auto' and not fence):
        scope = firefox
    else:
        scope = doc
    elements = find_elements(scope, fence_after=tree_cfg.get('fence_after') or [])
    snapshot = _classify_elements(platform, elements)
    snapshot.url = url
    return firefox, doc, snapshot


def build_menu_snapshot(platform: str) -> Tuple[Any, Any, Snapshot]:
    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        raise RuntimeError(f'Firefox not found for {platform}')
    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        raise RuntimeError(f'Document not found for {platform}')
    try:
        firefox.clear_cache_single()
    except Exception:
        pass
    try:
        doc.clear_cache_single()
    except Exception:
        pass

    menu = find_menu_items(firefox, doc)
    if not menu:
        elements = find_elements(doc)
        menu = [element for element in elements if (element.get('role') or '').strip().lower() in _MENU_ROLES and (element.get('name') or '').strip()]
        menu.sort(key=lambda item: (item.get('y') or 0, item.get('x') or 0))
    snapshot = _classify_elements(platform, menu, menu_items=menu)
    snapshot.url = atspi.get_document_url(doc)
    return firefox, doc, snapshot
