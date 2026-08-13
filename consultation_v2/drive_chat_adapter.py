"""One-process adapters for the supervised ``drive_chat`` lane.

Import this module only after the caller has bound ``DISPLAY`` and the AT-SPI
bus.  The caller continues to own display locking and JSON serialization.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from .runtime import ConsultationRuntime
from .types import ConsultationRequest, ConsultationResult
from .yaml_contract import CHAT_PLATFORMS


_SCROLL_CLICKS = 14
_SCROLL_ROUNDS = 3
_SCROLL_SETTLE_SECONDS = 0.5


class DriveChatAdapterError(RuntimeError):
    pass


def _driver(platform: str):
    if platform not in CHAT_PLATFORMS:
        raise DriveChatAdapterError(f'Unsupported chat platform: {platform!r}')
    module = importlib.import_module(f'.platforms.{platform}.driver', package='consultation_v2')
    candidates = [
        candidate
        for candidate in vars(module).values()
        if (
            isinstance(candidate, type)
            and candidate.__module__ == module.__name__
            and candidate.__name__.endswith('ConsultationDriver')
            and getattr(candidate, 'platform', None) == platform
        )
    ]
    if len(candidates) != 1:
        raise DriveChatAdapterError(
            f'{platform}: expected one built consultation driver, found {len(candidates)}'
        )
    return candidates[0]()


def _failure(platform: str, operation: str, result: ConsultationResult) -> DriveChatAdapterError:
    failed_steps = [step for step in result.steps if not step.success]
    detail = failed_steps[-1].message if failed_steps else 'driver returned false without evidence'
    return DriveChatAdapterError(f'{platform}: {operation} failed: {detail}')


def _scroll(runtime: ConsultationRuntime) -> None:
    if not runtime.scroll_document_to_bottom(
        clicks=_SCROLL_CLICKS,
        rounds=_SCROLL_ROUNDS,
        settle=_SCROLL_SETTLE_SECONDS,
    ):
        raise DriveChatAdapterError(
            f'{runtime.platform}: scroll_document_to_bottom returned false'
        )


def scroll(platform: str) -> dict[str, Any]:
    runtime = ConsultationRuntime(platform)
    _scroll(runtime)
    return {
        'platform': platform,
        'scrolled': True,
        'clicks': _SCROLL_CLICKS,
        'rounds': _SCROLL_ROUNDS,
        'settle_seconds': _SCROLL_SETTLE_SECONDS,
    }


def extract(platform: str, prompt: str = '') -> dict[str, Any]:
    driver = _driver(platform)
    request = ConsultationRequest(platform=platform, message=prompt)
    result = driver.result(request)
    result.session_url_after = driver.runtime.current_url()
    if not driver.extract_primary(request, result):
        raise _failure(platform, 'extract_primary', result)
    if not driver.extract_additional(request, result):
        raise _failure(platform, 'extract_additional', result)
    return {
        'platform': platform,
        'extracted': True,
        'response_text': result.response_text,
        'artifacts': [artifact.serializable() for artifact in result.extractions],
        'steps': [step.serializable() for step in result.steps],
        'session_url': result.session_url_after,
    }


def attach(platform: str, path: str) -> dict[str, Any]:
    attachment = Path(path).expanduser().resolve()
    if not attachment.is_file():
        raise DriveChatAdapterError(f'{platform}: attachment is not a file: {attachment}')
    driver = _driver(platform)
    request = ConsultationRequest(
        platform=platform,
        message='',
        attachments=[str(attachment)],
        attach_identity=False,
    )
    result = driver.result(request)
    if not driver.attach_files(request, result):
        raise _failure(platform, 'attach', result)
    return {
        'platform': platform,
        'attached': True,
        'path': str(attachment),
        'steps': [step.serializable() for step in result.steps],
    }


__all__ = ['DriveChatAdapterError', 'attach', 'extract', 'scroll']
