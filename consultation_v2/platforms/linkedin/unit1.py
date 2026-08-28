from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from consultation_v2.platforms.linkedin.manual import (
    NOTIFICATION_CANDIDATE_PREFIX,
    NOTIFICATIONS_CONTINUATION,
    NOTIFICATIONS_NAVIGATION,
    SELECTED_POST_EDITOR_PREFIX,
    SELECTED_POST_REACTION_PREFIX,
    SELECTED_POST_SUBMIT_PREFIX,
    SELECTED_POST_PREFIX,
    SELECTED_THREAD_OPEN_PREFIX,
    element_operation,
)
from consultation_v2.platforms.linkedin.driver import _exact_engagement_route
from consultation_v2.types import ElementRef, Snapshot


PRIVATE_INPUT_SCHEMA = 'linkedin_unit1_private_input_v1'
ACTION_CARD_SCHEMA = 'linkedin_unit1_action_card_v1'
STEP_RECEIPT_SCHEMA = 'linkedin_unit1_step_receipt_v1'

_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_PUBLIC_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
_ACTIVITY = re.compile(r'^[0-9]+$')
_CANDIDATE = re.compile(
    rf'^{NOTIFICATION_CANDIDATE_PREFIX}(?P<ordinal>[0-9]{{3}})_activity_'
    r'(?P<activity>[0-9]+)$'
)
_CONTINUATION = re.compile(
    rf'^{re.escape(NOTIFICATIONS_CONTINUATION)}$'
)
_SUBMIT = re.compile(
    rf'^{SELECTED_POST_SUBMIT_PREFIX}(?P<activity>[0-9]+)_body_'
    r'(?P<body>[0-9a-f]{64})_draft_(?P<draft>[0-9a-f]{64})$'
)
_AGE = re.compile(r'^(?P<count>[1-9][0-9]*)(?P<unit>[smhdw])$')

_PRIVATE_KEYS = frozenset({
    'author_cooloff_passed',
    'cycle_id',
    'dedup_passed',
    'display',
    'expected_author_name',
    'freshness_max_hours',
    'like_authorized',
    'notification_stream_sha256',
    'operation',
    'policy_sha256',
    'schema',
    'selected_activity',
    'selected_age_seconds',
    'selected_post_body_sha256',
    'target_passed',
    'text',
    'text_sha256',
    'thread_evidence_sha256',
    'transaction_id',
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
    'terminal_delivery_verified',
    'transaction_sha256',
})

_PHASE_TRANSITIONS = {
    'notifications_navigation': frozenset({'notifications_continuation', 'notification_candidate'}),
    'notifications_continuation': frozenset({'notifications_continuation', 'notification_candidate'}),
    'notification_candidate': frozenset({'thread_scroll', 'thread_open'}),
    'thread_scroll': frozenset({'thread_open'}),
    'thread_open': frozenset({'optional_like', 'comment_paste'}),
    'optional_like': frozenset({'comment_paste'}),
    'comment_paste': frozenset({'comment_submit'}),
    'comment_submit': frozenset(),
}
_PHASE_METHODS = {
    'notifications_navigation': 'activate',
    'notifications_continuation': 'activate',
    'notification_candidate': 'activate',
    'thread_scroll': 'scroll_into_view',
    'thread_open': 'mapped_pointer_activate',
    'optional_like': 'activate_optional_like',
    'comment_paste': 'paste_frozen_text',
    'comment_submit': 'submit_frozen_comment',
}


class LinkedInUnit1Error(ValueError):
    pass


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


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise LinkedInUnit1Error(f'{field} must be one lowercase SHA-256')
    return value


def _require_public_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or _PUBLIC_ID.fullmatch(value) is None:
        raise LinkedInUnit1Error(f'{field} must be one public-safe identity')
    return value


