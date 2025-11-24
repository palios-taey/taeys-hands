# AI Interface Documentation

Complete reference for all AI chat interfaces supported by Taey's Hands.

## Overview

| AI | URL | Input Selector | Response Selector |
|---|---|---|---|
| Claude | claude.ai | `[contenteditable="true"]` | `div.grid.standard-markdown` |
| ChatGPT | chatgpt.com | `#prompt-textarea` | `[data-message-author-role="assistant"]` |
| Gemini | gemini.google.com | `.ql-editor[contenteditable="true"]` | `p[data-path-to-node]` |
| Grok | grok.com | `textarea` | `div.response-content-markdown` |
| Perplexity | perplexity.ai | `#ask-input` | `[class*="prose"]` |

---

## Claude (claude.ai)

### Selectors
```javascript
chatInput: '[contenteditable="true"]'
sendButton: 'button[type="submit"]'
responseContainer: 'div.grid.standard-markdown:has(> .font-claude-response-body)'
newChatButton: 'button[aria-label="New chat"]'
thinkingIndicator: '[class*="thinking"], [class*="loading"]'
toolsMenuButton: '#input-tools-menu-trigger, [data-testid="input-menu-tools"]'
fileInput: 'input[type="file"]'
attachmentButton: 'button[aria-label*="Attach"], button[data-testid*="attach"]'
```

### Special Features

#### Research Mode
- **Method**: `setResearchMode(enabled: boolean)`
- **How**: Opens tools menu -> toggles Research button
- **Selector**: `button:has-text("Research")`

#### Extended Thinking
- Automatically detected via `thinkingIndicator`
- Longer timeout (5 minutes default)
- Shows "Claude is thinking deeply..." log

#### File Attachment
- **Menu Button**: `[data-testid="input-menu-plus"]`
- **Menu Item**: `"Upload a file"`
- Uses Finder dialog with Cmd+Shift+G navigation

### URL Patterns
- New chat: `https://claude.ai/new`
- Conversation: `https://claude.ai/chat/{conversationId}`

---

## ChatGPT (chatgpt.com)

### Selectors
```javascript
chatInput: '#prompt-textarea'
sendButton: 'button[data-testid="send-button"]'
responseContainer: '[data-message-author-role="assistant"]'
newChatButton: 'nav button:first-child'
thinkingIndicator: '.result-thinking, [class*="thinking"]'
fileInput: 'input[type="file"]'
attachmentButton: 'button[aria-label*="Attach"], button[data-testid*="attach"]'
```

### Special Features

#### Models (via dropdown)
- GPT-4o
- GPT-4o mini
- o1-preview
- o1-mini

#### File Attachment
- **Menu Button**: `[data-testid="composer-plus-btn"]` (+ button)
- **Menu Item**: `"Add photos & files"`
- Uses Finder dialog with Cmd+Shift+G navigation

#### Canvas Mode
- Not yet implemented
- Selector TBD

### URL Patterns
- New chat: `https://chatgpt.com`
- Conversation: `https://chatgpt.com/c/{conversationId}`

---

## Gemini (gemini.google.com)

### Selectors
```javascript
chatInput: '.ql-editor[contenteditable="true"], [aria-label="Enter a prompt here"]'
sendButton: 'button[aria-label="Send message"]'
responseContainer: 'p[data-path-to-node]'
newChatButton: 'button[aria-label="New chat"]'
fileInput: 'input[type="file"]'
attachmentButton: 'button[aria-label*="Upload"], button[aria-label*="Add"]'
```

### Special Features

#### Models
- Gemini 1.5 Pro
- Gemini 2.0 Flash (Experimental)

#### Deep Research Mode
- Extended processing for research queries
- Not yet implemented in interface

#### File Attachment
- **Menu Button**: `button[aria-label="Open upload file menu"]`
- **Upload Button**: `button[data-test-id="local-images-files-uploader-button"]`
- Uses Finder dialog with Cmd+Shift+G navigation

#### Extensions (Google Workspace integration)
- Not yet implemented
- Can access Google Docs, Sheets, Gmail, etc.

### URL Patterns
- New chat: `https://gemini.google.com/app`
- Conversation: `https://gemini.google.com/app/{conversationId}`

---

## Grok (grok.com)

