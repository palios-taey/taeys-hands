# SelectorRegistry - Centralized Selector Management

The SelectorRegistry provides a single source of truth for all platform UI selectors used in taey-hands v2.

## Overview

Instead of hardcoding selectors throughout the codebase, all selectors are stored in JSON configuration files and accessed through the SelectorRegistry API. This provides:

- **Single source of truth** - All selectors in one place
- **Easy updates** - Change selectors without touching code
- **Fallback support** - Primary and fallback selectors for resilience
- **Documentation** - Each selector has a description
- **Version tracking** - Selector configs are versioned
- **Better errors** - Helpful messages when selectors are missing

## Directory Structure

```
config/selectors/
├── chatgpt.json      # ChatGPT selectors
├── claude.json       # Claude selectors
├── gemini.json       # Gemini selectors
├── grok.json         # Grok selectors
└── perplexity.json   # Perplexity selectors

src/v2/core/selectors/
├── selector-registry.js  # Main registry implementation
└── README.md            # This file
```

## JSON Configuration Format

Each platform's JSON file follows this structure:

```json
{
  "version": "1.0.0",
  "platform": "chatgpt",
  "url": "https://chatgpt.com",
  "selectors": {
    "attach_button": {
      "primary": "button[data-testid=\"composer-plus-btn\"]",
      "fallback": "button[aria-label=\"Add files and more\"]",
      "description": "Plus button that opens attachment/modes menu"
    },
    "send_button": {
      "primary": "button[data-testid=\"send-button\"]",
      "fallback": "button[aria-label*=\"Send\"]",
      "description": "Send message button in composer"
    }
  }
}
```

### Required Fields
- `version` - Semver version string
- `platform` - Platform name (lowercase)
- `url` - Base URL for the platform
- `selectors` - Object mapping selector keys to definitions

### Selector Definition
- `primary` (required) - The primary selector to try first
- `fallback` (optional) - Backup selector if primary fails
- `description` (optional) - Human-readable description

## Usage

### Basic Usage

```javascript
import { SelectorRegistry } from './src/v2/core/selectors/selector-registry.js';

const registry = new SelectorRegistry();

// Get a selector string
const attachButton = await registry.getSelector('chatgpt', 'attach_button');
// Returns: "button[data-testid=\"composer-plus-btn\"]"

// Get full definition with fallback
const def = await registry.getDefinition('chatgpt', 'attach_button');
// Returns: { primary: "...", fallback: "...", description: "..." }
```

### In Platform Classes

```javascript
class ChatGPTPlatform {
  constructor() {
    this.registry = new SelectorRegistry();
  }

  async attachFiles(filePaths) {
    const attachSelector = await this.registry.getSelector('chatgpt', 'attach_button');
    await this.page.click(attachSelector);
    // ... rest of attachment logic
  }

  async sendMessage(message) {
    const inputSelector = await this.registry.getSelector('chatgpt', 'message_input');
    const sendSelector = await this.registry.getSelector('chatgpt', 'send_button');

    await this.page.fill(inputSelector, message);
    await this.page.click(sendSelector);
  }
}
```

### Error Handling

The registry provides helpful errors when selectors are missing:

```javascript
// Invalid platform
await registry.getSelector('invalid_platform', 'attach_button');
// Error: Selector config file not found for platform 'invalid_platform'
//        Available platforms: chatgpt, claude, gemini, grok, perplexity

// Invalid key
await registry.getSelector('chatgpt', 'invalid_key');
// Error: Selector key 'invalid_key' not found for platform 'chatgpt'.
//        Available keys: attach_button, send_button, message_input, ...
```

### Utility Methods

```javascript
// Get all available selector keys for a platform
const keys = await registry.getAvailableKeys('chatgpt');
// Returns: ['attach_button', 'send_button', 'message_input', ...]

// Get platform config (version, url)
const config = await registry.getPlatformConfig('chatgpt');
// Returns: { version: '1.0.0', platform: 'chatgpt', url: 'https://chatgpt.com' }

// Clear cache (useful for development/testing)
registry.clearCache('chatgpt'); // Clear specific platform
registry.clearCache();          // Clear all platforms
```

## Critical Selectors

Every platform must implement these core selectors:

- `attach_button` - File attachment button
- `send_button` - Send message button
- `message_input` - Text input/textarea for messages
- `new_chat_button` - Start new conversation

### Platform-Specific Differences

**ChatGPT**: Uses `composer-plus-btn` for attachments (opens menu with multiple options)

**Claude**: Separate buttons for attach, toggles for modes (Web search, Research, Extended thinking)

**Gemini**: Two-step attachment (menu button → hidden upload button), force-enable needed for Deep Research

**Grok**: Standard attach button, model selector includes custom instructions

**Perplexity**: Mode selection (Search/Research/Labs) instead of model selection, uses `textarea` for input

