"""Identity + task packet construction for V2 consultations (PACKET_CONTRACT).

Production consultations emit exactly two attachments plus a brief prompt:

* Bundle A (governance): FAMILY_KERNEL.md, destination IDENTITY_*.md, then
  SPOTLIGHT_STANDARD_FOR_INTEGRITY.md — full sources, that order, no task files.
* Bundle B (task): caller task dossier sources in caller order, plus a generated
  provenance manifest. No governance duplication.
* Brief: composer text only (built by the caller; not this module).

There is no one-package fallback, no automatic chunking, and no partial packet.
Missing/unreadable mandatory governance or an empty Bundle B raises IdentityError
and HALTS before any UI action (FLOW §4 / CONSULTATION_CONTRACT / PACKET_CONTRACT).

PROVENANCE (FLOW §3 / §8): each caller attachment's path + content hash is
captured BEFORE Bundle B is rendered. Bundle basenames are deterministic from
request_id + platform. A local receipt binds both bundle hashes; the receipt is
not a Chat attachment.

The platform->IDENTITY map below is allowed config/data (it selects which
identity file a platform gets); it is NOT platform branching control-flow.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

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


def _bundle_basenames(platform: str, request_id: str) -> Tuple[str, str]:
    """Deterministic Bundle A/B basenames from platform + frozen request_id."""
    safe_id = re.sub(r'[^A-Za-z0-9._-]+', '', request_id) or 'unknown'
    return (
        f'taey_bundle_a_{platform}_{safe_id}.md',
        f'taey_bundle_b_{platform}_{safe_id}.md',
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> Tuple[int, str]:
    with open(path, 'rb') as handle:
        data = handle.read()
    if not data:
        raise IdentityError(
            f'Bundle at {path!r} is empty after write — refusing partial packet '
            '(PACKET_CONTRACT: exactly two non-empty attachments).'
        )
    return len(data), _sha256_bytes(data)


def _render_bundle(
    platform: str,
    sections_src: List[Tuple[str, str, str]],
    title: str,
) -> str:
    """Render one bundle. Chat-facing locator is the logical name only."""
    sections = [f"# {title} for {platform}\n\n**Files**: {len(sections_src)}\n"]
    for _source_path, logical_name, content in sections_src:
        lang = _EXT_LANG.get(os.path.splitext(logical_name)[1].lower(), '')
        block = f"```{lang}\n{content}\n```\n"
        # Mandated constitutional/identity files are inlined verbatim + unedited;
        # wrap them in VERBATIM markers so prompting-lint skips them for the
        # authored-quality checks (PROMPTING_STANDARDS §3.2).
        if os.path.basename(logical_name) in _IDENTITY_BASENAMES:
            block = (
                f"<!-- BEGIN-VERBATIM: {os.path.basename(logical_name)} -->\n"
                f"{block}<!-- END-VERBATIM -->\n"
            )
        sections.append(
            f"\n---\n\n## {logical_name}\n\n`{logical_name}`\n\n" + block
        )
    return ''.join(sections)


def _governance_sections(platform: str) -> List[Tuple[str, str, str]]:
    """Bundle A sources in PACKET_CONTRACT order: kernel, identity, Spotlight."""
    kernel_content = _read_required(_FAMILY_KERNEL, 'FAMILY_KERNEL.md')
    identity_path = _identity_path(platform)
    identity_content = _read_required(
        identity_path, f'IDENTITY file for {platform}',
    )
    spotlight_content = _read_required(
        _SPOTLIGHT_STANDARD, 'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md',
    )
    return [
        (_FAMILY_KERNEL, 'FAMILY_KERNEL.md', kernel_content),
        (identity_path, os.path.basename(identity_path), identity_content),
        (
            _SPOTLIGHT_STANDARD,
            'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md',
            spotlight_content,
        ),
    ]


def _task_sections(
    caller_attachments: List[str],
    automatic_files: List[str],
) -> Tuple[List[Tuple[str, str, str]], List[AttachmentProvenance], List[str]]:
    """Read caller task sources for Bundle B; strip governance basenames."""
    provenance: List[AttachmentProvenance] = []
    task_src: List[Tuple[str, str, str]] = []
    expanded, attached_directories = _expand_caller_attachments(caller_attachments)
    for attachment, display_name in expanded:
        basename = os.path.basename(attachment)
        if basename in _IDENTITY_BASENAMES:
            logger.warning("Stripped caller identity file from Bundle B: %s", basename)
            continue
        content, digest = _read_caller_file(attachment)
        provenance.append(AttachmentProvenance(path=attachment, sha256=digest))
        task_src.append((attachment, display_name, content))
    _assert_named_inputs_attached(
        [(path, name, content) for path, name, content in task_src],
        attached_directories,
        automatic_files,
    )
    if not task_src:
        raise IdentityError(
            'Bundle B would be empty after stripping governance basenames — '
            'refusing one-package / partial packet (PACKET_CONTRACT requires a '
            'non-empty task bundle). Consultation halted.'
        )
    return task_src, provenance, attached_directories


def _provenance_manifest(
    platform: str,
    request_id: str,
    bundle_a_name: str,
    bundle_b_name: str,
    gov_src: List[Tuple[str, str, str]],
    task_src: List[Tuple[str, str, str]],
    task_provenance: List[AttachmentProvenance],
) -> str:
    """Generate Bundle B provenance manifest from frozen inputs (pre-render)."""
    digest_by_path = {item.path: item.sha256 for item in task_provenance}
    lines = [
        '# Provenance manifest',
        '',
        f'- platform: `{platform}`',
        f'- request_id: `{request_id}`',
        f'- bundle_a_basename: `{bundle_a_name}`',
        f'- bundle_b_basename: `{bundle_b_name}`',
        '',
        '## Governance sources (Bundle A; not duplicated in Bundle B body)',
        '',
    ]
    for source_path, logical_name, content in gov_src:
        digest = _sha256_bytes(content.encode('utf-8'))
        lines.append(
            f'- `{logical_name}` bytes={len(content.encode("utf-8"))} '
            f'sha256={digest} locator={source_path}'
        )
    lines.extend(['', '## Task sources (Bundle B)', ''])
    for source_path, logical_name, content in task_src:
        digest = digest_by_path.get(source_path) or _sha256_bytes(
            content.encode('utf-8')
        )
        lines.append(
            f'- `{logical_name}` bytes={len(content.encode("utf-8"))} '
            f'sha256={digest}'
        )
        # Operator-local absolute path stays in the receipt only; Chat sees
        # logical name above. Keep a non-path note that a local locator exists.
        lines.append('  - local_locator: retained in builder receipt (not Chat-facing)')
    lines.append('')
    return '\n'.join(lines)


def _write_text(path: str, text: str) -> None:
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)


def _write_receipt(path: str, payload: Dict[str, Any]) -> None:
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write('\n')


def build_inline_context(
    platform: str,
    caller_attachments: List[str],
) -> Tuple[str, List[AttachmentProvenance]]:
    """ChatGPT-only identity-inline helper when there are zero attachments.

    This is NOT the PACKET_CONTRACT attachment path and must not be used as a
    one-package fallback when caller task files exist. Prefer
    ``consolidate_attachments`` for production consultations.
    """
    if caller_attachments:
        raise IdentityError(
            'build_inline_context refused caller attachments — use '
            'consolidate_attachments for PACKET_CONTRACT Bundle A+B. '
            'Consultation halted (no one-package fallback).'
        )
    gov_src = _governance_sections(platform)
    package_text = _render_bundle(platform, gov_src, 'Inline governance context')
    logger.info(
        "Built inline governance context for %s from %d file(s), %d byte(s)",
        platform,
        len(gov_src),
        len(package_text.encode('utf-8')),
    )
    return package_text, []


def consolidate_attachments(
    platform: str,
    caller_attachments: List[str],
    request_id: Optional[str] = None,
) -> ConsolidatedPackage:
    """Build Bundle A (governance) + Bundle B (task) per PACKET_CONTRACT.md.

    Never emits a one-package merge. Returns ConsolidatedPackage with
    ``paths == [bundle_a, bundle_b]`` (exactly two non-empty files) or raises.
    """
    if not caller_attachments:
        raise IdentityError(
            'consolidate_attachments requires at least one caller task attachment '
            'for Bundle B. Consultation halted (no governance-only / one-package '
            'fallback on the PACKET_CONTRACT path).'
        )

    frozen_request_id = (request_id or '').strip()
    if not frozen_request_id:
        # Deterministic stand-in when caller has not yet minted request_id:
        # hash platform + attachment path list (order-preserving).
        seed = platform + '\x1f' + '\x1e'.join(caller_attachments)
        frozen_request_id = hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]

    bundle_a_name, bundle_b_name = _bundle_basenames(platform, frozen_request_id)
    out_dir = '/tmp'
    a_path = os.path.join(out_dir, bundle_a_name)
    b_path = os.path.join(out_dir, bundle_b_name)
    receipt_path = os.path.join(
        out_dir, f'taey_packet_receipt_{platform}_{frozen_request_id}.json'
    )

    gov_src = _governance_sections(platform)
    automatic = [path for path, _name, _content in gov_src]
    task_src, provenance, _attached_directories = _task_sections(
        caller_attachments,
        automatic,
    )

    # Provenance manifest is generated from frozen inputs BEFORE rendering B.
    manifest = _provenance_manifest(
        platform=platform,
        request_id=frozen_request_id,
        bundle_a_name=bundle_a_name,
        bundle_b_name=bundle_b_name,
        gov_src=gov_src,
        task_src=task_src,
        task_provenance=provenance,
    )
    task_with_manifest = list(task_src) + [
        ('provenance_manifest', 'PROVENANCE_MANIFEST.md', manifest),
    ]

    a_text = _render_bundle(platform, gov_src, 'Bundle A - Governance')
    b_text = _render_bundle(platform, task_with_manifest, 'Bundle B - Task')
    if not a_text.strip() or not b_text.strip():
        raise IdentityError(
            'Rendered Bundle A or Bundle B is empty — refusing partial packet '
            '(PACKET_CONTRACT). Consultation halted.'
        )

    _write_text(a_path, a_text)
    _write_text(b_path, b_text)

    # Independent re-read + hash of both completed bundles (PACKET_CONTRACT).
    a_bytes, a_digest = _sha256_file(a_path)
    b_bytes, b_digest = _sha256_file(b_path)
    paths = [a_path, b_path]
    if len(paths) != 2:
        raise IdentityError(
            f'Builder emitted {len(paths)} attachments; PACKET_CONTRACT requires '
            'exactly two. Consultation halted (no one-package fallback).'
        )

    receipt = {
        'request_id': frozen_request_id,
        'platform': platform,
        'bundle_a': {
            'basename': bundle_a_name,
            'path': a_path,
            'bytes': a_bytes,
            'sha256': a_digest,
            'sources': [
                {
                    'logical_name': logical_name,
                    'locator': source_path,
                    'bytes': len(content.encode('utf-8')),
                    'sha256': _sha256_bytes(content.encode('utf-8')),
                }
                for source_path, logical_name, content in gov_src
            ],
        },
        'bundle_b': {
            'basename': bundle_b_name,
            'path': b_path,
            'bytes': b_bytes,
            'sha256': b_digest,
            'sources': [
                {
                    'logical_name': logical_name,
                    'locator': source_path,
                    'bytes': len(content.encode('utf-8')),
                    'sha256': (
                        next(
                            (
                                item.sha256
                                for item in provenance
                                if item.path == source_path
                            ),
                            _sha256_bytes(content.encode('utf-8')),
                        )
                    ),
                }
                for source_path, logical_name, content in task_src
            ],
            'provenance_manifest_sha256': _sha256_bytes(manifest.encode('utf-8')),
        },
        'attachment_count': 2,
        'one_package_fallback': False,
    }
    _write_receipt(receipt_path, receipt)

    logger.info(
        "PACKET_CONTRACT bundles for %s request_id=%s: %s (%d B) + %s (%d B); "
        "receipt=%s",
        platform,
        frozen_request_id,
        a_path,
        a_bytes,
        b_path,
        b_bytes,
        receipt_path,
    )
    return ConsolidatedPackage(
        path=a_path,
        paths=paths,
        caller_provenance=provenance,
        receipt_path=receipt_path,
    )
