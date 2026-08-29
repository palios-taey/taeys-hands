#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import types
from urllib.parse import quote


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

if 'gi' not in sys.modules:
    fake_gi = types.ModuleType('gi')
    fake_gi.require_version = lambda *_args: None
    fake_repository = types.ModuleType('gi.repository')

    class _FakeAtspi:
        class CoordType:
            SCREEN = 0

        class StateType:
            CHECKED = 'checked'
            DEFUNCT = 'defunct'
            EDITABLE = 'editable'
            ENABLED = 'enabled'
            EXPANDED = 'expanded'
            FOCUSABLE = 'focusable'
            FOCUSED = 'focused'
            MULTI_LINE = 'multi line'
            PRESSED = 'pressed'
            REQUIRED = 'required'
            SELECTED = 'selected'
            SENSITIVE = 'sensitive'
            SHOWING = 'showing'
            VISIBLE = 'visible'

        class Text:
            @staticmethod
            def get_character_count(text_iface):
                return len(text_iface.text)

            @staticmethod
            def get_text(text_iface, start, end):
                return text_iface.text[start:end]

    fake_repository.Atspi = _FakeAtspi
    sys.modules['gi'] = fake_gi
    sys.modules['gi.repository'] = fake_repository

from consultation_v2.platforms.linkedin import manual  # noqa: E402
from consultation_v2.platforms.linkedin.unit1_prepare import (  # noqa: E402
    LinkedInUnit1PreparationError,
    NOTIFICATION_EXCLUSIONS_SCHEMA,
    PRIVATE_SELECTION_DECISION_SCHEMA,
    _category_authority_sha256,
    accept_preparation_step,
    compile_preparation_step,
    extract_selected_source,
    preparation_transaction_sha256,
    project_notification_inventory as project_notification_inventory_with_authority,
)
from consultation_v2.types import ElementRef, Snapshot  # noqa: E402


REVISION = '1' * 64
REVISION_B = '9' * 64
POLICY_SHA256 = '2' * 64
ACTIVITY_A = '1234567890123456789'
ACTIVITY_B = '2234567890123456789'
BODY = 'One exact public post body.'
BODY_SHA256 = hashlib.sha256(BODY.encode('utf-8')).hexdigest()
INVENTORY_TRANSACTION_SHA256 = '3' * 64
INVENTORY_CATEGORY_AUTHORITY_SHA256 = _category_authority_sha256(
    INVENTORY_TRANSACTION_SHA256
)


def project_notification_inventory(snapshot, snapshot_revision):
    return project_notification_inventory_with_authority(
        snapshot,
        snapshot_revision,
        transaction_sha256=INVENTORY_TRANSACTION_SHA256,
        category_authority_sha256=INVENTORY_CATEGORY_AUTHORITY_SHA256,
    )


def canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')).hexdigest()


