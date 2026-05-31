# Deep Research Extraction Patterns — Per Platform

**Context**: When Perplexity / Gemini / ChatGPT produce a Deep Research report, the report itself is rendered as a **document artifact** separate from the thread's normal response landmark. The generic extract path (`read_element_text` on `response_landmark`) captures the thread wrapper (prompt + summary + search-step footnotes) but MISSES the artifact body. Every Deep Research platform has a different button to get at the artifact.

This doc records the exact path per platform. When YAML extract sequences need updating, this is the reference.

## Perplexity Deep Research

**Element**: `copy_contents_button` — `name: "Copy contents"`, `role: push button`, located at the top of the report card (y≈1800-2400 depending on thread length; x≈1240).

**Sequence**:
1. Navigate to the completed thread URL (or stay on it)
2. Find `Copy contents` push button in document snapshot
3. Click it (strategy: `atspi_only`)
4. Wait ~2s for clipboard to populate
5. Read clipboard → that IS the clean markdown report

**Output quality**: Proper `# TOPIC — TITLE` heading, structured sections (I./II./III.), inline URLs and citations, no prompt contamination. 50K chars typical for a good DR.

**DO NOT** use:
- Icon-row `Copy` button (y≈895 at thread bottom) — copies summary only
- `Download → Markdown` — gives transcript with hidden footnote refs, not the structured report
- `response_landmark` text read — gives thread wrapper, not artifact

## Gemini Deep Research

**Element**: The report has its own `Share & Export` push button at the top (y≈210, x≈1663). Clicking opens menu with: `Share report`, `Export to Docs`, `Copy`.

**Sequence**:
1. Navigate / confirm on completed thread
2. Click `Share & Export` push button (y≈210)
3. In menu, click `Copy` (menu item)
4. Read clipboard

**Output quality**: Has inline URLs (32+ typical) but returns as one long line (no paragraph breaks). That's the raw Gemini clipboard format.

**Better alternative (markdown with line breaks)**: click into report panel, `Ctrl+A`, `Ctrl+C`, read `text/html` clipboard via `xclip`, then `markdownify.markdownify(html, heading_style='ATX')`, strip header chrome ("Climate Orthodoxy and Policy Dissent..." as marker, strip back), strip footer chrome ("Your PALIOS-TAEY chats"). Gives ~140K chars, 1992 lines, 935+ URLs with full formatting.

**DO NOT** use:
- Regular `copy_button` on response — returns the 144-char "I've completed your research" blurb
- Share report → returns a public URL (valid but indirect)

## ChatGPT Deep Research

**Element**: ChatGPT DR stores the report in a Canvas artifact. At the top of the artifact card: `Download` button (icon), `Expand` button.

**Sequence**:
1. Navigate / confirm on completed chat
2. Find artifact card with `Download` push button (position varies per report; usually x≈1412, y≈385 range)
3. Click Download → may open format menu or trigger direct markdown download
4. (If menu) select Markdown / .md option
5. File appears in ~/Downloads

**Alternative (AT-SPI tree scrape)**: The full report text is stored as the `name` attribute of a `push button` element that wraps the artifact — a single element with `len(name) > 2000`. Grep for long push-button names containing topic keywords.

**DO NOT** use:
- `copy_button` (generic response Copy) — copies the thread summary
- The plan card's `Update` button — that's to START the research, not extract

## Key invariants

- Every DR platform renders the report as a **document artifact** not part of the thread transcript.
- `response_landmark` / `chat_transcript` text reads ALWAYS miss the artifact.
- The artifact has its own header bar with Copy/Download/Share controls.
- Use `atspi_only` click strategy for menu items (coordinate clicks often miss in Firefox DR panes).
- After click, wait ≥2s for clipboard to populate before reading.

## Why this matters

Training corpora are built from these extractions. Prompt contamination in the corpus TRAINS the model to re-emit the prompt pattern. Incomplete reports (summary only) lose the bulk of the cited sources. Both failure modes appear silent to the caller — file size looks reasonable, but content is wrong.
