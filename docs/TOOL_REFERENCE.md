# Taey-Hands MCP Tools - Complete Reference

## Tool Overview Matrix

```
NAME                    INPUT ARGS              OUTPUT FIELDS                  SPEED    ERROR SAFE
──────────────────────────────────────────────────────────────────────────────────────────────
taey_connect            interface               sessionId, screenshot          2-4s     ✓
taey_disconnect         sessionId               success                        1-2s     ✓
taey_new_conversation   sessionId               conversationUrl                2-3s     ✓
taey_send_message       sessionId, message      success, sentText              1-2s     ✓
taey_extract_response   sessionId               responseText, timestamp        <1s      ✓
taey_select_model       sessionId, modelName    automationCompleted, screenshot 2-3s     ✓
taey_attach_files       sessionId, filePaths[]  automationCompleted, results   5-8s     ✓
taey_paste_response     srcSessionId, tgtSsId   automationCompleted, pastedText 2-3s     ✓
taey_enable_research    sessionId, enabled?     automationCompleted, mode      3-5s     ✓
taey_download_artifact  sessionId, path?        automationCompleted, filePath  8-12s    ✓
```

---

## Tool Details

### 1. taey_connect

**Purpose**: Establish a new session to a chat interface

**Input Parameters**:
```json
{
  "interface": "claude|chatgpt|gemini|grok|perplexity",
  "newSession": true,
  "sessionId": "optional-reuse-existing-session",
  "conversationId": "optional-conversation-id-or-url"
}
```

**REQUIRED**: Must specify EITHER `newSession: true` OR `sessionId` (explicit session management)

**Output**:
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "interface": "claude|chatgpt|gemini|grok|perplexity",
  "screenshot": "/tmp/taey-{interface}-{sessionId}-connected.png",
  "conversationUrl": "url-if-conversation-specified",
  "message": "Connected to {interface}"
}
```

**Example**:
```
// Create new session (REQUIRED parameter)
taey_connect(interface: "claude", newSession: true)
→ sessionId: "f47ac10b-58cc-4372-a567-0e02b2c3d479"
→ screenshot: "/tmp/taey-claude-f47ac10b-...-connected.png"

// Reuse existing session
taey_connect(interface: "claude", sessionId: "f47ac10b-...")
→ Reuses same browser tab

// Navigate to specific conversation
taey_connect(interface: "claude", newSession: true, conversationId: "abc123")
→ sessionId: "...", conversationUrl: "https://claude.ai/chat/abc123"
```

**Common Issues**:
- Chrome not running with `--remote-debugging-port=9222`
- Not logged in to the interface
- Port 9222 already in use

---

### 2. taey_disconnect

**Purpose**: Clean up and close a session

**Input Parameters**:
```json
{
  "sessionId": "uuid-from-taey_connect"
}
```

**Output**:
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "message": "Session disconnected"
}
```

**Example**:
```
taey_disconnect(sessionId: "f47ac10b-58cc-4372-a567-0e02b2c3d479")
→ success: true
```

**Important**: Always call this when done to release browser resources

---

### 3. taey_new_conversation

**Purpose**: Start a fresh conversation in the current interface

**Input Parameters**:
```json
{
  "sessionId": "uuid-from-taey_connect"
}
```

