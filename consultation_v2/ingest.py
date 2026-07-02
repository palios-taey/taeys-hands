"""Auto-ingestion: save extracted responses to corpus and trigger ISMA pipeline.

Called after successful extraction. Local corpus persistence always runs for a
real extracted response. External ISMA activation is opt-in via the shared
storage policy; request/auth/network failures raise so the caller logs a
configured-path failure and does not mark ingestion complete.

Two steps:
1. Save response to TAEY_CORPUS_PATH/extracts/{platform}/{timestamp}.md
2. POST to ISMA /ingest/session to feed the governed tile pipeline
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from consultation_v2 import storage_policy

logger = logging.getLogger(__name__)

_CORPUS_PATH = os.path.expanduser(os.environ.get('TAEY_CORPUS_PATH', '~/data/corpus'))
_SECRETS_PATH = '/home/mira/palios-taey-secrets.json'
_ALLOWED_ISMA_PLATFORMS = {
    'chatgpt',
    'claude',
    'claude_chat',
    'gemini',
    'grok',
    'perplexity',
}
_PLATFORM_ALIASES = {
    'perplexity_ai': 'perplexity',
}


class ISMAIngestError(RuntimeError):
    """Configured ISMA ingest path failed; callers must not treat it as success."""


def _env_or_machine(name: str) -> str:
    return storage_policy.env_or_machine(name)


_ISMA_API_URL = _env_or_machine('ISMA_API_URL')


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


def _read_isma_api_key() -> str:
    env_key = _env_or_machine('ISMA_API_KEY')
    try:
        with open(_SECRETS_PATH, encoding='utf-8') as handle:
            secrets = json.load(handle)
    except FileNotFoundError:
        secrets = {}
    except (OSError, json.JSONDecodeError) as exc:
        if env_key:
            logger.warning("Cannot read ISMA API key secrets file %s; using ISMA_API_KEY env", _SECRETS_PATH)
            return env_key
        raise ISMAIngestError(f"Cannot read ISMA API key secrets file {_SECRETS_PATH}: {exc}") from exc
    key = str(secrets.get('isma_api_key') or env_key).strip()
    if not key:
        raise ISMAIngestError(
            'ISMA_API_URL is configured but no isma_api_key is present in '
            f'{_SECRETS_PATH} and ISMA_API_KEY is unset'
        )
    return key


def _isma_platform(platform: str) -> str:
    normalized = str(platform or '').strip().lower().replace('-', '_')
    mapped = _PLATFORM_ALIASES.get(normalized, normalized)
    if mapped not in _ALLOWED_ISMA_PLATFORMS:
        raise ISMAIngestError(
            f"Unsupported ISMA ingest platform {platform!r}; expected one of "
            f"{sorted(_ALLOWED_ISMA_PLATFORMS)}"
        )
    return mapped


def trigger_isma_ingest(platform: str, content: str, url: str = None,
                        session_id: str = None,
                        external_store_enabled: bool = False) -> Optional[Dict]:
    """POST extracted response to ISMA for tile ingestion.

    Uses the governed /ingest/session endpoint. Build-only gate: returns None
    while external storage is disabled or ISMA_API_URL is unset; once enabled,
    failures raise loudly.
    """
    if not external_store_enabled and not storage_policy.store_config_enabled():
        return None
    if not _ISMA_API_URL:
        return None
    if not content or len(content.strip()) < 50:
        return None  # Skip trivially short extracts

    try:
        import requests
    except ImportError as exc:
        logger.error("ISMA ingest configured but requests is not installed")
        raise ISMAIngestError("ISMA ingest configured but requests is not installed") from exc

    api_key = _read_isma_api_key()
    mapped_platform = _isma_platform(platform)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    payload = {
        "content": content[:20000],
        "source_file": f"taeys-hands/{mapped_platform}/{ts}",
        "platform": mapped_platform,
        "source_type": "chat_session",
        "truth_tier": "operational",
        "session_id": session_id or "",
    }
    try:
        timeout = storage_policy.store_timeout_seconds()
        resp = storage_policy.run_bounded_store_call(
            'ISMA ingest POST',
            lambda: requests.post(
                f"{_ISMA_API_URL.rstrip('/')}/ingest/session",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": api_key,
                },
                timeout=timeout,
            ),
            timeout_seconds=timeout,
        )
        if resp.ok:
            result = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {"status": "ok"}
            logger.info("ISMA ingest triggered for %s: %s", mapped_platform, result.get("status", "ok"))
            return result
        message = f"ISMA ingest failed ({resp.status_code}): {resp.text[:200]}"
        logger.error(message)
        raise ISMAIngestError(message)
    except Exception as e:
        if isinstance(e, ISMAIngestError):
            raise
        logger.error("ISMA ingest failed: %s", e)
        raise ISMAIngestError(f"ISMA ingest failed: {e}") from e


def auto_ingest(platform: str, content: str, url: str = None,
                session_id: str = None, metadata: Dict = None,
                external_store_enabled: bool = False) -> Dict[str, Any]:
    """Combined auto-ingestion: save to corpus + trigger ISMA.

    Returns a summary dict of what was done. Corpus-save errors are local and
    non-fatal; configured ISMA request/auth/network failures raise.
    """
    result = {"corpus_path": None, "isma_triggered": False}

    # 1. Save to corpus
    corpus_path = save_to_corpus(platform, content, url, metadata)
    result["corpus_path"] = corpus_path

    # 2. Trigger ISMA pipeline
    isma_result = trigger_isma_ingest(
        platform,
        content,
        url,
        session_id,
        external_store_enabled=external_store_enabled,
    )
    if isma_result:
        result["isma_triggered"] = True
        result["isma_result"] = isma_result
    elif not external_store_enabled and not storage_policy.store_config_enabled():
        result["isma_skipped_reason"] = "external storage disabled by default"

    return result
