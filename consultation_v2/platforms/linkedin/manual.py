from __future__ import annotations

from dataclasses import replace
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from consultation_v2.platforms.linkedin.driver import (
    _all_elements,
    _element_uri,
    _exact_engagement_route,
    _notifications_target,
)
from consultation_v2.snapshot import build_snapshot
from consultation_v2.types import Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


NOTIFICATIONS_NAVIGATION = 'notifications_navigation'
NOTIFICATION_CANDIDATE_PREFIX = 'notification_candidate_'
NOTIFICATIONS_CONTINUATION_PREFIX = 'notifications_show_more_after_'

_CANDIDATE_KEY = re.compile(
    rf'^{NOTIFICATION_CANDIDATE_PREFIX}(?P<ordinal>[0-9]{{3}})_activity_(?P<activity>[0-9]+)$'
)
_CONTINUATION_KEY = re.compile(
    rf'^{NOTIFICATIONS_CONTINUATION_PREFIX}(?P<count>[0-9]+)$'
)
_RELATIVE_AGE = re.compile(r'^[1-9][0-9]*[smhdw]$')


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


def _manual_notification_contract() -> dict[str, Any]:
    workflow = load_platform_yaml('linkedin').get('workflow') or {}
    engagement = workflow.get('engagement_signal_capture') or {}
    contract = engagement.get('manual_notification_selection')
    expected = {
        'route_key': 'notifications_all',
        'article_names': ['Notification', 'Notification.', 'Unread notification.'],
        'candidate': {
            'name_prefix': 'Unread notification.',
            'role': 'link',
            'states_include': ['enabled', 'focusable'],
            'uri': {
                'scheme': 'https',
                'host': 'www.linkedin.com',
                'normalized_path': '/feed',
                'activity_query_key': 'highlightedUpdateUrn',
                'activity_prefix': 'urn:li:activity:',
            },
        },
        'relative_age': {
            'role': 'paragraph',
            'units': ['s', 'm', 'h', 'd', 'w'],
        },
        'categories': ['All', 'Jobs', 'My posts', 'Mentions'],
        'selection_policy': {
            'order': 'newest_first',
            'max_age_hours': 72,
            'author_cooloff_hours': 48,
            'filter_after_ordered_observation': True,
            'cooloff_source': 'private_careers_activity_database',
            'continue_only_when_all_mounted_candidates_are_evidenced_excluded': True,
        },
        'continuation': {
            'name': 'Show more results',
            'role': 'push button',
            'states_include': ['enabled', 'focusable'],
        },
        'observation_barrier': {
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 10000,
        },
    }
    if contract != expected:
        raise RuntimeError('LinkedIn manual notification selection contract is invalid')
    return dict(contract)


def _node_role(node: Any) -> str:
    try:
        return str(node.get_role_name() or '')
    except Exception:
        return ''


def _node_name(node: Any) -> str:
    try:
        return str(node.get_name() or '')
    except Exception:
        return ''


def _node_text(node: Any) -> str:
    try:
        import gi

        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi

        text_iface = node.get_text_iface()
        if text_iface is None:
            return ''
        count = int(Atspi.Text.get_character_count(text_iface))
        return str(Atspi.Text.get_text(text_iface, 0, count) or '').strip()
    except Exception:
        return ''


def _direct_children(node: Any) -> list[Any]:
    try:
        count = int(node.get_child_count())
        return [
            child
            for index in range(count)
            for child in (node.get_child_at_index(index),)
            if child is not None
        ]
    except Exception:
        return []


def _structural_index_path(node: Any) -> tuple[int, ...]:
    path: list[int] = []
    current = node
    for _depth in range(64):
        try:
            parent = current.get_parent()
            if parent is None:
                break
            index = int(current.get_index_in_parent())
        except Exception as exc:
            raise ValueError(
                'LinkedIn notification lacks an exact structural tree path'
            ) from exc
        if index < 0:
            break
        path.append(index)
        current = parent
    if not path:
        raise ValueError('LinkedIn notification structural tree path is empty')
    return tuple(reversed(path))


def _notification_activity(uri: str, contract: dict[str, Any]) -> str | None:
    uri_contract = contract['candidate']['uri']
    parsed = urlsplit(uri)
    if (
        parsed.scheme != uri_contract['scheme']
        or parsed.hostname != uri_contract['host']
        or parsed.port is not None
        or (parsed.path.rstrip('/') or '/') != uri_contract['normalized_path']
        or parsed.fragment
    ):
        return None
    values = parse_qs(parsed.query).get(uri_contract['activity_query_key']) or []
    if len(values) != 1 or not values[0].startswith(uri_contract['activity_prefix']):
        return None
    activity = values[0].removeprefix(uri_contract['activity_prefix'])
    return activity if activity.isdigit() else None