**Output**:
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "conversationUrl": "https://interface.com/chat/new-id",
  "message": "New conversation started"
}
```

**Example**:
```
taey_new_conversation(sessionId: "abc-123")
→ conversationUrl: "https://claude.ai/chat/new-conversation-id"
```

---

### 4. taey_send_message

**Purpose**: Type and send a message in the current conversation

**Input Parameters**:
```json
{
  "sessionId": "uuid-from-taey_connect",
  "message": "Your message here",
  "waitForResponse": false
}
```

**Output**:
```json
{
  "success": true,
  "sessionId": "uuid-string",
  "sentText": "Your message here",
  "message": "Message sent",
  "waitForResponse": false
}
```

**Example**:
```
taey_send_message(
  sessionId: "abc-123",
  message: "What is the capital of France?"
)
→ success: true, sentText: "What is the capital of France?"
```

**Details**:
- Types message with human-like delays
- Uses `taey_extract_response` to get the answer
- Message is sent via Enter key / Send button

---

### 5. taey_extract_response

**Purpose**: Get the latest AI response text

**Input Parameters**:
```json
{
  "sessionId": "uuid-from-taey_connect"
}
```

**Output**:
```json
{
  "success": true,
  "responseText": "The capital of France is Paris.",
  "timestamp": "2025-11-25T20:30:45.123Z"
}
```

**Example**:
```
// After taey_send_message
taey_extract_response(sessionId: "abc-123")
→ responseText: "The capital of France is Paris."
```

**Performance**:
- If response is ready: <1 second
- If still generating: Wait for completion (poll every few seconds)

---

### 6. taey_select_model

**Purpose**: Switch to a different AI model

**⚠️ ChatGPT Note**: Model selection is currently **disabled** for ChatGPT. ChatGPT sessions use Auto mode by default. For thinking-intensive tasks, use `taey_enable_research_mode` with `modeName: "Deep research"` instead.

**Input Parameters**:
```json
{
  "sessionId": "uuid-from-taey_connect",
  "modelName": "Opus 4.5|Sonnet 4|Haiku 4|etc",
  "isLegacy": false
}
```

**Output**:
```json
{
  "automationCompleted": true,
  "sessionId": "uuid-string",
  "interfaceType": "claude|chatgpt|gemini|grok|perplexity",
  "modelName": "Selected Model Name",
  "screenshot": "/tmp/taey-screenshot.png",
  "message": "Selected model: {modelName}"
}
```

**Available Models by Interface**:

**Claude**:
- Opus 4.5 (recommended for complex reasoning)
- Sonnet 4.5 (faster, good balance)
- Haiku 4.5 (fastest)

**ChatGPT** (Model selection disabled - Auto mode only):
- Auto (default, automatic selection)
- ~~Instant~~ (use Auto mode)
- ~~Thinking~~ (use Deep research mode via `taey_enable_research_mode`)
- ~~Pro~~ (use Auto mode)
- ~~GPT-4o~~ (legacy models unavailable)

**Gemini**:
- Thinking with 3 Pro (advanced reasoning)
- Thinking (standard thinking mode)
- 2.0 Flash (fast)
- 2.0 (balanced)

**Grok**:
- Grok 4.1 (latest, standard)
- Grok 4.1 Thinking (with extended reasoning)
- Grok 4 Heavy (powerful, resource-intensive)

**Perplexity**:
- ❌ No model selection implemented
- Uses default model per mode (Search/Research/Labs)

**Example**:
```
// Claude model selection (works)
taey_select_model(
  sessionId: "abc-123",
  modelName: "Opus 4.5"
)
→ automationCompleted: true, screenshot: "/tmp/..."

