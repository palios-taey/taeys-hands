# File Attachment Workflows Across Platforms

## Executive Summary

File attachment is implemented using **Cmd+Shift+G navigation** (macOS) to bypass the native file picker, but each platform has different UI entry points and menu structures. Current implementation has platform-specific methods that duplicate the navigation logic.

**Current State**: Working for all platforms
**Problem**: Code duplication, maintenance burden, selector fragility
**Recommendation**: Unified interface with platform-specific entry points only

---

## 1. Common Pattern (All Platforms)

### Workflow Steps
1. **Click attach button** (platform-specific selector)
2. **Navigate menu** (some platforms have submenus)
3. **Wait for native file picker** (1500ms standard)
4. **Use osascript for Cmd+Shift+G** (macOS navigation)
5. **Type directory path** + Enter
6. **Type filename** + Enter
7. **Wait for file to appear** (1500ms)
8. **Capture screenshot** for verification

### Shared Navigation Code
```javascript
// From _navigateFinderDialog() - lines 194-241
// Used by ChatGPT, Gemini, Grok, Perplexity (NOT Claude)

1. Cmd+Shift+G via osascript (800ms wait)
2. Type file path (baseDelay: 30ms, variation: 15ms)
3. Enter to navigate (1000ms wait)
4. Enter to select/open (1000ms wait)
```

---

## 2. Platform Variations

### **ChatGPT**
**Entry Point**: `+ menu` → `"Add photos & files"`

**Selectors**:
- Button: `[data-testid="composer-plus-btn"]`
- Menu Item: `text="Add photos & files"`

**Implementation**: Lines 1233-1300 (`attachFile` override)
- Uses shared `_navigateFinderDialog()` navigation
- 1500ms wait for file picker

**Notes**:
- Clean menu structure
- Standard timing works reliably

---

### **Claude**
**Entry Point**: `+ menu` → `"Upload a file"`

**Selectors**:
- Button: `[data-testid="input-menu-plus"]`
- Menu Item: `text="Upload a file"`

**Implementation**: Lines 938-1005 (`attachFile` override)
- **Custom navigation** (duplicates `_navigateFinderDialog` logic)
- Same Cmd+Shift+G pattern but reimplemented

**Notes**:
- Only platform NOT using shared navigation
- Should be refactored to use `_navigateFinderDialog()`

---

### **Gemini**
**Entry Point**: `Attach menu` (2 steps) → `"Upload files"`

**Selectors**:
- Menu Button: `button[aria-label="Open upload file menu"]` (+ 4 fallbacks)
- Upload Item: `button[data-test-id="local-images-files-uploader-button"]` (+ 4 fallbacks)

**Implementation**: Lines 1569-1655 (`attachFileHumanLike`)
- **Two-step menu**: Click attach button, THEN click "Upload files"
- Uses shared `_navigateFinderDialog()` navigation
- Multiple fallback selectors due to frequent UI changes

**Notes**:
- Most complex entry point (2 clicks required)
- UI changes frequently, needs robust selectors
- Overlay dismissal required before attachment (`dismissOverlays()`)

---

### **Grok**
**Entry Point**: `Attach button` → `"Upload a file"`

**Selectors**:
- Button: `button[aria-label="Attach"]`
- Menu Item: `div[role="menuitem"]:has-text("Upload a file")`

**Implementation**: Lines 1903-1938 (`attachFileHumanLike`)
- Uses shared `_navigateFinderDialog()` navigation
- Standard timing

**Notes**:
- Clean implementation
- Reliable selectors

---

### **Perplexity**
**Entry Point**: `Attach button` → `"Local files"`

**Selectors**:
- Button: `button[data-testid="attach-files-button"]`
- Menu Item: `div[role="menuitem"]:has-text("Local files")`

**Implementation**: Lines 2114-2149 (`attachFileHumanLike`)
- Uses shared `_navigateFinderDialog()` navigation
- Standard timing

**Notes**:
- Clean implementation
- "Local files" distinguishes from other file sources (Drive, etc.)

---

## 3. Current Implementation Analysis

### Atomic Method Pattern (Lines 297-359)
```javascript
async attachFile(filePath, options = {})
```

**Design**:
- Platform-specific selectors via lookup table (lines 302-309)
- Returns `{ screenshot, automationCompleted, filePath }`
- **Unverified action** - requires screenshot validation

