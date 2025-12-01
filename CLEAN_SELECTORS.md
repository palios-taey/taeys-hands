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