// ChatGPT model selection (disabled, returns stub)
taey_select_model(
  sessionId: "chatgpt-session",
  modelName: "Thinking"
)
→ automationCompleted: true, modelName: "Auto (selection disabled)"
→ Use taey_enable_research_mode(sessionId, modeName: "Deep research") instead
```

---

### 7. taey_attach_files

**Purpose**: Attach one or more files to the conversation

**Input Parameters**:
```json
{
  "sessionId": "uuid-from-taey_connect",
  "filePaths": [
    "/absolute/path/to/file1.pdf",
    "/absolute/path/to/file2.txt"
  ]
}
```

**Output**:
```json
{
  "automationCompleted": true,
  "filesAttached": 2,
  "attachments": [
    {
      "filePath": "/absolute/path/to/file1.pdf",
      "screenshot": "/tmp/taey-...",
      "automationCompleted": true
    }
  ],
  "message": "Attached 2 file(s)"
}
```

**Example**:
```
taey_attach_files(
  sessionId: "abc-123",
  filePaths: ["/Users/jesse/document.pdf", "/Users/jesse/data.csv"]
)
→ automationCompleted: true, filesAttached: 2
```

**Important**:
- Use ABSOLUTE paths only
- File must exist before call
- Some interfaces have Pro limits (e.g., Perplexity)
- Supports: PDF, TXT, CSV, JSON, MD, etc.

---

### 8. taey_paste_response

**Purpose**: Copy response from one AI and paste into another (cross-pollination)

**Input Parameters**:
```json
{
  "sourceSessionId": "uuid-from-taey_connect",
  "targetSessionId": "uuid-from-taey_connect",
  "prefix": "Optional prefix text"
}
```

**Output**:
```json
{
  "automationCompleted": true,
  "sourceSessionId": "uuid",
  "targetSessionId": "uuid",
  "pastedText": "Text from source + optional prefix",
  "responseLength": 1245,
  "message": "Response pasted successfully"
}
```

**Example**:
```
// Get Claude's response and send to ChatGPT
taey_paste_response(
  sourceSessionId: "claude-id",
  targetSessionId: "chatgpt-id",
  prefix: "Claude said: "
)
→ automationCompleted: true, pastedText: "Claude said: The answer is..."
```

**Workflow**:
1. Two separate sessions (one for Claude, one for ChatGPT)
2. Claude generates response
3. taey_paste_response extracts it and sends to ChatGPT
4. ChatGPT can build on Claude's answer

---

### 9. taey_enable_research_mode

**Purpose**: Toggle extended thinking / research modes

**Input Parameters**:
```json
{
  "sessionId": "uuid-from-taey_connect",
  "enabled": true,
  "modeName": "Deep research|Deep Research|Deep Think|Pro Search|..."
}
```

**Output**:
```json
{
  "automationCompleted": true,
  "sessionId": "uuid-string",
  "interfaceType": "claude|chatgpt|gemini|grok|perplexity",
  "screenshot": "/tmp/taey-screenshot.png",
  "enabled": true,
  "mode": "Extended Thinking enabled|Deep research enabled|...",
  "message": "{mode}"
}
```

**Modes by Interface**:

**Claude**:
- Extended Thinking (Research toggle - enabled/disabled via checkbox)
- Uses 64x more tokens for reasoning

**ChatGPT**:
- Deep research (autonomous web search)
- Agent mode (tool use)
- Web search (standard web search)
- GitHub (GitHub integration)

**Gemini**:
- Deep Research (web search + synthesis)
- Deep Think (extended reasoning)

**Grok**:
- ❌ No mode selection implemented
- Use model selection instead (4.1 Thinking, 4 Heavy)

**Perplexity**:
- Search (regular search mode)
- Research (Research Pro mode)
- Labs (Studio mode)

**Example**:
```
// Enable Claude's extended thinking
taey_enable_research_mode(
  sessionId: "claude-id",
  enabled: true
)
→ automationCompleted: true, mode: "Extended Thinking enabled"

