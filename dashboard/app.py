"""
The Conductor's Console — FastAPI Backend

Real-time orchestration dashboard with WebSocket streaming.
Routes tasks to agents via LVP scoring and delivers via tmux injection.
"""

import asyncio
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Orchestration imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestration.config import OrchConfig, get_redis_sync, get_redis_async, get_neo4j_driver
from orchestration.registry import AgentRegistry, AgentInfo, AgentStatus, AGENT_PROFILES
from orchestration.task_queue import TaskQueue, TaskMessage
from orchestration.task_router import rank_agents_for_task, select_best_agent
from orchestration.events import EventLog, Event, EventType, emit
from orchestration.heartbeat import HeartbeatMonitor, HeartbeatBroadcaster
from orchestration.cli_adapter import CLIAdapter

# --- Config ---
config = OrchConfig()
STATIC_DIR = Path(__file__).parent / "static"

# --- WebSocket connection manager ---
class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, message: dict):
        dead = set()
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        self.active -= dead

manager = ConnectionManager()

# --- Background tasks ---
async def heartbeat_monitor_loop():
    """Check agent liveness every 12s, push changes to WebSocket."""
    monitor = HeartbeatMonitor(config)
    agent_ids = list(AGENT_PROFILES.keys())
    prev_status = {}

    while True:
        try:
            status = monitor.check_all(agent_ids)
            # Detect changes
            for aid, alive in status.items():
                if aid in prev_status and prev_status[aid] != alive:
                    await manager.broadcast({
                        "type": "agent_status",
                        "data": {
                            "agent_id": aid,
                            "alive": alive,
                            "changed_at": time.time(),
                        }
                    })
            prev_status = status
        except Exception:
            pass
        await asyncio.sleep(12)


async def event_stream_loop():
    """Tail the event stream, push new events to WebSocket."""
    r = get_redis_async(config)
    last_id = "$"  # Only new events

    while True:
        try:
            result = await r.xread(
                streams={config.event_stream: last_id},
                count=10,
                block=5000,
            )
            if result:
                for stream_name, messages in result:
                    for msg_id, fields in messages:
                        last_id = msg_id
                        await manager.broadcast({
                            "type": "event",
                            "data": {
                                "id": msg_id,
                                "event_type": fields.get("event_type", ""),
                                "actor": fields.get("actor", ""),
                                "payload": json.loads(fields.get("payload", "{}")),
                                "timestamp": fields.get("timestamp", ""),
                                "event_hash": fields.get("event_hash", ""),
                            }
                        })
        except Exception:
            await asyncio.sleep(2)


async def pulse_updater_loop():
    """Query system-wide stats every 30s, push to WebSocket."""
    while True:
        try:
            pulse = _get_pulse_sync()
            await manager.broadcast({"type": "pulse", "data": pulse})
        except Exception:
            pass
        await asyncio.sleep(30)


# --- Shared instances ---
cli_adapter = CLIAdapter()
conductor_heartbeat = HeartbeatBroadcaster("claude-taeys-hands", config)


# --- App lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background tasks
    tasks = [
        asyncio.create_task(heartbeat_monitor_loop()),
        asyncio.create_task(event_stream_loop()),
        asyncio.create_task(pulse_updater_loop()),
        asyncio.create_task(conductor_heartbeat.run()),  # Beat my heart
    ]

    # Emit boot event
    emit(EventType.AGENT_STARTED.value, {"agent": "claude-taeys-hands", "source": "dashboard"}, actor="conductor")

    yield
    conductor_heartbeat.stop()
    for t in tasks:
        t.cancel()


app = FastAPI(title="The Conductor's Console", lifespan=lifespan)


# --- Helper functions ---

