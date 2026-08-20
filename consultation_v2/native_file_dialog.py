"""Revision-bound native GTK file-dialog observation from the AT-SPI tree."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from consultation_v2.platforms import routing as platform_routing
from consultation_v2.types import ElementRef, Snapshot


_YAML_PATH = Path(__file__).resolve().parent / 'native_file_dialog.yaml'
_MAPPED_KEYS = (
    'file_chooser_root',
    'file_chooser_widget',
    'location_layer',
    'location_entry',
)


class NativeDialogError(RuntimeError):
    """Zero, ambiguous, or incomplete native file-dialog tree."""


def load_native_file_dialog_yaml() -> Dict[str, Any]:
    source = _YAML_PATH.read_text(encoding='utf-8')
    data = yaml.safe_load(source) or {}
    if not isinstance(data, dict) or 'native_file_dialog' not in data:
        raise ValueError(f'{_YAML_PATH.name} must contain native_file_dialog')
    spec = data['native_file_dialog']
    if not isinstance(spec, dict):
        raise ValueError('native_file_dialog must be a mapping')
    root = spec.get('root')
    mapped = spec.get('mapped')
    if not isinstance(root, dict) or root.get('role') != 'file chooser':
        raise ValueError('native_file_dialog.root.role must be file chooser')
    if root.get('uniqueness') != 'exactly_one_application_child':
        raise ValueError(
            'native_file_dialog.root.uniqueness must be exactly_one_application_child'
        )
    if not isinstance(mapped, dict) or set(mapped) != set(_MAPPED_KEYS):
        raise ValueError(
            f'native_file_dialog.mapped must declare exactly {list(_MAPPED_KEYS)}'
        )
    for key, item in mapped.items():
        if not isinstance(item, dict) or not isinstance(item.get('role'), str) or not item['role']:
            raise ValueError(f'native_file_dialog.mapped.{key}.role must be exact')
        if 'name' in item and not isinstance(item['name'], str):
            raise ValueError(f'native_file_dialog.mapped.{key}.name must be a string')
        ancestor = item.get('ancestor')
        if ancestor is not None:
            if not isinstance(ancestor, dict):
                raise ValueError(f'native_file_dialog.mapped.{key}.ancestor must be a mapping')
            if not isinstance(ancestor.get('name'), str) or not isinstance(ancestor.get('role'), str):
                raise ValueError(
                    f'native_file_dialog.mapped.{key}.ancestor must have exact name and role'
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
    spec = load_native_file_dialog_yaml()
    firefox = platform_routing.find_firefox_for_platform(platform)
    if firefox is None:
        raise NativeDialogError(f'Firefox not found for {platform}')
    try:
        firefox.clear_cache_single()
    except Exception:
        pass
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
    mapped_spec = spec['mapped']
    widget = _exactly_one_descendant(
        root_obj,
        root_path,
        name=mapped_spec['file_chooser_widget']['name'],
        role=mapped_spec['file_chooser_widget']['role'],
        label='file_chooser_widget',
    )
    layer = _exactly_one_descendant(
        root_obj,
        root_path,
        name=mapped_spec['location_layer']['name'],
        role=mapped_spec['location_layer']['role'],
        label='location_layer',
    )
    entry = _exactly_one_descendant(
        layer[1],
        layer[0],
        name=mapped_spec['location_entry']['name'],
        role=mapped_spec['location_entry']['role'],
        label='location_entry',
    )
    mapped = {
        'file_chooser_root': [_to_ref('file_chooser_root', root_obj, root_path)],
        'file_chooser_widget': [_to_ref('file_chooser_widget', widget[1], widget[0])],
        'location_layer': [_to_ref('location_layer', layer[1], layer[0])],
        'location_entry': [_to_ref('location_entry', entry[1], entry[0])],
    }
    return Snapshot(
        platform=platform,
        url=None,
        mapped=mapped,
        raw_count=4,
    )


def _application_child_file_choosers(firefox: Any) -> List[Tuple[str, Any]]:
    found: List[Tuple[str, Any]] = []
    count = firefox.get_child_count()
    for index in range(count):
        child = firefox.get_child_at_index(index)
        if child is None:
            continue
        role = child.get_role_name() or ''
        if role == 'file chooser':
            found.append((f'APP/{index}', child))
    return found


def _exactly_one_descendant(
    root: Any,
    root_path: str,
    *,
    name: str,
    role: str,
    label: str,
) -> Tuple[str, Any]:
    matches: List[Tuple[str, Any]] = []

    def walk(obj: Any, path: str) -> None:
        if obj is None:
            return
        obj_name = obj.get_name() or ''
        obj_role = obj.get_role_name() or ''
        if obj_name == name and obj_role == role:
            matches.append((path, obj))
        child_count = obj.get_child_count()
        for index in range(child_count):
            walk(obj.get_child_at_index(index), f'{path}/{index}')

    walk(root, root_path)
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


def _to_ref(key: str, obj: Any, path: str) -> ElementRef:
    return ElementRef(
        key=key,
        name=obj.get_name() or '',
        role=obj.get_role_name() or '',
        x=None,
        y=None,
        states=_read_states(obj, path),
        atspi_obj=obj,
        raw={'tree_path': path},
    )


def _read_states(obj: Any, path: str) -> List[str]:
    if not hasattr(obj, 'get_state_set'):
        return []
    state_set = obj.get_state_set()
    if state_set is None:
        return []
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


def snapshot_contract(snapshot: Snapshot) -> Dict[str, Any]:
    revision = native_dialog_revision(snapshot)
    mapped: Dict[str, Any] = {}
    for key, items in snapshot.mapped.items():
        if len(items) != 1:
            raise NativeDialogError(f'snapshot key {key!r} is not unique')
        item = items[0]
        mapped[key] = {
            'name': item.name,
            'role': item.role,
            'tree_path': (item.raw or {}).get('tree_path'),
            'states': list(item.states),
        }
    return {
        'scope': 'native_dialog',
        'surface': 'native_dialog',
        'authority': 'atspi_tree',
        'platform': snapshot.platform,
        'snapshot_revision': revision,
        'mapped': mapped,
    }


def main() -> int:
    import argparse
    import sys

    from consultation_v2.platforms_runtime import apply_display_environment, get_platform_display

    parser = argparse.ArgumentParser(description='Observe the native GTK file dialog from AT-SPI')
    parser.add_argument('--platform', default='claude')
    parser.add_argument('--display')
    args = parser.parse_args()
    display = args.display or get_platform_display(args.platform)
    apply_display_environment(display)
    snapshot = build_native_dialog_snapshot(args.platform)
    sys.stdout.write(json.dumps(snapshot_contract(snapshot), indent=2, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
