from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from core import atspi
from core.tree import find_elements, find_menu_items

from .types import ElementRef, Snapshot
from .yaml_contract import load_platform_yaml


_MENU_ROLES = {"menu item", "radio menu item", "check menu item", "list item", "option"}


def _listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _lower_set(values: Any) -> set[str]:
    return {str(item).strip().lower() for item in _listify(values) if str(item).strip()}


def matches_spec(element: Dict[str, Any] | ElementRef, spec: Dict[str, Any]) -> bool:
    if not spec:
        return False

    name = ((element.name if isinstance(element, ElementRef) else element.get("name")) or "").strip()
    role = ((element.role if isinstance(element, ElementRef) else element.get("role")) or "").strip()
    states = set(
        s.strip().lower()
        for s in ((element.states if isinstance(element, ElementRef) else element.get("states")) or [])
        if str(s).strip()
    )

    name_lower = name.lower()
    role_lower = role.lower()

    if "name" in spec and name_lower != str(spec["name"]).strip().lower():
        return False

    if "names" in spec:
        allowed_names = _lower_set(spec["names"])
        if name_lower not in allowed_names:
            return False

    if "role" in spec and role_lower != str(spec["role"]).strip().lower():
        return False

    if "roles" in spec:
        allowed_roles = _lower_set(spec["roles"])
        if role_lower not in allowed_roles:
            return False

    if "states_include" in spec:
        needed = _lower_set(spec["states_include"])
        if not needed.issubset(states):
            return False

    if "states_exclude" in spec:
        blocked = _lower_set(spec["states_exclude"])
        if states & blocked:
            return False

    return True


def _is_excluded(element: Dict[str, Any], tree_cfg: Dict[str, Any]) -> bool:
    exclude = dict(tree_cfg.get("exclude", {}))
    name = (element.get("name") or "").strip().lower()
    role = (element.get("role") or "").strip().lower()

    if name and name in _lower_set(exclude.get("names")):
        return True
    if role and role in _lower_set(exclude.get("roles")):
        return True
    return False


def _to_ref(key: str | None, element: Dict[str, Any]) -> ElementRef:
    return ElementRef(
        key=key,
        name=(element.get("name") or "").strip(),
        role=(element.get("role") or "").strip(),
        x=element.get("x"),
        y=element.get("y"),
        states=list(element.get("states") or []),
        text=element.get("text"),
        description=element.get("description"),
        atspi_obj=element.get("atspi_obj"),
        raw=dict(element),
    )


def _classify_elements(
    platform: str,
    elements: Iterable[Dict[str, Any]],
    menu_items: List[Dict[str, Any]] | None = None,
) -> Snapshot:
    cfg = load_platform_yaml(platform)
    tree_cfg = dict(cfg.get("tree") or {})
    element_map = dict(tree_cfg.get("element_map") or {})
    sidebar_nav = [spec for spec in _listify(tree_cfg.get("sidebar_nav")) if isinstance(spec, dict)]

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

        if any(matches_spec(element, spec) for spec in sidebar_nav):
            sidebar.append(_to_ref(None, element))
            continue

        unknown.append(_to_ref(None, element))

    snapshot.mapped = mapped
    snapshot.unknown = unknown
    snapshot.sidebar = sidebar
    if menu_items:
        snapshot.menu_items = [_to_ref(None, item) for item in menu_items]
    return snapshot


def build_snapshot(platform: str, scan_root: str = "auto") -> Tuple[Any, Any, Snapshot]:
    """Build AT-SPI snapshot.

    scan_root controls where to scan:
      'auto' — scan from document (default, most platforms)
      'app'  — scan from Firefox app root (needed for React portals like ChatGPT model dropdown)
    """
    cfg = load_platform_yaml(platform)
    tree_cfg = dict(cfg.get("tree") or {})
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi as _Atspi

        desktop = _Atspi.get_desktop(0)
        desktop.clear_cache_single()
    except Exception:
        pass

    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        raise RuntimeError(f"Firefox not found for {platform}")

    try:
        firefox.clear_cache_single()
    except Exception:
        pass

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        # Check if YAML declares app-root scanning
        yaml_scan_root = tree_cfg.get("scan_root")
        if yaml_scan_root == "app":
            scan_root = "app"
        else:
            raise RuntimeError(f"{platform}: AT-SPI document not found; cannot proceed (fail closed)")
    url = atspi.get_document_url(doc) if doc else None

    fence = tree_cfg.get("fence_after") or []
    if scan_root == "app" or (scan_root == "auto" and not fence):
        scope = firefox
    else:
        scope = doc

    elements = find_elements(scope, fence_after=tree_cfg.get("fence_after") or [])
    snapshot = _classify_elements(platform, elements)
    snapshot.url = url
    return firefox, doc, snapshot


def build_menu_snapshot(platform: str) -> Tuple[Any, Any, Snapshot]:
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi as _Atspi

        desktop = _Atspi.get_desktop(0)
        desktop.clear_cache_single()
    except Exception:
        pass

    firefox = atspi.find_firefox_for_platform(platform)
    if not firefox:
        raise RuntimeError(f"Firefox not found for {platform}")

    doc = atspi.get_platform_document(firefox, platform)

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
    menu.sort(key=lambda item: (item.get("y") or 0, item.get("x") or 0))
    snapshot = _classify_elements(platform, menu, menu_items=menu)
    snapshot.url = atspi.get_document_url(doc) if doc is not None else None
    return firefox, doc, snapshot
