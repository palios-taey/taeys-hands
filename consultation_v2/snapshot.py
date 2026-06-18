from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from consultation_v2 import atspi
from consultation_v2.tree import find_elements, find_menu_items

from .types import ElementRef, Snapshot
from .yaml_contract import load_platform_yaml


_MENU_ROLES = {'menu item', 'radio menu item', 'check menu item', 'list item', 'option'}
_FORBIDDEN_MATCHER_KEYS = {
    'name_contains',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'name_not_contains',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'name_contains_all',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'name_pattern',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'role_contains',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'url_contains',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'title_contains',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'contains',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'regex',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'matches',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'fuzzy',  # lint-allow: exact-only matcher rejects legacy matcher grammar
    'substring',
}

# Firefox browser-chrome container roles. When build_snapshot scans from the app
# root (ChatGPT portals / doc-not-found fallback), these subtrees are the nav
# toolbar, menu bar, and tab strip — never page content (which lives under the
# content panel/document). Pruning their subtrees keeps UNKNOWN to real page
# elements. NOTE: 'menu'/'radio menu item' are deliberately NOT here — React
# portal dropdowns use them and are read via build_menu_snapshot (which does not
# prune), so portals are never affected by this.
_CHROME_SUBTREE_ROLES = ['tool bar', 'menu bar', 'page tab list']


def _listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _element_raw(element: Dict[str, Any] | ElementRef) -> Dict[str, Any]:
    return element.raw if isinstance(element, ElementRef) else element


def _element_attributes(element: Dict[str, Any] | ElementRef) -> Dict[str, Any]:
    raw = _element_raw(element)
    attributes = raw.get('attributes') or {}
    return attributes if isinstance(attributes, dict) else {}


def _reject_forbidden_matcher_keys(spec: Dict[str, Any]) -> None:
    found = sorted(key for key in spec if key in _FORBIDDEN_MATCHER_KEYS)
    if found:
        raise ValueError(f'Forbidden consultation_v2 matcher key(s): {found}')


def matches_spec(element: Dict[str, Any] | ElementRef, spec: Dict[str, Any]) -> bool:
    if not spec:
        return False
    _reject_forbidden_matcher_keys(spec)
    # A `structural:` locator (YAML_SCHEMA §2) matches by POSITION (exact role +
    # exact parent key + index/ordinal), which the flat element matcher cannot
    # evaluate. It is resolved by the per-platform driver against the parent's
    # subtree — never by this name/role pass. So a structural-only spec must NOT
    # positively match arbitrary elements here (that would pollute classification).
    if 'structural' in spec:
        return False
    name = (element.name if isinstance(element, ElementRef) else element.get('name')) or ''
    role = (element.role if isinstance(element, ElementRef) else element.get('role')) or ''
    states = set(s.lower() for s in ((element.states if isinstance(element, ElementRef) else element.get('states')) or []))

    if not any(key in spec for key in ('name', 'names_any_of', 'role', 'states_include', 'attributes', 'testid')):
        return False
    if 'name' in spec and name != str(spec['name']):
        return False
    if 'names_any_of' in spec:
        candidates = spec['names_any_of']
        if not isinstance(candidates, list):
            raise ValueError('names_any_of must be a list of exact labels')
        if not any(name == str(candidate) for candidate in candidates):
            return False
    if 'role' in spec and role != str(spec['role']):
        return False
    if 'states_include' in spec:
        needed = {str(item).lower() for item in _listify(spec['states_include'])}
        if not needed.issubset(states):
            return False
    if 'attributes' in spec:
        expected = spec['attributes']
        if not isinstance(expected, dict):
            raise ValueError('attributes matcher must be an exact key/value mapping')
        attrs = _element_attributes(element)
        if any(str(attrs.get(key, '')) != str(value) for key, value in expected.items()):
            return False
    if 'testid' in spec:
        raw = _element_raw(element)
        attrs = _element_attributes(element)
        expected = str(spec['testid'])
        candidates = [
            raw.get('testid'),
            raw.get('data-testid'),
            attrs.get('testid'),
            attrs.get('data-testid'),
        ]
        if not any(str(candidate) == expected for candidate in candidates if candidate is not None):
            return False
    return True


def _is_excluded(element: Dict[str, Any], tree_cfg: Dict[str, Any]) -> bool:
    exclude = dict(tree_cfg.get('exclude', {}))
    name = (element.get('name') or '').strip()
    role = (element.get('role') or '').strip()
    role_lower = role.lower()

    if name and name in set(_listify(exclude.get('names'))):
        return True
    if role and role_lower in {str(item).lower() for item in _listify(exclude.get('roles'))}:
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
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi as _Atspi
        desktop = _Atspi.get_desktop(0)
        desktop.clear_cache_single()
    except Exception:
        pass
    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        raise RuntimeError(f'Firefox not found for {platform}')
    try:
        firefox.clear_cache_single()
    except Exception:
        pass
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
        # App-root scope walks the whole Firefox frame, which includes the
        # browser chrome (nav/tab/menu bars) — prune those container subtrees
        # so UNKNOWN holds only real page elements + React portals. When scoped
        # to the document instead, there is no chrome to prune.
        prune_roles = _CHROME_SUBTREE_ROLES
    else:
        scope = doc
        prune_roles = None
    elements = find_elements(
        scope,
        fence_after=tree_cfg.get('fence_after') or [],
        prune_subtree_roles=prune_roles,
    )
    snapshot = _classify_elements(platform, elements)
    snapshot.url = url
    return firefox, doc, snapshot


def build_menu_snapshot(platform: str) -> Tuple[Any, Any, Snapshot]:
    # Clear desktop cache to discover new portal documents that appeared
    # since the last scan (dropdowns, overlays, file dialogs).
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi as _Atspi
        desktop = _Atspi.get_desktop(0)
        desktop.clear_cache_single()
    except Exception:
        pass
    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        raise RuntimeError(f'Firefox not found for {platform}')
    doc = atspi.get_platform_document(firefox, platform)
    # NOTE: doc may be None if a portal/dropdown opened during navigation.
    # Do NOT raise here — fall back gracefully; find_menu_items and find_elements
    # will use firefox (app root) which covers React portals outside the document.
    try:
        firefox.clear_cache_single()
    except Exception:
        pass
    if doc is not None:
        try:
            doc.clear_cache_single()
        except Exception:
            pass

    menu = find_menu_items(firefox, doc)

    # ALWAYS supplement with find_elements(firefox) — find_menu_items may return
    # only partial results (e.g., on Claude it finds 9 file/connector items but
    # misses Opus/Sonnet/Extended-thinking items that live in separate containers).
    # Since find_menu_items returns non-empty, the old fallback never fired and
    # those items were silently dropped. Now we always merge both sources.
    elements = find_elements(firefox)
    _EXTRA_ROLES = _MENU_ROLES | {'entry', 'push button', 'toggle button'}
    extra = [e for e in elements if (e.get('role') or '').strip().lower() in _EXTRA_ROLES and (e.get('name') or '').strip()]
    # Dedupe by (name, role) — preserve original menu order first, then append new items.
    seen = {(m.get('name', ''), m.get('role', '')) for m in menu}
    for e in extra:
        key = (e.get('name', ''), e.get('role', ''))
        if key not in seen:
            menu.append(e)
            seen.add(key)

    menu.sort(key=lambda item: (item.get('y') or 0, item.get('x') or 0))
    snapshot = _classify_elements(platform, menu, menu_items=menu)
    snapshot.url = atspi.get_document_url(doc) if doc is not None else None
    return firefox, doc, snapshot
