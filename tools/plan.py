"""
taey_plan - Create and manage execution plans.

Plans track the state of a multi-step interaction: what model/mode
to set, what files to attach, what message to send. Plans are stored
in Redis and consumed when the interaction completes.
"""

import json
import time
import uuid
import logging
from typing import Any, Dict, List

from core.platforms import BASE_URLS

logger = logging.getLogger(__name__)


def handle_plan(platform: str, action: str, params: Dict,
                redis_client) -> Dict[str, Any]:
    """Dispatch plan operations: create, get, update.

    Args:
        platform: Which platform.
        action: 'send_message', 'extract_response', 'get', 'update'.
        params: Action-specific parameters.
        redis_client: Redis client.

    Returns:
        Plan data or error.
    """
    if action == 'get':
        return _get_plan(params.get('plan_id'), platform, redis_client)
    elif action == 'update':
        return _update_plan(params.get('plan_id'), params, redis_client)
    elif action == 'send_message':
        return _create_plan(platform, action, params, redis_client)
    else:
        return {"error": f"Unknown plan action: {action}", "success": False}


def _create_plan(platform: str, action: str, params: Dict,
                 redis_client) -> Dict[str, Any]:
    """Create an execution plan for a platform interaction.

    All fields are required - no defaults. Forces explicit decision-making.
    """
    if not redis_client:
        return {"error": "Redis not available", "success": False}

    # Validate required fields
    missing = []
    session = params.get('session')
    message = params.get('message')
    model = params.get('model')
    mode = params.get('mode')
    tools = params.get('tools')
    attachments = params.get('attachments')

    if not session:
        missing.append('session ("new" or URL)')
    if not message:
        missing.append('message')
    if not model:
        missing.append('model')
    if not mode:
        missing.append('mode')
    if tools is None:
        missing.append('tools (list or "none")')
    if attachments is None:
        missing.append('attachments (list or [])')

    if missing:
        return {
            "success": False,
            "error": "Missing required fields: " + ", ".join(missing),
            "required_fields": {
                "session": '"new" or existing URL',
                "message": "Message text",
                "model": 'Model name or "N/A"',
                "mode": "Mode name",
                "tools": 'List or "none"',
                "attachments": "List of file paths or []",
            },
        }

    attachments_list = [] if attachments == "none" else list(attachments) if attachments else []
    tools_list = [] if tools == "none" else tools

    plan_id = str(uuid.uuid4())[:8]

    plan = {
        'plan_id': plan_id,
        'platform': platform,
        'action': action,
        'session': session,
        'message': message,
        'attachments': attachments_list,
        'required_state': {'model': model, 'mode': mode, 'tools': tools_list},
        'current_state': None,
        'steps': [],
        'status': 'created',
        'navigated': False,
        'created_at': time.time(),
    }

    redis_client.set(f"taey:v4:plan:{plan_id}", json.dumps(plan))
    redis_client.set(f"taey:v4:plan:current:{platform}", plan_id)

    # Hook-compatible format
    redis_client.setex(f"taey:plan:{platform}", 1800, json.dumps({
        'id': plan_id, 'platform': platform, 'action': action,
        'session': session, 'message': message,
        'model': model, 'mode': mode,
        'tools': tools_list, 'attachments': attachments_list,
        'validated': True, 'created_at': time.time(),
    }))

    # Clear stale checkpoints
    for suffix in ['inspect', 'set_map', 'attach']:
        redis_client.delete(f"taey:checkpoint:{platform}:{suffix}")

    return {
        "success": True,
        "plan_id": plan_id,
        "platform": platform,
        "action": action,
        "session": session,
        "required_state": plan['required_state'],
        "attachments": attachments_list,
        "next_step": f"Call taey_inspect to see current state",
    }


def _get_plan(plan_id: str, platform: str, redis_client) -> Dict[str, Any]:
    """Get a plan by ID or current plan for platform."""
    if not redis_client:
        return {"error": "Redis not available", "success": False}

    if not plan_id and platform:
        plan_id = redis_client.get(f"taey:v4:plan:current:{platform}")

    if not plan_id:
        return {"error": "No plan found", "success": False}

    data = redis_client.get(f"taey:v4:plan:{plan_id}")
    if not data:
        return {"error": f"Plan {plan_id} not found", "success": False}

    return {"success": True, "plan": json.loads(data)}


def _update_plan(plan_id: str, updates: Dict, redis_client) -> Dict[str, Any]:
    """Update a plan's state. Auto-generates steps when current_state provided."""
    if not redis_client:
        return {"error": "Redis not available", "success": False}

    data = redis_client.get(f"taey:v4:plan:{plan_id}")
    if not data:
        return {"error": f"Plan {plan_id} not found", "success": False}

    plan = json.loads(data)

    for key in ['current_state', 'steps', 'status']:
        if key in updates:
            plan[key] = updates[key]

    if 'current_state' in updates and plan.get('required_state'):
        plan['steps'] = _generate_steps(
            plan['required_state'], plan['current_state'],
            plan.get('attachments', []), plan.get('message', ''),
        )
        plan['status'] = 'ready'

    plan['updated_at'] = time.time()
    redis_client.set(f"taey:v4:plan:{plan_id}", json.dumps(plan))

    return {
        "success": True,
        "plan_id": plan_id,
        "status": plan['status'],
        "steps": plan.get('steps', []),
    }


def _generate_steps(required: Dict, current: Dict,
                    attachments: List, message: str) -> List[Dict]:
    """Generate execution steps by comparing required vs current state."""
    steps = []

    req_mode = required.get('mode')
    cur_mode = (current or {}).get('mode')
    if req_mode and req_mode != cur_mode:
        steps.append({"action": "set_mode", "target": req_mode, "current": cur_mode})

    req_tools = set(required.get('tools', []))
    cur_tools = set((current or {}).get('tools', []))
    for tool in req_tools - cur_tools:
        steps.append({"action": "enable_tool", "tool": tool})

    req_model = required.get('model')
    cur_model = (current or {}).get('model')
    if req_model and req_model != cur_model:
        steps.append({"action": "change_model", "target": req_model, "current": cur_model})

    for fp in attachments:
        steps.append({"action": "attach", "file": fp})

    if message:
        steps.append({"action": "send", "message": message[:100] + "..." if len(message) > 100 else message})

    return steps
