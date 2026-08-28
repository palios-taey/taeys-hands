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


def continuation_projection(snapshot):
    augmented = manual.augment_snapshot(snapshot)
    keys = [
        key
        for key, matches in augmented.mapped.items()
        if key.startswith(manual.NOTIFICATIONS_CONTINUATION_PREFIX) and matches
    ]
    require(keys == [manual.NOTIFICATIONS_CONTINUATION], 'continuation key is not stable')
    targets = list(augmented.mapped[manual.NOTIFICATIONS_CONTINUATION])
    require(len(targets) == 1, 'continuation target is not exact')
    return augmented, targets[0]


def authorize_runtime(snapshot, ref_value='atspi3:validator-current-ref'):
    augmented, target = continuation_projection(snapshot)
    context = {
        **dict(target.raw),
        'element': manual.NOTIFICATIONS_CONTINUATION,
        'ref': ref_value,
    }
    declared = manual.element_operation(
        manual.NOTIFICATIONS_CONTINUATION,
        list(target.states),
        context,
    )
    require(
        declared['method'] == 'activate'
        and declared['allowed_now'] == ['activate']
        and declared['postcondition']['kind']
        == 'notification_stream_stable_novelty',
        'runtime continuation was not exactly authorized',
    )
    return augmented, target, declared


def require_refused(callback, message):
    try:
        callback()
    except ValueError:
        return
    raise AssertionError(message)


