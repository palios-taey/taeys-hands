#!/usr/bin/env python3
from __future__ import annotations

# ruff: noqa: E402

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.yaml_contract import get_extraction, load_platform_yaml
from scripts.run_manual_chat_worker import _extract_content


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    cfg = load_platform_yaml('perplexity')
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
        == 2,
        'Perplexity extraction card must select the final Download before and after scroll',
    )
    _require(
        'exactly one mapped download_button' not in card,
        'Perplexity extraction card still rejects valid duplicate response Download controls',
    )
    print('perplexity manual extraction contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
