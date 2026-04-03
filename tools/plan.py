"""taey_plan - Create, audit, and manage execution plans.

The plan is the single source of truth. Flow:
  1. create  → store required model/mode/attachments in Redis
  2. audit   → scan AT-SPI tree directly → PASS or FAIL
  3. send.py → hard-blocked until audit_passed=True

No plan ships without audit. No send happens without a passed audit.

Audit is the hard gate: it scans the live AT-SPI tree to verify state
instead of trusting what the caller reports. Caller params are accepted
as hints only and used as fallback when tree verification is unavailable.
"""

import json
import os
import time
import uuid
import logging
from typing import Any, Dict, List, Optional, Tuple

from storage.redis_pool import node_key
from core.config import get_platform_config, get_element_spec, get_fence_after, get_validation

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
_PLAN_TTL = int(os.environ.get('TAEY_PLAN_TTL', '3600'))  # Default 1 hour (was 600s/10min)

# Platforms where model verification from the tree is unreliable without
# reopening the dropdown (complex interaction). Fall back to caller-reported.
_UNVERIFIABLE_MODEL_PLATFORMS = {'gemini', 'grok'}


def _inject_consultation_defaults(platform: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Attach platform consultation defaults to plan responses."""
    try:
        config = get_platform_config(platform)
    except (FileNotFoundError, ValueError):
        return result

    defaults = config.get('consultation_defaults')
    if not defaults:
        return result

    enriched = dict(result)
    enriched.setdefault('consultation_defaults', defaults)
    return enriched


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
        result = _create_plan(platform, params, redis_client)
    elif action == 'audit':
        result = _audit_plan(platform, params, redis_client)
    elif action == 'get':
        result = _get_plan(params.get('plan_id'), platform, redis_client)
    elif action == 'update':
        result = _update_plan(params.get('plan_id'), params, redis_client)
    elif action == 'extract_response':
        result = _create_extract_plan(platform, params, redis_client)
    elif action == 'delete':
        result = _delete_plan(platform, params, redis_client)
    else:
        return {"error": f"Unknown plan action: {action}", "success": False}

    return _inject_consultation_defaults(platform, result)


# ─── Create ──────────────────────────────────────────────────────────────

def _create_plan(platform: str, params: Dict,
                 redis_client) -> Dict[str, Any]:
    """Create an execution plan.

    For fresh sessions (session="new"): all fields required — no defaults.
    For follow-ups (session=URL): only session + message required.
      Model/mode/tools/attachments are optional (inherited from original session).

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
    # Follow-up sessions (URL) only need session + message.
    # Fresh sessions ("new") need everything.
    session = params.get('session')
    message = params.get('message')
    model = params.get('model')
    mode = params.get('mode')
    tools = params.get('tools')
    attachments = params.get('attachments')

    is_followup = session and session != 'new' and session.startswith('http')

    missing = []
    if not session:
        missing.append('session ("new" or URL)')
    if not message:
        missing.append('message')

    if not is_followup:
        # Fresh sessions require all fields
        if not model:
            missing.append('model')
        if not mode:
            missing.append('mode')
        if tools is None:
            missing.append('tools (list or "none")')
        if attachments is None:
            missing.append('attachments (list or [])')

    if missing:
        required_fields = {"session": '"new" or existing URL', "message": "Message text"}
        if not is_followup:
            required_fields.update({
                "model": 'Model name or "N/A"',
                "mode": "Mode name",
                "tools": 'List or "none"',
                "attachments": "List of file paths or []",
            })
        return {"success": False, "error": "Missing required fields: " + ", ".join(missing),
                "required_fields": required_fields}

    # Default optional fields for follow-ups
    if is_followup:
        model = model or 'inherited'
        mode = mode or 'inherited'
        if tools is None:
            tools = 'none'
        if attachments is None:
            attachments = []

    # Build attachment list:
    # Follow-ups: NO identity files. Only user-provided attachments.
    # Fresh sessions: identity files + user files → consolidated.
    attachments_list = [] if attachments == "none" else list(attachments) if attachments else []

    if is_followup:
        # Follow-ups: use attachments as-is (no identity prepend)
        all_files = attachments_list
        identity_added = []
    else:
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
        'followup': is_followup,
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

    if is_followup:
        next_steps = [
            "1. Navigate to session URL",
            "2. Call taey_attach if follow-up attachments needed",
            "3. Call taey_plan(action='audit') to verify",
            "4. Call taey_send",
        ]
    else:
        next_steps = [
            "1. Call taey_inspect to see current platform state",
            "2. Set model/mode if needed (taey_select_dropdown)",
            "3. Call taey_attach to upload the attachment",
            "4. Call taey_plan(action='audit') to verify everything matches",
            "5. Only then call taey_send",
        ]

    result = {
        "success": True,
        "plan_id": plan_id,
        "platform": platform,
        "session": session,
        "followup": is_followup,
        "required_state": plan['required_state'],
        "attachment": final_attachment,
        "audit_passed": False,
        "next_steps": next_steps,
    }
    if identity_added:
        result["identity_files_added"] = identity_added
    if consolidated_path and len(all_files) > 1:
        result["consolidated_from"] = len(all_files)
        result["consolidated_path"] = consolidated_path
    return result


# ─── Audit — Tree-based verification helpers ─────────────────────────────

def _scan_platform_elements(platform: str) -> Tuple[Optional[List[Dict]], Optional[str]]:
    """Scan the live AT-SPI tree for platform elements.

    Returns (elements, error_message). Handles both local and multi-display
    (Mira subprocess) modes via scan_platform_tree().
    Elements are raw dicts (no atspi_obj). Returns (None, error) on failure.
    """
    try:
        from core.config import scan_platform_tree
        elements, url, error = scan_platform_tree(platform)
        if error:
            return None, error
        return elements, None
    except Exception as e:
        logger.warning("AT-SPI tree scan failed for %s: %s", platform, e)
        return None, f"AT-SPI scan error: {e}"


def _find_element_by_spec(elements: List[Dict], spec: Dict) -> Optional[Dict]:
    """Find the first element in the list matching an element_map spec dict.

    Uses the same matching logic as inspect._match_element.
    """
    import fnmatch

    for element in elements:
        name = (element.get('name') or '').strip()
        name_lower = name.lower()
        role = element.get('role', '')
        states = set(s.lower() for s in element.get('states', []))

        matched = True

        if 'name' in spec and name_lower != str(spec['name']).lower():
            matched = False
        if matched and 'name_contains' in spec:
            pats = spec['name_contains']
            if isinstance(pats, str):
                pats = [pats]
            if not any(str(p).lower() in name_lower for p in pats):
                matched = False
        if matched and 'name_pattern' in spec:
            pats = spec['name_pattern']
            if isinstance(pats, str):
                pats = [pats]
            if not any(fnmatch.fnmatch(name_lower, str(p).lower()) for p in pats):
                matched = False
        if matched and 'role' in spec and role != spec['role']:
            matched = False
        if matched and 'role_contains' in spec and str(spec['role_contains']) not in role:
            matched = False
        if matched and 'states_include' in spec:
            if not set(s.lower() for s in spec['states_include']).issubset(states):
                matched = False

        if matched:
            return element

    return None


def _read_current_model_from_tree(
    platform: str,
    elements: List[Dict],
    config: Dict,
) -> Tuple[Optional[str], str]:
    """Read the currently selected model from the AT-SPI tree.

    Returns (model_name_or_None, verification_source).
    verification_source is one of: 'tree', 'unverifiable', 'error'

    Platform-specific logic:
      chatgpt:    model_selector button name = "Model selector, current model is {name}"
                  → extract name after "current model is "
      claude:     model_selector button name IS the model name (name_is_model=True)
                  → return button name directly
      gemini:     mode picker button text doesn't change; needs dropdown reopen → unverifiable
      grok:       model select button text doesn't change; needs dropdown reopen → unverifiable
      perplexity: model button name is static "Model"; name_is_model=True in validation
                  but the element_map criteria won't match a changed name → unverifiable
    """
    if platform in _UNVERIFIABLE_MODEL_PLATFORMS:
        logger.info(
            "Model verification for %s requires reopening dropdown (reopen_to_verify). "
            "Falling back to caller-reported model.", platform
        )
        return None, 'unverifiable'

    validation = config.get('validation', {})
    model_val = validation.get('model_selected', {})

    # Get the model_selector element spec from element_map
    selector_spec = get_element_spec(platform, 'model_selector')
    if not selector_spec:
        logger.warning("No model_selector in element_map for %s", platform)
        return None, 'error'

    selector_elem = _find_element_by_spec(elements, selector_spec)
    if not selector_elem:
        logger.info("model_selector element not found in AT-SPI tree for %s", platform)
        return None, 'error'

    button_name = (selector_elem.get('name') or '').strip()
    if not button_name:
        return None, 'error'

    # ChatGPT: "Model selector, current model is {name}"
    if model_val.get('name_contains_model'):
        _PREFIX = 'current model is '
        idx = button_name.lower().find(_PREFIX)
        if idx != -1:
            model_name = button_name[idx + len(_PREFIX):].strip()
            if model_name:
                logger.info("ChatGPT tree model: %r (from button: %r)", model_name, button_name)
                return model_name, 'tree'
        logger.warning(
            "ChatGPT model_selector name did not match expected pattern: %r", button_name
        )
        return None, 'error'

    # Claude (and perplexity if reachable): button name IS the model name
    if model_val.get('name_is_model'):
        # For perplexity, the static name "Model" means the element_map won't
        # find a changed button — if we got here, the button name is the model.
        # But perplexity is excluded above via _UNVERIFIABLE_MODEL_PLATFORMS
        # (its element_map name stays "Model"). For Claude, this works perfectly.
        logger.info("%s tree model: %r", platform, button_name)
        return button_name, 'tree'

    # Fallback: return the button name as-is and let caller decide
    logger.info("%s model_selector name: %r (no specific parse rule)", platform, button_name)
    return button_name, 'tree'


def _check_attachment_in_tree(
    platform: str,
    elements: List[Dict],
    config: Dict,
) -> Tuple[Optional[bool], str]:
    """Check whether an attachment is present in the AT-SPI tree.

    Returns (attached_bool_or_None, verification_source).
    verification_source: 'tree' if tree gave a clear answer, 'error' if scan failed.

    Looks for indicators from validation.attach_success.indicators in the YAML.
    Typically: a "Remove" button near the input area indicates an attachment is present.
    """
    validation = config.get('validation', {})
    attach_val = validation.get('attach_success', {})
    indicators = attach_val.get('indicators', [])

    if not indicators:
        logger.info("No attach indicators configured for %s", platform)
        return None, 'error'

    for indicator in indicators:
        found = _find_element_by_spec(elements, indicator)
        if found:
            logger.info(
                "%s attachment indicator found in tree: %r (role=%r)",
                platform, found.get('name', ''), found.get('role', '')
            )
            return True, 'tree'

    # No indicator found — attachment is NOT present (tree gave a clear negative)
    return False, 'tree'


# ─── Audit ───────────────────────────────────────────────────────────────

def _audit_plan(platform: str, params: Dict,
                redis_client) -> Dict[str, Any]:
    """Audit plan against live AT-SPI tree state with caller params as fallback hints.

    Scans the AT-SPI tree directly to verify model and attachment state.
    Caller-provided params (current_model, current_mode, current_tools,
    attachment_confirmed) are used as hints and fallback when tree verification
    is unavailable (e.g. Gemini/Grok model requires dropdown reopen).

    Each checked field records a 'verification_source':
      'tree'            — verified by reading the live AT-SPI tree
      'caller_reported' — tree could not verify; accepted from caller params
      'unverifiable'    — platform known to not support tree verification for this field
      'redis_checkpoint'— verified via Redis checkpoint (attachment only)
      'not_required'    — field not required by plan; check skipped
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

    # Caller-provided hints (fallback when tree can't verify)
    caller_model = params.get('current_model', '')
    caller_mode = params.get('current_mode', '')
    caller_tools = params.get('current_tools', [])
    attachment_confirmed = params.get('attachment_confirmed', False)

    # ── Step 1: Scan the live AT-SPI tree ────────────────────────────────
    config = get_platform_config(platform)
    elements, scan_error = _scan_platform_elements(platform)

    tree_available = elements is not None
    if not tree_available:
        logger.warning(
            "AT-SPI tree scan unavailable for %s audit: %s — falling back to caller params",
            platform, scan_error
        )

    # ── Step 2: Read model from tree ─────────────────────────────────────
    tree_model: Optional[str] = None
    model_source = 'caller_reported'

    if tree_available:
        tree_model, model_verification = _read_current_model_from_tree(
            platform, elements, config
        )
        if model_verification == 'tree':
            model_source = 'tree'
        elif model_verification == 'unverifiable':
            model_source = 'unverifiable'
            logger.info(
                "%s model is unverifiable from tree — using caller-reported: %r",
                platform, caller_model
            )
        # 'error' falls through to caller_reported

    actual_model = tree_model if tree_model else caller_model

    # ── Step 3: Check attachment in tree ─────────────────────────────────
    tree_attached: Optional[bool] = None
    attach_source = 'caller_reported'

    if tree_available and plan.get('attachment'):
        tree_attached, attach_verification = _check_attachment_in_tree(
            platform, elements, config
        )
        if attach_verification == 'tree':
            attach_source = 'tree'

    # Determine actual attachment state:
    # Tree gives a definitive answer when available.
    # Fall back to caller confirmation or Redis checkpoint.
    actual_attached: bool
    if attach_source == 'tree' and tree_attached is not None:
        actual_attached = tree_attached
    elif attachment_confirmed:
        actual_attached = True
        attach_source = 'caller_reported'
    else:
        # Check Redis checkpoint as a secondary fallback
        checkpoint = redis_client.get(node_key(f"checkpoint:{platform}:attach"))
        if checkpoint:
            actual_attached = True
            attach_source = 'redis_checkpoint'
        else:
            actual_attached = False
            attach_source = 'caller_reported' if not tree_available else attach_source

    # ── Step 4: Apply checks ──────────────────────────────────────────────
    failures = []

    # Model check — exact match (case-insensitive)
    # 'inherited' = follow-up session, model inherited from original — skip check.
    req_model = required.get('model', '')
    _MODEL_SKIP = ('N/A', 'any', 'default', 'inherited')
    model_check_source = model_source if req_model and req_model not in _MODEL_SKIP \
        else 'not_required'

    if req_model and req_model not in _MODEL_SKIP:
        if not actual_model:
            failures.append({
                "field": "model",
                "required": req_model,
                "current": "(not detected)",
                "fix": (
                    f"Provide current_model to audit, or use taey_inspect to read "
                    f"the model selector, then call taey_select_dropdown to set '{req_model}'"
                ),
                "verification_source": model_check_source,
            })
        elif actual_model.lower().strip() != req_model.lower().strip():
            failures.append({
                "field": "model",
                "required": req_model,
                "current": actual_model,
                "fix": f"Use taey_select_dropdown to change model to '{req_model}'",
                "verification_source": model_check_source,
            })

    # Mode check — exact match (case-insensitive)
    # 'inherited' = follow-up session, mode inherited from original — skip check.
    req_mode = required.get('mode', '')
    _MODE_SKIP = ('N/A', 'any', 'default', 'normal', 'inherited')
    mode_source = 'caller_reported'  # Mode is always caller-reported (no tree read yet)

    if req_mode and req_mode not in _MODE_SKIP:
        if not caller_mode:
            failures.append({
                "field": "mode",
                "required": req_mode,
                "current": "(not provided)",
                "fix": "Read mode from taey_inspect elements, then provide current_mode",
                "verification_source": mode_source,
            })
        elif caller_mode.lower().strip() != req_mode.lower().strip():
            failures.append({
                "field": "mode",
                "required": req_mode,
                "current": caller_mode,
                "fix": f"Use taey_select_dropdown to change mode to '{req_mode}'",
                "verification_source": mode_source,
            })

    # Tools check — exact set match
    req_tools = set(t.lower() for t in required.get('tools', []))
    cur_tools = set(t.lower() for t in (caller_tools or []))
    tools_source = 'caller_reported'
    missing_tools = req_tools - cur_tools
    if missing_tools:
        failures.append({
            "field": "tools",
            "required": sorted(req_tools),
            "current": sorted(cur_tools),
            "missing": sorted(missing_tools),
            "fix": f"Enable missing tools: {sorted(missing_tools)}",
            "verification_source": tools_source,
        })

    # Attachment check
    if plan.get('attachment'):
        if not actual_attached:
            failures.append({
                "field": "attachment",
                "required": os.path.basename(plan['attachment']),
                "current": "not attached",
                "fix": f"Call taey_attach('{platform}', '{plan['attachment']}')",
                "verification_source": attach_source,
            })

    # ── Step 5: Build result ───────────────────────────────────────────────
    passed = len(failures) == 0

    checked = {
        "model": {
            "required": required.get('model'),
            "current": actual_model,
            "verification_source": model_check_source,
        },
        "mode": {
            "required": required.get('mode'),
            "current": caller_mode,
            "verification_source": mode_source,
        },
        "tools": {
            "required": required.get('tools'),
            "current": list(cur_tools),
            "verification_source": tools_source,
        },
        "attachment": {
            "required": plan.get('attachment'),
            "confirmed": actual_attached,
            "verification_source": attach_source if plan.get('attachment') else 'not_required',
        },
    }

    # Note if tree scan was unavailable
    audit_notes = []
    if not tree_available:
        audit_notes.append(
            f"AT-SPI tree scan unavailable ({scan_error}). "
            "All checks used caller-reported values — less reliable."
        )
    elif model_source == 'unverifiable':
        audit_notes.append(
            f"{platform} model cannot be verified from static tree "
            f"(requires dropdown reopen). Accepted caller-reported model: {caller_model!r}."
        )

    audit_result = {
        "plan_id": plan_id,
        "passed": passed,
        "failures": failures,
        "checked": checked,
    }
    if audit_notes:
        audit_result["audit_notes"] = audit_notes

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

    redis_client.setex(f"taey:plan_active:{os.environ.get('DISPLAY', ':0')}", _PLAN_TTL, json.dumps({
        'plan_id': plan_id, 'platform': platform,
        'node_id': node_key('').rstrip(':'),
        'created_at': time.time(),
    }))

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
