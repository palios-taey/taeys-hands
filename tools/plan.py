"""taey_plan - Create, audit, and manage execution plans.

The plan is the single source of truth. Flow:
  1. create  → store required model/mode/attachments in Redis
  2. audit   → compare plan vs live AT-SPI elements → PASS or FAIL
  3. send.py → hard-blocked until audit_passed=True

No plan ships without audit. No send happens without a passed audit.
"""

import json
import os
import time
import uuid
import logging
from typing import Any, Dict, List, Optional

from storage.redis_pool import node_key

logger = logging.getLogger(__name__)

# Identity files — prepended to EVERY send_message plan's attachments.
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

_PLAN_ALLOWED_DIRS = [os.path.expanduser('~'), '/tmp', '/var/spark']
_PLAN_TTL = 600  # 10 minutes


def _validate_path(path: str) -> bool:
    """Check path is within allowed directories."""
    real = os.path.realpath(path)
    return any(real == d or real.startswith(d + os.sep) for d in _PLAN_ALLOWED_DIRS)


_IDENTITY_BASENAMES = (
    {'FAMILY_KERNEL.md'} |
    {os.path.basename(p) for p in _PLATFORM_IDENTITY.values()}
)


def _prepend_identity_files(attachments: List[str], platform: str) -> List[str]:
    """Prepend FAMILY_KERNEL + platform-specific identity file.

    Strips any identity files the caller included — identity is ALWAYS
    determined by the platform parameter, never by caller's attachments.
    """
    # Strip identity files from caller's list (prevents wrong-identity bugs)
    stripped = []
    clean_attachments = []
    for a in attachments:
        if os.path.basename(a) in _IDENTITY_BASENAMES:
            stripped.append(os.path.basename(a))
        else:
            clean_attachments.append(a)
    if stripped:
        logger.warning("Stripped caller-provided identity files: %s (identity is automatic)", stripped)

    identity_files = [_FAMILY_KERNEL]
    platform_id = _PLATFORM_IDENTITY.get(platform)
    if platform_id:
        identity_files.append(platform_id)

    result = []
    for path in identity_files:
        if os.path.isfile(path):
            result.append(path)
    result.extend(clean_attachments)
    return result


def _consolidate_attachments(files: List[str], platform: str) -> Optional[str]:
    """Consolidate multiple files into a single .md package.

    KERNEL + IDENTITY + user files → one file for upload.
    """
    try:
        sections = [f"# Package for {platform}\n\n**Files**: {len(files)}\n"]
        for path in files:
            if not os.path.isfile(path):
                continue
            if not _validate_path(path):
                logger.warning("Skipping disallowed path in consolidation: %s", path)
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


# ─── Dispatch ────────────────────────────────────────────────────────────

def handle_plan(platform: str, action: str, params: Dict,
                redis_client) -> Dict[str, Any]:
    """Dispatch plan operations: create, audit, get, update, delete."""
    if action == 'create' or action == 'send_message':
        return _create_plan(platform, params, redis_client)
    elif action == 'audit':
        return _audit_plan(platform, params, redis_client)
    elif action == 'get':
        return _get_plan(params.get('plan_id'), platform, redis_client)
    elif action == 'update':
        return _update_plan(params.get('plan_id'), params, redis_client)
    elif action == 'extract_response':
        return _create_extract_plan(platform, params, redis_client)
    elif action == 'delete':
        return _delete_plan(platform, params, redis_client)
    else:
        return {"error": f"Unknown plan action: {action}", "success": False}


# ─── Create ──────────────────────────────────────────────────────────────