def exclusion_decision(readiness: dict, transaction_sha256: str) -> dict:
    require(
        readiness['state'] == 'ready_for_private_selection'
        and readiness['input']['continuation_available'] is True,
        'continuation exclusions were requested without exact readiness',
    )
    inventory = readiness['input']['notification_inventory']
    unsigned = {
        'decision_inventory_sha256': inventory[
            'decision_inventory_sha256'
        ],
        'excluded_candidates': [
            {
                'activity': row['activity'],
                'reason_codes': ['off_target'],
            }
            for row in inventory['actionable_links']
        ],
        'notification_inventory_sha256': inventory['inventory_sha256'],
        'policy_sha256': POLICY_SHA256,
        'schema': NOTIFICATION_EXCLUSIONS_SCHEMA,
        'transaction_sha256': transaction_sha256,
    }
    return {
        **unsigned,
        'exclusions_sha256': canonical_sha256(unsigned),
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_decision_input(readiness: dict) -> dict:
    selection_input = readiness['input']
    inventory = selection_input['notification_inventory']
    decision = selection_input['decision_input']
    expected_candidates = []
    for link in inventory['actionable_links']:
        row = inventory['rows'][link['ordinal'] - 1]
        expected_candidates.append({
            'activity': link['activity'],
            'notification_text': row['notification_text'],
            'notification_text_sha256': row['notification_text_sha256'],
            'age_seconds': row['age_seconds'],
            'age_token': row['age_token'],
            'ordinal': link['ordinal'],
            'element': link['element'],
            'element_sha256': link['element_sha256'],
            'uri': link['uri'],
            'uri_sha256': link['uri_sha256'],
        })
    require(
        set(decision) == {
            'schema',
            'policy_sha256',
            'transaction_sha256',
            'continuation_available',
            'decision_inventory_sha256',
            'inventory_sha256',
            'mounted_article_count',
            'actionable_candidates',
        }
        and decision['schema']
        == PRIVATE_SELECTION_DECISION_SCHEMA
        and decision['policy_sha256'] == selection_input['policy_sha256']
        and decision['transaction_sha256']
        == selection_input['transaction_sha256']
        and decision['continuation_available']
        == selection_input['continuation_available']
        and decision['decision_inventory_sha256']
        == inventory['decision_inventory_sha256']
        and decision['inventory_sha256'] == inventory['inventory_sha256']
        and decision['mounted_article_count']
        == inventory['mounted_article_count']
        and decision['actionable_candidates'] == expected_candidates
        and len(expected_candidates) == len(inventory['actionable_links'])
        and all(
            inventory['rows'][link['ordinal'] - 1]['actionable'] is True
            for link in inventory['actionable_links']
        ),
        'private selection decision input is not the exact actionable projection',
    )
    return decision


class Hyperlink:
    def __init__(self, uri: str) -> None:
        self.uri = uri

    def get_uri(self, _index: int) -> str:
        return self.uri


class Node:
    def __init__(
        self,
        role: str,
        name: str = '',
        *,
        text: str = '',
        states: list[str] | None = None,
        uri: str | None = None,
    ) -> None:
        self.role = role
        self.name = name
        self.text = text
        self.states = list(states or [])
        self.uri = uri
        self.parent: Node | None = None
        self.children: list[Node] = []

    def add(self, *children: 'Node') -> 'Node':
        for child in children:
            child.parent = self
            self.children.append(child)
        return self

    def get_child_count(self) -> int:
        return len(self.children)

    def get_child_at_index(self, index: int) -> 'Node':
        return self.children[index]

    def get_parent(self) -> 'Node | None':
        return self.parent

    def get_index_in_parent(self) -> int:
        return self.parent.children.index(self) if self.parent is not None else -1

    def get_role_name(self) -> str:
        return self.role

    def get_name(self) -> str:
        return self.name

    def get_text_iface(self):
        return self if self.role in {'entry', 'paragraph', 'section'} else None

    def get_state_set(self):
        states = frozenset(self.states)
        return types.SimpleNamespace(contains=lambda state: state in states)

    def get_hyperlink(self):
        return Hyperlink(self.uri) if self.uri is not None else None


def ref(
    node: Node,
    *,
    key: str | None = None,
    text: str | None = None,
    raw: dict | None = None,
) -> ElementRef:
    return ElementRef(
        key=key,
        name=node.name,
        role=node.role,
        x=None,
        y=None,
        states=list(node.states),
        text=text,
        atspi_obj=node,
        raw=dict(raw or {}),
    )


def activity_uri(activity: str) -> str:
    urn = quote(f'urn:li:activity:{activity}', safe='')
    return f'https://www.linkedin.com/feed/?highlightedUpdateUrn={urn}'


def notification_article(
    name: str,
    text: str,
    age: str,
    *,
    uri: str,
) -> tuple[Node, list[ElementRef]]:
    article = Node('article', name)
    profile_link = Node(
        'link',
        'View exact profile.',
        states=['enabled', 'focusable'],
        uri='https://www.linkedin.com/in/exact-profile',
    )
    content_link = Node(
        'link',
        text,
        states=['enabled', 'focusable'],
        uri=uri,
    )
    age_node = Node('paragraph', text=age)
    metadata = Node('section')
    article.add(profile_link, content_link, age_node, metadata)
    return article, [
        ref(article),
        ref(profile_link),
        ref(content_link),
        ref(age_node, text=age),
        ref(metadata),
    ]


def inventory_snapshot(
    *,
    notification_text: str = 'Unread notification. Alice posted an exact update.',
    include_categories: bool = False,
) -> Snapshot:
    root = Node('document web', 'LinkedIn Notifications')
    article_a, refs_a = notification_article(
        'Unread notification.',
        notification_text,
        '2h',
        uri=activity_uri(ACTIVITY_A),
    )
    article_b, refs_b = notification_article(
        'Notification',
        'Bob posted another exact update.',
        '1d',
        uri=activity_uri(ACTIVITY_B),
    )
    article_c, refs_c = notification_article(
        'Notification.',
        'Your profile appeared in search.',
        '3d',
        uri='https://www.linkedin.com/me/search-appearances/',
    )
    categories = [
        Node(
            'radio button',
            name,
            states=['checked'] if name == 'All' else [],
        )
        for name in ('All', 'Jobs', 'My posts', 'Mentions')
    ] if include_categories else []
    root.add(*categories, article_a, article_b, article_c)
    return Snapshot(
        platform='linkedin',
        url='https://www.linkedin.com/notifications/?filter=all',
        unknown=[
            *(ref(category) for category in categories),
            *refs_a,
            *refs_b,
            *refs_c,
        ],
    )


def without_visible_categories(snapshot: Snapshot) -> Snapshot:
    snapshot.unknown = [
        item for item in snapshot.unknown if item.role != 'radio button'
    ]
    return snapshot


def with_continuation(snapshot: Snapshot) -> Snapshot:
    snapshot.unknown.append(ref(Node(
        'push button',
        'Show more results',
        states=['enabled', 'focusable'],
    )))
    return manual.augment_snapshot(snapshot)


def semantic_inventory_variants() -> list[tuple[str, Snapshot]]:
    changed_text = inventory_snapshot(
        notification_text='Unread notification. Alice changed the exact update.',
        include_categories=True,
    )

    changed_activity = inventory_snapshot(include_categories=True)
    activity_link = next(
        item
        for item in changed_activity.unknown
        if item.role == 'link' and item.atspi_obj.uri == activity_uri(ACTIVITY_A)
    )
    activity_link.atspi_obj.uri = activity_uri(ACTIVITY_A + '2')

    changed_age = inventory_snapshot(include_categories=True)
    age = next(
        item
        for item in changed_age.unknown
        if item.role == 'paragraph' and item.text == '2h'
    )
    age.text = '3h'
    age.atspi_obj.text = '3h'

    changed_uri = inventory_snapshot(include_categories=True)
    uri_link = next(
        item
        for item in changed_uri.unknown
        if item.role == 'link' and item.atspi_obj.uri == activity_uri(ACTIVITY_A)
    )
    uri_link.atspi_obj.uri = activity_uri(ACTIVITY_A) + '&trk=changed'

    changed_path = inventory_snapshot(include_categories=True)
    path_root = next(
        item for item in changed_path.unknown if item.role == 'article'
    ).atspi_obj.get_parent()
    prefix = Node('generic')
    prefix.parent = path_root
    path_root.children.insert(0, prefix)

    changed_ordinal = inventory_snapshot(include_categories=True)
    ordinal_root = next(
        item for item in changed_ordinal.unknown if item.role == 'article'
    ).atspi_obj.get_parent()
    article_indexes = [
        index
        for index, child in enumerate(ordinal_root.children)
        if child.role == 'article'
    ]
    first, second = article_indexes[:2]
    ordinal_root.children[first], ordinal_root.children[second] = (
        ordinal_root.children[second],
        ordinal_root.children[first],
    )

    return [
        ('text', changed_text),
        ('activity', changed_activity),
        ('age', changed_age),
        ('uri', changed_uri),
        ('structural_path', changed_path),
        ('ordinal', changed_ordinal),
    ]


def navigation_snapshot() -> Snapshot:
    node = Node(
        'push button',
        'Notifications',
        states=['showing', 'enabled'],
    )
    return Snapshot(
        platform='linkedin',
        url='https://www.linkedin.com/feed/',
        mapped={manual.NOTIFICATIONS_NAVIGATION: [ref(
            node,
            key=manual.NOTIFICATIONS_NAVIGATION,
        )]},
    )


def comment_root(author: str, text: str) -> tuple[Node, Node, list[ElementRef]]:
    root = Node('section', f'{author} comment root')
    target = Node('section', text=text)
    child_2 = Node('generic').add(Node('generic').add(Node('generic').add(target)))
    control_parent = Node('generic')
    possessive = '\u2019 comment.' if author.endswith('s') else '\u2019s comment.'
    control = Node(
        'push button',
        f'View more options for {author}{possessive}',
        states=['enabled', 'focusable'],
    )
    control_parent.add(control)
    root.add(Node('generic'), Node('generic'), child_2, control_parent)
    return root, control, [ref(control), ref(target, text=text)]


def selected_snapshot(
    *,
    count: int = 2,
    visible: bool = True,
    visible_count: int | None = None,
    repost: bool = False,
    body_index: int = 9,
) -> Snapshot:
    document = Node('document web', 'LinkedIn post')
    post_root = Node('list item', states=['showing'])
    post_card = Node('generic')
    heading = Node('heading', 'Feed post')
    body = Node('section', text=BODY, states=['showing', 'enabled'])
    body_wrapper = Node('generic').add(body)
    effective_body_index = 12 if repost else body_index
    fillers = [Node('generic') for _index in range(effective_body_index - 1)]
    count_node = (
        Node(
            'push button',
            f'{count} comments' if count != 1 else '1 comment',
            states=['enabled', 'focusable'],
        )
        if count > 0
        else Node('generic')
    )
    post_card.add(
        heading,
        *fillers,
        body_wrapper,
        Node('generic'),
        Node('generic'),
        count_node,
    )
    refs = [ref(post_root), ref(body, text=BODY)]
    if count > 0:
        refs.append(ref(count_node))
    mounted_count = (
        min(count, 2) if visible_count is None and visible else
        0 if visible_count is None else visible_count
    )
    if mounted_count < 0 or mounted_count > count:
        raise ValueError('visible_count must be within the declared count')
    authors = [
        'Alice Jones',
        'Bob Example',
        'Carol North',
        'Diego West',
        'Eve Stone',
        'Frank Ocean',
        'Grace Hopper',
        'Heidi Fields',
        'Ivan Brooks',
    ]
    for index in range(mounted_count):
        comment, _control, comment_refs = comment_root(
            authors[index],
            'First exact comment.' if index == 0 else '' if index == 1 else (
                f'Exact comment {index + 1}.'
            ),
        )
        post_card.add(comment)
        refs.extend([ref(comment), *comment_refs])
    post_root.add(post_card)
    document.add(post_root)
    selected_key = f'{manual.SELECTED_POST_PREFIX}{ACTIVITY_A}'
    selected = ref(
        body,
        key=selected_key,
        text=BODY,
        raw={
            'selected_activity': ACTIVITY_A,
            'selected_post_body_sha256': BODY_SHA256,
        },
    )
    return Snapshot(
        platform='linkedin',
        url=activity_uri(ACTIVITY_A),
        mapped={selected_key: [selected]},
        unknown=refs,
    )


def virtualized_selected_snapshot() -> Snapshot:
    snapshot = selected_snapshot(visible=False, body_index=12)
    selected_root = next(
        item.atspi_obj
        for item in snapshot.unknown
        if item.role == 'list item'
    )
    selected_body = _node_at_path(selected_root, [0, 12, 0])
    selected_root.states = []
    selected_body.states = ['enabled']
    snapshot.mapped = {}
    snapshot.unknown = [
        item
        for item in snapshot.unknown
        if id(item.atspi_obj) not in {id(selected_root), id(selected_body)}
    ]

    later_root = Node('list item', states=['showing'])
    later_card = Node('generic')
    later_heading = Node('heading', 'Feed post')
    later_body = Node(
        'section',
        text='Unrelated later visible post.',
        states=['showing', 'enabled'],
    )
    later_count = Node(
        'push button',
        '3 comments',
        states=['showing', 'enabled', 'focusable'],
    )
    later_card.add(
        later_heading,
        *(Node('generic') for _index in range(11)),
        Node('generic').add(later_body),
        Node('generic'),
        Node('generic'),
        later_count,
    )
    later_root.add(later_card)
    selected_root.get_parent().add(later_root)
    snapshot.unknown.extend([
        ref(later_root),
        ref(later_body, text=later_body.text),
        ref(later_count),
    ])
    return snapshot


def _node_at_path(node: Node, path: list[int]) -> Node:
    current = node
    for index in path:
        current = current.get_child_at_index(index)
    return current


def with_thread_expander(
    snapshot: Snapshot,
    more_count: int,
    *,
    states: list[str] | None = None,
) -> Snapshot:
    post_root = next(
        item.atspi_obj
        for item in snapshot.unknown
        if item.role == 'list item'
    )
    post_card = post_root.get_child_at_index(0)
    suffix = 'comment' if more_count == 1 else 'comments'
    expander = Node(
        'push button',
        f'See {more_count} more {suffix}',
        states=states if states is not None else ['enabled', 'focusable'],
    )
    post_card.add(expander)
    snapshot.unknown.append(ref(expander))
    return snapshot


def with_thread_opener(snapshot: Snapshot, count: int = 2) -> Snapshot:
    count_element = next(
        item
        for item in snapshot.unknown
        if item.role == 'push button'
        and item.name == (f'{count} comments' if count != 1 else '1 comment')
    )
    key = (
        f'{manual.SELECTED_THREAD_OPEN_PREFIX}{ACTIVITY_A}_body_{BODY_SHA256}'
    )
    snapshot.mapped[key] = [ref(
        count_element.atspi_obj,
        key=key,
        raw={
            'selected_activity': ACTIVITY_A,
            'selected_post_body_sha256': BODY_SHA256,
        },
    )]
    return snapshot


def with_zero_thread_opener(
    snapshot: Snapshot,
    *,
    compact_variant: bool = False,
    media_variant: bool = False,
) -> Snapshot:
    post_root = next(
        item.atspi_obj
        for item in snapshot.unknown
        if item.role == 'list item'
    )
    post_card = post_root.get_child_at_index(0)
    post_card.add(
        *(Node('generic') for _index in range(
            0 if compact_variant else 3 if media_variant else 2
        )),
        Node(
            'push button',
            'Comment',
            states=(
                ['enabled', 'focusable']
                if media_variant
                else ['showing', 'enabled', 'focusable']
            ),
        ),
        Node('push button', 'Repost', states=['enabled', 'focusable']),
        Node('link', 'Send', states=['enabled', 'focusable']),
    )
    snapshot.unknown.extend(ref(node) for node in post_card.children[-5:])
    return snapshot


def with_empty_comment_editor(snapshot: Snapshot) -> Snapshot:
    post_root = next(
        item.atspi_obj
        for item in snapshot.unknown
        if item.role == 'list item'
    )
    post_card = post_root.get_child_at_index(0)
    editor_text = Node(
        'paragraph',
        text='Add a comment...',
        states=['editable', 'visible', 'sensitive'],
    )
    editor = Node(
        'entry',
        'Text editor for creating comment',
        text='\uFFFC',
        states=['editable', 'focusable', 'visible', 'sensitive', 'showing'],
    ).add(editor_text)
    wrapper_3 = Node('generic').add(editor)
    wrapper_2 = Node('generic').add(wrapper_3)
    wrapper_1 = Node('generic').add(wrapper_2)
    post_card.add(wrapper_1)
    snapshot.unknown.extend([
        ref(wrapper_1),
        ref(wrapper_2),
        ref(wrapper_3),
        ref(editor),
        ref(editor_text, text='Add a comment...'),
    ])
    return snapshot


def barrier(card: dict) -> dict:
    postcondition = {
        'element_key': card['element'],
        'operation': card['verification_operation'],
        'effect_class': card['effect_class'],
        'postcondition': card['postcondition_kind'],
    }
    if card['phase'] == 'notifications_navigation':
        postcondition.update({
            'route_exact': True,
            'category_exact': True,
        })
    return {
        'result': 'PASS',
        'next_mutation_authorized': card['phase'] not in {
            'thread_scroll',
            'thread_expand_scroll',
        },
        'terminal_delivery_verified': False,
        'observe_required_before_next_mutation': True,
        'projection': card['postcondition_kind'],
        'refresh_policy': 'invalidate_reacquire',
        'stable_cycles_required': 2,
        'stable_cycles_observed': 2,
        'samples': [
            {'sample': 1, 'route_exact': True},
            {'sample': 2, 'route_exact': True},
        ],
        'postcondition_receipt': postcondition,
    }


def expect_error(operation, message: str) -> None:
    try:
        operation()
    except LinkedInUnit1PreparationError:
        return
    raise AssertionError(message)


def expect_value_error(operation, message: str) -> None:
    try:
        operation()
    except ValueError:
        return
    raise AssertionError(message)


def schema_required(name: str) -> set[str]:
    return set(json.loads(
        (
            REPO_ROOT
            / 'consultation_v2/platforms/linkedin'
            / name
        ).read_text(encoding='utf-8')
    )['required'])


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, interval: float) -> None:
        self.now += interval


