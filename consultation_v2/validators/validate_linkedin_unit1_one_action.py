#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

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


def barrier(card: dict) -> dict:
    terminal = card['phase'] == 'comment_submit'
    return {
        'result': 'PASS',
        'next_mutation_authorized': not terminal,
        'terminal_delivery_verified': terminal,
        'observe_required_before_next_mutation': not terminal,
        'postcondition_receipt': {
            'element_key': card['element'],
            'operation': card['verification_operation'],
            'effect_class': card['effect_class'],
            'postcondition': card['postcondition_kind'],
        },
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
            states=['showing', 'enabled'],
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
    require(
        set(card_schema['required']) == set(navigation),
        'action card schema drifted from the compiler output',
    )
    receipts.append(accept_unit1_step(navigation, barrier(navigation), None))

    candidate_card = compile_unit1_step(stream_snapshot, REVISION, private, receipts)
    require(candidate_card['phase'] == 'notification_candidate', 'qualifying post was not selected')
    receipts.append(accept_unit1_step(
        candidate_card,
        barrier(candidate_card),
        receipts[-1]['receipt_sha256'],
    ))

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
    thread = element(
        thread_key,
        states=['enabled', 'focusable'],
        raw={
            'selected_activity': ACTIVITY,
            'selected_post_body_sha256': BODY_SHA256,
        },
    )
    original_viewport = manual._selected_thread_viewport_state
    manual._selected_thread_viewport_state = lambda _raw: {
        'live_extent_in_viewport': True,
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
    receipts.append(accept_unit1_step(
        thread_card,
        barrier(thread_card),
        receipts[-1]['receipt_sha256'],
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
        barrier(like_card),
        receipts[-1]['receipt_sha256'],
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
        barrier(paste_card),
        receipts[-1]['receipt_sha256'],
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
    receipts.append(accept_unit1_step(
        submit_card,
        barrier(submit_card),
        receipts[-1]['receipt_sha256'],
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
