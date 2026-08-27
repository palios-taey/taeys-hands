#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.platforms.gemini.manual import (  # noqa: E402
    deep_research_send_phase_card,
    element_operation,
    key_requires_state,
)
from consultation_v2.types import ElementRef, Snapshot  # noqa: E402


REVISION = '4' * 64
DISPLAY = ':4'


def _element(
    key: str,
    name: str,
    *,
    states: tuple[str, ...] = ('enabled', 'showing'),
) -> ElementRef:
    return ElementRef(
        key=key,
        name=name,
        role='push button',
        x=1,
        y=1,
        states=list(states),
    )


def _snapshot(**mapped: list[ElementRef]) -> Snapshot:
    return Snapshot(
        platform='gemini',
        url='https://gemini.google.com/u/1/app/example',
        mapped=mapped,
    )


def _assert_card_hash(card: dict[str, object]) -> None:
    without_hash = dict(card)
    actual = without_hash.pop('card_sha256')
    encoded = json.dumps(
        without_hash,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    assert actual == hashlib.sha256(encoded).hexdigest()


def _card(snapshot: Snapshot, phase: str) -> dict[str, object] | None:
    return deep_research_send_phase_card(
        snapshot,
        scope='base',
        phase=phase,
        snapshot_revision=REVISION,
        display=DISPLAY,
    )


def main() -> int:
    assert element_operation('send_button', ['focused'], {}) is None
    assert key_requires_state('space') is False

    waiting = _card(_snapshot(), 'awaiting_initial_send')
    assert waiting is None

    ready_initial = _snapshot(
        input=[_element('input', 'Enter a prompt for Gemini')],
        mode_picker=[
            _element('mode_picker', 'Open mode picker, currently Pro Extended')
        ],
        tool_deselect_deep_research=[
            _element('tool_deselect_deep_research', 'Deselect Deep research')
        ],
        send_button=[
            _element(
                'send_button',
                'Send message',
                states=('focused', 'enabled', 'showing'),
            )
        ],
    )
    initial_card = _card(ready_initial, 'awaiting_initial_send')
    assert initial_card is not None
    assert initial_card == {
        'schema': 'taey.gemini_dr_send_phase.v1',
        'platform': 'gemini',
        'display': DISPLAY,
        'phase': 'ready_initial_send',
        'extraction_output_type': 'research_report',
        'snapshot_revision': REVISION,
        'allowed': {'action': 'key', 'key': 'space'},
        'next_phase': 'awaiting_start_research',
        'card_sha256': initial_card['card_sha256'],
    }
    _assert_card_hash(initial_card)

    plan_stop = _snapshot(
        stop_button=[_element('stop_button', 'Stop response')],
    )
    plan_card = _card(plan_stop, 'awaiting_start_research')
    assert plan_card is not None
    assert plan_card['phase'] == 'awaiting_start_research'
    assert plan_card['allowed'] == {'action': 'observe', 'scope': 'base'}
    assert plan_card['next_phase'] is None

    start_ready = _snapshot(
        start_research=[_element('start_research', 'Start research')],
    )
    start_card = _card(start_ready, 'awaiting_start_research')
    assert start_card is not None
    assert start_card['phase'] == 'ready_start_research'
    assert start_card['allowed'] == {
        'action': 'click',
        'element': 'start_research',
    }
    assert start_card['next_phase'] == 'awaiting_research_stop'
    _assert_card_hash(start_card)

    awaiting_stop = _card(_snapshot(), 'awaiting_research_stop')
    assert awaiting_stop is not None
    assert awaiting_stop['phase'] == 'awaiting_research_stop'
    assert awaiting_stop['allowed'] == {'action': 'observe', 'scope': 'base'}
    assert awaiting_stop['next_phase'] is None

    research_stop = _snapshot(
        stop_button=[_element('stop_button', 'Stop response')],
    )
    monitor_card = _card(research_stop, 'awaiting_research_stop')
    assert monitor_card is not None
    assert monitor_card['phase'] == 'monitor_ready'
    assert monitor_card['extraction_output_type'] == 'research_report'
    assert monitor_card['allowed'] is None
    assert monitor_card['next_phase'] is None
    _assert_card_hash(monitor_card)

    duplicate_start = _snapshot(
        start_research=[
            _element('start_research', 'Start research'),
            _element('start_research', 'Start research'),
        ],
    )
    try:
        _card(duplicate_start, 'awaiting_start_research')
    except ValueError as exc:
        assert "exact singleton 'start_research'" in str(exc)
    else:
        raise AssertionError('duplicate Start research did not fail closed')

    print('gemini Deep Research send phase card: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
