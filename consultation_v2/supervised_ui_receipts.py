from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any, Mapping
import uuid

from .supervised_ui_contract import (
    CONTRACT_VERSION,
    TRAINING_PROTOCOL_COMMIT,
    canonical_json_bytes,
    sha256_hex,
)


_EVENT_KIND_RE = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
)
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_GIT_COMMIT_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
_RECEIPT_RE = re.compile(r'^(\d{6})-([a-z][a-z0-9_]{0,63})\.(json|raw)$')
_TERMINAL_EXECUTION_KINDS = frozenset({
    'action_result_exact',
    'failed',
    'indeterminate',
    'replayed',
    'stale',
    'tool_result_exact',
})


class ReceiptStoreError(RuntimeError):
    pass


def _uuid_text(value: Any, context: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        raise ReceiptStoreError(f'{context} must be a lowercase UUID')
    return value


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError as exc:
            raise ReceiptStoreError(f'receipt path component does not exist: {current}') from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ReceiptStoreError(f'receipt path component is a symlink: {current}')


def _validate_external_root(root: str | os.PathLike[str], public_repo_roots: list[str]) -> Path:
    raw_root = Path(root)
    if not raw_root.is_absolute():
        raise ReceiptStoreError('receipt root must be absolute')
    _assert_no_symlink_components(raw_root)
    metadata = os.lstat(raw_root)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ReceiptStoreError('receipt root must be a directory')
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ReceiptStoreError('receipt root mode must be exactly 0700')
    if metadata.st_uid != os.getuid():
        raise ReceiptStoreError('receipt root must be owned by the worker user')
    resolved_root = raw_root.resolve(strict=True)
    if not public_repo_roots:
        raise ReceiptStoreError('at least one public repository root is required')
    for raw_public_root in public_repo_roots:
        public_root = Path(raw_public_root)
        if not public_root.is_absolute():
            raise ReceiptStoreError('public repository roots must be absolute')
        _assert_no_symlink_components(public_root)
        resolved_public = public_root.resolve(strict=True)
        if resolved_root == resolved_public or resolved_public in resolved_root.parents:
            raise ReceiptStoreError('receipt root must be outside every public repository')
    return resolved_root


def _write_all(fd: int, raw_bytes: bytes) -> None:
    view = memoryview(raw_bytes)
    written = 0
    while written < len(view):
        count = os.write(fd, view[written:])
        if count <= 0:
            raise ReceiptStoreError('receipt write made no progress')
        written += count


class HandsReceiptStore:
    def __init__(
        self,
        *,
        root: Path,
        session_dir: Path,
        session_id: str,
        presence_incarnation_id: str,
        hands_incarnation_id: str,
        hands_commit: str,
        dir_fd: int,
        lock_fd: int,
        events: list[dict[str, Any]],
    ) -> None:
        self.root = root
        self.session_dir = session_dir
        self.session_id = session_id
        self.presence_incarnation_id = presence_incarnation_id
        self.hands_incarnation_id = hands_incarnation_id
        self.hands_commit = hands_commit
        self._dir_fd = dir_fd
        self._lock_fd = lock_fd
        self._events = events
        self._broken = False

    @classmethod
    def open_external(
        cls,
        root: str | os.PathLike[str],
        public_repo_roots: list[str],
        *,
        session_id: str,
        presence_incarnation_id: str,
        hands_incarnation_id: str,
        hands_commit: str,
    ) -> 'HandsReceiptStore':
        _uuid_text(session_id, 'session_id')
        _uuid_text(presence_incarnation_id, 'presence_incarnation_id')
        _uuid_text(hands_incarnation_id, 'hands_incarnation_id')
        if not isinstance(hands_commit, str) or not _GIT_COMMIT_RE.fullmatch(hands_commit):
            raise ReceiptStoreError('hands_commit must be an exact commit SHA')
        validated_root = _validate_external_root(root, public_repo_roots)
        session_dir = validated_root / session_id
        try:
            os.mkdir(session_dir, mode=0o700)
            root_fd = os.open(
                validated_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
        except FileExistsError:
            pass
        session_metadata = os.lstat(session_dir)
        if stat.S_ISLNK(session_metadata.st_mode) or not stat.S_ISDIR(session_metadata.st_mode):
            raise ReceiptStoreError('session receipt path must be a real directory')
        if stat.S_IMODE(session_metadata.st_mode) != 0o700:
            raise ReceiptStoreError('session receipt directory mode must be exactly 0700')
        if session_metadata.st_uid != os.getuid():
            raise ReceiptStoreError('session receipt directory must be owned by the worker user')
        dir_fd = os.open(
            session_dir,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        lock_fd = -1
        try:
            lock_fd = os.open(
                '.worker.lock',
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=dir_fd,
            )
            os.fchmod(lock_fd, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ReceiptStoreError('another worker owns this supervised session') from exc
            events = cls._load_and_verify_events(
                dir_fd=dir_fd,
                session_id=session_id,
            )
            return cls(
                root=validated_root,
                session_dir=session_dir,
                session_id=session_id,
                presence_incarnation_id=presence_incarnation_id,
                hands_incarnation_id=hands_incarnation_id,
                hands_commit=hands_commit,
                dir_fd=dir_fd,
                lock_fd=lock_fd,
                events=events,
            )
        except Exception:
            if lock_fd >= 0:
                os.close(lock_fd)
            os.close(dir_fd)
            raise

    @staticmethod
    def _read_file(dir_fd: int, filename: str) -> bytes:
        fd = os.open(
            filename,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=dir_fd,
        )
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise ReceiptStoreError(f'unsafe receipt artifact {filename}')
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            return b''.join(chunks)
        finally:
            os.close(fd)

    @classmethod
    def _load_and_verify_events(
        cls,
        *,
        dir_fd: int,
        session_id: str,
    ) -> list[dict[str, Any]]:
        names = sorted(name for name in os.listdir(dir_fd) if name != '.worker.lock')
        if any(_RECEIPT_RE.fullmatch(name) is None for name in names):
            raise ReceiptStoreError('session receipt directory contains an unknown artifact')
        grouped: dict[tuple[int, str], set[str]] = {}
        for name in names:
            match = _RECEIPT_RE.fullmatch(name)
            assert match is not None
            key = (int(match.group(1)), match.group(2))
            grouped.setdefault(key, set()).add(match.group(3))
        events: list[dict[str, Any]] = []
        prior_hash: str | None = None
        prior_event_id: str | None = None
        for expected_sequence, ((sequence, kind), suffixes) in enumerate(sorted(grouped.items()), 1):
            if sequence != expected_sequence or suffixes != {'json', 'raw'}:
                raise ReceiptStoreError('receipt sequence is incomplete or noncontiguous')
            prefix = f'{sequence:06d}-{kind}'
            raw_bytes = cls._read_file(dir_fd, f'{prefix}.raw')
            metadata_bytes = cls._read_file(dir_fd, f'{prefix}.json')
            try:
                event = json.loads(metadata_bytes.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ReceiptStoreError('receipt metadata is not UTF-8 JSON') from exc
            if not isinstance(event, dict) or canonical_json_bytes(event) != metadata_bytes:
                raise ReceiptStoreError('receipt metadata is not canonical JSON')
            event_hash = event.get('event_hash')
            unsigned = dict(event)
            unsigned.pop('event_hash', None)
            if not isinstance(event_hash, str) or not _SHA256_RE.fullmatch(event_hash):
                raise ReceiptStoreError('receipt event hash is invalid')
            if sha256_hex(canonical_json_bytes(unsigned)) != event_hash:
                raise ReceiptStoreError('receipt event hash mismatch')
            checks = {
                event.get('schema_version') == CONTRACT_VERSION,
                event.get('session_id') == session_id,
                event.get('sequence') == sequence,
                event.get('kind') == kind,
                event.get('prior_event_hash') == prior_hash,
                event.get('caused_by_event_id') == prior_event_id,
                event.get('payload_sha256') == sha256_hex(raw_bytes),
                event.get('raw_artifact') == f'{prefix}.raw',
            }
            commits = event.get('public_repository_commits')
            if not isinstance(commits, dict) or frozenset(commits) != frozenset({
                'palios-taey/palios-training',
                'palios-taey/taeys-hands',
            }):
                raise ReceiptStoreError('receipt repository provenance is invalid')
            if commits['palios-taey/palios-training'] != TRAINING_PROTOCOL_COMMIT:
                raise ReceiptStoreError('receipt training protocol provenance changed')
            if not isinstance(commits['palios-taey/taeys-hands'], str) or not _GIT_COMMIT_RE.fullmatch(
                commits['palios-taey/taeys-hands']
            ):
                raise ReceiptStoreError('receipt Hands commit provenance is invalid')
            if False in checks:
                raise ReceiptStoreError('receipt causal chain verification failed')
            _uuid_text(event.get('event_id'), 'receipt.event_id')
            _uuid_text(event.get('hands_incarnation_id'), 'receipt.hands_incarnation_id')
            _uuid_text(event.get('presence_incarnation_id'), 'receipt.presence_incarnation_id')
            try:
                payload = json.loads(raw_bytes.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ReceiptStoreError('Hands receipt payload is not UTF-8 JSON') from exc
            event['_payload'] = payload
            events.append(event)
            prior_hash = event_hash
            prior_event_id = event['event_id']
        return events

    @property
    def events(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            {key: value for key, value in event.items() if key != '_payload'}
            for event in self._events
        )

    @property
    def last_event_id(self) -> str | None:
        return self._events[-1]['event_id'] if self._events else None

    def _create_file(self, filename: str, raw_bytes: bytes) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(filename, flags, 0o600, dir_fd=self._dir_fd)
        try:
            os.fchmod(fd, 0o600)
            _write_all(fd, raw_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self._dir_fd)

    def write_once(self, event: Mapping[str, Any], raw_bytes: bytes) -> Mapping[str, Any]:
        if self._broken:
            raise ReceiptStoreError('receipt store is terminal after a prior write failure')
        if not isinstance(raw_bytes, bytes) or not raw_bytes:
            raise ReceiptStoreError('receipt raw bytes must be nonempty')
        supplied = dict(event)
        required = frozenset({
            'approval_id',
            'event_id',
            'execution_id',
            'kind',
            'observation_id',
            'proposal_id',
            'turn_id',
        })
        if frozenset(supplied) != required:
            raise ReceiptStoreError('receipt event fields are incomplete or unknown')
        kind = supplied['kind']
        if not isinstance(kind, str) or not _EVENT_KIND_RE.fullmatch(kind):
            raise ReceiptStoreError('receipt event kind is invalid')
        _uuid_text(supplied['event_id'], 'event_id')
        for key in ('approval_id', 'execution_id', 'observation_id', 'proposal_id', 'turn_id'):
            _uuid_text(supplied[key], key, optional=True)
        sequence = len(self._events) + 1
        prefix = f'{sequence:06d}-{kind}'
        raw_filename = f'{prefix}.raw'
        metadata_filename = f'{prefix}.json'
        names = set(os.listdir(self._dir_fd))
        if raw_filename in names or metadata_filename in names:
            raise ReceiptStoreError('receipt filename collision')
        unsigned = {
            'approval_id': supplied['approval_id'],
            'caused_by_event_id': self.last_event_id,
            'event_id': supplied['event_id'],
            'execution_id': supplied['execution_id'],
            'hands_incarnation_id': self.hands_incarnation_id,
            'kind': kind,
            'monotonic_ns': time.monotonic_ns(),
            'observation_id': supplied['observation_id'],
            'payload_sha256': hashlib.sha256(raw_bytes).hexdigest(),
            'prior_event_hash': self._events[-1]['event_hash'] if self._events else None,
            'presence_incarnation_id': self.presence_incarnation_id,
            'proposal_id': supplied['proposal_id'],
            'public_repository_commits': {
                'palios-taey/palios-training': TRAINING_PROTOCOL_COMMIT,
                'palios-taey/taeys-hands': self.hands_commit,
            },
            'raw_artifact': raw_filename,
            'recorded_at': datetime.now(timezone.utc).isoformat(timespec='microseconds'),
            'schema_version': CONTRACT_VERSION,
            'sequence': sequence,
            'session_id': self.session_id,
            'turn_id': supplied['turn_id'],
        }
        recorded = dict(unsigned)
        recorded['event_hash'] = sha256_hex(canonical_json_bytes(unsigned))
        try:
            self._create_file(raw_filename, raw_bytes)
            self._create_file(metadata_filename, canonical_json_bytes(recorded))
        except Exception:
            self._broken = True
            raise
        internal = dict(recorded)
        internal['_payload'] = json.loads(raw_bytes.decode('utf-8'))
        self._events.append(internal)
        return dict(recorded)

    def has_approval_spend(self, approval_id: str) -> bool:
        return any(
            event['kind'] == 'approval_spent' and event['approval_id'] == approval_id
            for event in self._events
        )

    def has_execution(self, execution_id: str) -> bool:
        return any(event['execution_id'] == execution_id for event in self._events)

    def recover_incarnation(self) -> str:
        executions: dict[str, list[Mapping[str, Any]]] = {}
        for event in self._events:
            execution_id = event.get('execution_id')
            if execution_id is not None:
                executions.setdefault(execution_id, []).append(event)
        for execution_id, events in sorted(executions.items()):
            kinds = {event['kind'] for event in events}
            if not kinds.intersection({'approval_spent', 'execution_started'}):
                continue
            if kinds.intersection(_TERMINAL_EXECUTION_KINDS):
                continue
            last = events[-1]
            payload = canonical_json_bytes({
                'reason': 'recovered_incomplete_execution',
                'prior_hands_incarnation_id': last['hands_incarnation_id'],
            })
            self.write_once({
                'approval_id': last.get('approval_id'),
                'event_id': str(uuid.uuid4()),
                'execution_id': execution_id,
                'kind': 'indeterminate',
                'observation_id': last.get('observation_id'),
                'proposal_id': last.get('proposal_id'),
                'turn_id': last.get('turn_id'),
            }, payload)
        return self.hands_incarnation_id

    def close(self) -> None:
        if self._lock_fd >= 0:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = -1
        if self._dir_fd >= 0:
            os.close(self._dir_fd)
            self._dir_fd = -1

    def __enter__(self) -> 'HandsReceiptStore':
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()
