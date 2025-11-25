# MCP Tools in Claude Code: Complete Technical Analysis
**Research Date**: November 25, 2025  
**Status**: Comprehensive Investigation Complete

---

## EXECUTIVE SUMMARY

MCP (Model Context Protocol) tools in Claude Code operate through a **JSON-RPC 2.0 over stdio/SSE/HTTP** architecture with **strict timeout constraints** and **no native support for detached background processes**. Tools must either complete within timeout windows or implement **progress notifications** to keep connections alive.

**Critical Findings**:
1. Default timeout: **60 seconds** (TypeScript SDK)
2. Maximum configurable timeout: **120 seconds** (observed in Docker integration)
3. Startup timeout: **Configurable via MCP_TIMEOUT environment variable**
4. Background processes: **NOT directly supported** - requires workarounds
5. Progress notifications: **Reset timeout when received** (if resetTimeoutOnProgress=true)

---

## 1. TRANSPORT MECHANISMS

### A. Stdio Transport (Most Common)

**Architecture**:
- Uses Node.js `child_process.spawn()` to launch MCP server process
- Communication via stdin (client → server) and stdout (server → client)
- JSON-RPC 2.0 messages over stdio streams
- **Critical**: stderr should be used for logging, stdout reserved for protocol

**Process Lifecycle**:
```javascript
// Typical spawn pattern in MCP TypeScript SDK
const transport = new StdioClientTransport({
  command: 'node',
  args: ['server.js'],
  env: process.env
});
```

**Key Constraints**:
- **Single client connection only**
- **Process-bound lifecycle** - server dies when parent exits
- **No network accessibility**
- **Cannot use detached mode** with stdio inheritance (Node.js limitation)
- Parent process waits for child unless `subprocess.unref()` called

**Detachment Impossibility**:
From Node.js documentation: "When using the detached option to start a long-running process, the process will not stay running in the background after the parent exits unless it is provided with a stdio configuration that is not connected to the parent."

**Implication**: MCP stdio servers CANNOT detach while maintaining communication channel.

### B. HTTP/HTTPS Transport

**Architecture**:
- Remote MCP servers over network
- Recommended for cloud-based services
- Supports multiple concurrent clients
- Not bound to process lifecycle

**Advantages**:
- Production-ready
- Scalable
- Can run independently of client

### C. SSE (Server-Sent Events) Transport

**Status**: Deprecated in favor of HTTP
**Known Issues**:
- SSE stream disconnections after ~5 minutes
- Error: "SSE stream disconnected: TypeError: terminated"

---

## 2. TIMEOUT CONSTRAINTS AT EACH LAYER

### Layer 1: MCP TypeScript SDK Client

**Default Timeout**: 60 seconds
**Error Code**: -32001 (Request timeout)
**Behavior**: Hard timeout on tool execution
**Configurable**: Via client initialization (not documented in Claude Code)

**Issue Reference**: GitHub issue #470 - "Currently MCP tool calls over 60s in duration fail due to -32001 timeout in the mcp typescript-sdk"

### Layer 2: Claude Code MCP Integration

**Startup Timeout**: Configurable via `MCP_TIMEOUT` environment variable
- Example: `MCP_TIMEOUT=10000 claude` sets 10-second startup timeout
- Controls server initialization phase

**Output Limits**:
- **Default max**: 25,000 tokens
- **Warning threshold**: 10,000 tokens
- **Configurable**: Via `MAX_MCP_OUTPUT_TOKENS` environment variable

### Layer 3: Tool-Specific Timeouts

**Example - Bash Tool**:
```python
{
  "timeout": {
    "type": "number",
    "description": "Optional timeout in milliseconds",
    "maximum": 600000  # 10 minutes max
  }
}
```

### Layer 4: Docker/Gateway Integration

**Observed Timeout**: 120 seconds
**Issue**: Docker MCP Gateway tools timeout after 120s despite proper connection
**Error Message**: "Tool ran without output or errors"
**Root Cause**: Communication protocol mismatch between Claude Code and Docker stdio interface

---

## 3. PROGRESS NOTIFICATIONS: THE TIMEOUT SOLUTION

### The Problem
Tools that take >60 seconds fail with -32001 timeout, with no way to predict appropriate timeout values upfront (e.g., for sub-agent operations).

