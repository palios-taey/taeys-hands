"""Native file-dialog snapshot is Claude-YAML owned and fail-closed."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from consultation_v2 import native_file_dialog as native
from consultation_v2.native_file_dialog import NativeDialogError
from consultation_v2.yaml_contract import clear_yaml_cache, load_platform_yaml


class _Node:
    def __init__(self, role: str, name: str = '', children=None, nicks=None, text=''):
        self._role = role
        self._name = name
        self._children = list(children or [])
        self._nicks = list(nicks or ['showing', 'visible', 'enabled'])
        self._text = text

    def get_role_name(self):
        return self._role

    def get_name(self):
        return self._name

    def get_child_count(self):
        return len(self._children)

    def get_child_at_index(self, index):
        return self._children[index]

    def get_state_set(self):
        return SimpleNamespace(nicks=list(self._nicks))

    def get_text_iface(self):
        return SimpleNamespace(get_text=lambda start, end: self._text)

    def clear_cache_single(self):
        return None


def _chooser_root(children):
    return _Node(
        'file chooser',
        'File Upload - New chat - Claude — Mozilla Firefox',
        children,
    )


def _initial_tree():
    widget = _Node('file chooser', 'File Chooser Widget')
    root = _chooser_root([widget])
    frame = _Node('frame', 'Claude — Mozilla Firefox')
    return _Node('application', 'Firefox', [frame, root])


def _post_ctrl_l_tree():
    entry = _Node(
        'text',
        '',
        nicks=['showing', 'visible', 'focused', 'editable', 'enabled'],
        text='/tmp/example.md',
    )
    layer = _Node('filler', 'Location Layer', [entry])
    widget = _Node('file chooser', 'File Chooser Widget', [_Node('filler', 'pad', [layer])])
    root = _chooser_root([widget])
    frame = _Node('frame', 'Claude — Mozilla Firefox')
    return _Node('application', 'Firefox', [frame, root])


class NativeFileDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clear_yaml_cache()

    def test_spec_comes_from_claude_yaml_not_shared_file(self):
        spec = native.load_native_file_dialog_spec('claude')
        self.assertEqual(spec['root']['uniqueness'], 'exactly_one_application_child')
        self.assertFalse(spec['mapped']['location_layer']['required'])
        self.assertFalse(spec['mapped']['location_entry']['required'])
        self.assertFalse(Path('consultation_v2/native_file_dialog.yaml').exists())
        cfg = load_platform_yaml('claude')
        self.assertIn('native_file_dialog', cfg)

    def test_other_platform_without_section_fails(self):
        with self.assertRaisesRegex(NativeDialogError, 'does not declare native_file_dialog'):
            native.load_native_file_dialog_spec('chatgpt')

    def test_initial_chooser_without_location_succeeds(self):
        app = _initial_tree()
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            snapshot = native.build_native_dialog_snapshot('claude')
        contract = native.snapshot_contract(snapshot, display=':3')
        self.assertEqual(set(contract['mapped']), {'file_chooser_root', 'file_chooser_widget'})
        self.assertNotIn('location_layer', contract['mapped'])
        self.assertEqual(len(contract['snapshot_revision']), 64)
        self.assertEqual(contract['refs']['file_chooser_root']['revision'], contract['snapshot_revision'])
        self.assertEqual(contract['refs']['file_chooser_root']['display'], ':3')
        self.assertEqual(contract['refs']['file_chooser_root']['surface'], 'native_dialog')
        self.assertNotIn('x11', str(contract).lower())

    def test_post_ctrl_l_captures_location_text_and_refs(self):
        app = _post_ctrl_l_tree()
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            snapshot = native.build_native_dialog_snapshot('claude')
        contract = native.snapshot_contract(snapshot, display=':3')
        self.assertEqual(contract['mapped']['location_layer']['name'], 'Location Layer')
        self.assertEqual(contract['mapped']['location_entry']['text'], '/tmp/example.md')
        self.assertTrue(str(contract['mapped']['location_entry']['tree_path']).startswith('APP/1/'))
        self.assertTrue(all(len(ref['revision']) == 64 for ref in contract['refs'].values()))

    def test_zero_choosers_fail(self):
        app = _Node('application', 'Firefox', [_Node('frame', 'Claude — Mozilla Firefox')])
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            with self.assertRaisesRegex(NativeDialogError, 'no application-child file chooser'):
                native.build_native_dialog_snapshot('claude')

    def test_ambiguous_choosers_fail(self):
        app = _Node('application', 'Firefox', [
            _chooser_root([]),
            _Node('file chooser', 'File Upload - B'),
        ])
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            with self.assertRaisesRegex(NativeDialogError, '2 application-child file choosers'):
                native.build_native_dialog_snapshot('claude')

    def test_none_child_fails_closed(self):
        app = _Node('application', 'Firefox', [_Node('frame', 'x'), None])
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            with self.assertRaisesRegex(NativeDialogError, 'None child'):
                native.build_native_dialog_snapshot('claude')

    def test_clear_cache_failure_fails_closed(self):
        app = _initial_tree()

        def boom():
            raise RuntimeError('cache wedged')

        app.clear_cache_single = boom
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            with self.assertRaisesRegex(NativeDialogError, 'clear_cache_single failed'):
                native.build_native_dialog_snapshot('claude')

    def test_missing_required_states_fail(self):
        widget = _Node('file chooser', 'File Chooser Widget', nicks=['showing'])
        root = _chooser_root([widget])
        app = _Node('application', 'Firefox', [_Node('frame', 'Claude'), root])
        with mock.patch.object(native.platform_routing, 'find_firefox_for_platform', return_value=app):
            with self.assertRaisesRegex(NativeDialogError, 'missing required_states'):
                native.build_native_dialog_snapshot('claude')


if __name__ == '__main__':
    raise SystemExit(unittest.main())