def validate_private_input(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or frozenset(value) != _PRIVATE_KEYS:
        raise LinkedInUnit1Error('private input fields are incomplete or unknown')
    private = dict(value)
    if (
        private['schema'] != PRIVATE_INPUT_SCHEMA
        or private['operation'] != 'comment_from_notifications'
    ):
        raise LinkedInUnit1Error('private input schema or operation is invalid')
    _require_public_id(private['cycle_id'], 'cycle_id')
    _require_public_id(private['transaction_id'], 'transaction_id')
    display = private['display']
    if not isinstance(display, str) or re.fullmatch(r'^:[1-9][0-9]{0,2}$', display) is None:
        raise LinkedInUnit1Error('display must use the nonzero :N form')
    activity = private['selected_activity']
    if not isinstance(activity, str) or _ACTIVITY.fullmatch(activity) is None:
        raise LinkedInUnit1Error('selected_activity must be numeric')
    for field in (
        'notification_stream_sha256',
        'policy_sha256',
        'selected_post_body_sha256',
        'text_sha256',
        'thread_evidence_sha256',
    ):
        _require_sha256(private[field], field)
    if private['freshness_max_hours'] != 72:
        raise LinkedInUnit1Error('freshness_max_hours must remain exactly 72')
    age_seconds = private['selected_age_seconds']
    if (
        isinstance(age_seconds, bool)
        or not isinstance(age_seconds, int)
        or not 0 <= age_seconds <= 72 * 60 * 60
    ):
        raise LinkedInUnit1Error('selected_age_seconds exceeds the 72-hour boundary')
    for field in (
        'author_cooloff_passed',
        'dedup_passed',
        'target_passed',
    ):
        if private[field] is not True:
            raise LinkedInUnit1Error(f'{field} must be a frozen qualifying verdict')
    if not isinstance(private['like_authorized'], bool):
        raise LinkedInUnit1Error('like_authorized must be boolean')
    text = private['text']
    if not isinstance(text, str) or not text or len(text) > 1800 or '\x00' in text:
        raise LinkedInUnit1Error('text must contain 1-1800 non-NUL characters')
    if hashlib.sha256(text.encode('utf-8')).hexdigest() != private['text_sha256']:
        raise LinkedInUnit1Error('text does not match text_sha256')
    author = private['expected_author_name']
    if (
        not isinstance(author, str)
        or not author
        or author != author.strip()
        or len(author) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in author)
    ):
        raise LinkedInUnit1Error('expected_author_name is invalid')
    return private


def private_input_sha256(value: Mapping[str, Any]) -> str:
    return _sha256(validate_private_input(value))


def _receipt_payload(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, Mapping) or frozenset(receipt) != _RECEIPT_KEYS:
        raise LinkedInUnit1Error('receipt fields are incomplete or unknown')
    payload = dict(receipt)
    digest = payload.pop('receipt_sha256', None)
    if _require_sha256(digest, 'receipt_sha256') != _sha256(payload):
        raise LinkedInUnit1Error('receipt_sha256 does not match receipt bytes')
    return payload


def verify_receipt_chain(
    receipts: Sequence[Mapping[str, Any]],
    transaction_sha256: str,
) -> str | None:
    _require_sha256(transaction_sha256, 'transaction_sha256')
    previous_digest: str | None = None
    previous_phase: str | None = None
    for sequence, receipt in enumerate(receipts, 1):
        payload = _receipt_payload(receipt)
        terminal = payload.get('phase') == 'comment_submit'
        if (
            payload.get('schema') != STEP_RECEIPT_SCHEMA
            or payload.get('transaction_sha256') != transaction_sha256
            or payload.get('sequence') != sequence
            or payload.get('previous_receipt_sha256') != previous_digest
            or payload.get('postcondition_passed') is not True
            or not isinstance(payload.get('fresh_observation_required'), bool)
            or payload.get('fresh_observation_required') != (not terminal)
            or not isinstance(payload.get('next_step_authorized'), bool)
        ):
            raise LinkedInUnit1Error('receipt chain identity or postcondition is invalid')
        phase = payload.get('phase')
        if phase not in _PHASE_TRANSITIONS:
            raise LinkedInUnit1Error('receipt phase is unknown')
        if previous_phase is None and phase != 'notifications_navigation':
            raise LinkedInUnit1Error('Unit 1 must begin from Notifications navigation')
        if previous_phase is not None and phase not in _PHASE_TRANSITIONS[previous_phase]:
            raise LinkedInUnit1Error('receipt phase order violates Unit 1')
        if (
            payload.get('terminal_delivery_verified') is not terminal
            or payload.get('next_step_authorized') is terminal
        ):
            raise LinkedInUnit1Error('receipt terminal authority is invalid')
        previous_phase = str(phase)
        previous_digest = str(receipt['receipt_sha256'])
    return previous_phase


