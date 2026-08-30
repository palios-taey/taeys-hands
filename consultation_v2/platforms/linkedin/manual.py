from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
import hashlib
import json
import re
import time
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from consultation_v2.platforms.linkedin.driver import (
    _all_elements,
    _element_uri,
    _exact_engagement_route,
    _notifications_target,
    _notifications_target_state_digest,
)
from consultation_v2.platforms import routing as platform_routing
from consultation_v2.snapshot import build_snapshot
from consultation_v2.types import ElementRef, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


NOTIFICATIONS_NAVIGATION = 'notifications_navigation'
NOTIFICATION_CANDIDATE_PREFIX = 'notification_candidate_'
NOTIFICATIONS_CONTINUATION_PREFIX = 'notifications_show_more_'
NOTIFICATIONS_CONTINUATION = 'notifications_show_more_results'
SELECTED_POST_PREFIX = 'selected_post_activity_'
SELECTED_THREAD_OPEN_PREFIX = 'selected_post_thread_open_activity_'
SELECTED_THREAD_ZERO_OPEN_PREFIX = 'selected_post_zero_thread_open_activity_'
SELECTED_THREAD_EXPAND_PREFIX = 'selected_post_thread_expand_activity_'
SELECTED_POST_REACTION_PREFIX = 'selected_post_reaction_activity_'
SELECTED_POST_EDITOR_PREFIX = 'selected_post_editor_activity_'
SELECTED_POST_SUBMIT_PREFIX = 'selected_post_submit_activity_'

_CANDIDATE_KEY = re.compile(
    rf'^{NOTIFICATION_CANDIDATE_PREFIX}(?P<ordinal>[0-9]{{3}})_activity_(?P<activity>[0-9]+)$'
)
_CONTINUATION_KEY = re.compile(
    rf'^{re.escape(NOTIFICATIONS_CONTINUATION)}$'
)
_SELECTED_POST_KEY = re.compile(
    rf'^{SELECTED_POST_PREFIX}(?P<activity>[0-9]+)$'
)
_SELECTED_THREAD_OPEN_KEY = re.compile(
    rf'^{SELECTED_THREAD_OPEN_PREFIX}(?P<activity>[0-9]+)_body_'
    r'(?P<body>[0-9a-f]{64})$'
)
_SELECTED_THREAD_ZERO_OPEN_KEY = re.compile(
    rf'^{SELECTED_THREAD_ZERO_OPEN_PREFIX}(?P<activity>[0-9]+)_body_'
    r'(?P<body>[0-9a-f]{64})$'
)
_SELECTED_THREAD_EXPAND_KEY = re.compile(
    rf'^{SELECTED_THREAD_EXPAND_PREFIX}(?P<activity>[0-9]+)_body_'
    r'(?P<body>[0-9a-f]{64})_total_(?P<total>[1-9][0-9]*)_'
    r'visible_(?P<visible>[1-9][0-9]*)_more_'
    r'(?P<more>[1-9][0-9]*)$'
)
_SELECTED_POST_REACTION_KEY = re.compile(
    rf'^{SELECTED_POST_REACTION_PREFIX}(?P<activity>[0-9]+)_body_'
    r'(?P<body>[0-9a-f]{64})$'
)
_SELECTED_POST_EDITOR_KEY = re.compile(
    rf'^{SELECTED_POST_EDITOR_PREFIX}(?P<activity>[0-9]+)_body_'
    r'(?P<body>[0-9a-f]{64})$'
)
_SELECTED_POST_SUBMIT_KEY = re.compile(
    rf'^{SELECTED_POST_SUBMIT_PREFIX}(?P<activity>[0-9]+)_body_'
    r'(?P<body>[0-9a-f]{64})_draft_(?P<draft>[0-9a-f]{64})$'
)
_RELATIVE_AGE = re.compile(r'^[1-9][0-9]*[smhdw]$')
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_CONTINUATION_PRE_ACTION_SCHEMA = (
    'linkedin_notification_continuation_pre_action_v1'
)
_CONTINUATION_PRE_ACTION: ContextVar[dict[str, Any] | None] = ContextVar(
    'linkedin_notification_continuation_pre_action',
    default=None,
)


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
            'projection': 'exact_route_and_all_category',
            'route_key': 'notifications_all',
        },
        'observation_barrier': {
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 90000,
        },
    }
    if contract != expected:
        raise RuntimeError('LinkedIn manual post-action contract is invalid')
    return dict(contract)


def _initial_preparation_observation_contract() -> dict[str, Any]:
    workflow = load_platform_yaml('linkedin').get('workflow') or {}
    engagement = workflow.get('engagement_signal_capture') or {}
    navigation = engagement.get('navigation') or {}
    contract = navigation.get('initial_observation_barrier')
    expected = {
        'projection': 'exact_notifications_navigation',
        'refresh_policy': 'invalidate_reacquire',
        'stable_cycles': 2,
        'interval_ms': 200,
        'timeout_ms': 120000,
    }
    if contract != expected:
        raise RuntimeError(
            'LinkedIn initial preparation observation contract is invalid'
        )
    return dict(contract)


def _manual_notification_contract() -> dict[str, Any]:
    workflow = load_platform_yaml('linkedin').get('workflow') or {}
    engagement = workflow.get('engagement_signal_capture') or {}
    contract = engagement.get('manual_notification_selection')
    expected = {
        'route_key': 'notifications_all',
        'article_names': ['Notification', 'Notification.', 'Unread notification.'],
        'article_structure': {
            'direct_child_roles_exact': [
                'link',
                'link',
                'paragraph',
                'section',
            ],
            'content_link_direct_child_index': 1,
        },
        'candidate': {
            'role': 'link',
            'states_include': ['enabled', 'focusable'],
            'post_action_observation_barrier': {
                'refresh_policy': 'invalidate_reacquire',
                'stable_cycles': 2,
                'interval_ms': 200,
                'timeout_ms': 180000,
            },
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
            'postcondition': {
                'kind': 'notification_stream_stable_novelty',
                'action_identity': 'stable_semantic_key',
                'identity': 'exact_yaml_content_link_uri',
                'pre_action_freeze': 'exact_live_target_ref_revalidation',
                'frozen_inventory_digest': 'sha256_uri_digests_truncated_16',
                'frozen_inventory_members': 'sha256_uri_digests',
                'novelty': 'at_least_one_exact_unseen_identity',
                'candidate_projection': 'exact_separate',
            },
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
                'structural_order': 'first_feed_post',
                'exact_match_count': 1,
            },
            'heading': {
                'index_path': [0, 0],
                'role': 'heading',
                'name': 'Feed post',
            },
            'body': {
                'index_path_authority': 'first_exact_declared',
                'index_paths': [[0, 8, 0], [0, 9, 0], [0, 12, 0]],
                'role': 'section',
                'states_include': ['enabled'],
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
            'zero_open_element_key_prefix': SELECTED_THREAD_ZERO_OPEN_PREFIX,
            'expand_element_key_prefix': SELECTED_THREAD_EXPAND_PREFIX,
            'comment_count': {
                'role': 'push button',
                'index_paths': [[0, 11], [0, 12], [0, 15]],
                'states_include': ['enabled', 'focusable'],
            },
            'visible_comment': {
                'role': 'push button',
                'name_prefix': 'View more options for',
                'name_suffix': 'comment.',
            },
            'zero_open': {
                'structural_variants': [
                    {
                        'body_index_path': [0, 8, 0],
                        'index_path': [0, 12],
                    },
                    {
                        'body_index_path': [0, 8, 0],
                        'index_path': [0, 14],
                    },
                    {
                        'body_index_path': [0, 9, 0],
                        'index_path': [0, 15],
                    },
                    {
                        'body_index_path': [0, 9, 0],
                        'index_path': [0, 16],
                    },
                    {
                        'body_index_path': [0, 12, 0],
                        'index_path': [0, 19],
                    },
                ],
                'role': 'push button',
                'name': 'Comment',
                'states_include': ['enabled', 'focusable'],
                'action': {
                    'effect_class': 'page',
                    'primitives': ['mapped_pointer_activate'],
                    'allowed_now': ['mapped_pointer_activate'],
                },
                'postcondition': 'exact_selected_activity_zero_comment_thread_open',
            },
            'expand': {
                'role': 'push button',
                'relative_depth': 2,
                'name_prefix': 'See ',
                'name_suffixes': [' more comment', ' more comments'],
                'states_include': ['enabled', 'focusable'],
                'action': {
                    'effect_class': 'page',
                    'primitives': ['mapped_pointer_activate'],
                    'allowed_now': ['mapped_pointer_activate'],
                },
                'postcondition': 'exact_selected_thread_growth',
                'scroll_into_view': {
                    'phase': 'thread_expand_scroll',
                    'effect_class': 'viewport',
                    'primitives': ['scroll_into_view'],
                    'allowed_now': ['scroll_into_view'],
                    'scroll_target': 'selected_thread_expander',
                    'scroll_target_source': 'self',
                    'scroll_alignment': 'anywhere',
                    'postcondition': (
                        'exact_selected_thread_expander_in_viewport'
                    ),
                    'observation_barrier': {
                        'refresh_policy': 'invalidate_reacquire',
                        'stable_cycles': 2,
                        'interval_ms': 200,
                        'timeout_ms': 180000,
                    },
                },
            },
            'action': {
                'effect_class': 'page',
                'primitives': ['mapped_pointer_activate'],
                'allowed_now': ['mapped_pointer_activate'],
            },
            'scroll_into_view': {
                'phase': 'thread_scroll',
                'effect_class': 'viewport',
                'primitives': ['scroll_into_view'],
                'allowed_now': ['scroll_into_view'],
                'scroll_target': 'selected_post_root',
                'scroll_target_source': 'mapped_context',
                'scroll_alignment': 'top_edge',
                'min_downward_clearance_px': 0,
                'postcondition': 'exact_selected_thread_opener_in_viewport',
                'observation_barrier': {
                    'refresh_policy': 'invalidate_reacquire',
                    'stable_cycles': 2,
                    'interval_ms': 200,
                    'timeout_ms': 180000,
                },
            },
            'postcondition': 'exact_selected_activity_visible_comment_controls',
        },
        'observation_barrier': {
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 180000,
        },
    }
    if contract != expected:
        raise RuntimeError('LinkedIn manual notification selection contract is invalid')
    return dict(contract)


def _manual_comment_contract() -> dict[str, Any]:
    workflow = load_platform_yaml('linkedin').get('workflow') or {}
    engagement = workflow.get('engagement_signal_capture') or {}
    contract = engagement.get('manual_comment_composition')
    expected = {
        'selected_post_identity': {
            'activity_source': 'exact_selected_activity',
            'body_digest': 'sha256_utf8',
        },
        'reaction': {
            'element_key_prefix': SELECTED_POST_REACTION_PREFIX,
            'role': 'push button',
            'relative_depth': 2,
            'exact_names': {
                'no_reaction': 'Reaction button state: no reaction',
                'liked': 'Reaction button state: Like',
            },
            'action': {
                'effect_class': 'outward',
                'primitives': ['activate_optional_like'],
                'allowed_now': ['activate_optional_like'],
            },
            'postcondition': 'exact_same_activity_body_reaction_like',
        },
        'editor': {
            'element_key_prefix': SELECTED_POST_EDITOR_PREFIX,
            'name': 'Text editor for creating comment',
            'role': 'entry',
            'relative_depth': 6,
            'states_include': ['editable', 'focusable', 'visible', 'sensitive'],
            'ready_states_include': ['showing'],
            'max_text_chars': 1800,
            'text_child': {
                'role': 'paragraph',
                'parent_text': '\uFFFC',
                'empty_texts': ['Add a comment...', 'Add a comment...\n'],
                'states_include': ['editable', 'visible', 'sensitive'],
            },
            'action': {
                'effect_class': 'draft',
                'primitives': ['paste_frozen_text'],
                'allowed_now': ['paste_frozen_text'],
            },
            'postcondition': 'exact_same_activity_body_editor_text_sha256',
        },
        'submit': {
            'element_key_prefix': SELECTED_POST_SUBMIT_PREFIX,
            'name': 'Comment',
            'role': 'push button',
            'relative_depth': 4,
            'states_include': ['focusable', 'showing', 'visible', 'sensitive'],
            'action': {
                'effect_class': 'outward',
                'primitives': ['submit_frozen_comment'],
                'allowed_now': ['submit_frozen_comment'],
            },
            'precondition': 'exact_unsent_draft_on_same_activity_body',
            'postcondition': 'exact_comment_delivery',
        },
        'own_comment': {
            'control_name_prefix': 'View more options for ',
            'control_name_suffixes': ['\u2019s comment.', '\u2019 comment.'],
            'role': 'push button',
            'relative_depth': 5,
            'states_include': ['enabled', 'focusable'],
            'relative_text': {
                'root_distance': 2,
                'root_role': 'section',
                'child_path': [2, 0, 0, 0],
                'role': 'section',
                'max_text_chars': 1800,
            },
        },
        'observation_barrier': {
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 180000,
        },
    }
    if contract != expected:
        raise RuntimeError('LinkedIn manual comment composition contract is invalid')
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


def _node_exact_text(node: Any, max_chars: int) -> str:
    try:
        import gi

        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi

        text_iface = node.get_text_iface()
        if text_iface is None:
            raise ValueError('LinkedIn exact-text node has no Text interface')
        count = int(Atspi.Text.get_character_count(text_iface))
        if count < 0 or count > max_chars:
            raise ValueError(
                f'LinkedIn exact-text length is outside 0..{max_chars}: {count}'
            )
        return str(Atspi.Text.get_text(text_iface, 0, count) or '')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('LinkedIn exact text is unreadable') from exc


def _node_has_states(node: Any, required: list[str]) -> bool:
    try:
        import gi

        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi

        states = node.get_state_set()
        return all(
            states.contains(getattr(Atspi.StateType, state.upper()))
            for state in required
        )
    except Exception:
        return False


