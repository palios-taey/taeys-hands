import hashlib

import pytest

from consultation_v2.cli import _request_record, _resolve_identity_for_dry_run
from consultation_v2.identity import IdentityError
from consultation_v2.platforms.perplexity.driver import PerplexityConsultationDriver
from consultation_v2.types import ConsultationRequest, ElementRef, Snapshot


class FakeRuntime:
    def __init__(self, snapshots):
        self._snapshots = list(snapshots)
        self.pressed = []

    def snapshot(self):
        if len(self._snapshots) > 1:
            return self._snapshots.pop(0)
        return self._snapshots[0]

    def wait_until(self, probe, *, timeout, interval):
        for _ in range(8):
            value = probe()
            if value:
                return value
        return None

    def focus_firefox(self):
        return True

    def press(self, key):
        self.pressed.append(key)
        return True


def _element(key):
    return ElementRef(key=key, name=key, role='push button', x=1, y=1)


def _snapshot(*keys):
    return Snapshot(
        platform='perplexity',
        url='https://www.perplexity.ai/',
        mapped={key: [_element(key)] for key in keys},
        raw_count=len(keys),
    )


def _driver_with_snapshots(*snapshots):
    driver = PerplexityConsultationDriver()
    driver.runtime = FakeRuntime(snapshots)
    return driver


def _result():
    return _driver_with_snapshots(_snapshot('input', 'attach_trigger')).result(
        ConsultationRequest(platform='perplexity', message='hello')
    )


def test_computer_onboarding_dismisses_and_verifies_standard_composer():
    driver = _driver_with_snapshots(
        _snapshot('computer_ready'),
        _snapshot('input', 'attach_trigger'),
    )
    result = _result()

    assert driver._dismiss_computer_onboarding(result) is True

    assert driver.runtime.pressed == ['Escape']
    step = result.steps[-1]
    assert step.step == 'computer_onboarding'
    assert step.success is True
    assert step.evidence['standard_keys'] == ['input', 'attach_trigger']


def test_computer_onboarding_fails_closed_when_standard_composer_does_not_return():
    driver = _driver_with_snapshots(
        _snapshot('computer_ready'),
        _snapshot('computer_ready'),
    )
    result = _result()

    assert driver._dismiss_computer_onboarding(result) is False

    assert driver.runtime.pressed == ['Escape']
    step = result.steps[-1]
    assert step.step == 'computer_onboarding'
    assert step.success is False


def test_skip_identity_attachment_request_allows_zero_attachments_in_dry_run():
    request = ConsultationRequest(
        platform='perplexity',
        message='company research only',
        attach_identity=False,
    )

    resolved, identity = _resolve_identity_for_dry_run(request)

    assert resolved.attachments == []
    assert identity['mode'] == 'identity_attachment_skipped'
    assert identity['package_paths'] == []
    assert _request_record(resolved)['attach_identity'] is False


def test_no_identity_still_requires_a_caller_attachment():
    request = ConsultationRequest(
        platform='perplexity',
        message='caller-only still needs a packet',
        no_identity=True,
    )

    with pytest.raises(IdentityError):
        _resolve_identity_for_dry_run(request)


def test_skip_identity_attachment_changes_only_the_new_request_id_mode():
    default_request = ConsultationRequest(platform='perplexity', message='same prompt')
    skip_request = ConsultationRequest(
        platform='perplexity',
        message='same prompt',
        attach_identity=False,
    )
    seed = (
        f'{default_request.platform}\x1fnew\x1f'
        f'{default_request.prompt_hash()}'
    )

    assert default_request.request_id() == hashlib.sha256(
        seed.encode('utf-8')
    ).hexdigest()[:32]
    assert skip_request.request_id() != default_request.request_id()
