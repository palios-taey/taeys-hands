"""Focused tests for menu-item collection."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeExtents:
    def __init__(self, x=10, y=10, width=20, height=20):
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class _FakeComponent:
    def __init__(self, extents=None):
        self._extents = extents or _FakeExtents()

    def get_extents(self, _coord_type):
        return self._extents


class _FakeStateSet:
    def __init__(self, states):
        self._states = set(states)

    def contains(self, state):
        return state in self._states


class _FakeNode:
    def __init__(self, role, name='', children=None, states=None, y=10):
        self._role = role
        self._name = name
        self._children = children or []
        self._state_set = _FakeStateSet(states or set())
        self._component = _FakeComponent(_FakeExtents(y=y))

    def get_role_name(self):
        return self._role

    def get_name(self):
        return self._name

    def get_state_set(self):
        return self._state_set

    def get_component_iface(self):
        return self._component

    def get_child_count(self):
        return len(self._children)

    def get_child_at_index(self, idx):
        return self._children[idx]


def test_find_menu_items_collects_sibling_containers_and_dedupes():
    from core.tree import Atspi, find_menu_items

    showing = {Atspi.StateType.SHOWING}
    first_panel = _FakeNode(
        'panel',
        children=[_FakeNode('option', 'Deep Research', states=showing, y=20)],
        states=showing,
        y=10,
    )
    second_panel = _FakeNode(
        'panel',
        children=[
            _FakeNode('option', 'Deep Research', states=showing, y=30),
            _FakeNode('option', 'Normal', states=showing, y=40),
        ],
        states=showing,
        y=15,
    )
    root = _FakeNode('document frame', children=[first_panel, second_panel], states=showing)

    items = find_menu_items(None, root)

    assert [item['name'] for item in items] == ['Deep Research', 'Normal']


def test_find_menu_items_uses_flat_search_across_split_siblings():
    from core.tree import Atspi, find_menu_items

    showing = {Atspi.StateType.SHOWING}
    section = _FakeNode(
        'section',
        children=[_FakeNode('option', 'Deep Research', states=showing, y=20)],
        states=showing,
        y=10,
    )
    panel = _FakeNode(
        'panel',
        children=[_FakeNode('option', 'Normal', states=showing, y=40)],
        states=showing,
        y=15,
    )
    root = _FakeNode('document frame', children=[section, panel], states=showing)

    items = find_menu_items(None, root)

    assert [item['name'] for item in items] == ['Deep Research', 'Normal']
