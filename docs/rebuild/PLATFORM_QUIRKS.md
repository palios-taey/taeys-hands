# Platform Quirks and Special Handling

**Date**: 2025-11-30
**Purpose**: Document platform-specific behaviors that require special handling in browser automation

## Executive Summary

Each AI chat platform has unique UI behaviors that require specialized handling. These quirks fall into categories:

1. **UI Blocking Issues** - Elements that prevent standard automation
2. **Button State Manipulation** - Disabled buttons that must be force-enabled
3. **Selector Fragility** - Platform-specific DOM structures
4. **Modal/Menu Navigation** - Multi-step workflows for common actions
5. **Response Detection** - Different completion indicators

---

## 1. GROK (grok.com)

### Model Selection Quirk

**Issue**: Model selector button (`#model-select-trigger`) is often not visible/clickable via Playwright's standard click().

**Why**: Grok's UI uses visibility tricks or overlays that cause Playwright to reject the click as "not visible".

**Solution**: Use JavaScript evaluate to bypass visibility checks:

```javascript
await this.page.waitForSelector('#model-select-trigger', { state: 'attached', timeout: 5000 });
await this.page.evaluate(() => {
  const button = document.querySelector('#model-select-trigger');
  if (button) button.click();
});
await this.page.waitForTimeout(1000); // Wait for menu to fully render
```

**Code Location**: `src/interfaces/chat-interface.js:1957-1963`

### Model Options

- Grok 4.1 (default)
- Grok 4.1 Thinking
- Grok 4 Heavy

### File Attachment

**Method**: Two-step process
1. Click attach button: `button[aria-label="Attach"]`
2. Click menu item: `div[role="menuitem"]:has-text("Upload a file")`
3. Use standard macOS file picker navigation (Cmd+Shift+G)

### Special Methods

- `selectModel(modelName, options)` - Uses JavaScript click bypass
- Standard `attachFile()` with menu navigation

---

## 2. CLAUDE (claude.ai)

### Model Selection

**Selector**: `[data-testid="model-selector-dropdown"]`

**Method**: Standard dropdown menu
- Click selector button
- Find menu item: `div[role="menuitem"]:has-text("${modelName}")`
- Click item

**Models Available**:
- Opus 4.5
- Sonnet 4
- Haiku 4

### Extended Thinking Mode

**Selector**: Tools menu → Research toggle

**Method**:
1. Click tools menu: `#input-tools-menu-trigger`
2. Find Research button: `button:has-text("Research")`
3. Check toggle state: `input[role="switch"]`
4. Toggle if needed

**Implementation**: `setResearchMode(enabled)` - Can enable OR disable

**Response Detection**: Waits for thinking indicator to appear/disappear before extracting response

### File Attachment

**Unique Behavior**: Uses + menu instead of direct attach button

**Method**:
1. Click + menu: `[data-testid="input-menu-plus"]`
2. Click "Upload a file" menu item
3. Use macOS file picker navigation

### Download Artifact

**Simplest Platform**: Single-step download

**Method**:
1. Wait for Download button: `button[aria-label="Download"]`
2. Click and handle download event
3. Save to specified path

**Unique**: No export menu or format selection - just downloads

---

## 3. GEMINI (gemini.google.com)

### THE BIG QUIRK: Promotional Overlays

**Issue**: Gemini frequently shows promotional overlays/banners that block input clicks.

**Why**: Material Design overlays (`.cdk-overlay-container`) prevent Playwright clicks from reaching the input.

**Solution**: Multi-approach dismissal in `dismissOverlays()`:

```javascript
async dismissOverlays() {
  // Approach 1: Click close buttons
  const closeSelectors = [
    'button[aria-label="Close"]',
    'button[aria-label="Dismiss"]',
    '.cdk-overlay-container button mat-icon[fonticon="close"]',
    '.cdk-overlay-backdrop',
    '[aria-label="Close promotional banner"]'
  ];

  // Approach 2: Press Escape via xdotool (more reliable)
  await this.bridge.runCommand('xdotool key Escape');

  // Approach 3: Click empty area
  await this.bridge.clickAt(50, 50);
}
```

**When**: Called in `prepareInput()` before every input focus

