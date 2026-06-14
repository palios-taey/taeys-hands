from __future__ import annotations

from consultation_v2.snapshot import matches_spec


def test_consultation_v2_snapshot_supports_names_any_of_exact_alternatives() -> None:
    element = {'name': 'Stop answering', 'role': 'push button', 'states': []}
    spec = {'names_any_of': ['Stop streaming', 'Stop answering'], 'role': 'push button'}

    assert matches_spec(element, spec) is True
    assert matches_spec({'name': 'Stop composing', 'role': 'push button', 'states': []}, spec) is False
