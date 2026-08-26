#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
INTERACT_PATH = REPO_ROOT / 'consultation_v2/interact.py'
INPUT_PATH = REPO_ROOT / 'consultation_v2/input.py'
MANUAL_PATH = REPO_ROOT / 'consultation_v2/platforms/linkedin/manual.py'

from consultation_v2.yaml_contract import load_platform_yaml


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    candidates = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    _require(len(candidates) == 1, f'{path.name}:{name} is not unique')
    segment = ast.get_source_segment(source, candidates[0])
    _require(segment is not None, f'could not read {path.name}:{name}')
    return str(segment)


def main() -> int:
    cfg = load_platform_yaml('linkedin')
    selection = (
        ((cfg.get('workflow') or {}).get('engagement_signal_capture') or {})
        .get('manual_notification_selection') or {}
    )
    selected_thread = selection.get('selected_thread') or {}
    _require(
        selected_thread.get('scroll_into_view') == {
            'effect_class': 'viewport',
            'primitives': ['scroll_into_view'],
            'allowed_now': ['scroll_into_view'],
            'postcondition': 'exact_selected_thread_opener_in_viewport',
            'observation_barrier': {
                'refresh_policy': 'invalidate_reacquire',
                'stable_cycles': 2,
                'interval_ms': 200,
                'timeout_ms': 10000,
            },
        },
        'LinkedIn selected-thread viewport transition drifted',
    )

    operation_source = _function_source(MANUAL_PATH, 'element_operation')
    for required in (
        '_SELECTED_THREAD_OPEN_KEY.fullmatch(element_key)',
        '_selected_thread_viewport_state(dict(context or {}))',
        "viewport.get('live_extent_in_viewport') is True",
        "viewport.get('error') == 'live_extent_outside_display'",
        "'selected_thread'",
        "]['action']",
        "]['scroll_into_view']",
        "'exact_selected_thread_opener_in_viewport'",
        "'scroll_into_view'",
        "'mapped_pointer_activate'",
    ):
        _require(
            required in operation_source,
            f'LinkedIn selected-thread operation missing {required!r}',
        )

    pointer_source = _function_source(
        INTERACT_PATH,
        'atspi_mapped_pointer_activate',
    )
    _require(
        "inp.display_geometry()" in pointer_source
        and "live_extent_outside_display" in pointer_source
        and pointer_source.index('live_extent_outside_display')
        < pointer_source.index('inp.click_at('),
        'mapped pointer does not reject off-display extent before input',
    )
    click_source = _function_source(INPUT_PATH, 'click_at')
    _require(
        'display_geometry(timeout=timeout)' in click_source
        and "['xdotool', 'mousemove'" in click_source
        and click_source.index('display_geometry(timeout=timeout)')
        < click_source.index("['xdotool', 'mousemove'"),
        'click_at does not reject out-of-bounds points before xdotool mousemove',
    )
    barrier_source = _function_source(
        MANUAL_PATH,
        'stable_scroll_post_action_observation',
    )
    for required in (
        "snapshot.mapped.get(element_key)",
        "len(matches) == 1",
        "declared.get('method') == 'mapped_pointer_activate'",
        "'live_extent_in_viewport': True",
        "'observe_required_before_next_mutation': True",
    ):
        _require(required in barrier_source, f'scroll barrier missing {required!r}')

    print('linkedin selected-thread viewport contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
