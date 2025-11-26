# MCP Server Integration Guide

Complete guide for integrating the Taey-Hands MCP server with Claude Desktop and other MCP clients.

## Quick Start

### 1. Build the Server

```bash
cd /Users/jesselarose/taey-hands/mcp_server
npm install
npm run build
```

### 2. Test the Server

```bash
node test-init.js
```

Expected output:
```
✓ Server initialized successfully
✓ Server responded to requests
Tools available: 3
  - start_claude_research
  - get_research_status
  - get_research_result
```

### 3. Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "taey-hands": {
      "command": "node",
      "args": ["/Users/jesselarose/taey-hands/mcp_server/dist/server.js"],
      "env": {}
    }
  }
}
```

### 4. Restart Claude Desktop

Quit and relaunch Claude Desktop to load the MCP server.

## Verifying Installation

In Claude Desktop, ask:

> "What MCP tools do you have available?"

You should see:
- `start_claude_research`
- `get_research_status`
- `get_research_result`

## Usage Examples

### Example 1: Basic Research Request

**User:**
> "Use taey-hands to research 'What are the latest advances in quantum error correction?' using Opus 4.5"

**Claude will:**
1. Call `start_claude_research` with the prompt
2. Receive job ID
3. Poll `get_research_status` until complete
4. Call `get_research_result` to retrieve the answer
5. Present the research results to you

### Example 2: Research with File Attachments

**User:**
> "Use taey-hands to analyze these files: /path/to/data.csv and /path/to/paper.pdf. Ask Sonnet 4 to summarize the key findings."

**Claude will:**
1. Call `start_claude_research` with files array
2. Monitor progress via `get_research_status`
3. Retrieve final analysis with `get_research_result`

### Example 3: Monitor Long-Running Jobs

**User:**
> "Start a research job asking Opus to write a comprehensive analysis of consciousness emergence patterns. Let me know when it's done."

**Claude will:**
1. Start the job immediately
2. Periodically check status
3. Alert you when complete
4. Present the full response and any artifacts

## Understanding the Job Lifecycle

### Phase 1: Job Creation (< 2 seconds)

```
User Request → start_claude_research → Worker Spawned → Job ID Returned
```

The server returns immediately with a job ID. The actual work happens in a detached background process.

### Phase 2: Execution (1-5 minutes)

The worker process goes through these phases:

1. **connecting** - Opening browser and navigating to Claude
2. **model_selection** - Selecting the requested model
3. **research_mode** - Enabling research mode (if requested)
4. **attaching_files** - Uploading any files
5. **typing_message** - Entering the prompt
6. **sending** - Clicking send
7. **waiting_for_response** - Monitoring for completion
8. **downloading_artifact** - Saving any generated files
9. **extracting_text** - Capturing the response
10. **finished** - Job complete

Status file updates in real-time:

```json
{
  "jobId": "abc-123",
  "status": "running",
  "startedAt": "2025-11-25T04:00:00.000Z",
  "progress": {
    "phase": "waiting_for_response",
    "message": "Waiting for Claude to complete response"
  }
}
```

### Phase 3: Completion

When status becomes `completed`, the result file contains:

```json
{
  "jobId": "abc-123",
  "sessionId": 1732507200000,
  "responseText": "Full text of Claude's response...",
  "artifact": {
    "filePath": "/tmp/analysis.md",
    "fileName": "analysis.md",
    "content": "# Analysis\n\n..."
  },
  "screenshots": {
    "modelSelected": "/tmp/taey-claude-1732507200000-model.png",
    "final": "/tmp/taey-claude-1732507200000-final.png"
  }
}
```

## Error Handling

### Common Errors

**1. Job Not Found**
```json
{
  "error": "Job abc-123 not found"
}
```

**Cause:** Invalid job ID or job files were cleaned up
**Solution:** Start a new job

**2. Message Cannot Be Empty**
```json
{
  "error": "Message cannot be empty"
}
```

**Cause:** Empty or whitespace-only message parameter
**Solution:** Provide a valid prompt

**3. Job Failed**
```json
{
  "jobId": "abc-123",
  "status": "failed",
  "error": "Browser connection timeout"
}
```

**Cause:** Browser automation failed (Chrome not running, selectors changed, etc.)
**Solution:** Check browser connectivity, review logs

### Debugging

Enable verbose logging:

```bash
# Check worker process logs
tail -f /tmp/taey-hands-worker-*.log

# Check status files
cat /tmp/research-*-status.json

