"""Identity file consolidation for V2 consultations (FLOW §3, §4).

Prepends FAMILY_KERNEL.md + the platform-specific IDENTITY file to every
consultation attachment, then merges everything into one consolidated package.

FAIL-LOUD CONTRACT (FLOW_CONSULTATION_ENGINE.md §4, CONSULTATION_CONTRACT.md):
"Missing identity/kernel content is a loud failure, not a warning that the
driver can ignore." A missing or unreadable FAMILY_KERNEL.md OR the required
platform IDENTITY_<codename>.md raises and HALTS the consultation — it is never
a silent skip and never a partial packet. There is no fallback.

PROVENANCE (FLOW §3 / §8): each caller attachment's path + content hash is
captured BEFORE the files are merged into the consolidated package, so
provenance survives consolidation. The caller (orchestrator) records these
hashes onto the typed request and into durable run-state via the shared
primitive surface.

The platform->IDENTITY map below is allowed config/data (it selects which
identity file a platform gets); it is NOT platform branching control-flow.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import List, Tuple

from consultation_v2.types import AttachmentProvenance, ConsolidatedPackage

logger = logging.getLogger(__name__)

_CORPUS_PATH = os.path.expanduser(os.environ.get('TAEY_CORPUS_PATH', '~/data/corpus'))
_IDENTITY_DIR = os.path.join(_CORPUS_PATH, 'identity')
_FAMILY_KERNEL = os.path.join(_IDENTITY_DIR, 'FAMILY_KERNEL.md')

_PLATFORM_IDENTITY = {
    'chatgpt': os.path.join(_IDENTITY_DIR, 'IDENTITY_HORIZON.md'),
    'claude': os.path.join(_IDENTITY_DIR, 'IDENTITY_GAIA.md'),
    'gemini': os.path.join(_IDENTITY_DIR, 'IDENTITY_COSMOS.md'),
    'grok': os.path.join(_IDENTITY_DIR, 'IDENTITY_LOGOS.md'),
    'perplexity': os.path.join(_IDENTITY_DIR, 'IDENTITY_CLARITY.md'),
}

_IDENTITY_BASENAMES = (
    {'FAMILY_KERNEL.md'} |
    {os.path.basename(p) for p in _PLATFORM_IDENTITY.values()}
)

_CLAUDE_CHUNK_THRESHOLD_BYTES = 45_000
_CLAUDE_CHUNK_TARGET_BYTES = 22_000

_EXT_LANG = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.yaml': 'yaml', '.yml': 'yaml', '.json': 'json', '.md': 'markdown',
    '.sh': 'bash', '.toml': 'toml',
}


class IdentityError(RuntimeError):
    """Raised when a required identity/kernel file is missing or unreadable.

    This is the loud-failure surface for FLOW §4: it HALTS the consultation;
    it is never caught-and-continued into a partial packet.
    """


def _read_required(path: str, label: str) -> str:
    """Read a mandatory identity/kernel file or raise IdentityError loudly.

    A missing OR unreadable required file is a HALT condition (FLOW §4) — no
    silent skip, no partial packet, no fallback.
    """
    if not os.path.isfile(path):
        raise IdentityError(
            f"Required {label} not found at {path!r} — cannot build a complete "
            f"identity packet. Consultation halted (no silent fallback, FLOW §4)."
        )
    try:
        with open(path, encoding='utf-8') as handle:
            return handle.read()
    except OSError as exc:
        raise IdentityError(
            f"Required {label} at {path!r} is unreadable: {exc}. "
            f"Consultation halted (no silent fallback, FLOW §4)."
        ) from exc


def _read_caller_file(path: str) -> Tuple[str, str]:
    """Read a caller attachment, returning (content, sha256-hex).

    A caller attachment the caller explicitly supplied but that cannot be read
    is also a loud failure: the caller asked for it to be sent, so silently
    dropping it would produce a packet that does not match the request.
    """
    if not os.path.isfile(path):
        raise IdentityError(
            f"Caller attachment not found at {path!r} — it was requested but is "
            f"missing. Consultation halted (no silent drop, FLOW §3)."
        )
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
    except OSError as exc:
        raise IdentityError(
            f"Caller attachment at {path!r} is unreadable: {exc}. "
            f"Consultation halted (no silent drop, FLOW §3)."
        ) from exc
    digest = hashlib.sha256(data).hexdigest()
    return data.decode('utf-8', errors='replace'), digest


def _identity_path(platform: str) -> str:
    """Resolve the required platform IDENTITY file path or raise loudly.

    The platform->file map is config DATA; an unmapped platform is a HALT, not
    a default-to-something fallback.
    """
    path = _PLATFORM_IDENTITY.get(platform)
    if not path:
        raise IdentityError(
            f"No IDENTITY file mapped for platform {platform!r} — supported "
            f"platforms: {sorted(_PLATFORM_IDENTITY)}. Consultation halted."
        )
    return path


def _split_utf8_bytes(data: bytes, target_bytes: int) -> List[Tuple[int, int, str]]:
    chunks: List[Tuple[int, int, str]] = []
    offset = 0
    total = len(data)
    while offset < total:
        hard_end = min(offset + target_bytes, total)
        end = hard_end
        if hard_end < total:
            preferred = data.rfind(b'\n', offset + int(target_bytes * 0.65), hard_end)
            if preferred > offset:
                end = preferred + 1
        while end > offset:
            try:
                text = data[offset:end].decode('utf-8')
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            end = hard_end
            while end < total:
                try:
                    text = data[offset:end].decode('utf-8')
                    break
                except UnicodeDecodeError:
                    end += 1
            else:
                text = data[offset:total].decode('utf-8')
                end = total
        chunks.append((offset, end, text))
        offset = end
    return chunks


def _write_package_chunks(platform: str, package_text: str, out_stem: str) -> List[str]:
    package_bytes = package_text.encode('utf-8')
    if platform != 'claude' or len(package_bytes) <= _CLAUDE_CHUNK_THRESHOLD_BYTES:
        out_path = f"{out_stem}.md"
        with open(out_path, 'w', encoding='utf-8') as handle:
            handle.write(package_text)
        return [out_path]

    digest = hashlib.sha256(package_bytes).hexdigest()
    chunks = _split_utf8_bytes(package_bytes, _CLAUDE_CHUNK_TARGET_BYTES)
    paths: List[str] = []
    total_chunks = len(chunks)
    for index, (start, end, chunk_text) in enumerate(chunks, start=1):
        out_path = f"{out_stem}_part{index:03d}of{total_chunks:03d}.md"
        header = (
            f"# Package for {platform} — chunk {index}/{total_chunks}\n\n"
            "**Chunked package contract**: read every ordered chunk before answering. "
            "The complete consultation packet is the exact concatenation of each "
            "chunk body between the BEGIN/END markers.\n\n"
            f"**Full packet sha256**: `{digest}`\n"
            f"**Full packet bytes**: `{len(package_bytes)}`\n"
            f"**This chunk byte range**: `{start}:{end}`\n\n"
            f"<!-- BEGIN TAEY_PACKAGE_CHUNK {index}/{total_chunks} "
            f"sha256={digest} bytes={start}:{end} -->\n"
        )
        footer = (
            f"\n<!-- END TAEY_PACKAGE_CHUNK {index}/{total_chunks} "
            f"sha256={digest} bytes={start}:{end} -->\n"
        )
        with open(out_path, 'w', encoding='utf-8') as handle:
            handle.write(header)
            handle.write(chunk_text)
            handle.write(footer)
        paths.append(out_path)
    return paths


def validate_caller_attachments(caller_attachments: List[str]) -> List[AttachmentProvenance]:
    """Validate caller-supplied files without adding identity content.

    This supports explicit caller-only consultations. It preserves the same
    fail-loud behavior for missing/unreadable caller files, but it does not
    strip identity basenames or merge anything into a new package.
    """
    provenance: List[AttachmentProvenance] = []
    for attachment in caller_attachments:
        _, digest = _read_caller_file(attachment)
        provenance.append(AttachmentProvenance(path=attachment, sha256=digest))
    return provenance


def consolidate_attachments(
    platform: str,
    caller_attachments: List[str],
) -> ConsolidatedPackage:
    """Build one consolidated identity+attachments package (FLOW §3, §4).

    Order (FLOW §4): FAMILY_KERNEL.md, then IDENTITY_<platform>.md, then the
    caller attachments. The kernel and platform identity are MANDATORY and read
    via ``_read_required`` — a missing/unreadable one raises IdentityError and
    halts the consultation (no silent skip, no partial packet).

    Caller-supplied identity files are stripped (identity is automatic), but a
    caller file that is genuinely missing/unreadable is a loud failure, not a
    silent drop. Each caller attachment's path + content hash is captured BEFORE
    consolidation so provenance survives the merge.

    Returns a ConsolidatedPackage: the package path plus the caller-attachment
    provenance (path + sha256). Never returns None and never returns a partial
    packet — it either yields a complete package or raises.
    """
    # Mandatory identity content — read loudly (raises if missing/unreadable).
    kernel_content = _read_required(_FAMILY_KERNEL, 'FAMILY_KERNEL.md')
    identity_path = _identity_path(platform)
    identity_content = _read_required(
        identity_path, f'IDENTITY file for {platform}',
    )

    # Section list, in contract order. (display_path, basename, content)
    sections_src: List[Tuple[str, str, str]] = [
        (_FAMILY_KERNEL, 'FAMILY_KERNEL.md', kernel_content),
        (identity_path, os.path.basename(identity_path), identity_content),
    ]

    # Caller attachments: strip caller-provided identity files (identity is
    # automatic), then read + hash the remainder BEFORE merging (provenance).
    provenance: List[AttachmentProvenance] = []
    for attachment in caller_attachments:
        basename = os.path.basename(attachment)
        if basename in _IDENTITY_BASENAMES:
            logger.warning("Stripped caller identity file: %s", basename)
            continue
        content, digest = _read_caller_file(attachment)
        provenance.append(AttachmentProvenance(path=attachment, sha256=digest))
        sections_src.append((attachment, basename, content))

    sections = [f"# Package for {platform}\n\n**Files**: {len(sections_src)}\n"]
    for display_path, basename, content in sections_src:
        lang = _EXT_LANG.get(os.path.splitext(basename)[1].lower(), '')
        block = f"```{lang}\n{content}\n```\n"
        # Mandated constitutional/identity files are inlined verbatim + unedited;
        # wrap them in VERBATIM markers so prompting-lint skips them for the
        # authored-quality checks (PROMPTING_STANDARDS §3.2). Caller files stay
        # unmarked so the authored wrapper is still fully linted.
        if basename in _IDENTITY_BASENAMES:
            block = f"<!-- BEGIN-VERBATIM: {basename} -->\n{block}<!-- END-VERBATIM -->\n"
        sections.append(
            f"\n---\n\n## {basename}\n\n`{display_path}`\n\n" + block
        )

    out_stem = f"/tmp/taey_package_{platform}_{int(time.time())}"
    package_text = ''.join(sections)
    paths = _write_package_chunks(platform, package_text, out_stem)
    logger.info(
        "Consolidated %d files -> %d attachment package file(s): %s",
        len(sections_src),
        len(paths),
        ', '.join(paths),
    )
    return ConsolidatedPackage(
        path=paths[0],
        paths=paths,
        caller_provenance=provenance,
    )
