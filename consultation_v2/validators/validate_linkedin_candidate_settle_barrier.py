from __future__ import annotations

import time
from types import SimpleNamespace

from consultation_v2.platforms.linkedin import manual


ACTIVITY = '1234567890123456789'
ELEMENT = f'notification_candidate_001_activity_{ACTIVITY}'
EXPECTED_URL = (
    'https://www.linkedin.com/feed/?highlightedUpdateUrn='
    f'urn%3Ali%3Aactivity%3A{ACTIVITY}'
)


def exact_receipt() -> dict[str, object]:
    return {
        'postcondition': 'exact_notification_activity',
        'route_exact': True,
        'activity_exact': True,
        'document_url_exact': True,
        'activity_sources': ['document_url', 'showing_link_uri'],
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_sequence(
    urls: list[str],
    outcomes: list[dict[str, object] | ValueError],
) -> dict[str, object]:
    snapshots = iter(SimpleNamespace(url=url) for url in urls)
    receipts = iter(outcomes)
    original_build_snapshot = manual.build_snapshot
    original_cache_invalidator = manual._invalidate_linkedin_firefox_subtree
    original_verify_post_action = manual.verify_post_action
    manual.build_snapshot = lambda _platform: (None, None, next(snapshots))
    manual._invalidate_linkedin_firefox_subtree = lambda: 'recursive_success'

    def verify(*_args: object, **_kwargs: object) -> dict[str, object]:
        outcome = next(receipts)
        if isinstance(outcome, ValueError):
            raise outcome
        return outcome

    manual.verify_post_action = verify
    try:
        _snapshot, barrier = manual.stable_post_action_observation(
            ELEMENT,
            'activate',
            time.monotonic() + 10,
        )
    finally:
        manual.build_snapshot = original_build_snapshot
        manual._invalidate_linkedin_firefox_subtree = original_cache_invalidator
        manual.verify_post_action = original_verify_post_action
    return barrier


def main() -> int:
    structural_remount = ValueError(
        'LinkedIn notification structural tree path is empty'
    )
    barrier = run_sequence(
        [EXPECTED_URL, EXPECTED_URL, EXPECTED_URL],
        [exact_receipt(), structural_remount, exact_receipt()],
    )
    samples = barrier['samples']
    require(
        barrier['result'] == 'PASS'
        and barrier['stable_cycles_observed'] == 2
        and len(samples) == 3
        and samples[1]['settling_transient'] is True
        and samples[1]['counted_toward_stability'] is False
        and samples[1]['stable_cycles_observed_after_sample'] == 1,
        'expected-activity AT-SPI remount reset the exact candidate streak',
    )

    wrong_url = 'https://www.linkedin.com/notifications/?filter=all'
    barrier = run_sequence(
        [EXPECTED_URL, wrong_url, EXPECTED_URL, EXPECTED_URL],
        [exact_receipt(), structural_remount, exact_receipt(), exact_receipt()],
    )
    samples = barrier['samples']
    require(
        barrier['result'] == 'PASS'
        and len(samples) == 4
        and samples[1]['settling_transient'] is False
        and samples[1]['counted_toward_stability'] is True
        and samples[1]['stable_cycles_observed_after_sample'] == 0,
        'wrong-route structural failure preserved candidate stability authority',
    )

    print('linkedin candidate settle barrier: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
