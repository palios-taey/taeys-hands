# MCP Architecture - Current vs. Proposed

## Current Architecture (BROKEN)

```
User
  ↓
MCP Host (Claude Desktop / CLI)
  ↓
MCP Transport (stdio/HTTP)
  ↓
MCP Server (server-v2.ts)
  ├── Tool Invocation: taey_send_message
  │   ├─ sessionId, message, attachments
  │   ├─ waitForResponse: true ⚠️
  │   ↓
  │   Tool Handler Starts
  │   ├─ Prepare input: 1s ✓
  │   ├─ Type message: 1s ✓
  │   ├─ Click send: 1s ✓
  │   ├─ Timeout Clock: 60s (TypeScript SDK)
  │   │
  │   ├─ Start ResponseDetectionEngine: 2s elapsed ✓
  │   │
  │   ├─ Await detector.detectCompletion(): ⏳
  │   │   ├─ Simple response: 10-30s ✓
  │   │   ├─ Extended Thinking: 5-15 minutes ❌
  │   │   ├─ Deep Research: 2-10 minutes ❌
  │   │   │
  │   │   └─ At 60s elapsed:
  │   │       └─ ❌ TIMEOUT - MCP disconnects
  │   │
  │   ├─ (Never reached) Extract response
  │   ├─ (Never reached) Log to Neo4j
  │   │
  │   └─ Return error to client ❌
  │
  └─ Client never receives full response ❌
      ├─ Neo4j missing assistant message ❌
      ├─ No way to recover response text ❌
      └─ User has no visibility into failure ❌

Timeout Error -32001
├─ "Request timeout after 60 seconds"
└─ User must retry manually
```

**Summary**: One tool doing too much. Blocks on long operations. MCP timeout fires before completion.

---

## Proposed Architecture (WORKING)

```
User
  ↓
MCP Host (Claude Desktop / CLI)
  ├────────────────────────────────────────────────────────────────┐
  │                      Fresh Start                                │
  │                  (Timeout clock reset)                          │
  ├────────────────────────────────────────────────────────────────┘
  │
  ├─ Tool 1 Invocation: taey_send_message
  │  ├─ sessionId, message, attachments
  │  ├─ NO waitForResponse parameter ✓
  │  │
  │  MCP Transport
  │    ↓
  │    MCP Server Handler
  │    ├─ Prepare input: 1s ✓
  │    ├─ Type message: 1s ✓
  │    ├─ Click send: 1s ✓
  │    ├─ Timeout Clock: 60s
  │    │
  │    ├─ Return immediately: {success: true}
  │    │   └─ ✓ Returns before timeout
  │    │
  │    └─ Return to Host
  │
  ├─────────────────────────────────────────────────────────────────┐
  │            Tool 1 Complete (2-5 seconds elapsed)                │
  │                   Fresh Timeout Clock                           │
  └─────────────────────────────────────────────────────────────────┘
  │
  ├─ Tool 2 Invocation: taey_wait_for_response (Option A)
  │  ├─ sessionId, maxWaitSeconds=600, pollIntervalSeconds=10
  │  │
  │  MCP Transport
  │    ↓
  │    MCP Server Handler
  │    ├─ Start ResponseDetectionEngine: 0s ✓
  │    ├─ Timeout Clock: 600s (configured) ✓ [or 60s default]
  │    │
  │    ├─ Loop: Wait for response
  │    │   ├─ Try detect: start
  │    │   │   ├─ Simple response (10-30s) → Found! Return ✓
  │    │   │   ├─ Extended Thinking (5-15 min) → Still working...
  │    │   │   │   ├─ 10s elapsed: Report progress
  │    │   │   │   ├─ 20s elapsed: Report progress
  │    │   │   │   ├─ ...
  │    │   │   │   ├─ 300s elapsed: Response detected! ✓
  │    │   │   │   └─ Extract and return ✓
  │    │   │   │
  │    │   │   └─ Deep Research (2-10 min) → Still working...
  │    │   │       ├─ Report progress every 10s
  │    │   │       ├─ 500s elapsed: Response detected! ✓
  │    │   │       └─ Extract and return ✓
  │    │   │
  │    │   ├─ Sleep 1s
  │    │   └─ Loop (under timeout)
  │    │
  │    ├─ Response found → Return {success: true, responseText}
  │    │   └─ ✓ Tool completes before timeout (600s > 300s) ✓
  │    │
  │    └─ Return to Host
  │
  ├─────────────────────────────────────────────────────────────────┐
  │         Tool 2 Complete (after full response time)              │
  │              (e.g., 300s for Extended Thinking)                 │
  │                   Success! ✓✓✓                                  │
  └─────────────────────────────────────────────────────────────────┘
  │
  └─ User receives: {responseText, waitTime, detectionMethod}
      ├─ Full response text ✓
      ├─ Confidence metrics ✓
      ├─ Logged to Neo4j ✓
      └─ Ready for next operation ✓

Success!
├─ Extended Thinking: 5-15 min ✓
├─ Deep Research: 2-10 min ✓
├─ Simple responses: <60s ✓
└─ Tool separation enables flexibility ✓
```

