"""One-process adapters for the supervised ``drive_chat`` lane.

Import this module only after the caller has bound ``DISPLAY`` and the AT-SPI
bus.  The caller continues to own display locking and JSON serialization.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
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
    if artifact_directory.is_symlink():
        raise DriveChatAdapterError(
            f'output attachment path is a symlink: {artifact_directory}'
        )
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


def _read_exact_materialized_file(
    path: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DriveChatAdapterError(
            f'could not open materialized artifact file: {path}'
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size != expected_bytes
        ):
            raise DriveChatAdapterError(
                f'materialized artifact failed exact file validation: {path}'
            )
        content = bytearray()
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        stable_fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns')
        if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
            raise DriveChatAdapterError(
                f'materialized artifact changed while being read: {path}'
            )
        if len(content) != expected_bytes or digest.hexdigest() != expected_sha256:
            raise DriveChatAdapterError(
                f'materialized artifact failed exact digest validation: {path}'
            )
        return bytes(content)
    finally:
        os.close(descriptor)


def _write_private_exclusive(
    path: Path,
    payload: bytes,
    *,
    expected_sha256: str,
) -> tuple[Path, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise DriveChatAdapterError(
            f'could not create exclusive materialized artifact output: {path}'
        ) from exc
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise DriveChatAdapterError(
                    f'materialized artifact output write made no progress: {path}'
                )
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    readback = _read_exact_materialized_file(
        path,
        expected_bytes=len(payload),
        expected_sha256=expected_sha256,
    )
    if readback != payload:
        raise DriveChatAdapterError(
            f'materialized artifact output failed exact readback: {path}'
        )
    directory_flags = os.O_RDONLY
    if hasattr(os, 'O_DIRECTORY'):
        directory_flags |= os.O_DIRECTORY
    try:
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise DriveChatAdapterError(
            f'could not fsync materialized artifact directory: {path.parent}'
        ) from exc
    return path, expected_sha256


def _planned_materialized_artifacts(
    artifact_directory: Path,
    result: ConsultationResult,
    *,
    reserved_names: set[str],
    response_payload: bytes,
) -> list[dict[str, Any]]:
    if 'materialized_artifacts' not in result.storage:
        return []
    records = result.storage['materialized_artifacts']
    if not isinstance(records, list):
        raise DriveChatAdapterError('materialized_artifacts must be a list')
    planned: list[dict[str, Any]] = []
    names = set(reserved_names)
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != {
            'schema', 'name', 'path', 'bytes', 'sha256', 'metadata'
        }:
            raise DriveChatAdapterError(
                f'materialized_artifacts[{index}] has an invalid envelope'
            )
        if record['schema'] != 'taey.materialized_file.v1':
            raise DriveChatAdapterError(
                f'materialized_artifacts[{index}] has an unsupported schema'
            )
        name = record['name']
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name in {'.', '..'}
        ):
            raise DriveChatAdapterError(
                f'materialized_artifacts[{index}] has an invalid name'
            )
        if name in names:
            raise DriveChatAdapterError(f'duplicate extracted artifact name: {name!r}')
        source_value = record['path']
        if not isinstance(source_value, str) or not source_value:
            raise DriveChatAdapterError(
                f'materialized_artifacts[{index}] has an invalid source path'
            )
        source = Path(source_value).expanduser()
        if not source.is_absolute():
            raise DriveChatAdapterError(
                f'materialized_artifacts[{index}] source path must be absolute'
            )
        expected_bytes = record['bytes']
        expected_sha256 = record['sha256']
        if (
            not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or expected_bytes <= 0
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(character not in '0123456789abcdef' for character in expected_sha256)
            or not isinstance(record['metadata'], dict)
        ):
            raise DriveChatAdapterError(
                f'materialized_artifacts[{index}] has invalid byte/hash metadata'
            )
        payload = _read_exact_materialized_file(
            source,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
        )
        destination = artifact_directory / name
        if destination.exists() or destination.is_symlink():
            raise DriveChatAdapterError(
                f'extracted artifact already exists; refusing overwrite: {destination}'
            )
        if payload == response_payload:
            raise DriveChatAdapterError(
                f'extracted artifact duplicates the assistant response: {name!r}'
            )
        names.add(name)
        planned.append({
            'source': source,
            'destination': destination,
            'bytes': expected_bytes,
            'sha256': expected_sha256,
            'payload': payload,
            'record': record,
        })
    return planned


def _copy_materialized_artifact(plan: dict[str, Any]) -> tuple[Path, str]:
    return _write_private_exclusive(
        plan['destination'],
        plan['payload'],
        expected_sha256=plan['sha256'],
    )


def _receipt_payload(result: ConsultationResult) -> bytes:
    return json.dumps(
        result.serializable(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode('utf-8')


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
    if not result.ok or not result.response_text:
        if result.ok:
            result.ok = False
            result.add_step(
                'materialize_outputs',
                False,
                'consultation returned no response deliverable',
                stop_condition='output_materialization_failed',
            )
        receipt_payload = _receipt_payload(result)
        receipt_path, receipt_sha256 = _write_exclusive(
            str(receipt_path),
            receipt_payload,
            'receipt_file',
        )
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
    artifact_records: list[dict[str, Any]] = []
    try:
        planned_artifacts = _planned_artifacts(artifact_directory, result)
        reserved_names = {path.name for path, _ in planned_artifacts}
        planned_materialized = _planned_materialized_artifacts(
            artifact_directory,
            result,
            reserved_names=reserved_names,
            response_payload=response_payload,
        )
        for artifact_path, artifact_payload in planned_artifacts:
            if artifact_payload == response_payload:
                raise DriveChatAdapterError(
                    'extracted artifact duplicates the assistant response: '
                    f'{artifact_path.name!r}'
                )
        response_path, response_sha256 = _write_exclusive(
            str(output_path),
            response_payload,
            'output_file',
        )
        final_materialized_records: list[dict[str, Any]] = []
        if planned_artifacts or planned_materialized:
            artifact_directory.mkdir(mode=0o700, exist_ok=True)
            artifact_directory_details = artifact_directory.lstat()
            if not stat.S_ISDIR(artifact_directory_details.st_mode):
                raise DriveChatAdapterError(
                    f'output attachment path is not a directory: {artifact_directory}'
                )
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
            for plan in planned_materialized:
                materialized_path, artifact_sha256 = _copy_materialized_artifact(plan)
                artifact_record = {
                    'path': str(materialized_path),
                    'bytes': plan['bytes'],
                    'sha256': artifact_sha256,
                }
                artifact_records.append(artifact_record)
                final_record = dict(plan['record'])
                final_record['path'] = str(materialized_path)
                final_materialized_records.append(final_record)
        if planned_materialized:
            result.storage['materialized_artifacts'] = final_materialized_records
        result.add_step(
            'materialize_outputs',
            True,
            'consultation response and artifacts materialized exactly',
            response={
                'path': str(response_path),
                'bytes': len(response_payload),
                'sha256': response_sha256,
            },
            artifacts=artifact_records,
        )
    except (DriveChatAdapterError, OSError, ValueError) as exc:
        result.ok = False
        result.add_step(
            'materialize_outputs',
            False,
            f'consultation output materialization failed: {exc}',
            stop_condition='output_materialization_failed',
        )
        receipt_payload = _receipt_payload(result)
        receipt_path, receipt_sha256 = _write_exclusive(
            str(receipt_path),
            receipt_payload,
            'receipt_file',
        )
        raise DriveChatAdapterError(
            f'{platform}: consultation output materialization failed: {exc}; '
            f'receipt={receipt_path} sha256={receipt_sha256}'
        ) from exc
    receipt_payload = _receipt_payload(result)
    receipt_path, receipt_sha256 = _write_exclusive(
        str(receipt_path),
        receipt_payload,
        'receipt_file',
    )
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