def notification_stream_sha256(snapshot: Snapshot) -> str:
    rows: list[tuple[int, str]] = []
    for key, matches in snapshot.mapped.items():
        match = _CANDIDATE.fullmatch(key)
        if match is None:
            continue
        if len(matches) != 1:
            raise LinkedInUnit1Error(f'{key} is not a singleton mapped candidate')
        ordinal = int(match.group('ordinal'))
        activity = match.group('activity')
        raw = dict(matches[0].raw or {})
        if (
            raw.get('notification_ordinal') != ordinal
            or raw.get('notification_activity') != activity
        ):
            raise LinkedInUnit1Error(f'{key} does not match its mapped candidate identity')
        rows.append((ordinal, activity))
    rows.sort()
    if not rows or [ordinal for ordinal, _activity in rows] != list(range(1, len(rows) + 1)):
        raise LinkedInUnit1Error('notification candidate order is incomplete')
    activities = [activity for _ordinal, activity in rows]
    if len(activities) != len(set(activities)):
        raise LinkedInUnit1Error('notification activities are duplicated')
    return hashlib.sha256('\n'.join(activities).encode('ascii')).hexdigest()


def _mapped_singleton(snapshot: Snapshot, element_key: str) -> ElementRef:
    matches = list(snapshot.mapped.get(element_key) or [])
    if len(matches) != 1:
        raise LinkedInUnit1Error(
            f'{element_key} matched {len(matches)} elements; expected exactly one'
        )
    return matches[0]


def _declared_card(
    *,
    snapshot: Snapshot,
    snapshot_revision: str,
    transaction_sha256: str,
    sequence: int,
    phase: str,
    element_key: str,
) -> dict[str, Any]:
    target = _mapped_singleton(snapshot, element_key)
    try:
        declared = element_operation(
            element_key,
            list(target.states),
            dict(target.raw or {}),
        )
    except ValueError as exc:
        raise LinkedInUnit1Error(str(exc)) from exc
    if not isinstance(declared, dict):
        raise LinkedInUnit1Error(f'{element_key} has no LinkedIn YAML operation')
    method = declared.get('method')
    if declared.get('primitives') != [method] or declared.get('allowed_now') != [method]:
        raise LinkedInUnit1Error(f'{element_key} is not ready for one exact mutation')
    if method != _PHASE_METHODS.get(phase):
        raise LinkedInUnit1Error(f'{element_key} does not match the Unit 1 phase')
    postcondition = declared.get('postcondition')
    if not isinstance(postcondition, dict) or not isinstance(postcondition.get('kind'), str):
        raise LinkedInUnit1Error(f'{element_key} has no exact postcondition')
    verification_operation = (
        'activate'
        if method in {'activate', 'mapped_pointer_activate'}
        else method
    )
    card = {
        'schema': ACTION_CARD_SCHEMA,
        'transaction_sha256': transaction_sha256,
        'sequence': sequence,
        'phase': phase,
        'snapshot_revision': _require_sha256(snapshot_revision, 'snapshot_revision'),
        'element': element_key,
        'element_sha256': hashlib.sha256(element_key.encode('utf-8')).hexdigest(),
        'method': method,
        'verification_operation': verification_operation,
        'effect_class': declared.get('effect_class'),
        'postcondition_kind': (
            'notifications_all'
            if element_key == NOTIFICATIONS_NAVIGATION
            else postcondition['kind']
        ),
    }
    card['card_sha256'] = _sha256(card)
    return card


def _candidate_age_seconds(target: ElementRef) -> int:
    age = (target.raw or {}).get('notification_age')
    match = _AGE.fullmatch(str(age or ''))
    if match is None:
        raise LinkedInUnit1Error('selected candidate has no exact relative age')
    multiplier = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}[
        match.group('unit')
    ]
    return int(match.group('count')) * multiplier


def _selected_surface_identity(snapshot: Snapshot, private: Mapping[str, Any]) -> None:
    activity = private['selected_activity']
    key = f'{SELECTED_POST_PREFIX}{activity}'
    target = _mapped_singleton(snapshot, key)
    raw = dict(target.raw or {})
    if (
        raw.get('selected_activity') != activity
        or raw.get('selected_post_body_sha256') != private['selected_post_body_sha256']
    ):
        raise LinkedInUnit1Error('selected post does not match the frozen activity/body')


