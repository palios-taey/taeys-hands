#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.yaml_contract import get_extraction, load_platform_yaml  # noqa: E402
from scripts.run_manual_chat_worker import _send_content  # noqa: E402


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    cfg = load_platform_yaml('gemini')
    element_map = (cfg.get('tree') or {}).get('element_map') or {}
    selection = (cfg.get('workflow') or {}).get('selection') or {}
    menus = selection.get('menus') or {}
    model = menus.get('model') or {}
    mode = menus.get('mode') or {}
    tools = menus.get('tools') or {}

    _require(
        ((model.get('options') or {}).get('pro') or {}).get('active_trigger_names')
        == [
            'Open mode picker, currently Pro',
            'Open mode picker, currently Pro Extended',
            'Open mode picker, currently Pro Deep Think',
        ],
        'Gemini Pro active-trigger contract drifted',
    )
    _require(
        ((mode.get('options') or {}).get('extended') or {}).get('active_trigger_names')
        == ['Open mode picker, currently Pro Extended'],
        'Gemini Extended active proof drifted',
    )
    _require(
        tools.get('operate')
        == {'trigger': 'tools_button', 'scope': 'menu_snapshot'},
        'Gemini tools opener or YAML-owned observation scope drifted',
    )
    _require(
        (tools.get('options') or {}).get('deep_research')
        == {
            'element': 'tool_deep_research',
            'active_element': 'tool_deselect_deep_research',
        },
        'Gemini Deep Research selection or active-element contract drifted',
    )
    _require(
        element_map.get('tools_button')
        == {'name': 'Upload & tools', 'role': 'push button'},
        'Gemini tools_button exact identity drifted',
    )
    _require(
        element_map.get('tool_deep_research')
        == {
            'name': 'Deep research',
            'role': 'check menu item',
            'scope': 'tools_menu',
        },
        'Gemini Deep Research menu item exact identity drifted',
    )
    _require(
        element_map.get('tool_deselect_deep_research')
        == {'name': 'Deselect Deep research', 'role': 'push button'},
        'Gemini Deep Research active proof exact identity drifted',
    )
    _require(
        element_map.get('share_export')
        == {
            'name': 'Share & Export',
            'role': 'push button',
            'scope': 'app_root_snapshot',
        }
        and element_map.get('copy_content_item')
        == {
            'name': 'Copy',
            'role': 'menu item',
            'scope': 'app_root_snapshot',
        },
        'Gemini Deep Research report controls must use the live app-root scope',
    )
    report_workflow = get_extraction('gemini', 'research_report')
    _require(report_workflow is not None, 'Gemini research report extraction is missing')
    report_steps = tuple(
        (step.action, step.element, step.select, step.validation)
        for step in report_workflow.steps
    )
    _require(
        report_steps == (
            ('click', 'share_export', 'last', None),
            ('copy_element', 'copy_content_item', 'last', None),
            ('read_clipboard', None, 'last', 'response_complete'),
        ),
        'Gemini research report extraction sequence drifted',
    )

    content = _send_content(
        'gemini',
        ':4',
        Path('/frozen/bundle-a.md'),
        Path('/frozen/bundle-b.md'),
        Path('/frozen/prompt.txt'),
        Path('/frozen/response.md'),
    )
    model_proof = content.index(
        '2. Require mode_picker name exactly Open mode picker, currently Pro Extended.'
    )
    tool_step = content.index('3. From that fresh base observation')
    attach_a = content.index('4. Attach Bundle A')
    attach_b = content.index('5. Attach Bundle B')
    attachment_barrier = content.index(
        '6. Before any prompt mutation, observe scope=base exactly once more.'
    )
    paste = content.index('7. From that second fresh attachment-settle observation')
    send = content.index('8. focus element=send_button')
    start_research_wait = content.index(
        '9. Use read-only base observations to wait at most 180 seconds'
    )
    start_research_click = content.index(
        '10. click element=start_research exactly once'
    )
    research_confirmation = content.index(
        'RESEARCH-PHASE POST-START CONFIRMATION: ENTRY REQUIRES '
        'start_research_click_count=1 and a recorded start_research_post_revision.'
    )
    _require(
        model_proof
        < tool_step
        < attach_a
        < attach_b
        < attachment_barrier
        < paste
        < send
        < start_research_wait
        < start_research_click
        < research_confirmation,
        'Gemini Deep Research send sequence or attachment barrier is out of order',
    )
    _require(
        content.count(
            'if tool_deselect_deep_research is present exactly once with name exactly '
            'Deselect Deep research'
        ) == 1,
        'Gemini active Deep Research branch is missing or duplicated',
    )
    _require(
        content.count(
            'focus element=tools_button; observe scope=base; require tools_button '
            'match_count 1 with name exactly Upload & tools and state focused'
        ) == 1,
        'Gemini tools opener is not the exact focus/fresh-observation sequence',
    )
    _require(
        content.count(
            'key space using that fresh base revision; observe scope=menu_snapshot; require '
            'scope_expected_elements to contain tool_deep_research'
        ) == 1,
        'Gemini tools menu is not observed in the YAML-owned menu_snapshot scope',
    )
    _require(
        content.count(
            'tool_deep_research match_count 1 with name exactly Deep research; click '
            'element=tool_deep_research exactly once'
        ) == 1,
        'Gemini Deep Research exact singleton click is missing or duplicated',
    )
    _require(
        content.count(
            'tool_deselect_deep_research match_count 1 with name exactly Deselect Deep research'
        ) == 7,
        'Gemini Deep Research active proof is not preserved through Start research',
    )
    _require(
        'the Pro Extended proof, the Deep Research active proof' in content,
        'Gemini send receipt omits the mode-plus-tool proof',
    )
    _require(
        content.count('attachment_settle_revision_1') == 2
        and content.count('attachment_settle_revision_2') == 2,
        'Gemini two-observation attachment-settle receipts are missing or duplicated',
    )
    _require(
        content.count(
            'The current Gemini YAML exposes no mapped upload-in-progress, upload-busy, or '
            'upload-error element'
        ) == 1,
        'Gemini worker card invents or omits the current upload-state mapping boundary',
    )
    _require(
        content.count('key space exactly once; observe scope=base exactly once') == 1
        and content.count('plan_send_count=1') == 2,
        'Gemini initial plan send is missing or not receipted exactly once',
    )
    _require(
        content.count('click element=start_research exactly once') == 1
        and content.count('start_research_click_count=1') == 4
        and content.count('start_research_post_revision') == 4,
        'Gemini Start research action is missing or not receipted exactly once',
    )
    _require(
        'include the same attachment, prompt, plan-send, and Start-research fields in that '
        'terminal success receipt with research_stop_seen=false' in content,
        'Gemini completed-before-Stop receipt can omit Start research provenance',
    )
    _require(
        content.index('A stop_button during this phase proves only plan generation')
        < content.index('Only now follow the post-send confirmation below'),
        'Gemini worker card can hand plan-generation Stop to the monitor',
    )
    _require(
        content.count(
            'Immediately after plan_send_post_revision, Step 9 is the exclusive next phase.'
        ) == 1
        and content.count(
            'Until start_research_click_count=1 and start_research_post_revision are both '
            'recorded, do not evaluate any post-send exception or completed-before-Stop state'
        ) == 1,
        'Gemini plan send can enter generic post-send classification before Start research',
    )
    _require(
        content.count('RESEARCH-PHASE POST-START CONFIRMATION: ENTRY REQUIRES') == 1
        and content.count('POST-SEND CONFIRMATION:') == 0,
        'Gemini research completion classifier is not uniquely post-Start gated',
    )
    _require(
        content.index('start_research_click_count=1 plus start_research_post_revision')
        < research_confirmation,
        'Gemini research completion classifier precedes Start research proof',
    )
    _require(
        'click element=tools_button' not in content
        and 'operate element=tools_button' not in content,
        'Gemini worker card exposes an alternate tools-button mutation',
    )
    print('gemini manual Deep Research send contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