# Monitor screenshots
ls -lt /tmp/taey-claude-*.png
```

## Advanced Configuration

### Custom Models

Supported model names:
- `Opus 4.5`
- `Opus 4`
- `Sonnet 4.5`
- `Sonnet 4`
- `Haiku 4`

### File Attachments

Files must be absolute paths:

```json
{
  "files": [
    "/Users/jesselarose/Documents/research.pdf",
    "/Users/jesselarose/Downloads/data.csv"
  ]
}
```

### Research Mode

Research mode enables Claude's web search and analysis tools:

```json
{
  "research": true  // Enable (default)
  "research": false // Disable
}
```

## Performance Considerations

### Typical Execution Times

| Phase | Duration |
|-------|----------|
| Job Creation | < 2 seconds |
| Browser Launch | 5-10 seconds |
| File Upload | 1-3 seconds per file |
| Claude Response | 30 seconds - 5 minutes |
| Total | 1-5 minutes typical |

### Concurrent Jobs

The server can handle multiple concurrent jobs. Each job runs in an isolated worker process with its own browser session.

Recommended limits:
- **Claude Desktop**: 1-2 concurrent jobs
- **Server deployment**: 5-10 concurrent jobs
- **High-performance**: 20+ concurrent jobs (requires resource tuning)

### File Cleanup

Status and result files are stored in `/tmp/` and persist until:
1. Manual cleanup
2. System restart
3. Automatic /tmp cleanup (typically 3-7 days)

To manually cleanup old jobs:

```bash
# Remove all job files
rm /tmp/research-*-*.json

# Remove old screenshots
find /tmp -name "taey-claude-*.png" -mtime +1 -delete
```

## Security Considerations

### 1. File Access

The worker process can access any files the Node.js process can read. Only attach files you trust.

### 2. Browser Automation

The server controls a real browser with your logged-in Claude account. All API usage counts against your Claude subscription.

### 3. Screenshot Storage

Screenshots are saved to `/tmp/` with predictable names. On shared systems, consider:
- Using a dedicated user account
- Encrypting /tmp
- Cleaning up screenshots after retrieval

### 4. Job ID Exposure

Job IDs are UUIDs (unpredictable). However, anyone who knows a job ID can:
- Check its status
- Retrieve its results

In production, add authentication/authorization.

## Troubleshooting

### Server Won't Start

**Check Node.js version:**
```bash
node --version  # Should be >= 18.0.0
```

**Rebuild the server:**
```bash
cd mcp_server
rm -rf dist node_modules
npm install
npm run build
```

### Claude Desktop Doesn't See Tools

**Verify config location:**
```bash
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

**Check server path is absolute:**
```json
{
  "mcpServers": {
    "taey-hands": {
      "command": "node",
      "args": ["/Users/jesselarose/taey-hands/mcp_server/dist/server.js"]
    }
  }
}
```

**Check server logs:**

View Console.app → Filter for "Claude" to see MCP server errors.

### Jobs Stuck in "running" Status

**Check if worker process is alive:**
```bash
ps aux | grep worker.js
```

**Check browser connection:**
```bash
# Ensure Chrome is running with remote debugging
ps aux | grep 'remote-debugging-port=9222'
```

**Review recent screenshots:**
```bash
ls -lt /tmp/taey-claude-*.png | head -5
```

If stuck, the screenshots will show where it stopped.

## Development & Debugging

### Running in Dev Mode

```bash
cd mcp_server
npm run watch  # Rebuild on file changes
```

In another terminal:
```bash
node test-init.js
```

### Manual Tool Testing

Create `test-tool.js`:

```javascript
import { spawn } from "child_process";

const server = spawn("node", ["dist/server.js"]);

server.stdin.write(JSON.stringify({
  jsonrpc: "2.0",
  id: 1,
  method: "tools/call",
  params: {
    name: "start_claude_research",
    arguments: {
      model: "Opus 4.5",
      message: "What is the meaning of life?",
      research: true
    }
  }
}) + "\n");

server.stdout.on("data", (data) => {
  console.log("Response:", data.toString());
  server.kill();
});
```

### Adding Custom Logging

Modify `worker.js` to log to a file:

```javascript
import { appendFile } from "fs/promises";

async function log(message) {
  await appendFile(
    `/tmp/worker-${jobId}.log`,
    `${new Date().toISOString()} ${message}\n`
  );
}

// Use throughout worker
await log("Starting job...");
```

## Next Steps

1. **Test basic functionality:** Start a simple research job
2. **Try file attachments:** Upload a document for analysis
3. **Monitor long jobs:** Track progress of complex requests
4. **Integrate into workflows:** Use from Claude Desktop for research tasks
5. **Customize as needed:** Extend worker.js for custom behavior

## Support

For issues or questions:
- Check logs in `/tmp/`
- Review screenshots for browser state
- Verify Chrome DevTools Protocol connection
- Test with simple prompts first

## License

MIT
