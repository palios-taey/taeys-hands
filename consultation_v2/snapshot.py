from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml

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

_FIREFOX_CHROME_YAML = Path(__file__).resolve().parent / 'firefox_chrome.yaml'


def _listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


@lru_cache(maxsize=1)
def _load_firefox_chrome_filter() -> Dict[str, Any]:
    source = _FIREFOX_CHROME_YAML.read_text()
    data = yaml.safe_load(source) or {}
    if not isinstance(data, dict):
        raise ValueError(f'{_FIREFOX_CHROME_YAML.name} top-level YAML node must be a mapping')
    chrome = data.get('firefox_chrome') or data
    if not isinstance(chrome, dict):
        raise ValueError(f'{_FIREFOX_CHROME_YAML.name} firefox_chrome must be a mapping')
    for key in ('subtree_roles', 'exact_elements', 'portal_container_roles'):
        value = chrome.get(key) or []
        if not isinstance(value, list):
            raise ValueError(f'{_FIREFOX_CHROME_YAML.name} {key} must be a list')
    for spec in chrome.get('exact_elements') or []:
        if not isinstance(spec, dict):
            raise ValueError(f'{_FIREFOX_CHROME_YAML.name} exact_elements entries must be mappings')
        _reject_forbidden_matcher_keys(spec)
    return chrome


def _role_set(values: Iterable[Any]) -> Set[str]:
    return {str(item).strip().lower() for item in values if str(item).strip()}


