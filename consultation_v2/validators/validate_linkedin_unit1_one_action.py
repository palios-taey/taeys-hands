#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import types

from jsonschema import Draft202012Validator


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
            SHOWING = 'showing'
            VISIBLE = 'visible'

        class Text:
            pass

    fake_repository.Atspi = _FakeAtspi
    sys.modules['gi'] = fake_gi
    sys.modules['gi.repository'] = fake_repository

from consultation_v2.platforms.linkedin import manual  # noqa: E402
from consultation_v2.platforms.linkedin.unit1 import (  # noqa: E402
    LinkedInUnit1Error,
    accept_unit1_step,
    compile_unit1_step,
    notification_stream_sha256,
    private_input_sha256,
    verify_receipt_chain,
)
from consultation_v2.types import ElementRef, Snapshot  # noqa: E402


REVISION = '1' * 64
ACTIVITY = '1234567890123456789'
BODY_SHA256 = hashlib.sha256(b'public post body').hexdigest()
TEXT = 'A precise frozen comment.'
TEXT_SHA256 = hashlib.sha256(TEXT.encode('utf-8')).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def element(
    key: str,
    *,
    states: list[str],
    raw: dict | None = None,
) -> ElementRef:
    return ElementRef(
        key=key,
        name=key,
        role='push button',
        x=None,
        y=None,
        states=states,
        raw=dict(raw or {}),
    )


def snapshot(mapped: dict[str, list[ElementRef]]) -> Snapshot:
    return Snapshot(
        platform='linkedin',
        url='https://www.linkedin.com/notifications/?filter=all',
        mapped=mapped,
    )


def barrier(card: dict, private: dict) -> dict:
    terminal = card['phase'] == 'comment_submit'
    postcondition = {
        'element_key': card['element'],
        'operation': card['verification_operation'],
        'effect_class': card['effect_class'],
        'postcondition': card['postcondition_kind'],
    }
    if terminal:
        postcondition.update({
            'route_exact': True,
            'activity_exact': True,
            'activity_sources': ['document_url'],
            'selected_post_body_sha256': private['selected_post_body_sha256'],
            'editor_empty': True,
            'exact_own_comment_count': 1,
            'comment_text_sha256': private['text_sha256'],
            'comment_text_chars': len(private['text']),
            'observed_url': 'https://www.linkedin.com/feed/update/example/',
        })
    if card['method'] == 'scroll_into_view':
        postcondition.update({
            'scroll_target': card['scroll_target'],
            'scroll_target_source': card['scroll_target_source'],
            'scroll_alignment': card['scroll_alignment'],
            'phase': card['phase'],
            'scroll_context_intersects_viewport': True,
            'scroll_target_exact': True,
            'live_extent_in_viewport': True,
            'available_below_px': card.get(
                'min_downward_clearance_px',
                0,
            ),
        })
    if card['phase'] == 'thread_scroll':
        postcondition.update({
            'min_downward_clearance_px': card[
                'min_downward_clearance_px'
            ],
            'activity_exact': True,
            'body_sha256_exact': True,
            'selected_post_root_intersects_viewport': True,
            'thread_opener_live_extent_in_viewport': True,
            'thread_opener_available_below_px': card[
                'min_downward_clearance_px'
            ],
        })
    return {
        'result': 'PASS',
        'next_mutation_authorized': not terminal,
        'terminal_delivery_verified': terminal,
        'observe_required_before_next_mutation': not terminal,
        'postcondition_receipt': postcondition,
    }


