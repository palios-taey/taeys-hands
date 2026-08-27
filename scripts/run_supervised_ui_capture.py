#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import select
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Mapping
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_DISPLAY_RE = re.compile(r'^:[0-9]{1,3}$')
_GIT_COMMIT_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_REQUEST_LIMIT = 1024 * 1024


class CaptureSupervisorPreflightError(ValueError):
    """Raised when prelaunch containment, spent-record, or identity checks fail."""
    def __init__(self, failure_code: str, message: str) -> None:
        super().__init__(message)
        self.failure_code = failure_code


class CaptureSupervisorQuarantineError(RuntimeError):
    """Raised when an active child process fails, halts, or violates protocol."""
    def __init__(self, failure_code: str, message: str, last_hash: str | None = None) -> None:
        super().__init__(message)
        self.failure_code = failure_code
        self.last_hash = last_hash


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Run the approval-gated supervised Taey UI capture supervisor.',
    )
    # Forwarded to worker
    parser.add_argument(
        '--platform',
        required=True,
        choices=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'],
    )
    parser.add_argument('--display', required=True)
    parser.add_argument('--receipt-root', required=True)
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--presence-incarnation-id', required=True)
    parser.add_argument('--lease-expires-at', required=True)
    parser.add_argument('--lease-secret-env', required=True)
    parser.add_argument('--hands-commit', required=True)
    parser.add_argument('--public-repo-root', action='append', required=True)
    parser.add_argument('--lock-wait-seconds', type=float, default=0.0)

    # Supervisor-only arguments
    parser.add_argument('--export-root', required=True)
    parser.add_argument('--export-receipt', required=True)
    parser.add_argument('--close-ack-timeout-seconds', type=float, default=10.0)
    parser.add_argument('--worker-exit-timeout-seconds', type=float, default=10.0)
    return parser


def _strict_json(raw_text: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate key')
            value[key] = item
        return value

    parsed = json.loads(
        raw_text,
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError('non-JSON constant')),
    )
    if not isinstance(parsed, dict):
        raise ValueError('request must be an object')
    return parsed


def _require_keys(value: Mapping[str, Any], required: frozenset[str]) -> None:
    if frozenset(value) != required:
        raise ValueError('request fields are incomplete or unknown')


def _uuid_text(value: Any) -> str:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        raise ValueError('request_id must be a canonical lowercase UUID')
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    from consultation_v2.supervised_ui_contract import canonical_json_bytes
    return canonical_json_bytes(value)


def _sha256_hex(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def _assert_no_symlinks(path: Path) -> None:
    current = Path(path.root)
    for part in path.parts[1:]:
        current = current / part
        if not current.exists() and not current.is_symlink():
            break
        metadata = os.lstat(current)
        if stat.S_ISLNK(metadata.st_mode):
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                f'symlink path component {current}',
            )


def _validate_private_root(
    path_value: str | Path,
    public_roots: list[Path],
    context: str,
) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise CaptureSupervisorPreflightError(
            'FC-TRACE',
            f'{context} must be absolute',
        )
    _assert_no_symlinks(path)
    if not path.exists():
        raise CaptureSupervisorPreflightError(
            'FC-TRACE',
            f'{context} does not exist',
        )
    metadata = os.lstat(path)
    if not stat.S_ISDIR(metadata.st_mode):
        raise CaptureSupervisorPreflightError(
            'FC-TRACE',
            f'{context} must be a directory',
        )
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise CaptureSupervisorPreflightError(
            'FC-TRACE',
            f'{context} must have mode 0700',
        )
    if metadata.st_uid != os.getuid():
        raise CaptureSupervisorPreflightError(
            'FC-TRACE',
            f'{context} must be owned by effective user',
        )
    resolved = path.resolve(strict=True)
    for pub in public_roots:
        resolved_pub = pub.resolve(strict=True)
        if resolved == resolved_pub or resolved_pub in resolved.parents or resolved in resolved_pub.parents:
            raise CaptureSupervisorPreflightError(
                'FC-PRIVACY',
                f'{context} overlaps public repository root {resolved_pub}',
            )
    return resolved


def _open_spent_record_directory(root: Path, relative_dir_name: str) -> int:
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        try:
            os.mkdir(relative_dir_name, mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        try:
            os.fsync(root_fd)
        except OSError as exc:
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                f'unable to fsync containing root directory {root}: {exc}',
            ) from exc
        claim_dir_fd = os.open(
            relative_dir_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=root_fd,
        )
        metadata = os.fstat(claim_dir_fd)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
            os.close(claim_dir_fd)
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                f'claim directory {relative_dir_name} is not mode 0700 directory',
            )
        if metadata.st_uid != os.getuid():
            os.close(claim_dir_fd)
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                f'claim directory {relative_dir_name} is not owned by current user',
            )
        return claim_dir_fd
    finally:
        os.close(root_fd)