**Code Location**: `src/interfaces/chat-interface.js:1453-1500`

### Deep Research Button - DISABLED STATE QUIRK

**THE CRITICAL ISSUE**: The "Start research" button is programmatically disabled even when visually clickable.

**Selector**: `button[data-test-id="confirm-button"][aria-label="Start research"]`

**Problem**:
- `button.disabled = true`
- `pointer-events: none`
- `class: 'mat-mdc-button-disabled'`

**Solution**: Force-enable before clicking:

```javascript
await this.page.evaluate(() => {
  const button = document.querySelector('button[data-test-id="confirm-button"]');
  if (button && button.disabled) {
    console.log('  [Gemini]: Button was disabled, force-enabling...');
    button.disabled = false;
    button.classList.remove('mat-mdc-button-disabled');
    button.style.pointerEvents = 'auto';
  }
});
await this.page.waitForTimeout(500);
await startResearchButton.click();
```

**When**: Automatically handled in `waitForResponse()` override

**Code Location**: `src/interfaces/chat-interface.js:1841-1849`

**Git Commit**: `6b86f79` - "Fix Gemini Start research button - force-enable if disabled"

### Model Selection

**Selector**: `[data-test-id="bard-mode-menu-button"]`

**Models**:
- Thinking with 3 Pro
- Thinking

**Menu Items**: `button[mat-menu-item]:has-text("${modelName}")`

### Modes (Deep Research vs Deep Think)

**Selector**: Toolbox drawer button → `button[mat-list-item]:has-text("${modeName}")`

**Available Modes**:
- Deep Research - Multi-source investigation
- Deep Think - Logic/math reasoning

**Implementation**: `setMode(modeName, options)`

### Download Artifact

**Multi-step Process**:
1. Click asset card: `[data-testid="asset-card-open-button"]`
2. Click Export button
3. Click format: "Download as Markdown" or "Download as HTML"
4. Handle download event

### Input Focus Bypass

**Override**: `prepareInput()` uses xdotool click instead of Playwright click to bypass overlays

```javascript
// Get screen coordinates and click with xdotool
const screenX = windowInfo.screenX + box.x + (box.width / 2);
const screenY = windowInfo.screenY + chromeHeight + box.y + (box.height / 2);
await this.bridge.clickAt(Math.round(screenX), Math.round(screenY));
```

---

## 4. CHATGPT (chatgpt.com)

### Model Selection - DISABLED

**Status**: Model selection currently disabled (returns Auto mode always)

**Why**: ChatGPT UI changed, model selection became unreliable

**Workaround**: Use mode selection for thinking/research capabilities

**Code**:
```javascript
console.log(`[chatgpt] selectModel(${modelName}) - DISABLED`);
console.log(`  ChatGPT model selection disabled - using Auto mode`);
console.log(`  For thinking: use Deep Research mode via setMode() instead`);
```

**Legacy Models**: If re-enabled, `isLegacy=true` parameter would access Legacy submenu for GPT-4o

### Mode Selection (Preferred Method)

**Selector**: `[data-testid="composer-plus-btn"]` → Mode menu

**Available Modes**:
- Auto (default)
- Deep research - Autonomous investigation
- Agent mode
- Web search
- GitHub

**Implementation**: `setMode(modeName, options)`

**Method**:
1. Click + button: `[data-testid="composer-plus-btn"]`
2. Wait for menu to render (800ms)
3. Click mode: `text="${modeName}"`

### File Attachment

**Method**: + menu navigation
1. Click + button: `[data-testid="composer-plus-btn"]`
2. Click "Add photos & files" menu item
3. Use macOS file picker

### Download Artifact

**Not Supported**: ChatGPT does not support artifact downloads (no downloadArtifact method)

---

## 5. PERPLEXITY (perplexity.ai)

### Pro Search Mode

**Selector**: `button[value="research"]`

**Implementation**: `enableResearchMode(options)` - Simple button click, no toggle state

**Unique**: Always enables (no disable option)

### Response Extraction - SPECIAL SELECTOR

**Issue**: Base selector `[class*="prose"]` matches all child elements (p, h1, h2, ul) instead of parent container.

