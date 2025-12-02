# Platform-Specific Selectors for Response Extraction

## Perplexity

### Artifact Download Flow

Perplexity creates artifacts during Pro Research mode. The complete extraction flow requires 3 steps:

#### Step 1: Artifact Banner (in main response)
```html
<button class="absolute inset-0 cursor-pointer appearance-none" data-testid="asset-card-open-button"></button>
```
**Purpose**: Click this button to open the artifact side panel

#### Step 2: Export Button (in side panel header)
```html
<button data-state="closed" aria-expanded="false" aria-haspopup="menu" type="button"
        class="reset interactable select-none font-semimedium font-sans text-center items-center justify-center leading-loose whitespace-nowrap text-quiet border border-solid border-subtler bg-base h-8 text-sm cursor-pointer origin-center flex w-full hover:bg-subtler hover:border-subtle px-3 rounded-lg justify-between data-[state=open]:bg-subtler data-[state=open]:border-subtle">
  <div class="flex min-w-0 flex-1 items-center">
    <div class="mr-1 shrink-0">
      <svg role="img" class="inline-flex fill-current" width="16" height="16">
        <use xlink:href="#pplx-icon-download"></use>
      </svg>
    </div>
    <span class="text-box-trim-both truncate pl-1 pr-1 min-w-0">Export</span>
  </div>
  <div class="ml-1 shrink-0">
    <svg role="img" class="inline-flex fill-current" width="14" height="14">
      <use xlink:href="#pplx-icon-chevron-down"></use>
    </svg>
  </div>
</button>
```
**Purpose**: Opens dropdown menu with export options
**Selector**: `button:has-text("Export")` in side panel

#### Step 3: Download Menu Item (in dropdown)
```html
<div role="menuitem"
     class="reset flex min-w-[calc(var(--radix-dropdown-menu-trigger-width)-theme(spacing.sm))] reset w-full gap-sm px-sm flex select-none items-center py-1.5 font-sans text-[13px] leading-loose text-foreground reset hover:bg-subtler cursor-pointer rounded-lg"
     data-orientation="vertical" tabindex="-1">
  <div class="flex shrink-0 items-center">
    <svg role="img" class="inline-flex fill-current" width="16" height="16">
      <use xlink:href="#pplx-icon-download"></use>
    </svg>
  </div>
  <div class="flex-1">
    <div class="flex flex-col gap-y-0.5">Download as File</div>
  </div>
</div>
```
**Purpose**: Triggers file download
**Selector**: `div[role="menuitem"]:has-text("Download as File")`

### Complete Download Flow
1. Click `[data-testid="asset-card-open-button"]` to open side panel
2. Wait for side panel to load
3. Click Export button in side panel header
4. Wait for dropdown menu
5. Click "Download as File" menu item
6. Handle download event

### Response Container
Standard response text is captured separately from artifacts - both must be combined for complete response.

## Implementation Notes
- Perplexity responses may have BOTH summary text AND artifact attachments
- `getLatestResponse()` should check for artifact banner and extract inline content
- `downloadArtifact()` uses the full 3-step download flow
- Artifacts can be code files, markdown documents, or other generated content

## Claude

### Artifact Extraction Flow (New Interface)

Claude's new interface shows artifacts in a sidebar panel. The extraction flow requires multiple steps to copy each artifact:

#### Step 1: Sidebar Toggle Button (top right of chat)
```html
<button class="inline-flex
  items-center
  justify-center
  relative
  shrink-0
  can-focus
  select-none
  disabled:pointer-events-none
  disabled:opacity-50
  disabled:shadow-none
  disabled:drop-shadow-none border-transparent
          transition
          font-base
          duration-300
          ease-[cubic-bezier(0.165,0.85,0.45,1)] h-8 w-8 rounded-md active:scale-95 Button_ghost__BUAoh" type="button" aria-label="Open sidebar" data-testid="wiggle-controls-actions-toggle">
  <div class="flex items-center justify-center" style="width: 20px; height: 20px;">
    <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg" class="shrink-0" aria-hidden="true">
      <path d="M11.5859 2C11.9837 2.00004 12.3652 2.15818 12.6465 2.43945L15.5605 5.35352C15.8418 5.63478 16 6.01629 16 6.41406V16.5C16 17.3284 15.3284 18 14.5 18H5.5C4.72334 18 4.08461 17.4097 4.00781 16.6533L4 16.5V3.5C4 2.67157 4.67157 2 5.5 2H11.5859ZM5.5 3C5.22386 3 5 3.22386 5 3.5V16.5C5 16.7761 5.22386 17 5.5 17H14.5C14.7761 17 15 16.7761 15 16.5V7H12.5C11.6716 7 11 6.32843 11 5.5V3H5.5ZM12.54 13.3037C12.6486 13.05 12.9425 12.9317 13.1963 13.04C13.45 13.1486 13.5683 13.4425 13.46 13.6963C13.1651 14.3853 12.589 15 11.7998 15C11.3132 14.9999 10.908 14.7663 10.5996 14.4258C10.2913 14.7661 9.88667 14.9999 9.40039 15C8.91365 15 8.50769 14.7665 8.19922 14.4258C7.89083 14.7661 7.48636 15 7 15C6.72386 15 6.5 14.7761 6.5 14.5C6.5 14.2239 6.72386 14 7 14C7.21245 14 7.51918 13.8199 7.74023 13.3037L7.77441 13.2373C7.86451 13.0913 8.02513 13 8.2002 13C8.40022 13.0001 8.58145 13.1198 8.66016 13.3037C8.88121 13.8198 9.18796 14 9.40039 14C9.61284 13.9998 9.9197 13.8197 10.1406 13.3037L10.1748 13.2373C10.2649 13.0915 10.4248 13.0001 10.5996 13C10.7997 13 10.9808 13.1198 11.0596 13.3037C11.2806 13.8198 11.5874 13.9999 11.7998 14C12.0122 14 12.319 13.8198 12.54 13.3037ZM12.54 9.30371C12.6486 9.05001 12.9425 8.93174 13.1963 9.04004C13.45 9.14863 13.5683 9.44253 13.46 9.69629C13.1651 10.3853 12.589 11 11.7998 11C11.3132 10.9999 10.908 10.7663 10.5996 10.4258C10.2913 10.7661 9.88667 10.9999 9.40039 11C8.91365 11 8.50769 10.7665 8.19922 10.4258C7.89083 10.7661 7.48636 11 7 11C6.72386 11 6.5 10.7761 6.5 10.5C6.5 10.2239 6.72386 10 7 10C7.21245 10 7.51918 9.8199 7.74023 9.30371L7.77441 9.2373C7.86451 9.09126 8.02513 9 8.2002 9C8.40022 9.00008 8.58145 9.11981 8.66016 9.30371C8.88121 9.8198 9.18796 10 9.40039 10C9.61284 9.99978 9.9197 9.81969 10.1406 9.30371L10.1748 9.2373C10.2649 9.09147 10.4248 9.00014 10.5996 9C10.7997 9 10.9808 9.11975 11.0596 9.30371C11.2806 9.8198 11.5874 9.99989 11.7998 10C12.0122 10 12.319 9.81985 12.54 9.30371ZM12 5.5C12 5.77614 12.2239 6 12.5 6H14.793L12 3.20703V5.5Z"></path>
    </svg>
  </div>
</button>
```
**Purpose**: Opens the artifacts sidebar panel
**Selector**: `button[aria-label="Open sidebar"][data-testid="wiggle-controls-actions-toggle"]`

