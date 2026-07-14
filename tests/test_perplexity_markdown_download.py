from consultation_v2.platforms.perplexity.driver import PerplexityConsultationDriver
from consultation_v2.types import (
    Choice,
    ConsultationRequest,
    ConsultationResult,
    ElementRef,
    Snapshot,
)


PRODUCTION_MARKDOWN_SHAPE = """<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# \\# Perplexity Deep Research Request - Zapier / Staff Engineer, Backend, Revenue

Generated: 2026-07-14T14:31:34+00:00
Opportunity id: `22fc095b9b0f3d15`

## ISMA query seeds (derive concrete phrasings)

```json
{
  "company_terms": [
    "Zapier",
    "Staff"
  ]
}
```

## Output contract (REQUIRED - machine-ingested, do not omit)

End the report with ONE fenced ```json code block (it must be the LAST fenced block in the reply) of exactly this shape:

```
{
  "summary": "2-4 sentences: what the company does, stage/scale, hiring context",
  "product_summary": "what the product actually is, technically",
  "mission": "their stated mission, or [Unknown]",
  "values_summary": "citable values stance with source, or [Unknown]",
  "comp_signals": "comp band / equity signals found, or [Unknown]",
  "red_flags": ["each flag as one string; empty list if none"],
  "resonance_mode": "FOUNDER|PRODUCT|VALUES|GENERIC_TECHNICAL",
  "values_signal": {"axes": [], "strongest_genuine_axis": "NONE", "overlap_with_jesse": "NONE", "values_beat_eligible": false, "cannot_lie_note": "why eligible or not"},
  "company_application_site": "the company's own ATS/application URL"
}
```

Rules: label anything not directly sourced as [Unknown] - never invent. resonance_mode is GENERIC_TECHNICAL unless a citable, specific, action-backed resonance exists.

I now have all the information I need. Let me compose the full report now.

***

# Zapier - Staff Engineer, Backend, Revenue

## Company Overview

Observed report body.

```json
{
  "summary": "Zapier is a fully remote workflow automation platform.",
  "product_summary": "A no-code/low-code automation platform connecting SaaS apps.",
  "mission": "Make automation work for everyone.",
  "values_summary": "Published values include Build the Robot.",
  "comp_signals": "$211K-$316K base.",
  "red_flags": [],
  "resonance_mode": "VALUES",
  "values_signal": {"axes": [], "strongest_genuine_axis": "NONE", "overlap_with_jesse": "NONE", "values_beat_eligible": false, "cannot_lie_note": "fixture"},
  "company_application_site": "https://jobs.ashbyhq.com/zapier/1767482d-de23-460c-80eb-6d0a3caa72ab"
}
```
"""


def test_markdown_download_strips_echoed_request_before_report_json():
    cleaned = PerplexityConsultationDriver._markdown_download_answer_region(
        PRODUCTION_MARKDOWN_SHAPE,
    )

    assert cleaned.startswith("I now have all the information I need.")
    assert "# \\# Perplexity Deep Research Request" not in cleaned
    assert '"company_terms"' not in cleaned
    assert '"summary": "2-4 sentences' not in cleaned
    assert cleaned.count("```json") == 1
    assert '"summary": "Zapier is a fully remote workflow automation platform."' in cleaned


def test_markdown_download_cleanup_closes_spawned_firefox_popup(monkeypatch):
    driver = PerplexityConsultationDriver()
    seen_commands = []

    def fake_search(args, env, timeout=2):
        seen_commands.append(tuple(args))
        if args == ['--class', 'firefox']:
            return ['main-window', 'download-popup']
        return []

    def fake_window_name(window_id, env):
        return {
            'main-window': 'Zapier - Perplexity',
            'download-popup': 'Firefox',
        }[window_id]

    def fake_window_geometry(window_id, env):
        return {
            'main-window': (1280, 900),
            'download-popup': (496, 340),
        }[window_id]

    closed = []

    def fake_close(window_id, env):
        closed.append(window_id)
        return True

    visible_counts = iter([2, 1])

    monkeypatch.setattr(driver, '_xdotool_search', fake_search)
    monkeypatch.setattr(driver, '_xdotool_window_name', fake_window_name)
    monkeypatch.setattr(driver, '_x_window_geometry', fake_window_geometry)
    monkeypatch.setattr(driver, '_close_x_window', fake_close)
    monkeypatch.setattr(
        driver,
        '_visible_firefox_window_count',
        lambda env: next(visible_counts),
    )

    ok, evidence = driver._cleanup_markdown_download_popup({'main-window'})

    assert ok is True
    assert closed == ['download-popup']
    assert evidence['markdown_download_popup_closed_window_ids'] == ['download-popup']
    assert evidence['markdown_download_visible_firefox_windows_after_cleanup'] == 1
    assert ('--class', 'firefox') in seen_commands