def _get_agents_data() -> List[Dict[str, Any]]:
    """Get all agents with liveness status."""
    registry = AgentRegistry(config)
    monitor = HeartbeatMonitor(config)
    agents = registry.get_all()

    result = []
    for agent in agents:
        alive = monitor.is_alive(agent.agent_id)
        activity = monitor.get_activity(agent.agent_id)
        result.append({
            "agent_id": agent.agent_id,
            "name": agent.name,
            "cli_type": agent.cli_type,
            "machine": agent.machine,
            "role": agent.role.value,
            "status": agent.status.value,
            "current_load": agent.current_load,
            "current_task": agent.current_task,
            "context_window": agent.context_window,
            "capabilities": agent.capabilities.to_vector(),
            "alive": alive,
            "activity": activity,
        })

    # Sort: coordinator first, then by name
    role_order = {"coordinator": 0, "worker": 1, "shared": 2, "remote": 3}
    result.sort(key=lambda a: (role_order.get(a["role"], 9), a["name"]))
    return result


def _get_events_data(count: int = 50) -> List[Dict[str, Any]]:
    """Get recent events."""
    log = EventLog(config)
    events = log.read_recent(count=count)
    return [
        {
            "event_type": e.event_type,
            "actor": e.actor,
            "payload": e.payload,
            "timestamp": e.timestamp,
            "event_hash": e.event_hash,
        }
        for e in events
    ]


def _get_pulse_sync() -> Dict[str, Any]:
    """Get system-wide health stats."""
    r = get_redis_sync(config)
    pulse = {
        "redis_keys": r.dbsize(),
        "orch_events": 0,
        "orch_tasks": 0,
        "hmm_tiles": 0,
        "platform_sessions": [],
        "neo4j": {},
    }

    # Orchestration stream lengths
    try:
        pulse["orch_events"] = r.xlen(config.event_stream)
    except Exception:
        pass
    try:
        pulse["orch_tasks"] = r.xlen(config.task_stream)
    except Exception:
        pass

    # HMM tile count
    try:
        cursor = 0
        count = 0
        while True:
            cursor, keys = r.scan(cursor, match="hmm:tile:*", count=1000)
            count += len(keys)
            if cursor == 0:
                break
        pulse["hmm_tiles"] = count
    except Exception:
        pass

    # Active platform sessions
    try:
        for k in r.scan_iter("taey:session:*:active", count=100):
            platform = k.split(":")[2] if k.count(":") >= 3 else "unknown"
            pulse["platform_sessions"].append(platform)
    except Exception:
        pass

    # Neo4j counts
    try:
        driver = get_neo4j_driver(config)
        with driver.session(database=config.neo4j_db) as session:
            for label, key in [
                ("ISMAMessage", "messages"),
                ("Exchange", "exchanges"),
                ("ISMASession", "isma_sessions"),
                ("Project", "projects"),
                ("Task", "tasks"),
                ("Conversation", "conversations"),
            ]:
                result = session.run(f"MATCH (n:{label}) RETURN count(n) AS c")
                pulse["neo4j"][key] = result.single()["c"]
        driver.close()
    except Exception as e:
        pulse["neo4j"]["error"] = str(e)[:100]

    pulse["timestamp"] = time.time()
    return pulse


# Keyword → capability tag mapping for command routing
KEYWORD_TAGS = {
    "research": ["research"],
    "find": ["research"],
    "look up": ["research"],
    "search": ["research"],
    "review": ["review", "reasoning"],
    "audit": ["review", "reasoning"],
    "check": ["review"],
    "build": ["codegen", "architecture"],
    "implement": ["codegen", "architecture"],
    "add": ["codegen"],
    "create": ["codegen"],
    "write": ["codegen"],
    "test": ["testing", "codegen"],
    "verify": ["testing"],
    "security": ["security", "privacy"],
    "privacy": ["security", "privacy"],
    "refactor": ["codegen", "architecture", "multi_file"],
    "large": ["large_context"],
    "codebase": ["large_context", "review"],
}


def _extract_capability_tags(text: str) -> List[str]:
    """Extract capability tags from natural language using word boundaries."""
    text_lower = text.lower()
    tags = set()
    for keyword, tag_list in KEYWORD_TAGS.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            tags.update(tag_list)
    return list(tags) if tags else ["reasoning"]  # Default: general reasoning


