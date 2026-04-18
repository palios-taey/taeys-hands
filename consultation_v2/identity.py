# THE RULE — enforced in every function in this file:
# 1. YAML = exact AT-SPI truth. Exact string, exact case. No .lower().
# 2. No name_contains. Period. Anywhere. EXACT MATCH ONLY.
# 3. Driver code = zero platform knowledge.
# 4. YAML drives the driver, never the reverse.
# 5. Two scan scopes: snapshot() = document, menu_snapshot() = portals.
# 6. Validation targets persistent elements only.
# 7. No fallbacks, no broadening. Fail closed on missing config.

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

def _get_platform_identity_path(platform: str) -> str:
    """Read identity file from platform YAML. No hardcoded platform names.

    Fails closed (raises) when YAML is unreadable or identity_file is
    missing/empty. HARD RULE: every consultation gets a platform identity;
    swallowing errors here is how sessions proceed unconstitutional.
    """
    from consultation_v2.yaml_contract import load_platform_yaml
    cfg = load_platform_yaml(platform)
    identity_file = cfg.get('identity_file')
    if not identity_file:
        raise RuntimeError(
            f'platform YAML for {platform!r} missing identity_file — '
            f'HARD RULE requires every platform to declare its IDENTITY file.')
    return os.path.join(_IDENTITY_DIR, identity_file)

_EXT_LANG = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.yaml': 'yaml', '.yml': 'yaml', '.json': 'json', '.md': 'markdown',
    '.sh': 'bash', '.toml': 'toml',
}


def consolidate_attachments(
    platform: str,
    caller_attachments: List[str],
) -> str:
    """Prepend FAMILY_KERNEL + platform identity, consolidate into one file.

    HARD RULE: every consultation MUST include FAMILY_KERNEL.md and the
    platform's IDENTITY file. This function is the single enforcement
    point — it raises RuntimeError if either is missing on disk, rather
    than silently dropping files and letting an unconstitutional session
    proceed.

    Strips any identity files the caller included (identity is automatic).
    Returns the path to the consolidated .md package. Always consolidates,
    even when there's only one file, so the chip filename is unique per
    run (bare FAMILY_KERNEL.md would collide across retries).
    """
    # _get_platform_identity_path raises if YAML missing identity_file —
    # caller surfaces that as a fail-closed identity error.
    platform_id_path = _get_platform_identity_path(platform)

    # HARD RULE enforcement: both identity files must exist on disk. A
    # missing FAMILY_KERNEL.md or missing IDENTITY_*.md is a constitutional
    # failure, not a soft-warn-and-proceed case.
    if not os.path.isfile(_FAMILY_KERNEL):
        raise RuntimeError(
            f'FAMILY_KERNEL.md missing at {_FAMILY_KERNEL!r} — HARD RULE '
            f'requires it on every consultation.')
    if not os.path.isfile(platform_id_path):
        raise RuntimeError(
            f'platform identity missing at {platform_id_path!r} — HARD RULE '
            f'requires it on every consultation.')

    # Strip caller-provided identity files (they'd be duplicates and would
    # expose the wrong filename on the chip).
    identity_basenames = {'FAMILY_KERNEL.md', os.path.basename(platform_id_path)}
    clean = []
    for a in caller_attachments:
        if os.path.basename(a) in identity_basenames:
            logger.warning("Stripped caller identity file: %s", os.path.basename(a))
        else:
            clean.append(a)

    # Validate caller files also exist on disk — fail-closed rather than
    # silently dropping them during consolidation.
    for a in clean:
        if not os.path.isfile(a):
            raise RuntimeError(f'caller attachment missing on disk: {a!r}')

    all_files = [_FAMILY_KERNEL, platform_id_path] + clean
    sections = [f"# Package for {platform}\n\n**Files**: {len(all_files)}\n"]
    for path in all_files:
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