def _comment_editor_text(node: Any, contract: dict[str, Any]) -> str:
    text_child = contract['text_child']
    parent_text = _node_exact_text(node, len(text_child['parent_text']))
    if parent_text != text_child['parent_text']:
        raise ValueError(
            'LinkedIn comment editor parent text no longer matches YAML'
        )
    children = _direct_children(node)
    if len(children) != 1:
        raise ValueError(
            'LinkedIn comment editor must expose one YAML-authorized text child'
        )
    child = children[0]
    if (
        _node_role(child) != text_child['role']
        or not _node_has_states(child, text_child['states_include'])
    ):
        raise ValueError(
            'LinkedIn comment editor text child no longer matches YAML'
        )
    text = _node_exact_text(child, contract['max_text_chars'])
    return '' if text in text_child['empty_texts'] else text


def _comment_relative_text(node: Any, contract: dict[str, Any]) -> str:
    root = node
    for _depth in range(contract['root_distance']):
        try:
            root = root.get_parent()
        except Exception as exc:
            raise ValueError(
                'LinkedIn comment relative-text root is unreadable'
            ) from exc
        if root is None:
            raise ValueError('LinkedIn comment relative-text root is absent')
    if _node_role(root) != contract['root_role']:
        raise ValueError('LinkedIn comment relative-text root role drifted')
    target = _node_at_index_path(root, contract['child_path'])
    if target is None or _node_role(target) != contract['role']:
        raise ValueError('LinkedIn comment relative-text path drifted')
    return _node_exact_text(target, contract['max_text_chars'])


def _validate_frozen_comment_text(text: str, contract: dict[str, Any]) -> str:
    if not isinstance(text, str) or not text:
        raise ValueError('LinkedIn frozen comment text must be non-empty')
    if len(text) > contract['editor']['max_text_chars']:
        raise ValueError('LinkedIn frozen comment text exceeds the YAML maximum')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _validate_private_author_name(author_name: str) -> str:
    if (
        not isinstance(author_name, str)
        or not author_name
        or author_name != author_name.strip()
        or len(author_name) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in author_name)
    ):
        raise ValueError('LinkedIn private comment author name is invalid')
    return author_name


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


def _notification_article_content_link(
    article: ElementRef,
    elements_by_identity: dict[int, ElementRef],
    contract: dict[str, Any],
) -> tuple[ElementRef, str]:
    structure = contract['article_structure']
    children = _direct_children(article.atspi_obj)
    observed_roles = [_node_role(child) for child in children]
    expected_roles = structure['direct_child_roles_exact']
    if observed_roles != expected_roles:
        raise ValueError(
            'LinkedIn mounted notification direct-child role vector is not exact'
        )
    content_index = structure['content_link_direct_child_index']
    if (
        not isinstance(content_index, int)
        or isinstance(content_index, bool)
        or content_index < 0
        or content_index >= len(children)
    ):
        raise ValueError(
            'LinkedIn mounted notification content-link index is invalid'
        )
    content_node = children[content_index]
    content_link = elements_by_identity.get(id(content_node))
    if (
        content_link is None
        or content_link.role != 'link'
        or content_link.atspi_obj is None
        or id(content_link.atspi_obj) != id(content_node)
    ):
        raise ValueError(
            'LinkedIn mounted notification content link is not canonically mapped'
        )
    uri = _element_uri(content_link)
    if (
        not isinstance(uri, str)
        or not uri
        or uri != uri.strip()
        or any(character.isspace() for character in uri)
        or urlsplit(uri).scheme not in {'http', 'https'}
        or not urlsplit(uri).hostname
    ):
        raise ValueError(
            'LinkedIn mounted notification lacks one exact absolute content URI'
        )
    return content_link, uri


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
    roots_by_path: dict[tuple[int, ...], Any] = {}
    for element in elements:
        node = element.atspi_obj
        for _depth in range(64):
            if node is None:
                break
            if _node_role(node) == root_contract['role']:
                heading = _node_at_index_path(
                    node,
                    heading_contract['index_path'],
                )
                if (
                    heading is not None
                    and _node_role(heading) == heading_contract['role']
                    and _node_name(heading) == heading_contract['name']
                ):
                    roots_by_path[_structural_index_path(node)] = node
                    break
            try:
                node = node.get_parent()
            except Exception:
                break
    if root_contract['structural_order'] != 'first_feed_post':
        raise ValueError('LinkedIn selected-post structural order is not declared')
    ordered_roots = [roots_by_path[path] for path in sorted(roots_by_path)]
    selected_roots = ordered_roots[:1]
    if len(selected_roots) != root_contract['exact_match_count']:
        return None, None, None
    root_node = selected_roots[0]
    if body_contract['index_path_authority'] != 'first_exact_declared':
        raise ValueError('LinkedIn selected-post body path authority is invalid')
    bodies: list[tuple[Any, Any, str]] = []
    for index_path in body_contract['index_paths']:
        body_node = _node_at_index_path(root_node, index_path)
        if (
            body_node is None
            or _node_role(body_node) != body_contract['role']
            or not _node_has_states(body_node, body_contract['states_include'])
        ):
            continue
        body_element = elements_by_identity.get(id(body_node)) or ElementRef(
            key=None,
            name=_node_name(body_node),
            role=_node_role(body_node),
            x=None,
            y=None,
            states=list(body_contract['states_include']),
            text=None,
            atspi_obj=body_node,
            raw={},
        )
        text = _node_text(body_node) or body_element.text
        if text:
            bodies.append((body_node, body_element, text))
            break
    if len(bodies) != 1:
        return None, None, None
    root_element = elements_by_identity.get(id(root_node)) or ElementRef(
        key=None,
        name=_node_name(root_node),
        role=_node_role(root_node),
        x=None,
        y=None,
        states=[],
        text=None,
        atspi_obj=root_node,
        raw={},
    )
    _body_node, body_element, text = bodies[0]
    return root_element, body_element, text


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


def _selected_comment_controls(
    snapshot: Snapshot,
    root: Any,
    contract: dict[str, Any],
) -> dict[str, Any]:
    descendants = _selected_post_descendants(snapshot, root)
    reaction_contract = contract['reaction']
    reaction_candidates = [
        element
        for element, depth in descendants
        if (
            depth == reaction_contract['relative_depth']
            and element.role == reaction_contract['role']
            and element.name.startswith('Reaction button state:')
        )
    ]
    allowed_reaction_names = set(reaction_contract['exact_names'].values())
    if any(
        element.name not in allowed_reaction_names
        for element in reaction_candidates
    ):
        raise ValueError('LinkedIn selected-post reaction state is not declared')
    if len(reaction_candidates) > 1:
        raise ValueError('LinkedIn selected-post reaction control is ambiguous')

    editor_contract = contract['editor']
    editor_candidates = [
        element
        for element, depth in descendants
        if (
            depth == editor_contract['relative_depth']
            and element.name == editor_contract['name']
            and element.role == editor_contract['role']
        )
    ]
    if len(editor_candidates) > 1:
        raise ValueError('LinkedIn selected-post comment editor is ambiguous')
    editor_candidate = editor_candidates[0] if editor_candidates else None
    editor = (
        editor_candidate
        if editor_candidate is not None
        and _node_has_states(
            editor_candidate.atspi_obj,
            editor_contract['states_include'],
        )
        else None
    )
    editor_text: str | None = None
    editor_ready = False
    if editor is not None:
        editor_text = _comment_editor_text(editor.atspi_obj, editor_contract)
        editor_ready = _node_has_states(
            editor.atspi_obj,
            editor_contract['states_include']
            + editor_contract['ready_states_include'],
        )

    submit_contract = contract['submit']
    submit_candidates = [
        element
        for element, depth in descendants
        if (
            depth == submit_contract['relative_depth']
            and element.name == submit_contract['name']
            and element.role == submit_contract['role']
        )
    ]
    if len(submit_candidates) > 1:
        raise ValueError('LinkedIn selected-post comment submit is ambiguous')
    submit_candidate = submit_candidates[0] if submit_candidates else None
    submit = (
        submit_candidate
        if submit_candidate is not None
        and _node_has_states(
            submit_candidate.atspi_obj,
            submit_contract['states_include'],
        )
        else None
    )
    if editor_text and submit is None:
        raise ValueError(
            'LinkedIn non-empty comment editor lacks one ready same-card submit'
        )

    own_contract = contract['own_comment']
    comment_controls = [
        element
        for element, depth in descendants
        if (
            depth == own_contract['relative_depth']
            and element.role == own_contract['role']
            and element.name.startswith(own_contract['control_name_prefix'])
            and any(
                element.name.endswith(suffix)
                for suffix in own_contract['control_name_suffixes']
            )
            and set(own_contract['states_include']).issubset(element.states)
        )
    ]
    return {
        'reaction': reaction_candidates[0] if reaction_candidates else None,
        'editor': editor,
        'editor_text': editor_text,
        'editor_ready': editor_ready,
        'submit': submit,
        'comment_controls': comment_controls,
    }


def _selected_comment_surface(snapshot: Snapshot) -> dict[str, Any]:
    notification_contract = _manual_notification_contract()
    comment_contract = _manual_comment_contract()
    activity, activity_sources = _selected_activity_identity(
        snapshot,
        notification_contract,
    )
    if activity is None:
        raise ValueError('LinkedIn comment surface lacks one exact activity')
    root, _body, body_text = _selected_post_root_and_body(
        snapshot,
        notification_contract,
    )
    if root is None or body_text is None:
        raise ValueError('LinkedIn comment surface lacks one exact post body')
    body_sha256 = hashlib.sha256(body_text.encode('utf-8')).hexdigest()
    return {
        'activity': activity,
        'activity_sources': activity_sources,
        'body_sha256': body_sha256,
        'root': root,
        'controls': _selected_comment_controls(
            snapshot,
            root,
            comment_contract,
        ),
        'contract': comment_contract,
    }


def _exact_own_comment_count(
    surface: dict[str, Any],
    expected_author_name: str,
    expected_text: str,
) -> int:
    author_name = _validate_private_author_name(expected_author_name)
    own_contract = surface['contract']['own_comment']
    expected_names = {
        f"{own_contract['control_name_prefix']}{author_name}{suffix}"
        for suffix in own_contract['control_name_suffixes']
    }
    matches = [
        element
        for element in surface['controls']['comment_controls']
        if (
            element.name in expected_names
            and _comment_relative_text(
                element.atspi_obj,
                own_contract['relative_text'],
            ) == expected_text
        )
    ]
    return len(matches)


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
    elements_by_identity = {
        id(element.atspi_obj): element for element in _all_elements(snapshot)
    }
    for index_path in count_contract['index_paths']:
        count_node = _node_at_index_path(root.atspi_obj, index_path)
        count_element = elements_by_identity.get(id(count_node))
        if count_element is None:
            continue
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