def _route_command(text: str) -> Dict[str, Any]:
    """Route a command to the best agent via LVP."""
    tags = _extract_capability_tags(text)
    task_id = f"task-{uuid.uuid4().hex[:8]}"

    task = TaskMessage(
        task_id=task_id,
        description=text,
        priority=50,
        capability_tags=tags,
        estimated_tokens=50_000,
    )

    # Score all agents
    registry = AgentRegistry(config)
    agents = registry.get_all()
    ranked = rank_agents_for_task(agents, task)

    if not ranked:
        return {"error": "No agents available for this task"}

    best_agent, best_score = ranked[0]

    # Publish to task stream
    queue = TaskQueue(config)
    stream_id = queue.publish_task(task)

    # Emit event
    emit(
        EventType.TASK_CREATED.value,
        {"task_id": task_id, "description": text, "routed_to": best_agent.agent_id, "score": round(best_score, 3)},
        actor="conductor",
    )

    # Deliver task to agent via tmux injection
    delivered = False
    delivery_msg = f"[TASK {task_id}] {text}"
    if best_agent.role.value in ("worker", "shared"):
        delivered = cli_adapter.send_task(best_agent.agent_id, delivery_msg)
        if delivered:
            emit(
                EventType.TASK_CLAIMED.value,
                {"task_id": task_id, "agent": best_agent.agent_id, "delivery": "tmux"},
                actor=best_agent.agent_id,
            )

    return {
        "task_id": task_id,
        "description": text,
        "capability_tags": tags,
        "routed_to": {
            "agent_id": best_agent.agent_id,
            "name": best_agent.name,
            "score": round(best_score, 3),
        },
        "delivered": delivered,
        "alternatives": [
            {"agent_id": a.agent_id, "name": a.name, "score": round(s, 3)}
            for a, s in ranked[1:4]
        ],
        "stream_id": stream_id,
    }


# --- Routes ---

@app.get("/")
async def serve_dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/agents")
async def get_agents():
    return JSONResponse(_get_agents_data())


@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str):
    registry = AgentRegistry(config)
    agent = registry.get(agent_id)
    if not agent:
        return JSONResponse({"error": "Agent not found"}, status_code=404)
    monitor = HeartbeatMonitor(config)
    return JSONResponse({
        "agent_id": agent.agent_id,
        "name": agent.name,
        "cli_type": agent.cli_type,
        "machine": agent.machine,
        "role": agent.role.value,
        "status": agent.status.value,
        "current_load": agent.current_load,
        "current_task": agent.current_task,
        "context_window": agent.context_window,
        "capabilities": agent.capabilities.to_vector(),
        "alive": monitor.is_alive(agent.agent_id),
        "activity": monitor.get_activity(agent.agent_id),
    })


@app.get("/api/events")
async def get_events(count: int = 50):
    return JSONResponse(_get_events_data(count))


@app.get("/api/tasks")
async def get_tasks():
    queue = TaskQueue(config)
    pending = queue.get_pending(count=50)
    return JSONResponse({
        "stream_length": queue.stream_length(),
        "pending": pending,
    })


@app.get("/api/pulse")
async def get_pulse():
    return JSONResponse(_get_pulse_sync())


@app.post("/api/command")
async def submit_command(body: dict):
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "Empty command"}, status_code=400)

    # Route and broadcast
    result = _route_command(text)
    await manager.broadcast({
        "type": "command_result",
        "data": result,
    })
    return JSONResponse(result)


