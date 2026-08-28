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
    accept_preparation_step,
    compile_preparation_step,
    extract_selected_source,
    preparation_transaction_sha256,
    project_notification_inventory,
)
from consultation_v2.types import ElementRef, Snapshot  # noqa: E402


REVISION = '1' * 64
POLICY_SHA256 = '2' * 64
ACTIVITY_A = '1234567890123456789'
ACTIVITY_B = '2234567890123456789'
BODY = 'One exact public post body.'
BODY_SHA256 = hashlib.sha256(BODY.encode('utf-8')).hexdigest()


def canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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
        return self if self.role in {'paragraph', 'section'} else None

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
    link = Node(
        'link',
        text,
        states=['enabled', 'focusable'],
        uri=uri,
    )
    age_node = Node('paragraph', text=age)
    article.add(link, age_node)
    return article, [ref(article), ref(link), ref(age_node, text=age)]


def inventory_snapshot(
    *,
    notification_text: str = 'Unread notification. Alice posted an exact update.',
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
    root.add(article_a, article_b, article_c)
    return Snapshot(
        platform='linkedin',
        url='https://www.linkedin.com/notifications/?filter=all',
        unknown=[*refs_a, *refs_b, *refs_c],
    )


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
    control = Node(
        'push button',
        f'View more options for {author}\u2019s comment.',
        states=['visible', 'sensitive'],
    )
    control_parent.add(control)
    root.add(Node('generic'), Node('generic'), child_2, control_parent)
    return root, control, [ref(control), ref(target, text=text)]


def selected_snapshot(*, count: int = 2, visible: bool = True) -> Snapshot:
    document = Node('document web', 'LinkedIn post')
    post_root = Node('list item', states=['showing'])
    post_card = Node('generic')
    heading = Node('heading', 'Feed post')
    body = Node('section', text=BODY, states=['showing'])
    body_wrapper = Node('generic').add(body)
    fillers = [Node('generic') for _index in range(7)]
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
    if visible and count >= 1:
        comment_a, control_a, comment_refs_a = comment_root(
            'Alice Example',
            'First exact comment.',
        )
        post_card.add(comment_a)
        refs.extend([ref(comment_a), *comment_refs_a])
    if visible and count >= 2:
        comment_b, control_b, comment_refs_b = comment_root(
            'Bob Example',
            '',
        )
        post_card.add(comment_b)
        refs.extend([ref(comment_b), *comment_refs_b])
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


def barrier(card: dict) -> dict:
    return {
        'result': 'PASS',
        'next_mutation_authorized': card['phase'] != 'thread_scroll',
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
        'postcondition_receipt': {
            'element_key': card['element'],
            'operation': card['verification_operation'],
            'effect_class': card['effect_class'],
            'postcondition': card['postcondition_kind'],
        },
    }


def expect_error(operation, message: str) -> None:
    try:
        operation()
    except LinkedInUnit1PreparationError:
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


def main() -> int:
    stream = inventory_snapshot()
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
    changed = project_notification_inventory(
        inventory_snapshot(
            notification_text='Unread notification. Alice changed the exact update.'
        ),
        REVISION,
    )
    require(
        changed.artifact['inventory_sha256'] != artifact['inventory_sha256'],
        'inventory digest ignored raw notification text',
    )

    malformed = inventory_snapshot()
    malformed_article = next(
        item for item in malformed.unknown if item.role == 'article'
    )
    malformed_article.atspi_obj.add(Node('link', 'Second direct link'))
    malformed.unknown.append(ref(malformed_article.atspi_obj.children[-1]))
    expect_error(
        lambda: project_notification_inventory(malformed, REVISION),
        'malformed article was silently omitted',
    )
    duplicated = inventory_snapshot()
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
    receipts.append(accept_preparation_step(navigation, barrier(navigation), None))

    route_proof = compile_preparation_step(
        stream,
        REVISION,
        envelope,
        [],
    )
    require(
        route_proof['schema'] == 'linkedin_unit1_preparation_receipt_v1'
        and route_proof['phase'] == 'notifications_navigation'
        and route_proof['method'] == 'observe'
        and route_proof['effect_class'] == 'read_only'
        and route_proof['snapshot_revision'] == REVISION
        and route_proof['previous_receipt_sha256'] is None,
        'fresh exact Notifications route did not become phase proof',
    )
    require(
        schema_required('unit1-preparation-receipt.schema.json')
        == set(route_proof),
        'Notifications route proof did not preserve the receipt schema',
    )
    route_ready_selection = compile_preparation_step(
        stream,
        REVISION,
        envelope,
        [route_proof],
    )
    require(
        route_ready_selection['state'] == 'ready_for_private_selection',
        'Notifications route proof did not require a new compile observation',
    )
    near_route = inventory_snapshot()
    near_route.url = 'https://www.linkedin.com/notifications/?filter=mentions'
    expect_error(
        lambda: compile_preparation_step(near_route, REVISION, envelope, []),
        'non-exact Notifications route became phase proof',
    )

    ready_selection = compile_preparation_step(
        stream,
        REVISION,
        envelope,
        receipts,
    )
    require(
        ready_selection['state'] == 'ready_for_private_selection',
        'complete stream did not produce private selection input',
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
    candidate = compile_preparation_step(
        stream,
        REVISION,
        selected_envelope,
        receipts,
    )
    require(
        candidate['phase'] == 'notification_candidate'
        and candidate['element'].endswith(ACTIVITY_A),
        'exact private selection did not compile to one candidate card',
    )
    receipts.append(accept_preparation_step(
        candidate,
        barrier(candidate),
        receipts[-1]['receipt_sha256'],
    ))
    require(
        schema_required('unit1-preparation-receipt.schema.json')
        == set(receipts[-1]),
        'preparation receipt schema drifted',
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

    selected = selected_snapshot()
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
        source['thread']['exact_comment_count'] == 2
        and len(source['thread']['typed_rows']) == 2
        and source['thread']['typed_rows'][0]['kind'] == 'text'
        and source['thread']['typed_rows'][1]['kind'] == 'media_link_only',
        'selected thread was not captured as exact typed rows',
    )

    zero_snapshot = selected_snapshot(count=0)
    zero_ready = compile_preparation_step(
        zero_snapshot,
        REVISION,
        selected_envelope,
        receipts,
    )
    zero_source = zero_ready['input']['source']
    require(
        zero_ready['state'] == 'ready_for_private_draft'
        and zero_source['thread_open_receipt_sha256']
        == receipts[-1]['receipt_sha256']
        and zero_source['thread']['exact_comment_count'] == 0
        and zero_source['thread']['typed_rows'] == [],
        'exact zero thread was not represented',
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
            thread_open_receipt=receipts[-1],
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