def compile_unit1_step(
    snapshot: Snapshot,
    snapshot_revision: str,
    private_input: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if snapshot.platform != 'linkedin':
        raise LinkedInUnit1Error('Unit 1 requires a LinkedIn snapshot')
    private = validate_private_input(private_input)
    transaction_sha256 = _sha256(private)
    previous_phase = verify_receipt_chain(receipts, transaction_sha256)
    if previous_phase == 'comment_submit':
        raise LinkedInUnit1Error('comment delivery is terminal')
    sequence = len(receipts) + 1

    if previous_phase is None:
        return _declared_card(
            snapshot=snapshot,
            snapshot_revision=snapshot_revision,
            transaction_sha256=transaction_sha256,
            sequence=sequence,
            phase='notifications_navigation',
            element_key=NOTIFICATIONS_NAVIGATION,
        )

    if previous_phase in {'notifications_navigation', 'notifications_continuation'}:
        if not _exact_engagement_route(snapshot.url, 'notifications_all'):
            raise LinkedInUnit1Error('candidate selection requires exact Notifications-All')
        continuation_keys = [
            key for key, matches in snapshot.mapped.items()
            if _CONTINUATION.fullmatch(key) is not None and matches
        ]
        if len(continuation_keys) > 1:
            raise LinkedInUnit1Error('Notifications continuation is ambiguous')
        if continuation_keys:
            return _declared_card(
                snapshot=snapshot,
                snapshot_revision=snapshot_revision,
                transaction_sha256=transaction_sha256,
                sequence=sequence,
                phase='notifications_continuation',
                element_key=continuation_keys[0],
            )
        observed_stream_sha256 = notification_stream_sha256(snapshot)
        if observed_stream_sha256 != private['notification_stream_sha256']:
            raise LinkedInUnit1Error('complete notification stream changed after policy freeze')
        candidate_key = next(
            (
                key for key in snapshot.mapped
                if (match := _CANDIDATE.fullmatch(key)) is not None
                and match.group('activity') == private['selected_activity']
            ),
            None,
        )
        if candidate_key is None:
            raise LinkedInUnit1Error('frozen qualifying activity is not mapped')
        candidate = _mapped_singleton(snapshot, candidate_key)
        age_seconds = _candidate_age_seconds(candidate)
        if (
            age_seconds != private['selected_age_seconds']
            or age_seconds > private['freshness_max_hours'] * 3600
        ):
            raise LinkedInUnit1Error('frozen qualifying activity age changed or expired')
        return _declared_card(
            snapshot=snapshot,
            snapshot_revision=snapshot_revision,
            transaction_sha256=transaction_sha256,
            sequence=sequence,
            phase='notification_candidate',
            element_key=candidate_key,
        )

    _selected_surface_identity(snapshot, private)
    activity = private['selected_activity']
    body_sha256 = private['selected_post_body_sha256']

    if previous_phase in {'notification_candidate', 'thread_scroll'}:
        thread_key = (
            f'{SELECTED_THREAD_OPEN_PREFIX}{activity}_body_{body_sha256}'
        )
        target = _mapped_singleton(snapshot, thread_key)
        declared = element_operation(thread_key, list(target.states), dict(target.raw or {}))
        if not isinstance(declared, dict):
            raise LinkedInUnit1Error('selected thread opener has no declared operation')
        phase = 'thread_scroll' if declared.get('method') == 'scroll_into_view' else 'thread_open'
        if previous_phase == 'thread_scroll' and phase != 'thread_open':
            raise LinkedInUnit1Error('thread opener is still outside the verified viewport')
        return _declared_card(
            snapshot=snapshot,
            snapshot_revision=snapshot_revision,
            transaction_sha256=transaction_sha256,
            sequence=sequence,
            phase=phase,
            element_key=thread_key,
        )

    if previous_phase in {'thread_open', 'optional_like'}:
        reaction_key = (
            f'{SELECTED_POST_REACTION_PREFIX}{activity}_body_{body_sha256}'
        )
        reaction = _mapped_singleton(snapshot, reaction_key)
        reaction_declared = element_operation(
            reaction_key,
            list(reaction.states),
            dict(reaction.raw or {}),
        )
        if not isinstance(reaction_declared, dict):
            raise LinkedInUnit1Error('selected reaction has no declared operation')
        reaction_method = reaction_declared.get('method')
        if previous_phase == 'optional_like' and reaction_method != 'observe':
            raise LinkedInUnit1Error('optional Like did not reach the exact liked state')
        if private['like_authorized'] and reaction_method == 'activate_optional_like':
            return _declared_card(
                snapshot=snapshot,
                snapshot_revision=snapshot_revision,
                transaction_sha256=transaction_sha256,
                sequence=sequence,
                phase='optional_like',
                element_key=reaction_key,
            )

    if previous_phase not in {'thread_open', 'optional_like', 'comment_paste'}:
        raise LinkedInUnit1Error('Unit 1 receipt history cannot advance from this phase')

    editor_key = f'{SELECTED_POST_EDITOR_PREFIX}{activity}_body_{body_sha256}'
    editor = _mapped_singleton(snapshot, editor_key)
    editor_declared = element_operation(
        editor_key,
        list(editor.states),
        dict(editor.raw or {}),
    )
    if not isinstance(editor_declared, dict):
        raise LinkedInUnit1Error('selected comment editor has no declared operation')

    if previous_phase != 'comment_paste' and editor_declared.get('method') == 'paste_frozen_text':
        return _declared_card(
            snapshot=snapshot,
            snapshot_revision=snapshot_revision,
            transaction_sha256=transaction_sha256,
            sequence=sequence,
            phase='comment_paste',
            element_key=editor_key,
        )
    editor_raw = dict(editor.raw or {})
    if (
        editor_declared.get('method') != 'observe'
        or editor_raw.get('comment_editor_text_sha256') != private['text_sha256']
        or editor_raw.get('comment_editor_text_chars') != len(private['text'])
    ):
        raise LinkedInUnit1Error('editor does not contain the exact frozen draft')
    submit_key = (
        f'{SELECTED_POST_SUBMIT_PREFIX}{activity}_body_{body_sha256}_draft_'
        f"{private['text_sha256']}"
    )
    return _declared_card(
        snapshot=snapshot,
        snapshot_revision=snapshot_revision,
        transaction_sha256=transaction_sha256,
        sequence=sequence,
        phase='comment_submit',
        element_key=submit_key,
    )


def accept_unit1_step(
    card: Mapping[str, Any],
    barrier_receipt: Mapping[str, Any],
    previous_receipt_sha256: str | None,
    private_input: Mapping[str, Any],
) -> dict[str, Any]:
    private = validate_private_input(private_input)
    transaction_sha256 = _sha256(private)
    if not isinstance(card, Mapping) or frozenset(card) != _CARD_KEYS:
        raise LinkedInUnit1Error('action card fields are incomplete or unknown')
    card_payload = dict(card)
    card_digest = card_payload.pop('card_sha256', None)
    if _require_sha256(card_digest, 'card_sha256') != _sha256(card_payload):
        raise LinkedInUnit1Error('action card digest is invalid')
    if card_payload.get('schema') != ACTION_CARD_SCHEMA:
        raise LinkedInUnit1Error('action card schema is invalid')
    if card_payload.get('transaction_sha256') != transaction_sha256:
        raise LinkedInUnit1Error('action card is not bound to the frozen private input')
    phase = card_payload.get('phase')
    if phase not in _PHASE_TRANSITIONS:
        raise LinkedInUnit1Error('action card phase is invalid')
    sequence = card_payload.get('sequence')
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise LinkedInUnit1Error('action card sequence is invalid')
    if card_payload.get('method') != _PHASE_METHODS[phase]:
        raise LinkedInUnit1Error('action card method does not match its Unit 1 phase')
    element = card_payload.get('element')
    if (
        not isinstance(element, str)
        or not element
        or card_payload.get('element_sha256')
        != hashlib.sha256(element.encode('utf-8')).hexdigest()
    ):
        raise LinkedInUnit1Error('action card element identity is invalid')
    if previous_receipt_sha256 is not None:
        _require_sha256(previous_receipt_sha256, 'previous_receipt_sha256')
    if (sequence == 1) != (previous_receipt_sha256 is None):
        raise LinkedInUnit1Error('action card sequence is not bound to the prior receipt')
    if sequence == 1 and phase != 'notifications_navigation':
        raise LinkedInUnit1Error('Unit 1 must begin from Notifications navigation')
    if not isinstance(barrier_receipt, Mapping):
        raise LinkedInUnit1Error('postcondition barrier receipt is invalid')
    postcondition = barrier_receipt.get('postcondition_receipt')
    terminal = phase == 'comment_submit'
    next_mutation_authorized = barrier_receipt.get('next_mutation_authorized')
    if (
        barrier_receipt.get('result') != 'PASS'
        or not isinstance(postcondition, Mapping)
        or postcondition.get('element_key') != card_payload.get('element')
        or postcondition.get('operation') != card_payload.get('verification_operation')
        or postcondition.get('postcondition') != card_payload.get('postcondition_kind')
        or bool(barrier_receipt.get('terminal_delivery_verified')) is not terminal
        or bool(barrier_receipt.get('observe_required_before_next_mutation')) != (not terminal)
        or not isinstance(next_mutation_authorized, bool)
        or (terminal and next_mutation_authorized is not False)
    ):
        raise LinkedInUnit1Error('exact postcondition barrier did not authorize the step')
    if postcondition.get('effect_class') != card_payload.get('effect_class'):
        raise LinkedInUnit1Error('postcondition effect class does not match the action card')
    if terminal:
        submit_match = _SUBMIT.fullmatch(element)
        expected_postcondition_keys = {
            'activity_exact',
            'activity_sources',
            'comment_text_chars',
            'comment_text_sha256',
            'editor_empty',
            'effect_class',
            'element_key',
            'exact_own_comment_count',
            'observed_url',
            'operation',
            'postcondition',
            'route_exact',
            'selected_post_body_sha256',
        }
        activity_sources = postcondition.get('activity_sources')
        observed_url = postcondition.get('observed_url')
        if (
            submit_match is None
            or submit_match.group('activity') != private['selected_activity']
            or submit_match.group('body') != private['selected_post_body_sha256']
            or submit_match.group('draft') != private['text_sha256']
            or set(postcondition) != expected_postcondition_keys
            or postcondition.get('route_exact') is not True
            or postcondition.get('activity_exact') is not True
            or not isinstance(activity_sources, list)
            or not activity_sources
            or not all(isinstance(source, str) and source for source in activity_sources)
            or postcondition.get('selected_post_body_sha256')
            != private['selected_post_body_sha256']
            or postcondition.get('editor_empty') is not True
            or postcondition.get('exact_own_comment_count') != 1
            or postcondition.get('comment_text_sha256') != private['text_sha256']
            or postcondition.get('comment_text_chars') != len(private['text'])
            or not isinstance(observed_url, str)
            or not observed_url.startswith('https://www.linkedin.com/')
        ):
            raise LinkedInUnit1Error(
                'terminal barrier did not prove the exact route/activity/body '
                'and one rendered own author/text comment'
            )
    receipt = {
        'schema': STEP_RECEIPT_SCHEMA,
        'transaction_sha256': card_payload['transaction_sha256'],
        'sequence': card_payload['sequence'],
        'phase': phase,
        'previous_receipt_sha256': previous_receipt_sha256,
        'card_sha256': card_digest,
        'snapshot_revision': card_payload['snapshot_revision'],
        'element_sha256': card_payload['element_sha256'],
        'method': card_payload['method'],
        'effect_class': card_payload['effect_class'],
        'postcondition_sha256': _sha256(postcondition),
        'postcondition_passed': True,
        'fresh_observation_required': not terminal,
        'next_step_authorized': not terminal,
        'terminal_delivery_verified': terminal,
    }
    receipt['receipt_sha256'] = _sha256(receipt)
    return receipt


__all__ = [
    'ACTION_CARD_SCHEMA',
    'LinkedInUnit1Error',
    'PRIVATE_INPUT_SCHEMA',
    'STEP_RECEIPT_SCHEMA',
    'accept_unit1_step',
    'compile_unit1_step',
    'notification_stream_sha256',
    'private_input_sha256',
    'validate_private_input',
    'verify_receipt_chain',
]
