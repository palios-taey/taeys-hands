from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from consultation_v2.drivers.base import BaseConsultationDriver
from consultation_v2.drivers.chatgpt import ChatGPTConsultationDriver
from consultation_v2.drivers.gemini import GeminiConsultationDriver
from consultation_v2.drivers.perplexity import PerplexityConsultationDriver


ROOT = Path(__file__).resolve().parents[1]


class FakeElement:
    def __init__(self, name: str, role: str) -> None:
        self.name = name
        self.role = role


class FakeSnapshot:
    def __init__(self, elements: list[FakeElement] | None = None, present: set[str] | None = None) -> None:
        self.mapped = {'main': list(elements or [])}
        self.unknown: list[FakeElement] = []
        self.sidebar: list[FakeElement] = []
        self._present = set(present or set())

    def has(self, key: str) -> bool:
        return key in self._present

    def serializable(self) -> dict[str, object]:
        return {
            'present': sorted(self._present),
            'elements': [
                {'name': element.name, 'role': element.role}
                for element in self.mapped['main']
            ],
        }


class FakeRuntime:
    def __init__(self, snapshots: list[FakeSnapshot]) -> None:
        self.snapshots = snapshots
        self.index = 0

    def snapshot(self) -> FakeSnapshot:
        return self.snapshots[self.index]

    def wait_until(self, poll, timeout: float, interval: float) -> bool:  # noqa: ANN001, ARG002, ARG003
        for idx in range(len(self.snapshots)):
            self.index = idx
            if poll():
                return True
        self.index = max(0, len(self.snapshots) - 1)
        return False


class FakeResult:
    def __init__(self) -> None:
        self.steps: list[tuple[str, bool, str, dict[str, object]]] = []

    def add_step(self, name: str, verified: bool, message: str, **payload: object) -> None:
        self.steps.append((name, verified, message, payload))


def _load_platform(platform: str) -> dict:
    return yaml.safe_load((ROOT / 'consultation_v2' / 'platforms' / f'{platform}.yaml').read_text())


def test_file_chip_matches_truncated_taey_package_prefix() -> None:
    driver = SimpleNamespace(cfg={
        'validation': {
            'attach_success': {
                'file_chip': {
                    'roles': ['push button'],
                },
            },
        },
    })

    snapshot = FakeSnapshot(
        elements=[
            FakeElement('taey_package_perplexity_...md 49.8 KB', 'push button'),
        ],
    )

    assert BaseConsultationDriver.validation_passes(
        driver,
        snapshot,
        'attach_success',
        filename='/tmp/taey_package_perplexity_1760000000.md',
    )


@pytest.mark.parametrize(
    ('driver_cls', 'platform'),
    [
        (ChatGPTConsultationDriver, 'chatgpt'),
        (GeminiConsultationDriver, 'gemini'),
        (PerplexityConsultationDriver, 'perplexity'),
    ],
)
def test_monitor_generation_completes_without_copy_button(driver_cls, platform: str) -> None:
    driver = driver_cls.__new__(driver_cls)
    driver.cfg = _load_platform(platform)
    driver.runtime = FakeRuntime([
        FakeSnapshot(present={'stop_button'}),
        FakeSnapshot(present=set()),
    ])

    result = FakeResult()
    request = SimpleNamespace(timeout=3)

    assert driver.monitor_generation(request, result) is True
    assert result.steps[-1][0] == 'monitor'
    assert result.steps[-1][1] is True


def test_gemini_and_perplexity_attach_success_use_file_chip() -> None:
    for platform in ('gemini', 'perplexity'):
        validation = _load_platform(platform)['validation']['attach_success']
        assert validation == {'file_chip': {'roles': ['push button']}}


def test_response_complete_is_stop_absent_only() -> None:
    for platform in ('chatgpt', 'gemini', 'perplexity'):
        validation = _load_platform(platform)['validation']['response_complete']
        assert validation == {'stop_absent': 'stop_button'}
