from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Callable


_PARTIAL_SUFFIXES = (".crdownload", ".download", ".part", ".tmp")
_PREF_RE = re.compile(
    r'^user_pref\("(?P<key>(?:[^"\\]|\\.)+)",\s*(?P<value>.+)\);$'
)


class ClaudeArtifactDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaudeDownloadScope:
    display: str
    firefox_pid: int
    process_start_ticks: int
    profile_path: Path
    preferences_path: Path
    download_preferences_sha256: str
    directory: Path
    directory_source: str


@dataclass(frozen=True)
class DownloadEntry:
    device: int
    inode: int
    mode: int
    link_count: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class ClaudeDownloadSnapshot:
    scope: ClaudeDownloadScope
    entries: dict[str, DownloadEntry]


def _preference_values(preferences_path: Path) -> dict[str, object]:
    if preferences_path.is_symlink() or not preferences_path.is_file():
        raise ClaudeArtifactDownloadError(
            f"Claude Firefox preferences are unavailable: {preferences_path}"
        )
    try:
        preference_text = preferences_path.read_text(
            encoding="utf-8",
            errors="strict",
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise ClaudeArtifactDownloadError(
            "Claude Firefox preferences could not be read exactly"
        ) from exc
    values: dict[str, object] = {}
    for line in preference_text.splitlines():
        match = _PREF_RE.fullmatch(line)
        if match is None:
            continue
        key = json.loads(f'"{match.group("key")}"')
        if key not in {
            "browser.download.dir",
            "browser.download.folderList",
            "browser.download.useDownloadDir",
        }:
            continue
        if key in values:
            raise ClaudeArtifactDownloadError(
                f"Claude Firefox preference is duplicated: {key}"
            )
        try:
            values[key] = json.loads(match.group("value"))
        except json.JSONDecodeError as exc:
            raise ClaudeArtifactDownloadError(
                f"Claude Firefox preference is malformed: {key}"
            ) from exc
    return values


def _download_directory(
    profile_path: Path,
    *,
    home: Path,
) -> tuple[Path, Path, str, str]:
    preferences_path = profile_path / "prefs.js"
    values = _preference_values(preferences_path)
    if values.get("browser.download.useDownloadDir", True) is not True:
        raise ClaudeArtifactDownloadError(
            "Claude Firefox is configured to ask for a download directory"
        )
    folder_list = values.get("browser.download.folderList", 1)
    if isinstance(folder_list, bool) or not isinstance(folder_list, int):
        raise ClaudeArtifactDownloadError(
            "Claude Firefox browser.download.folderList is not an integer"
        )
    if folder_list == 0:
        directory = home / "Desktop"
        source = "profile_pref_desktop"
    elif folder_list == 1:
        directory = home / "Downloads"
        source = "profile_pref_default_downloads"
    elif folder_list == 2:
        configured = values.get("browser.download.dir")
        if not isinstance(configured, str) or not configured:
            raise ClaudeArtifactDownloadError(
                "Claude Firefox custom download directory is missing"
            )
        directory = Path(configured).expanduser()
        if not directory.is_absolute():
            raise ClaudeArtifactDownloadError(
                "Claude Firefox custom download directory is not absolute"
            )
        source = "profile_pref_custom"
    else:
        raise ClaudeArtifactDownloadError(
            f"Claude Firefox browser.download.folderList is unsupported: {folder_list}"
        )
    if directory.is_symlink() or not directory.is_dir():
        raise ClaudeArtifactDownloadError(
            f"Claude Firefox download directory is unavailable: {directory}"
        )
    download_preferences_sha256 = hashlib.sha256(
        json.dumps(
            {
                "browser.download.dir": values.get("browser.download.dir"),
                "browser.download.folderList": folder_list,
                "browser.download.useDownloadDir": values.get(
                    "browser.download.useDownloadDir",
                    True,
                ),
            },
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    try:
        directory = directory.resolve(strict=True)
    except OSError as exc:
        raise ClaudeArtifactDownloadError(
            "Claude Firefox download directory could not be resolved"
        ) from exc
    return directory, preferences_path, source, download_preferences_sha256


def resolve_claude_download_scope(display: str) -> ClaudeDownloadScope:
    if re.fullmatch(r":[1-9][0-9]*", display) is None:
        raise ClaudeArtifactDownloadError(f"invalid Claude display: {display!r}")
    pid_path = Path(f"/tmp/firefox_pid_{display}")
    if pid_path.is_symlink() or not pid_path.is_file():
        raise ClaudeArtifactDownloadError(
            f"Claude Firefox PID evidence is unavailable: {pid_path}"
        )
    try:
        raw_pid = pid_path.read_text(encoding="ascii", errors="strict").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise ClaudeArtifactDownloadError(
            "Claude Firefox PID evidence could not be read exactly"
        ) from exc
    if re.fullmatch(r"[1-9][0-9]*", raw_pid) is None:
        raise ClaudeArtifactDownloadError("Claude Firefox PID evidence is malformed")
    firefox_pid = int(raw_pid)
    command_path = Path("/proc") / raw_pid / "cmdline"
    try:
        arguments = [
            item.decode("utf-8", errors="strict")
            for item in command_path.read_bytes().split(b"\0")
            if item
        ]
    except (OSError, UnicodeDecodeError) as exc:
        raise ClaudeArtifactDownloadError(
            "Claude Firefox command-line evidence is unavailable"
        ) from exc
    if not arguments or Path(arguments[0]).name not in {"firefox", "firefox-bin"}:
        raise ClaudeArtifactDownloadError(
            "Claude Firefox PID does not identify a Firefox process"
        )
    try:
        environment_items = [
            item.decode("utf-8", errors="strict")
            for item in (Path("/proc") / raw_pid / "environ").read_bytes().split(b"\0")
            if item
        ]
        stat_fields = (
            (Path("/proc") / raw_pid / "stat")
            .read_text(encoding="ascii", errors="strict")
            .rsplit(")", 1)[1]
            .split()
        )
        process_start_ticks = int(stat_fields[19])
    except (IndexError, OSError, UnicodeDecodeError, ValueError) as exc:
        raise ClaudeArtifactDownloadError(
            "Claude Firefox process identity is unavailable"
        ) from exc
    display_values = [
        item.split("=", 1)[1]
        for item in environment_items
        if item.startswith("DISPLAY=")
    ]
    if display_values != [display]:
        raise ClaudeArtifactDownloadError(
            "Claude Firefox process is not bound to the requested display"
        )
    profile_indexes = [
        index for index, value in enumerate(arguments) if value == "--profile"
    ]
    if len(profile_indexes) != 1 or profile_indexes[0] + 1 >= len(arguments):
        raise ClaudeArtifactDownloadError(
            "Claude Firefox command line has no unique profile"
        )
    profile_path = Path(arguments[profile_indexes[0] + 1])
    if (
        not profile_path.is_absolute()
        or profile_path.is_symlink()
        or not profile_path.is_dir()
    ):
        raise ClaudeArtifactDownloadError(
            "Claude Firefox profile evidence is not an absolute regular directory"
        )
    try:
        profile_path = profile_path.resolve(strict=True)
    except OSError as exc:
        raise ClaudeArtifactDownloadError(
            "Claude Firefox profile could not be resolved"
        ) from exc
    directory, preferences_path, source, download_preferences_sha256 = (
        _download_directory(
            profile_path,
            home=Path.home(),
        )
    )
    return ClaudeDownloadScope(
        display=display,
        firefox_pid=firefox_pid,
        process_start_ticks=process_start_ticks,
        profile_path=profile_path,
        preferences_path=preferences_path,
        download_preferences_sha256=download_preferences_sha256,
        directory=directory,
        directory_source=source,
    )


def _scan_directory(directory: Path) -> dict[str, DownloadEntry]:
    entries: dict[str, DownloadEntry] = {}
    try:
        iterator = os.scandir(directory)
    except OSError as exc:
        raise ClaudeArtifactDownloadError(
            f"could not scan Claude download directory: {directory}"
        ) from exc
    with iterator:
        for item in iterator:
            try:
                details = item.stat(follow_symlinks=False)
            except OSError as exc:
                raise ClaudeArtifactDownloadError(
                    f"could not inspect Claude download candidate: {item.name}"
                ) from exc
            entries[item.name] = DownloadEntry(
                device=int(details.st_dev),
                inode=int(details.st_ino),
                mode=int(details.st_mode),
                link_count=int(details.st_nlink),
                size=int(details.st_size),
                mtime_ns=int(details.st_mtime_ns),
            )
    return entries


def snapshot_claude_downloads(scope: ClaudeDownloadScope) -> ClaudeDownloadSnapshot:
    return ClaudeDownloadSnapshot(
        scope=scope,
        entries=_scan_directory(scope.directory),
    )


def _read_stable_source(path: Path, expected: DownloadEntry) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ClaudeArtifactDownloadError(
            f"could not open Claude download candidate: {path.name}"
        ) from exc
    try:
        details = os.fstat(descriptor)
        observed = DownloadEntry(
            device=int(details.st_dev),
            inode=int(details.st_ino),
            mode=int(details.st_mode),
            link_count=int(details.st_nlink),
            size=int(details.st_size),
            mtime_ns=int(details.st_mtime_ns),
        )
        if observed != expected or not stat.S_ISREG(observed.mode):
            raise ClaudeArtifactDownloadError(
                "Claude download candidate changed before materialization"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            int(after.st_size) != len(raw)
            or int(after.st_mtime_ns) != expected.mtime_ns
            or int(after.st_ino) != expected.inode
            or int(after.st_dev) != expected.device
        ):
            raise ClaudeArtifactDownloadError(
                "Claude download candidate changed while being read"
            )
        return raw
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ClaudeArtifactDownloadError(
            f"could not create exclusive Claude extraction output: {path.name}"
        ) from exc
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ClaudeArtifactDownloadError(
                    "Claude extraction output write made no progress"
                )
            view = view[written:]
        os.fsync(descriptor)
    except OSError as exc:
        raise ClaudeArtifactDownloadError(
            f"could not persist Claude extraction output: {path.name}"
        ) from exc
    finally:
        os.close(descriptor)
    try:
        details = path.lstat()
    except OSError as exc:
        raise ClaudeArtifactDownloadError(
            f"could not verify Claude extraction output: {path.name}"
        ) from exc
    expected = DownloadEntry(
        device=int(details.st_dev),
        inode=int(details.st_ino),
        mode=int(details.st_mode),
        link_count=int(details.st_nlink),
        size=int(details.st_size),
        mtime_ns=int(details.st_mtime_ns),
    )
    if (
        not stat.S_ISREG(expected.mode)
        or expected.link_count != 1
        or stat.S_IMODE(expected.mode) != 0o600
        or expected.size != len(content)
        or _read_stable_source(path, expected) != content
    ):
        raise ClaudeArtifactDownloadError(
            f"Claude extraction output failed exact readback: {path.name}"
        )
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    try:
        parent_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except OSError as exc:
        raise ClaudeArtifactDownloadError(
            f"could not fsync Claude extraction output directory: {path.parent}"
        ) from exc


def materialize_claude_download(
    before: ClaudeDownloadSnapshot,
    destination: Path,
    *,
    timeout: float = 15.0,
    interval: float = 0.25,
    stable_cycles: int = 2,
    scope_resolver: Callable[[str], ClaudeDownloadScope] = (
        resolve_claude_download_scope
    ),
) -> dict[str, object]:
    if timeout <= 0 or interval <= 0 or stable_cycles < 2:
        raise ClaudeArtifactDownloadError("invalid Claude download observation policy")
    if destination.exists() or destination.is_symlink():
        raise ClaudeArtifactDownloadError(
            f"Claude extraction destination already exists: {destination}"
        )
    destination_parent = destination.parent
    if destination_parent.is_symlink() or not destination_parent.is_dir():
        raise ClaudeArtifactDownloadError(
            "Claude extraction destination parent is unavailable"
        )
    deadline = time.monotonic() + timeout
    last_candidate: tuple[str, DownloadEntry] | None = None
    stable_count = 0
    last_rejections: dict[str, list[str]] = {}
    while time.monotonic() < deadline:
        current = _scan_directory(before.scope.directory)
        changed_existing = sorted(
            name
            for name, entry in before.entries.items()
            if name not in current or current[name] != entry
        )
        new_entries = {
            name: entry
            for name, entry in current.items()
            if name not in before.entries
        }
        symlinks = sorted(
            name for name, entry in new_entries.items() if stat.S_ISLNK(entry.mode)
        )
        nonregular = sorted(
            name
            for name, entry in new_entries.items()
            if not stat.S_ISREG(entry.mode) and not stat.S_ISLNK(entry.mode)
        )
        partial = sorted(
            name
            for name, entry in new_entries.items()
            if stat.S_ISREG(entry.mode)
            and name.casefold().endswith(_PARTIAL_SUFFIXES)
        )
        empty = sorted(
            name
            for name, entry in new_entries.items()
            if stat.S_ISREG(entry.mode)
            and not name.casefold().endswith(_PARTIAL_SUFFIXES)
            and entry.size <= 0
        )
        duplicate = sorted(
            name
            for name, entry in new_entries.items()
            if stat.S_ISREG(entry.mode) and entry.link_count != 1
        )
        candidates = sorted(
            (
                (name, entry)
                for name, entry in new_entries.items()
                if stat.S_ISREG(entry.mode)
                and not name.casefold().endswith(_PARTIAL_SUFFIXES)
                and entry.size > 0
                and entry.link_count == 1
            ),
            key=lambda item: item[0],
        )
        last_rejections = {
            "changed_existing": changed_existing,
            "duplicate": duplicate,
            "empty": empty,
            "nonregular": nonregular,
            "partial": partial,
            "symlink": symlinks,
        }
        if changed_existing or symlinks or nonregular or duplicate:
            raise ClaudeArtifactDownloadError(
                "Claude download manifest changed ambiguously: "
                + json.dumps(last_rejections, sort_keys=True)
            )
        if len(candidates) > 1:
            raise ClaudeArtifactDownloadError(
                "multiple complete Claude downloads appeared: "
                + json.dumps([name for name, _entry in candidates])
            )
        if len(candidates) == 1 and not partial and not empty:
            candidate = candidates[0]
            if candidate == last_candidate:
                stable_count += 1
            else:
                last_candidate = candidate
                stable_count = 1
            if stable_count >= stable_cycles:
                name, entry = candidate
                source_path = before.scope.directory / name
                raw = _read_stable_source(source_path, entry)
                if not raw:
                    raise ClaudeArtifactDownloadError(
                        "Claude download candidate became empty"
                    )
                if scope_resolver(before.scope.display) != before.scope:
                    raise ClaudeArtifactDownloadError(
                        "Claude Firefox download scope changed before materialization"
                    )
                if _scan_directory(before.scope.directory) != current:
                    raise ClaudeArtifactDownloadError(
                        "Claude download manifest changed before materialization"
                    )
                _write_exclusive(destination, raw)
                digest = hashlib.sha256(raw).hexdigest()
                return {
                    "schema": "taey.claude_download_materialization.v1",
                    "stable_cycles": stable_count,
                    "source": {
                        "path": str(source_path),
                        "directory": str(before.scope.directory),
                        "directory_source": before.scope.directory_source,
                        "firefox_pid": before.scope.firefox_pid,
                        "process_start_ticks": before.scope.process_start_ticks,
                        "profile_path": str(before.scope.profile_path),
                        "preferences_path": str(before.scope.preferences_path),
                        "download_preferences_sha256": (
                            before.scope.download_preferences_sha256
                        ),
                        "device": entry.device,
                        "inode": entry.inode,
                        "mode": stat.S_IMODE(entry.mode),
                        "bytes": len(raw),
                        "sha256": digest,
                    },
                    "destination": {
                        "path": str(destination),
                        "bytes": len(raw),
                        "sha256": digest,
                    },
                }
        else:
            last_candidate = None
            stable_count = 0
        time.sleep(interval)
    raise ClaudeArtifactDownloadError(
        "no unique stable Claude download appeared: "
        + json.dumps(last_rejections, sort_keys=True)
    )


def write_download_receipt(path: Path, receipt: dict[str, object]) -> None:
    payload = (
        json.dumps(
            receipt,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    _write_exclusive(path, payload)