def _selected_thread_failure_evidence(
    snapshot: Snapshot,
    expected_activity: str,
    expected_body_sha256: str,
) -> dict[str, Any]:
    contract = _manual_notification_contract()
    activity, activity_sources = _selected_activity_identity(snapshot, contract)
    root, _body, body_text = _selected_post_root_and_body(snapshot, contract)
    evidence: dict[str, Any] = {
        'expected_activity': expected_activity,
        'observed_activity': activity,
        'activity_exact': activity == expected_activity,
        'activity_sources': list(activity_sources),
        'expected_body_sha256': expected_body_sha256,
        'selected_post_root_found': root is not None,
        'selected_post_body_found': body_text is not None,
    }
    if root is None or body_text is None:
        return evidence

    observed_body_sha256 = hashlib.sha256(body_text.encode('utf-8')).hexdigest()
    selected_thread = contract['selected_thread']
    count_contract = selected_thread['comment_count']
    visible_contract = selected_thread['visible_comment']
    zero_contract = selected_thread['zero_open']
    expand_contract = selected_thread['expand']
    comment_contract = _manual_comment_contract()
    editor_contract = comment_contract['editor']
    submit_contract = comment_contract['submit']
    mapped_keys_by_identity: dict[int, list[str]] = {}
    for key, matches in snapshot.mapped.items():
        for match in matches:
            if match.atspi_obj is not None:
                mapped_keys_by_identity.setdefault(id(match.atspi_obj), []).append(key)

    candidates: list[dict[str, Any]] = []
    for element, relative_depth in _selected_post_descendants(snapshot, root):
        name = element.name or ''
        if 'comment' not in name.lower():
            continue
        candidate = {
            'relative_depth': relative_depth,
            'structural_path': list(_structural_index_path(element.atspi_obj)),
            'role': element.role,
            'states': sorted(element.states),
            'x': element.x,
            'y': element.y,
            'name_sha256': hashlib.sha256(name.encode('utf-8')).hexdigest(),
            'name_chars': len(name),
            'mapped_keys': sorted(mapped_keys_by_identity.get(id(element.atspi_obj), [])),
            'name_has_comment_token': True,
            'matches_visible_comment_shape': bool(
                element.role == visible_contract['role']
                and name.startswith(visible_contract['name_prefix'])
                and name.endswith(visible_contract['name_suffix'])
            ),
            'matches_count_role': element.role == count_contract['role'],
            'matches_zero_open_shape': bool(
                element.role == zero_contract['role']
                and name == zero_contract['name']
            ),
            'matches_editor_shape': bool(
                relative_depth == editor_contract['relative_depth']
                and element.role == editor_contract['role']
                and name == editor_contract['name']
            ),
            'matches_submit_shape': bool(
                relative_depth == submit_contract['relative_depth']
                and element.role == submit_contract['role']
                and name == submit_contract['name']
            ),
            'matches_expand_shape': bool(
                relative_depth == expand_contract['relative_depth']
                and element.role == expand_contract['role']
                and name.startswith(expand_contract['name_prefix'])
                and any(name.endswith(suffix) for suffix in expand_contract['name_suffixes'])
            ),
            'viewport': _selected_thread_viewport_state({
                'atspi_obj': element.atspi_obj,
            }),
        }
        candidates.append(candidate)

    count_paths: list[dict[str, Any]] = []
    elements_by_identity = {
        id(element.atspi_obj): element for element in _all_elements(snapshot)
    }
    required_count_states = set(count_contract['states_include'])
    for index_path in count_contract['index_paths']:
        count_node = _node_at_index_path(root.atspi_obj, index_path)
        count_element = elements_by_identity.get(id(count_node))
        row: dict[str, Any] = {
            'index_path': list(index_path),
            'node_found': count_node is not None,
            'canonically_mapped': count_element is not None,
        }
        if count_element is not None:
            count_name = count_element.name or ''
            count_token = (
                count_name.removesuffix(' comments').replace(',', '')
                if count_name.endswith(' comments')
                else '1' if count_name == '1 comment' else ''
            )
            row.update({
                'role': count_element.role,
                'states': sorted(count_element.states),
                'name_sha256': hashlib.sha256(
                    count_name.encode('utf-8')
                ).hexdigest(),
                'name_chars': len(count_name),
                'count_token': int(count_token) if count_token.isdigit() else None,
                'role_exact': count_element.role == count_contract['role'],
                'states_exact': required_count_states.issubset(
                    count_element.states
                ),
                'viewport': _selected_thread_viewport_state({
                    'atspi_obj': count_element.atspi_obj,
                }),
            })
        count_paths.append(row)

    candidates_sha256 = hashlib.sha256(json.dumps(
        candidates,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')).hexdigest()
    evidence.update({
        'observed_body_sha256': observed_body_sha256,
        'body_exact': observed_body_sha256 == expected_body_sha256,
        'selected_post_structural_path': list(
            _structural_index_path(root.atspi_obj)
        ),
        'selected_post_viewport': _selected_thread_viewport_state({
            'atspi_obj': root.atspi_obj,
        }),
        'selected_post_descendant_count': len(
            _selected_post_descendants(snapshot, root)
        ),
        'comment_named_candidate_count': len(candidates),
        'comment_named_candidates_sha256': candidates_sha256,
        'comment_named_candidates': candidates,
        'comment_count_paths': count_paths,
    })
    return evidence


def _selected_thread_zero_is_exact(
    snapshot: Snapshot,
    root: Any,
    contract: dict[str, Any],
) -> bool:
    count_controls, visible_comments = _selected_thread_controls(
        snapshot,
        root,
        contract,
    )
    if count_controls or visible_comments:
        return False
    selected_thread = contract['selected_thread']
    zero_contract = selected_thread['zero_open']
    body_contract = contract['selected_post_observation']['body']
    exact_variants = []
    for variant in zero_contract['structural_variants']:
        body = _node_at_index_path(
            root.atspi_obj,
            variant['body_index_path'],
        )
        zero_node = _node_at_index_path(
            root.atspi_obj,
            variant['index_path'],
        )
        if (
            body is not None
            and _node_role(body) == body_contract['role']
            and zero_node is not None
            and _node_role(zero_node) == zero_contract['role']
            and _node_name(zero_node) == zero_contract['name']
            and _node_has_states(zero_node, zero_contract['states_include'])
        ):
            exact_variants.append((variant, zero_node))
    if len(exact_variants) != 1:
        return False
    _variant, zero_node = exact_variants[0]
    elements_by_identity = {
        id(element.atspi_obj): element for element in _all_elements(snapshot)
    }
    for count_path in selected_thread['comment_count']['index_paths']:
        count_node = _node_at_index_path(root.atspi_obj, count_path)
        count_element = elements_by_identity.get(id(count_node))
        if count_element is None or id(count_node) == id(zero_node):
            continue
        count_name = count_element.name
        count_token = (
            count_name.removesuffix(' comments').replace(',', '')
            if count_name.endswith(' comments')
            else '1' if count_name == '1 comment' else ''
        )
        if (
            (
                count_element.role == selected_thread['comment_count']['role']
                and count_token.isdigit()
                and int(count_token) > 0
            )
            or 'comment' in count_element.name.lower()
        ):
            return False
    for element, _depth in _selected_post_descendants(snapshot, root):
        count_name = element.name
        count_token = (
            count_name.removesuffix(' comments').replace(',', '')
            if count_name.endswith(' comments')
            else '1' if count_name == '1 comment' else ''
        )
        if (
            element.role == selected_thread['comment_count']['role']
            and count_token.isdigit()
            and int(count_token) > 0
        ):
            return False
    return not _selected_thread_grammatical_expanders(
        snapshot,
        root,
        contract,
    )


def _selected_zero_thread_opener(
    snapshot: Snapshot,
    root: Any,
    contract: dict[str, Any],
) -> Any | None:
    zero_contract = contract['selected_thread']['zero_open']
    if not _selected_thread_zero_is_exact(snapshot, root, contract):
        return None
    nodes = [
        node
        for variant in zero_contract['structural_variants']
        for node in (
            _node_at_index_path(root.atspi_obj, variant['index_path']),
        )
        if (
            node is not None
            and _node_role(node) == zero_contract['role']
            and _node_name(node) == zero_contract['name']
            and _node_has_states(node, zero_contract['states_include'])
        )
    ]
    if len(nodes) != 1:
        return None
    node = nodes[0]
    elements_by_identity = {
        id(element.atspi_obj): element for element in _all_elements(snapshot)
    }
    element = elements_by_identity.get(id(node))
    exact_candidates = [
        candidate
        for candidate, _depth in _selected_post_descendants(snapshot, root)
        if (
            candidate.role == zero_contract['role']
            and candidate.name == zero_contract['name']
            and set(zero_contract['states_include']).issubset(candidate.states)
        )
    ]
    comment_controls = _selected_comment_controls(
        snapshot,
        root,
        _manual_comment_contract(),
    )
    if (
        element is None
        or len(exact_candidates) != 1
        or id(exact_candidates[0].atspi_obj) != id(element.atspi_obj)
        or element.role != zero_contract['role']
        or element.name != zero_contract['name']
        or not set(zero_contract['states_include']).issubset(element.states)
        or comment_controls['editor_ready'] is True
    ):
        return None
    return element


def _selected_thread_grammatical_expanders(
    snapshot: Snapshot,
    root: Any,
    contract: dict[str, Any],
) -> list[tuple[Any, int]]:
    expand_contract = contract['selected_thread']['expand']
    prefix = expand_contract['name_prefix']
    suffixes = expand_contract['name_suffixes']
    matches: list[tuple[Any, int]] = []
    for element, relative_depth in _selected_post_descendants(snapshot, root):
        if (
            relative_depth != expand_contract['relative_depth']
            or element.role != expand_contract['role']
            or not element.name.startswith(prefix)
        ):
            continue
        matched_suffixes = [
            suffix for suffix in suffixes if element.name.endswith(suffix)
        ]
        if len(matched_suffixes) != 1:
            continue
        suffix = matched_suffixes[0]
        token = element.name[len(prefix):-len(suffix)].replace(',', '')
        if not token.isdigit() or int(token) <= 0:
            continue
        count = int(token)
        if (
            (count == 1 and suffix != ' more comment')
            or (count != 1 and suffix != ' more comments')
        ):
            continue
        matches.append((element, count))
    return matches


def _selected_thread_expander(
    snapshot: Snapshot,
    root: Any,
    contract: dict[str, Any],
) -> tuple[Any | None, int | None]:
    required_states = set(
        contract['selected_thread']['expand']['states_include']
    )
    matches = [
        match
        for match in _selected_thread_grammatical_expanders(
            snapshot,
            root,
            contract,
        )
        if required_states.issubset(match[0].states)
    ]
    if len(matches) > 1:
        raise ValueError('LinkedIn selected-thread expansion target is ambiguous')
    return matches[0] if matches else (None, None)


def _selected_thread_typed_rows(
    visible_comments: list[Any],
    comment_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    ordered = list(visible_comments)
    ordered.sort(key=lambda item: _structural_index_path(item.atspi_obj))
    prefix = comment_contract['control_name_prefix']
    suffixes = comment_contract['control_name_suffixes']
    rows: list[dict[str, Any]] = []
    for ordinal, control in enumerate(ordered, 1):
        matched_suffixes = [
            suffix for suffix in suffixes if control.name.endswith(suffix)
        ]
        if not control.name.startswith(prefix) or len(matched_suffixes) != 1:
            raise ValueError(
                'LinkedIn selected thread comment control name is not exact'
            )
        suffix = matched_suffixes[0]
        author = _validate_private_author_name(
            control.name[len(prefix):-len(suffix)]
        )
        text = _comment_relative_text(
            control.atspi_obj,
            comment_contract['relative_text'],
        )
        if '\x00' in text:
            raise ValueError('LinkedIn selected thread comment text contains NUL')
        rows.append({
            'author_name': author,
            'kind': 'text' if text else 'media_link_only',
            'ordinal': ordinal,
            'text': text,
            'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        })
    return rows


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
    elements = _all_elements(snapshot)
    elements_by_identity = {
        id(element.atspi_obj): element
        for element in elements
        if element.atspi_obj is not None
    }
    articles = [
        element
        for element in elements
        if element.role == 'article' and element.name in contract['article_names']
    ]
    articles.sort(key=lambda element: _structural_index_path(element.atspi_obj))
    candidates: list[tuple[Any, str, str]] = []
    for article in articles:
        element, uri = _notification_article_content_link(
            article,
            elements_by_identity,
            contract,
        )
        activity = _notification_activity(uri, contract)
        age = _notification_relative_age(element, contract)
        if age is None:
            raise ValueError(
                'LinkedIn mounted notification lacks one exact relative age'
            )
        if (
            activity is None
            or element.role != candidate_contract['role']
            or not set(candidate_contract['states_include']).issubset(
                element.states
            )
        ):
            continue
        candidates.append((element, activity, age))
    activities = [activity for _element, activity, _age in candidates]
    if len(activities) != len(set(activities)):
        raise ValueError('LinkedIn mounted notification activity identities are duplicated')
    return candidates


def _notification_stream_uri_digests(
    snapshot: Snapshot,
    contract: dict[str, Any],
) -> list[str]:
    elements = _all_elements(snapshot)
    elements_by_identity = {
        id(element.atspi_obj): element
        for element in elements
        if element.atspi_obj is not None
    }
    articles = [
        element
        for element in elements
        if element.role == 'article' and element.name in contract['article_names']
    ]
    if not articles:
        raise ValueError('LinkedIn Notifications-All exposes no mounted articles')
    articles.sort(key=lambda element: _structural_index_path(element.atspi_obj))
    seen_paths: set[tuple[int, ...]] = set()
    uri_digests: list[str] = []
    for article in articles:
        structural_path = _structural_index_path(article.atspi_obj)
        if structural_path in seen_paths:
            raise ValueError(
                'LinkedIn mounted notification structural paths are duplicated'
            )
        seen_paths.add(structural_path)
        _content_link, uri = _notification_article_content_link(
            article,
            elements_by_identity,
            contract,
        )
        uri_digests.append(hashlib.sha256(uri.encode('utf-8')).hexdigest())
    return uri_digests


def _notification_stream_prefix_digest(
    uri_digests: list[str],
    count: int | None = None,
) -> str:
    return hashlib.sha256(
        '\n'.join(uri_digests[:count]).encode('ascii')
    ).hexdigest()[:16]


def _continuation_context_sha256(value: Mapping[str, Any]) -> str:
    payload = {
        key: item
        for key, item in value.items()
        if key != 'context_sha256'
    }
    return hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')).hexdigest()


def _validate_notification_continuation_context(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected_keys = {
        'action_element',
        'action_operation',
        'action_ref_sha256',
        'context_sha256',
        'pre_action_candidate_count',
        'prior_notification_identity_digests',
        'prior_raw_notification_count',
        'prior_raw_notification_prefix',
        'schema',
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise ValueError(
            'LinkedIn continuation pre-action context fields are not exact'
        )
    frozen = dict(value)
    members = frozen.get('prior_notification_identity_digests')
    count = frozen.get('prior_raw_notification_count')
    candidate_count = frozen.get('pre_action_candidate_count')
    if (
        frozen.get('schema') != _CONTINUATION_PRE_ACTION_SCHEMA
        or frozen.get('action_element') != NOTIFICATIONS_CONTINUATION
        or frozen.get('action_operation') != 'activate'
        or _SHA256.fullmatch(str(frozen.get('action_ref_sha256') or '')) is None
        or not isinstance(members, list)
        or not members
        or not all(
            isinstance(member, str) and _SHA256.fullmatch(member) is not None
            for member in members
        )
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(members)
        or frozen.get('prior_raw_notification_prefix')
        != _notification_stream_prefix_digest(members)
        or isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count < 0
        or _SHA256.fullmatch(str(frozen.get('context_sha256') or '')) is None
        or frozen.get('context_sha256') != _continuation_context_sha256(frozen)
    ):
        raise ValueError(
            'LinkedIn continuation pre-action context is invalid'
        )
    frozen['prior_notification_identity_digests'] = list(members)
    return frozen


def _freeze_notification_continuation_context(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    if _CONTINUATION_PRE_ACTION.get() is not None:
        raise ValueError(
            'LinkedIn continuation pre-action context is already live'
        )
    if (
        context.get('element') != NOTIFICATIONS_CONTINUATION
        or not isinstance(context.get('ref'), str)
        or not context.get('ref')
    ):
        raise ValueError(
            'LinkedIn continuation freeze requires the re-resolved target/ref'
        )
    members = context.get('notification_stream_uri_digests')
    count = context.get('notification_stream_count')
    prefix = context.get('notification_stream_prefix')
    candidate_count = context.get('notification_candidate_count')
    if (
        not isinstance(members, list)
        or not members
        or not all(
            isinstance(member, str) and _SHA256.fullmatch(member) is not None
            for member in members
        )
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(members)
        or prefix != _notification_stream_prefix_digest(members)
        or isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count < 0
    ):
        raise ValueError(
            'LinkedIn continuation target lacks exact live inventory'
        )
    frozen = {
        'schema': _CONTINUATION_PRE_ACTION_SCHEMA,
        'action_element': NOTIFICATIONS_CONTINUATION,
        'action_operation': 'activate',
        'action_ref_sha256': hashlib.sha256(
            context['ref'].encode('utf-8')
        ).hexdigest(),
        'prior_raw_notification_count': count,
        'prior_raw_notification_prefix': prefix,
        'prior_notification_identity_digests': list(members),
        'pre_action_candidate_count': candidate_count,
    }
    frozen['context_sha256'] = _continuation_context_sha256(frozen)
    validated = _validate_notification_continuation_context(frozen)
    _CONTINUATION_PRE_ACTION.set(validated)
    return dict(validated)


def _consume_notification_continuation_context(
    element_key: str,
    operation: str,
) -> dict[str, Any]:
    frozen = _CONTINUATION_PRE_ACTION.get()
    _CONTINUATION_PRE_ACTION.set(None)
    if frozen is None:
        raise ValueError(
            'LinkedIn continuation has no one-shot pre-action context'
        )
    validated = _validate_notification_continuation_context(frozen)
    if (
        validated['action_element'] != element_key
        or validated['action_operation'] != operation
    ):
        raise ValueError(
            'LinkedIn continuation pre-action context does not match the action'
        )
    return validated


def _notification_continuation_measurement(
    snapshot: Snapshot,
    pre_action_context: Mapping[str, Any],
) -> dict[str, Any]:
    contract = _manual_notification_contract()
    frozen = _validate_notification_continuation_context(pre_action_context)
    prior_raw_count = frozen['prior_raw_notification_count']
    prior_raw_prefix = frozen['prior_raw_notification_prefix']
    prior_uri_digests = frozen['prior_notification_identity_digests']
    observed_raw_count: int | None = None
    observed_raw_prefix: str | None = None
    observed_raw_inventory_digest: str | None = None
    stream_projection_error: str | None = None
    try:
        uri_digests = _notification_stream_uri_digests(snapshot, contract)
        observed_raw_count = len(uri_digests)
        observed_raw_prefix = _notification_stream_prefix_digest(
            uri_digests,
            prior_raw_count,
        )
        observed_raw_inventory_digest = _notification_stream_prefix_digest(
            uri_digests
        )
    except ValueError as exc:
        stream_projection_error = str(exc)

    observed_candidate_count: int | None = None
    candidate_projection_error: str | None = None
    try:
        observed_candidate_count = len(_notification_candidates(snapshot, contract))
    except ValueError as exc:
        candidate_projection_error = str(exc)

    route_exact = _exact_engagement_route(snapshot.url, 'notifications_all')
    category_exact = _notification_categories_exact(snapshot, contract)
    raw_count_grew = (
        observed_raw_count is not None and observed_raw_count > prior_raw_count
    )
    raw_prefix_exact = observed_raw_prefix == prior_raw_prefix
    raw_inventory_changed = (
        observed_raw_inventory_digest is not None
        and (
            observed_raw_count != prior_raw_count
            or observed_raw_inventory_digest != prior_raw_prefix
        )
    )
    prior_uri_digest_set = set(prior_uri_digests)
    observed_novel_uri_digests = (
        [
            digest
            for digest in uri_digests
            if digest not in prior_uri_digest_set
        ]
        if stream_projection_error is None
        else []
    )
    raw_inventory_novelty_exact = bool(observed_novel_uri_digests)
    failures = [
        name
        for name, passed in (
            ('route', route_exact),
            ('raw_stream_projection', stream_projection_error is None),
            ('raw_inventory_novelty', raw_inventory_novelty_exact),
            ('candidate_projection', candidate_projection_error is None),
        )
        if not passed
    ]
    return {
        'pre_action_context_sha256': frozen['context_sha256'],
        'pre_action_ref_sha256': frozen['action_ref_sha256'],
        'pre_action_candidate_count': frozen['pre_action_candidate_count'],
        'route_exact': route_exact,
        'category_exact': category_exact,
        'raw_stream_projection_exact': stream_projection_error is None,
        'prior_raw_notification_count': prior_raw_count,
        'observed_raw_notification_count': observed_raw_count,
        'raw_notification_count_grew': raw_count_grew,
        'prior_raw_notification_prefix': prior_raw_prefix,
        'observed_raw_notification_prefix': observed_raw_prefix,
        'raw_notification_prefix_exact': raw_prefix_exact,
        'observed_raw_notification_inventory_digest': (
            observed_raw_inventory_digest
        ),
        'raw_notification_inventory_changed': raw_inventory_changed,
        'observed_novel_notification_identity_count': len(
            observed_novel_uri_digests
        ),
        'observed_novel_notification_identity_digests': (
            observed_novel_uri_digests
        ),
        'raw_notification_inventory_novelty_exact': (
            raw_inventory_novelty_exact
        ),
        'candidate_projection_exact': candidate_projection_error is None,
        'observed_candidate_count': observed_candidate_count,
        'postcondition_matched': not failures,
        'failed_components': failures,
        **(
            {'raw_stream_projection_error': stream_projection_error}
            if stream_projection_error is not None
            else {}
        ),
        **(
            {'candidate_projection_error': candidate_projection_error}
            if candidate_projection_error is not None
            else {}
        ),
        'observed_url': snapshot.url,
    }


def _notification_continuation_receipt(
    element_key: str,
    operation: str,
    measurement: dict[str, Any],
) -> dict[str, Any]:
    if not measurement['postcondition_matched']:
        raise ValueError(
            'LinkedIn notification continuation postcondition failed: '
            + ','.join(measurement['failed_components'])
        )
    return {
        'element_key': element_key,
        'operation': operation,
        'effect_class': 'page',
        'postcondition': _manual_notification_contract()['continuation'][
            'postcondition'
        ]['kind'],
        **measurement,
    }


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
            and not key.startswith(SELECTED_THREAD_ZERO_OPEN_PREFIX)
            and not key.startswith(SELECTED_THREAD_EXPAND_PREFIX)
            and not key.startswith(SELECTED_POST_REACTION_PREFIX)
            and not key.startswith(SELECTED_POST_EDITOR_PREFIX)
            and not key.startswith(SELECTED_POST_SUBMIT_PREFIX)
        )
    }
    mapped[NOTIFICATIONS_NAVIGATION] = (
        [replace(target, key=NOTIFICATIONS_NAVIGATION)]
        if target is not None
        else []
    )
    contract = _manual_notification_contract()
    if _exact_engagement_route(snapshot.url, 'notifications_all'):
        uri_digests = _notification_stream_uri_digests(snapshot, contract)
        candidates = _notification_candidates(snapshot, contract)
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
            mapped[NOTIFICATIONS_CONTINUATION] = [replace(
                continuations[0],
                key=NOTIFICATIONS_CONTINUATION,
                x=None,
                y=None,
                description=(
                    'continue only with exact inventory-bound exclusions '
                    'for every mounted actionable candidate'
                ),
                raw={
                    **dict(continuations[0].raw),
                    'notification_stream_count': len(uri_digests),
                    'notification_stream_prefix': (
                        _notification_stream_prefix_digest(uri_digests)
                    ),
                    'notification_stream_uri_digests': list(uri_digests),
                    'notification_candidate_count': len(candidates),
                },
            )]
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
    selected_activity, activity_sources = _selected_activity_identity(
        snapshot,
        contract,
    )
    if selected_activity is not None:
        root, body, body_text = _selected_post_root_and_body(snapshot, contract)
        if root is None or body is None or body_text is None:
            return replace(snapshot, mapped=mapped)
        selected_document = _selected_post_document(root)
        if selected_document is None:
            raise ValueError(
                'LinkedIn selected post lacks one exact document-web ancestor'
            )
        body_digest = hashlib.sha256(body_text.encode('utf-8')).hexdigest()
        comment_contract = _manual_comment_contract()
        comment_controls = _selected_comment_controls(
            snapshot,
            root,
            comment_contract,
        )
        reaction = comment_controls['reaction']
        reaction_state = None
        if reaction is not None:
            reaction_state = next(
                state
                for state, exact_name in comment_contract['reaction'][
                    'exact_names'
                ].items()
                if reaction.name == exact_name
            )
        key = f'{SELECTED_POST_PREFIX}{selected_activity}'
        raw = {
            **dict(body.raw),
            'selected_activity': selected_activity,
            'selected_activity_sources': list(activity_sources),
            'selected_post_body_sha256': body_digest,
            'selected_post_reaction_state': reaction_state,
        }
        mapped[key] = [replace(
            body,
            key=key,
            name='Selected LinkedIn post body',
            text=body_text,
            description=(
                f'activity={selected_activity}; body_sha256={body_digest}; '
                f'reaction_state={reaction_state or "not_mounted"}'
            ),
            raw=raw,
        )]
        if reaction is not None:
            reaction_key = (
                f'{SELECTED_POST_REACTION_PREFIX}{selected_activity}_body_'
                f'{body_digest}'
            )
            mapped[reaction_key] = [replace(
                reaction,
                key=reaction_key,
                description=(
                    f'activity={selected_activity}; body_sha256={body_digest}; '
                    f'reaction_state={reaction_state}'
                ),
                raw={
                    **dict(reaction.raw),
                    'selected_activity': selected_activity,
                    'selected_post_body_sha256': body_digest,
                    'selected_post_reaction_state': reaction_state,
                },
            )]
        editor = comment_controls['editor']
        editor_text = comment_controls['editor_text']
        if editor is not None and editor_text is not None:
            editor_text_sha256 = hashlib.sha256(
                editor_text.encode('utf-8')
            ).hexdigest()
            editor_key = (
                f'{SELECTED_POST_EDITOR_PREFIX}{selected_activity}_body_'
                f'{body_digest}'
            )
            mapped[editor_key] = [replace(
                editor,
                key=editor_key,
                name='LinkedIn selected-post comment editor',
                text=None,
                description=(
                    f'activity={selected_activity}; body_sha256={body_digest}; '
                    f'editor_text_sha256={editor_text_sha256}; '
                    f'editor_text_chars={len(editor_text)}'
                ),
                raw={
                    **dict(editor.raw),
                    'selected_activity': selected_activity,
                    'selected_post_body_sha256': body_digest,
                    'comment_editor_ready': comment_controls['editor_ready'],
                    'comment_editor_empty': editor_text == '',
                    'comment_editor_text_sha256': editor_text_sha256,
                    'comment_editor_text_chars': len(editor_text),
                },
            )]
            submit = comment_controls['submit']
            if editor_text and submit is not None:
                submit_key = (
                    f'{SELECTED_POST_SUBMIT_PREFIX}{selected_activity}_body_'
                    f'{body_digest}_draft_{editor_text_sha256}'
                )
                mapped[submit_key] = [replace(
                    submit,
                    key=submit_key,
                    name='LinkedIn selected-post comment submit',
                    description=(
                        f'activity={selected_activity}; body_sha256={body_digest}; '
                        f'draft_sha256={editor_text_sha256}; '
                        f'draft_chars={len(editor_text)}'
                    ),
                    raw={
                        **dict(submit.raw),
                        'selected_activity': selected_activity,
                        'selected_post_body_sha256': body_digest,
                        'comment_submit_ready': True,
                        'comment_draft_sha256': editor_text_sha256,
                        'comment_draft_chars': len(editor_text),
                    },
                )]
        comment_counts, visible_comments = _selected_thread_controls(
            snapshot,
            root,
            contract,
        )
        if len(comment_counts) > 1:
            raise ValueError(
                'LinkedIn selected-thread comment count is ambiguous'
            )
        if len(comment_counts) == 1 and not visible_comments:
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
                    'atspi_obj': comment_counts[0].atspi_obj,
                    'scroll_target_atspi_obj': root.atspi_obj,
                    'selected_post_document_atspi_obj': selected_document,
                    'selected_post_root_atspi_obj': root.atspi_obj,
                    'selected_post_body_atspi_obj': body.atspi_obj,
                    'selected_post_body_showing': _node_has_states(
                        body.atspi_obj,
                        ['showing'],
                    ),
                    'selected_activity': selected_activity,
                    'selected_post_body_sha256': body_digest,
                },
            )]
        if not comment_counts and not visible_comments:
            zero_opener = _selected_zero_thread_opener(
                snapshot,
                root,
                contract,
            )
            if zero_opener is not None:
                zero_open_key = (
                    f'{SELECTED_THREAD_ZERO_OPEN_PREFIX}{selected_activity}_body_'
                    f'{body_digest}'
                )
                mapped[zero_open_key] = [replace(
                    zero_opener,
                    key=zero_open_key,
                    description=(
                        f'activity={selected_activity}; open exact zero-comment '
                        'editor'
                    ),
                    raw={
                        **dict(zero_opener.raw),
                        'atspi_obj': zero_opener.atspi_obj,
                        'scroll_target_atspi_obj': root.atspi_obj,
                        'selected_post_document_atspi_obj': selected_document,
                        'selected_post_root_atspi_obj': root.atspi_obj,
                        'selected_post_body_atspi_obj': body.atspi_obj,
                        'selected_post_body_showing': _node_has_states(
                            body.atspi_obj,
                            ['showing'],
                        ),
                        'selected_activity': selected_activity,
                        'selected_post_body_sha256': body_digest,
                        'selected_thread_expected_count': 0,
                        'comment_editor_ready_before': False,
                    },
                )]
        if len(comment_counts) == 1 and visible_comments:
            count_name = comment_counts[0].name
            count_token = (
                count_name.removesuffix(' comments').replace(',', '')
                if count_name.endswith(' comments')
                else '1' if count_name == '1 comment' else ''
            )
            expected_count = int(count_token) if count_token.isdigit() else 0
            expand_target, more_count = _selected_thread_expander(
                snapshot,
                root,
                contract,
            )
            if expand_target is not None and expected_count <= len(visible_comments):
                raise ValueError(
                    'LinkedIn selected-thread expansion exceeds the exact count'
                )
            if (
                expand_target is not None
                and more_count is not None
                and expected_count > len(visible_comments)
                and more_count <= expected_count - len(visible_comments)
            ):
                thread_expand_key = (
                    f'{SELECTED_THREAD_EXPAND_PREFIX}{selected_activity}_body_'
                    f'{body_digest}_total_{expected_count}_'
                    f'visible_{len(visible_comments)}_more_'
                    f'{more_count}'
                )
                mapped[thread_expand_key] = [replace(
                    expand_target,
                    key=thread_expand_key,
                    description=(
                        f'activity={selected_activity}; expand exact selected '
                        f'thread from {len(visible_comments)} visible comments'
                    ),
                    raw={
                        **dict(expand_target.raw),
                        'atspi_obj': expand_target.atspi_obj,
                        'scroll_target_atspi_obj': expand_target.atspi_obj,
                        'selected_post_document_atspi_obj': selected_document,
                        'selected_post_root_atspi_obj': root.atspi_obj,
                        'selected_post_body_atspi_obj': body.atspi_obj,
                        'selected_post_body_showing': _node_has_states(
                            body.atspi_obj,
                            ['showing'],
                        ),
                        'selected_activity': selected_activity,
                        'selected_post_body_sha256': body_digest,
                        'selected_thread_total_count': expected_count,
                        'selected_thread_visible_count': len(visible_comments),
                        'selected_thread_more_count': more_count,
                    },
                )]
    return replace(snapshot, mapped=mapped)


def _selected_thread_viewport_state(element: dict[str, Any]) -> dict[str, object]:
    from consultation_v2.interact import atspi_element_viewport_state

    viewport = dict(atspi_element_viewport_state(element))
    document_obj = element.get('selected_post_document_atspi_obj')
    if document_obj is None:
        return viewport
    document = dict(atspi_element_viewport_state({
        'atspi_obj': document_obj,
    }))
    viewport.update({
        'viewport_source': 'linkedin_document',
        'document_extent_resolved': bool(
            document.get('live_extent_resolved')
        ),
        'document_x': int(document.get('x') or 0),
        'document_y': int(document.get('y') or 0),
        'document_width': int(document.get('width') or 0),
        'document_height': int(document.get('height') or 0),
        'display_available_below_px': int(
            viewport.get('available_below_px') or 0
        ),
    })
    if (
        viewport.get('live_extent_resolved') is not True
        or document.get('live_extent_resolved') is not True
    ):
        viewport.update({
            'live_extent_in_viewport': False,
            'intersects_viewport': False,
            'available_below_px': 0,
            'error': 'linkedin_document_extent_unavailable',
        })
        return viewport
    x = int(viewport['x'])
    y = int(viewport['y'])
    width = int(viewport['width'])
    height = int(viewport['height'])
    document_x = int(document['x'])
    document_y = int(document['y'])
    document_right = document_x + int(document['width'])
    document_bottom = document_y + int(document['height'])
    intersects_document = bool(
        x < document_right
        and x + width > document_x
        and y < document_bottom
        and y + height > document_y
    )
    contained_by_document = bool(
        x >= document_x
        and y >= document_y
        and x + width <= document_right
        and y + height <= document_bottom
    )
    viewport.update({
        'live_extent_in_viewport': contained_by_document,
        'intersects_viewport': intersects_document,
        'available_below_px': max(0, document_bottom - (y + height)),
        'error': (
            None if contained_by_document else 'live_extent_outside_document'
        ),
    })
    return viewport


def _selected_post_document(root: Any) -> Any | None:
    node = root.atspi_obj
    for _depth in range(64):
        if node is None:
            return None
        if _node_role(node) == 'document web':
            return node
        try:
            node = node.get_parent()
        except Exception:
            return None
    return None


def _selected_thread_open_geometry(context: dict[str, Any]) -> dict[str, Any]:
    document_obj = context.get('selected_post_document_atspi_obj')
    return {
        'selected_post_root': _selected_thread_viewport_state({
            'atspi_obj': context.get('selected_post_root_atspi_obj'),
            'selected_post_document_atspi_obj': document_obj,
        }),
        'selected_post_body': _selected_thread_viewport_state({
            'atspi_obj': context.get('selected_post_body_atspi_obj'),
            'selected_post_document_atspi_obj': document_obj,
        }),
        'selected_post_body_showing': (
            context.get('selected_post_body_showing') is True
        ),
        'thread_opener': _selected_thread_viewport_state({
            'atspi_obj': context.get('atspi_obj'),
            'selected_post_document_atspi_obj': document_obj,
        }),
    }


def element_operation(
    element_key: str,
    states: list[str],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    candidate_match = _CANDIDATE_KEY.fullmatch(element_key)
    continuation_match = _CONTINUATION_KEY.fullmatch(element_key)
    continuation_postcondition = (
        _manual_notification_contract()['continuation']['postcondition']
        if continuation_match is not None
        else None
    )
    selected_post_match = _SELECTED_POST_KEY.fullmatch(element_key)
    selected_thread_open_match = _SELECTED_THREAD_OPEN_KEY.fullmatch(element_key)
    selected_zero_thread_open_match = _SELECTED_THREAD_ZERO_OPEN_KEY.fullmatch(
        element_key
    )
    selected_thread_expand_match = _SELECTED_THREAD_EXPAND_KEY.fullmatch(
        element_key
    )
    selected_reaction_match = _SELECTED_POST_REACTION_KEY.fullmatch(element_key)
    selected_editor_match = _SELECTED_POST_EDITOR_KEY.fullmatch(element_key)
    selected_submit_match = _SELECTED_POST_SUBMIT_KEY.fullmatch(element_key)
    if (
        element_key != NOTIFICATIONS_NAVIGATION
        and candidate_match is None
        and continuation_match is None
        and selected_post_match is None
        and selected_thread_open_match is None
        and selected_zero_thread_open_match is None
        and selected_thread_expand_match is None
        and selected_reaction_match is None
        and selected_editor_match is None
        and selected_submit_match is None
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
    selected_context = dict(context or {})
    if selected_zero_thread_open_match is not None:
        activity = selected_zero_thread_open_match.group('activity')
        body_sha256 = selected_zero_thread_open_match.group('body')
        if (
            selected_context.get('selected_activity') != activity
            or selected_context.get('selected_post_body_sha256') != body_sha256
            or selected_context.get('selected_thread_expected_count') != 0
            or selected_context.get('comment_editor_ready_before') is not False
        ):
            raise ValueError(
                'LinkedIn zero-comment thread opener identity is not exact'
            )
    if selected_thread_expand_match is not None:
        activity = selected_thread_expand_match.group('activity')
        body_sha256 = selected_thread_expand_match.group('body')
        total_count = int(selected_thread_expand_match.group('total'))
        visible_count = int(selected_thread_expand_match.group('visible'))
        more_count = int(selected_thread_expand_match.group('more'))
        if (
            selected_context.get('selected_activity') != activity
            or selected_context.get('selected_post_body_sha256') != body_sha256
            or selected_context.get('selected_thread_total_count') != total_count
            or selected_context.get('selected_thread_visible_count')
            != visible_count
            or selected_context.get('selected_thread_more_count') != more_count
        ):
            raise ValueError('LinkedIn selected-thread expansion identity is not exact')
    if selected_reaction_match is not None:
        activity = selected_reaction_match.group('activity')
        body_sha256 = selected_reaction_match.group('body')
        reaction_state = selected_context.get('selected_post_reaction_state')
        if (
            selected_context.get('selected_activity') != activity
            or selected_context.get('selected_post_body_sha256') != body_sha256
            or reaction_state not in {'no_reaction', 'liked'}
        ):
            raise ValueError('LinkedIn reaction identity is not exact')
        reaction_contract = _manual_comment_contract()['reaction']
        if reaction_state == 'liked':
            return {
                'method': 'observe',
                'effect_class': 'observation',
                'primitives': [],
                'allowed_now': [],
                'forbidden': [
                    'activate',
                    'activate_optional_like',
                    'paste_frozen_text',
                    'submit_frozen_comment',
                ],
                'postcondition': {
                    'kind': reaction_contract['postcondition'],
                    'activity': activity,
                    'body_sha256': body_sha256,
                    'reaction_state': 'liked',
                },
            }
        return {
            'method': 'activate_optional_like',
            **reaction_contract['action'],
            'forbidden': [
                'click',
                'focus',
                'activate',
                'hover',
                'mapped_pointer_activate',
                'paste_frozen_text',
                'submit_frozen_comment',
            ],
            'postcondition': {
                'kind': reaction_contract['postcondition'],
                'activity': activity,
                'body_sha256': body_sha256,
                'reaction_state': 'liked',
            },
        }
    if selected_editor_match is not None:
        activity = selected_editor_match.group('activity')
        body_sha256 = selected_editor_match.group('body')
        editor_contract = _manual_comment_contract()['editor']
        editor_empty = selected_context.get('comment_editor_empty')
        editor_text_sha256 = selected_context.get(
            'comment_editor_text_sha256'
        )
        editor_text_chars = selected_context.get('comment_editor_text_chars')
        empty_digest = hashlib.sha256(b'').hexdigest()
        if (
            selected_context.get('selected_activity') != activity
            or selected_context.get('selected_post_body_sha256') != body_sha256
            or selected_context.get('comment_editor_ready') is not True
            or not isinstance(editor_empty, bool)
            or not isinstance(editor_text_sha256, str)
            or re.fullmatch(r'[0-9a-f]{64}', editor_text_sha256) is None
            or isinstance(editor_text_chars, bool)
            or not isinstance(editor_text_chars, int)
            or not 0 <= editor_text_chars <= editor_contract['max_text_chars']
            or editor_empty != (editor_text_chars == 0)
            or (editor_empty and editor_text_sha256 != empty_digest)
            or (not editor_empty and editor_text_sha256 == empty_digest)
        ):
            raise ValueError(
                'LinkedIn same-card editor observation identity is not exact'
            )
        if not editor_empty:
            return {
                'method': 'observe',
                'effect_class': 'observation',
                'primitives': [],
                'allowed_now': [],
                'forbidden': [
                    'activate',
                    'activate_optional_like',
                    'paste_frozen_text',
                    'submit_frozen_comment',
                ],
                'postcondition': {
                    'kind': editor_contract['postcondition'],
                    'activity': activity,
                    'body_sha256': body_sha256,
                    'editor_text_sha256': editor_text_sha256,
                    'editor_text_chars': editor_text_chars,
                },
            }
        return {
            'method': 'paste_frozen_text',
            'effect_class': editor_contract['action']['effect_class'],
            'primitives': list(editor_contract['action']['primitives']),
            'allowed_now': list(editor_contract['action']['allowed_now']),
            'max_text_chars': editor_contract['max_text_chars'],
            'forbidden': [
                'click',
                'activate',
                'hover',
                'mapped_pointer_activate',
                'submit_frozen_comment',
            ],
            'postcondition': {
                'kind': editor_contract['postcondition'],
                'activity': activity,
                'body_sha256': body_sha256,
            },
        }
    if selected_submit_match is not None:
        activity = selected_submit_match.group('activity')
        body_sha256 = selected_submit_match.group('body')
        draft_sha256 = selected_submit_match.group('draft')
        draft_chars = selected_context.get('comment_draft_chars')
        if (
            selected_context.get('selected_activity') != activity
            or selected_context.get('selected_post_body_sha256') != body_sha256
            or selected_context.get('comment_submit_ready') is not True
            or selected_context.get('comment_draft_sha256') != draft_sha256
            or isinstance(draft_chars, bool)
            or not isinstance(draft_chars, int)
            or not 1 <= draft_chars <= _manual_comment_contract()['editor'][
                'max_text_chars'
            ]
        ):
            raise ValueError('LinkedIn frozen comment submit identity is not exact')
        submit_contract = _manual_comment_contract()['submit']
        return {
            'method': 'submit_frozen_comment',
            'effect_class': submit_contract['action']['effect_class'],
            'primitives': list(submit_contract['action']['primitives']),
            'allowed_now': list(submit_contract['action']['allowed_now']),
            'forbidden': [
                'click',
                'focus',
                'activate',
                'hover',
                'mapped_pointer_activate',
                'paste_frozen_text',
            ],
            'precondition': {
                'kind': submit_contract['precondition'],
                'activity': activity,
                'body_sha256': body_sha256,
                'draft_sha256': draft_sha256,
            },
            'postcondition': {
                'kind': submit_contract['postcondition'],
                'activity': activity,
                'body_sha256': body_sha256,
                'draft_sha256': draft_sha256,
            },
        }
    normalized_states = {
        str(state).strip().lower().replace('_', ' ') for state in states
    }
    required_states = {'focusable', 'enabled'}
    selected_open_match = (
        selected_thread_open_match or selected_zero_thread_open_match
    )
    if selected_open_match is not None:
        geometry = _selected_thread_open_geometry(selected_context)
        root_viewport = geometry['selected_post_root']
        opener_viewport = geometry['thread_opener']
        if (
            root_viewport.get('viewport_source') != 'linkedin_document'
            or opener_viewport.get('viewport_source') != 'linkedin_document'
        ):
            raise ValueError(
                'LinkedIn selected-thread document viewport is unavailable'
            )
        scroll_action = _manual_notification_contract()[
            'selected_thread'
        ]['scroll_into_view']
        if (
            root_viewport.get('intersects_viewport') is True
            and opener_viewport.get('live_extent_in_viewport') is True
        ):
            declared_action = _manual_notification_contract()[
                'selected_thread'
            ]['action']
        elif (
            root_viewport.get('error') in {
                'live_extent_outside_display',
                'live_extent_outside_document',
            }
            or opener_viewport.get('error') in {
                'live_extent_outside_display',
                'live_extent_outside_document',
            }
            or root_viewport.get('intersects_viewport') is not True
            or opener_viewport.get('live_extent_in_viewport') is not True
        ):
            declared_action = scroll_action
        else:
            raise ValueError(
                'LinkedIn selected-thread root/opener viewport state is unavailable: '
                f"root={root_viewport.get('error') or 'unknown'}; "
                f"opener={opener_viewport.get('error') or 'unknown'}"
            )
    elif selected_thread_expand_match is not None:
        geometry = _selected_thread_open_geometry(selected_context)
        root_viewport = geometry['selected_post_root']
        expander_viewport = geometry['thread_opener']
        if (
            root_viewport.get('viewport_source') != 'linkedin_document'
            or expander_viewport.get('viewport_source') != 'linkedin_document'
        ):
            raise ValueError(
                'LinkedIn selected-thread expander document viewport is '
                'unavailable'
            )
        if (
            root_viewport.get('intersects_viewport') is True
            and expander_viewport.get('live_extent_in_viewport') is True
        ):
            declared_action = _manual_notification_contract()[
                'selected_thread'
            ]['expand']['action']
        elif (
            root_viewport.get('error') in {
                'live_extent_outside_display',
                'live_extent_outside_document',
            }
            or expander_viewport.get('error') in {
                'live_extent_outside_display',
                'live_extent_outside_document',
            }
            or root_viewport.get('intersects_viewport') is not True
            or expander_viewport.get('live_extent_in_viewport') is not True
        ):
            declared_action = _manual_notification_contract()[
                'selected_thread'
            ]['expand']['scroll_into_view']
        else:
            raise ValueError(
                'LinkedIn selected-thread root/expander viewport state is '
                'unavailable: '
                f"root={root_viewport.get('error') or 'unknown'}; "
                f"expander={expander_viewport.get('error') or 'unknown'}"
            )
    else:
        declared_action = {
            'effect_class': 'page',
            'primitives': ['activate'],
            'allowed_now': ['activate'],
        }
    declared_primitive = declared_action['primitives'][0]
    allowed_now = (
        [declared_primitive]
        if required_states.issubset(normalized_states)
        else []
    )
    runtime_context_present = (
        'element' in selected_context or 'ref' in selected_context
    )
    if continuation_match is not None and runtime_context_present:
        if allowed_now != ['activate']:
            raise ValueError(
                'LinkedIn continuation runtime target is not ready to activate'
            )
        _freeze_notification_continuation_context(selected_context)
    return {
        'method': declared_primitive,
        'effect_class': declared_action['effect_class'],
        'primitives': declared_action['primitives'],
        'allowed_now': allowed_now,
        **(
            {
                'phase': declared_action['phase'],
                'scroll_target': declared_action['scroll_target'],
                'scroll_target_source': declared_action[
                    'scroll_target_source'
                ],
                'scroll_alignment': declared_action['scroll_alignment'],
                **(
                    {
                        'min_downward_clearance_px': declared_action[
                            'min_downward_clearance_px'
                        ],
                    }
                    if 'min_downward_clearance_px' in declared_action
                    else {}
                ),
            }
            if declared_primitive == 'scroll_into_view'
            else {}
        ),
        'forbidden': [
            primitive
            for primitive in [
                'click',
                'focus',
                'activate',
                'hover',
                'mapped_pointer_activate',
                'scroll_into_view',
            ]
            if primitive != declared_primitive
        ],
        'postcondition': {
            'kind': (
                (
                    'exact_selected_thread_opener_in_viewport'
                    if declared_primitive == 'scroll_into_view'
                    else (
                        _manual_notification_contract()['selected_thread'][
                            'zero_open'
                        ]['postcondition']
                        if selected_zero_thread_open_match is not None
                        else 'exact_selected_activity_visible_comment_controls'
                    )
                )
                if selected_open_match is not None
                else (
                    (
                        _manual_notification_contract()['selected_thread'][
                            'expand'
                        ][
                            'scroll_into_view'
                        ]['postcondition']
                        if declared_primitive == 'scroll_into_view'
                        else _manual_notification_contract()['selected_thread'][
                            'expand'
                        ]['postcondition']
                    )
                    if selected_thread_expand_match is not None
                    else (
                        'exact_notification_activity'
                        if candidate_match is not None
                        else (
                            continuation_postcondition['kind']
                            if continuation_match is not None
                            else 'exact_document_route'
                        )
                    )
                )
            ),
            **(
                {'activity': candidate_match.group('activity')}
                if candidate_match is not None
                else {}
            ),
            **(
                {
                    'pre_action_inventory': (
                        'frozen_after_exact_live_target_ref_revalidation'
                    )
                }
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
            **(
                {
                    'activity': selected_zero_thread_open_match.group('activity'),
                    'body_sha256': selected_zero_thread_open_match.group('body'),
                    'exact_comment_count': 0,
                }
                if selected_zero_thread_open_match is not None
                else {}
            ),
        },
    }


def verify_comment_submit_precondition(
    snapshot: Snapshot,
    element_key: str,
    expected_text: str,
    expected_author_name: str,
) -> dict[str, Any]:
    _require_linkedin(snapshot)
    submit_match = _SELECTED_POST_SUBMIT_KEY.fullmatch(element_key)
    if submit_match is None:
        raise ValueError(
            'LinkedIn comment-submit precondition requires one exact submit key'
        )
    surface = _selected_comment_surface(snapshot)
    text_sha256 = _validate_frozen_comment_text(
        expected_text,
        surface['contract'],
    )
    author_name = _validate_private_author_name(expected_author_name)
    controls = surface['controls']
    if (
        submit_match.group('activity') != surface['activity']
        or submit_match.group('body') != surface['body_sha256']
        or submit_match.group('draft') != text_sha256
        or controls['editor_ready'] is not True
        or controls['editor_text'] != expected_text
        or controls['submit'] is None
        or _exact_own_comment_count(surface, author_name, expected_text) != 0
    ):
        raise ValueError(
            'LinkedIn comment-submit precondition is not one exact unsent '
            'draft on the selected activity/body'
        )
    author_control = (
        f"{surface['contract']['own_comment']['control_name_prefix']}"
        f"{author_name}"
        f"{surface['contract']['own_comment']['control_name_suffixes'][0]}"
    )
    return {
        'element_key': element_key,
        'operation': 'submit_frozen_comment',
        'effect_class': 'outward',
        'precondition': surface['contract']['submit']['precondition'],
        'route_exact': True,
        'activity_exact': True,
        'body_sha256_exact': True,
        'draft_sha256': text_sha256,
        'draft_chars': len(expected_text),
        'own_comment_control_sha256': hashlib.sha256(
            author_control.encode('utf-8')
        ).hexdigest(),
        'existing_exact_own_comment_count': 0,
    }


def verify_post_action(
    snapshot: Snapshot,
    element_key: str,
    operation: str,
    *,
    expected_text: str | None = None,
    expected_author_name: str | None = None,
    pre_action_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _require_linkedin(snapshot)
    reaction_match = _SELECTED_POST_REACTION_KEY.fullmatch(element_key)
    editor_match = _SELECTED_POST_EDITOR_KEY.fullmatch(element_key)
    submit_match = _SELECTED_POST_SUBMIT_KEY.fullmatch(element_key)
    if reaction_match is not None:
        if operation != 'activate_optional_like':
            raise ValueError(
                'LinkedIn reaction postcondition requires activate_optional_like'
            )
        surface = _selected_comment_surface(snapshot)
        reaction = surface['controls']['reaction']
        liked_name = surface['contract']['reaction']['exact_names']['liked']
        if (
            reaction_match.group('activity') != surface['activity']
            or reaction_match.group('body') != surface['body_sha256']
            or reaction is None
            or reaction.name != liked_name
        ):
            raise ValueError(
                'LinkedIn reaction postcondition did not prove Like on the '
                'same activity/body'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'outward',
            'postcondition': surface['contract']['reaction']['postcondition'],
            'route_exact': True,
            'activity_exact': True,
            'activity_sources': list(surface['activity_sources']),
            'selected_post_body_sha256': surface['body_sha256'],
            'reaction_state': 'liked',
            'observed_url': snapshot.url,
        }
    if editor_match is not None:
        if operation != 'paste_frozen_text' or expected_text is None:
            raise ValueError(
                'LinkedIn editor postcondition requires exact frozen text'
            )
        surface = _selected_comment_surface(snapshot)
        text_sha256 = _validate_frozen_comment_text(
            expected_text,
            surface['contract'],
        )
        if (
            editor_match.group('activity') != surface['activity']
            or editor_match.group('body') != surface['body_sha256']
            or surface['controls']['editor_ready'] is not True
            or surface['controls']['editor_text'] != expected_text
        ):
            raise ValueError(
                'LinkedIn editor postcondition did not prove exact frozen text '
                'on the same activity/body'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'draft',
            'postcondition': surface['contract']['editor']['postcondition'],
            'route_exact': True,
            'activity_exact': True,
            'activity_sources': list(surface['activity_sources']),
            'selected_post_body_sha256': surface['body_sha256'],
            'editor_text_sha256': text_sha256,
            'editor_text_chars': len(expected_text),
            'observed_url': snapshot.url,
        }
    if submit_match is not None:
        if (
            operation != 'submit_frozen_comment'
            or expected_text is None
            or expected_author_name is None
        ):
            raise ValueError(
                'LinkedIn submit postcondition requires frozen text and private author'
            )
        surface = _selected_comment_surface(snapshot)
        text_sha256 = _validate_frozen_comment_text(
            expected_text,
            surface['contract'],
        )
        author_name = _validate_private_author_name(expected_author_name)
        exact_own_comment_count = _exact_own_comment_count(
            surface,
            author_name,
            expected_text,
        )
        if (
            submit_match.group('activity') != surface['activity']
            or submit_match.group('body') != surface['body_sha256']
            or submit_match.group('draft') != text_sha256
            or surface['controls']['editor_ready'] is not True
            or surface['controls']['editor_text'] != ''
            or exact_own_comment_count != 1
        ):
            raise ValueError(
                'LinkedIn submit postcondition did not prove one exact own-comment '
                'render and an empty same-card editor'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'outward',
            'postcondition': surface['contract']['submit']['postcondition'],
            'route_exact': True,
            'activity_exact': True,
            'activity_sources': list(surface['activity_sources']),
            'selected_post_body_sha256': surface['body_sha256'],
            'editor_empty': True,
            'exact_own_comment_count': exact_own_comment_count,
            'comment_text_sha256': text_sha256,
            'comment_text_chars': len(expected_text),
            'observed_url': snapshot.url,
        }
    if operation != 'activate':
        raise ValueError(
            'LinkedIn post-action verification accepts only activate'
        )
    candidate_match = _CANDIDATE_KEY.fullmatch(element_key)
    continuation_match = _CONTINUATION_KEY.fullmatch(element_key)
    selected_thread_open_match = _SELECTED_THREAD_OPEN_KEY.fullmatch(element_key)
    selected_zero_thread_open_match = _SELECTED_THREAD_ZERO_OPEN_KEY.fullmatch(
        element_key
    )
    selected_thread_expand_match = _SELECTED_THREAD_EXPAND_KEY.fullmatch(
        element_key
    )
    if selected_zero_thread_open_match is not None:
        contract = _manual_notification_contract()
        activity, activity_sources = _selected_activity_identity(snapshot, contract)
        expected_activity = selected_zero_thread_open_match.group('activity')
        expected_body_digest = selected_zero_thread_open_match.group('body')
        root, _body, body_text = _selected_post_root_and_body(snapshot, contract)
        if root is None or body_text is None:
            raise ValueError(
                'LinkedIn zero-comment opener lost the exact selected post'
            )
        observed_body_digest = hashlib.sha256(
            body_text.encode('utf-8')
        ).hexdigest()
        comment_controls = _selected_comment_controls(
            snapshot,
            root,
            _manual_comment_contract(),
        )
        editor_text = comment_controls['editor_text']
        if (
            activity != expected_activity
            or observed_body_digest != expected_body_digest
            or not _selected_thread_zero_is_exact(snapshot, root, contract)
            or comment_controls['editor_ready'] is not True
            or editor_text != ''
        ):
            raise ValueError(
                'LinkedIn zero-comment opener postcondition failed: the exact '
                'selected activity/body did not expose one empty ready editor'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'page',
            'postcondition': 'exact_selected_activity_zero_comment_thread_open',
            'route_exact': True,
            'activity_exact': True,
            'activity_sources': list(activity_sources),
            'selected_post_body_sha256': observed_body_digest,
            'exact_comment_count': 0,
            'visible_comment_count': 0,
            'editor_empty': True,
            'editor_text_sha256': hashlib.sha256(b'').hexdigest(),
            'editor_text_chars': 0,
            'observed_url': snapshot.url,
        }
    if selected_thread_expand_match is not None:
        contract = _manual_notification_contract()
        activity, activity_sources = _selected_activity_identity(snapshot, contract)
        expected_activity = selected_thread_expand_match.group('activity')
        expected_body_digest = selected_thread_expand_match.group('body')
        declared_total_count = int(
            selected_thread_expand_match.group('total')
        )
        prior_visible_count = int(
            selected_thread_expand_match.group('visible')
        )
        declared_more_count = int(
            selected_thread_expand_match.group('more')
        )
        root, _body, body_text = _selected_post_root_and_body(snapshot, contract)
        if root is None or body_text is None:
            raise ValueError(
                'LinkedIn selected-thread expansion lost the exact selected post'
            )
        observed_body_digest = hashlib.sha256(
            body_text.encode('utf-8')
        ).hexdigest()
        comment_counts, visible_comments = _selected_thread_controls(
            snapshot,
            root,
            contract,
        )
        count_name = comment_counts[0].name if len(comment_counts) == 1 else ''
        count_token = (
            count_name.removesuffix(' comments').replace(',', '')
            if count_name.endswith(' comments')
            else '1' if count_name == '1 comment' else ''
        )
        expected_count = int(count_token) if count_token.isdigit() else 0
        expand_target, next_more_count = _selected_thread_expander(
            snapshot,
            root,
            contract,
        )
        observed_visible_count = len(visible_comments)
        observed_more_count = next_more_count if next_more_count is not None else 0
        remaining_count = observed_more_count
        typed_rows = _selected_thread_typed_rows(
            visible_comments,
            _manual_comment_contract()['own_comment'],
        )
        typed_rows_sha256 = hashlib.sha256(json.dumps(
            typed_rows,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')).hexdigest()
        if (
            activity != expected_activity
            or observed_body_digest != expected_body_digest
            or len(comment_counts) != 1
            or expected_count != declared_total_count
            or observed_visible_count <= prior_visible_count
            or observed_visible_count > expected_count
            or observed_more_count >= declared_more_count
            or (observed_more_count > 0 and expand_target is None)
            or (observed_more_count == 0 and expand_target is not None)
        ):
            raise ValueError(
                'LinkedIn selected-thread expansion postcondition failed: '
                'the exact selected activity/body did not grow within its '
                'declared comment count'
            )
        return {
            'element_key': element_key,
            'operation': operation,
            'effect_class': 'page',
            'postcondition': 'exact_selected_thread_growth',
            'route_exact': True,
            'activity_exact': True,
            'activity_sources': list(activity_sources),
            'selected_post_body_sha256': observed_body_digest,
            'exact_comment_count': expected_count,
            'prior_visible_comment_count': prior_visible_count,
            'declared_more_comment_count': declared_more_count,
            'visible_comment_count': observed_visible_count,
            'typed_row_count': len(typed_rows),
            'typed_rows_sha256': typed_rows_sha256,
            'remaining_comment_count': remaining_count,
            'next_expander_count': 1 if expand_target is not None else 0,
            'observed_url': snapshot.url,
        }
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
        augmented = augment_snapshot(snapshot)
        selected_key = f'{SELECTED_POST_PREFIX}{expected_activity}'
        selected_matches = list(augmented.mapped.get(selected_key) or [])
        selected_body_sha256 = (
            selected_matches[0].raw.get('selected_post_body_sha256')
            if len(selected_matches) == 1
            else None
        )
        if (
            activity != expected_activity
            or len(selected_matches) != 1
            or not isinstance(selected_body_sha256, str)
            or _SHA256.fullmatch(selected_body_sha256) is None
        ):
            raise ValueError(
                'LinkedIn notification candidate postcondition failed: '
                'fresh surface does not expose one exact selected activity/body'
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
            'selected_post_body_sha256': selected_body_sha256,
            'observed_url': snapshot.url,
        }
    if continuation_match is not None:
        frozen = (
            _validate_notification_continuation_context(pre_action_context)
            if pre_action_context is not None
            else _consume_notification_continuation_context(
                element_key,
                operation,
            )
        )
        return _notification_continuation_receipt(
            element_key,
            operation,
            _notification_continuation_measurement(snapshot, frozen),
        )
    if element_key != NOTIFICATIONS_NAVIGATION:
        raise ValueError('LinkedIn post-action element is not declared')
    route_exact = _exact_engagement_route(snapshot.url, 'notifications_all')
    category_exact = _notification_categories_exact(
        snapshot,
        _manual_notification_contract(),
    )
    if not route_exact or not category_exact:
        raise ValueError(
            'LinkedIn notifications_navigation postcondition failed: '
            'fresh snapshot does not prove the exact notifications_all route '
            'and All category'
        )
    return {
        'element_key': NOTIFICATIONS_NAVIGATION,
        'operation': 'activate',
        'effect_class': 'page',
        'postcondition': 'notifications_all',
        'route_exact': True,
        'category_exact': True,
        'observed_url': snapshot.url,
    }


def stable_scroll_post_action_observation(
    element_key: str,
    deadline_at: float,
) -> tuple[Snapshot | None, dict[str, Any]]:
    selected_thread_open_match = _SELECTED_THREAD_OPEN_KEY.fullmatch(element_key)
    selected_zero_thread_open_match = _SELECTED_THREAD_ZERO_OPEN_KEY.fullmatch(
        element_key
    )
    selected_thread_expand_match = _SELECTED_THREAD_EXPAND_KEY.fullmatch(
        element_key
    )
    selected_open_match = (
        selected_thread_open_match or selected_zero_thread_open_match
    )
    selected_identity_match = selected_open_match or selected_thread_expand_match
    if (
        selected_thread_open_match is None
        and selected_zero_thread_open_match is None
        and selected_thread_expand_match is None
    ):
        raise ValueError(
            'LinkedIn scroll post-action observation requires an exact '
            'selected-thread opener key'
        )
    if isinstance(deadline_at, bool) or not isinstance(deadline_at, (int, float)):
        raise ValueError('LinkedIn scroll post-action deadline must be monotonic seconds')

    notification_contract = _manual_notification_contract()
    selected_thread_contract = notification_contract['selected_thread']
    scroll_contract = (
        selected_thread_contract['expand']['scroll_into_view']
        if selected_thread_expand_match is not None
        else selected_thread_contract['scroll_into_view']
    )
    declared_minimum_clearance = (
        scroll_contract['min_downward_clearance_px']
        if selected_open_match is not None
        else 0
    )
    if (
        isinstance(declared_minimum_clearance, bool)
        or not isinstance(declared_minimum_clearance, int)
        or declared_minimum_clearance < 0
    ):
        raise ValueError(
            'LinkedIn scroll post-action minimum clearance is invalid'
        )
    barrier = scroll_contract['observation_barrier']
    stable_cycles_required = barrier['stable_cycles']
    interval = barrier['interval_ms'] / 1000.0
    started_at = time.monotonic()
    barrier_deadline = min(
        float(deadline_at),
        started_at + (barrier['timeout_ms'] / 1000.0),
    )
    sample_budget_seconds = (
        max(0.0, barrier_deadline - started_at) / stable_cycles_required
    )
    stable_cycles_observed = 0
    last_snapshot: Snapshot | None = None
    samples: list[dict[str, Any]] = []

    while time.monotonic() < barrier_deadline:
        if barrier_deadline - time.monotonic() < sample_budget_seconds:
            break
        cache_invalidation = _invalidate_linkedin_firefox_subtree()
        _firefox, _document, base_snapshot = build_snapshot('linkedin')
        snapshot = augment_snapshot(base_snapshot)
        last_snapshot = snapshot
        matches = list(snapshot.mapped.get(element_key) or [])
        opener_viewport: dict[str, Any] = {}
        root_viewport: dict[str, Any] = {}
        body_viewport: dict[str, Any] = {}
        body_showing = False
        selected_post_identity_exact = False
        scroll_target_exact = False
        exact = False
        if len(matches) == 1:
            target = matches[0]
            target_raw = dict(target.raw or {})
            opener_viewport = _selected_thread_viewport_state(target_raw)
            scroll_target_exact = target.atspi_obj is not None
            if selected_identity_match is not None:
                root, body, body_text = _selected_post_root_and_body(
                    snapshot,
                    notification_contract,
                )
                if root is not None and body is not None and body_text is not None:
                    expected_activity = selected_identity_match.group('activity')
                    expected_body_sha256 = selected_identity_match.group('body')
                    selected_document = _selected_post_document(root)
                    selected_post_identity_exact = bool(
                        target_raw.get('selected_activity') == expected_activity
                        and hashlib.sha256(
                            body_text.encode('utf-8')
                        ).hexdigest() == expected_body_sha256
                    )
                    scroll_target_exact = bool(
                        scroll_target_exact
                        and target_raw.get('atspi_obj') is target.atspi_obj
                        and target_raw.get('scroll_target_atspi_obj') is (
                            root.atspi_obj
                            if selected_open_match is not None
                            else target.atspi_obj
                        )
                        and target_raw.get('selected_post_document_atspi_obj')
                        is selected_document
                        and target_raw.get('selected_post_root_atspi_obj')
                        is root.atspi_obj
                        and target_raw.get('selected_post_body_atspi_obj')
                        is body.atspi_obj
                    )
                    root_viewport = _selected_thread_viewport_state({
                        'atspi_obj': root.atspi_obj,
                        'selected_post_document_atspi_obj': selected_document,
                    })
                    body_viewport = _selected_thread_viewport_state({
                        'atspi_obj': body.atspi_obj,
                        'selected_post_document_atspi_obj': selected_document,
                    })
                    body_showing = _node_has_states(
                        body.atspi_obj,
                        ['showing'],
                    )
            opener_clearance = opener_viewport.get('available_below_px')
            selected_geometry_exact = bool(
                selected_identity_match is not None
                and root_viewport.get('intersects_viewport') is True
                and selected_post_identity_exact
                and scroll_target_exact
                and opener_viewport.get('viewport_source')
                == 'linkedin_document'
                and root_viewport.get('viewport_source')
                == 'linkedin_document'
                and opener_viewport.get('live_extent_in_viewport') is True
                and isinstance(opener_clearance, int)
                and not isinstance(opener_clearance, bool)
                and opener_clearance >= declared_minimum_clearance
            )
            if (
                selected_geometry_exact
            ):
                declared = element_operation(
                    element_key,
                    list(target.states),
                    target_raw,
                )
                exact = bool(
                    declared
                    and declared.get('method') == 'mapped_pointer_activate'
                    and declared.get('primitives') == ['mapped_pointer_activate']
                    and declared.get('allowed_now') == ['mapped_pointer_activate']
                )
        stable_cycles_observed = stable_cycles_observed + 1 if exact else 0
        samples.append({
            'sample': len(samples) + 1,
            'elapsed_ms': round((time.monotonic() - started_at) * 1000),
            'exact_element_key_count': len(matches),
            'live_extent_resolved': bool(
                opener_viewport.get('live_extent_resolved')
            ),
            'display_geometry_resolved': bool(
                opener_viewport.get('display_geometry_resolved')
            ),
            'live_extent_in_viewport': bool(
                opener_viewport.get('live_extent_in_viewport')
            ),
            'scroll_context_intersects_viewport': bool(
                root_viewport.get('intersects_viewport')
            ),
            'viewport_source': opener_viewport.get('viewport_source'),
            'document_extent_resolved': bool(
                opener_viewport.get('document_extent_resolved')
            ),
            'available_below_px': int(
                opener_viewport.get('available_below_px') or 0
            ),
            'selected_post_identity_exact': selected_post_identity_exact,
            'scroll_target_exact': scroll_target_exact,
            'selected_post_root_live_extent_in_viewport': bool(
                root_viewport.get('live_extent_in_viewport')
            ),
            'selected_post_root_intersects_viewport': bool(
                root_viewport.get('intersects_viewport')
            ),
            'selected_post_body_live_extent_in_viewport': bool(
                body_viewport.get('live_extent_in_viewport')
            ),
            'selected_post_body_showing': body_showing,
            'thread_opener_live_extent_in_viewport': bool(
                opener_viewport.get('live_extent_in_viewport')
            ),
            'thread_opener_available_below_px': int(
                opener_viewport.get('available_below_px') or 0
            ),
            **(
                {
                    'min_downward_clearance_px': declared_minimum_clearance,
                }
                if selected_open_match is not None
                else {}
            ),
            'selected_post_root_viewport': root_viewport,
            'thread_opener_viewport': opener_viewport,
            'firefox_cache_invalidation': cache_invalidation,
            **(
                {'viewport_error': str(opener_viewport['error'])}
                if opener_viewport.get('error')
                else {}
            ),
            **(
                {
                    'selected_post_root_viewport_error': str(
                        root_viewport['error']
                    )
                }
                if root_viewport.get('error')
                else {}
            ),
        })
        if stable_cycles_observed >= stable_cycles_required:
            postcondition_receipt = {
                'element_key': element_key,
                'operation': 'scroll_into_view',
                'effect_class': 'viewport',
                'postcondition': scroll_contract['postcondition'],
                'route_exact': True,
                'element_key_exact': True,
                'activity_exact': True,
                'body_sha256_exact': True,
                'live_extent_in_viewport': True,
                'scroll_context_intersects_viewport': True,
                'viewport_source': 'linkedin_document',
                'document_extent_resolved': True,
                'scroll_target_exact': True,
                'available_below_px': int(
                    opener_viewport['available_below_px']
                ),
                'scroll_target': scroll_contract['scroll_target'],
                'scroll_target_source': scroll_contract[
                    'scroll_target_source'
                ],
                'scroll_alignment': scroll_contract['scroll_alignment'],
                'phase': scroll_contract['phase'],
                **(
                    {
                        'selected_post_root_intersects_viewport': True,
                        'thread_opener_live_extent_in_viewport': True,
                        'thread_opener_available_below_px': int(
                            opener_viewport['available_below_px']
                        ),
                        'min_downward_clearance_px': (
                            declared_minimum_clearance
                        ),
                        'selected_post_root_viewport': root_viewport,
                        'thread_opener_viewport': opener_viewport,
                    }
                    if selected_open_match is not None
                    else {}
                ),
                **(
                    {
                        'expansion_identity_exact': True,
                        'selected_post_root_intersects_viewport': True,
                        'selected_post_root_viewport': root_viewport,
                        'thread_opener_viewport': opener_viewport,
                        'total_count': int(
                            selected_thread_expand_match.group('total')
                        ),
                        'visible_count': int(
                            selected_thread_expand_match.group('visible')
                        ),
                        'more_count': int(
                            selected_thread_expand_match.group('more')
                        ),
                    }
                    if selected_thread_expand_match is not None
                    else {}
                ),
            }
            return snapshot, {
                'result': 'PASS',
                'next_mutation_authorized': False,
                'terminal_delivery_verified': False,
                'observe_required_before_next_mutation': True,
                'projection': scroll_contract['postcondition'],
                'refresh_policy': barrier['refresh_policy'],
                'stable_cycles_required': stable_cycles_required,
                'stable_cycles_observed': stable_cycles_observed,
                'samples': samples,
                'postcondition_receipt': postcondition_receipt,
            }
        remaining = barrier_deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))

    return last_snapshot, {
        'result': 'TIMEOUT',
        'next_mutation_authorized': False,
        'observe_required_before_next_mutation': True,
        'projection': scroll_contract['postcondition'],
        'refresh_policy': barrier['refresh_policy'],
        'stable_cycles_required': stable_cycles_required,
        'stable_cycles_observed': stable_cycles_observed,
        'samples': samples,
    }


def _invalidate_linkedin_firefox_subtree() -> str:
    firefox = platform_routing.find_firefox_for_platform('linkedin')
    if firefox is None:
        raise ValueError(
            'LinkedIn post-action refresh found no exact Firefox application'
        )
    try:
        firefox.clear_cache()
    except Exception as exc:
        raise ValueError(
            'LinkedIn post-action recursive Firefox cache invalidation failed'
        ) from exc
    return 'recursive_success'


def stable_post_action_observation(
    element_key: str,
    operation: str,
    deadline_at: float,
    *,
    expected_text: str | None = None,
    expected_author_name: str | None = None,
) -> tuple[Snapshot | None, dict[str, Any]]:
    navigation_contract = _manual_post_action_contract()
    notification_contract = _manual_notification_contract()
    comment_contract = _manual_comment_contract()
    selected_reaction_match = _SELECTED_POST_REACTION_KEY.fullmatch(element_key)
    selected_editor_match = _SELECTED_POST_EDITOR_KEY.fullmatch(element_key)
    selected_submit_match = _SELECTED_POST_SUBMIT_KEY.fullmatch(element_key)
    candidate_match = _CANDIDATE_KEY.fullmatch(element_key)
    continuation_match = _CONTINUATION_KEY.fullmatch(element_key)
    continuation_context = (
        _consume_notification_continuation_context(element_key, operation)
        if continuation_match is not None
        else None
    )
    existing_activate = operation == 'activate' and (
        element_key == navigation_contract['element_key']
        or _CANDIDATE_KEY.fullmatch(element_key) is not None
        or continuation_match is not None
        or _SELECTED_THREAD_OPEN_KEY.fullmatch(element_key) is not None
        or _SELECTED_THREAD_ZERO_OPEN_KEY.fullmatch(element_key) is not None
        or _SELECTED_THREAD_EXPAND_KEY.fullmatch(element_key) is not None
    )
    reaction_activate = (
        operation == 'activate_optional_like'
        and selected_reaction_match is not None
    )
    editor_write = (
        operation == 'paste_frozen_text'
        and selected_editor_match is not None
        and expected_text is not None
    )
    comment_submit = (
        operation == 'submit_frozen_comment'
        and selected_submit_match is not None
        and expected_text is not None
        and expected_author_name is not None
    )
    if not any((existing_activate, reaction_activate, editor_write, comment_submit)):
        raise ValueError('LinkedIn stable post-action observation is not declared')
    if isinstance(deadline_at, bool) or not isinstance(deadline_at, (int, float)):
        raise ValueError('LinkedIn post-action deadline must be monotonic seconds')

    selected_thread_open_match = _SELECTED_THREAD_OPEN_KEY.fullmatch(element_key)
    selected_zero_thread_open_match = _SELECTED_THREAD_ZERO_OPEN_KEY.fullmatch(
        element_key
    )
    selected_thread_expand_match = _SELECTED_THREAD_EXPAND_KEY.fullmatch(
        element_key
    )
    if element_key == navigation_contract['element_key']:
        postcondition = navigation_contract['postcondition']
    elif selected_thread_open_match is not None:
        postcondition = {
            'kind': 'exact_selected_activity_visible_comment_controls',
            'activity': selected_thread_open_match.group('activity'),
            'body_sha256': selected_thread_open_match.group('body'),
        }
    elif selected_zero_thread_open_match is not None:
        postcondition = {
            'kind': 'exact_selected_activity_zero_comment_thread_open',
            'activity': selected_zero_thread_open_match.group('activity'),
            'body_sha256': selected_zero_thread_open_match.group('body'),
            'exact_comment_count': 0,
        }
    elif selected_thread_expand_match is not None:
        postcondition = {
            'kind': 'exact_selected_thread_growth',
            'activity': selected_thread_expand_match.group('activity'),
            'body_sha256': selected_thread_expand_match.group('body'),
            'total_count': int(selected_thread_expand_match.group('total')),
            'visible_before': int(selected_thread_expand_match.group('visible')),
            'declared_more': int(selected_thread_expand_match.group('more')),
        }
    elif selected_reaction_match is not None:
        postcondition = {
            'kind': comment_contract['reaction']['postcondition'],
            'activity': selected_reaction_match.group('activity'),
            'body_sha256': selected_reaction_match.group('body'),
        }
    elif selected_editor_match is not None:
        postcondition = {
            'kind': comment_contract['editor']['postcondition'],
            'activity': selected_editor_match.group('activity'),
            'body_sha256': selected_editor_match.group('body'),
            'text_sha256': hashlib.sha256(
                str(expected_text).encode('utf-8')
            ).hexdigest(),
        }
    elif selected_submit_match is not None:
        postcondition = {
            'kind': comment_contract['submit']['postcondition'],
            'activity': selected_submit_match.group('activity'),
            'body_sha256': selected_submit_match.group('body'),
            'text_sha256': selected_submit_match.group('draft'),
        }
    elif continuation_match is not None:
        postcondition = notification_contract['continuation']['postcondition']
    else:
        postcondition = element_operation(
            element_key,
            ['enabled', 'focusable'],
        )['postcondition']
    if any(
        match is not None
        for match in (
            selected_reaction_match,
            selected_editor_match,
            selected_submit_match,
        )
    ):
        barrier = comment_contract['observation_barrier']
    elif element_key == navigation_contract['element_key']:
        barrier = navigation_contract['observation_barrier']
    elif candidate_match is not None:
        barrier = notification_contract['candidate'][
            'post_action_observation_barrier'
        ]
    else:
        barrier = notification_contract['observation_barrier']
    stable_cycles_required = barrier['stable_cycles']
    interval = barrier['interval_ms'] / 1000.0
    started_at = time.monotonic()
    barrier_deadline = min(
        float(deadline_at),
        started_at + (barrier['timeout_ms'] / 1000.0),
    )
    sample_budget_seconds = (
        max(0.0, barrier_deadline - started_at) / stable_cycles_required
    )
    stable_cycles_observed = 0
    last_snapshot: Snapshot | None = None
    samples: list[dict[str, Any]] = []

    while time.monotonic() < barrier_deadline:
        if barrier_deadline - time.monotonic() < sample_budget_seconds:
            break
        cache_invalidation = (
            'build_snapshot_invalidate_reacquire'
            if element_key == navigation_contract['element_key']
            else _invalidate_linkedin_firefox_subtree()
        )
        _firefox, _document, snapshot = build_snapshot('linkedin')
        last_snapshot = snapshot
        continuation_measurement = (
            _notification_continuation_measurement(snapshot, continuation_context)
            if continuation_context is not None
            else None
        )
        verification_error: str | None = None
        try:
            exact_receipt = (
                _notification_continuation_receipt(
                    element_key,
                    operation,
                    continuation_measurement,
                )
                if continuation_measurement is not None
                else verify_post_action(
                    snapshot,
                    element_key,
                    operation,
                    expected_text=expected_text,
                    expected_author_name=expected_author_name,
                )
            )
        except ValueError as exc:
            exact_receipt = None
            verification_error = str(exc)
        exact = exact_receipt is not None
        stable_cycles_observed = stable_cycles_observed + 1 if exact else 0
        sample = {
            'sample': len(samples) + 1,
            'elapsed_ms': round((time.monotonic() - started_at) * 1000),
            'route_exact': bool(exact_receipt and exact_receipt.get('route_exact')),
            'category_exact': bool(
                exact_receipt and exact_receipt.get('category_exact')
            ),
            'activity_exact': bool(
                exact_receipt and exact_receipt.get('activity_exact')
            ),
            'document_url_exact': bool(
                exact_receipt and exact_receipt.get('document_url_exact')
            ),
            'observed_url': snapshot.url,
            'firefox_cache_invalidation': cache_invalidation,
        }
        if continuation_measurement is not None:
            sample.update(continuation_measurement)
        if verification_error is not None:
            sample['verification_error'] = verification_error
        if exact_receipt is not None:
            sample['postcondition'] = exact_receipt['postcondition']
            if 'activity_sources' in exact_receipt:
                sample['activity_sources'] = exact_receipt['activity_sources']
            if 'observed_candidate_count' in exact_receipt:
                sample['observed_candidate_count'] = exact_receipt[
                    'observed_candidate_count'
                ]
            for field in (
                'reaction_state',
                'editor_text_sha256',
                'editor_text_chars',
                'editor_empty',
                'exact_own_comment_count',
                'comment_text_sha256',
                'comment_text_chars',
                'exact_comment_count',
                'prior_visible_comment_count',
                'declared_more_comment_count',
                'visible_comment_count',
                'typed_row_count',
                'typed_rows_sha256',
                'remaining_comment_count',
                'next_expander_count',
            ):
                if field in exact_receipt:
                    sample[field] = exact_receipt[field]
        samples.append(sample)
        if stable_cycles_observed >= stable_cycles_required:
            return snapshot, {
                'result': 'PASS',
                'next_mutation_authorized': operation != 'submit_frozen_comment',
                'terminal_delivery_verified': operation == 'submit_frozen_comment',
                'observe_required_before_next_mutation': (
                    operation != 'submit_frozen_comment'
                ),
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

    timeout_receipt = {
        'result': 'TIMEOUT',
        'next_mutation_authorized': False,
        'projection': postcondition.get('kind') or postcondition['projection'],
        'refresh_policy': barrier['refresh_policy'],
        'stable_cycles_required': stable_cycles_required,
        'stable_cycles_observed': stable_cycles_observed,
        'samples': samples,
    }
    if selected_thread_open_match is not None and last_snapshot is not None:
        try:
            timeout_receipt['selected_thread_failure_evidence'] = (
                _selected_thread_failure_evidence(
                    last_snapshot,
                    selected_thread_open_match.group('activity'),
                    selected_thread_open_match.group('body'),
                )
            )
        except Exception as exc:
            timeout_receipt['selected_thread_failure_evidence_error'] = (
                f'{type(exc).__name__}:{exc}'
            )
    return last_snapshot, timeout_receipt


def stable_initial_preparation_observation(
    deadline_at: float,
) -> tuple[Snapshot | None, dict[str, Any]]:
    barrier = _initial_preparation_observation_contract()
    if isinstance(deadline_at, bool) or not isinstance(deadline_at, (int, float)):
        raise ValueError(
            'LinkedIn initial preparation deadline must be monotonic seconds'
        )
    stable_cycles_required = barrier['stable_cycles']
    interval = barrier['interval_ms'] / 1000.0
    started_at = time.monotonic()
    barrier_deadline = min(
        float(deadline_at),
        started_at + (barrier['timeout_ms'] / 1000.0),
    )
    stable_cycles_observed = 0
    previous_state_digest: str | None = None
    last_snapshot: Snapshot | None = None
    samples: list[dict[str, Any]] = []

    while time.monotonic() < barrier_deadline:
        cache_invalidation = _invalidate_linkedin_firefox_subtree()
        _firefox, _document, snapshot = build_snapshot('linkedin')
        target, match_count = _notifications_target(snapshot)
        projected_mapped = {
            key: list(elements)
            for key, elements in snapshot.mapped.items()
            if key != NOTIFICATIONS_NAVIGATION
        }
        projected_mapped[NOTIFICATIONS_NAVIGATION] = (
            [replace(target, key=NOTIFICATIONS_NAVIGATION)]
            if target is not None
            else []
        )
        projected = replace(snapshot, mapped=projected_mapped)
        projected_matches = list(
            projected.mapped.get(NOTIFICATIONS_NAVIGATION) or []
        )
        declared: dict[str, Any] | None = None
        if len(projected_matches) == 1:
            declared = element_operation(
                NOTIFICATIONS_NAVIGATION,
                list(projected_matches[0].states),
                dict(projected_matches[0].raw or {}),
            )
        state_digest = (
            _notifications_target_state_digest(snapshot, target, match_count)
            if target is not None and match_count == 1
            else None
        )
        exact = (
            match_count == 1
            and len(projected_matches) == 1
            and isinstance(declared, dict)
            and declared.get('allowed_now') == ['activate']
            and state_digest is not None
        )
        if exact:
            stable_cycles_observed = (
                stable_cycles_observed + 1
                if state_digest == previous_state_digest
                else 1
            )
            previous_state_digest = state_digest
        else:
            stable_cycles_observed = 0
            previous_state_digest = None
        last_snapshot = projected
        samples.append({
            'sample': len(samples) + 1,
            'elapsed_ms': round((time.monotonic() - started_at) * 1000),
            'observed_url': snapshot.url,
            'notifications_target_match_count': match_count,
            'augmented_match_count': len(projected_matches),
            'declared_method': declared.get('method') if declared else None,
            'allowed_now': declared.get('allowed_now') if declared else None,
            'target_state_digest': state_digest,
            'exact': exact,
            'firefox_cache_invalidation': cache_invalidation,
        })
        if stable_cycles_observed >= stable_cycles_required:
            return projected, {
                'result': 'PASS',
                'compile_authorized': True,
                'next_mutation_authorized': False,
                'projection': barrier['projection'],
                'refresh_policy': barrier['refresh_policy'],
                'stable_cycles_required': stable_cycles_required,
                'stable_cycles_observed': stable_cycles_observed,
                'samples': samples,
            }
        remaining = barrier_deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))

    return last_snapshot, {
        'result': 'TIMEOUT',
        'compile_authorized': False,
        'next_mutation_authorized': False,
        'projection': barrier['projection'],
        'refresh_policy': barrier['refresh_policy'],
        'stable_cycles_required': stable_cycles_required,
        'stable_cycles_observed': stable_cycles_observed,
        'samples': samples,
    }


__all__ = [
    'NOTIFICATION_CANDIDATE_PREFIX',
    'NOTIFICATIONS_NAVIGATION',
    'NOTIFICATIONS_CONTINUATION_PREFIX',
    'SELECTED_POST_EDITOR_PREFIX',
    'SELECTED_POST_REACTION_PREFIX',
    'SELECTED_POST_SUBMIT_PREFIX',
    'augment_snapshot',
    'element_operation',
    'stable_initial_preparation_observation',
    'stable_scroll_post_action_observation',
    'stable_post_action_observation',
    'verify_comment_submit_precondition',
    'verify_post_action',
]
