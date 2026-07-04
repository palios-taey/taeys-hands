# Residue Split Slice Diff

Pinned implementation commit: `c3e5cf9fe44af0f192a8c06cb2ec048516652218`.
Rebased base: `origin/main` at `aab81c5c394ea9cbc3782760489a8d5c919a3104`.
Observed diff range: `c3e5cf9^..c3e5cf9`.

## Name Status
```text
M	consultation_v2/atspi.py
M	consultation_v2/drivers/chatgpt.py
M	consultation_v2/drivers/claude.py
M	consultation_v2/input.py
A	consultation_v2/platforms/_routing_core.py
A	consultation_v2/platforms/chatgpt/routing.py
A	consultation_v2/platforms/claude/routing.py
A	consultation_v2/platforms/gemini/routing.py
A	consultation_v2/platforms/grok/routing.py
A	consultation_v2/platforms/perplexity/routing.py
A	consultation_v2/platforms/routing.py
M	consultation_v2/platforms_runtime.py
M	consultation_v2/runtime.py
M	consultation_v2/snapshot.py
M	consultation_v2/validators/lint_platform_independence.py
```

## Diffstat
```text
consultation_v2/atspi.py                           |  84 ++---------
consultation_v2/drivers/chatgpt.py                 |  12 +-
consultation_v2/drivers/claude.py                  |  12 +-
consultation_v2/input.py                           | 127 +++-------------
consultation_v2/platforms/_routing_core.py         | 167 +++++++++++++++++++++
consultation_v2/platforms/chatgpt/routing.py       |  32 ++++
consultation_v2/platforms/claude/routing.py        |  32 ++++
consultation_v2/platforms/gemini/routing.py        |  32 ++++
consultation_v2/platforms/grok/routing.py          |  33 ++++
consultation_v2/platforms/perplexity/routing.py    |  32 ++++
consultation_v2/platforms/routing.py               |  35 +++++
consultation_v2/platforms_runtime.py               |  49 +-----
consultation_v2/runtime.py                         |  15 +-
consultation_v2/snapshot.py                        |  11 +-
consultation_v2/validators/lint_platform_independence.py | 4 +
15 files changed, 422 insertions(+), 255 deletions(-)
```

## Slice Summary
- `consultation_v2/input.py` no longer owns platform tab/display routing. It retains raw xdotool primitives plus `focus_firefox_pid` at `consultation_v2/input.py:186`.
- `consultation_v2/atspi.py` no longer owns URL-to-platform routing or platform document lookup. It retains AT-SPI desktop plumbing, raw Firefox discovery, DocURL extraction, and raw document-web enumeration at `consultation_v2/atspi.py:40`, `consultation_v2/atspi.py:70`, `consultation_v2/atspi.py:92`, and `consultation_v2/atspi.py:103`.
- `consultation_v2/platforms_runtime.py` no longer exports URL patterns, base URLs, tab shortcuts, or platform class sets. It retains shared display and screen runtime plumbing.
- Each chat platform now has an owning `consultation_v2/platforms/<platform>/routing.py` module containing its URL patterns and tab routing data.
- `consultation_v2/platforms/_routing_core.py` is a package-routing helper. It accepts package-owned `RouteSpec` data and contains no platform registry.
- `consultation_v2/platforms/routing.py` is a dispatcher for shared runtime call sites; platform packages do not import it.
- Runtime, snapshot, and legacy ChatGPT/Claude driver call sites now route through `consultation_v2.platforms.routing` instead of importing routing helpers from `input.py` or `atspi.py`.
- `consultation_v2/validators/lint_platform_independence.py` reclassifies `input.py` and `atspi.py` as leaf modules and permits routing-only package directories for the four not-yet-extracted packages.
