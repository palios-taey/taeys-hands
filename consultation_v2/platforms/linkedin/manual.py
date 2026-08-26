from __future__ import annotations

from dataclasses import replace
import hashlib
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
SELECTED_POST_PREFIX = 'selected_post_activity_'
SELECTED_THREAD_OPEN_PREFIX = 'selected_post_thread_open_activity_'

_CANDIDATE_KEY = re.compile(
    rf'^{NOTIFICATION_CANDIDATE_PREFIX}(?P<ordinal>[0-9]{{3}})_activity_(?P<activity>[0-9]+)$'
)
_CONTINUATION_KEY = re.compile(
    rf'^{NOTIFICATIONS_CONTINUATION_PREFIX}(?P<count>[0-9]+)_(?P<prefix>[0-9a-f]{{16}})$'
)
_SELECTED_POST_KEY = re.compile(
    rf'^{SELECTED_POST_PREFIX}(?P<activity>[0-9]+)$'
)
_SELECTED_THREAD_OPEN_KEY = re.compile(
    rf'^{SELECTED_THREAD_OPEN_PREFIX}(?P<activity>[0-9]+)_body_'
    r'(?P<body>[0-9a-f]{64})$'
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
        'selected_activity_postcondition': {
            'identity_sources': ['document_url', 'showing_link_uri'],
            'showing_link': {
                'role': 'link',
                'states_include': ['showing'],
            },
            'exact_activity_identity_count': 1,
        },
        'selected_post_observation': {
            'element_key_prefix': SELECTED_POST_PREFIX,
            'root': {
                'role': 'list item',
                'states_include': ['showing'],
                'exact_match_count': 1,
            },
            'heading': {
                'index_path': [0, 0],
                'role': 'heading',
                'name': 'Feed post',
            },
            'body': {
                'index_path': [0, 8, 0],
                'role': 'section',
                'states_include': ['showing'],
                'content_digest': 'sha256_utf8',
            },
            'operation': {
                'effect_class': 'observation',
                'primitives': [],
                'allowed_now': [],
            },
        },
        'selected_thread': {
            'open_element_key_prefix': SELECTED_THREAD_OPEN_PREFIX,
            'comment_count': {
                'role': 'push button',
                'index_path': [0, 11],
                'states_include': ['enabled', 'focusable'],
            },
            'visible_comment': {
                'role': 'push button',
                'name_prefix': 'View more options for',
                'name_suffix': 'comment.',
            },
            'action': {
                'effect_class': 'page',
                'primitives': ['activate'],
                'allowed_now': ['activate'],
            },
            'postcondition': 'exact_selected_activity_visible_comment_controls',
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


def _node_at_index_path(node: Any, index_path: list[int]) -> Any | None:
    current = node
    for index in index_path:
        children = _direct_children(current)
        if index < 0 or index >= len(children):
            return None
        current = children[index]
    return current


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


def _selected_activity_identity(
    snapshot: Snapshot,
    contract: dict[str, Any],
) -> tuple[str | None, tuple[str, ...]]:
    postcondition = contract['selected_activity_postcondition']
    sources: dict[str, set[str]] = {
        'document_url': set(),
        'showing_link_uri': set(),
    }
    document_activity = _notification_activity(str(snapshot.url or ''), contract)
    if document_activity is not None:
        sources['document_url'].add(document_activity)

    showing_link = postcondition['showing_link']
    required_states = set(showing_link['states_include'])
    for element in _all_elements(snapshot):
        if (
            element.role != showing_link['role']
            or not required_states.issubset(element.states)
        ):
            continue
        uri = _element_uri(element)
        activity = _notification_activity(uri or '', contract)
        if activity is not None:
            sources['showing_link_uri'].add(activity)

    identities = {
        activity
        for source in postcondition['identity_sources']
        for activity in sources[source]
    }
    if len(identities) != postcondition['exact_activity_identity_count']:
        return None, ()
    identity = next(iter(identities))
    matched_sources = tuple(
        source
        for source in postcondition['identity_sources']
        if identity in sources[source]
    )
    return identity, matched_sources


def _selected_post_root_and_body(
    snapshot: Snapshot,
    contract: dict[str, Any],
) -> tuple[Any | None, Any | None, str | None]:
    observation = contract['selected_post_observation']
    root_contract = observation['root']
    heading_contract = observation['heading']
    body_contract = observation['body']
    elements = _all_elements(snapshot)
    elements_by_identity = {id(element.atspi_obj): element for element in elements}
    roots: list[tuple[Any, Any, str]] = []
    for element in elements:
        if (
            element.role != root_contract['role']
            or not set(root_contract['states_include']).issubset(element.states)
        ):
            continue
        heading = _node_at_index_path(
            element.atspi_obj,
            heading_contract['index_path'],
        )
        body = _node_at_index_path(
            element.atspi_obj,
            body_contract['index_path'],
        )
        if (
            heading is None
            or _node_role(heading) != heading_contract['role']
            or _node_name(heading) != heading_contract['name']
            or body is None
            or _node_role(body) != body_contract['role']
        ):
            continue
        body_element = elements_by_identity.get(id(body))
        if (
            body_element is None
            or not set(body_contract['states_include']).issubset(body_element.states)
        ):
            continue
        text = body_element.text or _node_text(body)
        if text:
            roots.append((element, body_element, text))
    if len(roots) != root_contract['exact_match_count']:
        return None, None, None
    return roots[0]


def _selected_post_descendants(
    snapshot: Snapshot,
    root: Any,
) -> list[tuple[Any, int]]:
    root_path = _structural_index_path(root.atspi_obj)
    descendants: list[tuple[Any, int]] = []
    for element in _all_elements(snapshot):
        path = _structural_index_path(element.atspi_obj)
        if (
            len(path) > len(root_path)
            and path[:len(root_path)] == root_path
        ):
            descendants.append((element, len(path) - len(root_path)))
    return descendants


def _selected_thread_controls(
    snapshot: Snapshot,
    root: Any,
    contract: dict[str, Any],
) -> tuple[list[Any], list[Any]]:
    selected_thread = contract['selected_thread']
    count_contract = selected_thread['comment_count']
    visible_contract = selected_thread['visible_comment']
    required_states = set(count_contract['states_include'])
    comment_counts: list[Any] = []
    visible_comments: list[Any] = []
    count_node = _node_at_index_path(root.atspi_obj, count_contract['index_path'])
    elements_by_identity = {
        id(element.atspi_obj): element for element in _all_elements(snapshot)
    }
    count_element = elements_by_identity.get(id(count_node))
    if count_element is not None:
        count_name = count_element.name
        count_token = (
            count_name.removesuffix(' comments').replace(',', '')
            if count_name.endswith(' comments')
            else '1' if count_name == '1 comment' else ''
        )
        if (
            count_element.role == count_contract['role']
            and count_token.isdigit()
            and int(count_token) > 0
            and required_states.issubset(count_element.states)
        ):
            comment_counts.append(count_element)
    for element, relative_depth in _selected_post_descendants(snapshot, root):
        if (
            relative_depth > 0
            and element.role == visible_contract['role']
            and element.name.startswith(visible_contract['name_prefix'])
            and element.name.endswith(visible_contract['name_suffix'])
        ):
            visible_comments.append(element)
    return comment_counts, visible_comments


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


def _activity_prefix_digest(
    candidates: list[tuple[Any, str, str]],
    count: int | None = None,
) -> str:
    activities = [activity for _element, activity, _age in candidates[:count]]
    return hashlib.sha256('\n'.join(activities).encode('ascii')).hexdigest()[:16]


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
            and not key.startswith(SELECTED_POST_PREFIX)
            and not key.startswith(SELECTED_THREAD_OPEN_PREFIX)
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
            key = (
                f'{NOTIFICATIONS_CONTINUATION_PREFIX}{len(candidates):03d}_'
                f'{_activity_prefix_digest(candidates)}'
            )
            mapped[key] = [replace(
                continuations[0],
                key=key,
                description=(
                    f'continue only after all {len(candidates)} newer candidates '
                    'have evidenced exclusions'
                ),
            )]
    contract = _manual_notification_contract()
    selected_activity, activity_sources = _selected_activity_identity(
        snapshot,
        contract,
    )
    if selected_activity is not None:
        root, body, body_text = _selected_post_root_and_body(snapshot, contract)
        if root is None or body is None or body_text is None:
            raise ValueError(
                'LinkedIn selected activity lacks one exact showing post body'
            )
        body_digest = hashlib.sha256(body_text.encode('utf-8')).hexdigest()
        key = f'{SELECTED_POST_PREFIX}{selected_activity}'
        raw = {
            **dict(body.raw),
            'selected_activity': selected_activity,
            'selected_activity_sources': list(activity_sources),
            'selected_post_body_sha256': body_digest,
        }
        mapped[key] = [replace(
            body,
            key=key,
            name='Selected LinkedIn post body',
            text=body_text,
            description=(
                f'activity={selected_activity}; body_sha256={body_digest}'
            ),
            raw=raw,
        )]
        comment_counts, visible_comments = _selected_thread_controls(
            snapshot,
            root,
            contract,
        )
        if comment_counts and not visible_comments:
            thread_open_key = (
                f'{SELECTED_THREAD_OPEN_PREFIX}{selected_activity}_body_{body_digest}'
            )
            mapped[thread_open_key] = [replace(
                comment_counts[0],
                key=thread_open_key,
                description=(
                    f'activity={selected_activity}; open exact visible thread'
                ),
                raw={
                    **dict(comment_counts[0].raw),
                    'selected_activity': selected_activity,
                    'selected_post_body_sha256': body_digest,
                },
            )]
    return replace(snapshot, mapped=mapped)


def element_operation(
    element_key: str,
    states: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    candidate_match = _CANDIDATE_KEY.fullmatch(element_key)
    continuation_match = _CONTINUATION_KEY.fullmatch(element_key)
    selected_post_match = _SELECTED_POST_KEY.fullmatch(element_key)
    selected_thread_open_match = _SELECTED_THREAD_OPEN_KEY.fullmatch(element_key)
    if (
        element_key != NOTIFICATIONS_NAVIGATION
        and candidate_match is None
        and continuation_match is None
        and selected_post_match is None
        and selected_thread_open_match is None
    ):
        return None
    if selected_post_match is not None:
        selected_context = dict(context or {})
        activity = selected_post_match.group('activity')
        body_text = selected_context.get('text')
        body_digest = selected_context.get('selected_post_body_sha256')
        if (
            selected_context.get('selected_activity') != activity
            or not isinstance(body_text, str)
            or not body_text
            or body_digest != hashlib.sha256(body_text.encode('utf-8')).hexdigest()
        ):
            raise ValueError(
                'LinkedIn selected-post observation identity is not exact'
            )
        operation = _manual_notification_contract()[
            'selected_post_observation'
        ]['operation']
        return {
            'method': 'observe',
            **operation,
            'forbidden': [
                'click',
                'focus',
                'activate',
                'hover',
                'mapped_pointer_activate',
            ],
            'postcondition': {
                'kind': 'exact_selected_post_body',
                'activity': activity,
                'body_sha256': body_digest,
            },
        }
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
    declared_action = (
        _manual_notification_contract()['selected_thread']['action']
        if selected_thread_open_match is not None
        else {
            'effect_class': 'page',
            'primitives': ['activate'],
            'allowed_now': ['activate'],
        }
    )
    return {
        'method': 'activate',
        'effect_class': declared_action['effect_class'],
        'primitives': declared_action['primitives'],
        'allowed_now': allowed_now,
        'forbidden': ['click', 'focus', 'hover', 'mapped_pointer_activate'],
        'postcondition': {
            'kind': (
                'exact_selected_activity_visible_comment_controls'
                if selected_thread_open_match is not None
                else (
                    'exact_notification_activity'
                    if candidate_match is not None
                    else (
                        'notification_candidate_count_growth'
                        if continuation_match is not None
                        else 'exact_document_route'
                    )
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
                {'prior_activity_prefix': continuation_match.group('prefix')}
                if continuation_match is not None
                else {}
            ),
            **(
                {'route_key': 'notifications_all'}
                if element_key == NOTIFICATIONS_NAVIGATION
                else {}
            ),
            **(
                {
                    'activity': selected_thread_open_match.group('activity'),
                    'body_sha256': selected_thread_open_match.group('body'),
                }
                if selected_thread_open_match is not None
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
    selected_thread_open_match = _SELECTED_THREAD_OPEN_KEY.fullmatch(element_key)
    if selected_thread_open_match is not None:
        contract = _manual_notification_contract()
        activity, activity_sources = _selected_activity_identity(snapshot, contract)
        expected_activity = selected_thread_open_match.group('activity')
        expected_body_digest = selected_thread_open_match.group('body')
        root, _body, body_text = _selected_post_root_and_body(snapshot, contract)
        if root is None or body_text is None:
            raise ValueError(
                'LinkedIn selected-thread postcondition lost the exact selected post'
            )
        observed_body_digest = hashlib.sha256(body_text.encode('utf-8')).hexdigest()
        _comment_counts, visible_comments = _selected_thread_controls(
            snapshot,
            root,
            contract,
        )
        if (
            activity != expected_activity
            or observed_body_digest != expected_body_digest
            or not visible_comments
        ):
            raise ValueError(
                'LinkedIn selected-thread postcondition failed: the exact '
                'selected activity/body has no visible comment controls'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'page',
            'postcondition': 'exact_selected_activity_visible_comment_controls',
            'route_exact': True,
            'activity_exact': True,
            'activity_sources': list(activity_sources),
            'selected_post_body_sha256': observed_body_digest,
            'visible_comment_count': len(visible_comments),
            'observed_url': snapshot.url,
        }
    if candidate_match is not None:
        activity, activity_sources = _selected_activity_identity(
            snapshot,
            _manual_notification_contract(),
        )
        expected_activity = candidate_match.group('activity')
        if activity != expected_activity:
            raise ValueError(
                'LinkedIn notification candidate postcondition failed: '
                'fresh surface does not expose one exact selected activity'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'page',
            'postcondition': 'exact_notification_activity',
            'route_exact': True,
            'document_url_exact': 'document_url' in activity_sources,
            'activity_exact': True,
            'activity_sources': list(activity_sources),
            'observed_url': snapshot.url,
        }
    if continuation_match is not None:
        contract = _manual_notification_contract()
        candidates = _notification_candidates(snapshot, contract)
        prior_count = int(continuation_match.group('count'))
        expected_prefix = continuation_match.group('prefix')
        observed_prefix = _activity_prefix_digest(candidates, prior_count)
        if (
            not _exact_engagement_route(snapshot.url, 'notifications_all')
            or not _notification_categories_exact(snapshot, contract)
            or len(candidates) <= prior_count
            or observed_prefix != expected_prefix
        ):
            raise ValueError(
                'LinkedIn notification continuation postcondition failed: '
                'fresh candidate set did not preserve its exact ordered prefix and grow'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'page',
            'postcondition': 'notification_candidate_count_growth',
            'route_exact': True,
            'prior_candidate_count': prior_count,
            'prior_activity_prefix': expected_prefix,
            'observed_activity_prefix': observed_prefix,
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
        and _SELECTED_THREAD_OPEN_KEY.fullmatch(element_key) is None
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
            'activity_exact': bool(
                exact_receipt and exact_receipt.get('activity_exact')
            ),
            'document_url_exact': bool(
                exact_receipt and exact_receipt.get('document_url_exact')
            ),
            'observed_url': snapshot.url,
        }
        if exact_receipt is not None:
            sample['postcondition'] = exact_receipt['postcondition']
            if 'activity_sources' in exact_receipt:
                sample['activity_sources'] = exact_receipt['activity_sources']
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