### The Solution: resetTimeoutOnProgress

**Mechanism**: 
- Tool sends progress notifications during execution
- If `resetTimeoutOnProgress=true`, each progress update resets the timeout counter
- Allows indefinite execution as long as progress is reported

**Implementation (Python)**:
```python
async def long_running_tool(ctx):
    total_steps = 100
    for i in range(total_steps):
        # Do work
        await asyncio.sleep(1)
        
        # Send progress notification (resets timeout)
        await ctx.session.send_progress_notification(
            progress_token=ctx.request_id,
            progress=i,
            total=total_steps,
            message=f"Step {i}/{total_steps}"
        )
    
    return result
```

**Current Status in Claude Code**:
- **Feature Request**: GitHub issue #470 (opened March 13, 2025)
- **Assigned**: Ashwin Bhat
- **Status**: Enhancement, labeled for autoclose
- **Community Support**: 8 👍 reactions

**TypeScript SDK Status**:
- `resetTimeoutOnProgress` changed from default `false` to `true` in recent versions
- Now consistent with Python SDK behavior

**Recommendation**: Send progress updates every 5-10 seconds for long operations

---

## 4. WHAT CAUSES TOOLS TO HANG

### A. Communication Failures

**Windows-Specific Issues**:
- NPX commands require `cmd /c` wrapper
- Without wrapper: "Connection closed" error
- Reason: Windows cannot directly execute `npx`

**Protocol Mismatches**:
- Claude Code may fail to include `protocolVersion` field in initialize requests
- Causes timeout during `tools/list` request phase

### B. Timeout Expiration

**Symptoms**:
- Tool appears to execute but no output
- "-32001 Request timeout" error
- "Tool ran without output or errors" message

**Root Causes**:
1. Tool execution exceeds 60s without progress notifications
2. No response on stdout (stdio transport)
3. Server crashed/hung but connection still open

### C. Process Management Issues

**Detached Process Attempts**:
- Tools that spawn detached background processes lose stdio connection
- Parent process closes, child inherits closed file descriptors
- No mechanism to return control while background work continues

**Session State Loss**:
- Stdio servers are ephemeral per-session
- No persistence between tool calls
- Each invocation spawns fresh process (unless server implements caching)

### D. Output Issues

**Stdout Pollution**:
- Logging to stdout breaks JSON-RPC protocol
- Must log to stderr or file
- Any non-JSON-RPC output on stdout causes parsing failure

---

## 5. BACKGROUND PROCESS REQUIREMENTS

### The Fundamental Constraint

**MCP stdio servers CANNOT spawn truly detached background processes while maintaining communication.**

**Why?**:
1. Stdio transport requires active stdin/stdout pipes
2. Detached processes must not inherit parent stdio (Node.js requirement)
3. Cannot simultaneously detach AND maintain JSON-RPC channel

### Workarounds for Long-Running Operations

#### Pattern 1: Asynchronous Hand-Off (Recommended)

Implement a multi-tool suite:

```python
# Tool 1: Start operation, return immediately
@server.tool("start_research")
async def start_research(topic: str) -> dict:
    task_id = str(uuid.uuid4())
    # Spawn background worker (NOT via MCP process)
    asyncio.create_task(background_worker(task_id, topic))
    return {"task_id": task_id, "status": "started"}

# Tool 2: Check status
@server.tool("query_research")
async def query_research(task_id: str) -> dict:
    status = await get_task_status(task_id)
    return {"status": status, "progress": "..."}

# Tool 3: Poll with progress updates
@server.tool("wait_research")
async def wait_research(task_id: str, ctx) -> dict:
    while not complete:
        await asyncio.sleep(5)
        status = await get_task_status(task_id)
        await ctx.session.send_progress_notification(
            progress_token=ctx.request_id,
            message=f"Status: {status}"
        )
    return final_result
```

**Advantages**:
- Decouples request-response from execution
- Works within timeout constraints
- Provides progress feedback

#### Pattern 2: Durable Execution Engine (Enterprise)

**Use Temporal or similar workflow engine**:
- MCP server acts as thin gateway
- Temporal handles actual execution
- Crash-resistant, horizontally scalable
- Complete audit trail