def main() -> int:
    candidate_key = f'notification_candidate_001_activity_{ACTIVITY}'
    candidate = element(
        candidate_key,
        states=['enabled', 'focusable'],
        raw={
            'notification_activity': ACTIVITY,
            'notification_age': '2h',
            'notification_ordinal': 1,
        },
    )
    stream_snapshot = snapshot({candidate_key: [candidate]})
    private = {
        'schema': 'linkedin_unit1_private_input_v1',
        'operation': 'comment_from_notifications',
        'cycle_id': 'cycle-1',
        'transaction_id': 'transaction-1',
        'display': ':18',
        'policy_sha256': '2' * 64,
        'notification_stream_sha256': notification_stream_sha256(stream_snapshot),
        'selected_activity': ACTIVITY,
        'selected_age_seconds': 7200,
        'freshness_max_hours': 72,
        'target_passed': True,
        'dedup_passed': True,
        'author_cooloff_passed': True,
        'selected_post_body_sha256': BODY_SHA256,
        'thread_evidence_sha256': '3' * 64,
        'like_authorized': True,
        'text': TEXT,
        'text_sha256': TEXT_SHA256,
        'expected_author_name': 'Private Author',
    }
    private_schema = json.loads(
        (REPO_ROOT / 'consultation_v2/platforms/linkedin/unit1-private-input.schema.json')
        .read_text(encoding='utf-8')
    )
    require(
        set(private_schema['required']) == set(private),
        'private input schema drifted from the frozen binding',
    )
    transaction_sha256 = private_input_sha256(private)
    receipts: list[dict] = []

    navigation_snapshot = snapshot({
        manual.NOTIFICATIONS_NAVIGATION: [element(
            manual.NOTIFICATIONS_NAVIGATION,
            states=['enabled', 'focusable'],
        )],
    })
    navigation = compile_unit1_step(
        navigation_snapshot,
        REVISION,
        private,
        receipts,
    )
    require(navigation['phase'] == 'notifications_navigation', 'Notifications was not first')
    require(
        navigation['postcondition_kind'] == 'notifications_all',
        'Notifications card did not bind the exact route receipt',
    )
    card_schema = json.loads(
        (REPO_ROOT / 'consultation_v2/platforms/linkedin/unit1-action-card.schema.json')
        .read_text(encoding='utf-8')
    )
    Draft202012Validator.check_schema(card_schema)
    card_validator = Draft202012Validator(card_schema)
    require(
        set(card_schema['required']) == set(navigation),
        'action card schema drifted from the compiler output',
    )
    require(
        not list(card_validator.iter_errors(navigation)),
        'valid non-scroll action card failed its public schema',
    )
    for field, value in (
        ('scroll_target', 'selected_post_root'),
        ('scroll_target_source', 'mapped_context'),
        ('scroll_alignment', 'top_edge'),
        ('min_downward_clearance_px', 500),
    ):
        require(
            list(card_validator.iter_errors({**navigation, field: value})),
            f'non-scroll action card accepted forbidden {field}',
        )
    receipts.append(accept_unit1_step(navigation, barrier(navigation, private), None, private))

    candidate_card = compile_unit1_step(stream_snapshot, REVISION, private, receipts)
    require(candidate_card['phase'] == 'notification_candidate', 'qualifying post was not selected')
    receipts.append(accept_unit1_step(
        candidate_card,
        barrier(candidate_card, private),
        receipts[-1]['receipt_sha256'],
        private,
    ))
    candidate_receipts = list(receipts)

    selected_post_key = f'{manual.SELECTED_POST_PREFIX}{ACTIVITY}'
    thread_key = (
        f'{manual.SELECTED_THREAD_OPEN_PREFIX}{ACTIVITY}_body_{BODY_SHA256}'
    )
    selected = element(
        selected_post_key,
        states=['showing'],
        raw={
            'selected_activity': ACTIVITY,
            'selected_post_body_sha256': BODY_SHA256,
        },
    )
    thread_opener_object = object()
    thread = element(
        thread_key,
        states=['enabled', 'focusable'],
        raw={
            'atspi_obj': thread_opener_object,
            'scroll_target_atspi_obj': thread_opener_object,
            'selected_post_root_atspi_obj': object(),
            'selected_post_body_atspi_obj': object(),
            'selected_post_body_showing': True,
            'selected_activity': ACTIVITY,
            'selected_post_body_sha256': BODY_SHA256,
        },
    )
    original_viewport = manual._selected_thread_viewport_state
    manual._selected_thread_viewport_state = lambda _raw: {
        'error': 'live_extent_outside_display',
    }
    try:
        thread_scroll_card = compile_unit1_step(
            snapshot({selected_post_key: [selected], thread_key: [thread]}),
            REVISION,
            private,
            receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(
        thread_scroll_card['phase'] == 'thread_scroll'
        and thread_scroll_card['min_downward_clearance_px'] == 500
        and not list(card_validator.iter_errors(thread_scroll_card)),
        'valid selected-root scroll card failed its public schema',
    )
    for field in (
        'scroll_target',
        'scroll_target_source',
        'scroll_alignment',
        'min_downward_clearance_px',
    ):
        missing_scroll_field = dict(thread_scroll_card)
        missing_scroll_field.pop(field)
        require(
            list(card_validator.iter_errors(missing_scroll_field)),
            f'scroll action card accepted missing {field}',
        )
    thread_scroll_barrier = barrier(thread_scroll_card, private)
    accept_unit1_step(
        thread_scroll_card,
        thread_scroll_barrier,
        receipts[-1]['receipt_sha256'],
        private,
    )
    divergent_scroll_barrier = json.loads(json.dumps(thread_scroll_barrier))
    divergent_scroll_barrier['postcondition_receipt'][
        'available_below_px'
    ] = 501
    try:
        accept_unit1_step(
            thread_scroll_card,
            divergent_scroll_barrier,
            receipts[-1]['receipt_sha256'],
            private,
        )
    except LinkedInUnit1Error:
        pass
    else:
        raise AssertionError('thread scroll accepted divergent clearance evidence')
    manual._selected_thread_viewport_state = lambda _raw: {
        'intersects_viewport': True,
        'live_extent_in_viewport': True,
        'available_below_px': 199,
    }
    try:
        thread_card = compile_unit1_step(
            snapshot({selected_post_key: [selected], thread_key: [thread]}),
            REVISION,
            private,
            receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(thread_card['phase'] == 'thread_open', 'thread was not opened explicitly')
    zero_thread_key = (
        f'{manual.SELECTED_THREAD_ZERO_OPEN_PREFIX}{ACTIVITY}_body_{BODY_SHA256}'
    )
    zero_thread_opener_object = object()
    zero_thread = element(
        zero_thread_key,
        states=['showing', 'enabled', 'focusable'],
        raw={
            'atspi_obj': zero_thread_opener_object,
            'scroll_target_atspi_obj': zero_thread_opener_object,
            'selected_post_root_atspi_obj': object(),
            'selected_post_body_atspi_obj': object(),
            'selected_post_body_showing': True,
            'selected_activity': ACTIVITY,
            'selected_post_body_sha256': BODY_SHA256,
            'selected_thread_expected_count': 0,
            'comment_editor_ready_before': False,
        },
    )
    manual._selected_thread_viewport_state = lambda _raw: {
        'intersects_viewport': True,
        'live_extent_in_viewport': True,
        'available_below_px': 199,
    }
    try:
        zero_thread_card = compile_unit1_step(
            snapshot({
                selected_post_key: [selected],
                zero_thread_key: [zero_thread],
            }),
            REVISION,
            private,
            candidate_receipts,
        )
    finally:
        manual._selected_thread_viewport_state = original_viewport
    require(
        zero_thread_card['phase'] == 'thread_open'
        and zero_thread_card['element'] == zero_thread_key
        and zero_thread_card['postcondition_kind']
        == 'exact_selected_activity_zero_comment_thread_open',
        'exact zero-comment thread opener was not isolated',
    )
    receipts.append(accept_unit1_step(
        thread_card,
        barrier(thread_card, private),
        receipts[-1]['receipt_sha256'],
        private,
    ))

    reaction_key = (
        f'{manual.SELECTED_POST_REACTION_PREFIX}{ACTIVITY}_body_{BODY_SHA256}'
    )
    editor_key = (
        f'{manual.SELECTED_POST_EDITOR_PREFIX}{ACTIVITY}_body_{BODY_SHA256}'
    )
    reaction = element(
        reaction_key,
        states=['enabled', 'focusable'],
        raw={
            'selected_activity': ACTIVITY,
            'selected_post_body_sha256': BODY_SHA256,
            'selected_post_reaction_state': 'no_reaction',
        },
    )
    empty_editor = element(
        editor_key,
        states=['editable', 'focusable'],
        raw={
            'selected_activity': ACTIVITY,
            'selected_post_body_sha256': BODY_SHA256,
            'comment_editor_ready': True,
            'comment_editor_empty': True,
            'comment_editor_text_sha256': hashlib.sha256(b'').hexdigest(),
            'comment_editor_text_chars': 0,
        },
    )
    like_card = compile_unit1_step(
        snapshot({
            selected_post_key: [selected],
            reaction_key: [reaction],
            editor_key: [empty_editor],
        }),
        REVISION,
        private,
        receipts,
    )
    require(like_card['phase'] == 'optional_like', 'authorized Like was not isolated')
    receipts.append(accept_unit1_step(
        like_card,
        barrier(like_card, private),
        receipts[-1]['receipt_sha256'],
        private,
    ))

    liked = element(
        reaction_key,
        states=['enabled', 'focusable'],
        raw={
            'selected_activity': ACTIVITY,
            'selected_post_body_sha256': BODY_SHA256,
            'selected_post_reaction_state': 'liked',
        },
    )
    paste_card = compile_unit1_step(
        snapshot({
            selected_post_key: [selected],
            reaction_key: [liked],
            editor_key: [empty_editor],
        }),
        REVISION,
        private,
        receipts,
    )
    require(paste_card['phase'] == 'comment_paste', 'frozen paste was not isolated')
    receipts.append(accept_unit1_step(
        paste_card,
        barrier(paste_card, private),
        receipts[-1]['receipt_sha256'],
        private,
    ))

    filled_editor = element(
        editor_key,
        states=['editable', 'focusable'],
        raw={
            'selected_activity': ACTIVITY,
            'selected_post_body_sha256': BODY_SHA256,
            'comment_editor_ready': True,
            'comment_editor_empty': False,
            'comment_editor_text_sha256': TEXT_SHA256,
            'comment_editor_text_chars': len(TEXT),
        },
    )
    submit_key = (
        f'{manual.SELECTED_POST_SUBMIT_PREFIX}{ACTIVITY}_body_{BODY_SHA256}_draft_'
        f'{TEXT_SHA256}'
    )
    submit = element(
        submit_key,
        states=['focusable', 'showing'],
        raw={
            'selected_activity': ACTIVITY,
            'selected_post_body_sha256': BODY_SHA256,
            'comment_submit_ready': True,
            'comment_draft_sha256': TEXT_SHA256,
            'comment_draft_chars': len(TEXT),
        },
    )
    submit_card = compile_unit1_step(
        snapshot({
            selected_post_key: [selected],
            reaction_key: [liked],
            editor_key: [filled_editor],
            submit_key: [submit],
        }),
        REVISION,
        private,
        receipts,
    )
    require(submit_card['phase'] == 'comment_submit', 'publication was not final')
    submit_barrier = barrier(submit_card, private)
    for field, wrong_value in (
        ('route_exact', False),
        ('activity_exact', False),
        ('selected_post_body_sha256', '4' * 64),
        ('exact_own_comment_count', 0),
        ('comment_text_sha256', '5' * 64),
    ):
        insufficient = json.loads(json.dumps(submit_barrier))
        insufficient['postcondition_receipt'][field] = wrong_value
        try:
            accept_unit1_step(
                submit_card,
                insufficient,
                receipts[-1]['receipt_sha256'],
                private,
            )
        except LinkedInUnit1Error:
            pass
        else:
            raise AssertionError(f'terminal barrier accepted invalid {field}')
    insufficient = json.loads(json.dumps(submit_barrier))
    insufficient['postcondition_receipt'].pop('activity_sources')
    try:
        accept_unit1_step(
            submit_card,
            insufficient,
            receipts[-1]['receipt_sha256'],
            private,
        )
    except LinkedInUnit1Error:
        pass
    else:
        raise AssertionError('terminal barrier accepted incomplete evidence')
    wrong_private = {**private, 'expected_author_name': 'Different Private Author'}
    try:
        accept_unit1_step(
            submit_card,
            submit_barrier,
            receipts[-1]['receipt_sha256'],
            wrong_private,
        )
    except LinkedInUnit1Error:
        pass
    else:
        raise AssertionError('terminal barrier escaped the frozen author binding')
    receipts.append(accept_unit1_step(
        submit_card,
        submit_barrier,
        receipts[-1]['receipt_sha256'],
        private,
    ))
    require(
        verify_receipt_chain(receipts, transaction_sha256) == 'comment_submit',
        'terminal receipt chain did not verify',
    )
    require(
        receipts[-1]['terminal_delivery_verified'] is True
        and receipts[-1]['next_step_authorized'] is False,
        'final publication receipt was not terminal',
    )
    receipt_schema = json.loads(
        (REPO_ROOT / 'consultation_v2/platforms/linkedin/unit1-step-receipt.schema.json')
        .read_text(encoding='utf-8')
    )
    require(
        set(receipt_schema['required']) == set(receipts[-1]),
        'step receipt schema drifted from the terminal receipt',
    )

    forged = [dict(receipts[1])]
    forged[0]['sequence'] = 1
    forged[0]['previous_receipt_sha256'] = None
    payload = dict(forged[0])
    payload.pop('receipt_sha256')
    forged[0]['receipt_sha256'] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    ).hexdigest()
    try:
        verify_receipt_chain(forged, transaction_sha256)
    except LinkedInUnit1Error:
        pass
    else:
        raise AssertionError('candidate-only chain bypassed Notifications-first')

    invalid_private = {**private, 'dedup_passed': False}
    try:
        private_input_sha256(invalid_private)
    except LinkedInUnit1Error:
        pass
    else:
        raise AssertionError('nonqualifying private policy was accepted')

    print('linkedin Unit 1 one-action compiler: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
