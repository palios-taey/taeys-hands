#!/usr/bin/env python3
"""
Taey's Hands - MCP Server
AT-SPI-based chat and social platform automation.

Simple JSON-RPC over stdio (no mcp library) for AT-SPI compatibility
with system Python + gi.repository.

Run: python3 server.py
"""

import sys
import os
import json
import logging
import traceback
from typing import Any, Dict, List

# Load .env file (Redis host, Neo4j URI, etc.)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _val = _line.split('=', 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# Logging to file (stderr reserved for JSON-RPC)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('/tmp/taey_mcp_debug.log')],
)
logger = logging.getLogger('taeys-hands')

# =========================================================================
# CRITICAL: Set DISPLAY on Linux BEFORE importing AT-SPI modules
# On macOS, no DISPLAY needed — uses AXUIElement API instead
# =========================================================================
if sys.platform != 'darwin':
    from core.atspi import detect_display
    DISPLAY = detect_display()
    os.environ['DISPLAY'] = DISPLAY
else:
    DISPLAY = None  # macOS doesn't use X11

# Now safe to import platform-dependent modules

# Storage backends (optional - server works without them but persistence is disabled)
try:
    from storage.redis_pool import get_client as get_redis, node_key
except Exception as e:
    logger.warning("Redis unavailable: %s. Monitor notifications and state persistence disabled.", e)
    get_redis = lambda: None
    def node_key(suffix): return f"taey:local:{suffix}"

try:
    from storage import neo4j_client
except Exception as e:
    logger.warning("Neo4j unavailable: %s. Conversation history persistence disabled.", e)
    neo4j_client = None

from tools.inspect import handle_inspect
from tools.interact import handle_click
from tools.send_message import handle_send_message
from tools.extract import handle_quick_extract, handle_extract_history
from tools.attach import handle_attach
from tools.dropdown import handle_select_dropdown, handle_prepare
from tools.plan import handle_plan
from tools.sessions import handle_list_sessions
from tools.monitors import handle_monitors, handle_respawn_monitor


# =========================================================================
# Custom JSON encoder for Neo4j types
# =========================================================================