**Architecture**:
```
Claude Code → MCP Server → Temporal Workflow → Workers
                ↓                               ↓
            Returns task_id              Executes in background
```

#### Pattern 3: External Queue + Polling

**Use Redis/RabbitMQ/SQS**:
1. Tool enqueues job, returns job_id
2. External worker processes queue
3. Separate polling tool checks status
4. Progress notifications keep connection alive

---

## 6. SESSION STATE MANAGEMENT

### Stdio Server Lifecycle

**Per-Session Spawning**:
- Each Claude Code session spawns new MCP server process
- Server dies when session ends
- No persistence between sessions

**Within-Session State**:
- Server can maintain state in memory during session
- State survives across multiple tool calls in same session
- Lost on server restart/crash

### Output Styles (Claude Code Feature)

**Session-Scoped Persistence**:
- Output styles persist across all messages in session
- Set once, applies until explicitly changed
- NOT per-message injection

**Example**:
```bash
# Set once
claude --output-style json

# Applies to all subsequent messages until changed
```

### Continue Flag

**Session Resumption**:
```bash
claude --continue  # or -c
```

- Re-opens most recent conversation in project directory
- Can resume context
- MCP servers respawn (no state carried over)

---

## 7. IMPLEMENTATION CONSTRAINTS

### A. Configuration Requirements

**Claude Desktop MCP Config**:
```json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["server.js"],
      "env": {
        "API_KEY": "${API_KEY}"  // Environment variable expansion
      }
    }
  }
}
```

**Windows-Specific**:
```json
{
  "command": "cmd",
  "args": ["/c", "npx", "-y", "server-package"]
}
```

### B. Security Constraints

**Tool Execution Safety**:
- All tools require explicit user consent
- Represents arbitrary code execution
- Claude Code has deny patterns for dangerous operations

**From settings.json**:
```json
{
  "permissions": {
    "deny": [
      "Bash(rm -rf *)",
      "Write(delete:*)"
    ]
  }
}
```

### C. OAuth & Authentication

**Token Management**:
- Authentication tokens stored securely
- Automatic refresh for OAuth 2.0
- No manual token handling required

### D. Flag Parsing

**Critical**: Use `--` separator to prevent flag conflicts
```bash
claude -- mcp-server --server-flag
```

Without `--`, Claude Code parses `--server-flag` as its own argument.

---

## 8. BEST PRACTICES FOR LONG-RUNNING OPERATIONS

### 1. Implement Progress Notifications

**Always send progress for operations >10 seconds**:
```python
async def my_tool(ctx):
    steps = ["init", "process", "finalize"]
    for i, step in enumerate(steps):
        await ctx.session.send_progress_notification(
            progress_token=ctx.request_id,
            progress=i * 33,
            total=100,
            message=f"Step: {step}"
        )
        await do_work(step)
```

### 2. Decompose into Smaller Operations

**Break monolithic tasks into logical chunks**:
- Instead of: `research_and_analyze_and_report()`
- Use: `start_research()`, `get_research_status()`, `analyze_results()`, `generate_report()`

### 3. Use Async Hand-Off Pattern

**For truly long operations (>2 minutes)**:
- Return task_id immediately
- Provide separate status check tool
- Implement wait tool with progress updates

### 4. Proper Error Handling

**Implement retries with exponential backoff**:
```python
@retry(max_attempts=3, backoff_factor=2)
async def unreliable_operation():
    # May fail transiently
    pass
```

### 5. Log Correctly

**NEVER log to stdout in stdio servers**:
```python
import logging
import sys

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,  # NOT stdout!
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### 6. Handle Cancellation

**Gracefully handle cancellation requests**:
```python
try:
    await long_operation()
except asyncio.CancelledError:
    await cleanup()
    raise
```

### 7. Resource Management

**Properly close resources on shutdown**:
```python
import signal