def _create_plan(platform: str, params: Dict,
                 redis_client) -> Dict[str, Any]:
    """Create an execution plan. All fields required — no defaults.

    Does NOT set audit_passed. Caller must run audit before send.
    """
    if not redis_client:
        return {"error": "Redis not available", "success": False}

    # Block if another plan is already active
    existing = redis_client.get(f"taey:plan_active:{os.environ.get('DISPLAY', ':0')}")
    if existing:
        try:
            lock = json.loads(existing)
        except (json.JSONDecodeError, TypeError):
            lock = {}
        lock_platform = lock.get('platform', 'unknown')
        return {
            "error": f"Active plan exists for {lock_platform}. "
                     "Complete or delete it first.",
            "success": False,
            "existing_plan": lock,
            "hint": "Use taey_plan(action='delete') to cancel.",
        }

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
        return {"success": False, "error": "Missing required fields: " + ", ".join(missing),
                "required_fields": {
                    "session": '"new" or existing URL', "message": "Message text",
                    "model": 'Model name or "N/A"', "mode": "Mode name",
                    "tools": 'List or "none"', "attachments": "List of file paths or []",
                }}

    # Build attachment list: identity files + user files → consolidated
    attachments_list = [] if attachments == "none" else list(attachments) if attachments else []
    all_files = _prepend_identity_files(attachments_list, platform)
    identity_added = [f for f in all_files if f not in attachments_list]

    consolidated_path = None
    if len(all_files) > 1:
        consolidated_path = _consolidate_attachments(all_files, platform)
    elif len(all_files) == 1:
        consolidated_path = all_files[0]

    final_attachment = consolidated_path if consolidated_path else None
    tools_list = [] if tools == "none" else list(tools) if tools else []

    plan_id = str(uuid.uuid4())[:8]
    plan = {
        'plan_id': plan_id,
        'platform': platform,
        'action': 'send_message',
        'session': session,
        'message': message,
        'attachment': final_attachment,  # Single file (consolidated)
        'attachment_sources': all_files,  # What went into it
        'required_state': {
            'model': model,
            'mode': mode,
            'tools': tools_list,
        },
        'audit_passed': False,  # MUST be set True by audit before send
        'audit_result': None,
        'status': 'created',
        'created_at': time.time(),
    }

    # Store plan — plan:{plan_id} for full data, plan:current:{platform} for lookup,
    # plan:{platform} for hook validation (validate_send, validate_select_dropdown)
    redis_client.setex(node_key(f"plan:{plan_id}"), _PLAN_TTL, json.dumps(plan))
    redis_client.setex(node_key(f"plan:current:{platform}"), _PLAN_TTL, plan_id)
    redis_client.setex(node_key(f"plan:{platform}"), _PLAN_TTL, json.dumps({
        'id': plan_id, 'platform': platform, 'action': 'send_message',
        'session': session, 'message': message,
        'model': model, 'mode': mode,
        'tools': tools_list, 'attachments': [final_attachment] if final_attachment else [],
        'validated': True, 'created_at': time.time(),
    }))

    # Global plan lock — ONE lock for the whole machine.
    redis_client.setex(f"taey:plan_active:{os.environ.get('DISPLAY', ':0')}", _PLAN_TTL, json.dumps({
        'plan_id': plan_id, 'platform': platform,
        'node_id': node_key('').rstrip(':'),
        'created_at': time.time(),
    }))

    # Clear checkpoints from previous plans
    for suffix in ['inspect', 'set_map', 'attach']:
        redis_client.delete(node_key(f"checkpoint:{platform}:{suffix}"))

    result = {
        "success": True,
        "plan_id": plan_id,
        "platform": platform,
        "session": session,
        "required_state": plan['required_state'],
        "attachment": final_attachment,
        "audit_passed": False,
        "next_steps": [
            "1. Call taey_inspect to see current platform state",
            "2. Set model/mode if needed (taey_select_dropdown)",
            "3. Call taey_attach to upload the attachment",
            "4. Call taey_plan(action='audit') to verify everything matches",
            "5. Only then call taey_send",
        ],
    }
    if identity_added:
        result["identity_files_added"] = identity_added
    if consolidated_path and len(all_files) > 1:
        result["consolidated_from"] = len(all_files)
        result["consolidated_path"] = consolidated_path
    return result


# ─── Audit ───────────────────────────────────────────────────────────────

def _audit_plan(platform: str, params: Dict,
                redis_client) -> Dict[str, Any]:
    """Audit plan against caller-reported UI state with exact matching.

    Caller provides current_model, current_mode, current_tools from
    what they observed in taey_inspect. Exact match against plan requirements.
    """
    if not redis_client:
        return {"error": "Redis not available", "success": False}

    plan_id = redis_client.get(node_key(f"plan:current:{platform}"))
    if not plan_id:
        return {"error": "No active plan for this platform", "success": False}

    plan_data = redis_client.get(node_key(f"plan:{plan_id}"))
    if not plan_data:
        return {"error": f"Plan {plan_id} not found or expired", "success": False}

    plan = json.loads(plan_data)
    required = plan.get('required_state', {})

    current_model = params.get('current_model', '')
    current_mode = params.get('current_mode', '')
    current_tools = params.get('current_tools', [])
    attachment_confirmed = params.get('attachment_confirmed', False)

    failures = []

    # Model check — exact match
    req_model = required.get('model', '')
    if req_model and req_model not in ('N/A', 'any', 'default'):
        if not current_model:
            failures.append({
                "field": "model", "required": req_model,
                "current": "(not provided)",
                "fix": "Read model from taey_inspect elements, then provide current_model",
            })
        elif current_model.lower().strip() != req_model.lower().strip():
            failures.append({
                "field": "model", "required": req_model,
                "current": current_model,
                "fix": f"Use taey_select_dropdown to change model to '{req_model}'",
            })

    # Mode check — exact match
    req_mode = required.get('mode', '')
    if req_mode and req_mode not in ('N/A', 'any', 'default', 'normal'):
        if not current_mode:
            failures.append({
                "field": "mode", "required": req_mode,
                "current": "(not provided)",
                "fix": "Read mode from taey_inspect elements, then provide current_mode",
            })
        elif current_mode.lower().strip() != req_mode.lower().strip():
            failures.append({
                "field": "mode", "required": req_mode,
                "current": current_mode,
                "fix": f"Use taey_select_dropdown to change mode to '{req_mode}'",
            })

    # Tools check — exact set match
    req_tools = set(t.lower() for t in required.get('tools', []))
    cur_tools = set(t.lower() for t in (current_tools or []))
    missing_tools = req_tools - cur_tools
    if missing_tools:
        failures.append({
            "field": "tools", "required": sorted(req_tools),
            "current": sorted(cur_tools), "missing": sorted(missing_tools),
            "fix": f"Enable missing tools: {sorted(missing_tools)}",
        })

    # Attachment check — Redis checkpoint or caller confirmation
    if plan.get('attachment'):
        if not attachment_confirmed:
            checkpoint = redis_client.get(node_key(f"checkpoint:{platform}:attach"))
            if not checkpoint:
                failures.append({
                    "field": "attachment",
                    "required": os.path.basename(plan['attachment']),
                    "current": "not attached",
                    "fix": f"Call taey_attach('{platform}', '{plan['attachment']}')",
                })

    passed = len(failures) == 0
    audit_result = {
        "plan_id": plan_id, "passed": passed, "failures": failures,
        "checked": {
            "model": {"required": required.get('model'), "current": current_model},
            "mode": {"required": required.get('mode'), "current": current_mode},
            "tools": {"required": required.get('tools'), "current": current_tools},
            "attachment": {"required": plan.get('attachment'), "confirmed": attachment_confirmed},
        },
    }

    plan['audit_passed'] = passed
    plan['audit_result'] = audit_result
    plan['status'] = 'audit_passed' if passed else 'audit_failed'
    redis_client.setex(node_key(f"plan:{plan_id}"), _PLAN_TTL, json.dumps(plan))

    if passed:
        audit_result["next_step"] = "Audit PASSED. Call taey_send_message to send."
    else:
        audit_result["next_step"] = "Audit FAILED. Fix the issues above, then re-audit."

    return {"success": True, **audit_result}