def _create_spent_record_once(
    claim_dir_fd: int,
    domain_prefix: str,
    identity_payload: dict[str, Any],
    claim_kind: str,
) -> str:
    identity_bytes = _canonical_json_bytes(identity_payload)
    digest_seed = domain_prefix.encode('utf-8') + b'\x00' + identity_bytes
    identity_sha256 = _sha256_hex(digest_seed)
    filename = f'{identity_sha256}.claim'

    record = {
        'claim_kind': claim_kind,
        'identity': identity_payload,
        'identity_sha256': identity_sha256,
        'schema_version': 'supervised_ui_capture_spent_claim_v1',
        'terminal': True,
    }
    record_bytes = _canonical_json_bytes(record)

    try:
        fd = os.open(
            filename,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=claim_dir_fd,
        )
    except FileExistsError as exc:
        raise CaptureSupervisorPreflightError(
            'FC-SPENT-CLAIM',
            f'spent claim {filename} already exists',
        ) from exc
    except OSError as exc:
        raise CaptureSupervisorPreflightError(
            'FC-TRACE',
            f'unable to create spent claim {filename}: {exc}',
        ) from exc

    try:
        written = os.write(fd, record_bytes)
        if written != len(record_bytes):
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                f'short write for spent claim {filename}',
            )
        os.fchmod(fd, 0o600)
        os.fsync(fd)
    finally:
        os.close(fd)

    os.fsync(claim_dir_fd)

    # Exact readback verification
    read_fd = os.open(
        filename,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=claim_dir_fd,
    )
    try:
        metadata = os.fstat(read_fd)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                f'spent claim {filename} has invalid file mode',
            )
        if metadata.st_nlink != 1 or metadata.st_uid != os.getuid():
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                f'spent claim {filename} has invalid link count or owner',
            )
        readback = os.read(read_fd, len(record_bytes) + 1)
    finally:
        os.close(read_fd)

    if readback != record_bytes:
        raise CaptureSupervisorPreflightError(
            'FC-TRACE',
            f'spent claim {filename} readback bytes mismatch',
        )
    parsed = json.loads(readback.decode('utf-8'))
    if _canonical_json_bytes(parsed) != record_bytes:
        raise CaptureSupervisorPreflightError(
            'FC-TRACE',
            f'spent claim {filename} canonical json mismatch',
        )
    if parsed.get('identity_sha256') != identity_sha256 or parsed.get('claim_kind') != claim_kind:
        raise CaptureSupervisorPreflightError(
            'FC-TRACE',
            f'spent claim {filename} identity verification failed',
        )
    return identity_sha256


def _git_blob_sha1(data: bytes) -> str:
    header = f'blob {len(data)}\x00'.encode('ascii')
    return hashlib.sha1(header + data).hexdigest()