**Platform Overrides**:
- **Claude** (lines 938-1005): Custom implementation
- **ChatGPT** (lines 1233-1300): Override with custom navigation
- **Perplexity** (lines 2091-2109): Wrapper around `attachFileHumanLike`

### Legacy Method Pattern
```javascript
async attachFileHumanLike(filePath)
```

**Used By**:
- Claude (lines 1150-1184)
- ChatGPT (lines 1305-1339)
- Gemini (lines 1569-1655)
- Grok (lines 1903-1938)
- Perplexity (lines 2114-2149)

**Issues**:
- Duplicates logic with atomic `attachFile()`
- Should be deprecated in favor of atomic method

---

## 4. Problems Identified

### Code Duplication
1. **Claude duplicates navigation logic** (lines 970-992)
   - Should use `_navigateFinderDialog()` instead
   - Exact same Cmd+Shift+G pattern

2. **Two attachment methods per platform**
   - `attachFile()` atomic method
   - `attachFileHumanLike()` legacy method
   - Should consolidate to single method

### Selector Fragility
1. **Gemini has 5 fallback selectors** (lines 1591-1641)
   - UI changes frequently
   - Need robust selector strategy

2. **Hard-coded browser name** in osascript (lines 329, 975, 1270)
   - `tell process "Google Chrome"`
   - Should use `this._getBrowserName()` variable

### Timing Assumptions
1. **Fixed waits** may be too short/long depending on system
   - 1500ms for file picker (universal)
   - 500ms, 800ms, 1000ms for various steps
   - No adaptive timing based on success/failure

### Missing Validation
1. **File existence check** is duplicated (lines 945-949, 1239-1244, etc.)
2. **No validation** that file actually appeared in UI
   - Screenshot capture only (manual verification required)
   - Could check DOM for file attachment element

---

## 5. Recommended Rebuild Approach

### Architecture
```
attachFile(filePath, options)
  ├─ validateFileExists(filePath)
  ├─ getAttachmentEntryPoint(platform) → { button, menuItem, steps }
  ├─ clickEntryPoint(entryPoint)
  ├─ navigateFilePicker(filePath) [UNIFIED]
  └─ validateAttachment(filePath) [OPTIONAL]
```

### Unified Interface
```javascript
class ChatInterface {
  // Base implementation - calls platform-specific entry point
  async attachFile(filePath, options = {}) {
    await this.validateFileExists(filePath);
    await this.clickAttachmentEntryPoint();
    await this._navigateFilePicker(filePath); // SHARED
    return await this.captureAttachmentScreenshot(options);
  }

  // Platform override ONLY this method
  async clickAttachmentEntryPoint() {
    throw new Error('Must override in subclass');
  }
}
```

### Platform-Specific Overrides (ONLY entry point)
```javascript
// Claude
async clickAttachmentEntryPoint() {
  const plusBtn = await this.page.waitForSelector('[data-testid="input-menu-plus"]');
  await plusBtn.click();
  await this.page.waitForTimeout(500);

  const menuItem = await this.page.waitForSelector('text="Upload a file"');
  await menuItem.click();
}

// Gemini (2-step menu)
async clickAttachmentEntryPoint() {
  const menuBtn = await this.findAttachMenuButton(); // Try 5 selectors
  await menuBtn.click();
  await this.page.waitForTimeout(500);

  const uploadBtn = await this.findUploadMenuItem(); // Try 5 selectors
  await uploadBtn.click();
}
```

### Shared Navigation (NO changes needed)
```javascript
// _navigateFinderDialog() - lines 194-241
// Already works perfectly
// Used by ChatGPT, Gemini, Grok, Perplexity
```

---

## 6. Implementation Plan

### Phase 1: Consolidate Entry Points
1. Remove `attachFileHumanLike()` methods
2. Consolidate into single `attachFile()` per platform
3. Each platform overrides ONLY `clickAttachmentEntryPoint()`

### Phase 2: Unify Navigation
1. Make Claude use `_navigateFilePicker()` (rename from `_navigateFinderDialog`)
2. Remove duplicated navigation code (lines 970-992)
3. Extract browser name variable (replace hard-coded "Google Chrome")

### Phase 3: Improve Selectors
1. Gemini: Extract fallback selector logic to helper
2. All: Add selector validation with better error messages
3. Consider CSS selector arrays: `['primary', 'fallback1', 'fallback2']`