def _subtree_prune_specs(tree_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    specs = tree_cfg.get('prune_subtrees') or []
    if isinstance(specs, dict):
        specs = [specs]
    if not isinstance(specs, list):
        raise ValueError('tree.prune_subtrees must be a list of exact structural specs')
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError('tree.prune_subtrees entries must be mappings')
        _reject_forbidden_matcher_keys(spec)
        ancestor = spec.get('ancestor')
        if ancestor is not None:
            if not isinstance(ancestor, dict):
                raise ValueError('tree.prune_subtrees ancestor must be a mapping')
            _reject_forbidden_matcher_keys(ancestor)
    return [dict(spec) for spec in specs]


def _element_raw(element: Dict[str, Any] | ElementRef) -> Dict[str, Any]:
    return element.raw if isinstance(element, ElementRef) else element


def _element_attributes(element: Dict[str, Any] | ElementRef) -> Dict[str, Any]:
    raw = _element_raw(element)
    attributes = raw.get('attributes') or {}
    return attributes if isinstance(attributes, dict) else {}


def _element_identity(element: Dict[str, Any]) -> Any:
    obj = element.get('atspi_obj')
    if obj is not None:
        return id(obj)
    return (
        element.get('name'),
        element.get('role'),
        element.get('x'),
        element.get('y'),
    )


def _atspi_ancestor_objects(obj: Any | None) -> List[Any]:
    ancestors: List[Any] = []
    current = obj
    for _ in range(50):
        if current is None:
            break
        try:
            parent = current.get_parent()
        except Exception:
            break
        if parent is None:
            break
        ancestors.append(parent)
        current = parent
    return ancestors


def _obj_matches_spec(obj: Any, spec: Dict[str, Any]) -> bool:
    try:
        element = {
            'name': obj.get_name() or '',
            'role': obj.get_role_name() or '',
            'atspi_obj': obj,
        }
    except Exception:
        return False
    return matches_spec(element, spec)


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


def _is_excluded(
    element: Dict[str, Any],
    tree_cfg: Dict[str, Any],
    chrome_cfg: Dict[str, Any] | None = None,
    structural_exclude_roots: List[tuple[Dict[str, Any], Any]] | None = None,
) -> bool:
    chrome = chrome_cfg or {}
    for spec in chrome.get('exact_elements') or []:
        if matches_spec(element, spec):
            return True

    exclude = dict(tree_cfg.get('exclude', {}))
    for spec, root in structural_exclude_roots or []:
        if _matches_structural_exclude(element, spec, root):
            return True

    name = (element.get('name') or '').strip()
    role = (element.get('role') or '').strip()
    role_lower = role.lower()

    if name and name in set(_listify(exclude.get('names'))):
        return True
    if role and role_lower in {str(item).lower() for item in _listify(exclude.get('roles'))}:
        return True
    return False


def _structural_exclude_specs(tree_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    exclude = dict(tree_cfg.get('exclude') or {})
    specs = exclude.get('structural') or []
    if isinstance(specs, dict):
        specs = [specs]
    if not isinstance(specs, list):
        raise ValueError('tree.exclude.structural must be a list of structural exclude specs')
    normalized: List[Dict[str, Any]] = []
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError('tree.exclude.structural entries must be mappings')
        _reject_forbidden_matcher_keys(spec)
        ancestor = spec.get('ancestor')
        if ancestor is not None:
            if not isinstance(ancestor, dict):
                raise ValueError('tree.exclude.structural ancestor must be a mapping')
            _reject_forbidden_matcher_keys(ancestor)
        normalized.append(dict(spec))
    return normalized


def _structural_exclude_roots(
    elements: Iterable[Dict[str, Any]],
    specs: List[Dict[str, Any]],
) -> List[tuple[Dict[str, Any], Any]]:
    roots: List[tuple[Dict[str, Any], Any]] = []
    for spec in specs:
        ancestor_spec = spec.get('ancestor')
        if not isinstance(ancestor_spec, dict):
            roots.append((spec, None))
            continue
        matches = [
            element.get('atspi_obj')
            for element in elements
            if element.get('atspi_obj') is not None and matches_spec(element, ancestor_spec)
        ]
        ordinal = str(spec.get('ancestor_ordinal') or '').strip().lower()
        index = spec.get('ancestor_index')
        if isinstance(index, int):
            selected = matches[index:index + 1] if 0 <= index < len(matches) else []
        elif ordinal == 'first':
            selected = matches[:1]
        elif ordinal == 'last':
            selected = matches[-1:]
        else:
            selected = matches
        for root in selected:
            roots.append((spec, root))
    return roots


def _matches_structural_exclude(
    element: Dict[str, Any],
    spec: Dict[str, Any],
    root: Any | None,
) -> bool:
    if 'role' in spec and (element.get('role') or '') != str(spec['role']):
        return False
    if 'name' in spec and (element.get('name') or '') != str(spec['name']):
        return False
    if 'names_any_of' in spec:
        candidates = spec['names_any_of']
        if not isinstance(candidates, list):
            raise ValueError('tree.exclude.structural names_any_of must be a list')
        if (element.get('name') or '') not in {str(candidate) for candidate in candidates}:
            return False
    min_child_count = spec.get('min_child_count')
    if min_child_count is not None:
        obj = element.get('atspi_obj')
        try:
            if obj is None or obj.get_child_count() < int(min_child_count):
                return False
        except Exception:
            return False
    ancestor_spec = spec.get('ancestor')
    if isinstance(ancestor_spec, dict):
        ancestors = _atspi_ancestor_objects(element.get('atspi_obj'))
        if root is not None:
            return any(ancestor == root for ancestor in ancestors)
        return any(_obj_matches_spec(ancestor, ancestor_spec) for ancestor in ancestors)
    return True


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


def _classify_elements(
    platform: str,
    elements: Iterable[Dict[str, Any]],
    menu_items: List[Dict[str, Any]] | None = None,
    chrome_cfg: Dict[str, Any] | None = None,
) -> Snapshot:
    cfg = load_platform_yaml(platform)
    tree_cfg = dict(cfg.get('tree') or {})
    element_map = dict(tree_cfg.get('element_map') or {})
    sidebar_nav = _listify(tree_cfg.get('sidebar_nav'))
    elements = list(elements)
    structural_excludes = _structural_exclude_roots(
        elements,
        _structural_exclude_specs(tree_cfg),
    )
    snapshot = Snapshot(platform=platform, url=None, raw_count=0)
    mapped: Dict[str, List[ElementRef]] = {key: [] for key in element_map}
    sidebar: List[ElementRef] = []
    exact_accounted: Set[Any] = set()
    sidebar_accounted: Set[Any] = set()
    candidates: List[Dict[str, Any]] = []

    for element in elements:
        snapshot.raw_count += 1
        if _is_excluded(
            element,
            tree_cfg,
            chrome_cfg=chrome_cfg,
            structural_exclude_roots=structural_excludes,
        ):
            continue
        matched = False
        for key, spec in element_map.items():
            if 'structural' in spec:
                continue
            if matches_spec(element, spec):
                mapped.setdefault(key, []).append(_to_ref(key, element))
                exact_accounted.add(_element_identity(element))
                matched = True
        if matched:
            continue
        if any(matches_spec(element, spec) for spec in sidebar_nav if isinstance(spec, dict)):
            sidebar.append(_to_ref(None, element))
            sidebar_accounted.add(_element_identity(element))
            continue
        candidates.append(element)

    structural_accounted = _resolve_structural_mappings(
        element_map,
        elements,
        mapped,
        exact_accounted | sidebar_accounted,
    )
    accounted = exact_accounted | sidebar_accounted | structural_accounted
    unknown = [
        _to_ref(None, element)
        for element in candidates
        if _element_identity(element) not in accounted
    ]

    snapshot.mapped = mapped
    snapshot.unknown = unknown
    snapshot.sidebar = sidebar
    if menu_items:
        snapshot.menu_items = [_to_ref(None, item) for item in menu_items]
    return snapshot


def _menu_snapshot_filtered(
    elements: Iterable[Dict[str, Any]],
    tree_cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    menu_exclude = tree_cfg.get('menu_snapshot_exclude') or {}
    names = menu_exclude.get('names') or []
    if isinstance(names, str):
        names = [names]
    excluded_names = {str(name).strip() for name in names if str(name).strip()}
    if not excluded_names:
        return list(elements)
    return [
        element for element in elements
        if (element.get('name') or '').strip() not in excluded_names
    ]


def _resolve_structural_mappings(
    element_map: Dict[str, Any],
    elements: List[Dict[str, Any]],
    mapped: Dict[str, List[ElementRef]],
    accounted: Set[Any],
) -> Set[Any]:
    structural_accounted: Set[Any] = set()
    for key, spec in element_map.items():
        structural = spec.get('structural') if isinstance(spec, dict) else None
        if not isinstance(structural, dict):
            continue
        if spec.get('match_strategy') == 'name_agnostic_structural':
            expected_role = str(spec.get('role') or '').strip()
            if not expected_role:
                continue
            needed_states = {str(item).lower() for item in _listify(spec.get('states_include'))}
            candidates = []
            for element in elements:
                identity = _element_identity(element)
                if identity in accounted or identity in structural_accounted:
                    continue
                if (element.get('role') or '') != expected_role:
                    continue
                states = {str(item).lower() for item in (element.get('states') or [])}
                if needed_states and not needed_states.issubset(states):
                    continue
                candidates.append(element)
            selected = _select_structural_between(candidates, structural, mapped)
            if selected is None:
                continue
            mapped.setdefault(key, []).append(_to_ref(key, selected))
            structural_accounted.add(_element_identity(selected))
            continue
        parent_key = structural.get('parent')
        if not isinstance(parent_key, str):
            continue
        parent_refs = mapped.get(parent_key) or []
        parent_objects = [ref.atspi_obj for ref in parent_refs if ref.atspi_obj is not None]
        if not parent_objects:
            continue
        expected_role = str(structural.get('role') or spec.get('role') or '').strip()
        if not expected_role:
            continue
        candidates = []
        for element in elements:
            identity = _element_identity(element)
            if identity in accounted or identity in structural_accounted:
                continue
            if (element.get('role') or '') != expected_role:
                continue
            if structural.get('name_must_be_nonempty') and not (element.get('name') or '').strip():
                continue
            obj = element.get('atspi_obj')
            ancestors = _atspi_ancestor_objects(obj)
            if not any(parent in ancestors for parent in parent_objects):
                continue
            candidates.append(element)
        candidates.sort(key=lambda item: (item.get('y') or 0, item.get('x') or 0))
        index = structural.get('index')
        ordinal = str(structural.get('ordinal') or '').strip().lower()
        selected = None
        if isinstance(index, int):
            if 0 <= index < len(candidates):
                selected = candidates[index]
        elif ordinal == 'last' and candidates:
            selected = candidates[-1]
        elif candidates:
            selected = candidates[0]
        if selected is None:
            continue
        mapped.setdefault(key, []).append(_to_ref(key, selected))
        structural_accounted.add(_element_identity(selected))
    return structural_accounted


def _position_key(item: Dict[str, Any] | ElementRef) -> tuple[int, int]:
    if isinstance(item, ElementRef):
        y = item.y
        x = item.x
    else:
        y = item.get('y')
        x = item.get('x')
    return (int(y) if y is not None else 0, int(x) if x is not None else 0)


def _anchor_ref(mapped: Dict[str, List[ElementRef]], key: Any, *, last: bool) -> ElementRef | None:
    if not isinstance(key, str):
        return None
    refs = mapped.get(key) or []
    if not refs:
        return None
    refs = sorted(refs, key=_position_key)
    return refs[-1] if last else refs[0]


def _select_structural_between(
    candidates: List[Dict[str, Any]],
    structural: Dict[str, Any],
    mapped: Dict[str, List[ElementRef]],
) -> Dict[str, Any] | None:
    if not candidates:
        return None
    after_ref = _anchor_ref(mapped, structural.get('after'), last=True)
    before_ref = _anchor_ref(mapped, structural.get('before'), last=False)
    after_pos = _position_key(after_ref) if after_ref is not None else None
    before_pos = _position_key(before_ref) if before_ref is not None else None

    bounded: List[Dict[str, Any]] = []
    for candidate in candidates:
        pos = _position_key(candidate)
        if after_pos is not None and pos <= after_pos:
            continue
        if before_pos is not None and pos >= before_pos:
            continue
        bounded.append(candidate)
    if not bounded:
        return None
    bounded.sort(key=_position_key)
    if after_pos is not None and before_pos is not None:
        midpoint_y = (after_pos[0] + before_pos[0]) / 2
        midpoint_x = (after_pos[1] + before_pos[1]) / 2
        return min(
            bounded,
            key=lambda item: (
                abs(_position_key(item)[1] - midpoint_x),
                abs(_position_key(item)[0] - midpoint_y),
            ),
        )
    if after_pos is not None:
        return bounded[0]
    if before_pos is not None:
        return bounded[-1]
    return None


def _element_extent_is_onscreen(obj: Any) -> bool:
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi as _Atspi
        comp = obj.get_component_iface()
        if comp is None:
            return False
        rect = comp.get_extents(_Atspi.CoordType.SCREEN)
        return bool(rect and rect.x >= 0 and rect.y >= 0 and rect.width > 0 and rect.height > 0)
    except Exception:
        return False


def _ancestor_set(obj: Any | None) -> Set[Any]:
    ancestors: Set[Any] = set()
    current = obj
    for _ in range(50):
        if current is None:
            break
        try:
            parent = current.get_parent()
        except Exception:
            break
        if parent is None:
            break
        ancestors.add(parent)
        current = parent
    return ancestors


def _external_portal_roots(firefox: Any, doc: Any | None, chrome_cfg: Dict[str, Any]) -> List[Any]:
    portal_roles = _role_set(chrome_cfg.get('portal_container_roles') or [])
    chrome_subtree_roles = _role_set(chrome_cfg.get('subtree_roles') or [])
    if not firefox or not doc or not portal_roles:
        return []
    doc_ancestors = _ancestor_set(doc)
    roots: List[Any] = []

    def walk(obj: Any, in_chrome: bool = False) -> None:
        try:
            role = (obj.get_role_name() or '').strip().lower()
            if obj == doc:
                return
            # Other document webs are background tabs, not React portal roots.
            if role == 'document web':
                return
            if in_chrome or role in chrome_subtree_roles:
                return
            if obj not in doc_ancestors and role in portal_roles and _element_extent_is_onscreen(obj):
                roots.append(obj)
                return
            for index in range(obj.get_child_count()):
                child = obj.get_child_at_index(index)
                if child is not None:
                    walk(child, False)
        except Exception:
            return

    walk(firefox)
    return roots


def _dedupe_elements(elements: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: Set[Any] = set()
    for element in elements:
        obj = element.get('atspi_obj')
        key = id(obj) if obj is not None else (
            element.get('name'),
            element.get('role'),
            element.get('x'),
            element.get('y'),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(element)
    return deduped


def build_snapshot(platform: str, scan_root: str = 'auto') -> Tuple[Any, Any, Snapshot]:
    """Build AT-SPI snapshot.

    scan_root controls where to scan:
      'auto' — scan from document (default, most platforms)
      'app'  — scan from Firefox app root (needed for React portals like ChatGPT model dropdown)
    """
    cfg = load_platform_yaml(platform)
    chrome_cfg = _load_firefox_chrome_filter()
    tree_cfg = dict(cfg.get('tree') or {})
    prune_subtree_specs = _subtree_prune_specs(tree_cfg)
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
        if doc is not None:
            elements = find_elements(
                doc,
                fence_after=tree_cfg.get('fence_after') or [],
                prune_subtree_specs=prune_subtree_specs,
            )
            for portal_root in _external_portal_roots(firefox, doc, chrome_cfg):
                elements.extend(find_elements(
                    portal_root,
                    fence_after=[],
                    prune_subtree_specs=prune_subtree_specs,
                ))
            elements = _dedupe_elements(elements)
        else:
            elements = find_elements(
                firefox,
                fence_after=tree_cfg.get('fence_after') or [],
                prune_subtree_roles=chrome_cfg.get('subtree_roles') or [],
                prune_subtree_specs=prune_subtree_specs,
            )
    else:
        elements = find_elements(
            doc,
            fence_after=tree_cfg.get('fence_after') or [],
            prune_subtree_specs=prune_subtree_specs,
        )
    snapshot = _classify_elements(platform, elements, chrome_cfg=chrome_cfg)
    snapshot.url = url
    return firefox, doc, snapshot


def build_menu_snapshot(platform: str) -> Tuple[Any, Any, Snapshot]:
    cfg = load_platform_yaml(platform)
    chrome_cfg = _load_firefox_chrome_filter()
    tree_cfg = dict(cfg.get('tree') or {})
    prune_subtree_specs = _subtree_prune_specs(tree_cfg)
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
    # NOTE: menu_snapshot is the post-click portal/dropdown scope. Keep the scan
    # rooted at Firefox, not the document, so React overlays outside the document
    # subtree are visible while browser chrome remains pruned below.
    try:
        firefox.clear_cache_single()
    except Exception:
        pass
    if doc is not None:
        try:
            doc.clear_cache_single()
        except Exception:
            pass

    menu_snapshot_roles = _role_set(tree_cfg.get('menu_snapshot_roles') or [])
    if tree_cfg.get('menu_snapshot_scan') == 'document_menu_roles':
        role_filter = menu_snapshot_roles or _role_set(
            ['menu item', 'radio menu item', 'check menu item', 'option']
        )
        scan_root = firefox
        elements = find_elements(
            scan_root,
            fence_after=[],
            prune_subtree_roles=chrome_cfg.get('subtree_roles') or [],
            prune_subtree_specs=prune_subtree_specs,
        )
        menu = [
            item for item in elements
            if (item.get('name') or '').strip()
            and (item.get('role') or '').strip().lower() in role_filter
        ]
        menu = _menu_snapshot_filtered(menu, tree_cfg)
        menu = _dedupe_elements(menu)
        menu.sort(key=lambda item: (item.get('y') or 0, item.get('x') or 0))
        snapshot = _classify_elements(platform, menu, menu_items=menu, chrome_cfg=chrome_cfg)
        snapshot.url = atspi.get_document_url(doc) if doc is not None else None
        return firefox, doc, snapshot

    menu = _menu_snapshot_filtered(
        find_menu_items(firefox, doc, allowed_roles=menu_snapshot_roles or None),
        tree_cfg,
    )

    # ALWAYS supplement with find_elements(firefox) — find_menu_items may return
    # only partial results (e.g., on Claude it finds 9 file/connector items but
    # misses Opus/Sonnet/Extended-thinking items that live in separate containers).
    # Since find_menu_items returns non-empty, the old fallback never fired and
    # those items were silently dropped. Now we always merge both sources.
    elements = find_elements(firefox)
    _EXTRA_ROLES = menu_snapshot_roles or (_MENU_ROLES | {'entry', 'push button', 'toggle button'})
    extra = [
        e for e in _menu_snapshot_filtered(elements, tree_cfg)
        if (e.get('role') or '').strip().lower() in _EXTRA_ROLES
        and (e.get('name') or '').strip()
    ]
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


def build_app_root_snapshot(
    platform: str, allowed_roles: Optional[Iterable[str]] = None
) -> Snapshot:
    """Scan the LIVE Firefox app-root with NO cache-clear and NO subtree pruning.

    For transient React-portal popovers that the normal ``menu_snapshot`` misses:
    its ``clear_cache_single()`` dismisses the popover before the scan (observed
    on Gemini Deep Research "Share & Export": with the popover open, a raw
    find_elements(firefox) sees its "Copy" menu item, but menu_snapshot returns
    empty). This scans the already-open live tree directly so the popover items
    are captured. Noisy (no prune) — use ONLY to resolve a specific popover
    control, never as the general tree.
    """
    chrome_cfg = _load_firefox_chrome_filter()
    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        raise RuntimeError(f'Firefox not found for {platform}')
    elements = find_elements(firefox)
    if allowed_roles:
        role_filter = _role_set(allowed_roles)
        elements = [
            e for e in elements
            if (e.get('role') or '').strip().lower() in role_filter
            and (e.get('name') or '').strip()
        ]
    snapshot = _classify_elements(platform, elements, menu_items=elements, chrome_cfg=chrome_cfg)
    return snapshot