#### Step 2: Artifact List Items (in sidebar)
```html
<div class="flex text-left font-ui rounded-lg overflow-hidden border-0.5 transition duration-300 w-full hover:bg-bg-000/50 px-4 border-border-300/15 hover:border-border-200 !m-0" role="button" tabindex="0" aria-label="Preview contents">
  <div class="artifact-block-cell group/artifact-block flex flex-1 align-start justify-between w-full">
    <div class="flex flex-1 gap-2 min-w-0">
      <!-- Icon section -->
      <div class="flex items-end w-[68px] relative shrink-0">...</div>
      <!-- Name and type -->
      <div class="flex flex-col gap-1 py-4 min-w-0 flex-1">
        <div class="leading-tight text-sm line-clamp-1">Demo</div>
        <div class="text-xs line-clamp-1 text-text-400 opacity-100 transition-opacity duration-200">PY&nbsp;</div>
      </div>
    </div>
    <!-- Download button -->
    <div class="flex min-w-0 items-center justify-center gap-2 shrink-0">...</div>
  </div>
</div>
```
**Purpose**: Clickable artifact item in the list
**Selector**: `div[role="button"][aria-label="Preview contents"]` (gets all artifacts)
**Name extraction**: Query `.leading-tight.text-sm` within each item to get artifact name

#### Step 3: Copy Button (in artifact view)
```html
<button class="font-base-bold !text-xs rounded-l-lg bg-bg-000 h-full flex items-center justify-center px-2 border-y border-l border-border-200 hover:bg-bg-200">Copy</button>
```
**Purpose**: Copies artifact content to clipboard
**Selector**: `button.font-base-bold:has-text("Copy")` in artifact viewer

#### Step 4: Back Button (return to artifact list)
```html
<button class="inline-flex
  items-center
  justify-center
  relative
  shrink-0
  can-focus
  select-none
  disabled:pointer-events-none
  disabled:opacity-50
  disabled:shadow-none
  disabled:drop-shadow-none border-transparent
          transition
          font-base
          duration-300
          ease-[cubic-bezier(0.165,0.85,0.45,1)] h-9 w-9 rounded-md active:scale-95 shrink-0 !rounded-lg Button_ghost__BUAoh" type="button" aria-label="Go back">
  <div class="flex items-center justify-center" style="width: 20px; height: 20px;">
    <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" xmlns="http://www.w3.org/2000/svg" class="shrink-0" aria-hidden="true">
      <path d="M13.2402 3.07224C13.4389 2.95131 13.7018 2.98306 13.8662 3.16013C14.0305 3.3371 14.0422 3.60087 13.9072 3.79001L13.8399 3.86619L7.2334 9.99998L13.8399 16.1338C14.0422 16.3216 14.054 16.6375 13.8662 16.8398C13.6784 17.0422 13.3625 17.054 13.1602 16.8662L6.16016 10.3662L6.0918 10.289C6.03247 10.2053 6 10.1043 6 9.99998C6.00002 9.86097 6.05829 9.72836 6.16016 9.63377L13.1602 3.13376L13.2402 3.07224Z"></path>
    </svg>
  </div>
</button>
```
**Purpose**: Returns to artifact list from individual artifact view
**Selector**: `button[aria-label="Go back"]`

### Complete Extraction Flow (Multiple Artifacts)
1. Click sidebar toggle to open artifacts panel
2. Get list of all artifact items
3. For each artifact:
   a. Click artifact item to view
   b. Click Copy button
   c. Read clipboard contents
   d. Click Back button to return to list
4. Save all artifacts with their names

### Implementation Notes
- Old download button approach no longer works in new Claude interface
- Must use clipboard-based copying for each artifact individually
- Need to iterate through all artifacts in the list
- Artifact names should be extracted from list items for proper file naming