def _verify_hands_checkout_and_commit(
    hands_commit_arg: str,
    repo_root: Path,
) -> tuple[str, Any, int]:
    if not isinstance(hands_commit_arg, str) or not _GIT_COMMIT_RE.fullmatch(hands_commit_arg):
        raise CaptureSupervisorPreflightError('FC-WRONG-COMMIT', 'declared Hands commit format is invalid')

    # 1. Descriptor-open the running Hands checkout with no-follow containment
    _assert_no_symlinks(repo_root)
    try:
        repo_fd = os.open(repo_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise CaptureSupervisorPreflightError('FC-TRACE', f'unable to open repo root without symlinks: {exc}') from exc

    try:
        metadata = os.fstat(repo_fd)
        if not stat.S_ISDIR(metadata.st_mode):
            raise CaptureSupervisorPreflightError('FC-TRACE', 'Hands repo root is not a directory')

        # 2. Prove via Git toplevel on held descriptor that it is the exact same checkout
        try:
            toplevel_proc = subprocess.run(
                ['git', '-C', f'/proc/self/fd/{repo_fd}', 'rev-parse', '--show-toplevel'],
                check=True,
                capture_output=True,
                text=True,
                pass_fds=(repo_fd,),
            )
            toplevel_path = Path(toplevel_proc.stdout.strip()).resolve(strict=True)
            if toplevel_path != repo_root.resolve(strict=True):
                raise CaptureSupervisorPreflightError(
                    'FC-WRONG-COMMIT',
                    'Hands repository toplevel does not match running checkout',
                )
        except subprocess.CalledProcessError as exc:
            raise CaptureSupervisorPreflightError('FC-WRONG-COMMIT', f'unable to establish Git toplevel: {exc}') from exc

        # 3. Check for completely clean working tree (tracked and untracked) via held descriptor
        try:
            status_proc = subprocess.run(
                ['git', '-C', f'/proc/self/fd/{repo_fd}', 'status', '--porcelain'],
                check=True,
                capture_output=True,
                text=True,
                pass_fds=(repo_fd,),
            )
            if status_proc.stdout.strip():
                raise CaptureSupervisorPreflightError('FC-WRONG-COMMIT', 'Hands checkout has uncommitted or untracked changes')
        except subprocess.CalledProcessError as exc:
            raise CaptureSupervisorPreflightError('FC-WRONG-COMMIT', f'unable to check Git status: {exc}') from exc

        # 4. Prove local HEAD on held descriptor equals args.hands_commit
        try:
            rev_proc = subprocess.run(
                ['git', '-C', f'/proc/self/fd/{repo_fd}', 'rev-parse', 'HEAD'],
                check=True,
                capture_output=True,
                text=True,
                pass_fds=(repo_fd,),
            )
            actual_commit = rev_proc.stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise CaptureSupervisorPreflightError('FC-WRONG-COMMIT', f'unable to establish Git HEAD: {exc}') from exc

        if not _GIT_COMMIT_RE.fullmatch(actual_commit):
            raise CaptureSupervisorPreflightError('FC-WRONG-COMMIT', 'unable to establish exact Hands commit')

        if hands_commit_arg != actual_commit:
            raise CaptureSupervisorPreflightError(
                'FC-WRONG-COMMIT',
                f'declared Hands commit {hands_commit_arg} does not match checkout HEAD {actual_commit}',
            )

        # 5. Read entire scorer helper closure directly through descriptor and verify blob hashes against committed HEAD
        try:
            consult_fd = os.open(
                'consultation_v2',
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=repo_fd,
            )
        except OSError as exc:
            raise CaptureSupervisorPreflightError('FC-FORGED-EVIDENCE', f'unable to open consultation_v2 directory: {exc}') from exc

        try:
            def _read_closure_file(filename: str) -> bytes:
                try:
                    fd = os.open(
                        filename,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=consult_fd,
                    )
                except OSError as exc:
                    raise CaptureSupervisorPreflightError('FC-FORGED-EVIDENCE', f'unable to open {filename}: {exc}') from exc

                try:
                    f_meta = os.fstat(fd)
                    if not stat.S_ISREG(f_meta.st_mode):
                        raise CaptureSupervisorPreflightError('FC-FORGED-EVIDENCE', f'{filename} is not a regular file')
                    data = os.read(fd, f_meta.st_size + 1)
                    if len(data) != f_meta.st_size:
                        raise CaptureSupervisorPreflightError('FC-FORGED-EVIDENCE', f'{filename} read length mismatch')
                    return data
                finally:
                    os.close(fd)

            types_bytes = _read_closure_file('types.py')
            contract_bytes = _read_closure_file('supervised_ui_contract.py')
            scorer_bytes = _read_closure_file('ui_lane_production_scorer.py')
        finally:
            os.close(consult_fd)

        for rel_path, file_bytes in [
            ('consultation_v2/types.py', types_bytes),
            ('consultation_v2/supervised_ui_contract.py', contract_bytes),
            ('consultation_v2/ui_lane_production_scorer.py', scorer_bytes),
        ]:
            try:
                ls_proc = subprocess.run(
                    ['git', '-C', f'/proc/self/fd/{repo_fd}', 'ls-tree', actual_commit, rel_path],
                    check=True,
                    capture_output=True,
                    text=True,
                    pass_fds=(repo_fd,),
                )
                ls_parts = ls_proc.stdout.strip().split()
                if len(ls_parts) < 3 or ls_parts[1] != 'blob':
                    raise CaptureSupervisorPreflightError('FC-WRONG-COMMIT', f'{rel_path} not tracked at committed HEAD')
                committed_blob = ls_parts[2]
            except subprocess.CalledProcessError as exc:
                raise CaptureSupervisorPreflightError('FC-WRONG-COMMIT', f'unable to check {rel_path} git ls-tree: {exc}') from exc

            actual_blob = _git_blob_sha1(file_bytes)
            if actual_blob != committed_blob:
                raise CaptureSupervisorPreflightError(
                    'FC-WRONG-COMMIT',
                    f'{rel_path} on-disk content {actual_blob} differs from committed HEAD blob {committed_blob}',
                )

        # 6. Build hermetic private package and compile modules strictly from verified bytes
        import types
        pkg_name = f'_verified_hands_{actual_commit}'
        created_mod_names = [
            pkg_name,
            f'{pkg_name}.types',
            f'{pkg_name}.supervised_ui_contract',
            f'{pkg_name}.ui_lane_production_scorer',
        ]
        try:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = []
            sys.modules[pkg_name] = pkg

            types_mod = types.ModuleType(f'{pkg_name}.types')
            types_mod.__package__ = pkg_name
            types_mod.__file__ = f'/proc/self/fd/{repo_fd}/consultation_v2/types.py'
            sys.modules[f'{pkg_name}.types'] = types_mod
            exec(compile(types_bytes.decode('utf-8'), types_mod.__file__, 'exec'), types_mod.__dict__)

            contract_mod = types.ModuleType(f'{pkg_name}.supervised_ui_contract')
            contract_mod.__package__ = pkg_name
            contract_mod.__file__ = f'/proc/self/fd/{repo_fd}/consultation_v2/supervised_ui_contract.py'
            sys.modules[f'{pkg_name}.supervised_ui_contract'] = contract_mod
            exec(compile(contract_bytes.decode('utf-8'), contract_mod.__file__, 'exec'), contract_mod.__dict__)

            scorer_mod = types.ModuleType(f'{pkg_name}.ui_lane_production_scorer')
            scorer_mod.__package__ = pkg_name
            scorer_mod.__file__ = f'/proc/self/fd/{repo_fd}/consultation_v2/ui_lane_production_scorer.py'
            sys.modules[f'{pkg_name}.ui_lane_production_scorer'] = scorer_mod
            exec(compile(scorer_bytes.decode('utf-8'), scorer_mod.__file__, 'exec'), scorer_mod.__dict__)
            scorer_mod.REPO_ROOT = Path(f'/proc/self/fd/{repo_fd}')

            held_repo_fd = repo_fd
            repo_fd = -1
            return actual_commit, scorer_mod, held_repo_fd
        except Exception:
            for name in created_mod_names:
                sys.modules.pop(name, None)
            raise
    finally:
        if repo_fd >= 0:
            os.close(repo_fd)


def _preflight_fresh_session(
    args: argparse.Namespace,
    public_roots: list[Path],
) -> tuple[Path, Path, str, Any, int]:
    # 0. Verify Hands checkout and exact commit binding before any storage or helper import
    _, scorer_module, repo_fd = _verify_hands_checkout_and_commit(args.hands_commit, REPO_ROOT)
    pkg_name = scorer_module.__package__
    registered_mod_names = [
        pkg_name,
        f'{pkg_name}.types',
        f'{pkg_name}.supervised_ui_contract',
        f'{pkg_name}.ui_lane_production_scorer',
    ]

    try:
        # 1. Validate public roots
        for pub in public_roots:
            if not (pub / '.git').exists():
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    f'public repo root {pub} is not a git checkout',
                )

        # 2. Validate receipt-root
        receipt_root = _validate_private_root(args.receipt_root, public_roots, 'receipt-root')

        # 3. Validate session-id
        if not _UUID_RE.fullmatch(args.session_id):
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                'session-id must be a canonical lowercase UUID',
            )

        # 4. Validate export-root via verified scorer helper
        try:
            export_root = scorer_module._private_root(Path(args.export_root))
        except scorer_module.UiLaneScorerError as exc:
            raise CaptureSupervisorPreflightError(
                exc.refusal_code,
                exc.reason,
            ) from exc
        except Exception as exc:
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                f'export-root validation failed: {exc}',
            ) from exc

        for pub in public_roots:
            resolved_pub = pub.resolve(strict=True)
            if export_root == resolved_pub or resolved_pub in export_root.parents or export_root in resolved_pub.parents:
                raise CaptureSupervisorPreflightError(
                    'FC-PRIVACY',
                    f'export-root overlaps supplied public repository root {resolved_pub}',
                )

        # 5. Validate export-receipt
        if not isinstance(args.export_receipt, str) or not args.export_receipt:
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                'export-receipt must be a non-empty string',
            )
        raw_components = args.export_receipt.split('/')
        if any(part in {'', '.', '..'} for part in raw_components):
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                'export-receipt cannot contain empty, dot, or dot-dot components',
            )
        export_receipt_posix = PurePosixPath(*raw_components)
        if export_receipt_posix.is_absolute() or not export_receipt_posix.parts:
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                'export-receipt must be a relative path',
            )

        # 6. Open spent record directories
        session_claims_fd = _open_spent_record_directory(
            receipt_root,
            '.supervised-ui-capture-session-claims',
        )
        export_claims_fd = _open_spent_record_directory(
            export_root,
            '.supervised-ui-capture-export-claims',
        )

        try:
            # 7. Create session spent record first
            session_identity = {
                'receipt_root_realpath': str(receipt_root),
                'session_id': args.session_id,
            }
            _create_spent_record_once(
                session_claims_fd,
                'supervised-ui-capture-session-claim-v1',
                session_identity,
                'session',
            )

            # 8. Create export target spent record second
            export_identity = {
                'export_receipt_relative_posix': str(export_receipt_posix),
                'export_root_realpath': str(export_root),
            }
            _create_spent_record_once(
                export_claims_fd,
                'supervised-ui-capture-export-claim-v1',
                export_identity,
                'export_target',
            )
        finally:
            os.close(session_claims_fd)
            os.close(export_claims_fd)

        # 9. After both records verify, require session dir not to exist before mutating export hierarchy
        session_dir = receipt_root / args.session_id
        if session_dir.exists() or session_dir.is_symlink():
            raise CaptureSupervisorPreflightError(
                'FC-TRACE',
                'session directory already exists before fresh launch',
            )

        # 10. Require export target containment and absence
        parent_fd, target_name = _traverse_export_parent_directory(
            export_root,
            export_receipt_posix,
            is_preflight=True,
        )
        try:
            try:
                os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    f'export target {target_name} already exists before fresh launch',
                )
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    f'unable to stat export target {target_name}: {exc}',
                ) from exc
        finally:
            os.close(parent_fd)

        # 11. Create session directory once as mode 0700 via descriptor
        receipt_root_fd = os.open(
            receipt_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            try:
                os.mkdir(args.session_id, mode=0o700, dir_fd=receipt_root_fd)
            except FileExistsError as exc:
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    'session directory already exists before fresh launch',
                ) from exc
            except OSError as exc:
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    f'unable to create session directory {args.session_id}: {exc}',
                ) from exc

            try:
                os.fsync(receipt_root_fd)
            except OSError as exc:
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    f'unable to fsync receipt root after session mkdir: {exc}',
                ) from exc

            # 12. Reopen and verify new session directory descriptor-relative with O_NOFOLLOW
            try:
                session_dir_fd = os.open(
                    args.session_id,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=receipt_root_fd,
                )
            except OSError as exc:
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    f'unable to reopen fresh session directory {args.session_id}: {exc}',
                ) from exc
        finally:
            os.close(receipt_root_fd)

        try:
            metadata = os.fstat(session_dir_fd)
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    'fresh session directory has invalid mode',
                )
            if metadata.st_uid != os.getuid():
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    'fresh session directory has invalid owner',
                )
            entries = os.listdir(session_dir_fd)
            if len(entries) != 0:
                raise CaptureSupervisorPreflightError(
                    'FC-TRACE',
                    'fresh session directory is not empty',
                )
        finally:
            os.close(session_dir_fd)

        ret_repo_fd = repo_fd
        repo_fd = -1
        return receipt_root, export_root, str(export_receipt_posix), scorer_module, ret_repo_fd
    finally:
        if repo_fd >= 0:
            os.close(repo_fd)
            for name in registered_mod_names:
                sys.modules.pop(name, None)


