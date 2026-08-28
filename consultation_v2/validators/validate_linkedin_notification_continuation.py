#!/usr/bin/env python3
from __future__ import annotations

import time

from validate_linkedin_unit1_preparation import (
    ACTIVITY_A,
    Node,
    activity_uri,
    inventory_snapshot,
    notification_article,
    ref,
    require,
)

from consultation_v2.platforms.linkedin import manual


def with_controls(snapshot):
    for name in ('All', 'Jobs', 'My posts', 'Mentions'):
        node = Node(
            'radio button',
            name,
            states=['checked', 'selected'] if name == 'All' else [],
        )
        snapshot.unknown.append(ref(node))
    continuation = Node(
        'push button',
        'Show more results',
        states=['enabled', 'focusable'],
    )
    snapshot.unknown.append(ref(continuation))
    return snapshot


def expanded_snapshot():
    snapshot = inventory_snapshot()
    root = next(
        item for item in snapshot.unknown if item.role == 'article'
    ).atspi_obj.get_parent()
    article, references = notification_article(
        'Notification.',
        'Someone viewed your profile.',
        '4d',
        uri='https://www.linkedin.com/me/profile-views/',
    )
    root.add(article)
    snapshot.unknown.extend(references)
    return with_controls(snapshot)


def without_category_controls(snapshot):
    snapshot.unknown = [
        item for item in snapshot.unknown if item.role != 'radio button'
    ]
    return snapshot


def virtualized_changed_snapshot():
    snapshot = inventory_snapshot()
    profile_result = next(
        item
        for item in snapshot.unknown
        if item.role == 'link'
        and item.name == 'Your profile appeared in search.'
    )
    profile_result.atspi_obj.uri = activity_uri(ACTIVITY_A + '2')
    return without_category_controls(with_controls(snapshot))


