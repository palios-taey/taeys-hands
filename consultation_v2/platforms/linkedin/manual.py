from __future__ import annotations

from dataclasses import replace
from typing import Any

from consultation_v2.platforms.linkedin.driver import (
    _exact_engagement_route,
    _notifications_target,
)
from consultation_v2.types import Snapshot


NOTIFICATIONS_NAVIGATION = 'notifications_navigation'


def _require_linkedin(snapshot: Snapshot) -> None:
    if snapshot.platform != 'linkedin':
        raise ValueError(
            f'LinkedIn manual operation received platform {snapshot.platform!r}'
        )


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


__all__ = [
    'NOTIFICATIONS_NAVIGATION',
    'augment_snapshot',
    'element_operation',
    'verify_post_action',
]
