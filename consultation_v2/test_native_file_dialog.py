"""Native file-dialog snapshot fails closed on zero/ambiguous AT-SPI trees."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from consultation_v2 import native_file_dialog as native
from consultation_v2.native_file_dialog import NativeDialogError


class _Node:
    def __init__(self, role: str, name: str = '', children=None):
        self._role = role
        self._name = name
        self._children = list(children or [])

    def get_role_name(self):
        return self._role

    def get_name(self):
        return self._name

    def get_child_count(self):
        return len(self._children)

    def get_child_at_index(self, index):
        return self._children[index]

    def get_state_set(self):
        return SimpleNamespace(nicks=['showing'])

    def clear_cache_single(self):
        return None


def _dialog_tree():
    entry = _Node('text', '')
    layer = _Node('filler', 'Location Layer', [entry])
    widget = _Node('file chooser', 'File Chooser Widget', [_Node('filler', 'pad', [layer])])
    root = _Node(
        'file chooser',
        'File Upload - New chat - Claude — Mozilla Firefox',
        [widget],
    )
    frame = _Node('frame', 'Claude — Mozilla Firefox')
    app = _Node('application', 'Firefox', [frame, root])
    return app, root


class NativeFileDialogTests(unittest.TestCase):
    def test_yaml_contract_loads(self):
        spec = native.load_native_file_dialog_yaml()
        self.assertEqual(spec['root']['role'], 'file chooser')
        self.assertEqual(spec['root']['uniqueness'], 'exactly_one_application_child')

    def test_zero_choosers_fail(self):
        app = _Node('application', 'Firefox', [_Node('frame', 'Claude — Mozilla Firefox')])
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            with self.assertRaisesRegex(NativeDialogError, 'no application-child file chooser'):
                native.build_native_dialog_snapshot('claude')

    def test_ambiguous_choosers_fail(self):
        chooser = _Node('file chooser', 'File Upload - A')
        app = _Node('application', 'Firefox', [chooser, _Node('file chooser', 'File Upload - B')])
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            with self.assertRaisesRegex(NativeDialogError, '2 application-child file choosers'):
                native.build_native_dialog_snapshot('claude')

    def test_unique_tree_revision_is_stable(self):
        app, _root = _dialog_tree()
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            first = native.build_native_dialog_snapshot('claude')
            second = native.build_native_dialog_snapshot('claude')
        contract = native.snapshot_contract(first)
        self.assertEqual(contract['authority'], 'atspi_tree')
        self.assertEqual(contract['scope'], 'native_dialog')
        self.assertEqual(len(contract['snapshot_revision']), 64)
        self.assertEqual(
            contract['mapped']['file_chooser_root']['tree_path'],
            'APP/1',
        )
        self.assertEqual(
            contract['mapped']['file_chooser_widget']['name'],
            'File Chooser Widget',
        )
        self.assertEqual(contract['mapped']['location_layer']['name'], 'Location Layer')
        self.assertEqual(contract['mapped']['location_entry']['role'], 'text')
        self.assertEqual(native.native_dialog_revision(first), native.native_dialog_revision(second))
        self.assertNotIn('x11', str(contract).lower())
        self.assertNotIn('window_title', str(contract).lower())

    def test_missing_location_layer_fails(self):
        widget = _Node('file chooser', 'File Chooser Widget')
        root = _Node('file chooser', 'File Upload', [widget])
        app = _Node('application', 'Firefox', [root])
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            with self.assertRaisesRegex(NativeDialogError, 'missing location_layer'):
                native.build_native_dialog_snapshot('claude')


if __name__ == '__main__':
    raise SystemExit(unittest.main())
