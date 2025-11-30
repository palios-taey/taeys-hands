# Message Sending Workflows Across Platforms

**Analysis Date**: 2025-11-30
**Codebase**: taey-hands (AI Family chat interface automation)

---

## Table of Contents

1. [Overview](#overview)
2. [Send Flow Architecture](#send-flow-architecture)
3. [Platform-Specific Selectors](#platform-specific-selectors)
4. [Response Detection Engine](#response-detection-engine)
5. [Atomic Actions](#atomic-actions)
6. [MCP Tool Integration](#mcp-tool-integration)
7. [For Rebuild: Key Insights](#for-rebuild-key-insights)

---

## Overview

**Message sending in taey-hands follows a multi-phase, verification-driven workflow:**

1. **Prepare Input** - Focus input field and bring browser to front
2. **Type Message** - Human-like typing with mixed content support (type + paste)
3. **Click Send** - Press Enter key to submit
4. **Wait for Response** (optional) - Use ResponseDetectionEngine for completion detection
5. **Extract Response** - Pull completed AI response text from DOM

**Key Design Principle**: Each action returns a screenshot for visual verification. No action trusts its own success without screenshot confirmation.

---

## Send Flow Architecture

### High-Level Flow (MCP Tool)

**File**: `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts` (lines 458-657)

```
taey_send_message(sessionId, message, attachments?, waitForResponse?)
    ↓
1. VALIDATION CHECKPOINT - Check if attachments required by plan
    ↓
2. Get ChatInterface from SessionManager
    ↓
3. Log sent message to Neo4j (user role)
    ↓
4. prepareInput() - Focus input field
    ↓
5. typeMessage(message) - Human-like typing
    ↓
6. clickSend() - Press Enter
    ↓
7. IF waitForResponse=true:
   → Create ResponseDetectionEngine(page, platform)
   → detector.detectCompletion()
   → Extract response text
   → Log response to Neo4j (assistant role)
    ↓
8. Return result with response text (if waited) or just success
```

### Atomic Action Flow (ChatInterface)

**File**: `/Users/REDACTED/taey-hands/src/interfaces/chat-interface.js`

Each atomic action is a separate, screenshot-verified step:

#### 1. prepareInput() - Lines 373-396
```javascript
async prepareInput(options = {}) {
  // Bring tab to front (CRITICAL for osascript typing)
  await this.page.bringToFront();

  // Focus the input
  const input = await this.page.waitForSelector(this.selectors.chatInput, { timeout: 10000 });
  await input.click();

  // Capture screenshot
  await this.screenshot(screenshotPath);

  return { screenshot, automationCompleted: true };
}
```

**⚠️ UNVERIFIED ACTION**: Input focus MUST be confirmed via screenshot (look for cursor visible).

#### 2. typeMessage(message, options) - Lines 411-485
```javascript
async typeMessage(message, options = {}) {
  const useHumanInput = options.humanLike !== false;

  if (useHumanInput) {
    // CRITICAL: Bring tab to front again before typing
    await this.page.bringToFront();
    await this.page.waitForTimeout(200);

    // Focus browser window (using xdotool windowraise + windowfocus)
    await this.bridge.focusApp(this._getBrowserName());

    // CRITICAL: Click input with screen coordinates (not Playwright)
    // This ensures X11 focus is set correctly for xdotool typing
    const input = await this.page.waitForSelector(this.selectors.chatInput);
    const box = await input.boundingBox();
    if (box) {
      // Convert viewport coords to screen coords
      const windowInfo = await this.page.evaluate(() => ({
        screenX: window.screenX,
        screenY: window.screenY,
        outerHeight: window.outerHeight,
        innerHeight: window.innerHeight,
        outerWidth: window.outerWidth,
        innerWidth: window.innerWidth
      }));

      const chromeHeight = windowInfo.outerHeight - windowInfo.innerHeight;
      const chromeWidth = windowInfo.outerWidth - windowInfo.innerWidth;
      const screenX = windowInfo.screenX + (chromeWidth / 2) + box.x + (box.width / 2);
      const screenY = windowInfo.screenY + chromeHeight + box.y + (box.height / 2);

      await this.bridge.clickAt(clickX, clickY);
    }

    // Use mixed content typing (type + paste) for AI quotes
    if (options.mixedContent !== false) {
      await this.bridge.typeWithMixedContent(message);
    } else {
      await this.bridge.safeTypeLong(message);
    }
  } else {
    // Direct injection (faster but detectable)
    await input.fill(message);
  }

  // Capture screenshot
  await this.screenshot(screenshotPath);

  return { screenshot, automationCompleted: true };
}
```

**Key Features**:
- **Human-like typing**: Uses `platform-bridge` (xdotool on Linux, osascript on macOS)
- **Mixed content mode**: Combines typing + pasting to handle long AI-generated text naturally
- **Screen coordinates**: Converts Playwright viewport coords to X11 screen coords for xdotool
- **Focus validation**: Uses `safeTypeLong()` which re-checks Chrome focus during long messages

**⚠️ UNVERIFIED ACTION**: Text in input MUST be confirmed via screenshot (look for message visible).

#### 3. clickSend() - Lines 560-579
```javascript
async clickSend(options = {}) {
  // Send via Enter key
  await this.page.waitForTimeout(300);
  await this.bridge.pressKey('return');

  // Capture screenshot after send
  await this.page.waitForTimeout(1000);
  await this.screenshot(screenshotPath);

  return { screenshot, automationCompleted: true };
}
```

**Note**: Uses Enter key instead of clicking send button selector. More reliable across platforms.

**⚠️ UNVERIFIED ACTION**: Message submission MUST be confirmed via screenshot (input cleared, message appears).

#### 4. waitForResponse(timeout, options) - Lines 679-770
```javascript
async waitForResponse(timeout = 600000, options = {}) {
  const fibonacci = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55];
  const screenshotIntervals = new Set([0, 2, 5, 13, 34, 55]);

  let lastContent = '';
  let stableCount = 0;
  const stabilityRequired = 2; // 2 identical content reads = done

  // Get initial content to detect when new response appears
  const initialContent = await this.getLatestResponse();

  // Take screenshot at t=0
  if (takeScreenshots) {
    await this.screenshot(`${screenshotDir}/taey-${this.name}-${sessionId}-t0.png`);
  }

  while (Date.now() - startTime < timeout) {
    const content = await this.getLatestResponse();

    // Check if content is new and stable
    if (content && content !== initialContent && content.length > 0) {
      if (content === lastContent) {
        stableCount++;

        if (stableCount >= stabilityRequired) {
          // Final screenshot on completion
          if (takeScreenshots) {
            await this.screenshot(`${screenshotDir}/taey-${this.name}-${sessionId}-complete.png`);
          }
          return content;
        }
      } else {
        stableCount = 0;
        lastContent = content;
      }
    }

    // Fibonacci wait with screenshot capture at intervals
    let waitSeconds;
    if (stableCount > 0) {
      waitSeconds = 2; // Fast polling for confirmation
    } else if (fibIndex < 3) {
      waitSeconds = 1; // First 3 checks at 1s
    } else {
      waitSeconds = fibonacci[Math.min(fibIndex, fibonacci.length - 1)];
    }

    await this.page.waitForTimeout(waitSeconds * 1000);

    // Take screenshot at Fibonacci intervals
    if (takeScreenshots && screenshotIntervals.has(totalElapsed)) {
      await this.screenshot(`${screenshotDir}/taey-${this.name}-${sessionId}-t${totalElapsed}s.png`);
    }
  }

  // Timeout screenshot for debugging
  if (takeScreenshots) {
    await this.screenshot(`${screenshotDir}/taey-${this.name}-${sessionId}-timeout.png`);
  }

  return content;
}
```

**Fibonacci Polling Strategy**:
- Starts with 1s intervals (fast for quick responses)
- Expands to 2s, 3s, 5s, 8s, 13s, 21s, 34s, 55s for longer responses
- Takes screenshots at key intervals: 0s, 2s, 5s, 13s, 34s, 55s
- Switches to 2s fast polling once stability detected

**Stability Detection**:
- Requires 2 consecutive identical content reads
- Compares to initial content to detect new responses
- Prevents false positives from partial responses

#### 5. getLatestResponse() - Lines 792-798
```javascript
async getLatestResponse() {
  const containers = await this.page.$$(this.selectors.responseContainer);
  if (containers.length === 0) return '';

  const lastContainer = containers[containers.length - 1];
  return await lastContainer.textContent();
}
```

**Note**: Perplexity overrides this method (lines 2030-2049) to target parent prose container instead of child elements.

---

## Platform-Specific Selectors

### Claude (claude.ai)

**File**: Lines 852-871

```javascript
selectors: {
  chatInput: '[contenteditable="true"]',
  sendButton: 'button[type="submit"]',
  responseContainer: 'div.grid.standard-markdown:has(> .font-claude-response-body)',
  newChatButton: 'button[aria-label="New chat"]',
  thinkingIndicator: '[class*="thinking"], [class*="loading"]',
  toolsMenuButton: '#input-tools-menu-trigger, [data-testid="input-menu-tools"]',
  researchToggle: '[data-testid*="research"], button:has-text("Research")',
  fileInput: 'input[type="file"]',
  attachmentButton: 'button[aria-label*="Attach"], button[data-testid*="attach"]'
}
```

**Special Behavior**:
- Uses contenteditable div instead of textarea
- Has Extended Thinking mode (detected via thinkingIndicator)
- waitForResponse() checks for thinking indicator first (lines 1105-1125)

**Model Selection**: Lines 885-922
- Dropdown: `[data-testid="model-selector-dropdown"]`
- Models: "Opus 4.5", "Sonnet 4", "Haiku 4"
- Menu item: `div[role="menuitem"]:has-text("${modelName}")`

### ChatGPT (chatgpt.com)

**File**: Lines 1190-1207

```javascript
selectors: {
  chatInput: '#prompt-textarea',
  sendButton: 'button[data-testid="send-button"]',
  responseContainer: '[data-message-author-role="assistant"]',
  newChatButton: 'nav button:first-child',
  thinkingIndicator: '.result-thinking, [class*="thinking"]',
  fileInput: 'input[type="file"]',
  attachmentButton: 'button[aria-label*="Attach"], button[data-testid*="attach"]'
}
```

**Special Behavior**:
- Uses standard textarea with ID
- Model selection disabled (lines 1349-1370) - always uses Auto mode
- Use setMode() for "Deep research" instead of model selection

**Mode Selection**: Lines 1380-1418
- Button: `[data-testid="composer-plus-btn"]`
- Modes: "Deep research", "Agent mode", "Web search", "GitHub"
- Menu item: `text="${modeName}"`

### Gemini (gemini.google.com)

**File**: Lines 1424-1440

```javascript
selectors: {
  chatInput: '.ql-editor[contenteditable="true"], [aria-label="Enter a prompt here"]',
  sendButton: 'button[aria-label="Send message"]',
  responseContainer: 'message-content .markdown',
  newChatButton: 'button[aria-label="New chat"]',
  fileInput: 'input[type="file"]',
  attachmentButton: 'button[aria-label*="Upload"], button[aria-label*="Add"]'
}
```

**Special Behavior**:
- Uses Quill editor (.ql-editor contenteditable)
- Has promotional overlays that block input - dismissOverlays() required (lines 1453-1500)
- Overrides prepareInput() to use xdotool click to bypass overlays (lines 1506-1560)
- waitForResponse() detects and clicks "Start research" button for Deep Research (lines 1822-1866)

**Overlay Dismissal Strategies**:
1. Click close button: `button[aria-label="Close"]`, `.cdk-overlay-backdrop`, etc.
2. Press Escape via xdotool (more reliable)
3. Click empty area at (50, 50)

**Model Selection**: Lines 1664-1701
- Dropdown: `[data-test-id="bard-mode-menu-button"]`
- Models: "Thinking with 3 Pro", "Thinking"
- Menu item: `button[mat-menu-item]:has-text("${modelName}")`

**Mode Selection**: Lines 1711-1748
- Drawer: `button.toolbox-drawer-button`
- Modes: "Deep Research", "Deep Think"
- Menu item: `button[mat-list-item]:has-text("${modeName}")`

**Deep Research Auto-Start**: Lines 1822-1866
```javascript
// Wait for Start Research button
const startResearchButton = await this.page.waitForSelector(
  'button[data-test-id="confirm-button"][aria-label="Start research"]',
  { timeout: 10000, state: 'attached' }
);

// Force-enable button if disabled
await this.page.evaluate(() => {
  const button = document.querySelector('button[data-test-id="confirm-button"]');
  if (button && button.disabled) {
    button.disabled = false;
    button.classList.remove('mat-mdc-button-disabled');
    button.style.pointerEvents = 'auto';
  }
});

await startResearchButton.click();
```

### Grok (grok.com)

**File**: Lines 1872-1888

```javascript
selectors: {
  chatInput: 'textarea, [contenteditable="true"]',
  sendButton: 'button[type="submit"], button[aria-label*="send" i]',
  responseContainer: 'div.response-content-markdown',
  newChatButton: 'button[aria-label*="new" i], a[href="/"]',
  fileInput: 'input[type="file"]',
  attachmentButton: 'button[aria-label*="Attach"], button[aria-label*="upload" i]'
}
```

**Special Behavior**:
- Flexible input (textarea OR contenteditable)
- Case-insensitive aria-label matching (`i` flag)

**Model Selection**: Lines 1947-1987
- Dropdown: `#model-select-trigger` (clicked via JavaScript to bypass visibility checks)
- Models: "Grok 4.1", "Grok 4.1 Thinking", "Grok 4 Heavy"
- Menu item: Flexible matching with multiple role selectors

### Perplexity (perplexity.ai)

**File**: Lines 1993-2009

```javascript
selectors: {
  chatInput: '#ask-input, [data-lexical-editor="true"]',
  sendButton: 'button[aria-label*="Submit"], button[type="submit"]',
  responseContainer: '[class*="prose"], [class*="answer"]',
  newChatButton: 'a[href="/"], button[aria-label*="New"]',
  fileInput: 'input[type="file"]',
  attachmentButton: 'button[aria-label*="Attach"], button[aria-label*="Upload"]'
}
```

**Special Behavior**:
- Uses Lexical editor framework
- Overrides getLatestResponse() to target parent prose container (lines 2030-2049)
- Pro Search mode: `button[value="research"]`

**Response Extraction Override**: Lines 2030-2049
```javascript
async getLatestResponse() {
  // More specific selector for the main answer container
  const answerSelector = 'div.prose.dark\\:prose-invert.inline.leading-relaxed, div[class*="prose"][class*="inline"]';

  const containers = await this.page.$$(answerSelector);
  if (containers.length === 0) return '';

  const lastContainer = containers[containers.length - 1];
  const text = await lastContainer.textContent();

  return text;
}
```

**Why Override Needed**: Base selector `[class*="prose"]` matches ALL child elements (p, h1, h2, ul), returning only last paragraph. Override targets parent container to get full response.

**Mode Selection**: Lines 2159-2184
- Modes: "search", "research", "studio" (Labs)
- Button: `button[role="radio"][value="${modeValue}"]`

---

## Response Detection Engine

**File**: `/Users/REDACTED/taey-hands/src/core/response-detection.js` (535 lines)

### Overview

Multi-strategy detection engine that watches for AI response completion using:

1. **Streaming Class Removal** (95% confidence) - Claude, ChatGPT
2. **Button Appearance** (90% confidence) - ChatGPT Regenerate button
3. **Content Stability** (85% confidence) - All platforms fallback
4. **Labs Completion** (92% confidence) - Perplexity Labs "Working..." indicator

### Detection Strategies by Platform

**Lines 15-91**: Platform-specific detection configurations

```javascript
const DETECTION_STRATEGIES = {
  claude: {
    selectors: {
      container: '[data-test-render-count], [class*="font-claude-message"], .prose',
      streamingClass: 'result-streaming',
      thinkingIndicator: '[aria-label*="thinking"], [class*="thinking"]',
      completionButtons: 'button[aria-label*="Copy"], button[aria-label*="Retry"]'
    },
    detection: {
      primary: 'streamingClass',
      secondary: 'buttonAppearance',
      fallback: 'stabilityCheck',
      timeout: 300000 // 5 minutes for Extended Thinking
    }
  },

  chatgpt: {
    selectors: {
      container: '[data-message-author-role="assistant"]',
      streamingClass: 'result-streaming',
      regenerateButton: 'button[data-testid="regenerate-thread-button"]',
      completionButtons: 'button[data-testid="regenerate-thread-button"], button[aria-label*="Copy"]'
    },
    detection: {
      primary: 'buttonAppearance', // Regenerate button appears when done
      secondary: 'stabilityCheck',
      fallback: 'stabilityCheck',
      timeout: 180000 // 3 minutes for o1 reasoning
    }
  },

  gemini: {
    selectors: {
      container: 'p[data-path-to-node]',
      deepResearchIndicator: '[aria-label*="researching"]',
      progressBar: '.progress-linear'
    },
    detection: {
      primary: 'stabilityCheck', // Deep Research needs stability
      fallback: 'stabilityCheck',
      timeout: 3600000 // 60 minutes for Deep Research
    }
  },

  perplexity: {
    selectors: {
      container: '.prose',
      labsProgressIndicator: '[data-testid="labs-progress"], .labs-working-indicator'
    },
    detection: {
      primary: 'stabilityCheck', // More reliable for both Labs and Research
      fallback: 'stabilityCheck',
      timeout: 1800000 // 30 minutes for Labs
    }
  },

  grok: {
    selectors: {
      container: 'div.response-content-markdown',
      streamingIndicator: '.streaming'
    },
    detection: {
      primary: 'stabilityCheck',
      fallback: 'stabilityCheck',
      timeout: 60000 // 1 minute standard
    }
  }
};
```

### Strategy 1: Streaming Class Removal (Lines 124-201)

**Best for**: Claude, ChatGPT (when they add streaming class)

```javascript
async detectViaStreamingClass() {
  // First check if already complete (no streaming class)
  const containers = await this.page.$$(containerSelector);
  const lastContainer = containers[containers.length - 1];
  const hasStreamingClass = await lastContainer.evaluate(
    (el, cls) => el.classList.contains(cls),
    streamingClass
  );

  if (!hasStreamingClass) {
    // Already complete
    return { method: 'streamingClass', confidence: 0.95, content, note: 'Already complete' };
  }

  // Poll for class removal
  const pollInterval = setInterval(async () => {
    const hasStreamingClass = await lastContainer.evaluate(...);
    if (!hasStreamingClass) {
      return { method: 'streamingClass', confidence: 0.95, content };
    }
  }, this.options.pollInterval); // 500ms
}
```

**Confidence**: 95% - Very reliable when streaming class exists

### Strategy 2: Button Appearance (Lines 299-357)

**Best for**: ChatGPT (Regenerate button), Claude (Copy/Retry buttons)

```javascript
async detectViaButtonAppearance() {
  const checkButton = async () => {
    const buttons = await this.page.$$(buttonSelector);
    for (const button of buttons) {
      const isVisible = await button.evaluate(el => el.offsetParent !== null);
      if (isVisible) {
        const content = await this.getLatestContent();
        return { method: 'buttonAppearance', confidence: 0.90, content };
      }
    }
    return false;
  };

  // Check immediately (handle already-complete responses)
  const immediateResult = await checkButton();
  if (immediateResult) return immediateResult;

  // Poll for button appearance
  const pollInterval = setInterval(checkButton, 500);

  // Timeout → fallback to stability check
  setTimeout(() => {
    this.detectViaStability().then(resolve).catch(reject);
  }, 30000);
}
```

**Confidence**: 90% - Reliable completion indicator

### Strategy 3: Content Stability (Lines 207-292)

**Best for**: All platforms (fallback), Gemini, Perplexity, Grok (primary)

```javascript
async detectViaStability() {
  const stabilityWindow = 2000; // 2s no changes = stable
  let lastContent = '';
  let lastChangeTime = Date.now();

  const checkStability = async () => {
    const containers = await this.page.$$(containerSelector);
    const lastContainer = containers[containers.length - 1];
    const currentContent = await lastContainer.textContent();
    const now = Date.now();

    if (currentContent !== lastContent) {
      // Content changed - reset timer
      lastContent = currentContent;
      lastChangeTime = now;
      return false;
    }

    // Check if stable long enough
    const stableTime = now - lastChangeTime;
    if (stableTime >= stabilityWindow && currentContent.length > 0) {
      return { method: 'stability', confidence: 0.85, content: currentContent, stableTime };
    }

    return false;
  };

  // Poll every 500ms
  const pollInterval = setInterval(checkStability, 500);

  // Absolute timeout
  setTimeout(() => {
    // Return whatever we have
    if (finalContent && finalContent.length > 0) {
      resolve({ method: 'timeout', confidence: 0.5, content: finalContent });
    }
  }, this.config.detection.timeout);
}
```

**Confidence**: 85% - Good reliability, works everywhere

### Strategy 4: Labs Completion (Lines 364-441)

**Best for**: Perplexity Labs mode

```javascript
async detectViaLabsCompletion() {
  let wasWorking = false;

  const checkLabs = async () => {
    // Look for "Working..." text or indicator
    const workingText = await this.page.$('text=Working');
    const isWorking = workingText !== null;

    if (isWorking && !wasWorking) {
      wasWorking = true;
    }

    if (wasWorking && !isWorking) {
      // Was working, now done
      return { method: 'labsCompletion', confidence: 0.92, content };
    }
  };

  // Check immediately for already-complete response
  const workingText = await this.page.$('text=Working');
  if (!workingText) {
    const content = await getContent();
    if (content && content.length > 100) {
      return { method: 'labsCompletion', confidence: 0.88, content, note: 'Already complete' };
    }
  }

  // Poll every 1s for Labs
  const pollInterval = setInterval(checkLabs, 1000);
}
```

**Confidence**: 92% (active), 88% (already complete)

### Public API: detectCompletion() (Lines 447-511)

**Automatic Strategy Selection**:

```javascript
async detectCompletion() {
  this.detectionStartTime = Date.now();

  try {
    let result;

    // Select strategy based on platform config
    switch (this.config.detection.primary) {
      case 'streamingClass':
        result = await this.detectViaStreamingClass();
        break;
      case 'buttonAppearance':
        result = await this.detectViaButtonAppearance();
        break;
      case 'labsCompletion':
        result = await this.detectViaLabsCompletion();
        break;
      case 'stabilityCheck':
      default:
        result = await this.detectViaStability();
        break;
    }

    return result;

  } catch (primaryError) {
    // Try secondary strategy
    if (this.config.detection.secondary) {
      switch (this.config.detection.secondary) {
        case 'buttonAppearance':
          return await this.detectViaButtonAppearance();
        case 'streamingClass':
          return await this.detectViaStreamingClass();
        case 'stabilityCheck':
        default:
          return await this.detectViaStability();
      }
    }

    // Try fallback (stability check)
    if (this.config.detection.fallback === 'stabilityCheck') {
      return await this.detectViaStability();
    }

    throw primaryError;
  }
}
```

**Fallback Chain**: Primary → Secondary → Fallback (stability)

### Usage in MCP Server (Lines 576-613 in server-v2.ts)

```javascript
if (waitForResponse) {
  const detector = new ResponseDetectionEngine(
    chatInterface.page,
    session?.interfaceType || interfaceName,
    { debug: true }
  );

  const detectionResult = await detector.detectCompletion();
  const responseText = detectionResult.content;

  console.error(`[MCP] Response detected (${detectionResult.method}, ${detectionResult.confidence * 100}% confidence) in ${detectionResult.detectionTime}ms`);

  // Log to Neo4j with detection metadata
  await conversationStore.addMessage(sessionId, {
    role: 'assistant',
    content: responseText,
    platform: interfaceName,
    timestamp,
    metadata: {
      detectionMethod: detectionResult.method,
      detectionConfidence: detectionResult.confidence,
      detectionTime: detectionResult.detectionTime,
      contentLength: responseText.length
    }
  });

  return { success: true, responseText, detectionMethod, detectionConfidence };
}
```

---

## Atomic Actions

### Philosophy: Unverified Actions

**Every atomic action returns a screenshot but does NOT verify success itself.**

From documentation (lines 243-280 in chat-interface.js):

```
⚠️ UNVERIFIED ACTION - UI state change MUST be confirmed via screenshot
This method only confirms automation steps completed without errors.
It does NOT verify the UI actually changed state (button toggled, mode enabled).
ALWAYS check the returned screenshot to verify the intended effect occurred.
```

### Available Atomic Actions

**File**: `/Users/REDACTED/taey-hands/src/interfaces/chat-interface.js`

1. **prepareInput(options)** - Lines 373-396
   - Focus input field
   - Returns: `{ screenshot, automationCompleted: true }`
   - Verify: Cursor visible in input

2. **typeMessage(message, options)** - Lines 411-485
   - Type message with human-like timing
   - Options: `humanLike`, `mixedContent`, `sessionId`, `screenshotPath`
   - Returns: `{ screenshot, automationCompleted: true }`
   - Verify: Message text visible in input

3. **pasteMessage(message, options)** - Lines 501-546
   - Fast paste using typeFast (xclip bypass for VNC)
   - Returns: `{ screenshot, automationCompleted: true }`
   - Verify: Message text visible in input

4. **clickSend(options)** - Lines 560-579
   - Press Enter to submit
   - Returns: `{ screenshot, automationCompleted: true }`
   - Verify: Input cleared, message sent indicator

5. **attachFile(filePath, options)** - Lines 297-359 (base), overridden per platform
   - Open file dialog, navigate with Cmd+Shift+G (macOS) or Ctrl+L (Linux)
   - Returns: `{ screenshot, automationCompleted: true, filePath }`
   - Verify: File pill/preview visible in input area

6. **enableResearchMode(options)** - Lines 256-281
   - Toggle research/pro mode button
   - Returns: `{ screenshot, automationCompleted: true }`
   - Verify: Mode indicator changed

7. **selectModel(modelName, options)** - Platform-specific
   - Open model dropdown, click model
   - Returns: `{ screenshot, automationCompleted: true, modelName }`
   - Verify: Model name visible in UI

### Composite Actions (Legacy)

**sendMessage(message, options)** - Lines 586-671

**NOW DEPRECATED in favor of atomic actions**, but shows the systematic verification pattern:

```javascript
async sendMessage(message, options = {}) {
  // CHECKPOINT 1: Initial state
  await this.screenshot(`${sessionId}-01-initial.png`);

  // Focus input
  await input.click();

  // CHECKPOINT 2: After focus
  await this.screenshot(`${sessionId}-02-focused.png`);

  // Type message
  await this.bridge.typeWithMixedContent(message);

  // CHECKPOINT 3: After typing
  await this.screenshot(`${sessionId}-03-typed.png`);

  // Send
  await this.bridge.pressKey('return');

  // CHECKPOINT 4: After send
  await this.screenshot(`${sessionId}-04-sent.png`);

  // Wait for response
  if (waitForResponse) {
    const response = await this.waitForResponse(timeout, { sessionId });
    return { sent: true, response, screenshots: { initial, focused, typed, sent } };
  }
}
```

**Pattern**: Screenshot before/after each state change for debugging.

---

## MCP Tool Integration

### Tool: taey_send_message

**File**: `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts` (lines 103-132, 458-657)

**Input Schema**:
```typescript
{
  sessionId: string,      // Session ID from taey_connect
  message: string,        // Message text to send
  attachments?: string[], // Optional file paths
  waitForResponse?: boolean // Wait for AI response (default: false)
}
```

**Output Schema** (waitForResponse=true):
```typescript
{
  success: true,
  sessionId: string,
  message: "Message sent and response received",
  sentText: string,
  waitForResponse: true,
  responseText: string,
  responseLength: number,
  detectionMethod: string,     // "streamingClass" | "buttonAppearance" | "stability" | "labsCompletion"
  detectionConfidence: number, // 0.50 - 0.95
  detectionTime: number,       // milliseconds
  timestamp: string
}
```

**Output Schema** (waitForResponse=false):
```typescript
{
  success: true,
  sessionId: string,
  message: "Message sent successfully",
  sentText: string,
  waitForResponse: false
}
```

### Validation Checkpoints

**CRITICAL FEATURE**: Message sending requires validated plan before execution.

**Lines 466-546 in server-v2.ts**:

```typescript
// VALIDATION CHECKPOINT: Check if attachments required by plan
const attachmentRequirement = await validationStore.requiresAttachments(sessionId);

if (attachmentRequirement.required) {
  // Attachments specified in plan - MUST have attach_files validated
  const lastValidation = await validationStore.getLastValidation(sessionId);

  if (!lastValidation) {
    throw new Error(
      `Validation checkpoint failed: Draft plan requires ${attachmentRequirement.count} attachment(s).\n` +
      `No validation checkpoints found. You must:\n` +
      `1. Call taey_attach_files with files: ${JSON.stringify(attachmentRequirement.files)}\n` +
      `2. Review screenshot to confirm files are visible\n` +
      `3. Call taey_validate_step with step='attach_files' and validated=true`
    );
  }

  // Last validated step MUST be 'attach_files'
  if (lastValidation.step !== 'attach_files') {
    throw new Error(
      `Validation checkpoint failed: Draft plan requires ${attachmentRequirement.count} attachment(s).\n` +
      `Last validated step was '${lastValidation.step}'.\n` +
      `You MUST:\n` +
      `1. Call taey_attach_files with files: ${JSON.stringify(attachmentRequirement.files)}\n` +
      `2. Review screenshot to confirm files are visible\n` +
      `3. Call taey_validate_step with step='attach_files' and validated=true\n\n` +
      `You cannot skip attachment when the draft plan specifies files.`
    );
  }

  // Check attachment is validated (not pending)
  if (!lastValidation.validated) {
    throw new Error(
      `Validation checkpoint failed: Attachment step is pending validation (validated=false).\n` +
      `You must review the screenshot and call taey_validate_step with validated=true.`
    );
  }

  // Verify correct number of attachments
  const actualCount = lastValidation.actualAttachments?.length || 0;
  if (actualCount !== attachmentRequirement.count) {
    throw new Error(
      `Validation checkpoint failed: Plan required ${attachmentRequirement.count} file(s), ` +
      `but only ${actualCount} were attached.\n` +
      `Required files: ${JSON.stringify(attachmentRequirement.files)}\n` +
      `Actual files: ${JSON.stringify(lastValidation.actualAttachments || [])}`
    );
  }
}
```

**This prevents**:
1. Sending without attachments when plan requires them
2. Skipping attachment step entirely
3. Validating attachment step without actually attaching
4. Attaching wrong number of files

**For messages without attachments** (lines 518-546):
```typescript
const lastValidation = await validationStore.getLastValidation(sessionId);

if (!lastValidation) {
  throw new Error(
    `Validation checkpoint failed: No validation checkpoints found. ` +
    `You must validate the 'plan' step before sending a message.`
  );
}

if (!lastValidation.validated) {
  throw new Error(
    `Validation checkpoint failed: Step '${lastValidation.step}' is pending validation (validated=false). ` +
    `Call taey_validate_step with validated=true after reviewing screenshot.`
  );
}

const validSteps = ['plan', 'attach_files'];
if (!validSteps.includes(lastValidation.step)) {
  throw new Error(
    `Validation checkpoint failed: Last validated step was '${lastValidation.step}'. ` +
    `Must validate one of: ${validSteps.join(', ')} before sending.`
  );
}
```

### Neo4j Conversation Logging

**Lines 553-565, 596-612**:

```typescript
// Log sent message (user role)
await conversationStore.addMessage(sessionId, {
  role: 'user',
  content: message,
  platform: interfaceName,
  timestamp: new Date().toISOString(),
  attachments: attachments || [],
  metadata: { source: 'mcp_taey_send_message' }
});

// Log received response (assistant role)
if (waitForResponse) {
  await conversationStore.addMessage(sessionId, {
    role: 'assistant',
    content: responseText,
    platform: interfaceName,
    timestamp,
    metadata: {
      source: 'mcp_taey_send_message_auto_extract',
      detectionMethod: detectionResult.method,
      detectionConfidence: detectionResult.confidence,
      detectionTime: detectionResult.detectionTime,
      contentLength: responseText.length
    }
  });
}
```

**Schema**: Each message is a node in Neo4j with relationships to conversation.

---

## For Rebuild: Key Insights

### 1. Input Field Variations

**Platform-specific input types**:
- **Claude**: `contenteditable` div (`[contenteditable="true"]`)
- **ChatGPT**: `textarea` with ID (`#prompt-textarea`)
- **Gemini**: Quill editor (`contenteditable`) OR aria-label fallback
- **Grok**: Flexible (`textarea` OR `contenteditable`)
- **Perplexity**: Lexical editor (`[data-lexical-editor="true"]`) OR ID fallback

**Recommendation for rebuild**: Use multiple selector fallbacks with `||` operator:
```javascript
chatInput: 'textarea#main-input, [contenteditable="true"], [data-lexical-editor="true"], [aria-label*="prompt"]'
```

### 2. Send Button Strategies

**Current approach**: Press Enter key instead of clicking send button.

**Why this works better**:
1. Send button selectors change frequently
2. Enter key is more reliable across platforms
3. Handles disabled send buttons (typing enables them)
4. More human-like behavior

**For rebuild**: Continue using Enter key. Only fall back to button click if Enter doesn't work.

### 3. Response Detection Priorities

**By platform**:

| Platform   | Primary Strategy    | Why                                      | Timeout   |
|------------|---------------------|------------------------------------------|-----------|
| Claude     | Streaming Class     | Reliable class removal detection         | 5 min     |
| ChatGPT    | Button Appearance   | Regenerate button appears when done      | 3 min     |
| Gemini     | Content Stability   | Deep Research has no clear indicators    | 60 min    |
| Grok       | Content Stability   | Simple, no special indicators            | 1 min     |
| Perplexity | Content Stability   | Works for both Research and Labs         | 30 min    |

**For rebuild**: Always implement content stability as fallback. It works everywhere.

### 4. Human-Like Typing Requirements

**Critical components** (from typeMessage):

1. **Screen coordinate clicking**: Convert Playwright viewport coords to X11 screen coords
   ```javascript
   const chromeHeight = outerHeight - innerHeight;
   const screenX = windowX + (chromeWidth / 2) + boxX + (boxWidth / 2);
   const screenY = windowY + chromeHeight + boxY + (boxHeight / 2);
   ```

2. **Mixed content typing**: Combine typing + pasting for long AI-generated text
   ```javascript
   if (options.mixedContent !== false) {
     await this.bridge.typeWithMixedContent(message);
   } else {
     await this.bridge.safeTypeLong(message);
   }
   ```

3. **Focus validation**: Re-check browser focus during long messages
   - `safeTypeLong()` validates Chrome is focused every N characters
   - Prevents typing going to wrong window

**For rebuild**: Implement mixed typing (type some, paste some) to handle 1000+ char messages without taking forever.

### 5. Streaming vs Complete Responses

**Two detection modes**:

1. **Streaming detection**: Watch for class removal, button appearance
   - Fast (detects exact completion moment)
   - Requires platform-specific selectors
   - Best for: Claude, ChatGPT

2. **Stability detection**: Poll content, wait for 2s of no changes
   - Slower (2s delay after completion)
   - Works everywhere
   - Best for: Gemini, Grok, Perplexity

**For rebuild**: Use streaming detection as primary (95% confidence), stability as fallback (85% confidence).

### 6. Response Extraction Edge Cases

**Perplexity special case** (lines 2030-2049):

```javascript
// WRONG: Base selector matches ALL child elements
const containers = await this.page.$$('[class*="prose"]');
// Returns: [<p>, <h1>, <h2>, <ul>, <p>]
// Only gets last <p> text

// RIGHT: Target parent container specifically
const answerSelector = 'div.prose.dark\\:prose-invert.inline.leading-relaxed';
const containers = await this.page.$$(answerSelector);
// Returns: [<div class="prose ...">...</div>]
// Gets full response text
```

**For rebuild**: Always test response extraction with multi-paragraph responses. Look for parent container, not child elements.

### 7. Error Handling Strategy

**Current approach**: Fallback chain

```
Primary Strategy (95% confidence)
    ↓ (fails)
Secondary Strategy (90% confidence)
    ↓ (fails)
Fallback Strategy (85% confidence - stability)
    ↓ (timeout)
Return partial content (50% confidence)
```

**For rebuild**: Implement at least 2-level fallback. Never fail completely without returning something.

### 8. Screenshot-Driven Verification

**Pattern**: Every action returns screenshot path for visual verification.

**Why this matters**:
- Playwright's element checks don't guarantee visual state
- Overlays can block clicks without Playwright knowing
- User can debug by reviewing screenshots
- MCP tools require screenshot confirmation

**For rebuild**: Make screenshots mandatory for every state change. Store them in `/tmp` with timestamps.

### 9. Platform-Specific Quirks

**Gemini overlays** (lines 1453-1500):
- Promotional banners block input
- Must dismiss with Escape key or click outside
- Playwright click fails, xdotool click works

**Gemini Deep Research** (lines 1822-1866):
- "Start research" button appears after typing
- Button starts disabled, must force-enable
- Must click button to actually start research

**ChatGPT model selection** (lines 1349-1370):
- Model dropdown removed from UI
- All requests use "Auto" mode now
- Use setMode("Deep research") for reasoning

**For rebuild**: Test each platform individually. Don't assume UI patterns are consistent.

### 10. Message Queueing Not Needed

**Current implementation**: Serial execution, one message at a time.

**Why no queue needed**:
- SessionManager ensures one interface per session
- MCP tools are called sequentially by Claude Code
- Human-like typing takes time naturally
- Response detection blocks until complete

**For rebuild**: Don't implement message queue unless running multiple sessions to same platform concurrently.

### 11. Timeout Strategy

**Platform-specific timeouts**:
- Claude Extended Thinking: 5 min (300000ms)
- ChatGPT o1 Reasoning: 3 min (180000ms)
- Gemini Deep Research: 60 min (3600000ms)
- Perplexity Labs: 30 min (1800000ms)
- Grok: 1 min (60000ms)

**For rebuild**: Make timeout configurable per platform and mode. Deep Research needs WAY longer timeouts.

### 12. Reliability Strategy - Multi-Selector Approach

**Pattern**: Use multiple selectors with fallbacks

```javascript
// Claude send button
sendButton: 'button[type="submit"]',

// Grok send button (flexible)
sendButton: 'button[type="submit"], button[aria-label*="send" i]',

// Gemini input (multiple options)
chatInput: '.ql-editor[contenteditable="true"], [aria-label="Enter a prompt here"]',
```

**For rebuild**: Always provide 2-3 selector options. UIs change, selectors break.

---

## Summary: Reliable Message Sending

### Core Workflow

```
1. prepareInput() → Screenshot (verify cursor in input)
2. typeMessage() → Screenshot (verify text in input)
3. clickSend() → Screenshot (verify input cleared, sending)
4. waitForResponse() → Screenshots at intervals (verify completion)
5. extractResponse() → Return text content
```

### Platform Differences Summary

| Platform   | Input Type       | Send Method | Response Detection | Special Notes                          |
|------------|------------------|-------------|--------------------|----------------------------------------|
| Claude     | contenteditable  | Enter key   | Streaming class    | Extended Thinking (5 min timeout)      |
| ChatGPT    | textarea         | Enter key   | Regenerate button  | Model selection disabled, use setMode  |
| Gemini     | Quill editor     | Enter key   | Content stability  | Dismiss overlays, auto-click "Start"   |
| Grok       | Flexible         | Enter key   | Content stability  | Case-insensitive selectors             |
| Perplexity | Lexical editor   | Enter key   | Content stability  | Override getLatestResponse for parent  |

### Key Takeaways for Rebuild

1. **Screenshot everything** - Visual verification is mandatory
2. **Use Enter key** - More reliable than clicking send button
3. **Implement stability fallback** - Works on all platforms
4. **Handle overlays** - Gemini requires special treatment
5. **Mixed content typing** - Essential for long AI messages
6. **Screen coordinates** - Required for reliable clicking on Linux
7. **Multi-selector fallbacks** - UIs change, selectors break
8. **Platform timeouts** - Deep Research needs 60 min, quick responses need 1 min
9. **Response extraction testing** - Test with multi-paragraph responses
10. **Validation checkpoints** - Prevent skipping required steps

---

## Document Generation Info

- **Generated by**: Claude Code (Sonnet 4.5)
- **Date**: 2025-11-30
- **Source files analyzed**:
  - `/Users/REDACTED/taey-hands/src/interfaces/chat-interface.js` (2278 lines)
  - `/Users/REDACTED/taey-hands/src/core/response-detection.js` (535 lines)
  - `/Users/REDACTED/taey-hands/mcp_server/server-v2.ts` (partial)
- **Total lines analyzed**: 3000+
- **Platforms covered**: Claude, ChatGPT, Gemini, Grok, Perplexity
