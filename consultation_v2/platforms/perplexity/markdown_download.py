from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import time


def markdown_download_dirs() -> tuple[Path, ...]:
    candidates = [Path.home() / "Downloads"]
    configured = str(os.environ.get("XDG_DOWNLOAD_DIR") or "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate)
        if marker not in seen:
            seen.add(marker)
            unique.append(candidate)
    return tuple(unique)


def snapshot_markdown_downloads() -> dict[str, tuple[int, int]]:
    state: dict[str, tuple[int, int]] = {}
    available = False
    for directory in markdown_download_dirs():
        if not directory.is_dir():
            continue
        available = True
        for path in directory.glob("*.md"):
            try:
                stat = path.stat()
            except OSError as exc:
                raise OSError(
                    f"could not stat Markdown download candidate {path}: {exc}"
                ) from exc
            state[str(path)] = (int(stat.st_mtime_ns), int(stat.st_size))
    if not available:
        raise OSError(
            "Perplexity Markdown download directory is unavailable: "
            + ", ".join(str(path) for path in markdown_download_dirs())
        )
    return state


def read_new_markdown_download(
    before: dict[str, tuple[int, int]],
    *,
    timeout: float = 15.0,
) -> tuple[bytes, dict[str, object]]:
    deadline = time.monotonic() + timeout
    stable: dict[str, tuple[int, int]] = {}
    changed_paths: set[str] = set()
    rejected_paths: set[str] = set()
    while time.monotonic() < deadline:
        ready: list[
            tuple[
                Path,
                str,
                bytes,
                list[tuple[str, str]],
                list[tuple[str, str]],
            ]
        ] = []
        for directory in markdown_download_dirs():
            if not directory.is_dir():
                continue
            for path in directory.glob("*.md"):
                try:
                    stat = path.stat()
                    current = (int(stat.st_mtime_ns), int(stat.st_size))
                except OSError as exc:
                    raise OSError(
                        f"could not inspect Markdown download candidate {path}: {exc}"
                    ) from exc
                if before.get(str(path)) == current or current[1] <= 0:
                    continue
                changed_paths.add(str(path))
                try:
                    raw_bytes = path.read_bytes()
                except OSError as exc:
                    raise OSError(
                        f"could not read Markdown download candidate {path}: {exc}"
                    ) from exc
                raw = raw_bytes.decode("utf-8", errors="replace").strip()
                definitions = re.findall(
                    r"^\[\^([0-9]+)\]:\s+(.+?)\s*$",
                    raw,
                    flags=re.MULTILINE,
                )
                source_urls = [
                    (source_id, value)
                    for source_id, value in definitions
                    if re.match(r"^https?://\S+$", value)
                ]
                if not raw or not definitions:
                    stable[str(path)] = current
                    rejected_paths.add(str(path))
                    continue
                if stable.get(str(path)) == current:
                    ready.append((path, raw, raw_bytes, definitions, source_urls))
                stable[str(path)] = current
        if len(ready) > 1:
            return b"", {
                "download_error": "multiple complete Markdown downloads appeared",
                "download_candidates": sorted(str(item[0]) for item in ready),
                "download_timeout_seconds": timeout,
            }
        if len(ready) == 1:
            path, raw, raw_bytes, definitions, source_urls = ready[0]
            body = "\n".join(
                line
                for line in raw.splitlines()
                if not re.fullmatch(r"\[\^[0-9]+\]:\s+.+?\s*", line)
            )
            citation_ids = sorted(
                {int(value) for value in re.findall(r"\[\^([0-9]+)\]", body)}
            )
            source_ids = {int(item[0]) for item in definitions}
            source_url_ids = {int(item[0]) for item in source_urls}
            return raw_bytes, {
                "download_path": str(path),
                "download_bytes": len(raw_bytes),
                "download_characters": len(raw),
                "download_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "citation_ids": citation_ids,
                "markdown_source_ids": sorted(source_ids),
                "markdown_source_definition_count": len(definitions),
                "markdown_source_url_count": len({item[1] for item in source_urls}),
                "markdown_non_url_source_ids": sorted(source_ids - source_url_ids),
                "markdown_non_url_source_count": len(source_ids - source_url_ids),
            }
        time.sleep(0.25)
    return b"", {
        "download_error": "no unique complete Markdown download appeared",
        "download_changed_candidates": sorted(changed_paths),
        "download_rejected_candidates": sorted(rejected_paths),
        "download_timeout_seconds": timeout,
    }
