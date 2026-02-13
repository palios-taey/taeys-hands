"""
taey_send_message - Type, store, send, and spawn monitor.

The primary tool for sending messages to chat platforms.
Handles multi-line text, stores in Neo4j, and spawns a
background monitor daemon for response detection.
"""

import json
import os
import subprocess
import sys
import time
import logging
from typing import Any, Dict, List, Optional

from core import atspi, input as inp
from core.tree import find_elements, find_copy_buttons
from tools.interact import get_map
from storage import neo4j_client

logger = logging.getLogger(__name__)

# Track spawned daemon processes for zombie reaping
_daemon_processes = []


def _reap_daemons():
    """Clean up finished daemon processes to prevent zombies."""
    global _daemon_processes
    alive = []
    for proc in _daemon_processes:
        if proc.poll() is None:
            alive.append(proc)
    _daemon_processes = alive


def handle_send_message(platform: str, message: str,
                        redis_client, display: str,
                        attachments: List[str] = None,
                        session_type: str = None,
                        purpose: str = None) -> Dict[str, Any]:
    """Send a message with full workflow.

    1. Get stored map, validate input control exists
    2. Switch to platform, get URL
    3. Count baseline copy buttons
    4. Click input, type message (with shift+Return for line breaks)
    5. Store in Neo4j
    6. Press Enter to send
    7. Spawn background monitor daemon

    Args:
        platform: Which platform.
        message: Message text to send.
        redis_client: Redis client.
        display: X11 DISPLAY value for subprocess env.
        attachments: Already-attached files (for Neo4j record).
        session_type: Session type label.
        purpose: Session purpose description.

    Returns:
        Success info with baseline copy count and monitor details.
    """
    # Step 1: Get stored map
    map_data = get_map(platform, redis_client)
    if not map_data:
        return {
            "success": False,
            "error": f"No map for {platform}. Run taey_inspect + taey_set_map first.",
            "platform": platform,
        }

    controls = map_data.get('controls', {})
    if 'input' not in controls:
        return {
            "success": False,
            "error": "No 'input' control in map.",
            "platform": platform,
        }

    # Step 2: Switch to platform and get document
    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None

    if not doc:
        if not inp.switch_to_platform(platform):
            return {"success": False, "error": f"Failed to switch to {platform}", "platform": platform}
        time.sleep(0.3)
        firefox = atspi.find_firefox()
        doc = atspi.get_platform_document(firefox, platform) if firefox else None

    if not doc:
        return {"success": False, "error": f"Could not find {platform} document", "platform": platform}

    url = atspi.get_document_url(doc)

    # Step 3: Baseline copy button count
    all_elements = find_elements(doc)
    baseline_copy_count = len(find_copy_buttons(all_elements))

    # Step 4: Click input and type message
    input_coord = controls['input']
    if not inp.click_at(input_coord['x'], input_coord['y']):
        return {"success": False, "error": "Failed to click input field", "platform": platform}
    time.sleep(0.2)

    lines = message.split('\n')
    for i, line in enumerate(lines):
        if line:
            if not inp.type_text(line):
                return {"success": False, "error": f"Failed to type line {i}", "platform": platform}
        if i < len(lines) - 1:
            if not inp.press_key('shift+Return', timeout=5):
                return {"success": False, "error": f"Failed to insert line break at line {i}", "platform": platform}
            time.sleep(0.02)

    time.sleep(0.2)

    # Step 5: Store in Neo4j
    neo4j_result = None
    session_id = None
    message_id = None

    if url:
        session_id = neo4j_client.get_or_create_session(platform, url)
        if session_id:
            if session_type or purpose:
                neo4j_client.update_session(session_id, {
                    k: v for k, v in {'session_type': session_type, 'purpose': purpose}.items() if v
                })
            message_id = neo4j_client.add_message(session_id, 'user', message, attachments)
            neo4j_result = {"session_id": session_id, "message_id": message_id}

    # Step 5b: Store prompt metadata in Redis for later exchange tracking
    if redis_client:
        from datetime import datetime
        redis_client.setex(f"taey:pending_prompt:{platform}", 3600, json.dumps({
            'content': message,
            'attachments': attachments or [],
            'session_url': url,
            'session_id': session_id,
            'message_id': message_id,
            'sent_at': datetime.now().isoformat(),
        }))

    # Step 6: Send via Enter key
    if not inp.press_key('Return', timeout=5):
        return {
            "success": False,
            "error": "Send (Enter key) failed",
            "platform": platform,
            "neo4j": neo4j_result,
        }

    # Step 7: Spawn monitor daemon
    import uuid
    monitor_id = str(uuid.uuid4())[:8]

    # Determine timeout from plan's mode/tool guidance
    daemon_timeout = 3600  # Default 1 hour
    if redis_client:
        plan_id = redis_client.get(f"taey:v4:plan:current:{platform}")
        if plan_id:
            plan_json = redis_client.get(f"taey:v4:plan:{plan_id}")
            if plan_json:
                try:
                    plan_data = json.loads(plan_json)
                    req_tools = plan_data.get('required_state', {}).get('tools', [])
                    # Check if any research/deep tool is enabled - use longer timeout
                    research_tools = {'Deep Research', 'DeepSearch', 'Research'}
                    if any(t in research_tools for t in req_tools):
                        daemon_timeout = 7200  # 2 hours for research modes
                except (json.JSONDecodeError, AttributeError):
                    pass

    daemon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'monitor', 'daemon.py')
    daemon_cmd = [
        '/usr/bin/python3', daemon_path,
        '--platform', platform,
        '--monitor-id', monitor_id,
        '--baseline-copy-count', str(baseline_copy_count),
        '--timeout', str(daemon_timeout),
    ]
    if session_id:
        daemon_cmd.extend(['--session-id', session_id])
    if message_id:
        daemon_cmd.extend(['--user-message-id', message_id])

    _reap_daemons()

    daemon_env = os.environ.copy()
    daemon_env['DISPLAY'] = display
    daemon_spawned = False
    daemon_pid = None
    daemon_log_path = None

    try:
        log_file = f"/tmp/taey_daemon_{monitor_id}.log"
        daemon_log = open(log_file, 'w')
        proc = subprocess.Popen(
            daemon_cmd, env=daemon_env,
            stdout=daemon_log, stderr=daemon_log,
            start_new_session=True,
        )
        daemon_log.close()
        daemon_spawned = True
        daemon_pid = proc.pid
        daemon_log_path = log_file
        _daemon_processes.append(proc)
    except Exception as e:
        logger.error(f"Daemon spawn failed: {e}")
        if 'daemon_log' in locals():
            daemon_log.close()

    return {
        "success": True,
        "platform": platform,
        "url": url,
        "message_length": len(message),
        "baseline_copy_count": baseline_copy_count,
        "neo4j": neo4j_result,
        "monitor": {
            "id": monitor_id,
            "spawned": daemon_spawned,
            "pid": daemon_pid,
            "log": daemon_log_path,
        },
        "info": "Message sent. Monitor daemon will detect response completion.",
    }