### Selectors
```javascript
chatInput: 'textarea, [contenteditable="true"]'
sendButton: 'button[type="submit"], button[aria-label*="send" i]'
responseContainer: 'div.response-content-markdown'
newChatButton: 'button[aria-label*="new" i], a[href="/"]'
fileInput: 'input[type="file"]'
attachmentButton: 'button[aria-label*="Attach"], button[aria-label*="upload" i]'
```

### Special Features

#### Models
- Grok-2
- Grok-2 mini
- Heavy (extended thinking)

#### DeepSearch Mode
- Real-time web search integration
- Toggle available in interface

#### File Attachment
- **Attach Button**: `button[aria-label="Attach"]`
- **Menu Item**: `div[role="menuitem"]:has-text("Upload a file")`
- Uses Finder dialog with Cmd+Shift+G navigation

### URL Patterns
- New chat: `https://grok.com`
- Conversation: `https://grok.com/chat/{conversationId}` or `https://grok.com/c/{id}`

---

## Perplexity (perplexity.ai)

### Selectors
```javascript
chatInput: '#ask-input, [data-lexical-editor="true"]'
sendButton: 'button[aria-label*="Submit"], button[type="submit"]'
responseContainer: '[class*="prose"], [class*="answer"]'
newChatButton: 'a[href="/"], button[aria-label*="New"]'
fileInput: 'input[type="file"]'
attachmentButton: 'button[aria-label*="Attach"], button[aria-label*="Upload"]'
```

### Special Features

#### Focus Modes
- **All** - Standard search
- **Academic** - Scholar/research papers
- **Writing** - Content generation
- **YouTube** - Video search
- **Reddit** - Reddit discussions
- **Wolfram|Alpha** - Computational

#### Pro Search
- Extended research mode
- Multiple sources synthesis

#### File Attachment (Pro feature)
- **Attach Button**: `button[data-testid="attach-files-button"]`
- **Menu Item**: `div[role="menuitem"]:has-text("Local files")`
- Uses Finder dialog with Cmd+Shift+G navigation

#### Collections
- Organize searches into collections
- Not yet implemented

### URL Patterns
- New search: `https://perplexity.ai`
- Thread: `https://perplexity.ai/search/{threadId}`

---

## Common Methods

All interfaces inherit from `ChatInterface` and support:

| Method | Description |
|--------|-------------|
| `connect()` | Connect to browser via CDP |
| `disconnect()` | Close connection |
| `sendMessage(msg, options)` | Send message, optionally wait for response |
| `waitForResponse(timeout)` | Fibonacci polling for response |
| `getLatestResponse()` | Get last response text |
| `newConversation()` | Start fresh conversation |
| `goToConversation(urlOrId)` | Navigate to specific conversation |
| `screenshot(filename)` | Capture current page |
| `attachFile(paths)` | Attach file(s) via hidden input |
| `attachFileHumanLike(path)` | Attach via Finder dialog (human-like) |
| `isLoggedIn()` | Check if user is logged in |
| `startNewChat()` | Start new chat via button or URL |

### sendMessage Options
```javascript
{
  humanLike: true,       // Use osascript typing (default: true)
  waitForResponse: true, // Wait for AI response (default: true)
  timeout: 120000,       // Response timeout in ms (default: 2 min)
  mixedContent: true     // TYPE prompts, PASTE AI quotes (default: true)
}
```

---

## Not Yet Implemented

### All Interfaces
- [ ] Model selection dropdown
- [ ] Voice input/output
- [ ] Image generation
- [ ] Code execution

### Claude Specific
- [ ] Projects (context windows)
- [ ] Artifacts viewer
- [ ] Style settings

### ChatGPT Specific
- [ ] Canvas mode
- [ ] Memory management
- [ ] GPTs (custom agents)
- [ ] DALL-E image generation

### Gemini Specific
- [ ] Extensions (Workspace, Maps, etc.)
- [ ] Image generation
- [ ] Deep Research toggle

### Grok Specific
- [ ] Heavy mode toggle
- [ ] DeepSearch toggle
- [ ] X (Twitter) integration

### Perplexity Specific
- [ ] Focus mode switching
- [ ] Pro Search toggle
- [ ] Collections management
- [ ] Copilot settings