def _notification_relative_age(element: Any, contract: dict[str, Any]) -> str | None:
    try:
        parent = element.atspi_obj.get_parent()
    except Exception:
        return None
    if (
        _node_role(parent) != 'article'
        or _node_name(parent) not in contract['article_names']
    ):
        return None
    ages = [
        _node_text(child)
        for child in _direct_children(parent)
        if _node_role(child) == contract['relative_age']['role']
    ]
    exact = [age for age in ages if _RELATIVE_AGE.fullmatch(age)]
    return exact[0] if len(exact) == 1 else None


def _notification_candidates(
    snapshot: Snapshot,
    contract: dict[str, Any],
) -> list[tuple[Any, str, str]]:
    candidate_contract = contract['candidate']
    raw_candidates = [
        element
        for element in _all_elements(snapshot)
        if (
            element.role == candidate_contract['role']
            and element.name.startswith(candidate_contract['name_prefix'])
            and set(candidate_contract['states_include']).issubset(element.states)
        )
    ]
    candidates: list[tuple[Any, str, str]] = []
    for element in raw_candidates:
        uri = _element_uri(element)
        if not isinstance(uri, str):
            raise ValueError('LinkedIn mounted notification lacks one exact URI')
        activity = _notification_activity(uri, contract)
        age = _notification_relative_age(element, contract)
        if activity is None or age is None:
            raise ValueError(
                'LinkedIn mounted notification lacks exact activity or relative age'
            )
        candidates.append((element, activity, age))
    candidates.sort(key=lambda row: _structural_index_path(row[0].atspi_obj))
    activities = [activity for _element, activity, _age in candidates]
    if len(activities) != len(set(activities)):
        raise ValueError('LinkedIn mounted notification activity identities are duplicated')
    return candidates


def _notification_categories_exact(snapshot: Snapshot, contract: dict[str, Any]) -> bool:
    elements = _all_elements(snapshot)
    categories = {
        name: [
            element
            for element in elements
            if element.name == name and element.role == 'radio button'
        ]
        for name in contract['categories']
    }
    if any(len(items) != 1 for items in categories.values()):
        return False
    selected = {
        name
        for name, items in categories.items()
        if {'checked', 'selected'}.intersection(items[0].states)
    }
    return selected == {'All'}


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
        if (
            key != NOTIFICATIONS_NAVIGATION
            and not key.startswith(NOTIFICATION_CANDIDATE_PREFIX)
            and not key.startswith(NOTIFICATIONS_CONTINUATION_PREFIX)
        )
    }
    mapped[NOTIFICATIONS_NAVIGATION] = (
        [replace(target, key=NOTIFICATIONS_NAVIGATION)]
        if target is not None
        else []
    )
    if _exact_engagement_route(snapshot.url, 'notifications_all'):
        contract = _manual_notification_contract()
        if not _notification_categories_exact(snapshot, contract):
            raise ValueError('LinkedIn Notifications-All category state is not exact')
        candidates = _notification_candidates(snapshot, contract)
        for ordinal, (candidate, activity, age) in enumerate(candidates, 1):
            key = (
                f'{NOTIFICATION_CANDIDATE_PREFIX}{ordinal:03d}_activity_{activity}'
            )
            raw = {
                **dict(candidate.raw),
                'notification_activity': activity,
                'notification_age': age,
                'notification_ordinal': ordinal,
            }
            mapped[key] = [replace(
                candidate,
                key=key,
                description=f'newest_order={ordinal}; relative_age={age}',
                raw=raw,
            )]
        continuation_contract = contract['continuation']
        continuations = [
            element
            for element in _all_elements(snapshot)
            if (
                element.name == continuation_contract['name']
                and element.role == continuation_contract['role']
                and set(continuation_contract['states_include']).issubset(
                    element.states
                )
            )
        ]
        if len(continuations) > 1:
            raise ValueError('LinkedIn Show more results target is ambiguous')
        if continuations:
            key = f'{NOTIFICATIONS_CONTINUATION_PREFIX}{len(candidates):03d}'
            mapped[key] = [replace(
                continuations[0],
                key=key,
                description=(
                    f'continue only after all {len(candidates)} newer candidates '
                    'have evidenced exclusions'
                ),
            )]
    return replace(snapshot, mapped=mapped)


