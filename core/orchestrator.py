"""Orchestrator Integration — Task assignment, heartbeat, ISMA ingestion.

Connects hmm_bot to the orchestrator:
  - Heartbeat: keeps agent alive in registry
  - Task polling: check for assigned tasks (model/mode, platform, package)
  - ISMA ingestion: POST extracted responses to /api/ingest/transcript
  - Completion reporting: POST /api/report on success/failure

Uses /api/notify (Redis inbox) for sending tasks, NOT /api/command.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Config from environment
ORCH_URL = os.environ.get('ORCH_URL', 'https://orch-api.taey.ai')
ORCH_KEY = os.environ.get('ORCH_KEY', '')
AGENT_ID = os.environ.get('AGENT_ID', 'taeys-hands')
NODE_ID = os.environ.get('NODE_ID', 'unknown')


def _headers():
    return {
        'X-API-Key': ORCH_KEY,
        'Content-Type': 'application/json',
    }


def heartbeat(status: str = 'idle', current_task: str = None,
              capabilities: dict = None) -> bool:
    """Send heartbeat to orchestrator. Returns True on success."""
    payload = {
        'agent_id': AGENT_ID,
        'status': status,
    }
    if current_task:
        payload['current_task'] = current_task
    if capabilities:
        payload['capabilities'] = capabilities

    try:
        resp = requests.post(
            f'{ORCH_URL}/api/heartbeat',
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Heartbeat failed: {e}")
        return False


def poll_tasks() -> List[Dict]:
    """Poll orchestrator for ranked tasks. Returns list of task dicts."""
    try:
        resp = requests.get(
            f'{ORCH_URL}/api/tasks/ranked',
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            # Filter for tasks assigned to us or unassigned
            tasks = data if isinstance(data, list) else data.get('tasks', [])
            return [t for t in tasks
                    if not t.get('target_agent') or t['target_agent'] == AGENT_ID]
        return []
    except Exception as e:
        logger.warning(f"Task poll failed: {e}")
        return []


def check_inbox() -> List[Dict]:
    """Check Redis inbox for messages/tasks. Returns list of messages."""
    try:
        resp = requests.get(
            f'{ORCH_URL}/api/inbox/{AGENT_ID}',
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, list) else data.get('messages', [])
        return []
    except Exception as e:
        logger.warning(f"Inbox check failed: {e}")
        return []


def report_completion(task_id: str, result: str, status: str = 'completed',
                      metadata: dict = None) -> bool:
    """Report task completion to orchestrator."""
    payload = {
        'agent_id': AGENT_ID,
        'task_id': task_id,
        'result': result,
        'status': status,
    }
    if metadata:
        payload['metadata'] = metadata

    try:
        resp = requests.post(
            f'{ORCH_URL}/api/report',
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        ok = resp.status_code == 200
        if ok:
            logger.info(f"Task {task_id} reported as {status}")
        else:
            logger.warning(f"Task report failed ({resp.status_code}): {resp.text[:200]}")
        return ok
    except Exception as e:
        logger.warning(f"Task report failed: {e}")
        return False


def notify_agent(to: str, text: str, from_agent: str = None) -> bool:
    """Send notification to another agent via /api/notify (Redis inbox)."""
    payload = {
        'target': to,
        'from': from_agent or AGENT_ID,
        'body': text,
    }

    try:
        resp = requests.post(
            f'{ORCH_URL}/api/notify',
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        ok = resp.status_code == 200
        if ok:
            logger.info(f"Notification sent to {to}")
        return ok
    except Exception as e:
        logger.warning(f"Notify failed: {e}")
        return False


def ingest_transcript(platform: str, response_content: str,
                      package_metadata: dict,
                      prompt_content: str = '') -> Dict:
    """Ingest extracted response into ISMA via /api/ingest/transcript.

    Args:
        platform: chatgpt, gemini, grok, perplexity, claude
        response_content: The AI response text
        package_metadata: Dict with batch_id, tile_hash, model, etc.
        prompt_content: The prompt that was sent (for the exchange)

    Returns:
        Dict with 'success', 'content_hash', 'status_url'
    """
    # Map platform names to ISMA platform format
    platform_map = {
        'chatgpt': 'chatgpt',
        'gemini': 'gemini',
        'grok': 'grok',
        'perplexity': 'perplexity',
        'claude': 'claude_chat',
    }
    isma_platform = platform_map.get(platform, platform)

    # Build conversation_id from metadata
    batch_id = package_metadata.get('batch_id', 'unknown')
    tile_hash = package_metadata.get('tile_hash', 'unknown')
    conversation_id = f"hmm_{batch_id}_{platform}_{tile_hash}"

    # Build exchange
    exchange = {
        'prompt': prompt_content or package_metadata.get('prompt', ''),
        'response': response_content,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    payload = {
        'platform': isma_platform,
        'conversation_id': conversation_id,
        'title': f"HMM Analysis: {tile_hash}",
        'model': package_metadata.get('model', platform),
        'exchanges': [exchange],
    }

    try:
        resp = requests.post(
            f'{ORCH_URL}/api/ingest/transcript',
            headers=_headers(),
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"ISMA ingestion accepted: {data.get('content_hash', 'unknown')}")
            return {
                'success': True,
                'content_hash': data.get('content_hash'),
                'status_url': data.get('check_status'),
                'exchange_count': data.get('exchange_count'),
            }
        else:
            logger.error(f"ISMA ingestion failed ({resp.status_code}): {resp.text[:200]}")
            return {'success': False, 'error': f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        logger.error(f"ISMA ingestion failed: {e}")
        return {'success': False, 'error': str(e)}


def check_ingestion_status(content_hash: str) -> Dict:
    """Check if ISMA ingestion is complete."""
    try:
        resp = requests.get(
            f'{ORCH_URL}/api/ingest/status/{content_hash}',
            headers=_headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return {'error': f"HTTP {resp.status_code}"}
    except Exception as e:
        return {'error': str(e)}