## Model Selection

Platforms with model selection (all except Perplexity):

```javascript
// ChatGPT
await registry.getSelector('chatgpt', 'model_selector');
await registry.getSelector('chatgpt', 'model_auto');      // Auto
await registry.getSelector('chatgpt', 'model_pro');       // Pro
await registry.getSelector('chatgpt', 'model_thinking');  // Thinking

// Claude
await registry.getSelector('claude', 'model_selector');
await registry.getSelector('claude', 'model_opus');    // Opus 4.5
await registry.getSelector('claude', 'model_sonnet');  // Sonnet 4.5
await registry.getSelector('claude', 'model_haiku');   // Haiku 4

// Gemini
await registry.getSelector('gemini', 'model_selector');
await registry.getSelector('gemini', 'model_thinking_3pro'); // Thinking with 3 Pro
await registry.getSelector('gemini', 'model_thinking');      // Thinking

// Grok
await registry.getSelector('grok', 'model_selector');
await registry.getSelector('grok', 'model_grok41');  // Grok 4.1
await registry.getSelector('grok', 'model_auto');    // Auto
await registry.getSelector('grok', 'model_expert');  // Expert
```

## Mode/Feature Selection

```javascript
// ChatGPT - Menu items
await registry.getSelector('chatgpt', 'menu_item_deep_research');
await registry.getSelector('chatgpt', 'menu_item_web_search');

// Claude - Toggle switches
await registry.getSelector('claude', 'extended_thinking_toggle');
await registry.getSelector('claude', 'research_toggle');
await registry.getSelector('claude', 'web_search_toggle');

// Gemini - Deep Research mode
await registry.getSelector('gemini', 'start_research_button');  // Needs force-enable
await registry.getSelector('gemini', 'deselect_deep_research');

// Perplexity - Radio button modes
await registry.getSelector('perplexity', 'mode_search');    // Search mode
await registry.getSelector('perplexity', 'mode_research');  // Research (Pro) mode
await registry.getSelector('perplexity', 'mode_labs');      // Labs mode
```

## Selector Reliability Tiers

1. **Most reliable**: `data-testid`, `data-test-id` attributes
   - Rarely change, intended for testing
   - Used extensively by ChatGPT, Gemini, Perplexity

2. **Very reliable**: `aria-label` attributes
   - Accessibility-focused, relatively stable
   - Good fallback option

3. **Reliable**: Text content matching (`text=...`)
   - Good for menu items and buttons with stable labels
   - Language-dependent (English only currently)

4. **Less reliable**: CSS classes
   - Can change frequently with design updates
   - Avoid when possible

## Updating Selectors

When platform UIs change:

1. Identify the new selector using browser DevTools
2. Update the appropriate JSON file in `config/selectors/`
3. Update `version` field (semver)
4. Run tests: `node test_selector_registry.js`
5. Test manually with actual platform

### Example Update

```json
{
  "version": "1.1.0",  // Increment version
  "platform": "chatgpt",
  "url": "https://chatgpt.com",
  "selectors": {
    "attach_button": {
      "primary": "button[data-testid=\"new-composer-plus-btn\"]",  // Updated
      "fallback": "button[data-testid=\"composer-plus-btn\"]",      // Old becomes fallback
      "description": "Plus button that opens attachment/modes menu"
    }
  }
}
```

## Testing

Run the test suite to verify all selectors are properly configured:

```bash
node test_selector_registry.js
```

The test validates:
- All platform configs load successfully
- Critical selectors exist for all platforms
- Model selectors work (where applicable)
- Error handling for invalid platforms/keys
- Platform-specific selectors are accessible

## Best Practices

1. **Always use the registry** - Never hardcode selectors in platform code
2. **Provide fallbacks** - Add fallback selectors for critical elements
3. **Document changes** - Update version and add comments when changing selectors
4. **Test thoroughly** - Run test suite and manual tests after updates
5. **Use stable selectors** - Prefer `data-testid` and `aria-label` over classes
6. **Keep descriptions current** - Update descriptions when behavior changes

## Future Enhancements

Potential improvements for the selector system:

- **Multi-language support** - Selectors for different UI languages
- **Selector health monitoring** - Track which selectors fail in production
- **Auto-discovery** - Detect selector changes and suggest updates
- **Visual regression testing** - Screenshot comparisons for UI changes
- **Selector versioning** - Support multiple versions of platform selectors simultaneously
- **Hot reloading** - Update selectors without restarting MCP server

## References

- Source selectors: `/Users/REDACTED/taey-hands/docs/rebuild/CLEAN_SELECTORS.md`
- Rebuild architecture: `/Users/REDACTED/taey-hands/docs/rebuild/CHATGPT_REBUILD.md`
- Chat elements analysis: `/Users/REDACTED/taey-hands/CHAT_ELEMENTS.md`