def element_operation(
    element_key: str,
    states: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    del context
    candidate_match = _CANDIDATE_KEY.fullmatch(element_key)
    continuation_match = _CONTINUATION_KEY.fullmatch(element_key)
    if (
        element_key != NOTIFICATIONS_NAVIGATION
        and candidate_match is None
        and continuation_match is None
    ):
        return None
    normalized_states = {
        str(state).strip().lower().replace('_', ' ') for state in states
    }
    required_states = (
        {'showing', 'enabled'}
        if element_key == NOTIFICATIONS_NAVIGATION
        else {'focusable', 'enabled'}
    )
    allowed_now = (
        ['activate']
        if required_states.issubset(normalized_states)
        else []
    )
    return {
        'method': 'activate',
        'effect_class': 'page',
        'primitives': ['activate'],
        'allowed_now': allowed_now,
        'forbidden': ['click', 'focus', 'hover', 'mapped_pointer_activate'],
        'postcondition': {
            'kind': (
                'exact_notification_activity'
                if candidate_match is not None
                else (
                    'notification_candidate_count_growth'
                    if continuation_match is not None
                    else 'exact_document_route'
                )
            ),
            **(
                {'activity': candidate_match.group('activity')}
                if candidate_match is not None
                else {}
            ),
            **(
                {'prior_candidate_count': int(continuation_match.group('count'))}
                if continuation_match is not None
                else {}
            ),
            **(
                {'route_key': 'notifications_all'}
                if element_key == NOTIFICATIONS_NAVIGATION
                else {}
            ),
        },
    }


def verify_post_action(
    snapshot: Snapshot,
    element_key: str,
    operation: str,
) -> dict[str, Any]:
    _require_linkedin(snapshot)
    if operation != 'activate':
        raise ValueError(
            'LinkedIn post-action verification accepts only activate'
        )
    candidate_match = _CANDIDATE_KEY.fullmatch(element_key)
    continuation_match = _CONTINUATION_KEY.fullmatch(element_key)
    if candidate_match is not None:
        activity = _notification_activity(
            str(snapshot.url or ''),
            _manual_notification_contract(),
        )
        expected_activity = candidate_match.group('activity')
        if activity != expected_activity:
            raise ValueError(
                'LinkedIn notification candidate postcondition failed: '
                'fresh route does not expose the exact selected activity'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'page',
            'postcondition': 'exact_notification_activity',
            'route_exact': True,
            'activity_exact': True,
            'observed_url': snapshot.url,
        }
    if continuation_match is not None:
        contract = _manual_notification_contract()
        candidates = _notification_candidates(snapshot, contract)
        prior_count = int(continuation_match.group('count'))
        if (
            not _exact_engagement_route(snapshot.url, 'notifications_all')
            or not _notification_categories_exact(snapshot, contract)
            or len(candidates) <= prior_count
        ):
            raise ValueError(
                'LinkedIn notification continuation postcondition failed: '
                'fresh candidate count did not grow on the exact Notifications-All route'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'page',
            'postcondition': 'notification_candidate_count_growth',
            'route_exact': True,
            'prior_candidate_count': prior_count,
            'observed_candidate_count': len(candidates),
            'candidate_count_grew': True,
            'observed_url': snapshot.url,
        }
    if element_key != NOTIFICATIONS_NAVIGATION:
        raise ValueError('LinkedIn post-action element is not declared')
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
    navigation_contract = _manual_post_action_contract()
    notification_contract = _manual_notification_contract()
    if operation != 'activate' or (
        element_key != navigation_contract['element_key']
        and _CANDIDATE_KEY.fullmatch(element_key) is None
        and _CONTINUATION_KEY.fullmatch(element_key) is None
    ):
        raise ValueError('LinkedIn stable post-action observation is not declared')
    if isinstance(deadline_at, bool) or not isinstance(deadline_at, (int, float)):
        raise ValueError('LinkedIn post-action deadline must be monotonic seconds')

    postcondition = (
        navigation_contract['postcondition']
        if element_key == navigation_contract['element_key']
        else element_operation(element_key, ['enabled', 'focusable'])['postcondition']
    )
    barrier = (
        navigation_contract['observation_barrier']
        if element_key == navigation_contract['element_key']
        else notification_contract['observation_barrier']
    )
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
        try:
            exact_receipt = verify_post_action(snapshot, element_key, operation)
        except ValueError:
            exact_receipt = None
        exact = exact_receipt is not None
        stable_cycles_observed = stable_cycles_observed + 1 if exact else 0
        sample = {
            'sample': len(samples) + 1,
            'elapsed_ms': round((time.monotonic() - started_at) * 1000),
            'route_exact': bool(exact_receipt and exact_receipt.get('route_exact')),
            'observed_url': snapshot.url,
        }
        if exact_receipt is not None:
            sample['postcondition'] = exact_receipt['postcondition']
            if 'observed_candidate_count' in exact_receipt:
                sample['observed_candidate_count'] = exact_receipt[
                    'observed_candidate_count'
                ]
        samples.append(sample)
        if stable_cycles_observed >= stable_cycles_required:
            return snapshot, {
                'result': 'PASS',
                'next_mutation_authorized': True,
                'projection': postcondition.get('kind') or postcondition['projection'],
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
        'projection': postcondition.get('kind') or postcondition['projection'],
        'refresh_policy': barrier['refresh_policy'],
        'stable_cycles_required': stable_cycles_required,
        'stable_cycles_observed': stable_cycles_observed,
        'samples': samples,
    }


__all__ = [
    'NOTIFICATION_CANDIDATE_PREFIX',
    'NOTIFICATIONS_NAVIGATION',
    'NOTIFICATIONS_CONTINUATION_PREFIX',
    'augment_snapshot',
    'element_operation',
    'stable_post_action_observation',
    'verify_post_action',
]
