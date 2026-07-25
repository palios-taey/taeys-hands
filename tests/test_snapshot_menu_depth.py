from consultation_v2 import snapshot
from consultation_v2.types import Snapshot


def test_menu_snapshot_max_depth_defaults_to_find_elements_default():
    assert snapshot._menu_snapshot_max_depth({}) == 25


def test_menu_snapshot_max_depth_rejects_non_integer():
    try:
        snapshot._menu_snapshot_max_depth({'menu_snapshot_max_depth': '30'})
    except ValueError as exc:
        assert 'tree.menu_snapshot_max_depth must be an integer' in str(exc)
    else:
        raise AssertionError('expected non-integer menu depth to fail')


def test_app_root_snapshot_passes_configured_menu_depth(monkeypatch):
    calls = []
    firefox = object()

    monkeypatch.setattr(
        snapshot,
        'load_platform_yaml',
        lambda _platform: {'tree': {'menu_snapshot_max_depth': 30}},
    )
    monkeypatch.setattr(snapshot, '_load_firefox_chrome_filter', lambda: {})
    monkeypatch.setattr(
        snapshot.platform_routing,
        'find_firefox_for_platform',
        lambda _platform: firefox,
    )
    monkeypatch.setattr(
        snapshot,
        'find_elements',
        lambda scope, **kwargs: calls.append((scope, kwargs)) or [],
    )
    monkeypatch.setattr(
        snapshot,
        '_classify_elements',
        lambda platform, elements, **_kwargs: Snapshot(platform=platform, url=None),
    )

    snapshot.build_app_root_snapshot('claude')

    assert calls == [(firefox, {'max_depth': 30})]


def test_menu_snapshot_passes_configured_menu_depth(monkeypatch):
    calls = []

    class FakeAccessible:
        def clear_cache_single(self):
            pass

    firefox = FakeAccessible()
    doc = FakeAccessible()

    monkeypatch.setattr(
        snapshot,
        'load_platform_yaml',
        lambda _platform: {'tree': {'menu_snapshot_max_depth': 30}},
    )
    monkeypatch.setattr(snapshot, '_load_firefox_chrome_filter', lambda: {})
    monkeypatch.setattr(
        snapshot.platform_routing,
        'find_firefox_for_platform',
        lambda _platform: firefox,
    )
    monkeypatch.setattr(
        snapshot.platform_routing,
        'get_platform_document',
        lambda _firefox, _platform: doc,
    )
    monkeypatch.setattr(snapshot, 'find_menu_items', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        snapshot,
        'find_elements',
        lambda scope, **kwargs: calls.append((scope, kwargs)) or [],
    )
    monkeypatch.setattr(snapshot.atspi, 'get_document_url', lambda _doc: 'https://example.test/')
    monkeypatch.setattr(
        snapshot,
        '_classify_elements',
        lambda platform, elements, **_kwargs: Snapshot(platform=platform, url=None),
    )

    snapshot.build_menu_snapshot('claude')

    assert calls == [(firefox, {'max_depth': 30})]
