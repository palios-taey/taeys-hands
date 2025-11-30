# Platform UI Selectors Reference

Clean extraction from CHAT_ELEMENTS.md - essential selectors only, no HTML dumps.

## ChatGPT

### Model Selection
- **Model selector button**: `button[data-testid="model-switcher-dropdown-button"]`
  - Alternative: `button[aria-label*="Model selector"]`
- **Model menu items** (text-based selection):
  - Auto: Text content "Auto"
  - Instant: Text content "Instant"  
  - Thinking: Text content "Thinking"
  - Pro: Text content "Pro"
  - Legacy submenu: Text content "Legacy"
  - GPT-4o (in Legacy): Text content "GPT-4o"

### File Attachment & Modes
- **Plus button** (attachment/modes menu): `button[data-testid="composer-plus-btn"]`
  - Alternative: `button[aria-label="Add files and more"]`
- **Menu items** (text-based selection):
  - "Add photos & files"
  - "Deep research"
  - "Agent mode"
  - "Web search"
  - "GitHub"

### Message Input & Send
- **Message input**: `div[contenteditable="true"]` in composer area
- **Send button**: Look for send icon in composer area

---

## Claude

### Model Selection
- **Model selector button**: `button[data-testid="model-selector-dropdown"]`
- **Model menu items**:
  - Opus 4.5: `div[role="menuitem"]` containing text "Opus 4.5"
  - Sonnet 4.5: `div[role="menuitem"]` containing text "Sonnet 4.5"
  - Haiku 4: `div[role="menuitem"]` containing text "Haiku 4"

### Modes & Features
- **Web search toggle**: Button containing text "Web search"
  - Has toggle switch component (checkbox input)
- **Research toggle**: Button containing text "Research"  
  - Has toggle switch component (checkbox input)
- **Extended thinking toggle**: Button containing text "Extended thinking"
  - Has toggle switch component (checkbox input)

### File Attachment
- **Download button** (for artifacts): `button[aria-label="Download"]`
- **Artifact preview**: Click on artifact card in chat
- **Artifact menu dropdown**: Button with dropdown arrow in artifact pane
- **Download as Markdown**: Link/button with text "Download as Markdown"

### Message Input & Send
- **Message input**: `div[contenteditable="true"]` in composer
- **Send button**: Look for send icon in composer area

---

## Gemini

### Model Selection
- **Model selector button**: `button[data-test-id="bard-mode-menu-button"]`
  - Contains text of current model (e.g., "Thinking")
- **Model menu items**:
  - Thinking with 3 Pro: `button[data-test-id="bard-mode-option-thinkingwith3pro"]`
  - Thinking: `button[data-test-id="bard-mode-option-thinking"]` (likely)
  - Deep Research: `button[data-test-id*="deepresearch"]` (likely pattern)

### File Attachment
- **Upload button**: `button[aria-label="Open upload file menu"]`
  - Alternative: Button with mat-icon containing "add_2"
- **Hidden file upload buttons**:
  - Images: `button[data-test-id="hidden-local-image-upload-button"]`
  - Files: `button[data-test-id="hidden-local-file-upload-button"]`

### Deep Research Mode
- **Tools button**: `button[aria-label="Tools"]`
- **Deselect Deep Research**: `button[aria-label="Deselect Deep Research"]`
- **Start research button**: `button[data-test-id="confirm-button"]`
  - **CRITICAL**: This button is often programmatically disabled
  - Requires force-enable via JavaScript evaluation
  - See force-click code below

### Message Input & Send
- **Message input**: `div.ql-editor[contenteditable="true"][aria-label="Enter a prompt here"]`
- **Send button**: `button[aria-label="Send message"]`
  - Contains mat-icon with fonticon="send"
- **Microphone button**: `button[aria-label="Microphone"]`

---

## Grok

### Model Selection
- **Model selector button**: `button[id="model-select-trigger"]`
  - Alternative: `button[aria-label="Model select"]`
