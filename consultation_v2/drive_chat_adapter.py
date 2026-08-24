"""One-process adapters for the supervised ``drive_chat`` lane.

Import this module only after the caller has bound ``DISPLAY`` and the AT-SPI
bus.  The caller continues to own display locking and JSON serialization.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

from .runtime import ConsultationRuntime
from .types import ConsultationRequest, ConsultationResult
from .yaml_contract import CHAT_PLATFORMS, load_platform_yaml


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


def _frozen_selections(platform: str) -> dict[str, str]:
    cfg = load_platform_yaml(platform)
    workflow = cfg.get('workflow') or {}
    full_consult = workflow.get('full_consult') if isinstance(workflow, dict) else None
    select_mode = full_consult.get('select_mode') if isinstance(full_consult, dict) else None
    if not isinstance(select_mode, list) or not select_mode:
        raise DriveChatAdapterError(
            f'{platform}: workflow.full_consult.select_mode must be a non-empty list'
        )
    selections: dict[str, str] = {}
    for index, item in enumerate(select_mode):
        if not isinstance(item, dict) or set(item) != {'menu', 'option'}:
            raise DriveChatAdapterError(
                f'{platform}: full_consult.select_mode[{index}] must declare exactly menu/option'
            )
        menu = item.get('menu')
        option = item.get('option')
        if not isinstance(menu, str) or not menu or not isinstance(option, str) or not option:
            raise DriveChatAdapterError(
                f'{platform}: full_consult.select_mode[{index}] has an invalid menu/option'
            )
        if menu in selections:
            raise DriveChatAdapterError(
                f'{platform}: full_consult.select_mode repeats menu {menu!r}'
            )
        selections[menu] = option
    return selections


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


def _input_file(path: str, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise DriveChatAdapterError(f'{label} is not a file: {resolved}')
    return resolved


def _write_exclusive(path: str, payload: bytes, label: str) -> tuple[Path, str]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.parent.is_dir():
        raise DriveChatAdapterError(
            f'{label} parent directory does not exist: {resolved.parent}'
        )
    try:
        with resolved.open('xb') as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise DriveChatAdapterError(
            f'{label} already exists; refusing to overwrite: {resolved}'
        ) from exc
    return resolved, hashlib.sha256(payload).hexdigest()


def _planned_output(path: str, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.exists():
        raise DriveChatAdapterError(
            f'{label} already exists; refusing before browser action: {resolved}'
        )
    if not resolved.parent.is_dir():
        raise DriveChatAdapterError(
            f'{label} parent directory does not exist: {resolved.parent}'
        )
    return resolved


def _planned_artifact_directory(output_path: Path) -> Path:
    artifact_directory = output_path.parent / 'output_attachments'
    if artifact_directory.exists():
        if not artifact_directory.is_dir():
            raise DriveChatAdapterError(
                f'output attachment path is not a directory: {artifact_directory}'
            )
        if any(artifact_directory.iterdir()):
            raise DriveChatAdapterError(
                f'output attachment directory is not empty: {artifact_directory}'
            )
    return artifact_directory


def _planned_artifacts(
    artifact_directory: Path,
    result: ConsultationResult,
) -> list[tuple[Path, bytes]]:
    planned: list[tuple[Path, bytes]] = []
    names: set[str] = set()
    for artifact in result.extractions:
        name = str(artifact.name or '').strip()
        if not name or Path(name).name != name or name in {'.', '..'}:
            raise DriveChatAdapterError(f'invalid extracted artifact name: {name!r}')
        if name in names:
            raise DriveChatAdapterError(f'duplicate extracted artifact name: {name!r}')
        content = str(artifact.content or '')
        if not content.strip():
            raise DriveChatAdapterError(f'extracted artifact is empty: {name!r}')
        path = artifact_directory / name
        if path.exists():
            raise DriveChatAdapterError(
                f'extracted artifact already exists; refusing overwrite: {path}'
            )
        names.add(name)
        planned.append((path, content.encode('utf-8')))
    return planned


def consult(
    platform: str,
    *,
    prompt_file: str,
    bundle_a: str,
    bundle_b: str,
    output_file: str,
    receipt_file: str,
    requester: str,
    timeout: int = 5400,
) -> dict[str, Any]:
    prompt_path = _input_file(prompt_file, 'prompt_file')
    attachments = [
        _input_file(bundle_a, 'bundle_a'),
        _input_file(bundle_b, 'bundle_b'),
    ]
    source_paths = {prompt_path, *attachments}
    if len(source_paths) != 3:
        raise DriveChatAdapterError(
            'prompt_file, bundle_a, and bundle_b must be three distinct files'
        )
    output_path = _planned_output(output_file, 'output_file')
    receipt_path = _planned_output(receipt_file, 'receipt_file')
    artifact_directory = _planned_artifact_directory(output_path)
    if output_path == receipt_path or output_path in source_paths or receipt_path in source_paths:
        raise DriveChatAdapterError(
            'output_file and receipt_file must be distinct from each other and all inputs'
        )
    if not requester:
        raise DriveChatAdapterError('requester must be non-empty')
    try:
        prompt = prompt_path.read_text(encoding='utf-8')
    except UnicodeDecodeError as exc:
        raise DriveChatAdapterError('prompt_file must be UTF-8 text') from exc
    if not prompt.strip():
        raise DriveChatAdapterError('prompt_file is empty')

    from consultation_v2.orchestrator import run_consultation

    request = ConsultationRequest(
        platform=platform,
        message=prompt,
        attachments=[str(path) for path in attachments],
        selections=_frozen_selections(platform),
        timeout=timeout,
        store_enabled=False,
        attach_identity=False,
        purpose='frozen_manual_baseline_promotion',
        requester=requester,
    )
    result = run_consultation(request)
    receipt_payload = json.dumps(
        result.serializable(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode('utf-8')
    receipt_path, receipt_sha256 = _write_exclusive(
        str(receipt_path),
        receipt_payload,
        'receipt_file',
    )
    if not result.ok or not result.response_text:
        failed_steps = [step for step in result.steps if not step.success]
        detail = (
            failed_steps[-1].message
            if failed_steps
            else 'consultation returned no deliverable'
        )
        raise DriveChatAdapterError(
            f'{platform}: frozen consultation failed: {detail}; '
            f'receipt={receipt_path} sha256={receipt_sha256}'
        )

    response_payload = result.response_text.encode('utf-8')
    planned_artifacts = _planned_artifacts(artifact_directory, result)
    for artifact_path, artifact_payload in planned_artifacts:
        if artifact_payload == response_payload:
            raise DriveChatAdapterError(
                f'extracted artifact duplicates the assistant response: {artifact_path.name!r}'
            )

    response_path, response_sha256 = _write_exclusive(
        str(output_path),
        response_payload,
        'output_file',
    )
    artifact_records: list[dict[str, Any]] = []
    if planned_artifacts:
        artifact_directory.mkdir(mode=0o700, exist_ok=True)
        for artifact_path, artifact_payload in planned_artifacts:
            materialized_path, artifact_sha256 = _write_exclusive(
                str(artifact_path),
                artifact_payload,
                'extracted artifact',
            )
            artifact_records.append({
                'path': str(materialized_path),
                'bytes': len(artifact_payload),
                'sha256': artifact_sha256,
            })
    return {
        'platform': platform,
        'completed': True,
        'session_url': result.session_url_after,
        'response': {
            'path': str(response_path),
            'bytes': len(response_payload),
            'sha256': response_sha256,
        },
        'receipt': {
            'path': str(receipt_path),
            'bytes': len(receipt_payload),
            'sha256': receipt_sha256,
        },
        'artifacts': artifact_records,
        'steps': [
            {
                'step': step.step,
                'success': step.success,
                'message': step.message,
            }
            for step in result.steps
        ],
    }


__all__ = ['DriveChatAdapterError', 'attach', 'consult', 'extract', 'scroll']