def _traverse_export_parent_directory(
    export_root: Path,
    posix_path: PurePosixPath,
    *,
    is_preflight: bool = True,
) -> tuple[int, str]:
    err_cls = CaptureSupervisorPreflightError if is_preflight else CaptureSupervisorQuarantineError
    err_code = 'FC-TRACE' if is_preflight else 'export_parent_invalid'

    try:
        curr_fd = os.open(
            export_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        raise err_cls(err_code, f'unable to open export root {export_root} without symlink: {exc}') from exc

    try:
        for part in posix_path.parent.parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=curr_fd)
                try:
                    os.fsync(curr_fd)
                except OSError as exc:
                    raise err_cls(err_code, f'unable to fsync export parent after mkdir {part}: {exc}') from exc
            except FileExistsError:
                pass
            except OSError as exc:
                raise err_cls(err_code, f'unable to mkdir export parent {part}: {exc}') from exc

            next_fd = -1
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=curr_fd,
                )
                metadata = os.fstat(next_fd)
                if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
                    raise err_cls(err_code, f'export parent directory {part} is not mode 0700')
                if metadata.st_uid != os.getuid():
                    raise err_cls(err_code, f'export parent directory {part} is not owned by current user')
            except err_cls:
                if next_fd >= 0:
                    os.close(next_fd)
                raise
            except Exception as exc:
                if next_fd >= 0:
                    os.close(next_fd)
                raise err_cls(err_code, f'unable to open export parent {part} without symlink: {exc}') from exc

            old_fd = curr_fd
            curr_fd = next_fd
            try:
                os.close(old_fd)
            except Exception as exc:
                raise err_cls(err_code, f'unable to close export parent directory descriptor: {exc}') from exc

        result_fd = curr_fd
        curr_fd = -1
        return result_fd, posix_path.name
    finally:
        if curr_fd >= 0:
            os.close(curr_fd)


