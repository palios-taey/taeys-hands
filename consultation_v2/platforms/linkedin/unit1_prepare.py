from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from consultation_v2.platforms.linkedin.driver import (
    _all_elements,
    _element_uri,
    _exact_engagement_route,
)
from consultation_v2.platforms.linkedin.manual import (
    NOTIFICATION_CANDIDATE_PREFIX,
    NOTIFICATIONS_CONTINUATION_PREFIX,
    NOTIFICATIONS_NAVIGATION,
    SELECTED_POST_PREFIX,
    SELECTED_THREAD_OPEN_PREFIX,
    _comment_relative_text,
    _direct_children,
    _manual_comment_contract,
    _manual_notification_contract,
    _node_at_index_path,
    _node_role,
    _notification_activity,
    _notification_relative_age,
    _selected_post_root_and_body,
    _selected_thread_controls,
    _structural_index_path,
    element_operation,
)
from consultation_v2.types import ElementRef, Snapshot


PREPARATION_ENVELOPE_SCHEMA = 'linkedin_unit1_preparation_envelope_v1'
PREPARATION_ACTION_CARD_SCHEMA = 'linkedin_unit1_preparation_action_card_v1'
PREPARATION_RECEIPT_SCHEMA = 'linkedin_unit1_preparation_receipt_v1'
PREPARATION_RESULT_SCHEMA = 'linkedin_unit1_preparation_result_v1'
NOTIFICATION_INVENTORY_SCHEMA = 'linkedin_notification_inventory_v1'
SELECTED_SOURCE_SCHEMA = 'linkedin_selected_post_thread_source_v1'

_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_PUBLIC_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
_ACTIVITY = re.compile(r'^[0-9]+$')
_AGE = re.compile(r'^(?P<count>[1-9][0-9]*)(?P<unit>[smhdw])$')
_CONTINUATION = re.compile(
    rf'^{NOTIFICATIONS_CONTINUATION_PREFIX}(?P<count>[0-9]+)_'
    r'(?P<prefix>[0-9a-f]{16})$'
)

_ENVELOPE_KEYS = frozenset({
    'cycle_id',
    'display',
    'operation',
    'policy_sha256',
    'schema',
    'selection',
    'transaction_id',
})
_SELECTION_KEYS = frozenset({
    'author_cooloff_passed',
    'dedup_passed',
    'notification_inventory_sha256',
    'selected_activity',
    'selected_age_seconds',
    'selected_notification_ordinal',
    'selected_notification_text',
    'selected_notification_text_sha256',
    'selection_sha256',
    'target_passed',
    'transaction_sha256',
})
_CARD_KEYS = frozenset({
    'card_sha256',
    'effect_class',
    'element',
    'element_sha256',
    'method',
    'phase',
    'postcondition_kind',
    'schema',
    'sequence',
    'snapshot_revision',
    'transaction_sha256',
    'verification_operation',
})
_RECEIPT_KEYS = frozenset({
    'card_sha256',
    'effect_class',
    'element_sha256',
    'fresh_observation_required',
    'method',
    'next_step_authorized',
    'phase',
    'postcondition_passed',
    'postcondition_sha256',
    'previous_receipt_sha256',
    'receipt_sha256',
    'schema',
    'sequence',
    'snapshot_revision',
    'transaction_sha256',
})

_PHASE_TRANSITIONS = {
    'notifications_navigation': frozenset({
        'notifications_continuation',
        'notification_candidate',
    }),
    'notifications_continuation': frozenset({
        'notifications_continuation',
        'notification_candidate',
    }),
    'notification_candidate': frozenset({'thread_scroll', 'thread_open'}),
    'thread_scroll': frozenset({'thread_open'}),
    'thread_open': frozenset(),
}
_PHASE_METHODS = {
    'notifications_navigation': 'activate',
    'notifications_continuation': 'activate',
    'notification_candidate': 'activate',
    'thread_scroll': 'scroll_into_view',
    'thread_open': 'mapped_pointer_activate',
}


class LinkedInUnit1PreparationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NotificationInventoryProjection:
    artifact: dict[str, Any]
    targets: dict[str, ElementRef]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise LinkedInUnit1PreparationError(
            f'{field} must be one lowercase SHA-256'
        )
    return value


def _require_public_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or _PUBLIC_ID.fullmatch(value) is None:
        raise LinkedInUnit1PreparationError(
            f'{field} must be one public-safe identity'
        )
    return value