**Summary**: Two tools, each with own timeout. First returns quickly. Second waits with fresh timeout. No conflicts.

---

## Detailed Message Flow Comparison

### Current (Broken)

```
User:
  "Send 'Complex problem' and wait for response"
  ↓
Claude:
  Call taey_send_message(message, waitForResponse=true)
  ↓
Server-v2.ts (Line 551-696):
  ├─ Send message: 2s
  ├─ Start detection: 2s
  ├─ Wait for Extended Thinking: ⏳
  │   ├─ 60s: Timeout! ❌
  │   └─ Abort waiting
  │
  └─ Return error (NEVER got response)
      ├─ No response text
      ├─ No confidence metrics
      ├─ No Neo4j log
      └─ User has to retry

Result: ❌ FAILURE
```

### Proposed (Working)

```
User:
  "Send 'Complex problem' and wait for response"
  ↓
Claude:
  Call taey_send_message(message) → Returns immediately
  Call taey_wait_for_response(maxWaitSeconds=900) → Waits
  ↓
Server-v2.ts:

Step 1 - taey_send_message (Lines 551-696):
  ├─ Send message: 2s
  ├─ Return immediately: {success: true, sessionId}
  ↓
  Tool completes successfully (no blocking)

Step 2 - taey_wait_for_response (NEW HANDLER):
  ├─ Start fresh: 0s
  ├─ Detection loop:
  │   ├─ 10s: Check response → Not ready
  │   ├─ 20s: Check response → Not ready
  │   ├─ ...
  │   ├─ 300s: Check response → Complete! ✓
  │   │   ├─ Extract response text
  │   │   ├─ Log to Neo4j
  │   │   ├─ Update session state
  │   │   └─ Return: {success, responseText, waitTime}
  │   │
  │   └─ Return within 600s timeout ✓
  ↓
  Tool completes successfully

Result: ✓ SUCCESS
├─ Response text: "Extended thinking answer..."
├─ Wait time: 300000ms
├─ Detection method: "advanced_completion_detection"
└─ Neo4j logged and indexed
```

---

## State Diagram

### Current Implementation

```
┌──────────────┐
│ Tool Called  │
│ send_message │
│ waitResponse │
│    =true     │
└────┬─────────┘
     │
     ▼
┌────────────────┐
│ Message Sent   │
│ Detection      │
│ Started        │
└────┬───────────┘
     │
     │  ⏳ Extended Thinking
     │  5-15 minutes
     │
     ├─ <60s: Still waiting ✓
     │
     ├─ =60s: ❌ TIMEOUT ❌
     │         MCP disconnects
     │         No response
     │         No recovery
     │
     └─► ❌ FAILED STATE
         No response text
         No Neo4j log
         Connection closed
```

### Proposed Implementation

```
┌──────────────┐
│ Tool 1:      │
│ send_message │
└────┬─────────┘
     │
     ▼ (2s)
┌────────────────┐
│ Message Sent   │
└────┬───────────┘
     │
     ├──► ✓ Return immediately
     │    (Tool completes)
     │
     │    Fresh timeout clock
     │
     ├──► Tool 2: taey_wait_for_response
     │    sessionId, maxWaitSeconds=600
     │
     ▼
┌────────────────┐      ┌──────────────┐
│ Detection Loop │──────│ 10s Elapsed  │
│ Starts         │      │ Report:      │
│ Clock: 0s      │      │ Waiting...   │
└────┬───────────┘      └──────────────┘
     │
     │  ⏳ Extended Thinking
     │  5-15 minutes
     │
     ├─ <600s: Poll & wait ✓
     │
     │  ✓ 300s: Response complete
     │
     ├─► ✓ COMPLETION STATE
     │    Extract response
     │    Log to Neo4j
     │    Update session
     │    Return {success, responseText}
     │
     └──► ✓ Return within timeout (300s < 600s)
          (Tool completes)
```

---

## Tool Invocation Timeline

### Scenario: Extended Thinking (5-15 minute response)