def _resolve_export_target(export_root: Path, export_receipt: str) -> tuple[int, str]:
    return _traverse_export_parent_directory(
        export_root,
        PurePosixPath(export_receipt),
        is_preflight=False,
    )


def _launch_worker(
    args: argparse.Namespace,
    public_roots: list[str],
) -> subprocess.Popen[str]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / 'scripts' / 'run_supervised_ui_seat.py'),
        '--platform', args.platform,
        '--display', args.display,
        '--receipt-root', args.receipt_root,
        '--session-id', args.session_id,
        '--presence-incarnation-id', args.presence_incarnation_id,
        '--lease-expires-at', args.lease_expires_at,
        '--lease-secret-env', args.lease_secret_env,
        '--hands-commit', args.hands_commit,
        '--lock-wait-seconds', str(args.lock_wait_seconds),
    ]
    for pub in public_roots:
        cmd.extend(['--public-repo-root', pub])

    worker = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    return worker


def _read_worker_line(
    worker: subprocess.Popen[str],
    timeout: float | None = None,
) -> str:
    if worker.stdout is None:
        raise CaptureSupervisorQuarantineError('worker_stdout_missing', 'worker stdout pipe is missing')

    fd = worker.stdout.fileno()
    deadline = (time.monotonic() + timeout) if (timeout is not None and timeout > 0) else None

    chunks: list[bytes] = []
    while True:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CaptureSupervisorQuarantineError('worker_timeout', 'timed out waiting for worker response')
            rlist, _, _ = select.select([fd], [], [], max(0.0, remaining))
            if not rlist:
                raise CaptureSupervisorQuarantineError('worker_timeout', 'timed out waiting for worker response')

        try:
            chunk = os.read(fd, 1)
        except (BlockingIOError, InterruptedError):
            continue
        except OSError as exc:
            raise CaptureSupervisorQuarantineError('worker_read_failed', f'worker read failed: {exc}') from exc

        if not chunk:
            if chunks:
                line = b''.join(chunks).decode('utf-8')
                if line.endswith('\n'):
                    return line
            raise CaptureSupervisorQuarantineError('worker_eof', 'worker emitted unexpected EOF')

        chunks.append(chunk)
        if chunk == b'\n':
            return b''.join(chunks).decode('utf-8')


def _relay_request(
    worker: subprocess.Popen[str],
    line: str,
    timeout: float | None = None,
) -> str:
    if worker.stdin is None:
        raise CaptureSupervisorQuarantineError('worker_stdin_missing', 'worker stdin pipe is missing')
    try:
        worker.stdin.write(line)
        worker.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise CaptureSupervisorQuarantineError('worker_stdin_broken', f'worker stdin write failed: {exc}') from exc
    return _read_worker_line(worker, timeout=timeout)


_CLOSE_ACK_TOP_LEVEL_KEYS = frozenset({'ok', 'request_id', 'result'})
_CLOSE_ACK_RESULT_KEYS = frozenset({'event_hash', 'state'})