def _require_linkedin_snapshot(snapshot: Snapshot) -> None:
    if snapshot.platform != 'linkedin':
        raise LinkedInUnit1PreparationError(
            'Unit 1 preparation requires a LinkedIn snapshot'
        )


def _age_seconds(age: str) -> int:
    match = _AGE.fullmatch(age)
    if match is None:
        raise LinkedInUnit1PreparationError(
            'notification age is not one exact relative-age token'
        )
    multiplier = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}[
        match.group('unit')
    ]
    return int(match.group('count')) * multiplier


def _validate_selection(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or frozenset(value) != _SELECTION_KEYS:
        raise LinkedInUnit1PreparationError(
            'selection fields are incomplete or unknown'
        )
    selection = dict(value)
    for field in (
        'notification_inventory_sha256',
        'selection_sha256',
        'transaction_sha256',
    ):
        _require_sha256(selection[field], field)
    activity = selection['selected_activity']
    if not isinstance(activity, str) or _ACTIVITY.fullmatch(activity) is None:
        raise LinkedInUnit1PreparationError('selected_activity must be numeric')
    ordinal = selection['selected_notification_ordinal']
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise LinkedInUnit1PreparationError(
            'selected_notification_ordinal must be positive'
        )
    notification_text = selection['selected_notification_text']
    if (
        not isinstance(notification_text, str)
        or not notification_text
        or notification_text != notification_text.strip()
        or '\x00' in notification_text
    ):
        raise LinkedInUnit1PreparationError(
            'selected_notification_text is invalid'
        )
    if (
        _require_sha256(
            selection['selected_notification_text_sha256'],
            'selected_notification_text_sha256',
        )
        != _text_sha256(notification_text)
    ):
        raise LinkedInUnit1PreparationError(
            'selected notification text does not match its digest'
        )
    age_seconds = selection['selected_age_seconds']
    if (
        isinstance(age_seconds, bool)
        or not isinstance(age_seconds, int)
        or not 0 <= age_seconds <= 72 * 60 * 60
    ):
        raise LinkedInUnit1PreparationError(
            'selected_age_seconds exceeds the 72-hour boundary'
        )
    for field in (
        'author_cooloff_passed',
        'dedup_passed',
        'target_passed',
    ):
        if selection[field] is not True:
            raise LinkedInUnit1PreparationError(
                f'{field} must be a qualifying private verdict'
            )
    unsigned = {
        key: selection[key]
        for key in sorted(_SELECTION_KEYS - {'selection_sha256'})
    }
    if selection['selection_sha256'] != _sha256(unsigned):
        raise LinkedInUnit1PreparationError(
            'selection_sha256 does not match selection bytes'
        )
    return selection


def validate_preparation_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or frozenset(value) != _ENVELOPE_KEYS:
        raise LinkedInUnit1PreparationError(
            'preparation envelope fields are incomplete or unknown'
        )
    envelope = dict(value)
    if (
        envelope['schema'] != PREPARATION_ENVELOPE_SCHEMA
        or envelope['operation'] != 'comment_from_notifications_prepare'
    ):
        raise LinkedInUnit1PreparationError(
            'preparation envelope schema or operation is invalid'
        )
    _require_public_id(envelope['cycle_id'], 'cycle_id')
    _require_public_id(envelope['transaction_id'], 'transaction_id')
    display = envelope['display']
    if (
        not isinstance(display, str)
        or re.fullmatch(r'^:[1-9][0-9]{0,2}$', display) is None
    ):
        raise LinkedInUnit1PreparationError('display must use the nonzero :N form')
    _require_sha256(envelope['policy_sha256'], 'policy_sha256')
    envelope['selection'] = _validate_selection(envelope['selection'])
    return envelope


def preparation_transaction_sha256(value: Mapping[str, Any]) -> str:
    envelope = validate_preparation_envelope(value)
    bootstrap = {
        key: envelope[key]
        for key in (
            'cycle_id',
            'display',
            'operation',
            'policy_sha256',
            'schema',
            'transaction_id',
        )
    }
    transaction_sha256 = _sha256(bootstrap)
    selection = envelope['selection']
    if (
        selection is not None
        and selection['transaction_sha256'] != transaction_sha256
    ):
        raise LinkedInUnit1PreparationError(
            'private selection does not bind this preparation transaction'
        )
    return transaction_sha256


def _article_content_link(
    article: ElementRef,
    elements_by_identity: Mapping[int, ElementRef],
) -> ElementRef:
    children = _direct_children(article.atspi_obj)
    direct_links = [
        elements_by_identity.get(id(child))
        for child in children
        if _node_role(child) == 'link'
    ]
    if (
        len(direct_links) != 1
        or direct_links[0] is None
        or not children
        or id(children[0]) != id(direct_links[0].atspi_obj)
        or id(_node_at_index_path(article.atspi_obj, [0]))
        != id(direct_links[0].atspi_obj)
    ):
        raise LinkedInUnit1PreparationError(
            'mounted notification article does not expose exactly one '
            'canonical first-child content link'
        )
    return direct_links[0]


def project_notification_inventory(
    snapshot: Snapshot,
    snapshot_revision: str,
) -> NotificationInventoryProjection:
    _require_linkedin_snapshot(snapshot)
    revision = _require_sha256(snapshot_revision, 'snapshot_revision')
    if not _exact_engagement_route(snapshot.url, 'notifications_all'):
        raise LinkedInUnit1PreparationError(
            'notification inventory requires exact Notifications-All'
        )
    contract = _manual_notification_contract()
    elements = _all_elements(snapshot)
    elements_by_identity = {
        id(element.atspi_obj): element
        for element in elements
        if element.atspi_obj is not None
    }
    articles = [
        element
        for element in elements
        if (
            element.role == 'article'
            and element.name in contract['article_names']
        )
    ]
    if not articles:
        raise LinkedInUnit1PreparationError(
            'Notifications-All exposes no mounted notification articles'
        )
    try:
        articles.sort(key=lambda item: _structural_index_path(item.atspi_obj))
    except ValueError as exc:
        raise LinkedInUnit1PreparationError(str(exc)) from exc

    rows: list[dict[str, Any]] = []
    actionable_links: list[dict[str, Any]] = []
    targets: dict[str, ElementRef] = {}
    seen_paths: set[tuple[int, ...]] = set()
    seen_activities: set[str] = set()
    seen_raw_rows: set[tuple[str, str, str, str]] = set()
    required_states = set(contract['candidate']['states_include'])
    for ordinal, article in enumerate(articles, 1):
        try:
            structural_path = _structural_index_path(article.atspi_obj)
        except ValueError as exc:
            raise LinkedInUnit1PreparationError(str(exc)) from exc
        if structural_path in seen_paths:
            raise LinkedInUnit1PreparationError(
                'mounted notification article structural paths are duplicated'
            )
        seen_paths.add(structural_path)
        content_link = _article_content_link(article, elements_by_identity)
        notification_text = content_link.name
        if (
            not isinstance(notification_text, str)
            or not notification_text
            or notification_text != notification_text.strip()
            or '\x00' in notification_text
        ):
            raise LinkedInUnit1PreparationError(
                'mounted notification content link has invalid exact text'
            )
        age = _notification_relative_age(content_link, contract)
        if age is None:
            raise LinkedInUnit1PreparationError(
                'mounted notification article does not expose exactly one exact age'
            )
        age_seconds = _age_seconds(age)
        uri = _element_uri(content_link)
        activity = _notification_activity(uri or '', contract)
        raw_identity = (
            article.name,
            notification_text,
            age,
            uri or '',
        )
        if raw_identity in seen_raw_rows:
            raise LinkedInUnit1PreparationError(
                'mounted notification raw rows are duplicated'
            )
        seen_raw_rows.add(raw_identity)
        actionable = (
            activity is not None
            and content_link.role == contract['candidate']['role']
            and notification_text.startswith(
                contract['candidate']['name_prefix']
            )
            and required_states.issubset(content_link.states)
        )
        row = {
            'activity': activity,
            'actionable': actionable,
            'age_seconds': age_seconds,
            'age_token': age,
            'article_name': article.name,
            'article_states': list(article.states),
            'notification_text': notification_text,
            'notification_text_sha256': _text_sha256(notification_text),
            'ordinal': ordinal,
            'snapshot_revision': revision,
            'structural_path': list(structural_path),
        }
        rows.append(row)
        if not actionable:
            continue
        if activity is None:
            raise LinkedInUnit1PreparationError(
                'actionable notification has no exact activity identity'
            )
        if activity in seen_activities:
            raise LinkedInUnit1PreparationError(
                'mounted notification activity identities are duplicated'
            )
        seen_activities.add(activity)
        key = (
            f'{NOTIFICATION_CANDIDATE_PREFIX}{ordinal:03d}_activity_{activity}'
        )
        element_sha256 = _text_sha256(key)
        actionable_links.append({
            'activity': activity,
            'age_seconds': age_seconds,
            'element': key,
            'element_sha256': element_sha256,
            'ordinal': ordinal,
            'uri': uri,
            'uri_sha256': _text_sha256(uri or ''),
        })
        targets[key] = replace(
            content_link,
            key=key,
            raw={
                **dict(content_link.raw or {}),
                'notification_activity': activity,
                'notification_age': age,
                'notification_ordinal': ordinal,
            },
        )
    artifact = {
        'schema': NOTIFICATION_INVENTORY_SCHEMA,
        'platform': 'linkedin',
        'route': 'notifications_all',
        'snapshot_revision': revision,
        'mounted_article_count': len(rows),
        'rows': rows,
        'actionable_links': actionable_links,
    }
    artifact['inventory_sha256'] = _sha256(artifact)
    return NotificationInventoryProjection(artifact=artifact, targets=targets)


def _comment_count(name: str) -> int:
    if name == '1 comment':
        return 1
    if name.endswith(' comments'):
        token = name.removesuffix(' comments').replace(',', '')
        if token.isdigit() and int(token) > 0:
            return int(token)
    raise LinkedInUnit1PreparationError(
        'selected thread has no exact positive comment count'
    )


def _comment_author(name: str, contract: Mapping[str, Any]) -> str:
    prefix = contract['control_name_prefix']
    suffix = contract['control_name_suffix']
    if not name.startswith(prefix) or not name.endswith(suffix):
        raise LinkedInUnit1PreparationError(
            'selected thread comment control name is not exact'
        )
    author = name[len(prefix):-len(suffix)]
    if (
        not author
        or author != author.strip()
        or len(author) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in author)
    ):
        raise LinkedInUnit1PreparationError(
            'selected thread comment author is invalid'
        )
    return author