**Problem**: Only extracts last paragraph instead of full response.

**Solution**: Target parent container specifically:

```javascript
const answerSelector = 'div.prose.dark\\:prose-invert.inline.leading-relaxed, div[class*="prose"][class*="inline"]';
const containers = await this.page.$$(answerSelector);
const lastContainer = containers[containers.length - 1];
const text = await lastContainer.textContent();
```

**Code Location**: `src/interfaces/chat-interface.js:2030-2049`

### Mode Selection

**Selector**: `button[role="radio"][value="${modeValue}"]`

**Available Modes**:
- search (default)
- research (Pro Search)
- studio (Labs)

**Implementation**: `setMode(modeValue, options)`

### File Attachment

**Method**: Two-step menu
1. Click attach button: `button[data-testid="attach-files-button"]`
2. Click "Local files" menu item: `div[role="menuitem"]:has-text("Local files")`
3. Use macOS file picker

### Download Artifact

**Multi-step Process** (same as Gemini):
1. Click asset card
2. Click Export
3. Select format (Markdown or HTML)
4. Handle download

---

## Cross-Platform Patterns

### File Attachment Navigation (macOS)

**All platforms use**: Cmd+Shift+G navigation in file picker

```javascript
// Navigate to directory
const cmdShiftG = 'tell application "System Events" to tell process "Google Chrome" to keystroke "g" using {command down, shift down}';
await this.bridge.runScript(cmdShiftG);
await this.bridge.type(dir);
await this.bridge.pressKey('return');

// Type filename to select
await this.bridge.type(filename);
await this.bridge.pressKey('return');
```

**Platform Differences**: Only the button/menu to open the picker varies

### Response Detection

**Platform-Specific Indicators**:
- **Claude**: Thinking indicator appears/disappears
- **ChatGPT**: Standard response container
- **Gemini**: Start research button appears, content stability
- **Grok**: Content stability
- **Perplexity**: Special prose container selector

---

## For Rebuild: Standardization Strategy

### 1. What CAN Be Standardized

**Base Methods** (all platforms):
- `prepareInput()` - Focus input (with platform overrides)
- `typeMessage()` - Human-like typing
- `clickSend()` - Submit message
- `waitForResponse()` - Fibonacci polling (with platform overrides)
- `getLatestResponse()` - Extract response (with platform overrides)
- `screenshot()` - Capture state
- `newConversation()` - Start fresh
- `goToConversation(id)` - Navigate to existing

**Shared Patterns**:
- File picker navigation (macOS Cmd+Shift+G)
- Screenshot verification workflow
- Session management
- Bring-to-front before actions

### 2. What MUST Be Platform-Specific

**UI Element Selectors**:
- Each platform has unique DOM structure
- Selectors are fragile and change frequently
- Store in platform-specific config

**Model Selection**:
- Different menu structures per platform
- Different model names/availability
- Grok requires JavaScript click bypass
- ChatGPT disabled entirely

**Research/Thinking Modes**:
- Different activation methods
- Different mode names
- Different menu structures
- Different toggle behaviors (on/off vs always-on)

**File Attachment**:
- Different menu navigation paths
- Different button labels/selectors
- Same file picker once opened

**Download Artifact**:
- Not supported: ChatGPT, Grok
- Simple: Claude (direct download)
- Complex: Gemini, Perplexity (multi-step export)

**Response Detection**:
- Different completion indicators
- Different DOM structures for responses
- Perplexity needs special container selector
- Gemini needs Start button detection

### 3. Abstraction Strategy

**Create Platform Adapter Pattern**:

```javascript
class PlatformAdapter {
  // Platform must implement
  abstract getSelectors()
  abstract selectModel(modelName, options)
  abstract enableResearchMode(options)
  abstract attachFile(filePath, options)
  abstract downloadArtifact(options)
  abstract getLatestResponse()

  // Platform can override (defaults in base)
  prepareInput(options)
  waitForResponse(timeout, options)

  // Shared implementations (in base)
  typeMessage(message, options)
  clickSend(options)
  screenshot(path)
}

class GeminiAdapter extends PlatformAdapter {
  // Override to add overlay dismissal
  async prepareInput(options) {
    await this.dismissOverlays();
    await super.prepareInput(options);
  }

  // Override to force-enable Start button
  async waitForResponse(timeout, options) {
    await this.checkAndEnableStartButton();
    return await super.waitForResponse(timeout, options);
  }
}

class GrokAdapter extends PlatformAdapter {
  // Override to use JavaScript click
  async selectModel(modelName, options) {
    await this.page.evaluate(() => {
      document.querySelector('#model-select-trigger').click();
    });
    // ... rest of implementation
  }
}
```

