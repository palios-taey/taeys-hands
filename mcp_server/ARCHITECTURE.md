# MCP Server Architecture

Visual documentation of the Taey-Hands MCP server architecture, data flow, and component interactions.

---

## System Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                          MCP CLIENT                                 │
│                    (Claude Desktop, etc.)                           │
│                                                                      │
│  User: "Use taey-hands to research quantum computing"               │
└────────────────────┬───────────────────────────────────────────────┘
                     │
                     │ JSON-RPC over stdio
                     │ {"method": "tools/call", "params": {...}}
                     │
┌────────────────────▼───────────────────────────────────────────────┐
│                     MCP SERVER (server.ts)                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  @modelcontextprotocol/sdk                                   │  │
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐ │  │
│  │  │ ListTools      │  │ start_claude_  │  │ get_research_  │ │  │
│  │  │ Handler        │  │ research       │  │ status/result  │ │  │
│  │  └────────────────┘  └────────────────┘  └────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                     │                                               │
│  ┌──────────────────▼──────────────────────────────────────────┐   │
│  │              JobManager (job-manager.ts)                     │   │
│  │                                                              │   │
│  │  jobs: Map<string, JobStatus> = {                           │   │
│  │    "abc-123": {                                              │   │
│  │      jobId: "abc-123",                                       │   │
│  │      status: "running",                                      │   │
│  │      startedAt: "2025-11-25T04:00:00Z",                      │   │
│  │      progress: { phase: "waiting_for_response", ... }        │   │
│  │    }                                                         │   │
│  │  }                                                           │   │
│  │                                                              │   │
│  │  Methods:                                                    │   │
│  │  • startJob(config) → jobId                                 │   │
│  │  • getJobStatus(jobId) → JobStatus                          │   │
│  │  • getJobResult(jobId) → JobResult                          │   │
│  │  • cleanupJob(jobId) → void                                 │   │
│  └──────────────────┬──────────────────────────────────────────┘   │
└─────────────────────┼──────────────────────────────────────────────┘
                      │
                      │ spawn('node', ['worker.js', jobId, ...])
                      │ { detached: true, stdio: 'ignore' }
                      │ worker.unref()
                      │
┌─────────────────────▼──────────────────────────────────────────────┐
│                   WORKER PROCESS (worker.js)                        │
│                                                                      │
│  Process isolated from parent, runs independently                   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  1. Parse CLI args (jobId, sessionId, model, message, ...)  │    │
│  │  2. updateStatus("running", "connecting", ...)               │    │
│  │  3. Call claudeResearchRequest(config)                       │    │
│  │  4. updateStatus("running", "typing_message", ...)           │    │
│  │  5. updateStatus("completed", "finished", ...)               │    │
│  │  6. writeResult({ responseText, artifact, screenshots })     │    │
│  │  7. process.exit(0)                                          │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  Writes to:                                                          │
│  • /tmp/research-{jobId}-status.json  (during execution)            │
│  • /tmp/research-{jobId}-result.json  (on completion)               │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       │ import { claudeResearchRequest }
                       │
┌──────────────────────▼───────────────────────────────────────────────┐
│        EXISTING WORKFLOW (claude-research-request.js)                 │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  1. new ClaudeInterface()                                     │   │
│  │  2. connect()                                                 │   │
│  │  3. selectModel(model)                                        │   │
│  │  4. setResearchMode(true)                                     │   │
│  │  5. attachFile(files[])                                       │   │
│  │  6. typeMessage(message)                                      │   │
│  │  7. clickSend()                                               │   │
│  │  8. waitForResponse()                                         │   │
│  │  9. downloadArtifact()                                        │   │
│  │  10. screenshot() at each step                                │   │
│  │  11. disconnect()                                             │   │
│  │  12. return { responseText, artifact, screenshots }           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagram

### Starting a Job