def extract_selected_source(
    snapshot: Snapshot,
    snapshot_revision: str,
    *,
    selected_activity: str,
    notification_inventory_sha256: str,
    selection_sha256: str,
    thread_open_receipt: Mapping[str, Any],
    transaction_sha256: str,
) -> dict[str, Any]:
    _require_linkedin_snapshot(snapshot)
    revision = _require_sha256(snapshot_revision, 'snapshot_revision')
    _require_sha256(
        notification_inventory_sha256,
        'notification_inventory_sha256',
    )
    _require_sha256(selection_sha256, 'selection_sha256')
    _require_sha256(transaction_sha256, 'transaction_sha256')
    thread_receipt_payload = _receipt_payload(thread_open_receipt)
    if (
        thread_receipt_payload.get('schema') != PREPARATION_RECEIPT_SCHEMA
        or thread_receipt_payload.get('transaction_sha256')
        != transaction_sha256
        or thread_receipt_payload.get('phase') != 'thread_open'
        or thread_receipt_payload.get('postcondition_passed') is not True
        or thread_receipt_payload.get('fresh_observation_required') is not True
        or thread_receipt_payload.get('next_step_authorized') is not True
    ):
        raise LinkedInUnit1PreparationError(
            'selected source requires an exact thread-open receipt'
        )
    thread_open_receipt_sha256 = str(thread_open_receipt['receipt_sha256'])
    if not isinstance(selected_activity, str) or _ACTIVITY.fullmatch(
        selected_activity
    ) is None:
        raise LinkedInUnit1PreparationError('selected_activity must be numeric')
    selected_key = f'{SELECTED_POST_PREFIX}{selected_activity}'
    selected = list(snapshot.mapped.get(selected_key) or [])
    if len(selected) != 1:
        raise LinkedInUnit1PreparationError(
            'selected activity does not expose one canonical selected-post element'
        )
    selected_raw = dict(selected[0].raw or {})
    notification_contract = _manual_notification_contract()
    root, body, body_text = _selected_post_root_and_body(
        snapshot,
        notification_contract,
    )
    if root is None or body is None or body_text is None:
        raise LinkedInUnit1PreparationError(
            'selected activity lacks one exact post/body source'
        )
    body_sha256 = _text_sha256(body_text)
    if (
        selected_raw.get('selected_activity') != selected_activity
        or selected_raw.get('selected_post_body_sha256') != body_sha256
        or (selected[0].text or body_text) != body_text
    ):
        raise LinkedInUnit1PreparationError(
            'selected-post mapping does not match the exact source body'
        )

    count_controls, visible_controls = _selected_thread_controls(
        snapshot,
        root,
        notification_contract,
    )
    if len(count_controls) > 1:
        raise LinkedInUnit1PreparationError(
            'selected thread comment count is ambiguous'
        )
    try:
        visible_controls.sort(
            key=lambda item: _structural_index_path(item.atspi_obj)
        )
    except ValueError as exc:
        raise LinkedInUnit1PreparationError(str(exc)) from exc
    count_contract = notification_contract['selected_thread']['comment_count']
    count_node = _node_at_index_path(
        root.atspi_obj,
        count_contract['index_path'],
    )
    count_elements = {
        id(element.atspi_obj): element
        for element in _all_elements(snapshot)
        if element.atspi_obj is not None
    }
    count_element = count_elements.get(id(count_node))
    expected_count = _comment_count(count_controls[0].name) if count_controls else 0
    if (
        not count_controls
        and count_element is not None
        and (
            count_element.role == count_contract['role']
            or 'comment' in count_element.name.lower()
        )
    ):
        raise LinkedInUnit1PreparationError(
            'selected thread zero state is not exact'
        )
    if expected_count != len(visible_controls):
        raise LinkedInUnit1PreparationError(
            'selected thread count does not equal the typed visible row count'
        )
    comment_contract = _manual_comment_contract()['own_comment']
    rows: list[dict[str, Any]] = []
    for ordinal, control in enumerate(visible_controls, 1):
        author = _comment_author(control.name, comment_contract)
        try:
            text = _comment_relative_text(
                control.atspi_obj,
                comment_contract['relative_text'],
            )
        except ValueError as exc:
            raise LinkedInUnit1PreparationError(str(exc)) from exc
        if '\x00' in text:
            raise LinkedInUnit1PreparationError(
                'selected thread comment text contains NUL'
            )
        rows.append({
            'author_name': author,
            'kind': 'text' if text else 'media_link_only',
            'ordinal': ordinal,
            'text': text,
            'text_sha256': _text_sha256(text),
        })
    source = {
        'schema': SELECTED_SOURCE_SCHEMA,
        'platform': 'linkedin',
        'selected_activity': selected_activity,
        'snapshot_revision': revision,
        'notification_inventory_sha256': notification_inventory_sha256,
        'selection_sha256': selection_sha256,
        'thread_open_receipt_sha256': thread_open_receipt_sha256,
        'transaction_sha256': transaction_sha256,
        'post': {
            'body': body_text,
            'body_sha256': body_sha256,
        },
        'thread': {
            'exact_comment_count': expected_count,
            'read_complete': True,
            'typed_rows': rows,
        },
    }
    source['source_sha256'] = _sha256(source)
    return source


