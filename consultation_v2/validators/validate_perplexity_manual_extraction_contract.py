#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.yaml_contract import get_extraction, load_platform_yaml
from consultation_v2.platforms.perplexity.manual import element_operation
from scripts.run_manual_chat_worker import (
    _completed_before_stop_provenance,
    _completed_before_stop_state,
    _extract_content,
    _perplexity_artifacts_diagnostic_content,
    _perplexity_report_card_diagnostic_content,
    _post_send_confirmation_content,
    _validate_perplexity_artifacts_diagnostic_receipt,
    _validate_perplexity_report_card_diagnostic_receipt,
    build_parser,
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
        'copy_contents_button'
    ) or {}
    _require(
        copy_spec.get('name') == 'Copy contents'
        and copy_spec.get('role') == 'push button'
        and set(copy_spec.get('states_include') or ()) == {'showing', 'enabled'},
        'Perplexity standalone report Copy contents mapping drifted',
    )
    element_map = ((cfg.get('tree') or {}).get('element_map') or {})
    _require(
        element_map.get('artifacts_pane_toggle') == {
            'name': 'Artifacts',
            'role': 'push button',
            'states_include': [
                'showing',
                'focused',
                'expanded',
                'focusable',
                'enabled',
            ],
        }
        and element_map.get('artifacts_pane_download') == {
            'name': 'Download',
            'role': 'push button',
            'states_include': ['focusable', 'enabled'],
        }
        and element_map.get('artifact_report_entry') == {
            'role': 'push button',
            'states_include': ['showing', 'focusable', 'enabled'],
            'match_strategy': 'name_agnostic_structural',
            'structural': {
                'after': 'artifacts_pane_toggle',
                'before': 'artifacts_pane_download',
            },
            'reason': 'The Artifacts pane report entry has a request-derived dynamic title and is the only enabled push button bounded by the exact expanded Artifacts toggle and exact Download control.',
        },
        'Perplexity Artifacts-pane report-entry mapping drifted',
    )
    report_entry_name = 'Current Provider and Agent-Platform Capability Intelligence Report'
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
            'reason': 'The expanded Perplexity report has one nameless focusable scroll pane below the exact Close toolbar control; it is a mapped report surface, but extraction uses the standalone report Copy contents control.',
        },
        'Perplexity report-surface control mapping drifted',
    )
    _require(
        element_map.get('artifact_open_new_tab') == {
            'name': 'Open in new tab',
            'role': 'menu item',
            'states_include': ['showing', 'enabled'],
        },
        'Perplexity standalone report opener mapping drifted',
    )
    artifact_options_operation = element_operation(
        'artifact_options', ['showing', 'focusable', 'enabled'], {}
    )
    _require(
        artifact_options_operation is not None
        and artifact_options_operation.get('method') == 'mapped_pointer_activate'
        and artifact_options_operation.get('allowed_now') == ['mapped_pointer_activate'],
        'Perplexity Artifact options must use mapped pointer activation',
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
            ('open_panel', 'artifact_options', 'last', None),
            ('open_panel', 'artifact_open_new_tab', 'last', None),
            ('copy_element', 'copy_contents_button', 'last', None),
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
        card.count('performed_primitive=mapped_pointer_activate') == 1,
        'Perplexity extraction card must require mapped pointer activation for Artifact options',
    )
    _require(
        card.index('operate element=artifact_options exactly once')
        < card.index('click element=artifact_open_new_tab exactly once')
        < card.index('exactly one mapped copy_contents_button')
        < card.index('click element=copy_contents_button exactly once'),
        'Perplexity extraction card must open the standalone report before Copy contents',
    )
    _require(
        card.count('observe scope=base') == 4
        and 'https://www.perplexity.ai/computer/a/<non-empty-id>' in card
        and 'scroll_to_bottom' not in card,
        'Perplexity extraction card lost its exact report-tab transition or retained scrolling',
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
        'report_options_open_count=1' in card
        and 'standalone_report_open_count=1' in card
        and 'report_copy_count=1' in card
        and card.count('operate element=artifact_options exactly once') == 1
        and card.count('click element=artifact_open_new_tab exactly once') == 1
        and card.count('click element=copy_contents_button exactly once') == 1,
        'Perplexity extraction card lost exact options, standalone, or Copy cardinality',
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
    parser = build_parser()
    diagnostic_args = parser.parse_args([
        'diagnose-perplexity-artifacts',
        '--display',
        ':6',
        '--seat-id',
        'perplexity-artifacts-diagnostic-r1',
        '--artifact-root',
        '/private/perplexity-artifacts-diagnostic-r1',
        '--source-terminal-identity',
        'spent-perplexity-identity',
        '--thread-url',
        'https://www.perplexity.ai/search/exact-thread-id',
    ])
    _require(
        diagnostic_args.platform == 'perplexity'
        and diagnostic_args.phase == 'diagnose-perplexity-artifacts',
        'Perplexity Artifacts diagnostic parser binding drifted',
    )
    diagnostic = _perplexity_artifacts_diagnostic_content(
        ':6',
        'spent-perplexity-identity',
        'https://www.perplexity.ai/search/exact-thread-id',
    )
    _require(
        diagnostic.count('observe scope=base exactly once') == 2
        and diagnostic.count('click element=artifacts_one_button') == 1
        and 'exactly zero research_report_open' in diagnostic
        and 'exactly zero artifact_options' in diagnostic
        and 'exactly one artifacts_one_button named Artifacts 1' in diagnostic
        and 'separate platform and display fields' in diagnostic
        and 'platform/display' not in diagnostic,
        'Perplexity Artifacts diagnostic lost its exact 0/0/1 transition',
    )
    _require(
        'Do not navigate, attach, paste, send, Copy, read the clipboard, extract' in diagnostic
        and 'copied: false' in diagnostic
        and 'extracted: false' in diagnostic
        and 'sent: false' in diagnostic
        and 'other_mutation_count: 0' in diagnostic,
        'Perplexity Artifacts diagnostic widened mutation authority',
    )
    artifacts_receipt = '''# PERPLEXITY ARTIFACTS PANE DIAGNOSTIC RECEIPT
platform: perplexity
display: :6
source_terminal_identity: spent-perplexity-identity
thread_url: https://www.perplexity.ai/search/exact-thread-id
pre_observation_revision: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
pre_report_open_count: 0
pre_artifact_options_count: 0
pre_artifacts_one_count: 1
pre_copy_count: 1
pre_helpful_count: 1
pre_not_helpful_count: 1
clicked_element: artifacts_one_button
click_result: performed=true, performed_primitive=click
post_observation_revision: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
post_report_open_count: 0
post_artifact_options_count: 0
post_artifacts_one_count: 0
post_copy_contents_count: 0
post_copy_count: 1
observe_count: 2
click_count: 1
copied: false
extracted: false
sent: false
other_mutation_count: 0
'''
    _validate_perplexity_artifacts_diagnostic_receipt(
        artifacts_receipt,
        ':6',
        'spent-perplexity-identity',
        'https://www.perplexity.ai/search/exact-thread-id',
    )
    try:
        _validate_perplexity_artifacts_diagnostic_receipt(
            artifacts_receipt.replace(
                'platform: perplexity\ndisplay: :6',
                'platform/display: perplexity / :6',
            ),
            ':6',
            'spent-perplexity-identity',
            'https://www.perplexity.ai/search/exact-thread-id',
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            'Perplexity Artifacts parser accepted a combined platform/display field'
        )

    report_card_args = parser.parse_args([
        'diagnose-perplexity-report-card',
        '--display',
        ':6',
        '--seat-id',
        'perplexity-report-card-diagnostic-r2',
        '--artifact-root',
        '/private/perplexity-report-card-diagnostic-r2',
        '--source-diagnostic-identity',
        'perplexity-artifacts-diagnostic-r1',
        '--thread-url',
        'https://www.perplexity.ai/search/exact-thread-id',
    ])
    _require(
        report_card_args.platform == 'perplexity'
        and report_card_args.phase == 'diagnose-perplexity-report-card'
        and report_card_args.source_diagnostic_identity
        == 'perplexity-artifacts-diagnostic-r1',
        'Perplexity report-card diagnostic parser binding drifted',
    )
    report_card_diagnostic = _perplexity_report_card_diagnostic_content(
        ':6',
        'perplexity-artifacts-diagnostic-r1',
        'https://www.perplexity.ai/search/exact-thread-id',
    )
    _require(
        report_card_diagnostic.count('observe scope=base exactly once') == 2
        and report_card_diagnostic.count('click element=artifact_report_entry') == 1
        and 'exactly one artifacts_pane_toggle named Artifacts' in report_card_diagnostic
        and 'exactly one artifact_report_entry' in report_card_diagnostic
        and 'exactly one artifacts_pane_download named Download' in report_card_diagnostic,
        'Perplexity report-card diagnostic lost its exact one-click transition',
    )
    _require(
        'Do not navigate, attach, paste, send, Copy, read the clipboard, extract, retry, recover'
        in report_card_diagnostic
        and 'press a key' in report_card_diagnostic
        and 'clipboard_read: false' in report_card_diagnostic
        and 'other_mutation_count: 0' in report_card_diagnostic
        and 'complete post-action tree is retained' in report_card_diagnostic,
        'Perplexity report-card diagnostic widened mutation authority',
    )
    report_card_receipt = f'''# PERPLEXITY REPORT CARD DIAGNOSTIC RECEIPT
platform: perplexity
display: :6
source_diagnostic_identity: perplexity-artifacts-diagnostic-r1
thread_url: https://www.perplexity.ai/search/exact-thread-id
pre_observation_revision: {'c' * 64}
pre_stop_count: 0
pre_artifacts_pane_toggle_count: 1
pre_artifact_report_entry_count: 1
pre_artifacts_pane_download_count: 1
pre_report_entry_name: {report_entry_name}
clicked_element: artifact_report_entry
click_performed: true
performed_primitive: click
post_observation_revision: {'d' * 64}
post_current_url: https://www.perplexity.ai/search/exact-thread-id
post_stop_count: 0
post_artifacts_pane_toggle_count: 0
post_artifact_report_entry_count: 0
post_artifacts_pane_download_count: 0
post_research_report_open_count: 1
post_artifact_options_count: 1
post_copy_contents_count: 0
observe_count: 2
click_count: 1
copied: false
clipboard_read: false
extracted: false
sent: false
other_mutation_count: 0
'''
    _validate_perplexity_report_card_diagnostic_receipt(
        report_card_receipt,
        ':6',
        'perplexity-artifacts-diagnostic-r1',
        'https://www.perplexity.ai/search/exact-thread-id',
    )
    try:
        _validate_perplexity_report_card_diagnostic_receipt(
            report_card_receipt.replace('click_count: 1', 'click_count: 2'),
            ':6',
            'perplexity-artifacts-diagnostic-r1',
            'https://www.perplexity.ai/search/exact-thread-id',
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            'Perplexity report-card parser accepted more than one click'
        )
    print('perplexity manual extraction contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