```
Client                 Server              JobManager           Worker
  │                      │                      │                  │
  ├──start_claude───────>│                      │                  │
  │  research            │                      │                  │
  │                      │                      │                  │
  │                      ├──startJob(config)───>│                  │
  │                      │                      │                  │
  │                      │                      ├─generate UUID    │
  │                      │                      ├─create status    │
  │                      │                      ├─spawn worker────>│
  │                      │                      │  (detached)      │
  │                      │                      │                  │
  │                      │<─────jobId───────────┤                  │
  │                      │                      │                  │
  │<─────jobId───────────┤                      │                  │
  │  (< 2 seconds)       │                      │                  │
  │                      │                      │                  │
  │                      │                      │                  ├─execute
  │                      │                      │                  │  workflow
  │                      │                      │                  │
```

### Checking Status

```
Client                 Server              JobManager           Worker
  │                      │                      │                  │
  ├──get_research───────>│                      │                  │
  │  status              │                      │                  │
  │                      │                      │                  │
  │                      ├─getJobStatus(id)────>│                  │
  │                      │                      │                  │
  │                      │                      ├─check cache      │
  │                      │                      ├─read /tmp file   │
  │                      │                      │  (if needed)     │
  │                      │                      │                  │
  │                      │<─────status──────────┤                  │
  │                      │                      │                  │
  │<─────status──────────┤                      │                  │
  │  (< 1 second)        │                      │                  │
  │                      │                      │                  │
```

### Getting Results

```
Client                 Server              JobManager           Worker
  │                      │                      │                  │
  ├──get_research───────>│                      │                  │
  │  result              │                      │                  │
  │                      │                      │                  │
  │                      ├─getJobResult(id)────>│                  │
  │                      │                      │                  │
  │                      │                      ├─getJobStatus()   │
  │                      │                      ├─verify completed │
  │                      │                      ├─read result file │
  │                      │                      │  from /tmp       │
  │                      │                      │                  │
  │                      │<─────result──────────┤                  │
  │                      │  (responseText,      │                  │
  │                      │   artifact,          │                  │
  │                      │   screenshots)       │                  │
  │                      │                      │                  │
  │<─────result──────────┤                      │                  │
  │  (< 2 seconds)       │                      │                  │
  │                      │                      │                  │
```

---

## File System Layout

```
/Users/REDACTED/taey-hands/
│
├── mcp_server/                          # MCP server implementation
│   ├── server.ts                        # Main MCP server
│   ├── job-manager.ts                   # Job queue manager
│   ├── worker.js                        # Worker process
│   ├── dist/                            # Compiled TypeScript
│   │   ├── server.js
│   │   ├── job-manager.js
│   │   └── *.d.ts, *.map
│   ├── package.json
│   ├── tsconfig.json
│   ├── test-init.js
│   └── *.md                             # Documentation
│
├── src/
│   ├── workflows/
│   │   └── claude-research-request.js   # Workflow implementation
│   ├── interfaces/
│   │   └── chat-interface.js            # Claude UI abstraction
│   └── core/
│       └── browser-connector.js         # CDP connection
│
└── package.json                         # Parent project deps

/tmp/                                    # Runtime files
├── research-{jobId}-status.json         # Job status (updated live)
├── research-{jobId}-result.json         # Final results
└── taey-claude-{sessionId}-*.png        # Screenshots
```

---

## Component Interactions

### Server Initialization

```
1. Server starts
   └─> Load @modelcontextprotocol/sdk
   └─> Create JobManager instance
   └─> Register tool handlers
   └─> Create StdioServerTransport
   └─> Connect and listen

2. Client connects
   └─> Send initialize request
   └─> Receive server capabilities
   └─> Send tools/list request
   └─> Receive tool definitions
```

### Job Lifecycle

```
┌─────────────┐
│   PENDING   │  Created, not started
└──────┬──────┘
       │ Worker spawned
       ▼
┌─────────────┐
│   RUNNING   │  Executing workflow
│             │  • connecting
│             │  • model_selection
│             │  • research_mode
│             │  • attaching_files
│             │  • typing_message
│             │  • sending
│             │  • waiting_for_response
│             │  • downloading_artifact
│             │  • extracting_text
└──────┬──────┘
       │
       ├─────────────┐
       │             │
       ▼             ▼
┌──────────┐   ┌──────────┐
│COMPLETED │   │  FAILED  │
└──────────┘   └──────────┘
```