def _receipt_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, Mapping) or frozenset(receipt) != _RECEIPT_KEYS:
        raise LinkedInUnit1PreparationError(
            'preparation receipt fields are incomplete or unknown'
        )
    payload = dict(receipt)
    digest = payload.pop('receipt_sha256', None)
    if _require_sha256(digest, 'receipt_sha256') != _sha256(payload):
        raise LinkedInUnit1PreparationError(
            'preparation receipt_sha256 does not match receipt bytes'
        )
    return payload


def verify_preparation_receipts(
    receipts: Sequence[Mapping[str, Any]],
    transaction_sha256: str,
) -> str | None:
    _require_sha256(transaction_sha256, 'transaction_sha256')
    previous_digest: str | None = None
    previous_phase: str | None = None
    for sequence, receipt in enumerate(receipts, 1):
        payload = _receipt_payload(receipt)
        if (
            payload.get('schema') != PREPARATION_RECEIPT_SCHEMA
            or payload.get('transaction_sha256') != transaction_sha256
            or payload.get('sequence') != sequence
            or payload.get('previous_receipt_sha256') != previous_digest
            or payload.get('postcondition_passed') is not True
            or payload.get('fresh_observation_required') is not True
            or payload.get('next_step_authorized') is not True
        ):
            raise LinkedInUnit1PreparationError(
                'preparation receipt identity or authority is invalid'
            )
        phase = payload.get('phase')
        if phase not in _PHASE_TRANSITIONS:
            raise LinkedInUnit1PreparationError(
                'preparation receipt phase is unknown'
            )
        if previous_phase is None and phase != 'notifications_navigation':
            raise LinkedInUnit1PreparationError(
                'Unit 1 preparation must begin from Notifications navigation'
            )
        if (
            previous_phase is not None
            and phase not in _PHASE_TRANSITIONS[previous_phase]
        ):
            raise LinkedInUnit1PreparationError(
                'preparation receipt phase order violates Unit 1'
            )
        previous_phase = str(phase)
        previous_digest = str(receipt['receipt_sha256'])
    return previous_phase