def main() -> int:
    before = with_controls(inventory_snapshot())
    augmented = manual.augment_snapshot(before)
    continuation_keys = [
        key
        for key in augmented.mapped
        if key.startswith(manual.NOTIFICATIONS_CONTINUATION_PREFIX)
    ]
    require(len(continuation_keys) == 1, 'continuation key is not exact')
    continuation_key = continuation_keys[0]
    declared = manual.element_operation(
        continuation_key,
        ['enabled', 'focusable'],
    )
    require(
        declared['postcondition']['kind']
        == 'notification_stream_stable_novelty'
        and declared['postcondition']['prior_raw_notification_count'] == 3,
        'continuation card does not bind the full mounted stream',
    )
    tampered_key = continuation_key[:-1] + (
        '0' if continuation_key[-1] != '0' else '1'
    )
    try:
        manual._notification_continuation_measurement(
            before,
            manual._CONTINUATION_KEY.fullmatch(tampered_key),
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            'tampered frozen notification inventory retained authority'
        )

    no_controls = without_category_controls(with_controls(inventory_snapshot()))
    no_controls_augmented = manual.augment_snapshot(no_controls)
    require(
        len([
            key for key in no_controls_augmented.mapped
            if key.startswith(manual.NOTIFICATIONS_CONTINUATION_PREFIX)
        ]) == 1,
        'continuation disappeared when top-of-page category controls left the viewport',
    )
    require(
        not any(
            key.startswith(manual.NOTIFICATION_CANDIDATE_PREFIX)
            for key in no_controls_augmented.mapped
        ),
        'candidate keys bypassed live All-category proof',
    )

    obsolete_one_link = with_controls(inventory_snapshot())
    obsolete_article = next(
        item for item in obsolete_one_link.unknown if item.role == 'article'
    )
    obsolete_children = obsolete_article.atspi_obj.children
    obsolete_article.atspi_obj.children = [
        obsolete_children[1],
        obsolete_children[2],
    ]
    try:
        manual.augment_snapshot(obsolete_one_link)
    except ValueError:
        pass
    else:
        raise AssertionError(
            'continuation accepted the obsolete one-link notification fixture'
        )

    after = without_category_controls(expanded_snapshot())
    receipt = manual.verify_post_action(after, continuation_key, 'activate')
    require(
        receipt['postcondition'] == 'notification_stream_stable_novelty'
        and receipt['route_exact'] is True
        and receipt['category_exact'] is False
        and receipt['prior_raw_notification_count'] == 3
        and receipt['observed_raw_notification_count'] == 4
        and receipt['raw_notification_count_grew'] is True
        and receipt['raw_notification_prefix_exact'] is True
        and receipt['raw_notification_inventory_changed'] is True
        and receipt['raw_notification_inventory_novelty_exact'] is True
        and receipt['observed_novel_notification_identity_count'] == 1
        and receipt['candidate_projection_exact'] is True
        and receipt['observed_candidate_count'] == 1,
        'noncandidate mounted-stream growth did not satisfy continuation',
    )

    changed_text = expanded_snapshot()
    read_link = next(
        item
        for item in changed_text.unknown
        if item.role == 'link' and item.name == 'Bob posted another exact update.'
    )
    read_link.name = 'A changed accessible notification sentence.'
    read_link.atspi_obj.name = read_link.name
    text_receipt = manual.verify_post_action(
        changed_text,
        continuation_key,
        'activate',
    )
    require(
        text_receipt['raw_notification_prefix_exact'] is True,
        'mounted-stream identity is brittle to notification text',
    )

    changed_uri = expanded_snapshot()
    first_link = next(
        item
        for item in changed_uri.unknown
        if item.role == 'link' and item.name.startswith('Unread notification.')
    )
    first_link.atspi_obj.uri = activity_uri(ACTIVITY_A + '1')
    measurement = manual._notification_continuation_measurement(
        changed_uri,
        manual._CONTINUATION_KEY.fullmatch(continuation_key),
    )
    require(
        measurement['raw_notification_prefix_exact'] is False
        and measurement['raw_notification_inventory_changed'] is True
        and measurement['raw_notification_inventory_novelty_exact'] is True
        and measurement['postcondition_matched'] is True,
        'changed exact mounted-stream inventory did not satisfy continuation',
    )

    virtualized_before = without_category_controls(expanded_snapshot())
    virtualized_augmented = manual.augment_snapshot(virtualized_before)
    virtualized_key = next(
        key
        for key in virtualized_augmented.mapped
        if key.startswith(manual.NOTIFICATIONS_CONTINUATION_PREFIX)
    )
    virtualized_after = virtualized_changed_snapshot()
    virtualized_measurement = manual._notification_continuation_measurement(
        virtualized_after,
        manual._CONTINUATION_KEY.fullmatch(virtualized_key),
    )
    require(
        virtualized_measurement['prior_raw_notification_count'] == 4
        and virtualized_measurement['observed_raw_notification_count'] == 3
        and virtualized_measurement['raw_notification_count_grew'] is False
        and virtualized_measurement['raw_notification_prefix_exact'] is False
        and virtualized_measurement['raw_notification_inventory_changed'] is True
        and virtualized_measurement['raw_notification_inventory_novelty_exact']
        is True
        and virtualized_measurement['observed_novel_notification_identity_count']
        == 1
        and virtualized_measurement['candidate_projection_exact'] is True
        and virtualized_measurement['postcondition_matched'] is True,
        'stable virtualized inventory transition required monotonic DOM growth',
    )

    pure_unmount_measurement = manual._notification_continuation_measurement(
        without_category_controls(inventory_snapshot()),
        manual._CONTINUATION_KEY.fullmatch(virtualized_key),
    )
    require(
        pure_unmount_measurement['raw_notification_inventory_changed'] is True
        and pure_unmount_measurement[
            'raw_notification_inventory_novelty_exact'
        ] is False
        and pure_unmount_measurement['postcondition_matched'] is False
        and 'raw_inventory_novelty'
        in pure_unmount_measurement['failed_components'],
        'pure virtualized unmount satisfied continuation novelty',
    )

    reordered = expanded_snapshot()
    reordered_root = next(
        item for item in reordered.unknown if item.role == 'article'
    ).atspi_obj.get_parent()
    reordered_root.children.reverse()
    reordered_measurement = manual._notification_continuation_measurement(
        reordered,
        manual._CONTINUATION_KEY.fullmatch(virtualized_key),
    )
    require(
        reordered_measurement['raw_notification_inventory_changed'] is True
        and reordered_measurement['raw_notification_inventory_novelty_exact']
        is False
        and reordered_measurement['postcondition_matched'] is False,
        'pure inventory reorder satisfied continuation novelty',
    )

    invalid_candidate = expanded_snapshot()
    invalid_candidate_link = next(
        item
        for item in invalid_candidate.unknown
        if item.role == 'link' and item.name.startswith('Unread notification.')
    )
    invalid_candidate_link.atspi_obj.uri = 'https://www.linkedin.com/feed/'
    invalid_candidate_measurement = manual._notification_continuation_measurement(
        invalid_candidate,
        manual._CONTINUATION_KEY.fullmatch(continuation_key),
    )
    require(
        invalid_candidate_measurement['raw_stream_projection_exact'] is True
        and invalid_candidate_measurement['candidate_projection_exact'] is False
        and invalid_candidate_measurement['postcondition_matched'] is False
        and 'candidate_projection'
        in invalid_candidate_measurement['failed_components'],
        'inexact candidate projection satisfied continuation',
    )

    wrong_route = expanded_snapshot()
    wrong_route.url = 'https://www.linkedin.com/notifications/?filter=mentions'
    route_measurement = manual._notification_continuation_measurement(
        wrong_route,
        manual._CONTINUATION_KEY.fullmatch(continuation_key),
    )
    require(
        route_measurement['route_exact'] is False
        and route_measurement['category_exact'] is True
        and route_measurement['postcondition_matched'] is False,
        'non-exact Notifications route satisfied continuation',
    )

    wrong_category = expanded_snapshot()
    for item in wrong_category.unknown:
        if item.role != 'radio button':
            continue
        item.states = (
            ['checked', 'selected'] if item.name == 'Jobs' else []
        )
    category_measurement = manual._notification_continuation_measurement(
        wrong_category,
        manual._CONTINUATION_KEY.fullmatch(continuation_key),
    )
    require(
        category_measurement['route_exact'] is True
        and category_measurement['category_exact'] is False
        and category_measurement['postcondition_matched'] is True
        and 'category' not in category_measurement['failed_components'],
        'current viewport category state overrode prior category authority',
    )

    original_build_snapshot = manual.build_snapshot
    manual.build_snapshot = lambda _platform: (None, None, after)
    try:
        _snapshot, barrier = manual.stable_post_action_observation(
            continuation_key,
            'activate',
            time.monotonic() + 2,
        )
    finally:
        manual.build_snapshot = original_build_snapshot
    require(barrier['result'] == 'PASS', 'exact continuation barrier did not pass')
    required_sample_fields = {
        'route_exact',
        'category_exact',
        'prior_raw_notification_count',
        'observed_raw_notification_count',
        'raw_notification_count_grew',
        'prior_raw_notification_prefix',
        'observed_raw_notification_prefix',
        'raw_notification_prefix_exact',
        'observed_raw_notification_inventory_digest',
        'raw_notification_inventory_changed',
        'observed_novel_notification_identity_count',
        'observed_novel_notification_identity_digests',
        'raw_notification_inventory_novelty_exact',
        'observed_candidate_count',
        'candidate_projection_exact',
    }
    require(
        len(barrier['samples']) == 2
        and all(required_sample_fields <= set(sample) for sample in barrier['samples']),
        'continuation samples omitted componentwise evidence',
    )
    require(
        all(
            sample['observed_raw_notification_count'] == 4
            and sample['observed_candidate_count'] == 1
            and sample['raw_notification_prefix_exact'] is True
            and sample['raw_notification_inventory_changed'] is True
            and sample['raw_notification_inventory_novelty_exact'] is True
            for sample in barrier['samples']
        ),
        'stable samples did not preserve raw/candidate separation',
    )

    original_build_snapshot = manual.build_snapshot
    manual.build_snapshot = lambda _platform: (None, None, virtualized_after)
    try:
        _snapshot, virtualized_barrier = manual.stable_post_action_observation(
            virtualized_key,
            'activate',
            time.monotonic() + 2,
        )
    finally:
        manual.build_snapshot = original_build_snapshot
    require(
        virtualized_barrier['result'] == 'PASS'
        and len(virtualized_barrier['samples']) == 2
        and all(
            sample['observed_raw_notification_count'] == 3
            and sample['raw_notification_count_grew'] is False
            and sample['raw_notification_inventory_changed'] is True
            and sample['raw_notification_inventory_novelty_exact'] is True
            and sample['candidate_projection_exact'] is True
            for sample in virtualized_barrier['samples']
        ),
        'stable virtualized post-action state did not pass the barrier',
    )

    original_build_snapshot = manual.build_snapshot
    manual.build_snapshot = lambda _platform: (None, None, before)
    try:
        _snapshot, timeout = manual.stable_post_action_observation(
            continuation_key,
            'activate',
            time.monotonic() + 0.05,
        )
    finally:
        manual.build_snapshot = original_build_snapshot
    require(
        timeout['result'] == 'TIMEOUT'
        and timeout['next_mutation_authorized'] is False
        and timeout['samples']
        and required_sample_fields <= set(timeout['samples'][0])
        and timeout['samples'][0]['raw_notification_inventory_novelty_exact']
        is False
        and 'raw_inventory_novelty'
        in timeout['samples'][0]['failed_components']
        and 'verification_error' in timeout['samples'][0],
        'continuation failure did not preserve exact sample evidence',
    )

    print('linkedin full notification-stream continuation: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