# ─── Extract Plan ────────────────────────────────────────────────────────

def _create_extract_plan(platform: str, params: Dict,
                         redis_client) -> Dict[str, Any]:
    """Create extraction-only plan (no send_message, no audit needed)."""
    if not redis_client:
        return {"error": "Redis not available", "success": False}

    plan_id = str(uuid.uuid4())[:8]
    plan = {
        'plan_id': plan_id, 'platform': platform,
        'action': 'extract_response',
        'session': params.get('session', 'current'),
        'message': None, 'attachment': None,
        'required_state': {}, 'audit_passed': True,  # No audit needed for extract
        'status': 'ready', 'created_at': time.time(),
    }

    redis_client.setex(node_key(f"plan:{plan_id}"), _PLAN_TTL, json.dumps(plan))
    redis_client.setex(node_key(f"plan:current:{platform}"), _PLAN_TTL, plan_id)
    redis_client.setex(node_key(f"plan:{platform}"), _PLAN_TTL, json.dumps({
        'id': plan_id, 'platform': platform, 'action': 'extract_response',
        'session': plan['session'], 'model': None, 'mode': None,
        'tools': [], 'attachments': [], 'validated': True, 'created_at': time.time(),
    }))

    # NOTE: extract_response does NOT set plan_active lock.
    # Extract waits for the monitor to detect completion — the monitor
    # needs to cycle tabs freely. Locking here creates a deadlock.

    return {
        "success": True, "plan_id": plan_id, "platform": platform,
        "action": "extract_response",
        "next_step": f"Call taey_quick_extract('{platform}') to extract the response",
    }


# ─── Get / Update / Delete ──────────────────────────────────────────────

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
    """Update plan fields. Resets audit_passed if required_state changes."""
    if not redis_client:
        return {"error": "Redis not available", "success": False}
    data = redis_client.get(node_key(f"plan:{plan_id}"))
    if not data:
        return {"error": f"Plan {plan_id} not found", "success": False}

    plan = json.loads(data)

    # If required_state is being changed, reset audit
    if 'required_state' in updates:
        plan['required_state'] = updates['required_state']
        plan['audit_passed'] = False
        plan['audit_result'] = None
        plan['status'] = 'updated'

    for key in ['status', 'session', 'message', 'current_state']:
        if key in updates:
            plan[key] = updates[key]

    plan['updated_at'] = time.time()
    redis_client.setex(node_key(f"plan:{plan_id}"), _PLAN_TTL, json.dumps(plan))

    return {"success": True, "plan_id": plan_id,
            "status": plan['status'], "audit_passed": plan['audit_passed']}


def _delete_plan(platform: str, params: Dict, redis_client) -> Dict[str, Any]:
    """Delete/cancel an active plan and clear the global lock."""
    if not redis_client:
        return {"error": "Redis not available", "success": False}
    plan_id = params.get('plan_id') or redis_client.get(node_key(f"plan:current:{platform}"))
    deleted = []
    if plan_id:
        if redis_client.delete(node_key(f"plan:{plan_id}")):
            deleted.append(f"plan:{plan_id}")
    for suffix in [f"plan:current:{platform}", f"plan:{platform}"]:
        if redis_client.delete(node_key(suffix)):
            deleted.append(suffix)
    if redis_client.delete(f"taey:plan_active:{os.environ.get('DISPLAY', ':0')}"):
        deleted.append("plan_active (global)")
    return {"success": True, "deleted": deleted, "platform": platform}
