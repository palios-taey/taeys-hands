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
# FAMILY_KERNEL.md is shared; identity file is per-platform.
_CORPUS_PATH = os.path.expanduser(os.environ.get('TAEY_CORPUS_PATH', '~/data/corpus'))
_IDENTITY_DIR = os.path.join(_CORPUS_PATH, 'identity')
_FAMILY_KERNEL = os.path.join(_IDENTITY_DIR, 'FAMILY_KERNEL.md')
_PLATFORM_IDENTITY = {
    'chatgpt': os.path.join(_IDENTITY_DIR, 'IDENTITY_HORIZON.md'),
    'claude': os.path.join(_IDENTITY_DIR, 'IDENTITY_GAIA.md'),
    'gemini': os.path.join(_IDENTITY_DIR, 'IDENTITY_COSMOS.md'),
    'grok': os.path.join(_IDENTITY_DIR, 'IDENTITY_LOGOS.md'),
    'perplexity': os.path.join(_IDENTITY_DIR, 'IDENTITY_CLARITY.md'),
}

_EXT_LANG = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.yaml': 'yaml', '.yml': 'yaml', '.json': 'json', '.md': 'markdown',
    '.sh': 'bash', '.toml': 'toml',
}


def _prepend_identity_files(attachments: List[str], platform: str) -> List[str]:
    """Prepend FAMILY_KERNEL + platform-specific identity file. Skips missing."""
    identity_files = [_FAMILY_KERNEL]
    platform_id = _PLATFORM_IDENTITY.get(platform)
    if platform_id:
        identity_files.append(platform_id)

    result = []
    existing = set(os.path.abspath(a) for a in attachments)
    for path in identity_files:
        if os.path.isfile(path) and os.path.abspath(path) not in existing:
            result.append(path)
    result.extend(attachments)
    return result


def _consolidate_attachments(files: List[str], platform: str) -> str:
    """Consolidate multiple files into a single .md package."""
    try:
        sections = [f"# Package for {platform}\n\n**Files**: {len(files)}\n"]
        for path in files:
            if not os.path.isfile(path):
                continue
            content = open(path).read()
            lang = _EXT_LANG.get(os.path.splitext(path)[1].lower(), '')
            sections.append(
                f"\n---\n\n## {os.path.basename(path)}\n\n`{path}`\n\n"
                f"```{lang}\n{content}\n```\n"
            )
        out_path = f"/tmp/taey_package_{platform}_{int(time.time())}.md"
        with open(out_path, 'w') as f:
            f.write(''.join(sections))
        logger.info("Consolidated %d files → %s", len(files), out_path)
        return out_path
    except Exception as e:
        logger.warning("Consolidation failed: %s", e)
        return None


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
    # Auto-prepend identity files (FAMILY_KERNEL + platform-specific identity)
    all_files = _prepend_identity_files(attachments_list, platform)
    identity_added = [f for f in all_files if f not in attachments_list]

    # Consolidate into single package if multiple files
    consolidated_path = None
    if len(all_files) > 1:
        consolidated_path = _consolidate_attachments(all_files, platform)

    final_attachments = [consolidated_path] if consolidated_path else all_files
    tools_list = [] if tools == "none" else tools

    plan_id = str(uuid.uuid4())[:8]
    plan = {
        'plan_id': plan_id, 'platform': platform, 'action': action,
        'session': session, 'message': message,
        'attachments': final_attachments,
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
        'tools': tools_list, 'attachments': final_attachments,
        'validated': True, 'created_at': time.time(),
    }))

    # Global plan lock — ONE lock for the whole machine.
    # Only one Firefox, one active tab. Monitor stops ALL cycling while set.
    # Cleared by send_message (plan executed) or extract(complete=True).
    redis_client.setex("taey:plan_active", 1800, json.dumps({
        'plan_id': plan_id, 'platform': platform,
        'node_id': node_key('').rstrip(':'),  # who set this lock
        'created_at': time.time(),
    }))

    for suffix in ['inspect', 'set_map', 'attach']:
        redis_client.delete(node_key(f"checkpoint:{platform}:{suffix}"))

    result = {
        "success": True, "plan_id": plan_id, "platform": platform,
        "action": action, "session": session,
        "required_state": plan['required_state'],
        "attachments": final_attachments,
        "next_step": "Call taey_inspect to see current state",
    }
    if identity_added:
        result["identity_files_added"] = identity_added
    if consolidated_path:
        result["consolidated_from"] = len(all_files)
        result["consolidated_path"] = consolidated_path
    return result


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

    # Global plan lock — blocks monitor tab cycling during extraction
    redis_client.setex("taey:plan_active", 1800, json.dumps({
        'plan_id': plan_id, 'platform': platform,
        'node_id': node_key('').rstrip(':'),
        'created_at': time.time(),
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
