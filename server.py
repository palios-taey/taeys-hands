#!/usr/bin/env python3
"""Taey's Hands - MCP Server (AT-SPI platform automation over JSON-RPC/stdio)."""

import sys
import os
import json
import logging
import signal
import traceback
from typing import Any, Dict, List


class ToolTimeoutError(Exception):
    pass


def _tool_timeout_handler(signum, frame):
    raise ToolTimeoutError("Tool execution timed out")


TOOL_TIMEOUT_SECONDS = int(os.environ.get('MCP_TOOL_TIMEOUT', '120'))

# Load .env
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _val = _line.split('=', 1)
                os.environ.setdefault(_key.strip(), _val.strip())

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('/tmp/taey_mcp_debug.log')],
)
logger = logging.getLogger('taeys-hands')

# Set DISPLAY before AT-SPI imports
from core.atspi import detect_display
DISPLAY = detect_display()
os.environ['DISPLAY'] = DISPLAY

# Storage backends (required)
from storage.redis_pool import get_client as get_redis, node_key

try:
    from storage import neo4j_client
except Exception as e:
    logger.warning("Neo4j unavailable: %s", e)
    neo4j_client = None

from tools.inspect import handle_inspect
from tools.click import handle_click
from tools.send import handle_send_message
from tools.extract import handle_quick_extract, handle_extract_history
from tools.attach import handle_attach
from tools.dropdown import handle_select_dropdown, handle_prepare
from tools.plan import handle_plan
from tools.sessions import handle_list_sessions
from tools.monitors import handle_monitors, handle_respawn_monitor


class SafeJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return str(obj)
        return super().default(obj)


def get_pending_notifications(redis_client) -> List[Dict]:
    notifications = []
    if not redis_client:
        return notifications
    try:
        while len(notifications) < 10:
            data = redis_client.lpop(node_key("notifications"))
            if not data:
                break
            try:
                notifications.append(json.loads(data))
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    return notifications


def inject_notifications(result: Dict, redis_client) -> Dict:
    notifications = get_pending_notifications(redis_client)
    if notifications:
        result['_notifications'] = notifications
    return result


# =========================================================================
# Tool definitions
# =========================================================================

ALL_PLATFORMS = ["chatgpt", "claude", "gemini", "grok", "perplexity", "x_twitter", "linkedin"]
PLATFORM_PROP = {"type": "string", "enum": ALL_PLATFORMS, "description": "Which chat platform"}


