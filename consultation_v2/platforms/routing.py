"""Dispatch to package-owned platform routing modules."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType


def _route_module(platform: str) -> ModuleType:
    platform_name = str(platform or '').strip()
    if not platform_name.isidentifier() or platform_name.startswith('_'):
        raise RuntimeError(f'Invalid platform route name: {platform!r}')
    module_name = f'consultation_v2.platforms.{platform_name}.routing'
    parent_module_name = module_name.rsplit('.', 1)[0]
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name in {parent_module_name, module_name}:
            raise RuntimeError(f'No package routing module for platform: {platform_name}') from exc
        raise


def switch_to_platform(platform: str) -> bool:
    return bool(_route_module(platform).switch_to_platform())


def find_firefox_for_platform(platform: str, *, pid: int | None = None):
    return _route_module(platform).find_firefox(pid=pid)


def get_platform_document(firefox, platform: str):
    return _route_module(platform).get_document(firefox)


def platform_url_matches(platform: str, url: str | None) -> bool:
    return bool(_route_module(platform).url_matches(url))