def validate_initial_observation_barrier() -> None:
    require(
        manual._initial_preparation_observation_contract()['timeout_ms'] == 120000,
        'initial barrier does not cover two measured LinkedIn tree traversals',
    )
    require(
        manual._manual_post_action_contract()['observation_barrier'][
            'timeout_ms'
        ] == 90000,
        'post-action barrier does not cover two measured LinkedIn tree traversals',
    )
    require(
        manual._manual_notification_contract()['candidate'][
            'post_action_observation_barrier'
        ]['timeout_ms'] == 180000,
        'candidate barrier does not cover transition plus two measured tree traversals',
    )
    exact = navigation_snapshot()
    missing = Snapshot(platform='linkedin', url=exact.url)
    sequence = [missing, exact, exact]
    clock = Clock()
    original_build_snapshot = manual.build_snapshot
    original_notifications_target = manual._notifications_target
    original_monotonic = manual.time.monotonic
    original_sleep = manual.time.sleep

    def build_sequence(_platform: str):
        return object(), object(), sequence.pop(0)

    def mapped_target(snapshot: Snapshot):
        matches = list(
            snapshot.mapped.get(manual.NOTIFICATIONS_NAVIGATION) or []
        )
        return (matches[0] if len(matches) == 1 else None), len(matches)

    manual.build_snapshot = build_sequence
    manual._notifications_target = mapped_target
    manual.time.monotonic = clock.monotonic
    manual.time.sleep = clock.sleep
    try:
        snapshot, receipt = manual.stable_initial_preparation_observation(10.0)
    finally:
        manual.build_snapshot = original_build_snapshot
        manual._notifications_target = original_notifications_target
        manual.time.monotonic = original_monotonic
        manual.time.sleep = original_sleep
    require(
        snapshot is not None
        and snapshot.url == exact.url
        and len(
            snapshot.mapped.get(manual.NOTIFICATIONS_NAVIGATION) or []
        ) == 1,
        'barrier did not return the last augmented exact snapshot',
    )
    require(not sequence, 'barrier did not require two exact samples after stale read')
    require(
        receipt['result'] == 'PASS'
        and receipt['compile_authorized'] is True
        and receipt['next_mutation_authorized'] is False
        and receipt['stable_cycles_observed'] == 2,
        'stale-first-read barrier did not authorize compile without mutation',
    )
    require(
        [sample['notifications_target_match_count'] for sample in receipt['samples']]
        == [0, 1, 1]
        and all(
            sample['allowed_now'] == ['activate']
            for sample in receipt['samples'][1:]
        ),
        'barrier samples did not preserve exact target evidence',
    )

    clock = Clock()
    manual.build_snapshot = lambda _platform: (
        object(),
        object(),
        Snapshot(platform='linkedin', url=exact.url),
    )
    manual._notifications_target = mapped_target
    manual.time.monotonic = clock.monotonic
    manual.time.sleep = clock.sleep
    try:
        _snapshot, timeout = manual.stable_initial_preparation_observation(0.4)
    finally:
        manual.build_snapshot = original_build_snapshot
        manual._notifications_target = original_notifications_target
        manual.time.monotonic = original_monotonic
        manual.time.sleep = original_sleep
    require(
        timeout['result'] == 'TIMEOUT'
        and timeout['compile_authorized'] is False
        and timeout['next_mutation_authorized'] is False,
        'unsettled initial observation authorized compile or mutation',
    )


