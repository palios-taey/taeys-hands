# Residue Split Generative Disposition Table

Pinned implementation commit: `c3e5cf9fe44af0f192a8c06cb2ec048516652218`.
Rebased base: `origin/main` at `aab81c5c394ea9cbc3782760489a8d5c919a3104`.

Observed basis: implementation diff, `PLATFORM_INDEPENDENCE_SPEC.md` section 4, local validator output, and GitNexus impact results for the removed shared AT-SPI routing helpers. Claims are labeled as Observed, Inferred, or Unknown.

## Disposition

| Module | Disposition | Provenance |
| --- | --- | --- |
| `consultation_v2/input.py` | Observed: reclassified as leaf. Platform routing function `switch_to_platform(platform)` was removed. Remaining public primitives are raw keyboard, mouse, scroll, paste, Firefox focus, and PID focus operations. | `consultation_v2/input.py:25`, `consultation_v2/input.py:43`, `consultation_v2/input.py:79`, `consultation_v2/input.py:110`, `consultation_v2/input.py:129`, `consultation_v2/input.py:186`; lint reports 11 leaf modules. |
| `consultation_v2/atspi.py` | Observed: reclassified as leaf. Platform URL detection and platform document lookup were removed. Remaining public primitives are display detection, raw Firefox enumeration, DocURL extraction, raw document-web enumeration, and file-dialog probing. | `consultation_v2/atspi.py:20`, `consultation_v2/atspi.py:40`, `consultation_v2/atspi.py:70`, `consultation_v2/atspi.py:92`, `consultation_v2/atspi.py:103`, `consultation_v2/atspi.py:125`; lint reports 11 leaf modules. |
| `consultation_v2/platforms_runtime.py` | Observed: no longer owns platform URL patterns, base URLs, tab shortcuts, or chat/social platform sets. It remains shared display and screen runtime plumbing. | `consultation_v2/platforms_runtime.py:1`, `consultation_v2/platforms_runtime.py:10`, `consultation_v2/platforms_runtime.py:191`, `consultation_v2/platforms_runtime.py:217`. |
| `consultation_v2/platforms/_routing_core.py` | Observed: new shared routing mechanics parameterized by package-owned `RouteSpec`; no global platform registry. Preserves invalid `TAEY_TAB_PROFILE` fail-loud behavior. | `consultation_v2/platforms/_routing_core.py:16`, `consultation_v2/platforms/_routing_core.py:25`, `consultation_v2/platforms/_routing_core.py:38`, `consultation_v2/platforms/_routing_core.py:61`, `consultation_v2/platforms/_routing_core.py:74`, `consultation_v2/platforms/_routing_core.py:98`. |
| `consultation_v2/platforms/routing.py` | Observed: shared runtime dispatcher imports `consultation_v2.platforms.<platform>.routing` by validated platform name. Platform packages do not import this dispatcher. | `consultation_v2/platforms/routing.py:8`, `consultation_v2/platforms/routing.py:22`, `consultation_v2/platforms/routing.py:26`, `consultation_v2/platforms/routing.py:30`. |
| `consultation_v2/platforms/chatgpt/routing.py` | Observed: package owns ChatGPT URL and tab route data. | `consultation_v2/platforms/chatgpt/routing.py:11`. |
| `consultation_v2/platforms/claude/routing.py` | Observed: package owns Claude URL and tab route data. | `consultation_v2/platforms/claude/routing.py:11`. |
| `consultation_v2/platforms/gemini/routing.py` | Observed: package owns Gemini URL and tab route data. | `consultation_v2/platforms/gemini/routing.py:11`. |
| `consultation_v2/platforms/grok/routing.py` | Observed: package owns Grok URL, extra `x.com/i/grok` route, and tab route data. | `consultation_v2/platforms/grok/routing.py:11`, `consultation_v2/platforms/grok/routing.py:14`. |
| `consultation_v2/platforms/perplexity/routing.py` | Observed: package owns Perplexity URL and tab route data. Worker profile intentionally has no Perplexity tab shortcut. | `consultation_v2/platforms/perplexity/routing.py:11`, `consultation_v2/platforms/perplexity/routing.py:15`. |
| `consultation_v2/runtime.py` | Observed: runtime no longer imports platform routing from `input.py` or `atspi.py`; it uses the package dispatcher. | `consultation_v2/runtime.py:11`, `consultation_v2/runtime.py:153`, `consultation_v2/runtime.py:159`, `consultation_v2/runtime.py:182`, `consultation_v2/runtime.py:190`, `consultation_v2/runtime.py:373`, `consultation_v2/runtime.py:535`. |
| `consultation_v2/snapshot.py` | Observed: snapshot builders use the package dispatcher for Firefox/document resolution. | `consultation_v2/snapshot.py:10`, `consultation_v2/snapshot.py:638`, `consultation_v2/snapshot.py:647`, `consultation_v2/snapshot.py:703`, `consultation_v2/snapshot.py:706`, `consultation_v2/snapshot.py:789`. |
| `consultation_v2/drivers/chatgpt.py` | Observed: legacy driver call sites use the package dispatcher. | `consultation_v2/drivers/chatgpt.py:1549`, `consultation_v2/drivers/chatgpt.py:1552`, `consultation_v2/drivers/chatgpt.py:2085`, `consultation_v2/drivers/chatgpt.py:2117`, `consultation_v2/drivers/chatgpt.py:2129`. |
| `consultation_v2/drivers/claude.py` | Observed: legacy driver call sites use the package dispatcher. | `consultation_v2/drivers/claude.py:1184`, `consultation_v2/drivers/claude.py:1215`, `consultation_v2/drivers/claude.py:1351`, `consultation_v2/drivers/claude.py:1391`, `consultation_v2/drivers/claude.py:1566`, `consultation_v2/drivers/claude.py:1570`. |
| `consultation_v2/validators/lint_platform_independence.py` | Observed: `input.py` and `atspi.py` are now leaf lint targets; routing-only package dirs for flat-YAML platforms do not falsely fail driver-entry checks. | `consultation_v2/validators/lint_platform_independence.py:28`, `consultation_v2/validators/lint_platform_independence.py:38`, `consultation_v2/validators/lint_platform_independence.py:39`, `consultation_v2/validators/lint_platform_independence.py:307`. |

