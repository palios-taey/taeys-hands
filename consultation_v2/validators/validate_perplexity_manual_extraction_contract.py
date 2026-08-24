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
    download_spec = ((cfg.get('tree') or {}).get('element_map') or {}).get(
        'download_button'
    ) or {}
    _require(
        download_spec.get('pick') == 'last_by_y',
        'Perplexity Download control must select the final response by y',
    )

    workflow = get_extraction('perplexity', 'research_report')
    _require(workflow is not None, 'Perplexity research report extraction is missing')
    observed = tuple(
        (step.action, step.element, step.select, step.validation)
        for step in workflow.steps
    )
    _require(
        observed == (
            ('scroll_to_bottom', 'input', 'last', None),
            ('scroll_into_view', 'download_button', 'last', None),
            ('click', 'download_button', 'last', None),
            ('download', 'download_markdown_item', 'last', 'response_complete'),
        ),
        'Perplexity research report extraction sequence drifted',
    )

    card = _extract_content(
        'monitor-contract',
        'perplexity',
        ':6',
        Path('/frozen/response.txt'),
        Path('/frozen/perplexity_research_report.md'),
    )
    _require(
        card.count('exactly one fresh download_button target marked by the YAML last_by_y selection')
        == 1,
        'Perplexity extraction card must select the final Download only after scroll',
    )
    _require(
        card.index('scroll_to_bottom element=input exactly once')
        < card.index('at least one mapped download_button'),
        'Perplexity extraction card requires Download before the scroll that exposes it',
    )
    _require(
        'without any success cardinality field' in card,
        'Perplexity failure receipt may echo success cardinality fields',
    )
    _require(
        'exactly one mapped download_button' not in card,
        'Perplexity extraction card still rejects valid duplicate response Download controls',
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
        Path('/frozen/perplexity_research_report.md'),
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
