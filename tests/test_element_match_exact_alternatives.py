from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_inspect_match_element_supports_names_any_of() -> None:
    from tools.inspect import _match_element

    assert _match_element(
        {'name': 'Stop answering', 'role': 'push button', 'states': []},
        {'names_any_of': ['Stop answering', 'Stop response'], 'role': 'push button'},
    ) is True
    assert _match_element(
        {'name': 'Stop composing', 'role': 'push button', 'states': []},
        {'names_any_of': ['Stop answering', 'Stop response'], 'role': 'push button'},
    ) is False


def test_attach_match_element_supports_names_any_of() -> None:
    from tools.attach import _match_element

    assert _match_element(
        {'name': 'Stop response', 'role': 'push button', 'states': []},
        {'names_any_of': ['Stop answering', 'Stop response'], 'role': 'push button'},
    ) is True
    assert _match_element(
        {'name': 'Stop streaming soon', 'role': 'push button', 'states': []},
        {'names_any_of': ['Stop answering', 'Stop response'], 'role': 'push button'},
    ) is False