### Status File Updates

```
Worker writes status at each phase:

Phase: connecting
{
  "jobId": "abc-123",
  "status": "running",
  "startedAt": "2025-11-25T04:00:00Z",
  "progress": {
    "phase": "connecting",
    "message": "Connecting to Claude interface"
  }
}

Phase: waiting_for_response
{
  "jobId": "abc-123",
  "status": "running",
  "startedAt": "2025-11-25T04:00:00Z",
  "progress": {
    "phase": "waiting_for_response",
    "message": "Waiting for Claude to complete response"
  }
}

Phase: finished
{
  "jobId": "abc-123",
  "status": "completed",
  "startedAt": "2025-11-25T04:00:00Z",
  "completedAt": "2025-11-25T04:05:00Z",
  "progress": {
    "phase": "finished",
    "message": "Research completed successfully"
  }
}
```

---

## Process Tree

When a job starts:

```
└─ node dist/server.js                    # MCP Server (PID 1000)
   ├─ [stdin/stdout connected to client]
   └─ Map<jobId, status> in memory

    (spawn detached, then unref)

    node mcp_server/worker.js abc-123 ... # Worker (PID 2000, independent)
    ├─ Reads args from CLI
    ├─ Writes /tmp/research-abc-123-status.json
    ├─ Calls claudeResearchRequest()
    │  └─ Spawns Chrome via Playwright
    │     └─ chrome --remote-debugging-port=9222
    ├─ Writes /tmp/research-abc-123-result.json
    └─ process.exit(0)
```

The worker is **detached** and **unref'd**, so:
- Worker can outlive server
- Server can restart without affecting workers
- Workers exit cleanly on completion

---

## Communication Patterns

### Server ↔ Client

**Protocol:** JSON-RPC 2.0 over stdio

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "start_claude_research",
    "arguments": {
      "model": "Opus 4.5",
      "message": "What is quantum computing?",
      "research": true
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"jobId\":\"abc-123\",\"status\":\"started\"}"
      }
    ]
  }
}
```

### Server ↔ Worker

**Communication:** File system (/tmp)

**Server → Worker:** CLI arguments at spawn time

**Worker → Server:**
- Status file (updated during execution)
- Result file (written on completion)

**Server reads files when:**
- getJobStatus() called
- getJobResult() called
- Cache miss (not in memory)

---

## Error Handling Flow

```
Worker encounters error
    ├─> Catch exception
    ├─> Update status file
    │   {
    │     "status": "failed",
    │     "error": "Browser connection timeout"
    │   }
    ├─> Write result file with error
    ├─> Take error screenshot
    └─> process.exit(1)

Client checks status
    ├─> get_research_status
    └─> Returns: { "status": "failed", "error": "..." }

Client attempts result
    ├─> get_research_result
    └─> Returns: { "error": "..." }
```

---

## Memory Layout

### Server Process

```
┌────────────────────────────────────────┐
│  MCP Server Process (Node.js)          │
│  ────────────────────────────────       │
│  Heap: ~50 MB                           │
│  ├─ MCP SDK objects                    │
│  ├─ JobManager instance                │
│  │  └─ Map<jobId, JobStatus>           │
│  │     └─ ~100 KB per job              │
│  └─ Transport buffers                  │
│                                         │
│  Stack: ~2 MB                           │
│  Code: ~10 MB                           │
└────────────────────────────────────────┘
```

### Worker Process

```
┌────────────────────────────────────────┐
│  Worker Process (Node.js + Playwright) │
│  ────────────────────────────────────   │
│  Heap: ~100 MB                          │
│  ├─ Workflow state                     │
│  ├─ Playwright objects                 │
│  ├─ Screenshot buffers                 │
│  └─ Response text                      │
│                                         │
│  Chrome Process: ~300-500 MB           │
│  └─ Managed by Playwright              │
└────────────────────────────────────────┘
```

---

## Timing Diagram

```
Time →
0s      Client calls start_claude_research
│       │
│       ├─ Server validates input
│       ├─ JobManager generates UUID
│       ├─ Worker spawned (detached)
│       └─ Return jobId
2s      ─────────────────────────────────→ Job started (client receives jobId)
│
│       Worker executing...
│       ├─ 5s: Browser launched
│       ├─ 10s: Navigated to Claude
│       ├─ 15s: Model selected
│       ├─ 18s: Research mode enabled
│       ├─ 20s: Message typed
│       ├─ 22s: Send clicked
│       └─ 25s-180s: Waiting for response
│
180s    ─────────────────────────────────→ Response complete
│       │
│       ├─ Extract text
│       ├─ Download artifact
│       ├─ Write result file
│       └─ exit(0)
182s    ─────────────────────────────────→ Worker exits
│
│       Client polls get_research_status
│       └─ Returns: { "status": "completed" }
│
│       Client calls get_research_result
│       └─ Returns: { responseText, artifact, screenshots }
185s    ─────────────────────────────────→ Client has full results
```

---

## Threading Model

```
MCP Server Process
├─ Main Thread
│  ├─ Event Loop (async/await)
│  ├─ stdio transport
│  └─ Tool handlers