class SafeJSONEncoder(json.JSONEncoder):
    """Handle Neo4j DateTime and other non-serializable types."""

    def default(self, obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return str(obj)
        return super().default(obj)


# =========================================================================
# Notification injection (piggybacking pattern)
# =========================================================================

def get_pending_notifications(redis_client) -> List[Dict]:
    """Pop pending notifications from background monitors."""
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
    """Attach any pending monitor notifications to the result."""
    notifications = get_pending_notifications(redis_client)
    if notifications:
        result['_notifications'] = notifications
    return result


# =========================================================================
# Tool definitions (JSON schemas for MCP)
# =========================================================================

ALL_PLATFORMS = ["chatgpt", "claude", "gemini", "grok", "perplexity", "x_twitter", "linkedin"]

PLATFORM_PROP = {
    "type": "string",
    "enum": ALL_PLATFORMS,
    "description": "Which chat platform",
}


def get_tools() -> List[Dict]:
    """Return all MCP tool definitions."""
    return [
        {
            "name": "taey_inspect",
            "description": (
                "Inspect a chat platform and get the complete control map.\n\n"
                "Switches to the platform tab (Alt+N), scrolls to bottom (End), and returns:\n"
                "- URL of current conversation\n"
                "- State (model, mode, copy button count)\n"
                "- Controls (all visible elements for Claude to interpret)\n\n"
                "ALWAYS call this FIRST before any other taey_ tool."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": {**PLATFORM_PROP, "description": "Which chat platform to inspect"},
                    "scroll": {
                        "type": "string",
                        "enum": ["bottom", "top", "none"],
                        "description": (
                            "Where to scroll before scanning. Default 'bottom' (see latest chat). "
                            "Use 'none' for PURE SCAN — no tab switch, no scroll, no keyboard input. "
                            "Essential when a dropdown/menu is open or mid-workflow. "
                            "Use 'top' to scroll to page top first."
                        ),
                    },
                },
                "required": ["platform"],
            },
        },
        {
            "name": "taey_click",
            "description": (
                "Click at coordinates from inspect results.\n\n"
                "AT-SPI first (cached then fresh scan), xdotool fallback.\n"
                "Use coordinates from taey_inspect element list."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": PLATFORM_PROP,
                    "x": {"type": "number", "description": "X coordinate to click"},
                    "y": {"type": "number", "description": "Y coordinate to click"},
                },
                "required": ["platform", "x", "y"],
            },
        },
        {
            "name": "taey_prepare",
            "description": (
                "Get available options for a platform BEFORE creating a plan.\n\n"
                "Returns models, modes, tools, and sources available for selection.\n"
                "Call this before taey_plan to know what's available."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"platform": {**PLATFORM_PROP, "description": "Which chat platform to get options for"}},
                "required": ["platform"],
            },
        },
        {
            "name": "taey_plan",
            "description": (
                "Create or get an execution plan for a platform action.\n\n"
                "Plans track: required state (mode/model), attachments, message, execution steps.\n\n"
                "Step order for send_message:\n"
                "1. Mode/Model - switch if needed\n"
                "2. Attachments - add files if any\n"
                "3. Type message\n"
                "4. Send"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": PLATFORM_PROP,
                    "action": {
                        "type": "string",
                        "enum": ["send_message", "extract_response", "get", "update"],
                        "description": "Action to perform",
                    },
                    "params": {
                        "type": "object",
                        "description": "Action parameters",
                        "properties": {
                            "plan_id": {"type": "string"},
                            "message": {"type": "string"},
                            "mode": {"type": "string"},
                            "model": {"type": "string"},
                            "attachments": {"type": "array", "items": {"type": "string"}},
                            "current_state": {"type": "object"},
                            "steps": {"type": "array"},
                            "status": {"type": "string"},
                        },
                    },
                },
                "required": ["platform", "action"],
            },
        },
        {
            "name": "taey_send_message",
            "description": (
                "Send a message with full workflow: type, store in Neo4j, send, spawn monitor.\n\n"
                "IMPORTANT: Requires taey_inspect first to identify input/send coordinates.\n"
                "Claude must click the input field via taey_click BEFORE calling this.\n"
                "send_message pastes into whatever is focused, presses Enter, records, spawns daemon.\n\n"
                "The background monitor daemon will detect response completion and send\n"
                "a notification via Redis (injected into future tool responses)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": PLATFORM_PROP,
                    "message": {"type": "string", "description": "The message text to send"},
                    "attachments": {"type": "array", "items": {"type": "string"}, "description": "File paths attached (for Neo4j record)"},
                    "session_type": {"type": "string", "description": "Type of session (research, collaboration, development, testing)"},
                    "purpose": {"type": "string", "description": "What this session is for"},
                },
                "required": ["platform", "message"],
            },
        },
        {
            "name": "taey_quick_extract",
            "description": (
                "Extract the latest AI response via clipboard.\n\n"
                "Clicks the newest Copy button (highest Y), reads clipboard, returns text.\n"
                "If complete=True, consumes the plan (marks interaction done)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": {**PLATFORM_PROP, "description": "Which chat platform to extract from"},
                    "complete": {"type": "boolean", "description": "Whether this completes the interaction (consumes plan)"},
                },
                "required": ["platform"],
            },
        },
        {
            "name": "taey_extract_history",
            "description": (
                "Extract FULL conversation history from a chat platform.\n\n"
                "Scrolls through the conversation, clicking all Copy buttons chronologically.\n"
                "Returns all extracted messages."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": {**PLATFORM_PROP, "description": "Which chat platform to extract from"},
                    "max_messages": {"type": "integer", "description": "Maximum messages to extract (default 500)"},
                },
                "required": ["platform"],
            },
        },
        {
            "name": "taey_attach",
            "description": (
                "Attach a file to the chat input - multi-step with Claude in the loop.\n\n"
                "Flow:\n"
                "1. Clicks attach button via AT-SPI tree search\n"
                "2. If file dialog opened -> handles file selection automatically\n"
                "3. If dropdown appeared -> returns dropdown items for Claude to decide\n\n"
                "When dropdown returned, use taey_click to select the upload option,\n"
                "then call taey_attach again to complete the file selection."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": PLATFORM_PROP,
                    "file_path": {"type": "string", "description": "Absolute path to file to attach"},
                },
                "required": ["platform", "file_path"],
            },
        },
        {
            "name": "taey_select_dropdown",
            "description": (
                "Select an item from a dropdown menu (model, mode, etc.).\n\n"
                "Full workflow: click trigger -> find option -> click it -> validate."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": PLATFORM_PROP,
                    "dropdown": {"type": "string", "description": "Which dropdown to open (model, mode, thinking, etc.)"},
                    "target_value": {"type": "string", "description": "Value to select"},
                },
                "required": ["platform", "dropdown", "target_value"],
            },
        },
        {
            "name": "taey_list_sessions",
            "description": (
                "Show active sessions, pending responses, and recommendations.\n\n"
                "Returns sessions from Neo4j, pending responses from Redis monitors,\n"
                "and a recommendation for what to do next."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"platform": {**PLATFORM_PROP, "description": "Optional filter by platform"}},
                "required": [],
            },
        },
        {
            "name": "taey_monitors",
            "description": (
                "List or kill background monitor daemons.\n\n"
                "action='list': Show all active monitors with platform, ID, status, elapsed time.\n"
                "action='kill': EMERGENCY STOP — kill all daemons, clear all Redis monitor entries."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "kill"],
                        "description": "list: show monitors | kill: stop all monitors",
                    },
                },
                "required": ["action"],
            },
        },
        {
            "name": "taey_respawn_monitor",
            "description": (
                "Spawn a fresh monitor daemon for multi-step response flows.\n\n"
                "Use after clicking 'Start research' (Gemini), 'Continue' (Claude),\n"
                "or 'Show more' (ChatGPT) to monitor the next generation cycle.\n\n"
                "Reuses the existing session/message from pending_prompt."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": PLATFORM_PROP,
                },
                "required": ["platform"],
            },
        },
    ]


# =========================================================================
# Tool routing
# =========================================================================