def _mapped_singleton(snapshot: Snapshot, element_key: str) -> ElementRef:
    matches = list(snapshot.mapped.get(element_key) or [])
    if len(matches) != 1:
        raise LinkedInUnit1PreparationError(
            f'{element_key} matched {len(matches)} elements; expected exactly one'
        )
    return matches[0]


def _preparation_card(
    *,
    snapshot: Snapshot,
    snapshot_revision: str,
    transaction_sha256: str,
    sequence: int,
    phase: str,
    element_key: str,
    target: ElementRef | None = None,
) -> dict[str, Any]:
    exact_target = target or _mapped_singleton(snapshot, element_key)
    try:
        declared = element_operation(
            element_key,
            list(exact_target.states),
            dict(exact_target.raw or {}),
        )
    except ValueError as exc:
        raise LinkedInUnit1PreparationError(str(exc)) from exc
    if not isinstance(declared, dict):
        raise LinkedInUnit1PreparationError(
            f'{element_key} has no LinkedIn YAML operation'
        )
    method = declared.get('method')
    if (
        declared.get('primitives') != [method]
        or declared.get('allowed_now') != [method]
        or method != _PHASE_METHODS.get(phase)
    ):
        raise LinkedInUnit1PreparationError(
            f'{element_key} is not ready for the exact preparation mutation'
        )
    postcondition = declared.get('postcondition')
    if (
        not isinstance(postcondition, Mapping)
        or not isinstance(postcondition.get('kind'), str)
    ):
        raise LinkedInUnit1PreparationError(
            f'{element_key} has no exact postcondition'
        )
    card = {
        'schema': PREPARATION_ACTION_CARD_SCHEMA,
        'transaction_sha256': transaction_sha256,
        'sequence': sequence,
        'phase': phase,
        'snapshot_revision': _require_sha256(
            snapshot_revision,
            'snapshot_revision',
        ),
        'element': element_key,
        'element_sha256': _text_sha256(element_key),
        'method': method,
        'verification_operation': (
            'activate'
            if method in {'activate', 'mapped_pointer_activate'}
            else method
        ),
        'effect_class': declared.get('effect_class'),
        'postcondition_kind': (
            'notifications_all'
            if element_key == NOTIFICATIONS_NAVIGATION
            else postcondition['kind']
        ),
    }
    card['card_sha256'] = _sha256(card)
    return card