#### Current (Broken)
```
Timeline   | Tool State           | MCP Timeout | Result
-----------|----------------------|-------------|----------
0s         | Send message         | 60s remain  |
2s         | Detection start      | 58s remain  |
10s        | Waiting...           | 50s remain  |
20s        | Waiting...           | 40s remain  |
30s        | Waiting...           | 30s remain  |
40s        | Waiting...           | 20s remain  |
50s        | Waiting...           | 10s remain  |
60s        | ❌ TIMEOUT           | 0s         | ❌ FAIL
(300s)     | (Never reached)      | (expired)   |
```

#### Proposed (Working)
```
Tool 1: taey_send_message
Timeline   | State              | Timeout      | Result
-----------|-------------------|--------------|----------
0s         | Start              | 60s (60000)  |
2s         | Message sent       | 58s          |
2-3s       | Return immediately | COMPLETE     | ✓ SUCCESS
-----------+-------------------+--------------+----------
           | Tool 1 done        | Fresh clock  |

Tool 2: taey_wait_for_response (maxWaitSeconds=900)
Timeline   | State              | Timeout      | Result
-----------|-------------------|--------------|----------
0s         | Start              | 900s (fresh) |
5s         | Poll #1: Not ready | 895s         |
10s        | Poll #2: Not ready | 890s         |
           | (Progress logged)  |              |
20s        | Poll #3: Not ready | 880s         |
...        | ...                | ...          |
100s       | Poll #10: Wait...  | 800s         |
           | (Progress logged)  |              |
200s       | Poll #20: Wait...  | 700s         |
300s       | Poll #30: Complete!| 600s remain  | ✓ FOUND!
           | Extract response   |              |
305s       | Log to Neo4j       | 595s remain  |
310s       | Update session     | 590s remain  |
312s       | Return success     | 588s remain  | ✓ SUCCESS
-----------+-------------------+--------------+----------
           | Tool 2 done        | Within limit |

Total: Tool 1 (2s) + Tool 2 (312s) = 314s elapsed
MCP Timeout: 900s
Result: ✓ SUCCESS (314s < 900s)
```

---

## Memory & Resource Impact

### Current (Problematic)
```
┌─────────────────────────────────────┐
│ Single Tool (2-15 minutes blocking) │
├─────────────────────────────────────┤
│ • Playwright page held open          │
│ • ResponseDetectionEngine running    │
│ • MCP connection waiting             │
│ • User code blocked                  │
│ • Resources tied up                  │
│ • Cannot cancel or interrupt         │
└─────────────────────────────────────┘
```

### Proposed (Efficient)
```
Tool 1: taey_send_message (2s)      Tool 2: taey_wait_for_response (300s)
┌──────────────────────────┐         ┌──────────────────────────┐
│ • Execute send           │         │ • Poll page periodically  │
│ • Return immediately     │         │ • Report progress        │
│ • Release resources      │         │ • Extract when complete   │
│ • Unblock user code      │         │ • Log results             │
│ • Enable other tools     │         │ • Return to user         │
│ • High responsiveness    │         │ • Efficient polling      │
└──────────────────────────┘         └──────────────────────────┘
      ↓                                     ↓
  User can do other                   User gets response
  operations while                    with confidence metrics
  waiting for response                and timing info
```

---

## Timeout Configuration Comparison

```
SDK/Implementation    | Default Timeout | Configurable | Max Value
----------------------|-----------------|--------------|----------
TypeScript SDK        | 60s             | No           | 60s (hard)
Python SDK            | 30s             | Per-request  | No limit
LM Studio             | 30-60s          | No           | 60s
Claude Desktop        | 60s             | Global       | 600s+
Anthropic API (HTTP)  | 120s            | Per-request  | No limit
Temporal Workflows    | Custom          | Per-workflow | No limit
```

### Our Configuration Path
```
Default TypeScript: 60s
  ↓
Configured Global: 600s (10 min)
  ↓
Tool 1 (send): Uses 2-5s
Tool 2 (wait): Uses 300s+ (Extended Thinking)
  ↓
Result: 300s < 600s ✓ SUCCESS
```

---

## Summary

**Current Architecture**: Single blocking tool with MCP timeout conflict
- ✓ Simple design
- ✗ Fails for operations > 60s
- ✗ No recovery mechanism
- ✗ Poor user experience

**Proposed Architecture**: Two-tool async pattern with proper timeouts
- ✓ Scalable design
- ✓ Handles 10+ minute operations
- ✓ Clean separation of concerns
- ✓ Better user feedback
- ✓ Follows MCP best practices