- **Model menu items** (in dropdown):
  - Auto: Text "Auto" + "Chooses Fast or Expert"
  - Fast: Text "Fast" + "Quick responses"
  - Expert: Text "Expert" + "Thinks hard"
  - Heavy: Text "Heavy" + "Team of experts"
  - Grok 4.1: Text "Grok 4.1" + "Beta"

### Custom Instructions
- **Custom Instructions section**: Element with class "group/custom-instructions"
- **Customize button**: `button[aria-label="Open Custom Instructions"]`

### Message Input & Send
- **Message input**: `div[contenteditable="true"]` in composer
- **Send button**: Look for send icon in composer area

---

## Perplexity

### Mode Selection (No model picker)
- **Mode radiogroup**: `div[role="radiogroup"]` container
- **Mode buttons** (radio buttons):
  - Search: `button[role="radio"][value="search"][aria-label="Search"]`
    - Contains `data-testid="search-mode-search"`
  - Research (Pro): `button[role="radio"][value="research"][aria-label="Research"]`
    - Contains `data-testid="search-mode-research"`
  - Labs: `button[role="radio"][value="studio"][aria-label="Labs"]`
    - Contains `data-testid="search-mode-studio"`

### File Attachment
- **Attach files button**: `button[data-testid="attach-files-button"]`
  - Alternative: `button[aria-label*="attach"]` or button containing paperclip icon

### Message Input & Send
- **Message input**: `textarea` or `div[contenteditable="true"]` in composer
- **Send button**: Look for send icon in composer area

---

## Common Patterns Across Platforms

### General Selector Strategies
1. **Text-based selection**: Most reliable for menu items
   - Wait for element containing specific text
   - Click via Playwright's `page.getByText()` or `page.getByRole()`

2. **Aria labels**: Good for accessibility-rich platforms
   - Use `aria-label`, `aria-describedby` attributes
   - Example: `button[aria-label="Model selector"]`

3. **Test IDs**: Most stable when available
   - Gemini uses `data-test-id` extensively
   - ChatGPT uses `data-testid`
   - Perplexity uses `data-testid`
   - These rarely change

4. **Contenteditable divs**: Common for rich text input
   - Look for `div[contenteditable="true"]`
   - Often has `role="textbox"`

### Force-Click Pattern (Gemini)
When buttons are programmatically disabled but visually clickable:
```javascript
const button = document.querySelector('button[data-test-id="confirm-button"]');
if (button) {
  button.disabled = false;
  button.click();
}
```

---

## Notes & Limitations

### Platform-Specific Notes

**Perplexity**:
- No model selection (uses single model)
- Has mode selection: Search, Research (Pro), Labs
- Mode selection uses radio button pattern with `role="radio"`
- Pro Research is the default research mode

**Gemini**:
- Deep Research button often programmatically disabled
- Requires JavaScript force-enable before clicking
- Model selection uses descriptive names (e.g., "Thinking with 3 Pro")

**ChatGPT**:
- Legacy models in submenu (GPT-4o)
- Deep research available as mode option
- Model selector shows version number

**Claude**:
- Toggle switches for modes (Web search, Research, Extended thinking)
- Artifact download requires multi-step process
- Model selector shows tier names (Opus, Sonnet, Haiku)

**Grok**:
- Model selector shows descriptive names (Auto, Fast, Expert, Heavy, Grok 4.1)
- Custom Instructions available in model menu
- Beta tag on Grok 4.1

### Reliability Tiers
1. **Most reliable**: `data-test-id`, `data-testid` attributes
2. **Very reliable**: `aria-label` attributes  
3. **Reliable**: Text content matching
4. **Less reliable**: CSS classes (can change frequently)

### Recommendations
1. Always use multiple selector strategies (fallbacks)
2. Wait for elements to be visible/enabled before interaction
3. For Gemini, always check if buttons need force-enabling
4. Use text-based selection for menu items when possible
5. Test selectors regularly as platforms update frequently

---

## Update History
- Created: 2025-11-30
- Source: CHAT_ELEMENTS.md analysis
- Perplexity selectors extracted: 2025-11-30
- Status: Complete - ready for implementation testing
