from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

KNOWN_PLATFORMS = ('chatgpt', 'claude', 'gemini', 'grok', 'perplexity', 'x_twitter', 'grok_x_scout')


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def platforms_dir() -> Path:
    return _repo_root() / 'consultation_v2' / 'platforms'


def platform_yaml_path(platform: str) -> Path:
    if platform not in KNOWN_PLATFORMS:
        raise ValueError(f'Unsupported platform: {platform}')
    return platforms_dir() / f'{platform}.yaml'


@lru_cache(maxsize=None)
def load_platform_yaml(platform: str) -> Dict[str, Any]:
    path = platform_yaml_path(platform)
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text()) or {}
    required = ('platform', 'urls', 'tree', 'workflow', 'validation')
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f'{path.name} missing required keys: {missing}')
    return data


def clear_yaml_cache() -> None:
    load_platform_yaml.cache_clear()


def get_element_spec(platform: str, key: str) -> Dict[str, Any]:
    cfg = load_platform_yaml(platform)
    return dict((cfg.get('tree') or {}).get('element_map', {}).get(key, {}))


def get_workflow(platform: str) -> Dict[str, Any]:
    return dict(load_platform_yaml(platform).get('workflow', {}))


def get_validation(platform: str, key: str | None = None) -> Dict[str, Any]:
    validation = dict(load_platform_yaml(platform).get('validation', {}))
    if key is None:
        return validation
    return dict(validation.get(key, {}))
