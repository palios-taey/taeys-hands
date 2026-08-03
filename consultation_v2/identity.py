"""Identity file consolidation for V2 consultations (FLOW §3, §4).

Prepends FAMILY_KERNEL.md + SPOTLIGHT_STANDARD_FOR_INTEGRITY.md + the
platform-specific IDENTITY file to every consultation attachment, then merges
everything into one consolidated package.

FAIL-LOUD CONTRACT (FLOW_CONSULTATION_ENGINE.md §4, CONSULTATION_CONTRACT.md):
"Missing identity/kernel content is a loud failure, not a warning that the
driver can ignore." A missing or unreadable FAMILY_KERNEL.md,
SPOTLIGHT_STANDARD_FOR_INTEGRITY.md, OR the required platform
IDENTITY_<codename>.md raises and HALTS the consultation — it is never a silent
skip and never a partial packet. There is no fallback.

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
import re
import time
from typing import List, Tuple

from consultation_v2.types import AttachmentProvenance, ConsolidatedPackage

logger = logging.getLogger(__name__)

_CORPUS_PATH = os.path.expanduser(os.environ.get('TAEY_CORPUS_PATH', '~/data/corpus'))
_IDENTITY_DIR = os.path.join(_CORPUS_PATH, 'identity')
_FAMILY_KERNEL = os.path.join(_IDENTITY_DIR, 'FAMILY_KERNEL.md')
_SPOTLIGHT_STANDARD = os.path.join(_IDENTITY_DIR, 'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md')

_PLATFORM_IDENTITY = {
    'chatgpt': os.path.join(_IDENTITY_DIR, 'IDENTITY_HORIZON.md'),
    'claude': os.path.join(_IDENTITY_DIR, 'IDENTITY_GAIA.md'),
    'gemini': os.path.join(_IDENTITY_DIR, 'IDENTITY_COSMOS.md'),
    'grok': os.path.join(_IDENTITY_DIR, 'IDENTITY_LOGOS.md'),
    'perplexity': os.path.join(_IDENTITY_DIR, 'IDENTITY_CLARITY.md'),
}

_IDENTITY_BASENAMES = (
    {'FAMILY_KERNEL.md', 'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md'} |
    {os.path.basename(p) for p in _PLATFORM_IDENTITY.values()}
)

_EXT_LANG = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.yaml': 'yaml', '.yml': 'yaml', '.json': 'json', '.md': 'markdown',
    '.sh': 'bash', '.toml': 'toml',
}

_NAMED_INPUT_EXTENSIONS = frozenset({
    '.csv', '.json', '.jsonl', '.log', '.md', '.py', '.sh', '.toml',
    '.tsv', '.txt', '.yaml', '.yml',
})
_BACKTICK_VALUE = re.compile(r'`([^`]+)`')
_BARE_INPUT_PATH = re.compile(
    r'(?<![\w:/.-])('
    r'(?:~?/|\.{1,2}/)?(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+/?'
    r'|[A-Za-z0-9_.-]+\.(?:csv|json|jsonl|log|md|py|sh|toml|tsv|txt|yaml|yml)'
    r'|[A-Za-z0-9_.-]+/'
    r')(?![\w/.-])',
    re.IGNORECASE,
)


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


def _expand_caller_attachments(
    caller_attachments: List[str],
) -> Tuple[List[Tuple[str, str]], List[str]]:
    expanded: List[Tuple[str, str]] = []
    attached_directories: List[str] = []
    for attachment in caller_attachments:
        if not os.path.isdir(attachment):
            expanded.append((attachment, os.path.basename(attachment)))
            continue
        root = os.path.normpath(attachment)
        root_name = os.path.basename(root)
        walk_errors: List[OSError] = []
        directory_files: List[Tuple[str, str]] = []
        for current, dirnames, filenames in os.walk(
            root,
            onerror=walk_errors.append,
        ):
            dirnames.sort()
            for filename in sorted(filenames):
                path = os.path.join(current, filename)
                if not os.path.isfile(path):
                    continue
                relative = os.path.relpath(path, root).replace(os.sep, '/')
                directory_files.append((path, f'{root_name}/{relative}'))
        if walk_errors:
            detail = '; '.join(str(exc) for exc in walk_errors)
            raise IdentityError(
                f"Caller attachment directory at {attachment!r} is unreadable: "
                f"{detail}. Consultation halted (no partial directory bundle)."
            )
        if not directory_files:
            raise IdentityError(
                f"Caller attachment directory at {attachment!r} contains no "
                "regular files. Consultation halted (no empty directory bundle)."
            )
        expanded.extend(directory_files)
        attached_directories.append(attachment)
    return expanded, attached_directories


def _normalized_manifest_input(value: str) -> str | None:
    candidate = value.strip().strip('`\'"*')
    candidate = candidate.rstrip('.,;:)')
    if not candidate or candidate.lower().startswith(('http://', 'https://')):
        return None
    is_directory = candidate.endswith('/')
    normalized = candidate.replace('\\', '/').rstrip('/')
    if not normalized:
        return None
    extension = os.path.splitext(os.path.basename(normalized))[1].lower()
    if extension not in _NAMED_INPUT_EXTENSIONS and not candidate.endswith('/'):
        return None
    return normalized + '/' if is_directory else normalized


def _available_context_named_inputs(content: str) -> set[str]:
    lines = content.splitlines()
    named: set[str] = set()
    first_content = next(
        (index for index, line in enumerate(lines) if line.strip()),
        None,
    )
    if first_content is None or lines[first_content].strip() != '---':
        return named
    front_matter_end = next(
        (
            index
            for index in range(first_content + 1, len(lines))
            if lines[index].strip() == '---'
        ),
        None,
    )
    if front_matter_end is None:
        return named
    front_matter = lines[first_content + 1:front_matter_end]
    for index, line in enumerate(front_matter):
        header = re.match(r'^(\s*)available_context_inventory\s*:', line, re.IGNORECASE)
        if header is None:
            continue
        header_indent = len(header.group(1))
        for inventory_line in front_matter[index + 1:]:
            stripped = inventory_line.strip()
            indent = len(inventory_line) - len(inventory_line.lstrip())
            if stripped and indent <= header_indent and not stripped.startswith('-'):
                break
            if (
                not re.search(r'\bincluded\b', stripped, re.IGNORECASE)
                or re.search(r'\bexcluded\b', stripped, re.IGNORECASE)
                or re.search(r'\bincluded\s+(?:in\s+)?§', stripped, re.IGNORECASE)
            ):
                continue
            candidates = list(_BACKTICK_VALUE.findall(stripped))
            without_urls = re.sub(r'https?://\S+', '', stripped, flags=re.IGNORECASE)
            candidates.extend(_BARE_INPUT_PATH.findall(without_urls))
            for candidate in candidates:
                normalized = _normalized_manifest_input(candidate)
                if normalized:
                    named.add(normalized)
    return named


def _panel_named_inputs(content: str) -> set[str]:
    named: set[str] = set()
    for match in re.finditer(r'^\s*panel inputs\b[^\r\n]*', content, re.IGNORECASE | re.MULTILINE):
        line = match.group(0)
        included = re.search(r'\bincl\.\s*(.+?)\)', line, re.IGNORECASE)
        values = _BACKTICK_VALUE.findall(included.group(1) if included else line.split(':', 1)[-1])
        for value in values:
            normalized = _normalized_manifest_input(value)
            if normalized:
                named.add(normalized)
    return named


def _attachment_input_keys(
    file_sections: List[Tuple[str, str]],
    attached_directories: List[str],
    automatic_files: List[str] | None = None,
) -> set[str]:
    keys: set[str] = set()
    for path, display_name in file_sections:
        for value in (path, display_name, os.path.basename(path)):
            normalized = value.replace('\\', '/').rstrip('/').casefold()
            if normalized:
                keys.add(normalized)
                keys.add(os.path.basename(normalized))
    for path in automatic_files or []:
        normalized = path.replace('\\', '/').rstrip('/').casefold()
        if normalized:
            keys.add(normalized)
            keys.add(os.path.basename(normalized))
    for path in attached_directories:
        normalized = path.replace('\\', '/').rstrip('/').casefold()
        if normalized:
            keys.add(normalized + '/')
            keys.add(os.path.basename(normalized) + '/')
    return keys


def _manifest_input_is_attached(value: str, attached: set[str]) -> bool:
    expected = value.replace('\\', '/').casefold()
    if expected.endswith('/'):
        return expected in attached
    if '/' not in expected:
        return expected in attached
    return expected in attached or any(
        candidate.endswith('/' + expected)
        for candidate in attached
    )


def _assert_named_inputs_attached(
    caller_sections: List[Tuple[str, str, str]],
    attached_directories: List[str],
    automatic_files: List[str] | None = None,
) -> None:
    required_by_source: List[Tuple[str, set[str]]] = []
    for path, _, content in caller_sections:
        required = _panel_named_inputs(content) | _available_context_named_inputs(content)
        if required:
            required_by_source.append((path, required))
    if not required_by_source:
        return
    attached = _attachment_input_keys(
        [(path, display_name) for path, display_name, _ in caller_sections],
        attached_directories,
        automatic_files,
    )
    missing_by_source: List[str] = []
    for source, required in required_by_source:
        missing = sorted(
            value
            for value in required
            if not _manifest_input_is_attached(value, attached)
        )
        if missing:
            missing_by_source.append(f'{source}: {", ".join(missing)}')
    if missing_by_source:
        raise IdentityError(
            'Attachment manifest gate failed; named inputs are absent from the '
            'packet: ' + '; '.join(missing_by_source) +
            '. Consultation halted before send.'
        )


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


def _write_package_chunks(platform: str, package_text: str, out_stem: str) -> List[str]:
    # Claude packages over ~45KB were historically split into ~22KB
    # sha256-tagged ordered chunks on a PRESUMED Claude upload/read ceiling.
    # That DEGRADED answers: Claude reported only the last chunk in context,
    # while Claude.ai accepts a large single .md fine. Root-cause shape per
    # Jesse: there is no chunking, so write exactly one package file.
    out_path = f"{out_stem}.md"
    with open(out_path, 'w', encoding='utf-8') as handle:
        handle.write(package_text)
    return [out_path]


def validate_caller_attachments(caller_attachments: List[str]) -> List[AttachmentProvenance]:
    """Validate caller-supplied files without adding identity content.

    This supports explicit caller-only consultations. It preserves the same
    fail-loud behavior for missing/unreadable caller files, but it does not
    strip identity basenames or merge anything into a new package.
    """
    provenance: List[AttachmentProvenance] = []
    caller_sections: List[Tuple[str, str, str]] = []
    for attachment in caller_attachments:
        content, digest = _read_caller_file(attachment)
        provenance.append(AttachmentProvenance(path=attachment, sha256=digest))
        caller_sections.append((attachment, os.path.basename(attachment), content))
    _assert_named_inputs_attached(caller_sections, [])
    return provenance


def _build_package_text(
    platform: str,
    caller_attachments: List[str],
) -> Tuple[str, List[AttachmentProvenance], int]:
    # Mandatory identity content — read loudly (raises if missing/unreadable).
    kernel_content = _read_required(_FAMILY_KERNEL, 'FAMILY_KERNEL.md')
    spotlight_content = _read_required(
        _SPOTLIGHT_STANDARD, 'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md',
    )
    identity_path = _identity_path(platform)
    identity_content = _read_required(
        identity_path, f'IDENTITY file for {platform}',
    )

    # Section list, in contract order. (display_path, basename, content)
    sections_src: List[Tuple[str, str, str]] = [
        (_FAMILY_KERNEL, 'FAMILY_KERNEL.md', kernel_content),
        (
            _SPOTLIGHT_STANDARD,
            'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md',
            spotlight_content,
        ),
        (identity_path, os.path.basename(identity_path), identity_content),
    ]

    # Caller attachments: strip caller-provided identity files (identity is
    # automatic), then read + hash the remainder BEFORE merging (provenance).
    provenance: List[AttachmentProvenance] = []
    caller_sections: List[Tuple[str, str, str]] = []
    expanded_attachments, attached_directories = _expand_caller_attachments(
        caller_attachments,
    )
    for attachment, display_name in expanded_attachments:
        basename = os.path.basename(attachment)
        if basename in _IDENTITY_BASENAMES:
            logger.warning("Stripped caller identity file: %s", basename)
            continue
        content, digest = _read_caller_file(attachment)
        provenance.append(AttachmentProvenance(path=attachment, sha256=digest))
        caller_sections.append((attachment, display_name, content))
        sections_src.append((attachment, display_name, content))

    _assert_named_inputs_attached(
        caller_sections,
        attached_directories,
        [_FAMILY_KERNEL, _SPOTLIGHT_STANDARD, identity_path],
    )

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
    return ''.join(sections), provenance, len(sections_src)


def build_inline_context(
    platform: str,
    caller_attachments: List[str],
) -> Tuple[str, List[AttachmentProvenance]]:
    """Build a complete identity packet as inline text without writing files."""
    package_text, provenance, section_count = _build_package_text(platform, caller_attachments)
    logger.info(
        "Built inline identity context for %s from %d file(s), %d byte(s)",
        platform,
        section_count,
        len(package_text.encode('utf-8')),
    )
    return package_text, provenance


def consolidate_attachments(
    platform: str,
    caller_attachments: List[str],
) -> ConsolidatedPackage:
    """Build one consolidated identity+attachments package (FLOW §3, §4).

    Order (FLOW §4): FAMILY_KERNEL.md, then
    SPOTLIGHT_STANDARD_FOR_INTEGRITY.md, then IDENTITY_<platform>.md, then the
    caller attachments. The kernel, Spotlight standard, and platform identity
    are MANDATORY and read via ``_read_required`` — a missing/unreadable one
    raises IdentityError and halts the consultation (no silent skip, no partial
    packet).

    Caller-supplied identity files are stripped (identity is automatic), but a
    caller file that is genuinely missing/unreadable is a loud failure, not a
    silent drop. Each caller attachment's path + content hash is captured BEFORE
    consolidation so provenance survives the merge.

    Returns a ConsolidatedPackage: the package path plus the caller-attachment
    provenance (path + sha256). Never returns None and never returns a partial
    packet — it either yields a complete package or raises.
    """
    out_stem = f"/tmp/taey_package_{platform}_{int(time.time())}"
    package_text, provenance, section_count = _build_package_text(platform, caller_attachments)
    paths = _write_package_chunks(platform, package_text, out_stem)
    logger.info(
        "Consolidated %d files -> %d attachment package file(s): %s",
        section_count,
        len(paths),
        ', '.join(paths),
    )
    return ConsolidatedPackage(
        path=paths[0],
        paths=paths,
        caller_provenance=provenance,
    )