@app.post("/api/heartbeat")
async def agent_heartbeat(body: dict):
    """Remote heartbeat — any agent can POST to stay alive."""
    agent_id = body.get("agent_id", "").strip()
    activity = body.get("activity", "")
    if not agent_id:
        return JSONResponse({"error": "agent_id required"}, status_code=400)

    r = get_redis_sync(config)
    hb_key = f"{config.heartbeat_prefix}{agent_id}"
    ttl_ms = config.heartbeat_ttl_s * 1000
    r.psetex(hb_key, ttl_ms, str(time.time()))
    if activity:
        act_key = f"{config.activity_prefix}{agent_id}"
        r.hset(act_key, mapping={"last_command": activity, "timestamp": str(time.time())})

    return JSONResponse({"ok": True, "agent_id": agent_id})


@app.post("/api/report")
async def agent_report(body: dict):
    """Agent reports task completion or failure."""
    task_id = body.get("task_id", "").strip()
    agent_id = body.get("agent_id", "").strip()
    status = body.get("status", "completed")  # completed | failed
    summary = body.get("summary", "")

    if not task_id or not agent_id:
        return JSONResponse({"error": "task_id and agent_id required"}, status_code=400)

    event_type = EventType.TASK_COMPLETED.value if status == "completed" else EventType.TASK_FAILED.value
    payload = {"task_id": task_id, "agent": agent_id, "summary": summary}
    emit(event_type, payload, actor=agent_id)

    # Broadcast to dashboard
    await manager.broadcast({
        "type": "task_report",
        "data": {"task_id": task_id, "agent_id": agent_id, "status": status, "summary": summary, "timestamp": time.time()},
    })
    return JSONResponse({"ok": True, "task_id": task_id, "status": status})


@app.post("/api/message")
async def agent_message(body: dict):
    """Agent posts a message to The Stream — for discoveries, questions, greetings."""
    agent_id = body.get("agent_id", "").strip()
    text = body.get("text", "").strip()
    msg_type = body.get("type", "insight")  # insight | question | greeting | alert

    if not agent_id or not text:
        return JSONResponse({"error": "agent_id and text required"}, status_code=400)

    msg_id = f"msg-{uuid.uuid4().hex[:8]}"
    emit("agent.message", {"msg_id": msg_id, "text": text, "msg_type": msg_type}, actor=agent_id)

    await manager.broadcast({
        "type": "agent_message",
        "data": {
            "msg_id": msg_id,
            "agent_id": agent_id,
            "text": text,
            "msg_type": msg_type,
            "timestamp": time.time(),
        },
    })
    return JSONResponse({"ok": True, "msg_id": msg_id})


@app.post("/api/status")
async def agent_status_update(body: dict):
    """Agent updates its own status (busy/idle/current_task)."""
    agent_id = body.get("agent_id", "").strip()
    if not agent_id:
        return JSONResponse({"error": "agent_id required"}, status_code=400)

    registry = AgentRegistry(config)
    agent = registry.get(agent_id)
    if not agent:
        return JSONResponse({"error": "Agent not found"}, status_code=404)

    # Update fields
    if "status" in body:
        agent.status = AgentStatus(body["status"])
    if "current_task" in body:
        agent.current_task = body["current_task"]
    if "current_load" in body:
        agent.current_load = body["current_load"]

    registry.register(agent)

    await manager.broadcast({
        "type": "agent_status",
        "data": {
            "agent_id": agent_id,
            "status": agent.status.value,
            "current_task": agent.current_task,
            "current_load": agent.current_load,
            "changed_at": time.time(),
        },
    })
    return JSONResponse({"ok": True, "agent_id": agent_id})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send initial state on connect
        await ws.send_json({
            "type": "init",
            "data": {
                "agents": _get_agents_data(),
                "events": _get_events_data(20),
                "pulse": _get_pulse_sync(),
            }
        })
        # Keep alive — receive pings or commands
        while True:
            data = await ws.receive_text()
            # Client can send commands via WebSocket too
            try:
                msg = json.loads(data)
                if msg.get("type") == "command":
                    result = _route_command(msg.get("text", ""))
                    await ws.send_json({"type": "command_result", "data": result})
                elif msg.get("type") == "ping":
                    await ws.send_json({"type": "pong", "data": {"time": time.time()}})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
