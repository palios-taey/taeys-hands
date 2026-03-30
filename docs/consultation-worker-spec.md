# Consultation Worker Architecture Spec

**Author**: Perplexity Computer (for Jesse / palios-taey)
**Date**: 2026-03-30
**Status**: DRAFT — Awaiting review
**Repo**: palios-taey/taeys-hands
**Related Issues**: #32 (closed), #33 (open), #34 (closed/dup)

---

## Problem Statement

Taey's Hands runs a **single MCP server process** on Mira serving **5 virtual displays** (`:2`–`:6`), one per platform. Each display has its own:
- Xvfb at 1920×1080
- openbox window manager
- `dbus-run-session` with isolated `at-spi-bus-launcher`
- Firefox with `GTK_USE_PORTAL=0`
- AT-SPI bus address at `/tmp/a11y_bus_:N`, PID at `/tmp/firefox_pid_:N`

The MCP server process lives on its **own** D-Bus session bus (whichever `DISPLAY` it inherited at startup). When a tool like `taey_attach` needs to interact with a platform on `:4`, it cannot directly call AT-SPI — the live objects are on `:4`'s bus, not the server's bus.

The current mitigation uses `_RemoteFirefox`/`_RemoteDocument` sentinel objects and routes some operations through `subprocess_scan()` (spawning `_atspi_subprocess.py` with the correct `DISPLAY` + `AT_SPI_BUS_ADDRESS`). But this was bolted on incrementally:

