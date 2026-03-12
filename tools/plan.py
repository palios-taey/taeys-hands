"""taey_plan - Create and manage execution plans stored in Redis."""

import json
import os
import time
import uuid
import logging
from typing import Any, Dict, List

from storage.redis_pool import node_key

logger = logging.getLogger(__name__)

# Identity files — prepended to EVERY send_message plan's attachments.
# Configurable via TAEY_CORPUS_PATH env var (default: ~/data/corpus).
_CORPUS_PATH = os.path.expanduser(os.environ.get('TAEY_CORPUS_PATH', '~/data/corpus'))
_IDENTITY_FILES = [
    os.path.join(_CORPUS_PATH, 'identity', 'FAMILY_KERNEL.md'),
    os.path.join(_CORPUS_PATH, 'identity', 'IDENTITY_LOGOS.md'),
]


def _prepend_identity_files(attachments: List[str]) -> List[str]:
    """Prepend identity files to attachment list. Skips files that don't exist or are already listed."""
    result = []
    existing = set(os.path.abspath(a) for a in attachments)
    for path in _IDENTITY_FILES:
        if os.path.isfile(path) and os.path.abspath(path) not in existing:
            result.append(path)
    result.extend(attachments)
    return result


def _consolidate_attachments(files: List[str], platform: str) -> str:
    """Consolidate multiple files into a single .md package via build_package."""
    try:
        from scripts.build_package import collect_files, build_package
        import argparse
        args = argparse.Namespace(files=files, manifest=None, glob=None)
        collected = collect_files(args)
        if not collected:
            return None
        content = build_package(collected, f"Package for {platform}", 200000 * 4)
        out_path = f"/tmp/taey_package_{platform}_{int(time.time())}.md"
        with open(out_path, 'w') as f:
            f.write(content)
        logger.info(f"Consolidated {len(collected)} files → {out_path}")
        return out_path
    except Exception as e:
        logger.warning(f"Consolidation failed, using individual files: {e}")
        return None

logger = logging.getLogger(__name__)


def handle_plan(platform: str, action: str, params: Dict,
                redis_client) -> Dict[str, Any]:
    """Dispatch plan operations: create, get, update."""
    if action == 'get':
        return _get_plan(params.get('plan_id'), platform, redis_client)
    elif action == 'update':
        return _update_plan(params.get('plan_id'), params, redis_client)
    elif action == 'send_message':
        return _create_plan(platform, action, params, redis_client)
    elif action == 'extract_response':
        return _create_extract_plan(platform, params, redis_client)
    else:
        return {"error": f"Unknown plan action: {action}", "success": False}


def _create_plan(platform: str, action: str, params: Dict,
                 redis_client) -> Dict[str, Any]:
    """Create an execution plan. All fields required — no defaults."""
    if not redis_client:
        return {"error": "Redis not available", "success": False}

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
        return {"success": False, "error": "Missing required fields: " + ", ".join(missing),
                "required_fields": {
                    "session": '"new" or existing URL', "message": "Message text",
                    "model": 'Model name or "N/A"', "mode": "Mode name",
                    "tools": 'List or "none"', "attachments": "List of file paths or []",
                }}

    attachments_list = [] if attachments == "none" else list(attachments) if attachments else []
    attachments_list = _prepend_identity_files(attachments_list)
    tools_list = [] if tools == "none" else tools

    # Consolidate all attachments into a single .md package
    consolidated_path = None
    if len(attachments_list) > 1:
        consolidated_path = _consolidate_attachments(attachments_list, platform)
        if consolidated_path:
            original_files = attachments_list
            attachments_list = [consolidated_path]

    plan_id = str(uuid.uuid4())[:8]
    plan = {
        'plan_id': plan_id, 'platform': platform, 'action': action,
        'session': session, 'message': message,
        'attachments': attachments_list,
        'required_state': {'model': model, 'mode': mode, 'tools': tools_list},
        'current_state': None, 'steps': [], 'status': 'created',
        'navigated': False, 'created_at': time.time(),
    }

    redis_client.set(node_key(f"plan:{plan_id}"), json.dumps(plan))
    redis_client.set(node_key(f"plan:current:{platform}"), plan_id)
    redis_client.setex(node_key(f"plan:{platform}"), 1800, json.dumps({
        'id': plan_id, 'platform': platform, 'action': action,
        'session': session, 'message': message,
        'model': model, 'mode': mode,
        'tools': tools_list, 'attachments': attachments_list,
        'validated': True, 'created_at': time.time(),
    }))

    # Global plan lock — central monitor stops ALL tab/URL cycling while active.
    # Cleared by send_message on completion. TTL=120s safety net.
    redis_client.setex(node_key("plan_active"), 120, json.dumps({
        'plan_id': plan_id, 'platform': platform,
        'created_at': time.time(),
    }))

    for suffix in ['inspect', 'set_map', 'attach']:
        redis_client.delete(node_key(f"checkpoint:{platform}:{suffix}"))

    return {
        "success": True, "plan_id": plan_id, "platform": platform,
        "action": action, "session": session,
        "required_state": plan['required_state'],
        "attachments": attachments_list,
        "next_step": "Call taey_inspect to see current state",
    }