def _close_ack(
    worker: subprocess.Popen[str],
    close_request: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    req_bytes = _canonical_json_bytes(close_request)
    req_line = req_bytes.decode('utf-8') + '\n'
    ack_line = _relay_request(worker, req_line, timeout=timeout)
    try:
        ack_dict = _strict_json(ack_line)
    except Exception as exc:
        raise CaptureSupervisorQuarantineError('close_ack_malformed', f'close ack is not strict json: {exc}') from exc

    if not isinstance(ack_dict, dict):
        raise CaptureSupervisorQuarantineError('close_ack_malformed', 'close ack is not a dict')
    try:
        _require_keys(ack_dict, _CLOSE_ACK_TOP_LEVEL_KEYS)
    except Exception as exc:
        raise CaptureSupervisorQuarantineError('close_ack_shape_invalid', f'close ack top-level shape invalid: {exc}') from exc

    if ack_dict['ok'] is not True:
        raise CaptureSupervisorQuarantineError('close_ack_not_ok', f'close ack not ok: {ack_dict}')
    if ack_dict['request_id'] != close_request.get('request_id'):
        raise CaptureSupervisorQuarantineError('close_ack_id_mismatch', 'close ack request_id mismatch')

    result = ack_dict['result']
    if not isinstance(result, dict):
        raise CaptureSupervisorQuarantineError('close_ack_result_invalid', 'close ack result is not dict')
    try:
        _require_keys(result, _CLOSE_ACK_RESULT_KEYS)
    except Exception as exc:
        raise CaptureSupervisorQuarantineError('close_ack_result_shape_invalid', f'close ack result shape invalid: {exc}') from exc

    event_hash = result['event_hash']
    if not isinstance(event_hash, str) or not _SHA256_RE.fullmatch(event_hash):
        raise CaptureSupervisorQuarantineError('close_ack_hash_invalid', 'close ack event_hash is invalid')
    state = result['state']
    if not isinstance(state, str) or not state:
        raise CaptureSupervisorQuarantineError('close_ack_state_invalid', 'close ack state is invalid')
    return ack_dict


def _rehash_closed_session(
    receipt_root: Path,
    session_id: str,
    hands_commit: str,
    close_ack: dict[str, Any],
    scorer_module: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        events = scorer_module._verify_receipt_directory(
            receipt_root,
            session_id,
            expected_session_id=session_id,
            hands_commit=hands_commit,
        )
    except Exception as exc:
        raise CaptureSupervisorQuarantineError('rehash_failed', f'independent receipt rehash failed: {exc}') from exc

    if not events:
        raise CaptureSupervisorQuarantineError('rehash_empty', 'rehash produced zero events')
    if events[0].get('kind') != 'worker_started':
        raise CaptureSupervisorQuarantineError('first_event_not_started', 'first event is not worker_started')
    if events[-1].get('kind') != 'worker_closed':
        raise CaptureSupervisorQuarantineError('last_event_not_closed', 'last event is not worker_closed')

    ack_result = close_ack['result']
    ack_hash = ack_result['event_hash']
    ack_state = ack_result['state']

    if events[-1].get('event_hash') != ack_hash:
        raise CaptureSupervisorQuarantineError(
            'terminal_hash_mismatch',
            f"terminal event hash {events[-1].get('event_hash')} != close ACK {ack_hash}",
        )

    # Read worker_closed raw payload to verify final_state
    session_dir = receipt_root / session_id
    closed_prefix = f"{len(events):06d}-worker_closed"
    raw_path = session_dir / f"{closed_prefix}.raw"
    if not raw_path.exists():
        raise CaptureSupervisorQuarantineError('closed_raw_missing', 'worker_closed raw payload missing')
    try:
        closed_payload = json.loads(raw_path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise CaptureSupervisorQuarantineError('closed_raw_malformed', f'worker_closed raw payload malformed: {exc}') from exc

    if closed_payload.get('final_state') != ack_state:
        raise CaptureSupervisorQuarantineError(
            'closed_state_mismatch',
            f"worker_closed final_state {closed_payload.get('final_state')} != close ACK state {ack_state}",
        )

    rehash_summary = {
        'event_count': len(events),
        'first_kind': events[0]['kind'],
        'last_kind': events[-1]['kind'],
        'terminal_event_hash': events[-1]['event_hash'],
        'verified': True,
    }
    return rehash_summary, events


def _write_export_once(
    export_root: Path,
    export_receipt: str,
    export_data: dict[str, Any],
) -> None:
    parent_fd, filename = _resolve_export_target(export_root, export_receipt)
    export_bytes = _canonical_json_bytes(export_data)

    try:
        try:
            fd = os.open(
                filename,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError as exc:
            raise CaptureSupervisorQuarantineError('export_exists', f'export receipt {filename} already exists') from exc
        except OSError as exc:
            raise CaptureSupervisorQuarantineError('export_create_failed', f'unable to create export receipt: {exc}') from exc

        try:
            written = os.write(fd, export_bytes)
            if written != len(export_bytes):
                raise CaptureSupervisorQuarantineError('export_short_write', 'short write writing export receipt')
            os.fchmod(fd, 0o600)
            os.fsync(fd)
        finally:
            os.close(fd)

        os.fsync(parent_fd)

        # Readback verification descriptor-relative to parent_fd with O_NOFOLLOW
        try:
            read_fd = os.open(
                filename,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise CaptureSupervisorQuarantineError('export_readback_open_failed', f'unable to open export receipt for readback: {exc}') from exc

        try:
            metadata = os.fstat(read_fd)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise CaptureSupervisorQuarantineError('export_invalid_mode', 'export receipt file mode is not 0600')
            if metadata.st_nlink != 1 or metadata.st_uid != os.getuid():
                raise CaptureSupervisorQuarantineError('export_invalid_owner', 'export receipt link count or owner invalid')
            readback = os.read(read_fd, len(export_bytes) + 1)
        finally:
            os.close(read_fd)

        if readback != export_bytes:
            raise CaptureSupervisorQuarantineError('export_readback_mismatch', 'export receipt readback mismatch')
    finally:
        os.close(parent_fd)


def _quarantine(
    failure_code: str,
    worker: subprocess.Popen[str] | None = None,
    last_hash: str | None = None,
) -> int:
    worker_exit_code: int | None = None
    if worker is not None:
        if worker.poll() is None:
            if worker.stdin:
                try:
                    worker.stdin.close()
                except Exception:
                    pass
            try:
                worker.terminate()
                worker.wait(timeout=2.0)
            except (subprocess.TimeoutExpired, Exception):
                try:
                    worker.kill()
                    worker.wait(timeout=2.0)
                except Exception:
                    pass
        worker_exit_code = worker.poll()

    envelope = {
        'failure_code': failure_code,
        'last_verified_event_hash': last_hash,
        'ok': False,
        'status': 'quarantined',
        'worker_exit_code': worker_exit_code,
    }
    sys.stdout.write(json.dumps(envelope, sort_keys=True, separators=(',', ':')) + '\n')
    sys.stdout.flush()
    return 2


def _attest_export_root(export_root: Path, public_roots: list[str]) -> str:
    metadata = os.lstat(export_root)
    payload = {
        'absolute_root': True,
        'canonical_json': True,
        'create_once': True,
        'directory_mode': '0700',
        'export_root_realpath': str(export_root.resolve(strict=True)),
        'file_mode': '0600',
        'fsync': True,
        'no_symlink_traversal': True,
        'outside_public_repository': True,
        'owner_uid': metadata.st_uid,
        'public_repo_roots': sorted(public_roots),
        'schema_version': 'supervised_ui_capture_export_root_attestation_v1',
    }
    return _sha256_hex(_canonical_json_bytes(payload))


def main() -> int:
    repo_fd: int = -1
    scorer_module: Any = None
    try:
        args = build_parser().parse_args()
        if (
            not math.isfinite(args.close_ack_timeout_seconds)
            or args.close_ack_timeout_seconds <= 0
            or not math.isfinite(args.worker_exit_timeout_seconds)
            or args.worker_exit_timeout_seconds <= 0
        ):
            refusal = {
                'child_created': False,
                'error': 'timeouts must be positive floats',
                'reveal': 'claim kind and refusal code only; no private root or target path',
                'status': 'refused_preflight',
                'ui_action_count': 0,
            }
            sys.stdout.write(json.dumps(refusal, sort_keys=True, separators=(',', ':')) + '\n')
            sys.stdout.flush()
            return 2

        public_roots = [REPO_ROOT.resolve(strict=True)]
        for pub in args.public_repo_root:
            try:
                public_roots.append(Path(pub).resolve(strict=True))
            except Exception:
                refusal = {
                    'child_created': False,
                    'error': f'public repo root {pub} could not be resolved',
                    'reveal': 'claim kind and refusal code only; no private root or target path',
                    'status': 'refused_preflight',
                    'ui_action_count': 0,
                }
                sys.stdout.write(json.dumps(refusal, sort_keys=True, separators=(',', ':')) + '\n')
                sys.stdout.flush()
                return 2

        # Preflight fresh session
        try:
            receipt_root, export_root, export_receipt_posix, scorer_module, repo_fd = _preflight_fresh_session(args, public_roots)
        except CaptureSupervisorPreflightError as exc:
            refusal = {
                'child_created': False,
                'error': exc.failure_code,
                'reveal': 'claim kind and refusal code only; no private root or target path',
                'status': 'refused_preflight',
                'ui_action_count': 0,
            }
            sys.stdout.write(json.dumps(refusal, sort_keys=True, separators=(',', ':')) + '\n')
            sys.stdout.flush()
            return 2
        except Exception as exc:
            refusal = {
                'child_created': False,
                'error': f'preflight_failed: {exc}',
                'reveal': 'claim kind and refusal code only; no private root or target path',
                'status': 'refused_preflight',
                'ui_action_count': 0,
            }
            sys.stdout.write(json.dumps(refusal, sort_keys=True, separators=(',', ':')) + '\n')
            sys.stdout.flush()
            return 2

        # Launch worker
        resolved_public_roots_str = sorted({str(r) for r in public_roots})
        try:
            worker = _launch_worker(args, resolved_public_roots_str)
        except Exception as exc:
            return _quarantine(f'launch_worker_failed: {exc}')

        # Read and relay worker handshake
        try:
            handshake_line = _read_worker_line(worker, timeout=args.close_ack_timeout_seconds)
            handshake_dict = _strict_json(handshake_line)
            if handshake_dict.get('type') != 'handshake' or handshake_dict.get('ok') is not True:
                return _quarantine('handshake_invalid', worker)
            sys.stdout.write(handshake_line)
            sys.stdout.flush()
        except Exception as exc:
            return _quarantine(f'handshake_failed: {exc}', worker)

        # Relay loop
        for raw_line in sys.stdin:
            if len(raw_line.encode('utf-8')) > _REQUEST_LIMIT:
                return _quarantine('request_too_large', worker)
            try:
                request = _strict_json(raw_line)
            except Exception:
                return _quarantine('protocol_invalid', worker)

            command = request.get('command')
            if command in {'execute_approved', 'observe'}:
                try:
                    resp_line = _relay_request(worker, raw_line)
                    sys.stdout.write(resp_line)
                    sys.stdout.flush()
                except Exception as exc:
                    return _quarantine(f'relay_failed: {exc}', worker)
                continue

            if command == 'cancel':
                try:
                    resp_line = _relay_request(worker, raw_line)
                    sys.stdout.write(resp_line)
                    sys.stdout.flush()
                    worker.wait(timeout=args.worker_exit_timeout_seconds)
                    return 0
                except Exception as exc:
                    return _quarantine(f'cancel_failed: {exc}', worker)

            if command == 'close':
                try:
                    _require_keys(request, frozenset({'command', 'request_id'}))
                    request_id = _uuid_text(request['request_id'])
                except Exception:
                    return _quarantine('close_request_invalid', worker)

                close_request_dict = dict(request)
                try:
                    ack_dict = _close_ack(worker, close_request_dict, timeout=args.close_ack_timeout_seconds)
                except CaptureSupervisorQuarantineError as exc:
                    return _quarantine(exc.failure_code, worker, exc.last_hash)
                except Exception as exc:
                    return _quarantine(f'close_ack_failed: {exc}', worker)

                # Wait for worker exit code 0
                try:
                    exit_code = worker.wait(timeout=args.worker_exit_timeout_seconds)
                    if exit_code != 0:
                        return _quarantine('worker_exit_nonzero', worker)
                except subprocess.TimeoutExpired:
                    return _quarantine('worker_exit_timeout', worker)
                except Exception as exc:
                    return _quarantine(f'worker_wait_failed: {exc}', worker)

                # Independent rehash
                try:
                    rehash_summary, events = _rehash_closed_session(
                        receipt_root,
                        args.session_id,
                        args.hands_commit,
                        ack_dict,
                        scorer_module,
                    )
                except CaptureSupervisorQuarantineError as exc:
                    return _quarantine(exc.failure_code, worker, exc.last_hash)
                except Exception as exc:
                    return _quarantine(f'rehash_failed: {exc}', worker)

                # Compute capture content sha256
                capture_script_path = REPO_ROOT / 'scripts' / 'run_supervised_ui_capture.py'
                capture_content_sha256 = _sha256_hex(capture_script_path.read_bytes())
                export_root_attestation_sha = _attest_export_root(export_root, resolved_public_roots_str)

                export_data = {
                    'capture_entrypoint_content_sha256': capture_content_sha256,
                    'capture_implementation_commit': args.hands_commit,
                    'close_ack': ack_dict,
                    'close_ack_sha256': _sha256_hex(_canonical_json_bytes(ack_dict)),
                    'close_request': close_request_dict,
                    'close_request_sha256': _sha256_hex(_canonical_json_bytes(close_request_dict)),
                    'display': args.display,
                    'export_root_attestation_sha256': export_root_attestation_sha,
                    'hands_commit': args.hands_commit,
                    'platform': args.platform,
                    'presence_incarnation_id': args.presence_incarnation_id,
                    'rehash': rehash_summary,
                    'schema_version': 'supervised_ui_capture_export_v1',
                    'seat_receipt_session': {
                        'receipt_directory': args.session_id,
                        'role': 'exercise',
                        'session_id': args.session_id,
                        'terminal_event_hash': rehash_summary['terminal_event_hash'],
                    },
                    'session_id': args.session_id,
                    'status': 'closed',
                    'worker_entrypoint': 'scripts/run_supervised_ui_seat.py',
                    'worker_exit_code': 0,
                }

                try:
                    _write_export_once(export_root, export_receipt_posix, export_data)
                except CaptureSupervisorQuarantineError as exc:
                    return _quarantine(exc.failure_code, worker, exc.last_hash)
                except Exception as exc:
                    return _quarantine(f'export_write_failed: {exc}', worker)

                terminal_envelope = {
                    'export_receipt_path': export_receipt_posix,
                    'ok': True,
                    'rehash': rehash_summary,
                    'request_id': request_id,
                    'status': 'closed',
                }
                sys.stdout.write(json.dumps(terminal_envelope, sort_keys=True, separators=(',', ':')) + '\n')
                sys.stdout.flush()
                return 0

            return _quarantine('unknown_command', worker)

        # Worker EOF before close
        return _quarantine('worker_eof_before_close', worker)
    finally:
        if repo_fd >= 0:
            os.close(repo_fd)
        if scorer_module is not None and getattr(scorer_module, '__package__', None):
            pkg_name = scorer_module.__package__
            for name in [
                pkg_name,
                f'{pkg_name}.types',
                f'{pkg_name}.supervised_ui_contract',
                f'{pkg_name}.ui_lane_production_scorer',
            ]:
                sys.modules.pop(name, None)


if __name__ == '__main__':
    sys.exit(main())
