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
from core.smart_input import smart_type, find_entry_element
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


def _validate_plan_requirements(platform: str, redis_client) -> Optional[Dict]:
    """Check if active plan has unmet requirements. Returns error dict or None.

    This is a HARD GATE: if a plan exists with required_state, the current_state
    MUST be set and MUST match. Otherwise send is blocked.

    This prevents sending with wrong model/mode/tools on strategic consultations.
    """
    if not redis_client:
        return None

    plan_id = redis_client.get(f"taey:v4:plan:current:{platform}")
    if not plan_id:
        return None  # No plan = no gate (ad-hoc messages allowed)

    plan_json = redis_client.get(f"taey:v4:plan:{plan_id}")
    if not plan_json:
        return None

    try:
        plan = json.loads(plan_json)
    except (json.JSONDecodeError, TypeError):
        return None

    required = plan.get('required_state', {})
    if not required:
        return None  # Plan has no requirements

    current = plan.get('current_state')

    # Gate 1: current_state must be set (inspect + update must have happened)
    if current is None:
        return {
            "success": False,
            "error": (
                "VALIDATION GATE BLOCKED: Plan has required_state but current_state "
                "was never set. You must: 1) taey_inspect, 2) taey_plan(update) with "
                "current_state reflecting what you SEE, 3) fix any mismatches, "
                "4) update current_state again, THEN send."
            ),
            "platform": platform,
            "plan_id": plan_id,
            "required_state": required,
            "fix": "taey_plan(action='update', params={plan_id, current_state: {model, mode, tools}})",
        }

    # Gate 2: each requirement must be met
    unmet = []
    req_model = required.get('model')
    cur_model = current.get('model')
    if req_model and req_model not in ('N/A', 'any') and req_model != cur_model:
        unmet.append(f"model: required='{req_model}', current='{cur_model}'")

    req_mode = required.get('mode')
    cur_mode = current.get('mode')
    if req_mode and req_mode not in ('N/A', 'any') and req_mode != cur_mode:
        unmet.append(f"mode: required='{req_mode}', current='{cur_mode}'")

    req_tools = set(required.get('tools', []))
    cur_tools = set(current.get('tools', []))
    if req_tools:
        missing_tools = req_tools - cur_tools
        if missing_tools:
            unmet.append(f"tools: missing={sorted(missing_tools)}")

    if unmet:
        return {
            "success": False,
            "error": (
                "VALIDATION GATE BLOCKED: Plan requirements not met. "
                "Fix the state before sending. Unmet: " + "; ".join(unmet)
            ),
            "platform": platform,
            "plan_id": plan_id,
            "unmet_requirements": unmet,
            "required_state": required,
            "current_state": current,
        }

    return None  # All requirements met


def handle_send_message(platform: str, message: str,
                        redis_client, display: str,
                        attachments: List[str] = None,
                        session_type: str = None,
                        purpose: str = None) -> Dict[str, Any]:
    """Send a message with full workflow.

    0. VALIDATION GATE: Check plan requirements are met
    1. Get stored map, validate input control exists
    2. Switch to platform, get URL
    3. Count baseline copy buttons
    4. Click input, type message (with shift+Return for line breaks)
    5. Store in Neo4j
    6. Spawn monitor daemon BEFORE sending (avoids race condition)
    7. Press Enter to send (daemon already watching)

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
    # Step 0: VALIDATION GATE - refuse to send if plan requirements unmet
    gate_error = _validate_plan_requirements(platform, redis_client)
    if gate_error:
        return gate_error

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

    # Step 2: ALWAYS switch to platform tab first, then get document
    # AT-SPI can see all tab documents even when they're not active,
    # but click coordinates are screen-relative and hit the VISIBLE tab.
    if not inp.switch_to_platform(platform):
        return {"success": False, "error": f"Failed to switch to {platform}", "platform": platform}
    time.sleep(0.5)

    firefox = atspi.find_firefox()
    doc = atspi.get_platform_document(firefox, platform) if firefox else None

    if not doc:
        return {"success": False, "error": f"Could not find {platform} document", "platform": platform}

    url = atspi.get_document_url(doc)

    # Step 3: Baseline copy button count
    all_elements = find_elements(doc)
    baseline_copy_count = len(find_copy_buttons(all_elements))

    # Step 4: Focus input via AT-SPI grab_focus (primary) or stored coordinates (fallback)
    # AT-SPI grab_focus is immune to UI shifts from file attachment, model changes, etc.
    # Stored map coordinates go stale when the UI changes - only use as last resort.
    entry_el = find_entry_element(doc, platform)

    input_focused = False
    if entry_el:
        try:
            comp = entry_el.get_component_iface()
            if comp:
                comp.grab_focus()
                time.sleep(0.3)
                input_focused = True
                logger.info(f"Input focused via AT-SPI grab_focus for {platform}")
        except Exception as e:
            logger.warning(f"AT-SPI grab_focus failed: {e}")

    if not input_focused:
        # Fallback: click stored coordinates (may be stale after file attach)
        input_coord = controls['input']
        logger.warning(f"Using stored coordinates fallback for {platform} input ({input_coord})")
        if not inp.click_at(input_coord['x'], input_coord['y']):
            return {"success": False, "error": "Failed to focus input field", "platform": platform}
        time.sleep(0.3)
        # Re-search for entry element after click
        entry_el = find_entry_element(doc, platform)

    # Use smart_type with full message (handles multi-line via clipboard paste)
    type_result = smart_type(message, platform=platform, entry_element=entry_el)
    if not type_result['success']:
        return {
            "success": False,
            "error": f"Failed to type message: {type_result.get('error', 'unknown')}",
            "platform": platform,
            "input_method": type_result.get('method'),
        }

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

    # Step 6: Spawn monitor daemon BEFORE sending (fixes race condition)
    # The daemon must be polling before Enter is pressed, otherwise fast
    # responses can complete before the daemon even starts.
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

    # Step 7: Send via Enter key (daemon is already watching)
    if not inp.press_key('Return', timeout=5):
        # Kill the daemon since we failed to send
        if daemon_spawned and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        return {
            "success": False,
            "error": "Send (Enter key) failed",
            "platform": platform,
            "neo4j": neo4j_result,
        }

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
        "info": "Message sent. Monitor daemon was pre-spawned to catch fast responses.",
    }
