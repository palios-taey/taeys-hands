# Taey-Hands MCP Server

Model Context Protocol (MCP) server for orchestrating Claude research workflows via browser automation.

## Overview

This MCP server provides three tools for managing long-running Claude research requests:

1. **start_claude_research** - Spawn a research job (returns immediately with job ID)
2. **get_research_status** - Check job progress and current phase
3. **get_research_result** - Retrieve completed results (response, artifacts, screenshots)

## Architecture

```
MCP Server (server.ts)
    ├── Job Manager (job-manager.ts)
    │   ├── Spawns detached worker processes
    │   ├── Tracks jobs in-memory (Map)
    │   └── Manages status/result files (/tmp)
    └── Worker (worker.js)
        ├── Calls existing claude-research-request.js workflow
        ├── Updates status file during execution
        └── Writes final result file on completion
```

## Installation

```bash
cd mcp_server
npm install
npm run build
```

## Usage

### Running the Server

The MCP server communicates via stdio (standard input/output):

```bash
node dist/server.js
```

### Tool 1: start_claude_research

Start a new research job. Returns immediately with a job ID.

**Input:**
```json
{
  "model": "Opus 4.5",
  "message": "Research the latest advances in quantum computing",
  "files": ["/path/to/file1.pdf", "/path/to/file2.txt"],
  "research": true
}
```

**Output:**
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "started",
  "message": "Research job started successfully"
}
```

**Execution Time:** < 2 seconds (just spawns process)

### Tool 2: get_research_status

Check the status of a running or completed job.

**Input:**
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Output:**
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "startedAt": "2025-11-25T04:00:00.000Z",
  "progress": {
    "phase": "waiting_for_response",
    "message": "Waiting for Claude to complete response"
  }
}
```

**Status Values:**
- `pending` - Job queued but not started
- `running` - Job actively executing
- `completed` - Job finished successfully
- `failed` - Job encountered an error

**Execution Time:** < 1 second (reads status file)

### Tool 3: get_research_result

Retrieve the final result of a completed job.

**Input:**
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Output:**
```json
{
  "jobId": "550e8400-e29b-41d4-a716-446655440000",
  "sessionId": 1732507200000,
  "responseText": "Based on my research...",
  "artifact": {
    "filePath": "/tmp/artifact-12345.txt",
    "fileName": "quantum-computing-analysis.txt",
    "content": "..."
  },
  "screenshots": {
    "modelSelected": "/tmp/taey-claude-1732507200000-model.png",
    "researchEnabled": "/tmp/taey-claude-1732507200000-research-enabled.png",
    "messageTyped": "/tmp/taey-claude-1732507200000-typed.png",
    "messageSent": "/tmp/taey-claude-1732507200000-sent.png",
    "responseComplete": "/tmp/taey-claude-1732507200000-response.png",
    "final": "/tmp/taey-claude-1732507200000-final.png"
  }
}
```

**Execution Time:** < 2 seconds (reads result file)

## Job Lifecycle

1. **Client calls start_claude_research**
   - Server generates unique job ID
   - Spawns detached worker process
   - Returns job ID immediately

2. **Worker process executes**
   - Connects to Claude via browser automation
   - Selects model and enables research mode
   - Attaches files (if provided)
   - Types and sends message
   - Waits for response completion
   - Downloads artifacts
   - Takes screenshots at each phase
   - Updates status file throughout

3. **Client polls get_research_status**
   - Reads current status from file
   - Returns progress information

4. **Client retrieves get_research_result**
   - When status = "completed"
   - Reads final result from file
   - Returns response text, artifacts, screenshots

## File System Layout

```
/tmp/
├── research-{jobId}-status.json   # Job status (updated during execution)
├── research-{jobId}-result.json   # Final result (written on completion)
└── taey-claude-{sessionId}-*.png  # Screenshots from workflow
```

## Configuration

The MCP server uses the existing taey-hands configuration:

- **Browser automation:** `src/core/browser-connector.js`
- **Claude interface:** `src/interfaces/chat-interface.js`
- **Workflow:** `src/workflows/claude-research-request.js`

## Error Handling

All tools return structured error responses:

```json
{
  "error": "Job 12345 not found"
}
```

With `isError: true` flag set in the MCP response.

## Development

### Build
```bash
npm run build
```

### Watch mode (rebuild on changes)
```bash
npm run watch
```

### Run locally
```bash
npm run dev
```

## Integration with Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "taey-hands": {
      "command": "node",
      "args": ["/Users/REDACTED/taey-hands/mcp_server/dist/server.js"]
    }
  }
}
```

Then restart Claude Desktop.

## Typical Workflow

```javascript
// 1. Start a research job
const startResult = await callTool("start_claude_research", {
  model: "Opus 4.5",
  message: "Analyze the attached research papers",
  files: ["/path/to/paper1.pdf", "/path/to/paper2.pdf"],
  research: true
});

const jobId = JSON.parse(startResult).jobId;

// 2. Poll for status
let status;
do {
  await sleep(5000); // Wait 5 seconds
  const statusResult = await callTool("get_research_status", { jobId });
  status = JSON.parse(statusResult);
} while (status.status === "running");

// 3. Get final result
if (status.status === "completed") {
  const resultData = await callTool("get_research_result", { jobId });
  const result = JSON.parse(resultData);

  console.log("Response:", result.responseText);
  console.log("Artifact:", result.artifact?.fileName);
  console.log("Screenshots:", Object.keys(result.screenshots));
}
```

## Dependencies

- `@modelcontextprotocol/sdk` - Official MCP TypeScript SDK
- `typescript` - TypeScript compiler
- `@types/node` - Node.js type definitions

## License

MIT