def main() -> int:
    before = with_controls(inventory_snapshot())
    before_augmented, before_target = continuation_projection(before)
    after = without_category_controls(expanded_snapshot())
    after_augmented, after_target = continuation_projection(after)
    require(
        before_target.key == after_target.key
        and before_target.description == after_target.description
        and before_target.x is None
        and before_target.y is None
        and after_target.x is None
        and after_target.y is None
        and before_target.raw['notification_stream_uri_digests']
        != after_target.raw['notification_stream_uri_digests'],
        'volatile inventory remained in the semantic action projection',
    )
    require(
        not any(
            key.startswith(manual.NOTIFICATION_CANDIDATE_PREFIX)
            for key in before_augmented.mapped
        )
        and not any(
            key.startswith(manual.NOTIFICATION_CANDIDATE_PREFIX)
            for key in after_augmented.mapped
        ),
        'candidate mappings remained live while continuation was mandatory',
    )
    before_declared = manual.element_operation(
        manual.NOTIFICATIONS_CONTINUATION,
        list(before_target.states),
        dict(before_target.raw),
    )
    after_declared = manual.element_operation(
        manual.NOTIFICATIONS_CONTINUATION,
        list(after_target.states),
        dict(after_target.raw),
    )
    require(
        before_declared == after_declared
        and manual._CONTINUATION_PRE_ACTION.get() is None,
        'compile-time card authority depended on volatile inventory',
    )

    partial_runtime = {
        **dict(before_target.raw),
        'element': manual.NOTIFICATIONS_CONTINUATION,
    }
    require_refused(
        lambda: manual.element_operation(
            manual.NOTIFICATIONS_CONTINUATION,
            list(before_target.states),
            partial_runtime,
        ),
        'continuation froze before exact target/ref re-resolution',
    )
    require(
        manual._CONTINUATION_PRE_ACTION.get() is None,
        'failed partial runtime context leaked authority',
    )

    authorize_runtime(before)
    require_refused(
        lambda: authorize_runtime(before, 'atspi3:second-ref'),
        'a second live pre-action context replaced the first',
    )
    manual._consume_notification_continuation_context(
        manual.NOTIFICATIONS_CONTINUATION,
        'activate',
    )
    require(
        manual._CONTINUATION_PRE_ACTION.get() is None,
        'explicit context consume did not clear authority',
    )

    authorize_runtime(before)
    receipt = manual.verify_post_action(
        after,
        manual.NOTIFICATIONS_CONTINUATION,
        'activate',
    )
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
        'exact noncandidate inventory novelty did not satisfy continuation',
    )
    require(
        manual._CONTINUATION_PRE_ACTION.get() is None,
        'successful continuation did not clear one-shot context',
    )
    require_refused(
        lambda: manual.verify_post_action(
            after,
            manual.NOTIFICATIONS_CONTINUATION,
            'activate',
        ),
        'one-shot continuation context was reusable',
    )

    authorize_runtime(before)
    require_refused(
        lambda: manual._consume_notification_continuation_context(
            'notifications_show_more_wrong',
            'activate',
        ),
        'mismatched continuation element retained authority',
    )
    require(manual._CONTINUATION_PRE_ACTION.get() is None, 'element mismatch leaked context')
    authorize_runtime(before)
    require_refused(
        lambda: manual._consume_notification_continuation_context(
            manual.NOTIFICATIONS_CONTINUATION,
            'mapped_pointer_activate',
        ),
        'mismatched continuation operation retained authority',
    )
    require(manual._CONTINUATION_PRE_ACTION.get() is None, 'operation mismatch leaked context')

    no_controls = without_category_controls(with_controls(inventory_snapshot()))
    no_controls_augmented, _no_controls_target = continuation_projection(no_controls)
    require(
        not any(
            key.startswith(manual.NOTIFICATION_CANDIDATE_PREFIX)
            for key in no_controls_augmented.mapped
        ),
        'candidate keys bypassed receipt-bound All-category authority',
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
    require_refused(
        lambda: manual.augment_snapshot(obsolete_one_link),
        'continuation accepted the obsolete one-link notification fixture',
    )

    changed_text = expanded_snapshot()
    read_link = next(
        item
        for item in changed_text.unknown
        if item.role == 'link' and item.name == 'Bob posted another exact update.'
    )
    read_link.name = 'A changed accessible notification sentence.'
    read_link.atspi_obj.name = read_link.name
    authorize_runtime(before)
    text_receipt = manual.verify_post_action(
        changed_text,
        manual.NOTIFICATIONS_CONTINUATION,
        'activate',
    )
    require(
        text_receipt['raw_notification_prefix_exact'] is True,
        'mounted-stream identity is brittle to notification text',
    )

    virtualized_before = without_category_controls(expanded_snapshot())
    virtualized_after = virtualized_changed_snapshot()
    authorize_runtime(virtualized_before)
    virtualized_receipt = manual.verify_post_action(
        virtualized_after,
        manual.NOTIFICATIONS_CONTINUATION,
        'activate',
    )
    require(
        virtualized_receipt['prior_raw_notification_count'] == 4
        and virtualized_receipt['observed_raw_notification_count'] == 3
        and virtualized_receipt['raw_notification_count_grew'] is False
        and virtualized_receipt['raw_notification_prefix_exact'] is False
        and virtualized_receipt['raw_notification_inventory_changed'] is True
        and virtualized_receipt['raw_notification_inventory_novelty_exact'] is True
        and virtualized_receipt['observed_novel_notification_identity_count'] == 1
        and virtualized_receipt['candidate_projection_exact'] is True,
        'immediate pre-action inventory did not govern virtualized novelty',
    )

    negative_snapshots = []
    negative_snapshots.append((
        without_category_controls(inventory_snapshot()),
        'pure virtualized unmount satisfied continuation novelty',
    ))
    reordered = expanded_snapshot()
    reordered_root = next(
        item for item in reordered.unknown if item.role == 'article'
    ).atspi_obj.get_parent()
    reordered_root.children.reverse()
    negative_snapshots.append((reordered, 'pure inventory reorder satisfied novelty'))
    negative_snapshots.append((virtualized_before, 'unchanged inventory satisfied novelty'))
    for observed, message in negative_snapshots:
        authorize_runtime(virtualized_before)
        require_refused(
            lambda observed=observed: manual.verify_post_action(
                observed,
                manual.NOTIFICATIONS_CONTINUATION,
                'activate',
            ),
            message,
        )
        require(
            manual._CONTINUATION_PRE_ACTION.get() is None,
            'failed novelty check leaked one-shot context',
        )

    invalid_candidate = expanded_snapshot()
    invalid_candidate_link = next(
        item
        for item in invalid_candidate.unknown
        if item.role == 'link' and item.name.startswith('Unread notification.')
    )
    invalid_candidate_link.atspi_obj.uri = 'https://www.linkedin.com/feed/'
    authorize_runtime(before)
    require_refused(
        lambda: manual.verify_post_action(
            invalid_candidate,
            manual.NOTIFICATIONS_CONTINUATION,
            'activate',
        ),
        'inexact candidate projection satisfied continuation',
    )

    wrong_route = expanded_snapshot()
    wrong_route.url = 'https://www.linkedin.com/notifications/?filter=mentions'
    authorize_runtime(before)
    require_refused(
        lambda: manual.verify_post_action(
            wrong_route,
            manual.NOTIFICATIONS_CONTINUATION,
            'activate',
        ),
        'non-exact Notifications route satisfied continuation',
    )

    wrong_category = expanded_snapshot()
    for item in wrong_category.unknown:
        if item.role != 'radio button':
            continue
        item.states = ['checked', 'selected'] if item.name == 'Jobs' else []
    authorize_runtime(before)
    category_receipt = manual.verify_post_action(
        wrong_category,
        manual.NOTIFICATIONS_CONTINUATION,
        'activate',
    )
    require(
        category_receipt['category_exact'] is False
        and category_receipt['postcondition_matched'] is True
        and 'category' not in category_receipt['failed_components'],
        'live offscreen category state replaced receipt-bound authority',
    )

    original_build_snapshot = manual.build_snapshot
    authorize_runtime(before)
    manual.build_snapshot = lambda _platform: (None, None, after)
    try:
        _snapshot, barrier = manual.stable_post_action_observation(
            manual.NOTIFICATIONS_CONTINUATION,
            'activate',
            time.monotonic() + 2,
        )
    finally:
        manual.build_snapshot = original_build_snapshot
    required_sample_fields = {
        'candidate_projection_exact',
        'observed_candidate_count',
        'observed_novel_notification_identity_count',
        'observed_novel_notification_identity_digests',
        'observed_raw_notification_count',
        'pre_action_candidate_count',
        'pre_action_context_sha256',
        'pre_action_ref_sha256',
        'prior_raw_notification_count',
        'raw_notification_inventory_novelty_exact',
        'route_exact',
    }
    require(
        barrier['result'] == 'PASS'
        and len(barrier['samples']) == 2
        and all(required_sample_fields <= set(sample) for sample in barrier['samples'])
        and len({sample['pre_action_context_sha256'] for sample in barrier['samples']}) == 1,
        'stable continuation barrier omitted exact one-shot evidence',
    )
    require_refused(
        lambda: manual.stable_post_action_observation(
            manual.NOTIFICATIONS_CONTINUATION,
            'activate',
            time.monotonic() + 0.1,
        ),
        'stable barrier reused a consumed context',
    )

    authorize_runtime(before)
    manual.build_snapshot = lambda _platform: (None, None, before)
    try:
        _snapshot, timeout = manual.stable_post_action_observation(
            manual.NOTIFICATIONS_CONTINUATION,
            'activate',
            time.monotonic() + 0.05,
        )
    finally:
        manual.build_snapshot = original_build_snapshot
    require(
        timeout['result'] == 'TIMEOUT'
        and timeout['next_mutation_authorized'] is False
        and timeout['samples']
        and timeout['samples'][0]['raw_notification_inventory_novelty_exact'] is False
        and 'raw_inventory_novelty' in timeout['samples'][0]['failed_components']
        and manual._CONTINUATION_PRE_ACTION.get() is None,
        'unchanged timeout retained mutation authority or context',
    )

    print('linkedin one-shot continuation inventory: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