// Enable ChatGPT deep research (recommended over model selection)
taey_enable_research_mode(
  sessionId: "chatgpt-id",
  enabled: true,
  modeName: "Deep research"
)
→ automationCompleted: true, mode: "Deep research enabled"
```

---

### 10. taey_download_artifact

**Purpose**: Download artifacts (files, code, documents) from AI responses

**Input Parameters**:
```json
{
  "sessionId": "uuid-from-taey_connect",
  "downloadPath": "/tmp",
  "format": "markdown|html",
  "timeout": 10000
}
```

**Output**:
```json
{
  "automationCompleted": true,
  "sessionId": "uuid-string",
  "interfaceType": "claude|chatgpt|gemini|grok|perplexity",
  "filePath": "/tmp/artifact_filename.md",
  "screenshot": "/tmp/taey-screenshot.png",
  "format": "markdown",
  "message": "Downloaded artifact to: /tmp/artifact_filename.md"
}
```

**Supported by Interface**:
- Claude: Yes (simple button click)
- ChatGPT: No artifact download
- Gemini: Yes (markdown or HTML export)
- Grok: No artifact download
- Perplexity: Yes (markdown or HTML export)

**Example**:
```
taey_download_artifact(
  sessionId: "claude-id",
  downloadPath: "/Users/jesse/Downloads",
  format: "markdown"
)
→ automationCompleted: true, filePath: "/Users/jesse/Downloads/code_1234.md"
```

**File Types**:
- Code (Python, JavaScript, HTML, etc.)
- Documents (Markdown, rich text)
- Data (CSV, JSON)
- HTML pages
- SVG diagrams

---

## Common Workflows

### Single-AI Conversation
```
1. taey_connect(interface: "claude")
2. taey_send_message(sessionId, "Your question")
3. taey_extract_response(sessionId)
4. taey_disconnect(sessionId)
```

### Multi-AI Comparison
```
1. taey_connect(interface: "claude")
2. taey_connect(interface: "chatgpt")
3. taey_send_message(claudeId, "Question")
4. taey_send_message(chatgptId, "Same question")
5. taey_extract_response(claudeId)
6. taey_extract_response(chatgptId)
7. taey_paste_response(claudeId, chatgptId, "Claude says: ")
8. taey_extract_response(chatgptId)  # Get updated response
9. taey_disconnect(claudeId)
10. taey_disconnect(chatgptId)
```

### Research with Artifacts
```
1. taey_connect(interface: "claude")
2. taey_enable_research_mode(sessionId, enabled: true)
3. taey_select_model(sessionId, "Opus 4.5")
4. taey_send_message(sessionId, "Write a comprehensive guide on X")
5. Wait for response
6. taey_download_artifact(sessionId, downloadPath: "/tmp")
7. taey_extract_response(sessionId)
8. taey_disconnect(sessionId)
```

### Multi-File Analysis
```
1. taey_connect(interface: "claude")
2. taey_attach_files(sessionId, ["/path/file1.pdf", "/path/file2.csv"])
3. taey_send_message(sessionId, "Analyze these files")
4. taey_extract_response(sessionId)
5. taey_disconnect(sessionId)
```

---

## Error Handling

All tools return `isError: true` on failure:

```json
{
  "success": false,
  "error": "Session not found: xyz",
  "isError": true
}
```

**Common Errors**:
- `Session not found` - Invalid sessionId
- `Not logged in` - Need to login in Chrome debug window
- `Selector not found` - UI changed, need to update selectors
- `Timeout` - Operation took >60 seconds (MCP SDK limit)
- `Chrome not running` - Start Chrome with `--remote-debugging-port=9222`

---

## Performance Expectations

| Operation | Typical | Max |
|-----------|---------|-----|
| Connect | 2-4s | 5s |
| Send message | 1-2s | 3s |
| Extract response (ready) | <1s | 2s |
| Select model | 2-3s | 5s |
| Attach files | 5-8s | 15s |
| Download artifact | 8-12s | 20s |
| Disconnect | 1-2s | 3s |
| **Session total** | **30-50s** | **60s** |

Total time for 1 full conversation: 30-50 seconds
Typical throughput: ~1 full conversation per minute

---

## Tips & Tricks

1. **Parallel Sessions**: Create multiple sessions for different AIs, process in parallel
2. **Response Polling**: Check `taey_extract_response` repeatedly (tool doesn't have built-in wait)
3. **Model Selection**: Always select model after connect for consistent behavior
4. **File Paths**: Use absolute paths, never relative
5. **Cleanup**: Always `taey_disconnect` to avoid resource leaks
6. **Cross-Pollination**: Use `taey_paste_response` to feed Claude's response to ChatGPT, Gemini, etc.
7. **Research Mode**: Enable on long/complex questions to get better reasoning

---

Generated: November 25, 2025
Last Updated: MCP v2.0 (9 tools)
