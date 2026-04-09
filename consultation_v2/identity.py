"""Identity file consolidation for V2 consultations.

Prepends FAMILY_KERNEL.md + platform-specific IDENTITY file to every
consultation attachment. Uses the same file paths as tools/plan.py
(lines 27-37) but without Redis dependencies.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import List, Optional

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

_EXT_LANG = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.yaml': 'yaml', '.yml': 'yaml', '.json': 'json', '.md': 'markdown',
    '.sh': 'bash', '.toml': 'toml',
}


def consolidate_attachments(
    platform: str,
    caller_attachments: List[str],
) -> Optional[str]:
    """Prepend FAMILY_KERNEL + platform identity, consolidate into one file.

    Strips any identity files the caller included (identity is automatic).
    Returns path to the consolidated .md package, or None on failure.
    """
    # Strip caller-provided identity files
    clean = []
    for a in caller_attachments:
        if os.path.basename(a) in _IDENTITY_BASENAMES:
            logger.warning("Stripped caller identity file: %s", os.path.basename(a))
        else:
            clean.append(a)

    # Build file list: KERNEL + IDENTITY + caller files
    identity_files = [_FAMILY_KERNEL]
    platform_id = _PLATFORM_IDENTITY.get(platform)
    if platform_id:
        identity_files.append(platform_id)

    all_files = [p for p in identity_files if os.path.isfile(p)] + clean

    if len(all_files) <= 1:
        return all_files[0] if all_files else None

    # Consolidate into single package
    sections = [f"# Package for {platform}\n\n**Files**: {len(all_files)}\n"]
    for path in all_files:
        if not os.path.isfile(path):
            continue
        content = open(path).read()
        lang = _EXT_LANG.get(os.path.splitext(path)[1].lower(), '')
        sections.append(
            f"\n---\n\n## {os.path.basename(path)}\n\n`{path}`\n\n"
            f"```{lang}\n{content}\n```\n"
        )

    out_path = f"/tmp/taey_package_{platform}_{int(time.time())}.md"
    with open(out_path, 'w') as f:
        f.write(''.join(sections))
    logger.info("Consolidated %d files → %s", len(all_files), out_path)
    return out_path
