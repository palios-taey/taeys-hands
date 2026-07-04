# Residue Split Routing Audit

Pinned implementation commit: `c3e5cf9fe44af0f192a8c06cb2ec048516652218`.
Rebased base: `origin/main` at `aab81c5c394ea9cbc3782760489a8d5c919a3104`.

Task: `consult-platform-independence::residue-split-input-atspi`.

## Cannot-Lie Summary

Observed: the old shared platform routing in `consultation_v2/input.py`, `consultation_v2/atspi.py`, and `consultation_v2/platforms_runtime.py` has been split out of those modules.

Observed: the five chat platforms now own their URL and tab route data in package-local `routing.py` modules:
- `consultation_v2/platforms/chatgpt/routing.py`
- `consultation_v2/platforms/claude/routing.py`
- `consultation_v2/platforms/gemini/routing.py`
- `consultation_v2/platforms/grok/routing.py`
- `consultation_v2/platforms/perplexity/routing.py`

Observed: the residual shared core is mechanical:
- `consultation_v2/input.py`: raw key, click, hover, scroll, type, Firefox focus, and PID focus.
- `consultation_v2/atspi.py`: display detection, AT-SPI desktop traversal, raw Firefox enumeration, DocURL extraction, raw document-web enumeration, and file-dialog detection.
- `consultation_v2/platforms_runtime.py`: display allocation and screen runtime plumbing.

Inferred from GitNexus impact: this was a CRITICAL shared-routing split because the old AT-SPI routing helpers fed ChatGPT and Claude extraction/monitor flows. The direct indexed callers were remediated to package routing.

Unknown: `input.switch_to_platform` was not indexed by GitNexus, so its unreachability is proven by implementation diff, validator coverage, and runtime call-site diff rather than by GitNexus.

## Moved Routing

| Platform | Package route data | URL data | Tab data |
| --- | --- | --- | --- |
| ChatGPT | `consultation_v2/platforms/chatgpt/routing.py:11` | `chatgpt.com` | default `alt+1`, worker `alt+1` |
| Claude | `consultation_v2/platforms/claude/routing.py:11` | `claude.ai` | default `alt+2`, worker `alt+2` |
| Gemini | `consultation_v2/platforms/gemini/routing.py:11` | `gemini.google.com` | default `alt+3`, worker `alt+3` |
| Grok | `consultation_v2/platforms/grok/routing.py:11` | `grok.com`, extra `x.com/i/grok` | default `alt+4`, worker `alt+4` |
| Perplexity | `consultation_v2/platforms/perplexity/routing.py:11` | `perplexity.ai` | default `alt+5`, worker `None` |

The package modules call shared mechanics from `consultation_v2/platforms/_routing_core.py`, but the registry data lives in the owning package module. The dispatcher in `consultation_v2/platforms/routing.py` exists for shared runtime callers; platform packages do not import it.

## Shared-Core Reclassification

| Module | Leaf claim | Evidence |
| --- | --- | --- |
| `consultation_v2/input.py` | Leaf after split. No platform-specific routing function remains. | `focus_firefox_pid` is raw PID focus at `consultation_v2/input.py:186`; isolation lint includes the file as leaf at `consultation_v2/validators/lint_platform_independence.py:38`. |
| `consultation_v2/atspi.py` | Leaf after split. URL-to-platform and platform document matching moved out. | `document_web_elements` is raw document enumeration at `consultation_v2/atspi.py:103`; isolation lint includes the file as leaf at `consultation_v2/validators/lint_platform_independence.py:39`. |
| `consultation_v2/platforms_runtime.py` | Shared display/runtime, not route registry. | Module description and exports now cover screen/display plumbing starting at `consultation_v2/platforms_runtime.py:1`. |

## Call-Site Reroute

Observed:
- `ConsultationRuntime.switch`, `current_url`, popup dismissal, and scroll-point logic use `consultation_v2.platforms.routing`.
- `snapshot.build_snapshot`, `build_menu_snapshot`, and `build_app_root_snapshot` use package routing.
- Legacy ChatGPT and Claude driver extraction helpers use package routing.

These are the call sites GitNexus identified as affected for the old AT-SPI helpers, plus the runtime/snapshot shared callers found in the implementation diff.

## GitNexus Notes

Pre-edit impact results:
- `find_firefox_for_platform` in `consultation_v2/atspi.py`: CRITICAL, impactedCount 7, direct 4, 6 affected processes.
- `get_platform_document` in `consultation_v2/atspi.py`: CRITICAL, impactedCount 9, direct 3, 6 affected processes.
- `detect_platform_from_url` in `consultation_v2/atspi.py`: CRITICAL, impactedCount 8, direct 1, 5 affected processes.
- `switch_to_platform` in `consultation_v2/input.py`: UNKNOWN, target not indexed.

Pre-commit `mcp__gitnexus.detect_changes(scope=staged)` returned no changed symbols in this peer worktree. That result was recorded as a tool/worktree limitation, not as evidence that the diff was empty. The implementation evidence is the Git diff plus the impact call graph above.

Post-rebase `mcp__gitnexus.detect_changes(scope=compare, base_ref=origin/main)` and the same call with base commit `aab81c5c394ea9cbc3782760489a8d5c919a3104` returned no changed symbols in this peer worktree. That result is recorded as a detector limitation, not as evidence that the PR diff is empty. The implementation evidence is the rebased Git diff plus the explicit CRITICAL impact call graph above.

## Gate Results

Observed clean:
- `python3 -m py_compile ...` for all touched Python files.
- `python3 consultation_v2/validators/lint_platform_independence.py --all`
- `python3 consultation_v2/validators/lint_platform_independence.py --self-test`
- `python3 consultation_v2/validators/lint_exact_match.py`
- `python3 consultation_v2/validators/lint_no_yaml_silent_fallbacks.py --all`
- `python3 consultation_v2/validators/lint_consultation_v2_contract.py --all`
- Dispatcher smoke for all five package routing modules, ChatGPT URL match, Grok domain match, Grok `x.com/i/grok` match, Perplexity URL match, worker tab profile, and invalid `TAEY_TAB_PROFILE` fail-loud behavior.

Unknown: no live browser production run was executed from this branch; PR/r5 sequencing belongs after Grok PR #6.
