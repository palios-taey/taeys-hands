# Taey-Hands MCP Server - Quick Reference

## Installation

```bash
cd /Users/REDACTED/taey-hands/mcp_server
npm install && npm run build
```

## Testing

```bash
node test-init.js
```

Expected: ✓ Server initialized successfully, 3 tools available

## Claude Desktop Setup

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Restart Claude Desktop.

## Three Tools

### 1. start_claude_research

**Purpose:** Start a research job (returns immediately)

**Input:**
```json
{
  "model": "Opus 4.5",           // Optional, default: "Opus 4.5"
  "message": "Your question",     // Required
  "files": ["/path/to/file"],    // Optional, default: []
  "research": true                // Optional, default: true
}
```

**Output:**
```json
{
  "jobId": "uuid-here",
  "status": "started"
}
```

**Time:** < 2 seconds

---

### 2. get_research_status

**Purpose:** Check job progress

**Input:**
```json
{
  "jobId": "uuid-here"
}
```

**Output:**
```json
{
  "jobId": "uuid-here",
  "status": "running",           // pending|running|completed|failed
  "startedAt": "ISO-8601",
  "progress": {
    "phase": "waiting_for_response",
    "message": "Descriptive message"
  }
}
```

**Time:** < 1 second

---

### 3. get_research_result

**Purpose:** Get final results (only when completed)

**Input:**
```json
{
  "jobId": "uuid-here"
}
```

**Output:**
```json
{
  "jobId": "uuid-here",
  "sessionId": 1732507200000,
  "responseText": "Claude's full response...",
  "artifact": {
    "filePath": "/tmp/file.txt",
    "fileName": "file.txt",
    "content": "artifact contents"
  },
  "screenshots": {
    "modelSelected": "/tmp/screenshot-1.png",
    "final": "/tmp/screenshot-2.png"
  }
}
```

**Time:** < 2 seconds

## Workflow Phases

1. **connecting** - Opening browser
2. **model_selection** - Selecting model
3. **research_mode** - Enabling research
4. **attaching_files** - Uploading files
5. **typing_message** - Entering prompt
6. **sending** - Clicking send
7. **waiting_for_response** - Monitoring completion
8. **downloading_artifact** - Saving files
9. **extracting_text** - Capturing response
10. **finished** - Complete

## Supported Models

- Opus 4.5
- Opus 4
- Sonnet 4.5
- Sonnet 4
- Haiku 4

## File Locations

```
/tmp/
├── research-{jobId}-status.json    # Job status
├── research-{jobId}-result.json    # Final result
└── taey-claude-{sessionId}-*.png   # Screenshots
```

## Typical Usage (Claude Desktop)

**User:** "Use taey-hands to research quantum computing advances with Opus 4.5"

**Claude will:**
1. Call `start_claude_research` → get job ID
2. Poll `get_research_status` → wait for completion
3. Call `get_research_result` → retrieve answer
4. Present results to user

## Debugging

**Check server logs:**
```bash
# View Console.app → Filter "Claude"
```

**Check job status:**
```bash
cat /tmp/research-{jobId}-status.json
```

**Check screenshots:**
```bash
ls -lt /tmp/taey-claude-*.png | head -5
open /tmp/taey-claude-{sessionId}-final.png
```

**Clean up old files:**
```bash
rm /tmp/research-*-*.json
rm /tmp/taey-claude-*.png
```

## Common Issues

| Issue | Solution |
|-------|----------|
| Server won't start | Check Node.js >= 18, rebuild with `npm run build` |
| Tools not visible | Check config path is absolute, restart Claude Desktop |
| Job stuck "running" | Check browser connection, review screenshots |
| "Job not found" | Use correct job ID from start_claude_research response |

## Development

**Build:**
```bash
npm run build
```

**Watch mode:**
```bash
npm run watch
```

**Manual test:**
```bash
node dist/server.js  # Server runs on stdio
```

## Architecture

```
server.ts          → Main MCP server, handles tool requests
job-manager.ts     → Spawns workers, tracks jobs
worker.js          → Executes workflow, updates status
```

## Performance

| Metric | Value |
|--------|-------|
| Job creation | < 2 seconds |
| Browser launch | 5-10 seconds |
| Typical job | 1-5 minutes |
| Max concurrent | 5-10 jobs |

## Security Notes

- Worker has same file access as Node.js process
- Uses your logged-in Claude account
- Screenshots saved to /tmp (world-readable on some systems)
- Job IDs are UUIDs (unpredictable)

## Next Steps

1. Test with simple prompt: "What is 2+2?"
2. Try file attachment: Upload a PDF
3. Monitor long job: Complex research question
4. Use in workflows: Integrate with other MCP tools

## Documentation

- **README.md** - Full documentation
- **INTEGRATION_GUIDE.md** - Detailed integration steps
- **QUICK_REFERENCE.md** - This file

## License

MIT