def main() -> int:
    validate_initial_observation_barrier()
    stream = inventory_snapshot(include_categories=True)
    inventory = project_notification_inventory(stream, REVISION)
    artifact = inventory.artifact
    require(artifact['mounted_article_count'] == 3, 'full stream omitted an article')
    require(len(artifact['rows']) == 3, 'inventory row cardinality drifted')
    require(len(artifact['actionable_links']) == 1, 'actionable links were not separate')
    require(
        artifact['rows'][0]['notification_text']
        == 'Unread notification. Alice posted an exact update.',
        'raw notification text was not preserved',
    )
    offset_surface = inventory_snapshot(include_categories=True)
    offset_root = next(
        item.atspi_obj.get_parent()
        for item in offset_surface.unknown
        if item.role == 'article'
    )
    article_indexes = [
        index
        for index, child in enumerate(offset_root.children)
        if child.role == 'article'
    ]
    first, second = article_indexes[:2]
    offset_root.children[first], offset_root.children[second] = (
        offset_root.children[second],
        offset_root.children[first],
    )
    offset_surface = manual.augment_snapshot(offset_surface)
    offset_inventory = project_notification_inventory(offset_surface, REVISION)
    offset_actionable = offset_inventory.artifact['actionable_links'][0]
    offset_target = offset_inventory.targets[offset_actionable['element']]
    require(
        offset_actionable['activity'] == ACTIVITY_A
        and offset_actionable['ordinal'] == 2
        and offset_actionable['element']
        == f'{manual.NOTIFICATION_CANDIDATE_PREFIX}001_activity_{ACTIVITY_A}'
        and offset_target.raw['notification_ordinal'] == 1
        and len(
            offset_surface.mapped.get(offset_actionable['element']) or []
        ) == 1
        and offset_surface.mapped[offset_actionable['element']][0].atspi_obj
        is offset_target.atspi_obj,
        'non-actionable article offset the exact runtime candidate key',
    )
    require(
        artifact['inventory_sha256'] == canonical_sha256({
            'schema': artifact['schema'],
            'platform': artifact['platform'],
            'route': artifact['route'],
            'mounted_article_count': artifact['mounted_article_count'],
            'rows': [
                {
                    key: value
                    for key, value in row.items()
                    if key not in {'snapshot_revision', 'structural_path'}
                }
                for row in artifact['rows']
            ],
            'actionable_links': artifact['actionable_links'],
        }),
        'inventory digest material included provenance or omitted semantics',
    )
    same_surface_next_observation = project_notification_inventory(
        inventory_snapshot(include_categories=True),
        REVISION_B,
    )
    require(
        artifact['snapshot_revision'] == REVISION
        and all(row['snapshot_revision'] == REVISION for row in artifact['rows'])
        and same_surface_next_observation.artifact['snapshot_revision'] == REVISION_B
        and all(
            row['snapshot_revision'] == REVISION_B
            for row in same_surface_next_observation.artifact['rows']
        )
        and same_surface_next_observation.artifact['inventory_sha256']
        == artifact['inventory_sha256'],
        'equivalent observations did not preserve provenance with one semantic digest',
    )
    semantic_variants = semantic_inventory_variants()
    for changed_field, changed_surface in semantic_variants:
        changed = project_notification_inventory(changed_surface, REVISION_B)
        require(
            (
                changed.artifact['inventory_sha256']
                == artifact['inventory_sha256']
            ) == (changed_field == 'structural_path'),
            f'inventory digest authority mismatch for changed {changed_field}',
        )

    obsolete_one_link = inventory_snapshot(include_categories=True)
    obsolete_article = next(
        item for item in obsolete_one_link.unknown if item.role == 'article'
    )
    obsolete_children = obsolete_article.atspi_obj.children
    obsolete_article.atspi_obj.children = [
        obsolete_children[1],
        obsolete_children[2],
    ]
    expect_error(
        lambda: project_notification_inventory(obsolete_one_link, REVISION),
        'obsolete one-link notification article was accepted',
    )

    extra_child = inventory_snapshot(include_categories=True)
    extra_article = next(
        item for item in extra_child.unknown if item.role == 'article'
    )
    extra_article.atspi_obj.add(Node('link', 'Unexpected direct link'))
    extra_child.unknown.append(ref(extra_article.atspi_obj.children[-1]))
    expect_error(
        lambda: project_notification_inventory(extra_child, REVISION),
        'extra direct child was accepted',
    )

    missing_child = inventory_snapshot(include_categories=True)
    missing_article = next(
        item for item in missing_child.unknown if item.role == 'article'
    )
    missing_article.atspi_obj.children.pop()
    expect_error(
        lambda: project_notification_inventory(missing_child, REVISION),
        'missing direct child was accepted',
    )

    reordered_child = inventory_snapshot(include_categories=True)
    reordered_article = next(
        item for item in reordered_child.unknown if item.role == 'article'
    )
    reordered_article.atspi_obj.children[1:3] = [
        reordered_article.atspi_obj.children[2],
        reordered_article.atspi_obj.children[1],
    ]
    expect_error(
        lambda: project_notification_inventory(reordered_child, REVISION),
        'reordered direct child was accepted',
    )

    unmapped_content = inventory_snapshot(include_categories=True)
    unmapped_article = next(
        item for item in unmapped_content.unknown if item.role == 'article'
    )
    unmapped_node = unmapped_article.atspi_obj.children[1]
    unmapped_content.unknown = [
        item
        for item in unmapped_content.unknown
        if id(item.atspi_obj) != id(unmapped_node)
    ]
    expect_error(
        lambda: project_notification_inventory(unmapped_content, REVISION),
        'unmapped content-link index was accepted',
    )

    invalid_uri = inventory_snapshot(include_categories=True)
    invalid_uri_article = next(
        item for item in invalid_uri.unknown if item.role == 'article'
    )
    invalid_uri_article.atspi_obj.children[1].uri = '/relative-content'
    expect_error(
        lambda: project_notification_inventory(invalid_uri, REVISION),
        'invalid content-link URI was accepted',
    )
    duplicated = inventory_snapshot(include_categories=True)
    duplicate_root = next(
        item for item in duplicated.unknown if item.role == 'article'
    ).atspi_obj.get_parent()
    duplicate_article, duplicate_refs = notification_article(
        'Unread notification.',
        'Unread notification. Alice posted an exact update.',
        '2h',
        uri=activity_uri(ACTIVITY_A),
    )
    duplicate_root.add(duplicate_article)
    duplicated.unknown.extend(duplicate_refs)
    expect_error(
        lambda: project_notification_inventory(duplicated, REVISION),
        'duplicate raw notification row was accepted',
    )

    envelope = {
        'schema': 'linkedin_unit1_preparation_envelope_v1',
        'operation': 'comment_from_notifications_prepare',
        'cycle_id': 'cycle-1',
        'transaction_id': 'transaction-1',
        'display': ':18',
        'policy_sha256': POLICY_SHA256,
        'selection': None,
    }
    transaction_sha256 = preparation_transaction_sha256(envelope)
    receipts: list[dict] = []
    navigation = compile_preparation_step(
        navigation_snapshot(),
        REVISION,
        envelope,
        receipts,
    )
    require(
        navigation['phase'] == 'notifications_navigation',
        'preparation did not begin from Notifications',
    )
    require(
        schema_required('unit1-preparation-action-card.schema.json')
        == set(navigation),
        'preparation action-card schema drifted',
    )
    missing_navigation_category = barrier(navigation)
    missing_navigation_category['postcondition_receipt'].pop('category_exact')
    expect_error(
        lambda: accept_preparation_step(
            navigation,
            missing_navigation_category,
            None,
        ),
        'navigation receipt accepted missing All-category authority',
    )
    wrong_navigation_category = barrier(navigation)
    wrong_navigation_category['postcondition_receipt']['category_exact'] = False
    expect_error(
        lambda: accept_preparation_step(
            navigation,
            wrong_navigation_category,
            None,
        ),
        'navigation receipt accepted false All-category authority',
    )
    receipts.append(accept_preparation_step(navigation, barrier(navigation), None))
    require(
        receipts[0]['category_authority_sha256']
        == _category_authority_sha256(transaction_sha256),
        'navigation receipt category authority is not reconstructable',
    )

    wrong_token = dict(receipts[0])
    wrong_token['category_authority_sha256'] = '4' * 64
    wrong_token_payload = dict(wrong_token)
    wrong_token_payload.pop('receipt_sha256')
    wrong_token['receipt_sha256'] = canonical_sha256(wrong_token_payload)
    expect_error(
        lambda: compile_preparation_step(
            stream,
            REVISION,
            envelope,
            [wrong_token],
        ),
        're-signed wrong category authority token was accepted',
    )
    missing_token = dict(receipts[0])
    missing_token.pop('category_authority_sha256')
    missing_token_payload = dict(missing_token)
    missing_token_payload.pop('receipt_sha256')
    missing_token['receipt_sha256'] = canonical_sha256(missing_token_payload)
    expect_error(
        lambda: compile_preparation_step(
            stream,
            REVISION,
            envelope,
            [missing_token],
        ),
        'missing category authority token was accepted',
    )
    wrong_transaction = dict(receipts[0])
    wrong_transaction['transaction_sha256'] = '5' * 64
    wrong_transaction['category_authority_sha256'] = (
        _category_authority_sha256('5' * 64)
    )
    wrong_transaction_payload = dict(wrong_transaction)
    wrong_transaction_payload.pop('receipt_sha256')
    wrong_transaction['receipt_sha256'] = canonical_sha256(
        wrong_transaction_payload
    )
    expect_error(
        lambda: compile_preparation_step(
            stream,
            REVISION,
            envelope,
            [wrong_transaction],
        ),
        'wrong-transaction category authority was accepted',
    )
    wrong_order = dict(receipts[0])
    wrong_order['phase'] = 'notifications_continuation'
    wrong_order_payload = dict(wrong_order)
    wrong_order_payload.pop('receipt_sha256')
    wrong_order['receipt_sha256'] = canonical_sha256(wrong_order_payload)
    expect_error(
        lambda: compile_preparation_step(
            stream,
            REVISION,
            envelope,
            [wrong_order],
        ),
        'non-navigation-first category authority was accepted',
    )

    exact_route_navigation = inventory_snapshot(include_categories=True)
    exact_route_navigation.mapped[manual.NOTIFICATIONS_NAVIGATION] = (
        navigation_snapshot().mapped[manual.NOTIFICATIONS_NAVIGATION]
    )
    exact_route_card = compile_preparation_step(
        exact_route_navigation,
        REVISION,
        envelope,
        [],
    )
    require(
        exact_route_card['schema'] == 'linkedin_unit1_preparation_action_card_v1'
        and exact_route_card['phase'] == 'notifications_navigation'
        and exact_route_card['method'] == 'activate'
        and exact_route_card['element'] == manual.NOTIFICATIONS_NAVIGATION,
        'exact Notifications URL skipped mandatory Notifications activation',
    )

    partial_selected_navigation = navigation_snapshot()
    partial_selected_navigation.url = activity_uri(ACTIVITY_A)
    partial_navigation_target = partial_selected_navigation.mapped[
        manual.NOTIFICATIONS_NAVIGATION
    ][0]
    original_notifications_target = manual._notifications_target
    manual._notifications_target = lambda _snapshot: (
        partial_navigation_target,
        1,
    )
    try:
        partial_selected_augmented = manual.augment_snapshot(
            partial_selected_navigation
        )
    finally:
        manual._notifications_target = original_notifications_target
    require(
        compile_preparation_step(
            partial_selected_augmented,
            REVISION,
            envelope,
            [],
        )['element'] == manual.NOTIFICATIONS_NAVIGATION
        and not any(
            key.startswith(manual.SELECTED_POST_PREFIX)
            for key in partial_selected_augmented.mapped
        ),
        'partial selected-post rendering blocked mandatory Notifications navigation',
    )

    missing_categories = without_visible_categories(
        inventory_snapshot(include_categories=True)
    )
    missing_categories.mapped[manual.NOTIFICATIONS_NAVIGATION] = (
        navigation_snapshot().mapped[manual.NOTIFICATIONS_NAVIGATION]
    )
    original_notifications_target = manual._notifications_target
    manual._notifications_target = lambda _snapshot: (
        missing_categories.mapped[manual.NOTIFICATIONS_NAVIGATION][0],
        1,
    )
    try:
        augmented_missing_categories = manual.augment_snapshot(missing_categories)
    finally:
        manual._notifications_target = original_notifications_target
    require(
        compile_preparation_step(
            augmented_missing_categories,
            REVISION,
            envelope,
            [],
        )['element'] == manual.NOTIFICATIONS_NAVIGATION,
        'missing category proof hid the mandatory Notifications target',
    )
    require(
        any(
            key.startswith(manual.NOTIFICATION_CANDIDATE_PREFIX)
            for key in augmented_missing_categories.mapped
        ),
        'exact-route candidate projection depended on mounted category controls',
    )
    require(
        project_notification_inventory(
            missing_categories,
            REVISION,
        ).artifact['mounted_article_count'] == 3,
        'chain-authorized inventory still depended on visible category controls',
    )
    expect_error(
        lambda: project_notification_inventory_with_authority(
            missing_categories,
            REVISION,
            transaction_sha256=INVENTORY_TRANSACTION_SHA256,
            category_authority_sha256='6' * 64,
        ),
        'inventory accepted a wrong category authority token',
    )
    navigation_postcondition = manual.verify_post_action(
        stream,
        manual.NOTIFICATIONS_NAVIGATION,
        'activate',
    )
    require(
        navigation_postcondition['route_exact'] is True
        and navigation_postcondition['category_exact'] is True,
        'Notifications activation did not prove exact route and All category',
    )
    try:
        manual.verify_post_action(
            missing_categories,
            manual.NOTIFICATIONS_NAVIGATION,
            'activate',
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            'Notifications activation accepted a missing All-category proof'
        )
    wrong_selected_category = inventory_snapshot(include_categories=True)
    for item in wrong_selected_category.unknown:
        if item.role == 'radio button':
            item.states = ['checked'] if item.name == 'Jobs' else []
    try:
        manual.verify_post_action(
            wrong_selected_category,
            manual.NOTIFICATIONS_NAVIGATION,
            'activate',
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            'Notifications activation accepted selected Jobs category'
        )
    near_route = inventory_snapshot(include_categories=True)
    near_route.url = 'https://www.linkedin.com/notifications/?filter=mentions'
    near_route.mapped[manual.NOTIFICATIONS_NAVIGATION] = (
        navigation_snapshot().mapped[manual.NOTIFICATIONS_NAVIGATION]
    )
    require(
        compile_preparation_step(
            near_route,
            REVISION,
            envelope,
            [],
        )['element'] == manual.NOTIFICATIONS_NAVIGATION,
        'non-exact Notifications route did not compile mandatory activation',
    )

    first_continuation_surface = with_continuation(
        inventory_snapshot(include_categories=True)
    )
    continuation_receipts = list(receipts)
    first_continuation_readiness = compile_preparation_step(
        first_continuation_surface,
        REVISION,
        envelope,
        continuation_receipts,
    )
    require(
        first_continuation_readiness['state'] == 'ready_for_private_selection'
        and first_continuation_readiness['input']['continuation_available'] is True,
        'continuation bypassed the mounted candidate inventory',
    )
    require_decision_input(first_continuation_readiness)
    first_exclusions = exclusion_decision(
        first_continuation_readiness,
        transaction_sha256,
    )
    first_excluded_envelope = {**envelope, 'selection': first_exclusions}
    first_continuation = compile_preparation_step(
        first_continuation_surface,
        REVISION_B,
        first_excluded_envelope,
        continuation_receipts,
    )
    require(
        first_continuation['phase'] == 'notifications_continuation'
        and first_continuation['snapshot_revision'] == REVISION_B,
        'equivalent fresh observation refused exact prior exclusions',
    )
    continuation_receipts.append(accept_preparation_step(
        first_continuation,
        barrier(first_continuation),
        continuation_receipts[-1]['receipt_sha256'],
    ))
    require(
        continuation_receipts[-1]['category_authority_sha256']
        == continuation_receipts[0]['category_authority_sha256'],
        'continuation did not carry category authority',
    )

    second_continuation_surface = without_visible_categories(
        inventory_snapshot(include_categories=True)
    )
    second_root = next(
        item
        for item in second_continuation_surface.unknown
        if item.role == 'article'
    ).atspi_obj.get_parent()
    fourth_article, fourth_references = notification_article(
        'Notification.',
        'Someone viewed your profile.',
        '4d',
        uri='https://www.linkedin.com/me/profile-views/',
    )
    second_root.add(fourth_article)
    second_continuation_surface.unknown.extend(fourth_references)
    second_continuation_surface.unknown.append(ref(Node(
        'push button',
        'Show more results',
        states=['enabled', 'focusable'],
    )))
    second_continuation_surface = manual.augment_snapshot(
        second_continuation_surface
    )
    require(
        any(
            key.startswith(manual.NOTIFICATION_CANDIDATE_PREFIX)
            for key in second_continuation_surface.mapped
        ),
        'second virtualized continuation hid exact-route candidate keys',
    )
    presentation_drift_continuation = compile_preparation_step(
        second_continuation_surface,
        REVISION,
        first_excluded_envelope,
        continuation_receipts,
    )
    require(
        presentation_drift_continuation['phase']
        == 'notifications_continuation',
        'nonactionable presentation drift invalidated exact candidate exclusions',
    )
    changed_candidate_surface = with_continuation(inventory_snapshot(
        notification_text='Unread notification. Alice changed the exact update.',
        include_categories=True,
    ))
    changed_candidate_readiness = compile_preparation_step(
        changed_candidate_surface,
        REVISION,
        first_excluded_envelope,
        continuation_receipts,
    )
    require(
        changed_candidate_readiness['state'] == 'ready_for_private_selection'
        and changed_candidate_readiness['input']['notification_inventory'][
            'decision_inventory_sha256'
        ] != first_exclusions['decision_inventory_sha256']
        and 'phase' not in changed_candidate_readiness,
        'changed exact candidate content did not require a fresh private decision',
    )
    second_continuation_readiness = compile_preparation_step(
        second_continuation_surface,
        REVISION,
        envelope,
        continuation_receipts,
    )
    require(
        second_continuation_readiness['state'] == 'ready_for_private_selection'
        and second_continuation_readiness['input']['continuation_available'] is True,
        'second continuation bypassed its changed mounted inventory',
    )
    second_exclusions = exclusion_decision(
        second_continuation_readiness,
        transaction_sha256,
    )
    partial_exclusions = {
        **second_exclusions,
        'excluded_candidates': second_exclusions['excluded_candidates'][:-1],
    }
    partial_unsigned = dict(partial_exclusions)
    partial_unsigned.pop('exclusions_sha256')
    partial_exclusions['exclusions_sha256'] = canonical_sha256(partial_unsigned)
    expect_error(
        lambda: compile_preparation_step(
            second_continuation_surface,
            REVISION,
            {**envelope, 'selection': partial_exclusions},
            continuation_receipts,
        ),
        'partial exclusions authorized continuation',
    )
    duplicate_exclusions = {
        **second_exclusions,
        'excluded_candidates': [
            *second_exclusions['excluded_candidates'],
            second_exclusions['excluded_candidates'][0],
        ],
    }
    duplicate_unsigned = dict(duplicate_exclusions)
    duplicate_unsigned.pop('exclusions_sha256')
    duplicate_exclusions['exclusions_sha256'] = canonical_sha256(
        duplicate_unsigned
    )
    expect_error(
        lambda: preparation_transaction_sha256({
            **envelope,
            'selection': duplicate_exclusions,
        }),
        'duplicate excluded activity was accepted',
    )
    unknown_reason_exclusions = {
        **second_exclusions,
        'excluded_candidates': [
            {
                **second_exclusions['excluded_candidates'][0],
                'reason_codes': ['unknown_reason'],
            },
            *second_exclusions['excluded_candidates'][1:],
        ],
    }
    unknown_reason_unsigned = dict(unknown_reason_exclusions)
    unknown_reason_unsigned.pop('exclusions_sha256')
    unknown_reason_exclusions['exclusions_sha256'] = canonical_sha256(
        unknown_reason_unsigned
    )
    expect_error(
        lambda: preparation_transaction_sha256({
            **envelope,
            'selection': unknown_reason_exclusions,
        }),
        'unknown exclusion reason was accepted',
    )
    second_continuation = compile_preparation_step(
        second_continuation_surface,
        REVISION,
        {**envelope, 'selection': second_exclusions},
        continuation_receipts,
    )
    require(
        second_continuation['phase'] == 'notifications_continuation',
        'complete second inventory exclusions did not authorize continuation',
    )

    stream_without_categories = without_visible_categories(
        inventory_snapshot(include_categories=True)
    )

    ready_selection = compile_preparation_step(
        stream_without_categories,
        REVISION,
        envelope,
        receipts,
    )
    require(
        ready_selection['state'] == 'ready_for_private_selection',
        'complete stream did not produce private selection input',
    )
    require_decision_input(ready_selection)
    require(
        ready_selection['input']['continuation_available'] is False,
        'complete stream incorrectly exposed continuation authority',
    )
    require(
        schema_required('unit1-preparation-result.schema.json')
        == set(ready_selection),
        'preparation result schema drifted',
    )
    selection_unsigned = {
        'author_cooloff_passed': True,
        'dedup_passed': True,
        'notification_inventory_sha256': artifact['inventory_sha256'],
        'selected_activity': ACTIVITY_A,
        'selected_age_seconds': 7200,
        'selected_notification_ordinal': 1,
        'selected_notification_text': artifact['rows'][0]['notification_text'],
        'selected_notification_text_sha256': artifact['rows'][0][
            'notification_text_sha256'
        ],
        'target_passed': True,
        'transaction_sha256': transaction_sha256,
    }
    selection = {
        **selection_unsigned,
        'selection_sha256': canonical_sha256(selection_unsigned),
    }
    selected_envelope = {**envelope, 'selection': selection}
    candidate_key = next(
        key
        for key in first_continuation_surface.mapped
        if (
            key.startswith(manual.NOTIFICATION_CANDIDATE_PREFIX)
            and key.endswith(ACTIVITY_A)
        )
    )
    require(
        len(
            first_continuation_surface.mapped.get(
                manual.NOTIFICATIONS_CONTINUATION,
            ) or []
        ) == 1
        and len(first_continuation_surface.mapped.get(candidate_key) or []) == 1,
        'candidate and continuation did not coexist as exact runtime targets',
    )
    candidate_before_continuation = compile_preparation_step(
        first_continuation_surface,
        REVISION_B,
        selected_envelope,
        receipts,
    )
    require(
        candidate_before_continuation['phase'] == 'notification_candidate'
        and candidate_before_continuation['snapshot_revision'] == REVISION_B
        and candidate_before_continuation['element'].endswith(ACTIVITY_A)
        and len(
            first_continuation_surface.mapped.get(
                candidate_before_continuation['element'],
            ) or []
        ) == 1,
        'equivalent fresh observation refused exact qualifying selection',
    )
    for changed_field, changed_surface in semantic_variants:
        changed_continuation_surface = with_continuation(changed_surface)
        if changed_field == 'structural_path':
            moved_candidate = compile_preparation_step(
                changed_continuation_surface,
                REVISION_B,
                selected_envelope,
                receipts,
            )
            require(
                moved_candidate['phase'] == 'notification_candidate'
                and moved_candidate['element'].endswith(ACTIVITY_A),
                'structural-path churn invalidated exact selection authority',
            )
        else:
            expect_error(
                lambda changed_continuation_surface=changed_continuation_surface: (
                    compile_preparation_step(
                        changed_continuation_surface,
                        REVISION_B,
                        selected_envelope,
                        receipts,
                    )
                ),
                f'changed {changed_field} retained stale selection authority',
            )
        if changed_field in {'age', 'ordinal', 'structural_path'}:
            equivalent_exclusion = compile_preparation_step(
                changed_continuation_surface,
                REVISION_B,
                first_excluded_envelope,
                receipts,
            )
            require(
                equivalent_exclusion['phase'] == 'notifications_continuation',
                f'changed {changed_field} invalidated exact candidate exclusions',
            )
        else:
            refreshed_exclusions = compile_preparation_step(
                changed_continuation_surface,
                REVISION_B,
                first_excluded_envelope,
                receipts,
            )
            require(
                refreshed_exclusions['state'] == 'ready_for_private_selection'
                and refreshed_exclusions['input']['notification_inventory'][
                    'decision_inventory_sha256'
                ] != first_exclusions['decision_inventory_sha256']
                and 'phase' not in refreshed_exclusions,
                f'changed {changed_field} did not require fresh private selection',
            )
    candidate = compile_preparation_step(
        stream_without_categories,
        REVISION,
        selected_envelope,
        receipts,
    )
    require(
        candidate['phase'] == 'notification_candidate'
        and candidate['element'].endswith(ACTIVITY_A),
        'exact private selection did not compile to one candidate card',
    )
    detached_transition = inventory_snapshot(include_categories=True)
    for item in detached_transition.unknown:
        if (
            item.role == 'link'
            and getattr(item.atspi_obj, 'uri', None) == activity_uri(ACTIVITY_B)
        ):
            item.states = []
            item.atspi_obj.states = []
    detached_article = next(
        item.atspi_obj
        for item in detached_transition.unknown
        if item.role == 'article'
    )
    detached_article.parent = None
    expect_value_error(
        lambda: manual.verify_post_action(
            detached_transition,
            candidate['element'],
            'activate',
        ),
        'detached Notifications tree authorized the selected-post transition',
    )
    settled_candidate_receipt = manual.verify_post_action(
        selected_snapshot(),
        candidate['element'],
        'activate',
    )
    require(
        settled_candidate_receipt['activity_exact'] is True
        and settled_candidate_receipt['selected_post_body_sha256'] == BODY_SHA256,
        'settled candidate transition omitted the exact selected activity/body',
    )
    receipts.append(accept_preparation_step(
        candidate,
        barrier(candidate),
        receipts[-1]['receipt_sha256'],
    ))
    candidate_receipts = list(receipts)
    require(
        schema_required('unit1-preparation-receipt.schema.json')
        == set(receipts[-1]),
        'preparation receipt schema drifted',
    )

    for body_index in (8, 9, 12):
        variant = selected_snapshot(body_index=body_index)
        root, body, body_text = manual._selected_post_root_and_body(
            variant,
            manual._manual_notification_contract(),
        )
        require(
            root is not None and body is not None and body_text == BODY,
            f'selected post body variant {body_index} was not mapped exactly',
        )
        comment_counts, _visible_comments = manual._selected_thread_controls(
            variant,
            root,
            manual._manual_notification_contract(),
        )
        require(
            len(comment_counts) == 1 and comment_counts[0].name == '2 comments',
            f'selected thread count variant {body_index + 3} was not mapped exactly',
        )

    overlapping_body = selected_snapshot(body_index=8)
    overlapping_root = next(
        item.atspi_obj
        for item in overlapping_body.unknown
        if item.role == 'list item'
    )
    overlapping_control_section = Node(
        'section',
        text='Controls',
        states=['enabled'],
    )
    overlapping_card = overlapping_root.get_child_at_index(0)
    overlapping_control_wrapper = Node('generic').add(
        overlapping_control_section,
    )
    overlapping_card.add(overlapping_control_wrapper)
    overlapping_body.unknown.extend([
        ref(overlapping_control_wrapper),
        ref(overlapping_control_section, text='Controls'),
    ])
    _overlap_root, _overlap_body, overlap_text = (
        manual._selected_post_root_and_body(
            overlapping_body,
            manual._manual_notification_contract(),
        )
    )
    require(
        overlap_text == BODY,
        'later matching control section displaced first exact body path',
    )

    virtualized = virtualized_selected_snapshot()
    virtualized_augmented = manual.augment_snapshot(virtualized)
    virtualized_selected_key = f'{manual.SELECTED_POST_PREFIX}{ACTIVITY_A}'
    virtualized_thread_key = (
        f'{manual.SELECTED_THREAD_OPEN_PREFIX}{ACTIVITY_A}_body_{BODY_SHA256}'
    )
    require(
        len(virtualized_augmented.mapped.get(virtualized_selected_key) or []) == 1
        and virtualized_augmented.mapped[virtualized_selected_key][0].raw[
            'selected_post_body_sha256'
        ] == BODY_SHA256,
        'virtualized selected root rebound to a later visible post body',
    )
    require(
        len(virtualized_augmented.mapped.get(virtualized_thread_key) or []) == 1
        and virtualized_augmented.mapped[virtualized_thread_key][0].name
        == '2 comments',
        'virtualized selected root lost its exact same-card thread opener',
    )
    original_build_snapshot = manual.build_snapshot
    original_viewport = manual._selected_thread_viewport_state
    manual.build_snapshot = lambda _platform: (None, None, virtualized)
    manual._selected_thread_viewport_state = lambda _raw: {
        'live_extent_in_viewport': True,
    }
    try:
        _virtualized_snapshot, virtualized_barrier = (
            manual.stable_scroll_post_action_observation(
                virtualized_thread_key,
                manual.time.monotonic() + 5,
            )
        )
    finally:
        manual.build_snapshot = original_build_snapshot
        manual._selected_thread_viewport_state = original_viewport
    require(
        virtualized_barrier['result'] == 'PASS'
        and virtualized_barrier['stable_cycles_observed'] == 2
        and all(
            sample['exact_element_key_count'] == 1
            for sample in virtualized_barrier['samples']
        ),
        'virtualized selected root did not retain exact identity for two samples',
    )

    missing_thread = selected_snapshot(visible=False)
    expect_error(
        lambda: compile_preparation_step(
            missing_thread,
            REVISION,
            selected_envelope,
            receipts,
        ),
        'candidate receipt bypassed the mandatory thread opener',
    )
    unopened_thread = with_thread_opener(selected_snapshot(visible=False))
    original_viewport = manual._selected_thread_viewport_state
    manual._selected_thread_viewport_state = lambda _raw: {
        'live_extent_in_viewport': True,
    }
    try:
        thread_card = compile_preparation_step(
            unopened_thread,
            REVISION,
            selected_envelope,
            receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(thread_card['phase'] == 'thread_open', 'mandatory thread was not opened')
    receipts.append(accept_preparation_step(
        thread_card,
        barrier(thread_card),
        receipts[-1]['receipt_sha256'],
    ))
    thread_open_receipts = list(receipts)

    partial_thread = manual.augment_snapshot(with_thread_expander(
        selected_snapshot(count=9, visible_count=2),
        6,
    ))
    original_viewport = manual._selected_thread_viewport_state
    manual._selected_thread_viewport_state = lambda _raw: {
        'error': 'live_extent_outside_display',
    }
    try:
        first_expand_scroll = compile_preparation_step(
            partial_thread,
            REVISION,
            selected_envelope,
            receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(
        first_expand_scroll['phase'] == 'thread_expand_scroll'
        and first_expand_scroll['method'] == 'scroll_into_view'
        and '_total_9_visible_2_more_6' in first_expand_scroll['element'],
        'off-screen selected thread expansion did not compile one exact scroll',
    )
    original_build_snapshot = manual.build_snapshot
    manual.build_snapshot = lambda _platform: (None, None, partial_thread)
    manual._selected_thread_viewport_state = lambda _raw: {
        'live_extent_in_viewport': True,
    }
    try:
        _scroll_snapshot, expand_scroll_barrier = (
            manual.stable_scroll_post_action_observation(
                first_expand_scroll['element'],
                manual.time.monotonic() + 5,
            )
        )
    finally:
        manual.build_snapshot = original_build_snapshot
        manual._selected_thread_viewport_state = original_viewport
    require(
        expand_scroll_barrier['result'] == 'PASS'
        and expand_scroll_barrier['stable_cycles_observed'] == 2
        and expand_scroll_barrier['postcondition_receipt'][
            'expansion_identity_exact'
        ] is True
        and expand_scroll_barrier['postcondition_receipt']['total_count'] == 9
        and expand_scroll_barrier['postcondition_receipt']['visible_count'] == 2
        and expand_scroll_barrier['postcondition_receipt']['more_count'] == 6,
        'selected thread expansion scroll barrier lost exact key identity',
    )
    receipts.append(accept_preparation_step(
        first_expand_scroll,
        expand_scroll_barrier,
        receipts[-1]['receipt_sha256'],
    ))
    manual._selected_thread_viewport_state = lambda _raw: {
        'error': 'live_extent_outside_display',
    }
    try:
        expect_error(
            lambda: compile_preparation_step(
                partial_thread,
                REVISION,
                selected_envelope,
                receipts,
            ),
            'thread expansion scroll repeated while target stayed off-screen',
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    changed_expand_key = manual.augment_snapshot(with_thread_expander(
        selected_snapshot(count=9, visible_count=3),
        6,
    ))
    manual._selected_thread_viewport_state = lambda _raw: {
        'live_extent_in_viewport': True,
    }
    try:
        expect_error(
            lambda: compile_preparation_step(
                changed_expand_key,
                REVISION,
                selected_envelope,
                receipts,
            ),
            'thread expansion target identity changed after scroll',
        )
        expect_error(
            lambda: compile_preparation_step(
                manual.augment_snapshot(
                    selected_snapshot(count=9, visible_count=9)
                ),
                REVISION,
                selected_envelope,
                receipts,
            ),
            'thread expansion scroll receipt bypassed the pointer action',
        )
        first_expand = compile_preparation_step(
            partial_thread,
            REVISION,
            selected_envelope,
            receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(
        first_expand['phase'] == 'thread_expand'
        and first_expand['method'] == 'mapped_pointer_activate'
        and first_expand['element'] == first_expand_scroll['element']
        and '_total_9_visible_2_more_6' in first_expand['element'],
        'scrolled selected thread did not compile the same exact expansion',
    )
    invalid_typed_growth = with_thread_expander(
        selected_snapshot(count=9, visible_count=8),
        1,
    )
    invalid_control = next(
        item
        for item in invalid_typed_growth.unknown
        if item.name.startswith('View more options for Carol North')
    )
    invalid_control.name = 'View more options for Bad\nName’s comment.'
    invalid_control.atspi_obj.name = invalid_control.name
    invalid_typed_growth = manual.augment_snapshot(invalid_typed_growth)
    try:
        manual.verify_post_action(
            invalid_typed_growth,
            first_expand['element'],
            first_expand['verification_operation'],
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            'thread expansion accepted a mounted control that was not a typed row'
        )
    eight_visible = manual.augment_snapshot(with_thread_expander(
        selected_snapshot(count=9, visible_count=8),
        1,
    ))
    first_expand_barrier = barrier(first_expand)
    first_expand_barrier['postcondition_receipt'] = manual.verify_post_action(
        eight_visible,
        first_expand['element'],
        first_expand['verification_operation'],
    )
    partial_live_before = manual.augment_snapshot(with_thread_expander(
        selected_snapshot(count=12, visible_count=2),
        9,
    ))
    partial_live_key = next(
        key
        for key in partial_live_before.mapped
        if key.startswith(manual.SELECTED_THREAD_EXPAND_PREFIX)
    )
    partial_live_after = manual.augment_snapshot(with_thread_expander(
        selected_snapshot(count=12, visible_count=7),
        4,
    ))
    partial_live_receipt = manual.verify_post_action(
        partial_live_after,
        partial_live_key,
        'activate',
    )
    require(
        partial_live_receipt['prior_visible_comment_count'] == 2
        and partial_live_receipt['declared_more_comment_count'] == 9
        and partial_live_receipt['visible_comment_count'] == 7
        and partial_live_receipt['remaining_comment_count'] == 4
        and partial_live_receipt['next_expander_count'] == 1,
        'partial exact thread growth did not preserve the remaining expander',
    )
    try:
        manual.verify_post_action(
            partial_live_before,
            partial_live_key,
            'activate',
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            'unchanged partial thread was accepted as exact growth'
        )
    receipts.append(accept_preparation_step(
        first_expand,
        first_expand_barrier,
        receipts[-1]['receipt_sha256'],
    ))
    manual._selected_thread_viewport_state = lambda _raw: {
        'live_extent_in_viewport': True,
    }
    try:
        second_expand = compile_preparation_step(
            eight_visible,
            REVISION,
            selected_envelope,
            receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(
        second_expand['phase'] == 'thread_expand'
        and '_total_9_visible_8_more_1' in second_expand['element'],
        'remaining selected thread did not compile its exact singular expansion',
    )
    selected = manual.augment_snapshot(
        selected_snapshot(count=9, visible_count=9)
    )
    second_expand_barrier = barrier(second_expand)
    second_expand_barrier['postcondition_receipt'] = manual.verify_post_action(
        selected,
        second_expand['element'],
        second_expand['verification_operation'],
    )
    receipts.append(accept_preparation_step(
        second_expand,
        second_expand_barrier,
        receipts[-1]['receipt_sha256'],
    ))
    ready_draft = compile_preparation_step(
        selected,
        REVISION,
        selected_envelope,
        receipts,
    )
    require(
        ready_draft['state'] == 'ready_for_private_draft',
        'exact selected source did not produce private draft input',
    )
    source = ready_draft['input']['source']
    require(
        source['thread']['exact_comment_count'] == 9
        and len(source['thread']['typed_rows']) == 9
        and source['thread']['typed_rows'][0]['kind'] == 'text'
        and source['thread']['typed_rows'][1]['kind'] == 'media_link_only',
        'expanded selected thread was not captured as exact typed rows',
    )
    require(
        source['thread_open_receipt_sha256']
        == thread_open_receipts[-1]['receipt_sha256']
        and source['thread_ready_receipt_sha256'] == receipts[-1]['receipt_sha256'],
        'expanded selected source lost open-to-ready receipt provenance',
    )

    repost_ready = compile_preparation_step(
        selected_snapshot(count=9, visible_count=9, repost=True),
        REVISION,
        selected_envelope,
        receipts,
    )
    require(
        repost_ready['state'] == 'ready_for_private_draft'
        and repost_ready['input']['source']['thread']['exact_comment_count'] == 9,
        'exact repost structure did not produce private draft input',
    )

    ambiguous_count = selected_snapshot(visible=False)
    ambiguous_root = next(
        item.atspi_obj
        for item in ambiguous_count.unknown
        if item.role == 'list item'
    )
    ambiguous_card = ambiguous_root.get_child_at_index(0)
    ambiguous_card.add(Node('generic'), Node('generic'))
    second_count = Node(
        'push button',
        '2 comments',
        states=['enabled', 'focusable'],
    )
    ambiguous_card.add(second_count)
    ambiguous_count.unknown.append(ref(second_count))
    try:
        manual.augment_snapshot(ambiguous_count)
    except ValueError:
        pass
    else:
        raise AssertionError(
            'two declared comment-count paths authorized a thread opener'
        )

    zero_snapshot = manual.augment_snapshot(
        with_zero_thread_opener(selected_snapshot(count=0))
    )
    original_viewport = manual._selected_thread_viewport_state
    manual._selected_thread_viewport_state = lambda _raw: {
        'live_extent_in_viewport': True,
    }
    try:
        zero_card = compile_preparation_step(
            zero_snapshot,
            REVISION,
            selected_envelope,
            candidate_receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(
        zero_card['phase'] == 'thread_open'
        and zero_card['element'].startswith(
            manual.SELECTED_THREAD_ZERO_OPEN_PREFIX
        ),
        'exact zero thread did not compile its distinct opener',
    )
    compact_zero_source = selected_snapshot(count=0, body_index=8)
    compact_zero_root = next(
        item.atspi_obj
        for item in compact_zero_source.unknown
        if item.role == 'list item'
    )
    compact_zero_card_root = compact_zero_root.get_child_at_index(0)
    reactions_menu = Node(
        'push button',
        'Open reactions menu',
        states=['enabled', 'focusable'],
    )
    displaced_control = compact_zero_card_root.children[11]
    compact_zero_card_root.children[11] = reactions_menu
    reactions_menu.parent = compact_zero_card_root
    compact_zero_source.unknown = [
        item
        for item in compact_zero_source.unknown
        if id(item.atspi_obj) != id(displaced_control)
    ]
    compact_zero_source.unknown.append(ref(reactions_menu))
    compact_zero_snapshot = manual.augment_snapshot(with_zero_thread_opener(
        compact_zero_source,
        compact_variant=True,
    ))
    manual._selected_thread_viewport_state = lambda _raw: {
        'live_extent_in_viewport': True,
    }
    try:
        compact_zero_card = compile_preparation_step(
            compact_zero_snapshot,
            REVISION,
            selected_envelope,
            candidate_receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(
        compact_zero_card['phase'] == 'thread_open'
        and compact_zero_card['element'].startswith(
            manual.SELECTED_THREAD_ZERO_OPEN_PREFIX
        ),
        'compact zero thread did not compile one exact opener',
    )
    document_zero_snapshot = manual.augment_snapshot(with_zero_thread_opener(
        selected_snapshot(count=0, body_index=8),
    ))
    manual._selected_thread_viewport_state = lambda _raw: {
        'live_extent_in_viewport': True,
    }
    try:
        document_zero_card = compile_preparation_step(
            document_zero_snapshot,
            REVISION,
            selected_envelope,
            candidate_receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(
        document_zero_card['phase'] == 'thread_open'
        and document_zero_card['element'].startswith(
            manual.SELECTED_THREAD_ZERO_OPEN_PREFIX
        ),
        'document zero thread did not compile one exact opener',
    )
    media_zero_snapshot = manual.augment_snapshot(with_zero_thread_opener(
        selected_snapshot(count=0, body_index=12),
        media_variant=True,
    ))
    manual._selected_thread_viewport_state = lambda _raw: {
        'error': 'live_extent_outside_display',
    }
    try:
        media_zero_card = compile_preparation_step(
            media_zero_snapshot,
            REVISION,
            selected_envelope,
            candidate_receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(
        media_zero_card['phase'] == 'thread_scroll'
        and media_zero_card['element'].startswith(
            manual.SELECTED_THREAD_ZERO_OPEN_PREFIX
        ),
        'off-screen media zero thread did not compile one exact scroll',
    )
    disabled_expander = manual.augment_snapshot(with_thread_expander(
        with_zero_thread_opener(selected_snapshot(count=0)),
        1,
        states=['showing'],
    ))
    require(
        not any(
            key.startswith(manual.SELECTED_THREAD_ZERO_OPEN_PREFIX)
            for key in disabled_expander.mapped
        ),
        'disabled grammatical expander was misclassified as exact zero',
    )
    zero_after = manual.augment_snapshot(with_empty_comment_editor(
        with_zero_thread_opener(selected_snapshot(count=0))
    ))
    zero_barrier = barrier(zero_card)
    zero_barrier['postcondition_receipt'] = manual.verify_post_action(
        zero_after,
        zero_card['element'],
        zero_card['verification_operation'],
    )
    zero_receipts = [
        *candidate_receipts,
        accept_preparation_step(
            zero_card,
            zero_barrier,
            candidate_receipts[-1]['receipt_sha256'],
        ),
    ]
    zero_ready = compile_preparation_step(
        zero_after,
        REVISION,
        selected_envelope,
        zero_receipts,
    )
    zero_source = zero_ready['input']['source']
    require(
        zero_ready['state'] == 'ready_for_private_draft'
        and zero_source['thread_open_receipt_sha256']
        == zero_receipts[-1]['receipt_sha256']
        and zero_source['thread_ready_receipt_sha256']
        == zero_receipts[-1]['receipt_sha256']
        and zero_source['thread']['exact_comment_count'] == 0
        and zero_source['thread']['typed_rows'] == [],
        'exact zero thread was not represented',
    )
    expect_error(
        lambda: extract_selected_source(
            zero_after,
            REVISION,
            selected_activity=ACTIVITY_A,
            notification_inventory_sha256=artifact['inventory_sha256'],
            selection_sha256=selection['selection_sha256'],
            thread_open_receipt=thread_open_receipts[-1],
            thread_ready_receipt=thread_open_receipts[-1],
            transaction_sha256=transaction_sha256,
        ),
        'positive-count opener receipt authorized an exact zero thread',
    )

    mismatch = selected_snapshot(count=2)
    mismatch.unknown = [
        item
        for item in mismatch.unknown
        if not item.name.startswith('View more options for Bob Example')
    ]
    expect_error(
        lambda: extract_selected_source(
            mismatch,
            REVISION,
            selected_activity=ACTIVITY_A,
            notification_inventory_sha256=artifact['inventory_sha256'],
            selection_sha256=selection['selection_sha256'],
            thread_open_receipt=thread_open_receipts[-1],
            thread_ready_receipt=thread_open_receipts[-1],
            transaction_sha256=transaction_sha256,
        ),
        'thread count mismatch became ready',
    )
    invalid_unsigned = {**selection_unsigned, 'dedup_passed': False}
    invalid_selection = {
        **invalid_unsigned,
        'selection_sha256': canonical_sha256(invalid_unsigned),
    }
    expect_error(
        lambda: compile_preparation_step(
            stream,
            REVISION,
            {**envelope, 'selection': invalid_selection},
            receipts[:1],
        ),
        'nonqualifying private verdict became ready',
    )
    expect_error(
        lambda: preparation_transaction_sha256({
            **selected_envelope,
            'cycle_id': 'different-cycle',
        }),
        'private selection crossed preparation transactions',
    )

    envelope_schema = json.loads((
        REPO_ROOT
        / 'consultation_v2/platforms/linkedin/unit1-preparation-envelope.schema.json'
    ).read_text(encoding='utf-8'))
    require(
        set(envelope_schema['required']) == set(envelope),
        'preparation envelope schema drifted',
    )
    serialized_schemas = json.dumps({
        name: json.loads((
            REPO_ROOT / 'consultation_v2/platforms/linkedin' / name
        ).read_text(encoding='utf-8'))
        for name in (
            'unit1-preparation-envelope.schema.json',
            'unit1-preparation-action-card.schema.json',
            'unit1-preparation-receipt.schema.json',
            'unit1-preparation-result.schema.json',
        )
    }, sort_keys=True)
    require(
        'human_approval' not in serialized_schemas
        and 'review_required' not in serialized_schemas,
        'autonomous preparation schemas acquired a human-review gate',
    )
    require(
        preparation_transaction_sha256(envelope) == transaction_sha256,
        'preparation transaction identity is unstable',
    )

    print('linkedin Unit 1 autonomous preparation boundary: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