## GitNexus Risk Disposition

| Removed shared symbol | GitNexus impact before removal | Disposition |
| --- | --- | --- |
| `consultation_v2/atspi.py::find_firefox_for_platform` | Observed from GitNexus: CRITICAL, impactedCount 7, direct 4, 6 affected processes. Direct callers were ChatGPT `extract_primary`, Claude `extract_primary`, Claude `extract_thinking_notes`, and Claude `_copy_artifact_from_tree_controls`. | Observed: all direct indexed callers now import `consultation_v2.platforms.routing` and call `platform_routing.find_firefox_for_platform`. |
| `consultation_v2/atspi.py::get_platform_document` | Observed from GitNexus: CRITICAL, impactedCount 9, direct 3, 6 affected processes. | Observed: document lookup now lives behind package-owned routing modules; indexed driver/runtime/snapshot call sites use `platform_routing.get_platform_document`. |
| `consultation_v2/atspi.py::detect_platform_from_url` | Observed from GitNexus: CRITICAL, impactedCount 8, direct 1, 5 affected processes through `get_platform_document`. | Observed: the URL-to-platform function was removed; each package routing module owns its `url_matches` data. |
| `consultation_v2/input.py::switch_to_platform` | Unknown from GitNexus: target was not indexed and impact returned risk UNKNOWN. | Observed by diff/lint: the function was removed from `input.py`; runtime switching now calls `platform_routing.switch_to_platform`. |

Post-rebase `mcp__gitnexus.detect_changes(scope=compare, base_ref=origin/main)` and the same call with base commit `aab81c5c394ea9cbc3782760489a8d5c919a3104` returned no changed symbols in this peer worktree. That result is recorded as a detector limitation; the GitNexus evidence for the split is the explicit CRITICAL impact analysis above plus the rebased Git diff.

## Verification

```text
python3 -m py_compile consultation_v2/input.py consultation_v2/atspi.py consultation_v2/platforms/_routing_core.py consultation_v2/platforms/routing.py consultation_v2/platforms/chatgpt/routing.py consultation_v2/platforms/claude/routing.py consultation_v2/platforms/gemini/routing.py consultation_v2/platforms/grok/routing.py consultation_v2/platforms/perplexity/routing.py consultation_v2/runtime.py consultation_v2/snapshot.py consultation_v2/drivers/chatgpt.py consultation_v2/drivers/claude.py consultation_v2/validators/lint_platform_independence.py consultation_v2/platforms_runtime.py
python3 consultation_v2/validators/lint_platform_independence.py --all
python3 consultation_v2/validators/lint_platform_independence.py --self-test
python3 consultation_v2/validators/lint_exact_match.py
python3 consultation_v2/validators/lint_no_yaml_silent_fallbacks.py --all
python3 consultation_v2/validators/lint_consultation_v2_contract.py --all
python3 - <<'PY'
import os
from consultation_v2.platforms import routing
from consultation_v2.platforms._routing_core import tab_shortcut
from consultation_v2.platforms.chatgpt import routing as chatgpt_routing
from consultation_v2.platforms.perplexity import routing as perplexity_routing
for p in ['chatgpt', 'claude', 'gemini', 'grok', 'perplexity']:
    mod = routing._route_module(p)
    print(p, mod.__name__, mod.url_matches('https://example.com'))
print('chatgpt', routing.platform_url_matches('chatgpt', 'https://chatgpt.com/c/abc'))
print('grok-x', routing.platform_url_matches('grok', 'https://x.com/i/grok'))
print('grok-domain', routing.platform_url_matches('grok', 'https://grok.com/'))
print('perplexity', routing.platform_url_matches('perplexity', 'https://perplexity.ai/search'))
os.environ['TAEY_TAB_PROFILE'] = 'worker'
print('worker-chatgpt-tab', tab_shortcut(chatgpt_routing._SPEC))
print('worker-perplexity-tab', tab_shortcut(perplexity_routing._SPEC))
os.environ['TAEY_TAB_PROFILE'] = 'bogus'
try:
    tab_shortcut(chatgpt_routing._SPEC)
except RuntimeError as exc:
    print('invalid-profile', str(exc))
else:
    raise SystemExit('invalid profile did not fail')
PY
```

Observed results: compile exited 0; platform isolation lint CLEAN with 5 packages, 11 leaf modules, 0 findings; self-test PASS; exact-match lint PASS; YAML silent fallback lint CLEAN; consultation_v2 contract lint CLEAN; dispatcher smoke matched ChatGPT, Grok domain, Grok x.com, and Perplexity URLs, preserved worker Perplexity no-tab behavior, and failed loudly on invalid `TAEY_TAB_PROFILE`.

Unknown: no live browser consultation was run from this branch. This slice is ready for PR/r5 review after Grok PR #6 sequencing.