- **`taey_inspect`**: Fully converted — subprocess scan with YAML filtering. Works.
- **`_wait_for_chip()`**: Converted — uses `_scan_elements_for_platform()`. Works.
- **`_verify_attach_success()`**: Converted. Works.
- **`_scan_menu_items_for_platform()`**: Converted. Works.
- **`_find_attach_button()` / `_get_attach_button_coords()`**: **BROKEN** — checks `is_defunct(e)` which requires live `atspi_obj`. Subprocess scan results are serialized dicts with no `atspi_obj`. Every button is skipped. (Issue #33)
- **`_click_upload_item()`**: Partially broken — tries `atspi_obj.get_action_iface()` first, falls back to coordinates. On multi-display, `atspi_obj` is always `None` so coordinate fallback works, but only if the item was found (depends on the menu scan fix above).
- **`handle_send_message()`**: Uses `find_elements(doc)` and `atspi_obj.get_component_iface().grab_focus()` — both are direct AT-SPI calls that fail on `_RemoteDocument`.
- **`handle_quick_extract()`**: Direct AT-SPI scan, direct `atspi_click()` on copy buttons. Completely broken on multi-display.

**Meanwhile, Thor's `hmm_bot.py` runs at 100% reliability** because each bot process has `DISPLAY` and `DBUS_SESSION_BUS_ADDRESS` set in its environment. Every AT-SPI call is a direct call on the correct bus. No sentinels, no serialization.

The fundamental issue: every new AT-SPI operation requires remembering to check `_remote` and route through subprocess. This will keep generating bugs.

---

## Proposed Architecture: Per-Display Persistent Workers

### Overview

Replace the single-process multi-display proxy with **5 persistent worker processes**, one per platform/display. The MCP server becomes a **dispatcher** that routes tool calls to the correct worker via a simple IPC mechanism.

```
┌──────────────────────────────────────────────────────────┐
│                    MCP Server (server.py)                 │
│                                                          │
│  JSON-RPC/stdio ←→ Claude Code                           │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │              Tool Dispatcher                      │    │
│  │                                                   │    │
│  │  taey_inspect(platform="gemini")                  │    │
│  │    → route to worker[:4]                          │    │
│  │                                                   │    │
│  │  taey_attach(platform="claude", file="...")       │    │
│  │    → route to worker[:3]                          │    │
│  │                                                   │    │
│  │  taey_send_message(platform="chatgpt", msg="...") │    │
│  │    → route to worker[:2]                          │    │
│  └──────┬───────┬───────┬───────┬───────┬────────────┘    │
│         │       │       │       │       │                 │
└─────────┼───────┼───────┼───────┼───────┼─────────────────┘
          │       │       │       │       │
    ┌─────▼─┐ ┌───▼──┐ ┌──▼───┐ ┌─▼───┐ ┌▼──────────┐
    │Worker │ │Worker│ │Worker│ │Work.│ │Worker    │
    │:2     │ │:3    │ │:4    │ │:5   │ │:6        │
    │chatgpt│ │claude│ │gemini│ │grok │ │perplexity│
    │       │ │      │ │      │ │     │ │          │
    │DISPLAY│ │DISPL.│ │DISPL.│ │DISP.│ │DISPLAY   │
    │=:2    │ │=:3   │ │=:4   │ │=:5  │ │=:6       │
    │       │ │      │ │      │ │     │ │          │
    │Direct │ │Direct│ │Direct│ │Dir. │ │Direct    │
    │AT-SPI │ │AT-SPI│ │AT-SPI│ │ATSP.│ │AT-SPI    │
    └───────┘ └──────┘ └──────┘ └─────┘ └──────────┘
```

### Key Principles

1. **Same code path as Thor** — workers use `hmm_bot`'s proven functions: `get_firefox()`, `get_doc()`, `find_elements()`, `attach_file()`, `send_prompt()`, `extract_response()`, etc.
2. **Workers are persistent** — spawned at MCP server startup, stay alive for the server's lifetime. Hold cached AT-SPI refs across operations (like `hmm_bot._cached_firefox`, `_cached_doc`).
3. **IPC is simple JSON over Unix sockets** — one socket per worker at `/tmp/taey_worker_:N.sock`. Request/response pattern. No complex protocol.
4. **Data pipeline unchanged** — Neo4j, Redis, ISMA ingest all work exactly as they do today. Workers import and call the same storage modules.
5. **MCP tool interface unchanged** — Claude Code still calls `taey_inspect`, `taey_attach`, `taey_send_message`, `taey_quick_extract`. The routing is internal.
6. **Fallback for single-display** — on Thor (no `PLATFORM_DISPLAYS`), the server handles tools directly as it always has. Workers are only spawned on multi-display.

---

## Detailed Design

### 1. Worker Process: `workers/display_worker.py`

Each worker is a standalone Python process that:
- Sets `DISPLAY=:N` and `DBUS_SESSION_BUS_ADDRESS` from `/tmp/a11y_bus_:N` **before** any AT-SPI import
- Imports the same modules as `hmm_bot.py`: `core.atspi`, `core.tree`, `core.input`, `core.clipboard`, `tools.attach`, etc.
- Listens on a Unix socket at `/tmp/taey_worker_:N.sock`
- Accepts JSON command objects, executes them, returns JSON results
- Maintains AT-SPI cache across commands (like `hmm_bot._cached_firefox`, `_cached_doc`)

#### Environment Setup (before any imports)

```python
#!/usr/bin/env python3
"""Per-display consultation worker for multi-display MCP server."""

import os
import sys
import json
import socket
import logging
import signal
import time

# MUST set display before any AT-SPI/GTK imports
def setup_display_env(display: str):
    """Configure env for this display's AT-SPI bus."""
    os.environ['DISPLAY'] = display
    
    bus_file = f'/tmp/a11y_bus_{display}'
    try:
        with open(bus_file) as f:
            bus = f.read().strip()
        if bus:
            os.environ['AT_SPI_BUS_ADDRESS'] = bus
            os.environ['DBUS_SESSION_BUS_ADDRESS'] = bus
    except FileNotFoundError:
        logging.warning(f"No AT-SPI bus file for {display}")
    
    os.environ['GTK_USE_PORTAL'] = '0'

# Parse args and setup BEFORE imports
DISPLAY = sys.argv[1]  # e.g. ":2"
PLATFORM = sys.argv[2]  # e.g. "chatgpt"
setup_display_env(DISPLAY)

# NOW import AT-SPI modules
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

# Add project root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
```

#### Command Handlers

Each MCP tool maps to a worker command:

| MCP Tool | Worker Command | Handler Function |
|---|---|---|
| `taey_inspect` | `{"cmd": "inspect", "scroll": "bottom", "fresh_session": false}` | Reuse `tools/inspect.py` `handle_inspect()` |
| `taey_attach` | `{"cmd": "attach", "file_path": "/tmp/pkg.md"}` | Reuse `tools/attach.py` `handle_attach()` |
| `taey_send_message` | `{"cmd": "send", "message": "...", "attachments": [...]}` | Reuse `tools/send.py` `handle_send_message()` |
| `taey_quick_extract` | `{"cmd": "extract", "complete": false}` | Reuse `tools/extract.py` `handle_quick_extract()` |
| `taey_click` | `{"cmd": "click", "x": 767, "y": 617}` | Reuse `tools/click.py` `handle_click()` |
| `taey_plan` | `{"cmd": "plan", "action": "create", ...}` | Reuse `tools/plan.py` `handle_plan()` |
| `taey_prepare` | `{"cmd": "prepare", "dropdown_name": "model"}` | Reuse `tools/dropdown.py` `handle_prepare()` |
| `taey_select_dropdown` | `{"cmd": "select_dropdown", ...}` | Reuse `tools/dropdown.py` `handle_select_dropdown()` |
| `taey_list_sessions` | `{"cmd": "list_sessions"}` | Reuse `tools/sessions.py` `handle_list_sessions()` |
| `taey_monitors` | `{"cmd": "monitors"}` | Reuse `tools/monitors.py` `handle_monitors()` |

**Critical**: Workers import and call the **existing handler functions directly**. No rewriting. The functions work correctly when running on the right bus — they were only broken because the MCP server was on the wrong bus.

#### Worker Main Loop

```python
SOCKET_PATH = f'/tmp/taey_worker_{DISPLAY}.sock'

def handle_command(cmd_data: dict) -> dict:
    """Route command to the appropriate handler."""
    cmd = cmd_data.get('cmd')
    platform = PLATFORM
    
    # Get shared resources
    redis_client = get_redis()
    
    try:
        if cmd == 'inspect':
            return handle_inspect(
                platform, redis_client,
                scroll=cmd_data.get('scroll', 'bottom'),
                fresh_session=cmd_data.get('fresh_session', False),
            )
        elif cmd == 'attach':
            return handle_attach(
                platform, cmd_data['file_path'], redis_client,
            )
        elif cmd == 'send':
            return handle_send_message(
                platform, cmd_data['message'], redis_client,
                display=DISPLAY,
                attachments=cmd_data.get('attachments'),
                session_type=cmd_data.get('session_type'),
                purpose=cmd_data.get('purpose'),
            )
        elif cmd == 'extract':
            return handle_quick_extract(
                platform, redis_client,
                neo4j_mod=neo4j_client,
                complete=cmd_data.get('complete', False),
            )
        elif cmd == 'click':
            return handle_click(
                platform, cmd_data['x'], cmd_data['y'],
            )
        elif cmd == 'plan':
            return handle_plan(
                platform, redis_client,
                action=cmd_data.get('action', 'get'),
                **{k: v for k, v in cmd_data.items() 
                   if k not in ('cmd', 'action')},
            )
        elif cmd == 'ping':
            return {'status': 'alive', 'platform': platform, 
                    'display': DISPLAY, 'pid': os.getpid()}
        else:
            return {'error': f'Unknown command: {cmd}'}
    except Exception as e:
        logging.error(f"Command {cmd} failed: {e}", exc_info=True)
        return {'error': str(e)}

def run_worker():
    """Main loop: accept connections, handle commands."""
    # Clean up stale socket
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(1)  # Single client (MCP server)
    os.chmod(SOCKET_PATH, 0o600)
    
    logging.info(f"Worker {PLATFORM} on {DISPLAY} listening at {SOCKET_PATH}")
    
    while True:
        conn, _ = server.accept()
        try:
            data = b''
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
                # Simple framing: newline-terminated JSON
                if b'\n' in data:
                    break
            
            if data:
                cmd_data = json.loads(data.decode().strip())
                result = handle_command(cmd_data)
                response = json.dumps(result, cls=SafeJSONEncoder) + '\n'
                conn.sendall(response.encode())
        except Exception as e:
            try:
                conn.sendall(json.dumps({'error': str(e)}).encode() + b'\n')
            except:
                pass
        finally:
            conn.close()
```

### 2. MCP Server Dispatcher: Changes to `server.py`

On startup, if `PLATFORM_DISPLAYS` is configured, the MCP server:
1. Spawns 5 worker processes
2. Waits for each to become ready (socket exists + responds to `ping`)
3. Routes all tool calls to the appropriate worker

#### Worker Lifecycle Management

```python
# In server.py

import subprocess
import socket as _socket

_workers: dict[str, subprocess.Popen] = {}  # platform -> Popen
_WORKER_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'workers', 'display_worker.py'
)

def spawn_workers():
    """Spawn per-display workers for multi-display mode."""
    from core.platforms import _PLATFORM_DISPLAYS, get_platform_bus
    
    if not _PLATFORM_DISPLAYS:
        return  # Single-display mode — no workers needed
    
    for platform, display in _PLATFORM_DISPLAYS.items():
        log_path = f'/tmp/taey_worker_{platform}.log'
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        
        proc = subprocess.Popen(
            [sys.executable, _WORKER_SCRIPT, display, platform],
            stdout=log_fd, stderr=log_fd,
            close_fds=True,
        )
        os.close(log_fd)
        _workers[platform] = proc
        logger.info(f"Spawned worker for {platform} on {display} (PID {proc.pid})")
    
    # Wait for all workers to be ready
    for platform in _PLATFORM_DISPLAYS:
        sock_path = f'/tmp/taey_worker_{_PLATFORM_DISPLAYS[platform]}.sock'
        for attempt in range(30):  # 15 seconds max
            if os.path.exists(sock_path):
                try:
                    result = send_to_worker(platform, {'cmd': 'ping'})
                    if result.get('status') == 'alive':
                        logger.info(f"Worker {platform} ready")
                        break
                except:
                    pass
            time.sleep(0.5)
        else:
            logger.error(f"Worker {platform} failed to start within 15s")


def send_to_worker(platform: str, cmd: dict, timeout: float = 120.0) -> dict:
    """Send command to platform worker, return result."""
    from core.platforms import get_platform_display
    
    display = get_platform_display(platform)
    if not display:
        raise RuntimeError(f"No display configured for {platform}")
    
    sock_path = f'/tmp/taey_worker_{display}.sock'
    
    # Check worker is alive, restart if dead
    if platform in _workers and _workers[platform].poll() is not None:
        logger.warning(f"Worker {platform} died (exit={_workers[platform].returncode}), restarting...")
        _restart_worker(platform)
    
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(sock_path)
        payload = json.dumps(cmd) + '\n'
        sock.sendall(payload.encode())
        
        data = b''
        while b'\n' not in data:
            chunk = sock.recv(1048576)  # 1MB chunks
            if not chunk:
                break
            data += chunk
        
        return json.loads(data.decode().strip())
    finally:
        sock.close()


def _restart_worker(platform: str):
    """Kill and restart a worker."""
    from core.platforms import _PLATFORM_DISPLAYS
    
    display = _PLATFORM_DISPLAYS.get(platform)
    if not display:
        return
    
    # Kill old
    old = _workers.get(platform)
    if old:
        try:
            old.kill()
            old.wait(timeout=5)
        except:
            pass
    
    # Spawn new
    log_path = f'/tmp/taey_worker_{platform}.log'
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    proc = subprocess.Popen(
        [sys.executable, _WORKER_SCRIPT, display, platform],
        stdout=log_fd, stderr=log_fd, close_fds=True,
    )
    os.close(log_fd)
    _workers[platform] = proc
    
    # Wait for ready
    sock_path = f'/tmp/taey_worker_{display}.sock'
    for _ in range(20):
        if os.path.exists(sock_path):
            try:
                result = send_to_worker(platform, {'cmd': 'ping'})
                if result.get('status') == 'alive':
                    break
            except:
                pass
        time.sleep(0.5)
```

#### Tool Dispatch (modified tool handlers in server.py)

```python
def dispatch_tool(tool_name: str, platform: str, params: dict) -> dict:
    """Route tool call to worker (multi-display) or handle locally (single-display)."""
    from core.platforms import is_multi_display, get_platform_display
    
    if is_multi_display() and get_platform_display(platform):
        # Multi-display: route to worker
        cmd = _tool_to_cmd(tool_name, platform, params)
        return send_to_worker(platform, cmd)
    else:
        # Single-display: handle directly (existing behavior)
        return _handle_tool_locally(tool_name, platform, params)


def _tool_to_cmd(tool_name: str, platform: str, params: dict) -> dict:
    """Convert MCP tool call to worker command."""
    cmd_map = {
        'taey_inspect': 'inspect',
        'taey_attach': 'attach',
        'taey_send_message': 'send',
        'taey_quick_extract': 'extract',
        'taey_click': 'click',
        'taey_plan': 'plan',
        'taey_prepare': 'prepare',
        'taey_select_dropdown': 'select_dropdown',
        'taey_list_sessions': 'list_sessions',
        'taey_monitors': 'monitors',
    }
    return {'cmd': cmd_map[tool_name], **params}
```

### 3. Data Pipeline: Neo4j + ISMA

Both prompts and responses MUST be persisted. The pipeline has **three destinations**:

#### 3a. Neo4j Graph Storage (Conversation History)

**Schema** (existing, no changes):
```
(:ChatSession {session_id, platform, url, session_type, purpose, 
               created_at, last_activity, message_count})
  -[:HAS_MESSAGE]->
(:Message {message_id, role, content, attachments, created_at, handled})

(:Message {role:"assistant"})
  -[:RESPONDS_TO]->
(:Message {role:"user"})
```

**Write paths** (both must work identically in workers):

| Event | Writer | Neo4j Call | Redis State |
|---|---|---|---|
| **Send prompt** | `handle_send_message()` | `get_or_create_session(platform, url)` → `add_message(session_id, 'user', message, attachments)` | `pending_prompt:{platform}` — stores `{content, session_id, message_id, sent_at, session_url}` |
| **Extract response** | `handle_quick_extract()` | `get_or_create_session(platform, url)` (fallback if pending_prompt expired) → `add_message(session_id, 'assistant', content)` → `_link_response(response_id, user_message_id)` — creates `RESPONDS_TO` edge | Reads `pending_prompt:{platform}` for `session_id` + `message_id` linkage |

**Worker requirement**: Workers import `storage.neo4j_client` and `storage.redis_pool` directly. Since Neo4j uses `bolt://localhost:7687` and Redis uses `127.0.0.1:6379`, both are accessible from worker processes. The `node_key()` function scopes keys by `DISPLAY` (e.g., `taey:taeys-hands-d2:pending_prompt:chatgpt`), which is correct — each worker on its own display gets its own key namespace.

**IMPORTANT**: The `NODE_ID` for each worker will be auto-detected as `taeys-hands-d{N}` (from `_detect_node_id()` in `redis_pool.py`). This means Redis keys are automatically scoped per-display. **No changes needed to Redis key logic.**

#### 3b. ISMA Tile Ingestion (Semantic Search)

**Two ingest paths exist** — both should be used:

**Path 1: Direct ISMA API** (via `core/ingest.py` → `auto_ingest()`)
- Called by `handle_quick_extract()` after every successful extraction
- POSTs to `ISMA_API_URL/ingest/session` (embedding-server `query_api.py`)
- Generates Qwen3-Embedding-8B vector, stores in Weaviate as `ISMA_Quantum` tile
- Env vars: `ISMA_API_URL`, `ISMA_API_KEY`

**Path 2: Orchestrator transcript ingest** (via `core/orchestrator.py` → `ingest_transcript()`)
- Called by `hmm_bot.py` in the HMM enrichment pipeline
- POSTs to `ORCH_URL/api/ingest/transcript` (the-conductor `gateway/api.py`)
- Writes JSON to disk, triggers async `process_transcripts.py`
- Includes full exchange (prompt + response) in structured format

**For consultation workers, BOTH paths should fire:**
1. `auto_ingest()` fires automatically in `handle_quick_extract()` — already wired, no changes needed
2. `ingest_transcript()` should fire after extract with the full exchange (prompt from `pending_prompt` Redis key + response from extraction). This needs to be added.

#### 3c. Corpus File Storage (Backup/Audit Trail)

`auto_ingest()` → `save_to_corpus()` already saves to `{TAEY_CORPUS_PATH}/extracts/{platform}/{timestamp}.md`. No changes needed.

### 4. Data Pipeline Wiring

The storage layer is already built:
- **Neo4j**: Prompts stored via `handle_send_message()` → `add_message(session_id, 'user', message, attachments)`. Responses stored via `handle_quick_extract()` → `add_message(session_id, 'assistant', content)`. Linkage via `RESPONDS_TO` edge.
- **ISMA**: Response extraction → `auto_ingest()` → corpus file + ISMA `/ingest/session` tile.
- **Redis**: `pending_prompt:{platform}` bridges send→extract with session_id/message_id for linkage.

**What needs wiring** (existing code, just not connected in the MCP tool path):

1. `ingest_transcript()` (in `core/orchestrator.py`) handles full prompt+response exchange ingestion via the-conductor. Currently only called from `unified_bot.py`. Needs to be called from `handle_quick_extract()` after successful extraction.

2. `auto_ingest()` for prompts — currently only responses get ISMA tiles. Prompts should too.

**Fix for extract path** — add to `handle_quick_extract()` after Neo4j storage:

```python
# Wire full exchange to orchestrator transcript ingest
try:
    from core.orchestrator import ingest_transcript
    prompt_content = ''
    if redis_client:
        pending_json = redis_client.get(node_key(f"pending_prompt:{platform}"))
        if pending_json:
            prompt_content = json.loads(pending_json).get('content', '')
    
    ingest_transcript(
        platform=platform,
        response_content=content,
        package_metadata={
            'batch_id': 'consultation',
            'tile_hash': neo4j_stored.get('response_id', 'unknown') if neo4j_stored else 'unknown',
            'model': platform,
        },
        prompt_content=prompt_content,
    )
except Exception as e:
    logger.warning("Transcript ingest failed: %s", e)
```

**Fix for send path** — add to `handle_send_message()` after Neo4j storage:

```python
# Ingest prompt to ISMA as a searchable tile
try:
    from core.ingest import auto_ingest
    auto_ingest(
        platform, message, url=url,
        session_id=session_id,
        metadata={
            "role": "user",
            "source_type": "consultation_prompt",
            "attachments": json.dumps(attachments or []),
        }
    )
except Exception as e:
    logger.warning("Prompt auto-ingest failed: %s", e)
```

### 5. Monitor Integration

The central monitor (`monitor/central.py`) polls Redis for active sessions and detects response completion via stop-button presence/absence. 

**No changes needed.** The monitor is already a separate process with its own `DISPLAY` env. It reads session data from Redis (which workers write to). The `register_monitor_session()` call in `handle_send_message()` creates the same Redis keys.

**One consideration**: The monitor currently does AT-SPI polling on its own display. For multi-display, the monitor needs to poll each platform's display. The existing monitor already handles this via its session registry — it reads `DISPLAY` from the session data and spawns subprocess scans.

If the monitor doesn't yet support multi-display polling (needs verification), it should be extended to use the same `subprocess_scan()` mechanism. But this is separate from the worker architecture.

### 6. Full-Cycle Mode (Bonus: `consultation.py`)

In addition to the MCP tool-by-tool interface, provide a `consultation.py` script for **full unattended cycles** (like `hmm_bot.process_platform()`):

```
python3 scripts/consultation.py \
    --platform gemini \
    --file /tmp/package.md \
    --message "Analyze the attached file" \
    --model "2.5 Pro" \
    --mode "Deep Research"
```

This would:
1. Set up display env (like worker)
2. Navigate to fresh session
3. Select model/mode if specified
4. Attach file
5. Send message
6. Wait for response (stop-button polling)
7. Extract response
8. Store in Neo4j (prompt + response)
9. Ingest to ISMA (prompt tile + response tile + full transcript)
10. Print result JSON to stdout

**Implementation**: A thin wrapper around the worker's command handlers, called sequentially. OR, reuse `hmm_bot.process_platform()` with a configurable prompt (instead of the HMM-specific prompt).

---

## File Changes Summary

### New Files

| File | Purpose |
|---|---|
| `workers/__init__.py` | Package marker |
| `workers/display_worker.py` | Per-display persistent worker process |
| `scripts/consultation.py` | Full-cycle consultation script (optional, for non-MCP use) |

### Modified Files

| File | Changes |
|---|---|
| `server.py` | Add worker spawning at startup, add `dispatch_tool()` routing, modify each tool handler to call `dispatch_tool()` on multi-display |
| `tools/send.py` | Add `auto_ingest()` call for prompt persistence in ISMA |
| `tools/extract.py` | Add `ingest_transcript()` call for full exchange persistence |
| `core/platforms.py` | No changes needed — `_PLATFORM_DISPLAYS` already works |
| `core/atspi.py` | No changes needed on multi-display path (workers bypass it entirely) |

### Unchanged Files (used by workers via import)

All existing tool handlers, core modules, storage backends, platform YAMLs — workers import and call them directly. The handlers work correctly when running on the correct bus.

---

## Redis Key Map (Reference)

All keys are scoped by `node_key()` → `taey:{NODE_ID}:{suffix}`

| Key | Writer | Reader | TTL | Purpose |
|---|---|---|---|---|
| `plan:current:{platform}` | `handle_plan` | `handle_send_message`, `handle_inspect` | Configured (default 300s) | Active plan ID |
| `plan:{plan_id}` | `handle_plan` | All tools | Configured (default 600s) | Plan data JSON |
| `pending_prompt:{platform}` | `handle_send_message` | `handle_quick_extract` | 3600s | Prompt content + session/message IDs for Neo4j linkage |
| `checkpoint:{platform}:inspect` | `handle_inspect` | `validate_send` hook | 1800s | Last inspect state |
| `checkpoint:{platform}:attach` | `handle_attach` | `validate_send` hook | 1800s | Attach confirmation |
| `active_session:{monitor_id}` | `handle_send_message` | `monitor/central.py` | Variable (default 7200s) | Monitor session for stop-button polling |
| `active_session_ids` (SET) | `handle_send_message` | `monitor/central.py` | None | Index of active session keys |
| `inspect:{platform}` | `handle_inspect` | Various | None | Last inspect result |
| `attach:pending:{platform}` | `handle_attach` | `handle_attach` | 120s | In-progress attach (dropdown opened, waiting for dialog) |
| `dropdown_baseline:{platform}:{name}` | `handle_prepare` | `handle_select_dropdown` | None | Dropdown item baseline for change detection |
| `notifications` (LIST) | `monitor/central.py` | `server.py` | None | Pending notifications queue |
| `plan_active:{DISPLAY}` (NOTE: not node-scoped) | `handle_plan`, `handle_send_message` | `handle_plan` | Variable | Display-level plan lock |
| `response_reviewed:{platform}` | Claude hook | `handle_quick_extract` | None | Flag for response review state |

**Worker scoping**: Each worker on display `:N` gets `NODE_ID = taeys-hands-dN`, so all keys are naturally isolated. Worker on `:2` writes `taey:taeys-hands-d2:pending_prompt:chatgpt`. The monitor reads these keys by scanning for `taey:*:active_session:*`.

---

## Migration Plan

### Phase 1: Worker Infrastructure (no behavior changes)

1. Create `workers/display_worker.py` with Unix socket server
2. Add `spawn_workers()` to `server.py` startup
3. Add `send_to_worker()` IPC function
4. Add `dispatch_tool()` routing with multi-display check
5. Test: verify `taey_inspect` returns identical results via worker vs. direct

### Phase 2: Route All Tools Through Workers

6. Route `taey_inspect` through worker on multi-display
7. Route `taey_attach` through worker — this fixes #33 immediately
8. Route `taey_send_message` through worker
9. Route `taey_quick_extract` through worker
10. Route remaining tools (`taey_click`, `taey_plan`, `taey_prepare`, `taey_select_dropdown`)
11. Test: full consultation cycle on Mira (plan → inspect → attach → send → extract)

### Phase 3: Data Pipeline Wiring

12. Wire `ingest_transcript()` into `handle_quick_extract()` — full exchange (prompt+response) to orchestrator
13. Wire `auto_ingest()` for prompts into `handle_send_message()` — prompt tiles in ISMA
14. Test: verify Neo4j has both user + assistant messages with RESPONDS_TO edges (should already work)
15. Test: verify ISMA has prompt tiles, response tiles, and transcript records via orchestrator

### Phase 4: Monitor + Cleanup

16. Add `check_stop` command to display workers
17. Refactor `central.py` to poll workers instead of direct AT-SPI
18. Remove `_RemoteFirefox` / `_RemoteDocument` sentinel classes (no longer needed — workers use direct AT-SPI)
19. Remove `subprocess_scan()` infrastructure (workers don't need it)
20. Remove `_scan_elements_for_platform()` / `_scan_menu_items_for_platform()` remote paths
21. Close issue #33
22. Build `scripts/consultation.py` for full-cycle non-MCP use

---

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Worker crash takes down one platform | Auto-restart in `send_to_worker()` — detect dead process, respawn, retry |
| Unix socket connection refused | Retry with backoff (3 attempts, 1s between). Fall back to direct single-display handling if worker unreachable |
| Worker memory leak (AT-SPI cache grows) | Add periodic cache invalidation (every N commands or on explicit `refresh` command) |
| Neo4j/Redis connection in workers | Workers share the same connection pool config. Neo4j driver is lazy-init per-process. Redis pool is per-process. Both are lightweight |
| Race condition: two MCP sessions sending to same platform | Workers are single-threaded (one connection at a time on Unix socket). Commands are serialized per-platform. This is actually safer than the current model |
| Display env changes (bus address rotates) | Worker reads bus file at startup. If bus changes (rare — only on display restart), worker must be restarted. MCP server can detect stale bus via `ping` failure |

---

## Decisions (Resolved)

1. **Worker startup**: **Eager**. All 5 workers spawn at MCP server startup. AI-native, AI-first, AI-speed — no lazy initialization.

2. **Full-cycle `consultation.py`**: **Yes, build it**. Both the MCP tool-by-tool interface AND the standalone full-cycle script. Same principle — AI-speed means having every path available.

3. **Monitor multi-display**: **Needs the same worker treatment.** See new section below.

4. **Data pipeline**: **Already built.** The plan, attachments (file paths), and prompt are all stored in Neo4j via `handle_send_message()` → `add_message(session_id, 'user', message, attachments)`. Responses are extracted and stored via `handle_quick_extract()` → `add_message(session_id, 'assistant', content)` + `RESPONDS_TO` edge. ISMA ingest of responses goes through `auto_ingest()` in `core/ingest.py`. Full exchange ingest (prompt + response together) goes through `ingest_transcript()` in `core/orchestrator.py` — currently only wired in `unified_bot.py`, needs to be wired into the MCP extract path too.

5. **Orchestrator integration**: **Not now.** Workers report to `-t taeys-hands` (tmux target), not the orchestrator API. Orchestrator integration is for later.

6. **Concurrency model**: **Single-threaded per worker is fine for now.**

---

## CRITICAL: Monitor Needs Worker Treatment Too

The central monitor (`monitor/central.py`) is **broken on multi-display Mira**. Evidence from the code:

- Line 50: `DISPLAY = detect_display()` — picks up whatever display it inherited at spawn time
- Line 58: `from core.atspi import find_firefox, get_platform_document` — direct AT-SPI imports
- Line 528: `firefox = find_firefox()` — scans its OWN bus, not the platform's bus
- Line 555: `doc = get_platform_document(firefox, platform)` — direct AT-SPI call
- Line 400: `self._scan_for_stop_button(doc, platform)` — direct AT-SPI tree walk

On multi-display Mira, the monitor runs on the MCP server's display (e.g. `:0` or whatever `_ensure_central_monitor()` passes). It calls `find_firefox()` on that bus → sees nothing (Firefox instances are on `:2`–`:6`). Stop-button detection is completely blind.

**Fix options:**

**Option A: One monitor worker per display** — each worker already has the correct bus. Add a `monitor` command to the worker protocol. The MCP server spawns a monitoring loop per worker that periodically sends `{"cmd": "check_stop_button"}`. This is cleanest — reuses the worker infrastructure.

**Option B: Monitor uses subprocess scanning** — like `_atspi_subprocess.py` but for stop-button detection. Add a `stop_scan` command to the subprocess scanner. Monitor spawns it with the correct `DISPLAY`/`AT_SPI_BUS_ADDRESS` per platform.

**Option C: One monitor process per display** — spawn 5 independent `central.py` instances, each with the correct `DISPLAY` env and `--single-display` flag. Simplest but most resource-heavy.

**Recommendation: Option A** — the worker already exists, already has the right bus, already imports the right modules. Adding stop-button polling is trivial.

### Monitor Worker Command

```python
# In display_worker.py, add to handle_command():
elif cmd == 'check_stop':
    firefox = atspi.find_firefox_for_platform(PLATFORM)
    if not firefox:
        return {'stop_found': False, 'error': 'Firefox not found'}
    doc = atspi.get_platform_document(firefox, PLATFORM)
    if not doc:
        return {'stop_found': False, 'error': 'Document not found'}
    # Reuse the monitor's stop-button scan logic
    from monitor.central import CentralMonitor
    monitor = CentralMonitor.__new__(CentralMonitor)
    monitor.stop_patterns = _load_stop_patterns()
    stop_found = monitor._scan_for_stop_button(doc, PLATFORM)
    return {'stop_found': stop_found, 'platform': PLATFORM}
```

Then the central monitor becomes a thin loop that polls each worker for stop-button state, instead of scanning AT-SPI directly.

---

## Data Pipeline Correction

The original spec incorrectly stated that prompts weren't being stored in Neo4j. They are. The actual data flow:

### What's Already Built and Working

| Data | Storage | Code Path | Status |
|---|---|---|---|
| Prompt text | Neo4j `Message(role='user')` | `send.py` → `neo4j_client.add_message()` | **Working** |
| Attachment file paths | Neo4j `Message.attachments` | `send.py` → `neo4j_client.add_message(attachments=[...])` | **Working** |
| Plan (model, mode, tools, attachments) | Redis (TTL) | `plan.py` → `redis_client.setex(plan:{id})` | **Working** |
| Response text | Neo4j `Message(role='assistant')` | `extract.py` → `neo4j_client.add_message()` | **Working** |
| Prompt→Response linkage | Neo4j `RESPONDS_TO` edge | `extract.py` → `_link_response()` | **Working** |
| Response → ISMA tile | Weaviate `ISMA_Quantum` | `extract.py` → `auto_ingest()` → ISMA `/ingest/session` | **Working** |
| Response → corpus file | Filesystem | `extract.py` → `auto_ingest()` → `save_to_corpus()` | **Working** |
| Session ID → Redis | Redis (TTL 3600s) | `send.py` → `pending_prompt:{platform}` | **Working** |

### What's Missing (Needs Wiring)

| Data | Storage | Code Path | Status |
|---|---|---|---|
| Full exchange (prompt+response) → orchestrator | the-conductor `/api/ingest/transcript` | `orchestrator.ingest_transcript()` | **Built but only called from `unified_bot.py`** — needs to be wired into `handle_quick_extract()` |
| Prompt → ISMA tile | Weaviate `ISMA_Quantum` | `auto_ingest()` | **Not called for prompts** — only responses go to ISMA currently |

**Fix**: After extraction succeeds in `handle_quick_extract()`, call `ingest_transcript()` with both prompt (from `pending_prompt` Redis key) and response. This feeds the full exchange to the orchestrator pipeline which already handles it correctly.
