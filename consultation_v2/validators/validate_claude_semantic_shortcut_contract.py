#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.platforms.claude import manual
from consultation_v2.types import ElementRef, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml
from scripts.run_manual_chat_worker import _claude_active_model_names, _send_content


def _element(
    key: str,
    name: str,
    role: str,
    *,
    states: list[str] | None = None,
    x: int = 10,
    y: int = 20,
) -> ElementRef:
    return ElementRef(
        key=key,
        name=name,
        role=role,
        x=x,
        y=y,
        states=list(states or []),
    )


def _snapshot() -> Snapshot:
    return Snapshot(
        platform='claude',
        url='https://claude.ai/new',
        raw_count=20,
        mapped={
            'input': [
                _element(
                    'input',
                    'Write your prompt to Claude',
                    'entry',
                    states=['enabled', 'focusable', 'focused', 'showing'],
                )
            ],
            'model_selector': [
                _element(
                    'model_selector',
                    'Model: Opus 5 · Extra',
                    'push button',
                    states=['enabled', 'showing'],
                )
            ],
            'toggle_menu': [
                _element(
                    'toggle_menu',
                    'Add files, connectors, and more',
                    'push button',
                    states=['enabled', 'showing'],
                )
            ],
            'address_bar': [
                _element(
                    'address_bar',
                    'Search with Google or enter address',
                    'entry',
                    states=['enabled', 'focusable', 'showing'],
                )
            ],
        },
    )


def _token(snapshot: Snapshot) -> str:
    tokens = manual.key_preconditions(snapshot, scope='base')
    assert list(tokens) == ['ctrl+u']
    return tokens['ctrl+u']


def main() -> int:
    cfg = load_platform_yaml('claude')
    element_map = cfg['tree']['element_map']
    assert element_map['model_selector']['structural'] == {'after': 'toggle_menu'}
    assert element_map['press_record_button']['name'] == 'Press and hold to record'
    assert element_map['voice_mode_button']['name'] == 'Use voice mode'
    key_precondition = cfg['workflow']['attachment']['key_precondition']
    assert key_precondition['focused_element'] == 'input'
    assert key_precondition['unfocused_elements'] == ['address_bar']

    baseline = _snapshot()
    baseline_token = _token(baseline)
    manual.validate_key_precondition(
        'ctrl+u',
        baseline,
        scope='base',
        expected_sha256=baseline_token,
    )

    optional_drift = _snapshot()
    optional_drift.mapped['settings_button'] = [
        _element('settings_button', 'Settings', 'push button', x=800, y=900)
    ]
    optional_drift.mapped['toggle_menu'][0].x = 400
    optional_drift.mapped['toggle_menu'][0].y = 500
    optional_drift.mapped['toggle_menu'][0].states.append('focused')
    assert _token(optional_drift) == baseline_token

    model_changed = _snapshot()
    model_changed.mapped['model_selector'][0].name = 'Model: Sonnet 4.6'
    assert _token(model_changed) != baseline_token

    attachment_changed = _snapshot()
    attachment_changed.mapped['remove_attachment'] = [
        _element('remove_attachment', 'Remove', 'push button')
    ]
    assert _token(attachment_changed) != baseline_token

    unfocused = _snapshot()
    unfocused.mapped['input'][0].states.remove('focused')
    assert manual.key_preconditions(unfocused, scope='base') == {}

    dual_focused = _snapshot()
    dual_focused.mapped['address_bar'][0].states.append('focused')
    assert manual.key_preconditions(dual_focused, scope='base') == {}

    missing_unfocused_element = _snapshot()
    del missing_unfocused_element.mapped['address_bar']
    assert manual.key_preconditions(missing_unfocused_element, scope='base') == {}

    duplicate_unfocused_element = _snapshot()
    duplicate_unfocused_element.mapped['address_bar'].append(
        _element(
            'address_bar',
            'Search with Google or enter address',
            'entry',
            states=['enabled', 'focusable', 'showing'],
        )
    )
    assert manual.key_preconditions(duplicate_unfocused_element, scope='base') == {}

    stopped = _snapshot()
    stopped.mapped['stop_button'] = [
        _element('stop_button', 'Stop response', 'push button')
    ]
    assert manual.key_preconditions(stopped, scope='base') == {}

    exceptional = _snapshot()
    exceptional.mapped['claude_capacity_alert'] = [
        _element('claude_capacity_alert', 'Capacity', 'alert')
    ]
    assert manual.key_preconditions(exceptional, scope='base') == {}

    wrong_url = _snapshot()
    wrong_url.url = 'https://claude.ai/chat/example'
    assert manual.key_preconditions(wrong_url, scope='base') == {}

    duplicate = _snapshot()
    duplicate.mapped['toggle_menu'].append(
        _element('toggle_menu', 'Add files, connectors, and more', 'push button')
    )
    assert manual.key_preconditions(duplicate, scope='base') == {}

    try:
        manual.validate_key_precondition(
            'ctrl+u',
            model_changed,
            scope='base',
            expected_sha256=baseline_token,
        )
    except ValueError as exc:
        assert 'semantic state changed' in str(exc)
    else:
        raise AssertionError('changed semantic projection was accepted')

    try:
        manual.validate_key_action('CTRL+U', baseline)
    except ValueError as exc:
        assert 'exactly equal YAML' in str(exc)
    else:
        raise AssertionError('case-drifted shortcut was accepted')

    assert manual.key_preconditions(baseline, scope='menu_snapshot') == {}
    assert manual.key_requires_state('ctrl+u') is True
    assert manual.key_requires_state('Return') is False

    active_model_names = _claude_active_model_names()
    assert active_model_names == (
        'Model: Opus 5 Extra',
        'Model: Opus 5 · Extra',
    )
    content = _send_content(
        'claude',
        ':3',
        Path('/bundles/bundle-a.md'),
        Path('/bundles/bundle-b.md'),
        Path('/bundles/prompt.txt'),
    )
    names_literal = '["Model: Opus 5 Extra", "Model: Opus 5 · Extra"]'
    assert content.count(f'YAML-derived set {names_literal}') >= 7
    assert content.count('key_preconditions.ctrl+u') == 4
    assert content.count('focus element=input exactly once') == 2
    assert content.count('If it is still absent') == 2
    assert content.count('key=ctrl+u') == 2
    assert 'whose exact name is Model: Opus 5 Extra' not in content
    print('PASS: Claude semantic attachment shortcut contract')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
