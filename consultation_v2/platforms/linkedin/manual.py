from __future__ import annotations

from dataclasses import replace
import time
from typing import Any

from consultation_v2.platforms.linkedin.driver import (
    _exact_engagement_route,
    _notifications_target,
)
from consultation_v2.snapshot import build_snapshot
from consultation_v2.types import Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


NOTIFICATIONS_NAVIGATION = 'notifications_navigation'


def _require_linkedin(snapshot: Snapshot) -> None:
    if snapshot.platform != 'linkedin':
        raise ValueError(
            f'LinkedIn manual operation received platform {snapshot.platform!r}'
        )


def _manual_post_action_contract() -> dict[str, Any]:
    workflow = load_platform_yaml('linkedin').get('workflow') or {}
    engagement = workflow.get('engagement_signal_capture') or {}
    navigation = engagement.get('navigation') or {}
    contract = navigation.get('manual_post_action')
    expected = {
        'element_key': NOTIFICATIONS_NAVIGATION,
        'operation': 'activate',
        'postcondition': {
            'projection': 'exact_route',
            'route_key': 'notifications_all',
        },
        'observation_barrier': {
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 10000,
        },
    }
    if contract != expected:
        raise RuntimeError('LinkedIn manual post-action contract is invalid')
    return dict(contract)


def augment_snapshot(snapshot: Snapshot) -> Snapshot:
    _require_linkedin(snapshot)
    target, match_count = _notifications_target(snapshot)
    if match_count > 1:
        raise ValueError(
            'LinkedIn notifications_navigation matched '
            f'{match_count} elements; expected at most one'
        )

    mapped = {
        key: list(elements)
        for key, elements in snapshot.mapped.items()
        if key != NOTIFICATIONS_NAVIGATION
    }
    mapped[NOTIFICATIONS_NAVIGATION] = (
        [replace(target, key=NOTIFICATIONS_NAVIGATION)]
        if target is not None
        else []
    )
    return replace(snapshot, mapped=mapped)


def element_operation(
    element_key: str,
    states: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    del context
    if element_key != NOTIFICATIONS_NAVIGATION:
        return None
    normalized_states = {
        str(state).strip().lower().replace('_', ' ') for state in states
    }
    allowed_now = (
        ['activate']
        if {'showing', 'enabled'}.issubset(normalized_states)
        else []
    )
    return {
        'method': 'activate',
        'effect_class': 'page',
        'primitives': ['activate'],
        'allowed_now': allowed_now,
        'forbidden': ['click', 'focus', 'hover', 'mapped_pointer_activate'],
        'postcondition': {
            'kind': 'exact_document_route',
            'route_key': 'notifications_all',
        },
    }


def verify_post_action(
    snapshot: Snapshot,
    element_key: str,
    operation: str,
) -> dict[str, Any]:
    _require_linkedin(snapshot)
    if element_key != NOTIFICATIONS_NAVIGATION or operation != 'activate':
        raise ValueError(
            'LinkedIn post-action verification accepts only '
            'notifications_navigation activate'
        )
    if not _exact_engagement_route(snapshot.url, 'notifications_all'):
        raise ValueError(
            'LinkedIn notifications_navigation postcondition failed: '
            'fresh snapshot is not the exact notifications_all route'
        )
    return {
        'element_key': NOTIFICATIONS_NAVIGATION,
        'operation': 'activate',
        'effect_class': 'page',
        'postcondition': 'notifications_all',
        'route_exact': True,
        'observed_url': snapshot.url,
    }


def stable_post_action_observation(
    element_key: str,
    operation: str,
    deadline_at: float,
) -> tuple[Snapshot | None, dict[str, Any]]:
    contract = _manual_post_action_contract()
    if (
        element_key != contract['element_key']
        or operation != contract['operation']
    ):
        raise ValueError(
            'LinkedIn stable post-action observation accepts only '
            'notifications_navigation activate'
        )
    if isinstance(deadline_at, bool) or not isinstance(deadline_at, (int, float)):
        raise ValueError('LinkedIn post-action deadline must be monotonic seconds')

    postcondition = contract['postcondition']
    barrier = contract['observation_barrier']
    stable_cycles_required = barrier['stable_cycles']
    interval = barrier['interval_ms'] / 1000.0
    started_at = time.monotonic()
    barrier_deadline = min(
        float(deadline_at),
        started_at + (barrier['timeout_ms'] / 1000.0),
    )
    stable_cycles_observed = 0
    last_snapshot: Snapshot | None = None
    samples: list[dict[str, Any]] = []

    while time.monotonic() < barrier_deadline:
        _firefox, _document, snapshot = build_snapshot('linkedin')
        last_snapshot = snapshot
        route_exact = _exact_engagement_route(
            snapshot.url,
            postcondition['route_key'],
        )
        stable_cycles_observed = (
            stable_cycles_observed + 1 if route_exact else 0
        )
        samples.append({
            'sample': len(samples) + 1,
            'elapsed_ms': round((time.monotonic() - started_at) * 1000),
            'route_exact': route_exact,
            'observed_url': snapshot.url,
        })
        if stable_cycles_observed >= stable_cycles_required:
            exact_receipt = verify_post_action(snapshot, element_key, operation)
            return snapshot, {
                'result': 'PASS',
                'next_mutation_authorized': True,
                'projection': postcondition['projection'],
                'route_key': postcondition['route_key'],
                'refresh_policy': barrier['refresh_policy'],
                'stable_cycles_required': stable_cycles_required,
                'stable_cycles_observed': stable_cycles_observed,
                'samples': samples,
                'postcondition_receipt': exact_receipt,
            }
        remaining = barrier_deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))

    return last_snapshot, {
        'result': 'TIMEOUT',
        'next_mutation_authorized': False,
        'projection': postcondition['projection'],
        'route_key': postcondition['route_key'],
        'refresh_policy': barrier['refresh_policy'],
        'stable_cycles_required': stable_cycles_required,
        'stable_cycles_observed': stable_cycles_observed,
        'samples': samples,
    }


__all__ = [
    'NOTIFICATIONS_NAVIGATION',
    'augment_snapshot',
    'element_operation',
    'stable_post_action_observation',
    'verify_post_action',
]
