#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.yaml_contract import get_extraction, load_platform_yaml
from scripts.run_manual_chat_worker import (
    _completed_before_stop_provenance,
    _completed_before_stop_state,
    _extract_content,
    _post_send_confirmation_content,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    cfg = load_platform_yaml('perplexity')
    monitor = (cfg.get('workflow') or {}).get('monitor') or {}
    _require(
        monitor.get('completion_gate') == 'stop_absent_same_thread',
        'Perplexity monitor must cut to extraction after stable Stop absence on the same thread',
    )
    copy_spec = ((cfg.get('tree') or {}).get('element_map') or {}).get(
        'copy_button'
    ) or {}
    _require(
        copy_spec.get('name') == 'Copy'
        and copy_spec.get('role') == 'push button'
        and set(copy_spec.get('states_include') or ()) == {'showing', 'enabled'},
        'Perplexity Copy control mapping drifted',
    )
    element_map = ((cfg.get('tree') or {}).get('element_map') or {})
    _require(
        element_map.get('expand_artifact') == {
            'name': 'Expand artifact',
            'role': 'push button',
        }
        and element_map.get('close_artifact') == {
            'name': 'Close',
            'role': 'push button',
        }
        and element_map.get('report_scroll_pane') == {
            'role': 'scroll pane',
            'states_include': ['showing', 'enabled'],
            'match_strategy': 'name_agnostic_structural',
            'structural': {
                'after': 'close_artifact',
                'ordinal': 'first',
            },
            'reason': 'The expanded Perplexity report has one nameless focusable scroll pane below the exact Close toolbar control; this is the report-owned surface that must reach bottom before its Copy control is rendered.',
        },
        'Perplexity report-surface control mapping drifted',
    )

    workflow = get_extraction('perplexity', 'assistant_text')
    _require(workflow is not None, 'Perplexity assistant text extraction is missing')
    observed = tuple(
        (step.action, step.element, step.select, step.validation)
        for step in workflow.steps
    )
    _require(
        observed == (
            ('scroll_to_bottom', 'input', 'last', None),
            ('copy_element', 'copy_button', 'last', None),
            ('read_clipboard', None, 'last', 'response_complete'),
        ),
        'Perplexity assistant text extraction sequence drifted',
    )
    report_workflow = get_extraction('perplexity', 'research_report')
    _require(report_workflow is not None, 'Perplexity research report extraction is missing')
    report_steps = tuple(
        (step.action, step.element, step.select, step.validation)
        for step in report_workflow.steps
    )
    _require(
        report_steps == (
            ('open_panel', 'research_report_open', 'last', None),
            ('open_panel', 'expand_artifact', 'last', None),
            ('scroll_to_bottom', 'report_scroll_pane', 'last', None),
            ('copy_element', 'copy_button', 'last', None),
            ('read_clipboard', None, 'last', 'response_complete'),
        ),
        'Perplexity research report extraction sequence drifted',
    )

    card = _extract_content(
        'monitor-contract',
        'perplexity',
        ':6',
        Path('/frozen/response.txt'),
    )
    _require(
        card.count('selected by the YAML last_by_y rule')
        == 1,
        'Perplexity extraction card must select the final Copy only after scroll',
    )
    _require(
        card.index('click element=research_report_open exactly once')
        < card.index('click element=expand_artifact exactly once')
        < card.index('scroll_to_bottom element=report_scroll_pane exactly once')
        < card.index('exactly one mapped copy_button'),
        'Perplexity extraction card must open, expand, and scroll the report before requiring Copy',
    )
    _require(
        'mapped copy_button absent' in card
        and card.count('scroll_to_bottom element=report_scroll_pane exactly once') == 1,
        'Perplexity extraction card lost its pre-scroll Copy absence or exact report scroll',
    )
    _require(
        'without any success cardinality field' in card,
        'Perplexity failure receipt may echo success cardinality fields',
    )
    _require(
        'operate element=more_actions' not in card
        and 'download_menu_item' not in card
        and 'download_markdown_item' not in card,
        'Perplexity extraction card still exposes the optional native download path',
    )
    _require(
        'report_open_count=1' in card
        and 'report_expand_count=1' in card
        and 'report_scroll_count=1' in card
        and 'report_copy_count=1' in card
        and card.count('click element=research_report_open exactly once') == 1
        and card.count('click element=expand_artifact exactly once') == 1
        and card.count('click element=copy_button exactly once') == 1,
        'Perplexity extraction card lost exact open, expand, scroll, or Copy cardinality',
    )
    completed_state = _completed_before_stop_state('perplexity')
    _require(
        completed_state is not None
        and completed_state.get('handoff') == 'separate_extract',
        'Perplexity completed-before-Stop state must hand off to separate extraction',
    )
    send_card = _post_send_confirmation_content('perplexity', None)
    _require(
        'Do not scroll, Copy, Download, or mutate' in send_card,
        'Perplexity send card must prohibit extraction after completed-before-Stop',
    )
    source_sha256 = 'a' * 64
    completed_card = _extract_content(
        None,
        'perplexity',
        ':6',
        Path('/frozen/response.txt'),
        source_sha256,
    )
    _require(
        'No completion monitor reported COMPLETE' in completed_card
        and f'source_response_json_sha256={source_sha256}' in completed_card,
        'Perplexity separate extraction card lost terminal source provenance',
    )
    receipt = '''# COMPLETED-BEFORE-STOP SEND RECEIPT
completion_basis: completed_before_stop
stop_seen: false
monitor_id: none
send_count: 1
observation_revision_1: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
observation_revision_2: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
thread_url: https://www.perplexity.ai/search/ad156ccc-b809-4f0a-bf6b-4f5cacb5f43d
platform: perplexity
display: :6
'''
    _require(
        _completed_before_stop_provenance(receipt, 'perplexity', ':6'),
        'Perplexity completed-before-Stop receipt fields are not machine-readable',
    )
    print('perplexity manual extraction contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
