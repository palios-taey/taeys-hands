"""Auto-ingestion: save extracted responses to corpus and trigger ISMA pipeline.

Called by extract.py after successful extraction. Non-blocking — failures are
logged but never break the extraction flow.

Two steps:
1. Save response to TAEY_CORPUS_PATH/extracts/{platform}/{timestamp}.md
2. POST to ISMA /api/ingest/transcript to feed the tile pipeline
"""

import json
import os
import time
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CORPUS_PATH = os.path.expanduser(os.environ.get('TAEY_CORPUS_PATH', '~/data/corpus'))
_ISMA_API_URL = os.environ.get('ISMA_API_URL', '')
_ISMA_API_KEY = os.environ.get('ISMA_API_KEY', '')


def save_to_corpus(platform: str, content: str, url: str = None,
                   metadata: Dict = None) -> Optional[str]:
    """Save extracted response to corpus directory.

    Returns the file path on success, None on failure.
    Structure: {CORPUS_PATH}/extracts/{platform}/{YYYY-MM-DD}_{HH-MM-SS}.md
    """
    if not content or not content.strip():
        return None

    try:
        extract_dir = os.path.join(_CORPUS_PATH, 'extracts', platform)
        os.makedirs(extract_dir, exist_ok=True)

        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f"{ts}.md"
        filepath = os.path.join(extract_dir, filename)

        # Build markdown with metadata header
        header_lines = [
            f"# Extract: {platform}",
            f"**Timestamp**: {datetime.now().isoformat()}",
        ]
        if url:
            header_lines.append(f"**URL**: {url}")
        if metadata:
            for k, v in metadata.items():
                header_lines.append(f"**{k}**: {v}")
        header_lines.append("")
        header_lines.append("---")
        header_lines.append("")

        with open(filepath, 'w') as f:
            f.write('\n'.join(header_lines))
            f.write(content)

        logger.info("Saved extract to corpus: %s (%d chars)", filepath, len(content))
        return filepath
    except Exception as e:
        logger.warning("Failed to save extract to corpus: %s", e)
        return None


def trigger_isma_ingest(platform: str, content: str, url: str = None,
                        session_id: str = None) -> Optional[Dict]:
    """POST extracted response to ISMA for tile ingestion.

    Uses /api/ingest/transcript endpoint. Non-blocking — returns result or None.
    Only runs if ISMA_API_URL and ISMA_API_KEY are configured.
    """
    if not _ISMA_API_URL:
        return None
    if not content or len(content.strip()) < 50:
        return None  # Skip trivially short extracts

    try:
        import requests
        resp = requests.post(
            f"{_ISMA_API_URL.rstrip('/')}/ingest/session",
            json={
                "content": content[:50000],  # Cap at 50k chars
                "source_file": f"taeys-hands/{platform}/{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "platform": platform,
                "url": url or "",
                "session_id": session_id or "",
            },
            headers={
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if resp.ok:
            result = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {"status": "ok"}
            logger.info("ISMA ingest triggered for %s: %s", platform, result.get("status", "ok"))
            return result
        else:
            logger.warning("ISMA ingest failed (%d): %s", resp.status_code, resp.text[:200])
            return None
    except ImportError:
        logger.warning("requests not installed — ISMA ingest skipped")
        return None
    except Exception as e:
        logger.warning("ISMA ingest failed: %s", e)
        return None


def auto_ingest(platform: str, content: str, url: str = None,
                session_id: str = None, metadata: Dict = None) -> Dict[str, Any]:
    """Combined auto-ingestion: save to corpus + trigger ISMA.

    Returns a summary dict of what was done. Never raises.
    """
    result = {"corpus_path": None, "isma_triggered": False}

    # 1. Save to corpus
    corpus_path = save_to_corpus(platform, content, url, metadata)
    result["corpus_path"] = corpus_path

    # 2. Trigger ISMA pipeline
    isma_result = trigger_isma_ingest(platform, content, url, session_id)
    if isma_result:
        result["isma_triggered"] = True
        result["isma_result"] = isma_result

    return result
