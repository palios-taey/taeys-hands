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
RUNTIME_PATH = REPO_ROOT / 'consultation_v2/runtime.py'

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
    _require(
        selection.get('article_structure') == {
            'direct_child_roles_exact': [
                'link',
                'link',
                'paragraph',
                'section',
            ],
            'content_link_direct_child_index': 1,
        },
        'LinkedIn mounted-article structure contract drifted',
    )
    _require(
        ((selection.get('continuation') or {}).get('postcondition') or {}).get(
            'identity'
        ) == 'exact_yaml_content_link_uri',
        'LinkedIn continuation identity is not bound to the YAML content link',
    )
    selected_thread = selection.get('selected_thread') or {}
    _require(
        ((selection.get('selected_post_observation') or {}).get('body') or {})
        .get('index_path_authority') == 'first_exact_declared',
        'LinkedIn selected-post body path authority drifted',
    )
    _require(
        selected_thread.get('zero_open') == {
            'structural_variants': [
                {
                    'body_index_path': [0, 8, 0],
                    'index_path': [0, 12],
                },
                {
                    'body_index_path': [0, 8, 0],
                    'index_path': [0, 14],
                },
                {
                    'body_index_path': [0, 9, 0],
                    'index_path': [0, 15],
                },
                {
                    'body_index_path': [0, 9, 0],
                    'index_path': [0, 16],
                },
                {
                    'body_index_path': [0, 12, 0],
                    'index_path': [0, 19],
                },
            ],
            'role': 'push button',
            'name': 'Comment',
            'states_include': ['enabled', 'focusable'],
            'action': {
                'effect_class': 'page',
                'primitives': ['mapped_pointer_activate'],
                'allowed_now': ['mapped_pointer_activate'],
            },
            'postcondition': (
                'exact_selected_activity_zero_comment_thread_open'
            ),
        },
        'LinkedIn exact zero-comment opener contract drifted',
    )
    _require(
        selected_thread.get('scroll_into_view') == {
            'phase': 'thread_scroll',
            'effect_class': 'viewport',
            'primitives': ['scroll_into_view'],
            'allowed_now': ['scroll_into_view'],
            'scroll_target': 'selected_thread_opener',
            'scroll_target_source': 'self',
            'scroll_alignment': 'top_edge',
            'min_downward_clearance_px': 500,
            'postcondition': 'exact_selected_thread_opener_in_viewport',
            'observation_barrier': {
                'refresh_policy': 'invalidate_reacquire',
                'stable_cycles': 2,
                'interval_ms': 200,
                'timeout_ms': 120000,
            },
        },
        'LinkedIn selected-thread viewport transition drifted',
    )
    _require(
        selected_thread.get('expand') == {
            'role': 'push button',
            'relative_depth': 2,
            'name_prefix': 'See ',
            'name_suffixes': [' more comment', ' more comments'],
            'states_include': ['enabled', 'focusable'],
            'action': {
                'effect_class': 'page',
                'primitives': ['mapped_pointer_activate'],
                'allowed_now': ['mapped_pointer_activate'],
            },
            'postcondition': 'exact_selected_thread_growth',
            'scroll_into_view': {
                'phase': 'thread_expand_scroll',
                'effect_class': 'viewport',
                'primitives': ['scroll_into_view'],
                'allowed_now': ['scroll_into_view'],
                'scroll_target': 'selected_thread_expander',
                'scroll_target_source': 'self',
                'scroll_alignment': 'anywhere',
                'postcondition': 'exact_selected_thread_expander_in_viewport',
                'observation_barrier': {
                    'refresh_policy': 'invalidate_reacquire',
                    'stable_cycles': 2,
                    'interval_ms': 200,
                    'timeout_ms': 45000,
                },
            },
        },
        'LinkedIn selected-thread expansion transition drifted',
    )
    _require(
        selection.get('observation_barrier') == {
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 45000,
        },
        'LinkedIn selected-surface observation window drifted',
    )

    operation_source = _function_source(MANUAL_PATH, 'element_operation')
    for required in (
        '_SELECTED_THREAD_OPEN_KEY.fullmatch(element_key)',
        '_SELECTED_THREAD_ZERO_OPEN_KEY.fullmatch(',
        '_selected_thread_open_geometry(selected_context)',
        "root_viewport.get('intersects_viewport') is True",
        "opener_viewport.get('live_extent_in_viewport') is True",
        "opener_viewport['available_below_px'] >= minimum_clearance",
        "root_viewport.get('error') == 'live_extent_outside_display'",
        "opener_viewport.get('error') == 'live_extent_outside_display'",
        "'scroll_target'",
        "'phase'",
        "'scroll_target_source'",
        "'scroll_alignment'",
        "'min_downward_clearance_px'",
        "'selected_thread'",
        "]['action']",
        "]['scroll_into_view']",
        "'exact_selected_thread_opener_in_viewport'",
        "'scroll_into_view'",
        "'mapped_pointer_activate'",
        '_SELECTED_THREAD_EXPAND_KEY.fullmatch(',
        "'expand'",
        "['scroll_into_view']",
        "'zero_open'",
    ):
        _require(
            required in operation_source,
            f'LinkedIn selected-thread operation missing {required!r}',
        )

    verification_source = _function_source(MANUAL_PATH, 'verify_post_action')
    for required in (
        '_SELECTED_THREAD_ZERO_OPEN_KEY.fullmatch(',
        "'exact_selected_activity_zero_comment_thread_open'",
        "comment_controls['editor_ready'] is not True",
        '_SELECTED_THREAD_EXPAND_KEY.fullmatch(',
        "'exact_selected_thread_growth'",
        'observed_visible_count <= prior_visible_count',
        'observed_more_count >= declared_more_count',
        'expected_count != declared_total_count',
        '_selected_thread_typed_rows(',
        "'typed_rows_sha256'",
    ):
        _require(
            required in verification_source,
            f'LinkedIn selected-thread expansion verification missing {required!r}',
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
    viewport_source = _function_source(
        INTERACT_PATH,
        'atspi_element_viewport_state',
    )
    for required in (
        "'intersects_viewport': False",
        "'x': 0",
        "'y': 0",
        "'width': 0",
        "'height': 0",
        "'display_width': 0",
        "'display_height': 0",
        "'available_below_px': 0",
        "'error': None",
        "'intersects_viewport': bool(",
        "'available_below_px': max(",
        'rect.width > 0',
        'rect.height > 0',
        'display_width > 0',
        'display_height > 0',
    ):
        _require(
            required in viewport_source,
            f'generic viewport evidence missing {required!r}',
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
        "root_viewport.get('intersects_viewport') is True",
        'selected_post_identity_exact',
        'and scroll_target_exact',
        "opener_clearance >= declared_minimum_clearance",
        "'selected_post_root_intersects_viewport': True",
        "'scroll_target_exact': True",
        "'thread_opener_live_extent_in_viewport': True",
        "'thread_opener_available_below_px': int(",
        "'min_downward_clearance_px': (",
        "'selected_post_root_viewport': root_viewport",
        "'thread_opener_viewport': opener_viewport",
        "target_raw.get('scroll_target_atspi_obj')",
        'is target.atspi_obj',
        "'scroll_target': scroll_contract['scroll_target']",
        "'scroll_alignment': scroll_contract['scroll_alignment']",
        "'phase': scroll_contract['phase']",
        "'terminal_delivery_verified': False",
        "'observe_required_before_next_mutation': True",
        '_SELECTED_THREAD_EXPAND_KEY.fullmatch(',
    ):
        _require(required in barrier_source, f'scroll barrier missing {required!r}')

    runtime_source = RUNTIME_PATH.read_text(encoding='utf-8')
    runtime_tree = ast.parse(runtime_source)
    runtime_class = next(
        node
        for node in runtime_tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == 'ConsultationRuntime'
    )
    scroll_method = next(
        node
        for node in runtime_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name == 'scroll_element_into_view'
    )
    scroll_source = ast.get_source_segment(runtime_source, scroll_method) or ''
    _require(
        "alignment: str = 'anywhere'" in scroll_source
        and "'anywhere': _Atspi.ScrollType.ANYWHERE" in scroll_source
        and "'top_edge': _Atspi.ScrollType.TOP_EDGE" in scroll_source
        and 'comp.scroll_to(scroll_type)' in scroll_source,
        'shared scroll runtime lost default-anywhere or explicit top-edge alignment',
    )

    print('linkedin selected-thread viewport contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