def handle_shutdown(signum, frame):
    logger.info("Shutting down gracefully")
    # Close connections, save state, etc.
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)
```

---

## 9. KNOWN ISSUES & WORKAROUNDS

### Issue #470: Long MCP Tool Calls Timeout

**Problem**: Tools >60s fail with -32001 timeout  
**Workaround**: Implement progress notifications  
**Status**: Feature request pending (resetTimeoutOnProgress support in Claude Code)

### Issue #4202: Docker MCP Gateway Timeout

**Problem**: Docker tools timeout at 120s despite connection  
**Root Cause**: Communication protocol mismatch  
**Workaround**: Use HTTP transport instead of stdio for Docker

### Issue #3033: MCP Server Timeout Config Ignored

**Problem**: SSE connection timeout configuration not respected  
**Workaround**: Use HTTP transport instead of SSE

### Issue #3426: MCP Tools Not Exposed

**Problem**: Playwright MCP server tools not visible to AI  
**Root Cause**: Server registration failure  
**Workaround**: Verify server config, check logs in ~/.claude/debug/

### Windows NPX Issue

**Problem**: "Connection closed" errors on Windows  
**Solution**: Use `cmd /c npx ...` wrapper in server command

---

## 10. ARCHITECTURAL RECOMMENDATIONS FOR TAEY-HANDS

### Current Implementation Analysis

**Existing System (palios-taey-nova)**:
- Custom tool registry (not MCP protocol)
- Python-based tool execution
- Supports streaming
- 30s timeout, 5MB output limit on bash tool
- Pattern-based routing with trust verification

**Taey-Hands Current State**:
- JavaScript/Node.js orchestration
- Browser automation via Playwright
- No MCP implementation detected
- Neo4j for conversation persistence

### Recommended MCP Integration Strategy

#### Option 1: HTTP MCP Server (Recommended for Production)

**Architecture**:
```
Claude Code → HTTP MCP Client → FastAPI MCP Server → Taey-Hands Tools
                                      ↓
                              Neo4j + Playwright + OSABridge
```

**Advantages**:
- No timeout constraints
- Production-ready
- Can run on separate machine (e.g., mira)
- Supports multiple concurrent clients
- Natural fit with existing FastAPI infrastructure

**Implementation**:
```python
from fastapi import FastAPI
from mcp import MCPServer

app = FastAPI()
mcp_server = MCPServer()

@mcp_server.tool("orchestrate_chat")
async def orchestrate_chat(
    message: str, 
    ai_sequence: list[str],
    ctx: MCPContext
) -> dict:
    # Import existing orchestrator
    orchestrator = Orchestrator()
    
    total_steps = len(ai_sequence)
    results = []
    
    for i, ai in enumerate(ai_sequence):
        await ctx.session.send_progress_notification(
            progress_token=ctx.request_id,
            progress=i * (100 / total_steps),
            total=100,
            message=f"Asking {ai}..."
        )
        
        result = await orchestrator.ask(ai, message)
        results.append(result)
    
    return {"results": results}
```

#### Option 2: Stdio MCP Server (For Local Development)

**Use Case**: Local development, single-user scenarios

**Constraints**:
- Must implement progress notifications for long operations
- Cannot spawn truly detached processes
- Need async hand-off pattern for >60s operations

#### Option 3: Hybrid Approach

**Local stdio server for quick operations (<30s)**:
- File operations
- Quick queries
- Status checks

**HTTP server for long operations**:
- Multi-AI orchestration
- Browser automation workflows
- Research operations

### Specific Tool Design

#### Tool: Multi-AI Orchestration

**Challenge**: Orchestrating Claude → Gemini → Grok chain takes >60s

**Solution Pattern**:
```python
@server.tool("start_orchestration")
async def start_orchestration(message: str, sequence: list) -> dict:
    task_id = create_task(message, sequence)
    # Spawn orchestration in background (via queue/Temporal)
    enqueue_orchestration(task_id)
    return {"task_id": task_id, "status": "started"}

@server.tool("wait_orchestration")
async def wait_orchestration(task_id: str, ctx: MCPContext) -> dict:
    while True:
        status = get_task_status(task_id)
        
        if status["complete"]:
            return status["results"]
        
        await ctx.session.send_progress_notification(
            progress_token=ctx.request_id,
            message=f"Current: {status['current_ai']}"
        )
        
        await asyncio.sleep(5)
```

#### Tool: Browser Automation

**Challenge**: Playwright operations can take 30-120s

**Solution**: Progress notifications at each step
```python
@server.tool("automate_browser")
async def automate_browser(steps: list, ctx: MCPContext) -> dict:
    browser = await launch_browser()
    
    for i, step in enumerate(steps):
        await ctx.session.send_progress_notification(
            progress_token=ctx.request_id,
            progress=i * (100 / len(steps)),
            total=100,
            message=f"Executing: {step['action']}"
        )
        
        await execute_step(browser, step)
    
    return {"status": "complete"}