def handle_tool(name: str, args: Dict, redis_client) -> Dict:
    """Route tool call to handler, inject notifications."""

    result = _route_tool(name, args, redis_client)
    return inject_notifications(result, redis_client)


def _route_tool(name: str, args: Dict, redis_client) -> Dict:
    """Dispatch tool call to the appropriate handler."""

    if name == "taey_inspect":
        platform = args.get("platform")
        if not platform:
            return {"error": "platform is required"}
        scroll = args.get("scroll", "bottom")
        return handle_inspect(platform, redis_client, scroll=scroll)

    if name == "taey_click":
        platform = args.get("platform")
        x = args.get("x")
        y = args.get("y")
        if not platform:
            return {"error": "platform is required"}
        if x is None or y is None:
            return {"error": "x and y are required"}
        return handle_click(platform, x, y)

    if name == "taey_prepare":
        platform = args.get("platform")
        if not platform:
            return {"error": "platform is required"}
        return handle_prepare(platform, redis_client)

    if name == "taey_plan":
        platform = args.get("platform")
        action = args.get("action")
        params = args.get("params", {})
        if not platform:
            return {"error": "platform is required"}
        if not action:
            return {"error": "action is required"}
        return handle_plan(platform, action, params, redis_client)

    if name == "taey_send_message":
        platform = args.get("platform")
        message = args.get("message")
        if not platform:
            return {"error": "platform is required"}
        if not message:
            return {"error": "message is required"}
        return handle_send_message(
            platform=platform,
            message=message,
            redis_client=redis_client,
            display=DISPLAY,
            attachments=args.get("attachments"),
            session_type=args.get("session_type"),
            purpose=args.get("purpose"),
        )

    if name == "taey_quick_extract":
        platform = args.get("platform")
        if not platform:
            return {"error": "platform is required"}
        return handle_quick_extract(
            platform=platform,
            redis_client=redis_client,
            neo4j_mod=neo4j_client,
            complete=args.get("complete", False),
        )

    if name == "taey_extract_history":
        platform = args.get("platform")
        if not platform:
            return {"error": "platform is required"}
        return handle_extract_history(
            platform=platform,
            redis_client=redis_client,
            max_messages=args.get("max_messages", 500),
        )

    if name == "taey_attach":
        platform = args.get("platform")
        file_path = args.get("file_path")
        if not platform:
            return {"error": "platform is required"}
        if not file_path:
            return {"error": "file_path is required"}
        return handle_attach(platform, file_path, redis_client)

    if name == "taey_select_dropdown":
        platform = args.get("platform")
        dropdown = args.get("dropdown")
        target_value = args.get("target_value")
        if not platform:
            return {"error": "platform is required"}
        if not dropdown:
            return {"error": "dropdown is required"}
        if not target_value:
            return {"error": "target_value is required"}
        return handle_select_dropdown(platform, dropdown, target_value, redis_client)

    if name == "taey_list_sessions":
        return handle_list_sessions(args.get("platform"), redis_client)

    if name == "taey_monitors":
        action = args.get("action")
        if not action:
            return {"error": "action is required"}
        return handle_monitors(action, redis_client)

    if name == "taey_respawn_monitor":
        platform = args.get("platform")
        if not platform:
            return {"error": "platform is required"}
        return handle_respawn_monitor(platform, redis_client, DISPLAY)

    return {"error": f"Unknown tool: {name}"}


# =========================================================================
# MCP Server (JSON-RPC over stdio)
# =========================================================================

def run_server():
    """Run the MCP server over stdio."""
    try:
        redis_client = get_redis()
    except Exception as e:
        logger.warning("Redis unavailable at startup: %s. Running without Redis.", e)
        redis_client = None

    def read_message():
        """Read a JSON-RPC message from stdin."""
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())

    def write_message(msg):
        """Write a JSON-RPC message to stdout."""
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
                write_message({
                    "jsonrpc": "2.0",
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "taeys-hands", "version": "5.0.0"},
                        "capabilities": {"tools": {}},
                    },
                    "id": msg_id,
                })

            elif method == 'tools/list':
                write_message({
                    "jsonrpc": "2.0",
                    "result": {"tools": get_tools()},
                    "id": msg_id,
                })

            elif method == 'tools/call':
                tool_name = params.get('name')
                tool_args = params.get('arguments', {})
                result = handle_tool(tool_name, tool_args, redis_client)
                is_error = isinstance(result, dict) and result.get('error') is not None
                write_message({
                    "jsonrpc": "2.0",
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": json.dumps(result, indent=2, cls=SafeJSONEncoder),
                        }],
                        "isError": is_error,
                    },
                    "id": msg_id,
                })

            elif method == 'notifications/initialized':
                pass

            else:
                write_message({
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                    "id": msg_id,
                })

        except json.JSONDecodeError as e:
            write_message({
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": f"Parse error: {e}"},
                "id": None,
            })
        except Exception as e:
            logger.error("Internal error: %s", traceback.format_exc())
            write_message({
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": f"Internal error: {e}"},
                "id": None,
            })


if __name__ == '__main__':
    run_server()