def get_tools() -> List[Dict]:
    return [
        {"name": "taey_inspect",
         "description": "Switch to platform tab, scan AT-SPI tree, return elements with x,y coords. REQUIRES taey_plan first (sets monitor lock). Use fresh_session=true for new chat.",
         "inputSchema": {"type": "object", "properties": {
             "platform": {**PLATFORM_PROP},
             "scroll": {"type": "string", "enum": ["bottom", "top", "none"],
                        "description": "Scroll before scan. 'none'=pure scan (no tab switch/scroll)."},
             "fresh_session": {"type": "boolean", "description": "Navigate to base URL for fresh chat."},
         }, "required": ["platform"]}},

        {"name": "taey_click",
         "description": "Click at x,y coords from inspect results (AT-SPI first, xdotool fallback).",
         "inputSchema": {"type": "object", "properties": {
             "platform": PLATFORM_PROP,
             "x": {"type": "number"}, "y": {"type": "number"},
         }, "required": ["platform", "x", "y"]}},

        {"name": "taey_prepare",
         "description": "Get platform capabilities (models/modes/tools) from YAML config.",
         "inputSchema": {"type": "object", "properties": {
             "platform": PLATFORM_PROP,
         }, "required": ["platform"]}},

        {"name": "taey_plan",
         "description": "Create/get/update execution plan. Plans track required state, attachments, message, steps. Identity files (FAMILY_KERNEL + platform-specific) are auto-prepended — only pass your own files in attachments.",
         "inputSchema": {"type": "object", "properties": {
             "platform": PLATFORM_PROP,
             "action": {"type": "string", "enum": ["send_message", "extract_response", "audit", "get", "update", "delete"]},
             "params": {"type": "object", "properties": {
                 "plan_id": {"type": "string"}, "message": {"type": "string"},
                 "session": {"type": "string", "description": "'new' or existing URL"},
                 "mode": {"type": "string"}, "model": {"type": "string"},
                 "tools": {"type": "array", "items": {"type": "string"},
                           "description": "List of tool names or empty array"},
                 "attachments": {"type": "array", "items": {"type": "string"}},
                 "current_state": {"type": "object"}, "steps": {"type": "array"},
                 "status": {"type": "string"},
                 "current_model": {"type": "string"}, "current_mode": {"type": "string"},
                 "current_tools": {"type": "array", "items": {"type": "string"}},
                 "attachment_confirmed": {"type": "boolean"},
             }},
         }, "required": ["platform", "action"]}},

        {"name": "taey_send_message",
         "description": "Paste message, press Enter, store in Neo4j, spawn monitor. Click input field via taey_click FIRST.",
         "inputSchema": {"type": "object", "properties": {
             "platform": PLATFORM_PROP,
             "message": {"type": "string", "description": "Message text"},
             "attachments": {"type": "array", "items": {"type": "string"}},
             "session_type": {"type": "string"}, "purpose": {"type": "string"},
         }, "required": ["platform", "message"]}},

        {"name": "taey_quick_extract",
         "description": "Click newest Copy button, read clipboard, return response text. complete=true consumes plan.",
         "inputSchema": {"type": "object", "properties": {
             "platform": PLATFORM_PROP,
             "complete": {"type": "boolean"},
         }, "required": ["platform"]}},

        {"name": "taey_extract_history",
         "description": "Extract full conversation history by scrolling through all Copy buttons.",
         "inputSchema": {"type": "object", "properties": {
             "platform": PLATFORM_PROP,
             "max_messages": {"type": "integer"},
         }, "required": ["platform"]}},

        {"name": "taey_attach",
         "description": "Attach file: clicks attach button, handles file dialog or returns dropdown for Claude to pick from.",
         "inputSchema": {"type": "object", "properties": {
             "platform": PLATFORM_PROP,
             "file_path": {"type": "string", "description": "Absolute path to file"},
         }, "required": ["platform", "file_path"]}},

        {"name": "taey_select_dropdown",
         "description": "Open dropdown (model/mode/tools), return items for Claude to click.",
         "inputSchema": {"type": "object", "properties": {
             "platform": PLATFORM_PROP,
             "dropdown": {"type": "string", "description": "Dropdown trigger name"},
             "target_value": {"type": "string", "description": "Value to select"},
         }, "required": ["platform", "dropdown", "target_value"]}},

        {"name": "taey_list_sessions",
         "description": "Show active sessions, pending responses, and next-action recommendation.",
         "inputSchema": {"type": "object", "properties": {
             "platform": {**PLATFORM_PROP, "description": "Optional filter"},
         }, "required": []}},

        {"name": "taey_monitors",
         "description": "List or kill background monitor daemons.",
         "inputSchema": {"type": "object", "properties": {
             "action": {"type": "string", "enum": ["list", "kill"]},
         }, "required": ["action"]}},

        {"name": "taey_respawn_monitor",
         "description": "Spawn fresh monitor for multi-step flows (Gemini Deep Research, Claude Continue).",
         "inputSchema": {"type": "object", "properties": {
             "platform": PLATFORM_PROP,
         }, "required": ["platform"]}},
    ]


# =========================================================================
# Tool routing (dict-based dispatch)
# =========================================================================

def _validate_required(args, *keys):
    for k in keys:
        if not args.get(k):
            return {"error": f"{k} is required"}
    return None

def _validate_required_any(args, *keys):
    for k in keys:
        if args.get(k) is None:
            return {"error": f"{k} is required"}
    return None


def _h_inspect(args, rc):
    return handle_inspect(args['platform'], rc, scroll=args.get('scroll', 'bottom'),
                          fresh_session=args.get('fresh_session', False))

def _h_click(args, rc):
    err = _validate_required_any(args, 'x', 'y')
    return err or handle_click(args['platform'], int(args['x']), int(args['y']))

def _h_prepare(args, rc):
    return handle_prepare(args['platform'], rc)

def _h_plan(args, rc):
    err = _validate_required(args, 'action')
    return err or handle_plan(args['platform'], args['action'], args.get('params', {}), rc)

def _h_send(args, rc):
    err = _validate_required(args, 'message')
    return err or handle_send_message(args['platform'], args['message'], rc, DISPLAY,
                                       args.get('attachments'), args.get('session_type'),
                                       args.get('purpose'))

def _h_extract(args, rc):
    return handle_quick_extract(args['platform'], rc, neo4j_client, args.get('complete', False))

def _h_history(args, rc):
    return handle_extract_history(args['platform'], rc, args.get('max_messages', 500))

def _h_attach(args, rc):
    err = _validate_required(args, 'file_path')
    return err or handle_attach(args['platform'], args['file_path'], rc)

def _h_dropdown(args, rc):
    err = _validate_required(args, 'dropdown', 'target_value')
    return err or handle_select_dropdown(args['platform'], args['dropdown'],
                                          args['target_value'], rc)

def _h_sessions(args, rc):
    return handle_list_sessions(args.get('platform'), rc)

def _h_monitors(args, rc):
    err = _validate_required(args, 'action')
    return err or handle_monitors(args['action'], rc)

def _h_respawn(args, rc):
    return handle_respawn_monitor(args['platform'], rc, DISPLAY)