Worker Process (independent)
├─ Main Thread
│  ├─ Workflow execution
│  └─ File I/O
└─ Playwright manages Chrome threads
```

No shared memory. All communication via file system.

---

## Security Boundaries

```
┌────────────────────────────────────────────────────────┐
│  MCP Client (Claude Desktop)                           │
│  Trust: Full (local application)                       │
└─────────────────┬──────────────────────────────────────┘
                  │ stdio (local only)
┌─────────────────▼──────────────────────────────────────┐
│  MCP Server                                             │
│  Trust: Full (same user, local)                         │
│  Security: Input validation only                        │
└─────────────────┬──────────────────────────────────────┘
                  │ spawn (detached)
┌─────────────────▼──────────────────────────────────────┐
│  Worker Process                                         │
│  Trust: Full (same user, local)                         │
│  Security: None (inherits user permissions)             │
│  Can access: All files user can access                  │
│             All websites user can visit                 │
│             User's logged-in Claude session             │
└─────────────────┬──────────────────────────────────────┘
                  │ CDP (Chrome DevTools Protocol)
┌─────────────────▼──────────────────────────────────────┐
│  Chrome Browser                                         │
│  Trust: User's session (logged in)                      │
│  Security: Standard browser security                    │
└─────────────────────────────────────────────────────────┘
```

**Key Points:**
- No authentication between components (local trust)
- Worker inherits all user permissions
- Browser uses real user session
- File system is shared resource (/tmp)

---

## Scaling Considerations

### Current Design (Single Machine)

```
Server
├─ Worker 1 → Chrome 1
├─ Worker 2 → Chrome 2
├─ Worker 3 → Chrome 3
└─ ...

Bottlenecks:
• Chrome memory (~500 MB each)
• CPU for browser rendering
• Disk I/O for screenshots
```

### Future: Distributed Workers

```
Server
├─ Queue (Redis)
│
Worker Pool (multiple machines)
├─ Machine 1
│  ├─ Worker 1 → Chrome 1
│  └─ Worker 2 → Chrome 2
├─ Machine 2
│  ├─ Worker 3 → Chrome 3
│  └─ Worker 4 → Chrome 4
└─ ...

Required changes:
• Shared job queue (Redis)
• Shared file storage (S3, NFS)
• Worker registration
• Load balancing
```

---

## Monitoring Points

### Server Health
- Tool request latency
- Job creation rate
- Active job count
- Memory usage

### Worker Health
- Job completion rate
- Average job duration
- Failure rate
- Browser launch time

### System Health
- /tmp disk usage
- Chrome process count
- File descriptor count
- Network connectivity

---

This architecture provides:
- ✅ Fast response times (< 2s for job creation)
- ✅ Isolation (detached workers)
- ✅ Simple IPC (file system)
- ✅ Observable (status files, screenshots)
- ✅ Debuggable (inspectable at every level)
- ✅ Scalable (add more workers)

Built for local development, ready for production deployment with minimal changes.
