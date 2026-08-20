"""Revision-bound native GTK file-dialog observation from a platform YAML contract."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from consultation_v2.platforms import routing as platform_routing
from consultation_v2.types import ElementRef, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


class NativeDialogError(RuntimeError):
    """Zero, ambiguous, or incomplete native file-dialog tree."""


def load_native_file_dialog_spec(platform: str) -> Dict[str, Any]:
    cfg = load_platform_yaml(platform)
    spec = cfg.get('native_file_dialog')
    if not isinstance(spec, dict):
        raise NativeDialogError(
            f'{platform} YAML does not declare native_file_dialog; refusing shared/global dialog authority'
        )
    return spec


def native_dialog_revision(snapshot: Snapshot) -> str:
    rows: Dict[str, Any] = {}
    for key in sorted(snapshot.mapped):
        items = []
        for item in snapshot.mapped[key]:
            items.append(
                {
                    'name': item.name,
                    'role': item.role,
                    'tree_path': (item.raw or {}).get('tree_path'),
                    'states': sorted(set(item.states)),
                    'text': item.text or '',
                }
            )
        rows[key] = items
    payload = {
        'scope': 'native_dialog',
        'platform': snapshot.platform,
        'mapped': rows,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    ).hexdigest()


def build_native_dialog_snapshot(platform: str) -> Snapshot:
    spec = load_native_file_dialog_spec(platform)
    firefox = platform_routing.find_firefox_for_platform(platform)
    if firefox is None:
        raise NativeDialogError(f'Firefox not found for {platform}')
    _clear_cache(firefox)
    uniqueness = spec['root']['uniqueness']
    mapped_spec = spec['mapped']
    if uniqueness != 'exactly_one_application_child':
        raise NativeDialogError(f'unsupported native_file_dialog uniqueness {uniqueness!r}')
    if mapped_spec['file_chooser_root'].get('application_child') is not True:
        raise NativeDialogError('file_chooser_root.application_child must be true')
    roots = _application_child_file_choosers(firefox)
    if not roots:
        raise NativeDialogError(
            f'{platform} AT-SPI tree has no application-child file chooser'
        )
    if len(roots) != 1:
        paths = ', '.join(path for path, _obj in roots)
        raise NativeDialogError(
            f'{platform} AT-SPI tree has {len(roots)} application-child file choosers '
            f'({paths}); refusing ambiguous observation'
        )
    root_path, root_obj = roots[0]
    mapped: Dict[str, List[ElementRef]] = {
        'file_chooser_root': [_to_ref('file_chooser_root', root_obj, root_path, mapped_spec['file_chooser_root'])],
    }
    widget = _exactly_one_match(
        root_obj,
        root_path,
        mapped_spec['file_chooser_widget'],
        label='file_chooser_widget',
    )
    mapped['file_chooser_widget'] = [
        _to_ref('file_chooser_widget', widget[1], widget[0], mapped_spec['file_chooser_widget'])
    ]
    _maybe_map_optional(
        mapped,
        'location_layer',
        mapped_spec.get('location_layer'),
        root_obj,
        root_path,
    )
    layer_items = mapped.get('location_layer') or []
    layer_spec = mapped_spec.get('location_entry')
    if layer_spec is not None:
        if not layer_items:
            if layer_spec.get('required') is False:
                pass
            else:
                raise NativeDialogError('location_entry required but location_layer is absent')
        else:
            _maybe_map_optional(
                mapped,
                'location_entry',
                layer_spec,
                layer_items[0].atspi_obj,
                str((layer_items[0].raw or {}).get('tree_path') or root_path),
            )
    for key, item_spec in mapped_spec.items():
        if item_spec.get('required', True) and key not in mapped:
            raise NativeDialogError(f'native dialog missing required {key}')
        if key in mapped:
            _assert_required_states(mapped[key][0], item_spec.get('required_states') or [], key)
    return Snapshot(
        platform=platform,
        url=None,
        mapped=mapped,
        raw_count=sum(len(items) for items in mapped.values()),
    )


def snapshot_contract(
    snapshot: Snapshot,
    *,
    display: str | None = None,
) -> Dict[str, Any]:
    revision = native_dialog_revision(snapshot)
    if not _is_hex64(revision):
        raise NativeDialogError('native dialog revision is not 64 hex')
    mapped: Dict[str, Any] = {}
    refs: Dict[str, Any] = {}
    for key, items in snapshot.mapped.items():
        if len(items) != 1:
            raise NativeDialogError(f'snapshot key {key!r} is not unique')
        item = items[0]
        tree_path = (item.raw or {}).get('tree_path')
        mapped[key] = {
            'name': item.name,
            'role': item.role,
            'tree_path': tree_path,
            'states': list(item.states),
            'text': item.text or '',
        }
        refs[key] = {
            'v': 1,
            'display': display,
            'platform': snapshot.platform,
            'surface': 'native_dialog',
            'scope': 'native_dialog',
            'revision': revision,
            'element': key,
            'tree_path': tree_path,
        }
    return {
        'scope': 'native_dialog',
        'surface': 'native_dialog',
        'authority': 'atspi_tree',
        'platform': snapshot.platform,
        'snapshot_revision': revision,
        'mapped': mapped,
        'refs': refs,
    }


def _clear_cache(firefox: Any) -> None:
    clearer = getattr(firefox, 'clear_cache_single', None)
    if clearer is None:
        raise NativeDialogError('Firefox accessible has no clear_cache_single')
    try:
        clearer()
    except Exception as exc:
        raise NativeDialogError(f'AT-SPI clear_cache_single failed: {exc}') from exc


def _application_child_file_choosers(firefox: Any) -> List[Tuple[str, Any]]:
    found: List[Tuple[str, Any]] = []
    count = _child_count(firefox, 'APP')
    for index in range(count):
        child = _child_at(firefox, index, 'APP')
        role = child.get_role_name() or ''
        if role == 'file chooser':
            found.append((f'APP/{index}', child))
    return found


def _maybe_map_optional(
    mapped: Dict[str, List[ElementRef]],
    key: str,
    spec: Optional[Dict[str, Any]],
    root: Any,
    root_path: str,
) -> None:
    if spec is None:
        return
    try:
        match = _exactly_one_match(root, root_path, spec, label=key)
    except NativeDialogError:
        if spec.get('required') is False:
            return
        raise
    mapped[key] = [_to_ref(key, match[1], match[0], spec)]


def _exactly_one_match(
    root: Any,
    root_path: str,
    spec: Dict[str, Any],
    *,
    label: str,
) -> Tuple[str, Any]:
    search_root = root
    search_path = root_path
    ancestor = spec.get('ancestor')
    if ancestor is not None:
        search_path, search_root = _exactly_one_descendant(
            root,
            root_path,
            name=str(ancestor['name']),
            role=str(ancestor['role']),
            label=f'{label}.ancestor',
        )
    return _exactly_one_descendant(
        search_root,
        search_path,
        name=str(spec.get('name', '')),
        role=str(spec['role']),
        label=label,
        include_root=True,
    )


def _exactly_one_descendant(
    root: Any,
    root_path: str,
    *,
    name: str,
    role: str,
    label: str,
    include_root: bool = True,
) -> Tuple[str, Any]:
    matches: List[Tuple[str, Any]] = []

    def walk(obj: Any, path: str, include: bool) -> None:
        obj_name = obj.get_name() or ''
        obj_role = obj.get_role_name() or ''
        if include and obj_name == name and obj_role == role:
            matches.append((path, obj))
        child_count = _child_count(obj, path)
        for index in range(child_count):
            walk(_child_at(obj, index, path), f'{path}/{index}', True)

    walk(root, root_path, include_root)
    if not matches:
        raise NativeDialogError(
            f'native dialog missing {label} name={name!r} role={role!r} under {root_path}'
        )
    if len(matches) != 1:
        paths = ', '.join(path for path, _obj in matches)
        raise NativeDialogError(
            f'native dialog ambiguous {label} ({len(matches)} matches: {paths})'
        )
    return matches[0]


def _child_count(obj: Any, path: str) -> int:
    try:
        count = obj.get_child_count()
    except Exception as exc:
        raise NativeDialogError(f'cannot read child_count at {path}: {exc}') from exc
    if not isinstance(count, int) or count < 0:
        raise NativeDialogError(f'invalid child_count at {path}: {count!r}')
    return count


def _child_at(obj: Any, index: int, path: str) -> Any:
    try:
        child = obj.get_child_at_index(index)
    except Exception as exc:
        raise NativeDialogError(f'cannot read child {path}/{index}: {exc}') from exc
    if child is None:
        raise NativeDialogError(f'AT-SPI None child at {path}/{index}')
    return child


def _to_ref(key: str, obj: Any, path: str, spec: Dict[str, Any]) -> ElementRef:
    text = _capture_text(obj, path) if spec.get('role') == 'text' else None
    return ElementRef(
        key=key,
        name=obj.get_name() or '',
        role=obj.get_role_name() or '',
        x=None,
        y=None,
        states=_read_states(obj, path),
        text=text,
        atspi_obj=obj,
        raw={'tree_path': path},
    )


def _capture_text(obj: Any, path: str) -> str:
    getter = getattr(obj, 'get_text_iface', None)
    if getter is None:
        raise NativeDialogError(f'native dialog text node at {path} has no get_text_iface')
    try:
        iface = getter()
    except Exception as exc:
        raise NativeDialogError(f'cannot open Text interface at {path}: {exc}') from exc
    if iface is None:
        raise NativeDialogError(f'native dialog text node at {path} has no Text interface')
    simple = getattr(iface, 'get_text', None)
    if callable(simple) and not hasattr(iface, '__gtype__'):
        text = simple(0, -1)
    else:
        try:
            import gi
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi
            count = int(Atspi.Text.get_character_count(iface))
            if count < 0:
                raise NativeDialogError(f'invalid text length {count} at {path}')
            text = Atspi.Text.get_text(iface, 0, count)
        except NativeDialogError:
            raise
        except Exception as exc:
            raise NativeDialogError(f'cannot capture text at {path}: {exc}') from exc
    if text is None:
        return ''
    if not isinstance(text, str):
        raise NativeDialogError(f'text at {path} is not a string')
    return text


def _assert_required_states(item: ElementRef, required: List[str], key: str) -> None:
    observed = set(item.states)
    missing = [state for state in required if state not in observed]
    if missing:
        raise NativeDialogError(
            f'{key} missing required_states {missing}; observed={sorted(observed)}'
        )


def _read_states(obj: Any, path: str) -> List[str]:
    if not hasattr(obj, 'get_state_set'):
        raise NativeDialogError(f'accessible at {path} has no get_state_set')
    try:
        state_set = obj.get_state_set()
    except Exception as exc:
        raise NativeDialogError(f'cannot read state set at {path}: {exc}') from exc
    if state_set is None:
        raise NativeDialogError(f'None state set at {path}')
    canned = getattr(state_set, 'nicks', None)
    if isinstance(canned, list):
        return [str(item) for item in canned]
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
    except Exception as exc:
        raise NativeDialogError(f'cannot import Atspi to read states for {path}: {exc}') from exc
    states: List[str] = []
    for state in (
        Atspi.StateType.SHOWING,
        Atspi.StateType.VISIBLE,
        Atspi.StateType.FOCUSED,
        Atspi.StateType.EDITABLE,
        Atspi.StateType.ENABLED,
    ):
        try:
            present = bool(state_set.contains(state))
        except Exception as exc:
            raise NativeDialogError(f'cannot read AT-SPI state {state} for {path}: {exc}') from exc
        if present:
            states.append(state.value_nick)
    return states


def _is_hex64(value: str) -> bool:
    return len(value) == 64 and all(char in '0123456789abcdef' for char in value)


def main() -> int:
    import argparse
    import json as json_lib
    import sys

    from consultation_v2.platforms_runtime import apply_display_environment, get_platform_display

    parser = argparse.ArgumentParser(description='Observe the native GTK file dialog from AT-SPI')
    parser.add_argument('--platform', default='claude')
    parser.add_argument('--display')
    args = parser.parse_args()
    display = args.display or get_platform_display(args.platform)
    apply_display_environment(display)
    snapshot = build_native_dialog_snapshot(args.platform)
    sys.stdout.write(
        json_lib.dumps(snapshot_contract(snapshot, display=display), indent=2, sort_keys=True) + '\n'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