def _create_extract_plan(platform: str, params: Dict,
                         redis_client) -> Dict[str, Any]:
    """Create extraction-only plan (no send_message)."""
    if not redis_client:
        return {"error": "Redis not available", "success": False}

    plan_id = str(uuid.uuid4())[:8]
    plan = {
        'plan_id': plan_id, 'platform': platform,
        'action': 'extract_response',
        'session': params.get('session', 'current'),
        'message': None, 'attachments': [],
        'required_state': {}, 'current_state': None,
        'steps': [{"action": "extract", "platform": platform}],
        'status': 'ready', 'navigated': False, 'created_at': time.time(),
    }

    redis_client.set(node_key(f"plan:{plan_id}"), json.dumps(plan))
    redis_client.set(node_key(f"plan:current:{platform}"), plan_id)
    redis_client.setex(node_key(f"plan:{platform}"), 1800, json.dumps({
        'id': plan_id, 'platform': platform, 'action': 'extract_response',
        'session': plan['session'], 'message': None,
        'model': None, 'mode': None,
        'tools': [], 'attachments': [],
        'validated': True, 'created_at': time.time(),
    }))

    return {
        "success": True, "plan_id": plan_id, "platform": platform,
        "action": "extract_response", "steps": plan['steps'],
        "next_step": f"Call taey_quick_extract('{platform}') to extract the response",
    }


def _get_plan(plan_id: str, platform: str, redis_client) -> Dict[str, Any]:
    if not redis_client:
        return {"error": "Redis not available", "success": False}
    if not plan_id and platform:
        plan_id = redis_client.get(node_key(f"plan:current:{platform}"))
    if not plan_id:
        return {"error": "No plan found", "success": False}
    data = redis_client.get(node_key(f"plan:{plan_id}"))
    if not data:
        return {"error": f"Plan {plan_id} not found", "success": False}
    return {"success": True, "plan": json.loads(data)}


def _update_plan(plan_id: str, updates: Dict, redis_client) -> Dict[str, Any]:
    """Update plan state. Auto-generates steps when current_state provided."""
    if not redis_client:
        return {"error": "Redis not available", "success": False}
    data = redis_client.get(node_key(f"plan:{plan_id}"))
    if not data:
        return {"error": f"Plan {plan_id} not found", "success": False}

    plan = json.loads(data)
    for key in ['current_state', 'steps', 'status']:
        if key in updates:
            plan[key] = updates[key]

    if 'current_state' in updates and plan.get('required_state'):
        plan['steps'] = _generate_steps(
            plan['required_state'], plan['current_state'],
            plan.get('attachments', []), plan.get('message', ''))
        plan['status'] = 'ready'

    plan['updated_at'] = time.time()
    redis_client.set(node_key(f"plan:{plan_id}"), json.dumps(plan))

    return {"success": True, "plan_id": plan_id,
            "status": plan['status'], "steps": plan.get('steps', [])}


def _generate_steps(required: Dict, current: Dict,
                    attachments: List, message: str) -> List[Dict]:
    """Generate execution steps by comparing required vs current state."""
    steps = []
    req_mode = required.get('mode')
    cur_mode = (current or {}).get('mode')
    if req_mode and req_mode != cur_mode:
        steps.append({"action": "set_mode", "target": req_mode, "current": cur_mode})

    for tool in set(required.get('tools', [])) - set((current or {}).get('tools', [])):
        steps.append({"action": "enable_tool", "tool": tool})

    req_model = required.get('model')
    cur_model = (current or {}).get('model')
    if req_model and req_model != cur_model:
        steps.append({"action": "change_model", "target": req_model, "current": cur_model})

    for fp in attachments:
        steps.append({"action": "attach", "file": fp})

    if message:
        steps.append({"action": "send",
                       "message": message[:100] + "..." if len(message) > 100 else message})
    return steps