def _preparation_result(
    *,
    state: str,
    transaction_sha256: str,
    previous_receipt_sha256: str | None,
    snapshot_revision: str,
    input_payload: Mapping[str, Any],
) -> dict[str, Any]:
    input_value = dict(input_payload)
    result = {
        'schema': PREPARATION_RESULT_SCHEMA,
        'state': state,
        'transaction_sha256': transaction_sha256,
        'previous_receipt_sha256': previous_receipt_sha256,
        'snapshot_revision': _require_sha256(
            snapshot_revision,
            'snapshot_revision',
        ),
        'input': input_value,
        'input_sha256': _sha256(input_value),
    }
    result['result_sha256'] = _sha256(result)
    return result


def compile_preparation_step(
    snapshot: Snapshot,
    snapshot_revision: str,
    envelope: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    _require_linkedin_snapshot(snapshot)
    frozen = validate_preparation_envelope(envelope)
    transaction_sha256 = preparation_transaction_sha256(frozen)
    previous_phase = verify_preparation_receipts(receipts, transaction_sha256)
    previous_receipt_sha256 = (
        str(receipts[-1]['receipt_sha256']) if receipts else None
    )
    sequence = len(receipts) + 1
    if previous_phase is None:
        return _preparation_card(
            snapshot=snapshot,
            snapshot_revision=snapshot_revision,
            transaction_sha256=transaction_sha256,
            sequence=sequence,
            phase='notifications_navigation',
            element_key=NOTIFICATIONS_NAVIGATION,
        )

    if previous_phase in {
        'notifications_navigation',
        'notifications_continuation',
    }:
        if not _exact_engagement_route(snapshot.url, 'notifications_all'):
            raise LinkedInUnit1PreparationError(
                'notification preparation requires exact Notifications-All'
            )
        continuation_keys = [
            key
            for key, matches in snapshot.mapped.items()
            if _CONTINUATION.fullmatch(key) is not None and matches
        ]
        if len(continuation_keys) > 1:
            raise LinkedInUnit1PreparationError(
                'Notifications continuation is ambiguous'
            )
        if continuation_keys:
            return _preparation_card(
                snapshot=snapshot,
                snapshot_revision=snapshot_revision,
                transaction_sha256=transaction_sha256,
                sequence=sequence,
                phase='notifications_continuation',
                element_key=continuation_keys[0],
            )
        inventory = project_notification_inventory(snapshot, snapshot_revision)
        selection = frozen['selection']
        if selection is None:
            return _preparation_result(
                state='ready_for_private_selection',
                transaction_sha256=transaction_sha256,
                previous_receipt_sha256=previous_receipt_sha256,
                snapshot_revision=snapshot_revision,
                input_payload={
                    'schema': 'linkedin_unit1_private_selection_input_v1',
                    'policy_sha256': frozen['policy_sha256'],
                    'transaction_sha256': transaction_sha256,
                    'notification_inventory': inventory.artifact,
                },
            )
        if (
            selection['notification_inventory_sha256']
            != inventory.artifact['inventory_sha256']
        ):
            raise LinkedInUnit1PreparationError(
                'private selection does not bind the current exact inventory'
            )
        activity = selection['selected_activity']
        actionable = next(
            (
                item
                for item in inventory.artifact['actionable_links']
                if item['activity'] == activity
            ),
            None,
        )
        if actionable is None:
            raise LinkedInUnit1PreparationError(
                'private selection is not one exact actionable inventory link'
            )
        if actionable['age_seconds'] != selection['selected_age_seconds']:
            raise LinkedInUnit1PreparationError(
                'private selection age does not match the exact inventory row'
            )
        selected_row = inventory.artifact['rows'][actionable['ordinal'] - 1]
        if (
            selected_row['ordinal'] != selection['selected_notification_ordinal']
            or selected_row['notification_text']
            != selection['selected_notification_text']
            or selected_row['notification_text_sha256']
            != selection['selected_notification_text_sha256']
        ):
            raise LinkedInUnit1PreparationError(
                'private selection does not bind the exact notification row'
            )
        element_key = actionable['element']
        return _preparation_card(
            snapshot=snapshot,
            snapshot_revision=snapshot_revision,
            transaction_sha256=transaction_sha256,
            sequence=sequence,
            phase='notification_candidate',
            element_key=element_key,
            target=inventory.targets[element_key],
        )

    selection = frozen['selection']
    if selection is None:
        raise LinkedInUnit1PreparationError(
            'selected-post preparation requires a frozen private selection'
        )
    activity = selection['selected_activity']
    selected_key = f'{SELECTED_POST_PREFIX}{activity}'
    selected = _mapped_singleton(snapshot, selected_key)
    body_sha256 = dict(selected.raw or {}).get('selected_post_body_sha256')
    _require_sha256(body_sha256, 'selected_post_body_sha256')

    if previous_phase in {'notification_candidate', 'thread_scroll'}:
        thread_key = f'{SELECTED_THREAD_OPEN_PREFIX}{activity}_body_{body_sha256}'
        matches = list(snapshot.mapped.get(thread_key) or [])
        if not matches:
            raise LinkedInUnit1PreparationError(
                'selected activity lacks one exact mandatory thread opener'
            )
        target = _mapped_singleton(snapshot, thread_key)
        try:
            declared = element_operation(
                thread_key,
                list(target.states),
                dict(target.raw or {}),
            )
        except ValueError as exc:
            raise LinkedInUnit1PreparationError(str(exc)) from exc
        if not isinstance(declared, Mapping):
            raise LinkedInUnit1PreparationError(
                'selected thread opener has no declared operation'
            )
        phase = (
            'thread_scroll'
            if declared.get('method') == 'scroll_into_view'
            else 'thread_open'
        )
        if previous_phase == 'thread_scroll' and phase != 'thread_open':
            raise LinkedInUnit1PreparationError(
                'thread opener is still outside the verified viewport'
            )
        return _preparation_card(
            snapshot=snapshot,
            snapshot_revision=snapshot_revision,
            transaction_sha256=transaction_sha256,
            sequence=sequence,
            phase=phase,
            element_key=thread_key,
        )

    if previous_phase != 'thread_open':
        raise LinkedInUnit1PreparationError(
            'preparation receipt history cannot produce draft input'
        )
    source = extract_selected_source(
        snapshot,
        snapshot_revision,
        selected_activity=activity,
        notification_inventory_sha256=selection[
            'notification_inventory_sha256'
        ],
        selection_sha256=selection['selection_sha256'],
        thread_open_receipt=receipts[-1],
        transaction_sha256=transaction_sha256,
    )
    selected_notification = {
        'activity': activity,
        'age_seconds': selection['selected_age_seconds'],
        'inventory_sha256': selection['notification_inventory_sha256'],
        'notification_text': selection['selected_notification_text'],
        'notification_text_sha256': selection[
            'selected_notification_text_sha256'
        ],
        'ordinal': selection['selected_notification_ordinal'],
    }
    return _preparation_result(
        state='ready_for_private_draft',
        transaction_sha256=transaction_sha256,
        previous_receipt_sha256=previous_receipt_sha256,
        snapshot_revision=snapshot_revision,
        input_payload={
            'schema': 'linkedin_unit1_private_draft_input_v1',
            'policy_sha256': frozen['policy_sha256'],
            'transaction_sha256': transaction_sha256,
            'selection_sha256': selection['selection_sha256'],
            'selected_notification': selected_notification,
            'source': source,
        },
    )


def accept_preparation_step(
    card: Mapping[str, Any],
    barrier: Mapping[str, Any],
    previous_receipt_sha256: str | None,
) -> dict[str, Any]:
    if not isinstance(card, Mapping) or frozenset(card) != _CARD_KEYS:
        raise LinkedInUnit1PreparationError(
            'preparation action card fields are incomplete or unknown'
        )
    card_value = dict(card)
    card_digest = card_value.pop('card_sha256', None)
    if _require_sha256(card_digest, 'card_sha256') != _sha256(card_value):
        raise LinkedInUnit1PreparationError(
            'preparation card_sha256 does not match card bytes'
        )
    if previous_receipt_sha256 is not None:
        _require_sha256(previous_receipt_sha256, 'previous_receipt_sha256')
    expected_barrier_keys = frozenset({
        'next_mutation_authorized',
        'observe_required_before_next_mutation',
        'postcondition_receipt',
        'result',
        'terminal_delivery_verified',
    })
    if (
        not isinstance(barrier, Mapping)
        or not expected_barrier_keys.issubset(barrier)
        or barrier.get('result') != 'PASS'
        or barrier.get('next_mutation_authorized') is not True
        or barrier.get('terminal_delivery_verified') is not False
        or barrier.get('observe_required_before_next_mutation') is not True
    ):
        raise LinkedInUnit1PreparationError(
            'preparation post-action barrier did not authorize one next step'
        )
    postcondition = barrier.get('postcondition_receipt')
    if not isinstance(postcondition, Mapping):
        raise LinkedInUnit1PreparationError(
            'preparation barrier has no exact postcondition receipt'
        )
    expected = {
        'effect_class': card['effect_class'],
        'element_key': card['element'],
        'operation': card['verification_operation'],
        'postcondition': card['postcondition_kind'],
    }
    if not all(postcondition.get(key) == value for key, value in expected.items()):
        raise LinkedInUnit1PreparationError(
            'preparation barrier does not match the exact action card'
        )
    receipt = {
        'schema': PREPARATION_RECEIPT_SCHEMA,
        'transaction_sha256': card['transaction_sha256'],
        'sequence': card['sequence'],
        'phase': card['phase'],
        'previous_receipt_sha256': previous_receipt_sha256,
        'card_sha256': card_digest,
        'snapshot_revision': card['snapshot_revision'],
        'element_sha256': card['element_sha256'],
        'method': card['method'],
        'effect_class': card['effect_class'],
        'postcondition_sha256': _sha256(dict(postcondition)),
        'postcondition_passed': True,
        'fresh_observation_required': True,
        'next_step_authorized': True,
    }
    receipt['receipt_sha256'] = _sha256(receipt)
    return receipt
