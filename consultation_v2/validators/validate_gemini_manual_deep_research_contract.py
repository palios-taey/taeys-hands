#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.yaml_contract import load_platform_yaml
from scripts.run_manual_chat_worker import _send_content


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
    paste = content.index('6. From the immediately preceding fresh base observation')
    send = content.index('7. focus element=send_button')
    _require(
        model_proof < tool_step < attach_a < attach_b < paste < send,
        'Gemini Deep Research selection is not ordered after Pro Extended and before attachments',
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
        ) == 5,
        'Gemini Deep Research active proof is not preserved from selection through send',
    )
    _require(
        'the Pro Extended proof, the Deep Research active proof' in content,
        'Gemini send receipt omits the mode-plus-tool proof',
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
