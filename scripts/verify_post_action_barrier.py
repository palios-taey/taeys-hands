#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.post_action_barrier import (
    PostActionObservationError,
    PostActionLineage,
    PostActionSample,
    _run_post_action_barrier,
    resolve_post_action_transition,
)
from consultation_v2.types import ElementRef, Snapshot


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def element(key: str, name: str, role: str, states: tuple[str, ...] = ()) -> ElementRef:
    return ElementRef(
        key=key,
        name=name,
        role=role,
        x=1,
        y=1,
        states=list(states),
    )


def sample(
    mapped: dict[str, list[ElementRef]],
    url: str = 'https://grok.com/c/example',
) -> PostActionSample:
    return PostActionSample(
        snapshot=Snapshot(
            platform='grok',
            url=url,
            mapped=mapped,
            raw_count=sum(map(len, mapped.values())),
        ),
        refresh_outcomes=(
            {'target': 'desktop', 'outcome': 'invalidated'},
            {'target': 'firefox', 'outcome': 'reacquired'},
            {'target': 'firefox', 'outcome': 'invalidated'},
            {'target': 'document', 'outcome': 'reacquired'},
            {'target': 'document', 'outcome': 'invalidated'},
            {'target': 'snapshot', 'outcome': 'reacquired'},
        ),
    )


def main() -> int:
    transition = resolve_post_action_transition('grok', 'usage_limit_retry')
    assert transition.action == 'click'
    assert transition.element == 'retry_button'
    assert transition.success_element == 'stop_button'
    assert transition.consecutive_matches == 2
    assert transition.refresh_policy == 'invalidate_reacquire'

    lineage = PostActionLineage(
        seat_id='gate-seat',
        turn_id='gate-turn',
        process_generation='0123456789abcdef0123456789abcdef',
        display=':gate',
        atspi_bus_address='unix:path=/gate/a11y',
        pre_action_revision='gate-pre-action-revision',
    )
    action_receipt = {
        'action': 'click',
        'element': 'retry_button',
        'mutation_count': 1,
        'outcome': 'applied',
        'ref': 'atspi3.gate-ref',
        'revision': 'gate-pre-action-revision',
    }

    stop = element('stop_button', 'Stop model response', 'push button')
    success_samples = iter((sample({'stop_button': [stop]}), sample({'stop_button': [stop]})))
    success_time = FakeTime()
    success = _run_post_action_barrier(
        'grok',
        'usage_limit_retry',
        lineage=lineage,
        action_receipt=action_receipt,
        sample_reader=lambda _transition: next(success_samples),
        monotonic=success_time.monotonic,
        sleeper=success_time.sleep,
    )
    assert success['verdict'] == 'PASS'
    assert success['next_mutation_authorized'] is True
    assert len(success['samples']) == 2
    assert all(item['projection']['state'] == 'happy' for item in success['samples'])

    alert = element(
        'usage_limit_updated_alert',
        '',
        'alert',
        ('showing', 'enabled'),
    )
    retry = element('retry_button', 'Retry', 'push button')
    alternate_time = FakeTime()
    alternate = _run_post_action_barrier(
        'grok',
        'usage_limit_retry',
        lineage=lineage,
        action_receipt=action_receipt,
        sample_reader=lambda _transition: sample({
            'usage_limit_updated_alert': [alert],
            'retry_button': [retry],
        }),
        monotonic=alternate_time.monotonic,
        sleeper=alternate_time.sleep,
    )
    assert alternate['verdict'] == 'HALT'
    assert alternate['reason'] == 'mapped_exception:usage_limit_updated'
    assert alternate['next_mutation_authorized'] is False
    assert len(alternate['samples']) == 1

    duplicate_time = FakeTime()
    duplicate = _run_post_action_barrier(
        'grok',
        'usage_limit_retry',
        lineage=lineage,
        action_receipt=action_receipt,
        sample_reader=lambda _transition: sample({'stop_button': [stop, stop]}),
        monotonic=duplicate_time.monotonic,
        sleeper=duplicate_time.sleep,
    )
    assert duplicate['verdict'] == 'HALT'
    assert duplicate['reason'] == 'postcondition_drift'
    assert duplicate['next_mutation_authorized'] is False
    assert len(duplicate['samples']) == 1

    timeout_time = FakeTime()
    timeout = _run_post_action_barrier(
        'grok',
        'usage_limit_retry',
        lineage=lineage,
        action_receipt=action_receipt,
        sample_reader=lambda _transition: sample({}),
        monotonic=timeout_time.monotonic,
        sleeper=timeout_time.sleep,
    )
    assert timeout['verdict'] == 'HALT'
    assert timeout['reason'] == 'postcondition_timeout'
    assert timeout['next_mutation_authorized'] is False

    failure_time = FakeTime()
    failure = _run_post_action_barrier(
        'grok',
        'usage_limit_retry',
        lineage=lineage,
        action_receipt=action_receipt,
        sample_reader=lambda _transition: (_ for _ in ()).throw(
            PostActionObservationError(
                'document cache invalidation failed',
                ({'target': 'document', 'outcome': 'failed'},),
            )
        ),
        monotonic=failure_time.monotonic,
        sleeper=failure_time.sleep,
    )
    assert failure['verdict'] == 'HALT'
    assert failure['reason'] == 'observation_failed'
    assert failure['next_mutation_authorized'] is False
    assert failure['samples'][0]['refresh_outcomes'][0]['outcome'] == 'failed'

    print('PASS: Grok usage_limit_retry requires two exact fresh projections')
    print('PASS: mapped exception terminates without mutation authority')
    print('PASS: duplicate projected control terminates without mutation authority')
    print('PASS: timeout terminates without mutation authority')
    print('PASS: refresh failure produces a terminal receipted HALT')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
