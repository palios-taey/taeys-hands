# SelectorRegistry Quick Reference

## Import

```javascript
import { SelectorRegistry } from './src/v2/core/selectors/selector-registry.js';
// or
import { SelectorRegistry } from './src/v2/core/selectors/index.js';
```

## Basic Usage

```javascript
const registry = new SelectorRegistry();

// Get a selector string
const selector = await registry.getSelector('chatgpt', 'attach_button');
// Returns: "button[data-testid=\"composer-plus-btn\"]"

// Get full definition (primary + fallback + description)
const def = await registry.getDefinition('chatgpt', 'attach_button');
// Returns: { primary: "...", fallback: "...", description: "..." }
```

## Critical Selectors (All Platforms)

| Key | Purpose |
|-----|---------|
| `attach_button` | File attachment button |
| `send_button` | Send message button |
| `message_input` | Text input/textarea |
| `new_chat_button` | Start new conversation |

## Platform-Specific Quick Reference

### ChatGPT (15 selectors)

**Core:**
- `model_selector` - Model dropdown
- `attach_button` - Plus button (opens menu)
- `send_button` - Send message
- `message_input` - Message input div
- `new_chat_button` - New chat

**Models:**
- `model_auto`, `model_instant`, `model_thinking`, `model_pro`
- `model_legacy_submenu`, `model_gpt4o`

**Features:**
- `menu_item_attach_files`, `menu_item_deep_research`
- `menu_item_agent_mode`, `menu_item_web_search`

### Claude (13 selectors)

**Core:**
- `model_selector` - Model dropdown
- `attach_button` - Paperclip icon
- `send_button` - Send message
- `message_input` - Message input div
- `new_chat_button` - New chat

**Models:**
- `model_opus`, `model_sonnet`, `model_haiku`

**Modes:**
- `extended_thinking_toggle` - Extended thinking switch
- `research_toggle` - Research mode switch
- `web_search_toggle` - Web search switch

**Artifacts:**
- `download_artifact_button`, `download_as_markdown`

### Gemini (14 selectors)

**Core:**
- `model_selector` - Mode menu button
- `attach_button` - Upload menu button
- `send_button` - Send message
- `message_input` - Message input div
- `new_chat_button` - New chat

**Models:**
- `model_thinking_3pro`, `model_thinking`, `model_deep_research`

**Deep Research:**
- `tools_button` - Tools menu
- `start_research_button` - **REQUIRES FORCE-ENABLE VIA JS**
- `deselect_deep_research` - Deselect research

**Upload:**
- `hidden_image_upload`, `hidden_file_upload`

**Other:**
- `microphone_button` - Voice input

### Grok (12 selectors)

**Core:**
- `model_selector` - Model select trigger
- `attach_button` - Attach files
- `send_button` - Send message
- `message_input` - Message input div
- `new_chat_button` - New chat

**Models:**
- `model_grok41`, `model_auto`, `model_fast`, `model_expert`, `model_heavy`

**Custom Instructions:**
- `custom_instructions_section`, `custom_instructions_button`

### Perplexity (8 selectors)

**Core:**
- `attach_button` - Attach files button
- `send_button` - Send message
- `message_input` - **TEXTAREA** (not contenteditable)
- `new_chat_button` - New thread

**Modes** (no model selection):
- `mode_radiogroup` - Radio button container
- `mode_search` - Search mode
- `mode_research` - Research (Pro) mode
- `mode_labs` - Labs mode

## Utility Methods

```javascript
// List all available selector keys
const keys = await registry.getAvailableKeys('chatgpt');

// Get platform config (version, url)
const config = await registry.getPlatformConfig('chatgpt');
// Returns: { version: '1.0.0', platform: 'chatgpt', url: 'https://chatgpt.com' }

// Clear cache (for development)
registry.clearCache('chatgpt'); // Clear one platform
registry.clearCache();          // Clear all
```

## Error Messages

**Invalid platform:**
```
Error: Selector config file not found for platform 'foo'.
Available platforms: chatgpt, claude, gemini, grok, perplexity
```

**Invalid key:**
```
Error: Selector key 'bar' not found for platform 'chatgpt'.
Available keys: attach_button, send_button, message_input, ...
```

## Platform Differences Cheat Sheet

| Platform | Attach | Input Type | Model Selection | Special Notes |
|----------|--------|------------|-----------------|---------------|
| ChatGPT | Plus button → menu | contenteditable | Dropdown | Menu for modes |
| Claude | Paperclip | contenteditable | Dropdown | Toggle switches |
| Gemini | Upload button → hidden | contenteditable | Mode button | Force-enable research |
| Grok | Paperclip | contenteditable | Dropdown | Custom instructions |
| Perplexity | Attach button | textarea | None | Radio button modes |

## Common Patterns

### Get selector with fallback handling

```javascript
async function getElementWithFallback(page, platform, key) {
  const def = await registry.getDefinition(platform, key);

  try {
    // Try primary
    return await page.waitForSelector(def.primary, { timeout: 5000 });
  } catch {
    if (def.fallback) {
      // Try fallback
      return await page.waitForSelector(def.fallback, { timeout: 5000 });
    }
    throw new Error(`Could not find element for ${key} on ${platform}`);
  }
}
```

### Use in platform class

```javascript
class ChatGPTPlatform {
  constructor() {
    this.registry = new SelectorRegistry();
  }

  async attachFiles(filePaths) {
    const selector = await this.registry.getSelector('chatgpt', 'attach_button');
    await this.page.click(selector);

    const menuItem = await this.registry.getSelector('chatgpt', 'menu_item_attach_files');
    await this.page.click(menuItem);
    // ... file dialog handling
  }

  async sendMessage(message) {
    const input = await this.registry.getSelector('chatgpt', 'message_input');
    const send = await this.registry.getSelector('chatgpt', 'send_button');

    await this.page.fill(input, message);
    await this.page.click(send);
  }
}
```

## Testing

```bash
# Run the test suite
node test_selector_registry.js

# Expected output: 41/41 tests passed
```

## Files

- Configs: `/Users/REDACTED/taey-hands/config/selectors/*.json`
- Source: `/Users/REDACTED/taey-hands/src/v2/core/selectors/selector-registry.js`
- Test: `/Users/REDACTED/taey-hands/test_selector_registry.js`
- Docs: `/Users/REDACTED/taey-hands/src/v2/core/selectors/README.md`