```

---

## 11. TECHNICAL SPECIFICATIONS SUMMARY

### JSON-RPC 2.0 Protocol

**Message Format**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "tool_name",
    "arguments": {...}
  }
}
```

**Response Format**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {...}
}
```

**Error Format**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32001,
    "message": "Request timeout (60s)"
  }
}
```

### Tool Definition Schema

```json
{
  "name": "tool_name",
  "description": "What the tool does",
  "inputSchema": {
    "type": "object",
    "properties": {
      "param_name": {
        "type": "string",
        "description": "Parameter description"
      }
    },
    "required": ["param_name"]
  }
}
```

### Progress Notification Schema

```json
{
  "jsonrpc": "2.0",
  "method": "notifications/progress",
  "params": {
    "progressToken": "request_id_123",
    "progress": 50,
    "total": 100,
    "message": "Processing step 5 of 10"
  }
}
```

---

## 12. CONCLUSION & KEY TAKEAWAYS

### Critical Constraints

1. **60-second hard timeout** on tool execution (MCP TypeScript SDK default)
2. **No native detached process support** - architecture fundamentally incompatible
3. **Progress notifications required** for operations >60s
4. **Stdio transport = process-bound lifecycle**
5. **HTTP transport = production recommendation**

### Architectural Implications

**For short operations (<30s)**:
- Stdio transport acceptable
- Synchronous execution fine
- Minimal progress updates needed

**For medium operations (30-120s)**:
- MUST implement progress notifications
- Send updates every 5-10 seconds
- Decompose into logical steps

**For long operations (>2 minutes)**:
- Async hand-off pattern REQUIRED
- Return task_id immediately
- Separate status/wait tools
- Consider durable execution engine (Temporal)

### Best Transport Choice by Use Case

| Use Case | Recommended Transport | Rationale |
|----------|----------------------|-----------|
| Local dev tools | Stdio | Simple, direct access to system |
| Production services | HTTP | Scalable, no timeouts, remote capable |
| Cloud integrations | HTTP | Network-accessible, stateless |
| Browser automation | HTTP | Long-running, needs progress updates |
| Quick file ops | Stdio | <30s, local only |

### Implementation Checklist

- [ ] Choose transport type (stdio vs HTTP)
- [ ] Implement progress notifications for all operations >10s
- [ ] Use async hand-off pattern for operations >60s
- [ ] Log to stderr only (stdio) or separate log file (HTTP)
- [ ] Handle cancellation gracefully
- [ ] Implement proper shutdown hooks
- [ ] Add retry logic with exponential backoff
- [ ] Validate all input parameters
- [ ] Return structured error messages
- [ ] Test timeout scenarios explicitly

---

## REFERENCES

### Documentation
- [MCP Specification (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18)
- [Claude Code MCP Docs](https://code.claude.com/docs/en/mcp)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

### Issues Referenced
- [#470: resetTimeoutOnProgress for long tool calls](https://github.com/anthropics/claude-code/issues/470)
- [#4202: Docker MCP Gateway timeout](https://github.com/anthropics/claude-code/issues/4202)
- [#3033: MCP timeout config ignored (SSE)](https://github.com/anthropics/claude-code/issues/3033)
- [#3426: MCP tools not exposed](https://github.com/anthropics/claude-code/issues/3426)

### Technical Guides
- [Building Timeout-Proof MCP Tools](https://www.arsturn.com/blog/no-more-timeouts-how-to-build-long-running-mcp-tools-that-actually-finish-the-job)
- [MCP Interactive Tools (Progress, Cancellation)](https://newsletter.victordibia.com/p/mcp-for-software-engineers-part-2)
- [Building MCP with Temporal](https://temporal.io/blog/building-long-running-interactive-mcp-tools-temporal)

---

**Research Compiled By**: Claude Code (CCM)  
**Date**: November 25, 2025  
**Confidence Level**: High (based on official docs, source code inspection, and issue tracker analysis)  
**Recommendation**: Implement HTTP MCP server with progress notifications for Taey-Hands integration