### Phase 4: Add Validation (Optional)
1. Check DOM for file attachment element after upload
2. Extract filename from attachment UI
3. Compare with expected filename
4. Return `{ success: boolean, screenshot: string, fileName: string }`

---

## 7. Success Indicators

### Current State
- **File attachment selector**: `input[type="file"]` (hidden)
- **Attachment button**: Platform-specific (see section 2)
- **Success validation**: Screenshot only (manual review required)

### After Rebuild
- **Reduced code**: ~300 lines → ~100 lines
- **Maintainability**: Single navigation implementation
- **Reliability**: Validated attachment success
- **Extensibility**: New platforms only need entry point override

---

## 8. Platform-Specific Quirks

### ChatGPT
- Clean menu structure
- No special handling needed

### Claude
- Currently duplicates navigation
- **FIX**: Use shared `_navigateFilePicker()` method

### Gemini
- **Overlay dismissal required** before attachment
- Two-step menu (attach button → upload files)
- Frequent UI changes require fallback selectors
- **FIX**: Robust selector helper with graceful degradation

### Grok
- Simple, reliable
- No special handling needed

### Perplexity
- "Local files" menu item (vs Drive/other sources)
- Clean implementation
- No special handling needed

---

## 9. File Picker Navigation Details

### macOS (Cmd+Shift+G)
```javascript
// Lines 194-241: _navigateFinderDialog()
1. Cmd+Shift+G (osascript keystroke "g" using {command down, shift down})
2. Type directory path (mimesis typing with delays)
3. Enter (navigate to directory)
4. Type filename (select file)
5. Enter (confirm selection)
```

**Timing**:
- 800ms after Cmd+Shift+G
- 300ms after typing path
- 1000ms after first Enter
- 300ms after typing filename
- 1000ms after final Enter

### Linux (Ctrl+L)
```javascript
// Lines 223-240: Linux alternative
1. Ctrl+L (location bar in file dialogs)
2. Type full file path
3. Enter (navigate and select)
```

**Note**: Currently implemented but not fully tested

---

## 10. Error Scenarios

### File Not Found
- **Current**: Throws error before opening file picker
- **Good**: Fails fast, clear error message

### Selector Not Found
- **Current**: Throws timeout error (5000ms default)
- **Issue**: Unclear which selector failed (button vs menu item)
- **FIX**: Better error messages with selector context

### File Picker Timeout
- **Current**: 1500ms fixed wait
- **Issue**: May be too short on slow systems
- **FIX**: Adaptive timing or longer default (2000ms)

### Overlay Blocking (Gemini)
- **Current**: `dismissOverlays()` method (lines 1453-1500)
- **Methods**: Close button, Escape key, click empty area
- **FIX**: Run before EVERY Gemini attachment

### osascript Failure
- **Current**: Throws error, no fallback
- **Issue**: osascript requires accessibility permissions
- **FIX**: Graceful degradation to Playwright `setInputFiles()`?

---

## Summary Table

| Platform | Entry Point | Steps | Navigation | Issues | Priority |
|----------|------------|-------|------------|--------|----------|
| ChatGPT | `+ menu` → `Add photos & files` | 1 | Shared | None | ✅ Good |
| Claude | `+ menu` → `Upload a file` | 1 | **Custom** | **Duplicates navigation** | 🔴 Fix |
| Gemini | `Attach` → `Upload files` | 2 | Shared | Overlays, selector fragility | 🟡 Monitor |
| Grok | `Attach` → `Upload a file` | 1 | Shared | None | ✅ Good |
| Perplexity | `Attach` → `Local files` | 1 | Shared | None | ✅ Good |

---

## Appendix: Code Locations

### Base Class (ChatInterface)
- Generic `attachFile()`: Lines 126-169 (UNUSED - all platforms override)
- Shared `_navigateFinderDialog()`: Lines 194-241

### Platform Overrides
- **Claude**: Lines 938-1005, 1150-1184
- **ChatGPT**: Lines 1233-1300, 1305-1339
- **Gemini**: Lines 1569-1655
- **Grok**: Lines 1903-1938
- **Perplexity**: Lines 2091-2109, 2114-2149

### CHAT_ELEMENTS.md Selectors
- ChatGPT: Lines 18-21
- Claude: Lines 59-76
- Gemini: Lines 95-97
- Grok: Lines 170-171
- Perplexity: Lines 188-189