**Benefits**:
- Clear separation of platform-specific vs shared code
- Easy to add new platforms
- Testable in isolation
- Maintainable when platforms change

**Config-Driven Selectors**:

```javascript
const PLATFORM_CONFIGS = {
  gemini: {
    selectors: {
      chatInput: '.ql-editor[contenteditable="true"]',
      modelSelector: '[data-test-id="bard-mode-menu-button"]',
      startResearchButton: 'button[data-test-id="confirm-button"]',
      // ... etc
    },
    quirks: {
      hasOverlays: true,
      needsButtonForceEnable: true,
      modelSelectionMethod: 'standard'
    }
  },
  grok: {
    selectors: {
      modelSelector: '#model-select-trigger',
      // ... etc
    },
    quirks: {
      hasOverlays: false,
      needsButtonForceEnable: false,
      modelSelectionMethod: 'javascript-click'
    }
  }
}
```

### 4. Testing Strategy

**Platform Smoke Tests**:
- Model selection (if supported)
- Research mode enable (if supported)
- File attachment
- Message send + response extraction
- Artifact download (if supported)

**Quirk Regression Tests**:
- Gemini: Verify overlay dismissal works
- Gemini: Verify Start button force-enable works
- Grok: Verify JavaScript click bypass works
- Perplexity: Verify full response extraction (not just last paragraph)

---

## Implementation Notes

### Current Architecture

**File**: `src/interfaces/chat-interface.js`
- Base class: `ChatInterface` with shared methods
- Subclasses: `ClaudeInterface`, `ChatGPTInterface`, `GeminiInterface`, `GrokInterface`, `PerplexityInterface`
- Each override methods as needed

**Works Well**:
- Inheritance pattern keeps shared code DRY
- Platform-specific overrides are clear
- Easy to find platform differences

**Could Improve**:
- Selectors hardcoded in constructors (should be in config)
- Quirk handling mixed with business logic (should be in adapters)
- Some methods very long (model selection, file attachment)

### Migration Path

1. **Extract Selectors** → Move to `platform-configs.js`
2. **Create Adapters** → Wrap quirk-specific logic
3. **Refactor Base** → Simplify to essential shared methods
4. **Add Tests** → Cover each platform's quirks
5. **Document** → Keep this quirks doc updated

---

## Maintenance

**When Platform UIs Change**:

1. Check selectors first (most common breakage)
2. Check menu navigation flows (second most common)
3. Check quirk workarounds still needed (rarely changes)
4. Update tests to match new behavior
5. Update this document

**When Adding New Platform**:

1. Identify unique quirks (overlay issues, disabled buttons, etc.)
2. Document in this file
3. Create platform adapter if quirks are complex
4. Add to config if quirks are simple
5. Write smoke tests

---

## Summary Table

| Platform | Model Selection | Research Mode | File Attachment | Download Artifact | Major Quirks |
|----------|----------------|---------------|-----------------|-------------------|--------------|
| **Grok** | JavaScript click bypass | N/A | Menu → Upload | Not supported | Button visibility trick |
| **Claude** | Standard dropdown | Toggle on/off | + menu → Upload | Simple download | Thinking indicator |
| **Gemini** | Standard dropdown | Menu → Modes | Menu → Upload | Multi-step export | Overlays, disabled button |
| **ChatGPT** | DISABLED | + menu → Modes | + menu → Upload | Not supported | Model selection unreliable |
| **Perplexity** | N/A | Button click | Menu → Local files | Multi-step export | Response selector fragility |

---

**Last Updated**: 2025-11-30
**Maintainer**: CCM (Claude Code on Mac)
**Next Review**: When any platform UI changes
