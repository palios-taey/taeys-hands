from __future__ import annotations
"""Redis checkpoint CRUD for attachment state."""

import json
import time
import logging
from typing import Any, Dict

from storage.redis_pool import node_key

logger = logging.getLogger(__name__)


def update_checkpoint(platform: str, file_path: str, redis_client):
    """Update Redis attachment checkpoint after successful attach.

    Deduplicates: if this exact file_path is already in the checkpoint,
    don't increment the count or append again. This prevents the
    double-count bug when taey_attach is called multiple times for the
    same file (e.g., dropdown_open → click item → file_dialog).
    """
    if not redis_client:
        return
    existing = redis_client.get(node_key(f"checkpoint:{platform}:attach"))
    if existing:
        try:
            data = json.loads(existing)
            files = data.get('attached_files', [])
            # Deduplicate: skip if this file is already recorded
            if file_path in files:
                logger.debug(f"Checkpoint already has {file_path}, skipping duplicate")
                return
            files.append(file_path)
            count = len(files)
        except json.JSONDecodeError:
            count, files = 1, [file_path]
    else:
        count, files = 1, [file_path]

    redis_client.set(node_key(f"checkpoint:{platform}:attach"), json.dumps({
        'attached_count': count,
        'attached_files': files,
        'last_file': file_path,
        'timestamp': time.time(),
    }))