def test_markdown_download_cleanup_fails_loud_when_popup_remains(monkeypatch):
    driver = PerplexityConsultationDriver()

    monkeypatch.setattr(
        driver,
        '_visible_firefox_windows',
        lambda env: [
            {
                'id': 'main-window',
                'title': 'Zapier - Perplexity',
                'width': 1280,
                'height': 900,
                'area': 1152000,
            },
            {
                'id': 'download-popup',
                'title': 'Firefox',
                'width': 496,
                'height': 340,
                'area': 168640,
            },
        ],
    )
    monkeypatch.setattr(driver, '_close_x_window', lambda window_id, env: False)
    monkeypatch.setattr(driver, '_visible_firefox_window_count', lambda env: 2)

    ok, evidence = driver._cleanup_markdown_download_popup(
        {'main-window'},
        timeout=0.1,
    )

    assert ok is False
    assert evidence['markdown_download_popup_close_failed_window_ids'] == [
        'download-popup',
    ]
    assert evidence['markdown_download_visible_firefox_windows_after_cleanup'] == 2


def test_deep_research_empty_copy_button_clipboard_reaches_markdown_download(
    monkeypatch,
):
    driver = PerplexityConsultationDriver()
    copy_button = ElementRef(
        key='copy_button',
        name='Copy',
        role='push button',
        x=10,
        y=20,
    )
    snap = Snapshot(
        platform='perplexity',
        url='https://www.perplexity.ai/search/92b7d26b',
        mapped={'copy_button': [copy_button]},
        raw_count=10,
    )

    class FakeRuntime:
        def __init__(self):
            self.clicked = []

        def scroll_element_into_view(self, target):
            return True

        def write_clipboard(self, _text):
            return None

        def click(self, target, strategy=None):
            self.clicked.append((target.key, strategy))
            return True

    runtime = FakeRuntime()
    driver.runtime = runtime

    request = ConsultationRequest(
        platform='perplexity',
        message='research',
        selections={'mode': Choice('deep_research')},
    )
    result = ConsultationResult(platform='perplexity', request=request)
    markdown_attempts_seen = []

    def fake_markdown_download(_request, result_arg, attempts):
        markdown_attempts_seen.extend(attempts)
        result_arg.response_text = 'markdown fallback answer'
        result_arg.add_step(
            'extract_primary',
            True,
            'markdown fallback reached',
            target_key='markdown_download',
            markdown_download_attempts=attempts,
        )
        return True

    monkeypatch.setattr(driver, '_ensure_answer_thread', lambda _result: True)
    monkeypatch.setattr(
        driver,
        '_deep_research_copy_target',
        lambda: (
            snap,
            'copy_button',
            copy_button,
            {
                'waited_for': 'copy_contents_button',
                'matched': False,
                'selected': 'copy_button',
            },
        ),
    )
    monkeypatch.setattr(
        driver,
        '_read_clipboard_until_nonempty',
        lambda: ('', {'clipboard_reads': 14}),
    )
    monkeypatch.setattr(
        driver,
        '_extract_via_markdown_download',
        fake_markdown_download,
    )

    assert driver.extract_primary(request, result) is True

    assert runtime.clicked == [('copy_button', 'atspi_only')]
    assert markdown_attempts_seen
    assert markdown_attempts_seen[0]['fallback_after_target_key'] == 'copy_button'
    assert markdown_attempts_seen[0]['fallback_reason'] == 'empty_clipboard'
    assert (
        markdown_attempts_seen[0]['deep_research_render_shape']
        == 'copy_button_empty_clipboard_after_copy_contents_timeout'
    )
    assert result.steps[-1].success is True
    assert result.steps[-1].evidence['target_key'] == 'markdown_download'
