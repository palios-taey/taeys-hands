"""6-Sigma Halt System — Global halt on tool failure, platform halt on YAML drift.

Two halt levels:
1. GLOBAL HALT (tool-level): AT-SPI can't find Firefox, D-Bus hung, xdotool failed.
   ALL machines stop ALL operations. Something is fundamentally broken.
2. PLATFORM HALT (YAML-level): element_map didn't match, dropdown items changed,
   new unknown button appeared. Only this platform stops.

Halt flags live in Redis so ALL bot instances across ALL machines respect them.
Escalation goes to the orchestrator via /api/notify.

Clearing halts:
  - Orchestrator (Claude Code) investigates, fixes the issue, clears:
      redis-cli DEL taey:halt:global
      redis-cli DEL taey:halt:chatgpt
  - Or via clear_halt() / clear_platform_halt() in code after fix verified.
"""

import json
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Environment
NODE_ID = os.environ.get('NODE_ID', 'unknown')
ORCH_URL = os.environ.get('ORCH_URL', 'https://orch-api.taey.ai')
ORCH_KEY = os.environ.get('ORCH_KEY', '')
NOTIFY_TARGET = os.environ.get('NOTIFY_TARGET', 'weaver')


def halt_global(reason: str, redis_client, source_platform: str = '') -> bool:
    """Tool-level failure — halt everything everywhere.

    Sets Redis flag that ALL bot instances check before each cycle.
    Sends escalation to orchestrator.
    Returns True if halt was set successfully.
    """
    halt_data = {
        'reason': reason,
        'timestamp': time.time(),
        'source': f'{NODE_ID}:{source_platform}' if source_platform else NODE_ID,
        'level': 'global',
    }

    try:
        if redis_client:
            redis_client.set('taey:halt:global', json.dumps(halt_data))
            logger.critical(f"GLOBAL HALT SET: {reason}")
        else:
            logger.critical(f"GLOBAL HALT (no Redis): {reason}")
    except Exception as e:
        logger.error(f"Failed to set global halt in Redis: {e}")

    _escalate(f"🚨 GLOBAL HALT: {reason}", redis_client)
    return True


def halt_platform(platform: str, reason: str, redis_client,
                  drift_data: dict = None) -> bool:
    """YAML-level failure — halt this platform only.

    Sets Redis flag for this specific platform.
    Other platforms continue operating.
    Includes drift data (old vs new elements) for investigation.
    """
    halt_data = {
        'reason': reason,
        'timestamp': time.time(),
        'source': f'{NODE_ID}:{platform}',
        'platform': platform,
        'level': 'platform',
    }
    if drift_data:
        halt_data['drift_data'] = drift_data

    try:
        if redis_client:
            redis_client.set(f'taey:halt:{platform}', json.dumps(halt_data))
            logger.error(f"PLATFORM HALT [{platform}]: {reason}")
        else:
            logger.error(f"PLATFORM HALT (no Redis) [{platform}]: {reason}")
    except Exception as e:
        logger.error(f"Failed to set platform halt in Redis: {e}")

    _escalate(f"⚠️ PLATFORM HALT [{platform}]: {reason}", redis_client)
    return True


def check_halt(platform: str, redis_client) -> Optional[dict]:
    """Check if any halt is active. Returns halt data dict or None.

    Called at the top of every bot cycle. If this returns non-None,
    the bot must NOT proceed.
    """
    if not redis_client:
        return None

    try:
        # Check global halt first
        global_halt = redis_client.get('taey:halt:global')
        if global_halt:
            data = json.loads(global_halt)
            logger.warning(f"GLOBAL HALT active: {data.get('reason', 'unknown')}")
            return data

        # Check platform-specific halt
        platform_halt = redis_client.get(f'taey:halt:{platform}')
        if platform_halt:
            data = json.loads(platform_halt)
            logger.warning(f"PLATFORM HALT [{platform}] active: {data.get('reason', 'unknown')}")
            return data

    except Exception as e:
        logger.error(f"Halt check failed: {e}")

    return None


def clear_halt(redis_client) -> bool:
    """Clear global halt. Called after investigation + fix."""
    try:
        if redis_client:
            redis_client.delete('taey:halt:global')
            logger.info("Global halt cleared")
            return True
    except Exception as e:
        logger.error(f"Failed to clear global halt: {e}")
    return False


def clear_platform_halt(platform: str, redis_client) -> bool:
    """Clear platform-specific halt. Called after YAML updated."""
    try:
        if redis_client:
            redis_client.delete(f'taey:halt:{platform}')
            logger.info(f"Platform halt cleared: {platform}")
            return True
    except Exception as e:
        logger.error(f"Failed to clear platform halt for {platform}: {e}")
    return False


def _escalate(message: str, redis_client):
    """Send escalation via orchestrator /api/notify."""
    # Try orchestrator API first
    if ORCH_URL and ORCH_KEY:
        try:
            resp = requests.post(
                f'{ORCH_URL}/api/notify',
                headers={'X-API-Key': ORCH_KEY, 'Content-Type': 'application/json'},
                json={
                    'target': NOTIFY_TARGET,
                    'from': f'taeys-hands-{NODE_ID}',
                    'body': message,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info(f"Escalation sent to {NOTIFY_TARGET}: {message[:100]}")
                return
        except Exception as e:
            logger.warning(f"Orchestrator notify failed: {e}")

    # Fallback: taey-notify CLI
    try:
        import subprocess
        subprocess.run(
            ['taey-notify', NOTIFY_TARGET, message, '--type', 'escalation'],
            capture_output=True, timeout=5,
        )
    except Exception:
        logger.error(f"All escalation methods failed for: {message[:100]}")