_TOOL_HANDLERS = {
    'taey_inspect': ('platform', _h_inspect),
    'taey_click': ('platform', _h_click),
    'taey_prepare': ('platform', _h_prepare),
    'taey_plan': ('platform', _h_plan),
    'taey_send_message': ('platform', _h_send),
    'taey_quick_extract': ('platform', _h_extract),
    'taey_extract_history': ('platform', _h_history),
    'taey_attach': ('platform', _h_attach),
    'taey_select_dropdown': ('platform', _h_dropdown),
    'taey_list_sessions': (None, _h_sessions),
    'taey_monitors': (None, _h_monitors),
    'taey_respawn_monitor': ('platform', _h_respawn),
}

# Tools that require an active plan before they can run.
# These interact with the platform UI (switch tabs, click, type).
# Without a plan, the monitor cycles tabs and disrupts the workflow.
_REQUIRES_PLAN = {
    'taey_inspect', 'taey_click', 'taey_attach',
    'taey_send_message', 'taey_select_dropdown',
    'taey_quick_extract', 'taey_extract_history',
}


def _check_plan_required(name: str, args: Dict, redis_client) -> Dict:
    """Block platform UI tools unless a plan exists for that platform."""
    if name not in _REQUIRES_PLAN:
        return None
    platform = args.get('platform')
    if not platform or not redis_client:
        return None
    plan_id = redis_client.get(node_key(f"plan:current:{platform}"))
    if plan_id:
        return None
    return {
        "error": f"No plan exists for {platform}. Create one first with "
                 f"taey_plan(platform='{platform}', action='send_message', "
                 f"params={{...}}) or taey_plan(platform='{platform}', "
                 f"action='extract_response'). "
                 f"Plans set a lock that prevents the monitor from cycling tabs.",
        "fix": "taey_plan",
    }


def handle_tool(name: str, args: Dict, redis_client) -> Dict:
    if not redis_client:
        return {"error": "Redis is not connected. Redis is required infrastructure. "
                "Ensure Redis is running and restart the MCP server."}
    entry = _TOOL_HANDLERS.get(name)
    if not entry:
        return {"error": f"Unknown tool: {name}"}
    required_key, handler = entry
    if required_key:
        err = _validate_required(args, required_key)
        if err:
            return err
    err = _check_plan_required(name, args, redis_client)
    if err:
        return err
    result = handler(args, redis_client)
    return inject_notifications(result, redis_client)


# =========================================================================
# MCP Server (JSON-RPC over stdio)
# =========================================================================

def run_server():
    try:
        redis_client = get_redis()
    except Exception as e:
        logger.warning("Redis unavailable at startup: %s", e)
        redis_client = None

    def read_message():
        line = sys.stdin.readline()
        return json.loads(line.strip()) if line else None

    def write_message(msg):
        sys.stdout.write(json.dumps(msg, cls=SafeJSONEncoder) + '\n')
        sys.stdout.flush()

    logger.info("Taey's Hands MCP server starting (display=%s)", DISPLAY)

    while True:
        try:
            msg = read_message()
            if msg is None:
                break

            method = msg.get('method')
            params = msg.get('params', {})
            msg_id = msg.get('id')

            if method == 'initialize':
                write_message({"jsonrpc": "2.0", "id": msg_id, "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "taeys-hands", "version": "7.0.0"},
                    "capabilities": {"tools": {}},
                }})

            elif method == 'tools/list':
                write_message({"jsonrpc": "2.0", "id": msg_id,
                              "result": {"tools": get_tools()}})

            elif method == 'tools/call':
                tool_name = params.get('name')
                tool_args = params.get('arguments', {})
                old_handler = signal.signal(signal.SIGALRM, _tool_timeout_handler)
                signal.alarm(TOOL_TIMEOUT_SECONDS)
                try:
                    result = handle_tool(tool_name, tool_args, redis_client)
                except ToolTimeoutError:
                    result = {"error": f"Tool '{tool_name}' timed out after {TOOL_TIMEOUT_SECONDS}s"}
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                is_error = isinstance(result, dict) and result.get('error') is not None
                write_message({"jsonrpc": "2.0", "id": msg_id, "result": {
                    "content": [{"type": "text",
                                 "text": json.dumps(result, indent=2, cls=SafeJSONEncoder)}],
                    "isError": is_error,
                }})

            elif method == 'notifications/initialized':
                pass

            else:
                write_message({"jsonrpc": "2.0", "id": msg_id,
                              "error": {"code": -32601, "message": f"Method not found: {method}"}})

        except json.JSONDecodeError as e:
            write_message({"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32700, "message": f"Parse error: {e}"}})
        except Exception as e:
            logger.error("Internal error: %s", traceback.format_exc())
            write_message({"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32603, "message": f"Internal error: {e}"}})


if __name__ == '__main__':
    run_server()
