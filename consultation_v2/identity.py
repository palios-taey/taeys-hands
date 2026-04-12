# THE RULE — enforced in every function in this file:
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

def _get_platform_identity_path(platform: str) -> Optional[str]:
    """Read identity file from platform YAML. No hardcoded platform names."""
    try:
        from consultation_v2.yaml_contract import load_platform_yaml
        cfg = load_platform_yaml(platform)
        identity_file = cfg.get('identity_file')
        if identity_file:
            return os.path.join(_IDENTITY_DIR, identity_file)
    except Exception:
        pass
    return None

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
    platform_id_path = _get_platform_identity_path(platform)
    identity_basenames = {'FAMILY_KERNEL.md'}
    if platform_id_path:
        identity_basenames.add(os.path.basename(platform_id_path))

    clean = []
    for a in caller_attachments:
        if os.path.basename(a) in identity_basenames:
            logger.warning("Stripped caller identity file: %s", os.path.basename(a))
        else:
            clean.append(a)

    # Build file list: KERNEL + IDENTITY + caller files
    identity_files = [_FAMILY_KERNEL]
    if platform_id_path:
        identity_files.append(platform_id_path)

    all_files = [p for p in identity_files if os.path.isfile(p)] + clean

    if len(all_files) <= 1:
        return all_files[0] if all_files else None

    # Consolidate into single package
    sections = [f"# Package for {platform}\n\n**Files**: {len(all_files)}\n"]
    for path in all_files:
        if not os.path.isfile(path):
            continue
        content = open(path).read()
        lang = _EXT_LANG.get(os.path.splitext(path)[1], '')
        sections.append(
            f"\n---\n\n## {os.path.basename(path)}\n\n`{path}`\n\n"
            f"```{lang}\n{content}\n```\n"
        )

    out_path = f"/tmp/taey_package_{platform}_{int(time.time())}.md"
    with open(out_path, 'w') as f:
        f.write(''.join(sections))
    logger.info("Consolidated %d files → %s", len(all_files), out_path)
    return out_path
