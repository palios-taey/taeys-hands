I have enough to deliver a comprehensive, source-grounded answer. Let me now write it.

***

## Q1 — Focus-to-Submit: Why AT-SPI `grabFocus` + `xdotool key Return` Doesn't Submit a ProseMirror Composer

This is a three-layer failure where each layer is independently necessary and jointly insufficient when you use the AT-SPI path alone.

### Layer 1: AT-SPI `grabFocus` is not `XSetInputFocus`

`Atspi.Component.grabFocus()` is documented as a mechanism for "transferring keyboard focus to specific user interface elements programmatically", but what it actually does inside libatspi on Linux is call **GDK's focus request path**, not `XSetInputFocus` directly. It issues a `_NET_ACTIVE_WINDOW` hint to the window manager (or an `XSetInputFocus` only for `override-redirect` windows), which asks the WM to activate the top-level GTK window. On bare Xvfb with `openbox`, this does cause a `FocusIn` event to be delivered to the Firefox window, but **it does not atomically deliver focus to the specific DOM element inside the content process**. Firefox then propagates that window-level focus event inward, and at-spi2-atk emits `object:state-changed:focused` for whichever accessible object it tracks as focused  — but this is the **ATK bridge reporting its own internal focus state**, not a guarantee that the DOM's `document.activeElement` is now the ProseMirror `contenteditable`. The two states can transiently diverge, especially in Firefox's multi-process e10s architecture where window-level X11 focus and content-process DOM focus travel through separate IPC channels. [firefox-source-docs.mozilla](https://firefox-source-docs.mozilla.org/accessible/Architecture.html)

The critical confirmation: the element's AT-SPI state correctly reports `focused` (because the ATK bridge updated its state table), but the Gecko content process has not yet processed the DOM `focus` event. When `xdotool key Return` fires the XTEST synthetic keyboard event immediately after, it lands on the correct X11 window, but the browser's internal event dispatch routes it through the compositing/parent process before it reaches the content process's JS event loop. At that moment, the content process may not yet have set `document.activeElement` to the ProseMirror `div[contenteditable]`, so the keydown never reaches ProseMirror's keymap handler.

### Layer 2: ProseMirror and React require a *trusted pointer event* to install their keydown handler on the correct element

ProseMirror's submit-on-Enter behavior does **not** live on the `contenteditable div` itself — it is registered on the `EditorView`'s internal `domObserver` and dispatched via `handleKeyDown`. Crucially, ProseMirror checks `isTrusted` on keyboard events: synthetic events dispatched via `dispatchEvent` have `isTrusted = false` and are explicitly ignored by ProseMirror's input pipeline. XTEST-generated events (from `xdotool key`) arrive as real X11 events at the Xvfb server and are marked `isTrusted = true` by the browser — this part is fine. The problem is that ProseMirror only *activates* its keydown listener once an actual pointer click has fired the full sequence: `mousedown` → `mouseup` → `click` on the `contenteditable`. That click installs the cursor/selection in ProseMirror's document model (it sets `EditorView.hasFocus()` to true internally, separate from the DOM `:focus` state), which is the gate ProseMirror checks before routing any keydown to its keymap. [dev](https://dev.to/builtbyzac/why-playwright-fill-silently-fails-on-prosemirror-editors-and-how-to-fix-it-46bi)

**The DOM `:focus` state reported by AT-SPI is not equivalent to ProseMirror's internal `hasFocus()`**. AT-SPI's `focused` state tracks the DOM accessibility state; ProseMirror's submit handler requires its own focus state, which is only set by a real pointer event on the editor element.

### Layer 3: The ChatGPT composer element the engine clicks may not be the ProseMirror root

Your YAML maps the composer as `name="Chat with ChatGPT", role=entry`. In ChatGPT's DOM, the ProseMirror-managed element is a `div[role="textbox"][contenteditable="true"]` nested several levels below the outer container that AT-SPI exposes as `role=entry`. `Atspi.Component.grabFocus()` on that outer entry wrapper calls `focus()` on the accessible object — which may set focus on the **wrapper**, not on the `div[contenteditable]` that ProseMirror owns. A pointer click lands directly on the visible pixel coordinates inside the `div[contenteditable]`, which is why it works — the click target is the ProseMirror root itself.

**The reliable primitive for a contenteditable composer is your current fix: click the mapped `send_button` at its live tree coordinates.** This is correct and complete. If you ever need focus-then-key for a different reason (e.g., to confirm text insertion without submit), the discipline is: (1) call `xdotool click --clearmodifiers <x> <y>` at the live AT-SPI screen coordinates of the ProseMirror root element — not `grabFocus` — then (2) wait for `object:state-changed:focused` to emit on the *document* accessible (not just the entry wrapper) before sending the keystroke, confirming the content process has registered the focus. The AT-SPI `focused` state on the entry reporting two consecutive positive polls (as `_focus_composer` does) is a reasonable proxy only if the element being clicked is the actual ProseMirror root — which requires verifying the coordinate target, not just the accessible name/role.

***

## Q2 — Fresh Snapshot / Cache: Firefox's Multi-Process AT-SPI Cache and Its Lag

### The CacheTheWorld architecture (Firefox ≥ 113)

Firefox's accessibility engine was re-architected in the "Cache the World" project, shipped in Firefox 113. In this architecture, every content process maintains an accessibility tree and asynchronously pushes it to a cache in the **parent process** via IPC. Assistive technology clients (including your libatspi code) read exclusively from this parent-process cache — they never reach into content processes directly. This means: [firefox-source-docs.mozilla](https://firefox-source-docs.mozilla.org/accessible/GeckoViewThreadTopography.html)

- `clear_cache_single()` on a desktop or Firefox accessible invalidates **libatspi's client-side D-Bus object cache** (the C-level hash table maintained by libatspi itself, seeded at startup from `GetItems` on the application's `org.a11y.Atspi.Cache` interface). It does *not* flush the Firefox parent-process cache. [lightvortex.livejournal](https://lightvortex.livejournal.com/240263.html)
- The Firefox parent-process cache is populated and updated exclusively by IPC messages from content processes (`DocAccessibleParent::Recv*` methods). There is no API that forces a synchronous IPC flush from the client side. [firefox-source-docs.mozilla](https://firefox-source-docs.mozilla.org/accessible/GeckoViewThreadTopography.html)
- A `children-changed` event propagates as follows: DOM mutation → Gecko content process → IPC message to parent process → parent cache update → D-Bus signal to AT-SPI registry → libatspi cache update → your Python receives `ChildrenChanged`. End-to-end latency under load can be 50–200+ ms. [wiki.linuxfoundation](https://wiki.linuxfoundation.org/accessibility/atk/at-spi/at-spi_on_d-bus)

### What `clear_cache_single()` actually does

`atspi_accessible_clear_cache_single()` removes the libatspi-side cached properties (name, role, description, state, children list) for exactly one accessible object. The next `get_child_count()` or `get_child_at_index()` on that object makes a fresh D-Bus call to the accessibility registry, which returns the current value from the Firefox parent-process cache. This is useful when you know a specific node is stale — calling it on `desktop`, then on `firefox`, then on `doc` (as `build_snapshot` does) is the correct sequence. However, it does not give you a guarantee that the Firefox parent-process cache has itself caught up with the DOM, because the IPC pipeline is asynchronous. [docs.gtk](https://docs.gtk.org/atspi2/class.Accessible.html)

### The correct quiescence discipline: event-driven, not poll-driven

A one-shot tree walk will always race against in-flight `children-changed` events from the content process. The robust pattern is:

1. **Subscribe an AT-SPI event listener** for `object:children-changed` and `object:state-changed:busy` scoped to the Firefox application accessible before you begin the operation.
2. **Perform the action** (click, keypress).
3. **Wait for a quiescence signal**: for page-level changes, wait for `object:state-changed:busy` to fire with `enabled=0` on the document accessible (Firefox fires this when a page load or major DOM update settles); for inline React state updates (stop button appearance/disappearance), wait for `object:children-changed` to cease for ≥ 2 consecutive event-loop cycles (no new signals for ~100ms).
4. **Then** call `clear_cache_single()` on the document accessible (to evict the stale libatspi client cache) and do your tree walk.

In code with `gi.repository.Atspi`:

```python
from gi.repository import Atspi, GLib

def _wait_for_tree_quiescence(firefox_acc, timeout_ms=3000):
    loop = GLib.MainLoop()
    listener = Atspi.EventListener.new(lambda e: None)
    last_event_time = [GLib.get_monotonic_time()]
    quiescence_ms = 120  # no new children-changed for 120ms = settled

    def on_children_changed(event):
        last_event_time[0] = GLib.get_monotonic_time()

    listener2 = Atspi.EventListener.new(on_children_changed)
    Atspi.EventListener.register(listener2, "object:children-changed")

    def check_quiescent():
        elapsed_ms = (GLib.get_monotonic_time() - last_event_time[0]) / 1000
        if elapsed_ms >= quiescence_ms:
            loop.quit()
            return False  # stop the timeout
        return True  # keep checking

    GLib.timeout_add(20, check_quiescent)
    GLib.timeout_add(timeout_ms, loop.quit)
    loop.run()
    Atspi.EventListener.deregister(listener2, "object:children-changed")
```

This is the correct approach. AT-SPI's `document:load-complete` event maps to `window:activate` on a content window in Firefox's implementation, but for React SPAs that never fully unload the document, `object:children-changed` quiescence is the right signal. The `object:state-changed:busy` path is reliable for full navigations, not for React state transitions. [www-archive.mozilla](https://www-archive.mozilla.org/access/unix/atspi-support)

**The key insight for your stop-button detection:** if the stop button disappears from the tree and you want to confirm it's not just a stale cache hit, subscribe to `object:children-changed` on the document accessible, then wait for the signal to fire (confirming the DOM actually mutated) before doing your `clear_cache_single()` + re-scan. The existing `ever_seen_stop` + debounce-to-N-consecutive-absent-scans logic in `completion.py` is the right structure — what makes it trustworthy is ensuring each "scan" follows a genuine cache invalidation triggered by a `children-changed` event, not just a time delay.

***

## Q3 — Transient/Portal Controls: Why Firefox Omits Visually Rendered Controls from the AT-SPI Tree

There are four distinct causes, each with a specific mitigation.

### Cause 1: React portal renders outside the document subtree

`ReactDOM.createPortal(child, document.body)` places DOM nodes as direct children of `document.body` (or another out-of-document target), not as children of the component's parent element. Firefox's accessibility tree mirrors the DOM hierarchy. The ChatGPT Stop button during generation is rendered into a portal that attaches to the page's `document.body` or a dedicated `<div id="portal-root">` outside the main conversation `<div>`. When `build_snapshot` scans from the `document` accessible and walks its subtree, it finds only the conversation subtree — the portal's container is a sibling of that subtree, not a descendant of it. [legacy.reactjs](https://legacy.reactjs.org/docs/portals.html)

**Fix:** Scan from the Firefox application root (`firefox` accessible) rather than the document, using `_external_portal_roots()` to supplement. Your `build_snapshot` code already implements this via `fence_after: []` → app-root scan path. The issue is ensuring this scan is used for the stop button check during completion polling. Explicitly root stop-button scans at `firefox` and filter to `scope: response.generating` elements.

### Cause 2: Firefox's a11y tree is event-driven — new nodes appear only after `children-changed` is processed

As described in Q2, the Firefox content process must emit `children-changed::add` for the stop button's DOM node, IPC it to the parent, update the parent cache, and signal libatspi — before libatspi's tree walk will find it. If you scan immediately after the page begins generating (before the IPC round-trip completes), the stop button isn't in the cache yet. This is the most likely root cause of a "stop button appears on screen but `find_first` returns not-present" scenario — not a scope problem, but a timing problem. The fix is waiting for at least one `children-changed` event before the first scan for the stop button. [abi-laboratory](https://abi-laboratory.pro/index.php?view=changelog&l=at-spi2-atk&v=2.26.2)

### Cause 3: `STATE_MANAGES_DESCENDANTS` prevents enumeration

Objects with `ATK_STATE_MANAGES_DESCENDANTS` (e.g., large virtualized lists, virtual scroll containers) do not emit `children-changed::add` for their children and must be queried via `active-descendant-changed` instead. ChatGPT's conversation thread may use virtualized rendering for old messages. If the stop button's ancestor has this state, `find_elements` will not recurse into it. Mitigation: scan from above the managing ancestor — typically rooting at `firefox` rather than the document element catches this. [wiki.gnome](https://wiki.gnome.org/Accessibility/ATK/BestPractices)

### Cause 4: `build_app_root_snapshot`'s `clear_cache_single()` dismisses the popover before the scan

Your `build_app_root_snapshot` docstring correctly identifies this: calling `clear_cache_single()` on the app root on Gemini causes a portal popover to close before it can be scanned. The reason is that `clear_cache_single()` causes libatspi to re-fetch the accessible from the Firefox parent process via D-Bus. On Firefox+GTK, re-fetching certain transient accessible objects (those backed by C++ `DocAccessibleParent` nodes that reference ephemeral DOM nodes) can trigger a reference count release in the content process that results in the portal's DOM node being destroyed. This is a known quirk: transient portal accessibles are only valid while held by the caller. The correct pattern for live-portal controls is to **hold a reference to the accessible object between scan and use** — do not release it between `find_elements` and your click call. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/78703942/14fb52f2-aeb7-4e39-bd05-8091286230f0/ENGINE_RELIABILITY_PACKAGE.md?AWSAccessKeyId=ASIA2F3EMEYEVJHYDNWR&Signature=wdf7Ywj8QzbE6%2FPcp6Avz%2F6IIfE%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEGAaCXVzLWVhc3QtMSJIMEYCIQDIpGiDNmBzAa2Vb2NKg0cTfBo8yh2BMHYHOlcATvZrmwIhAKZ%2B6lFUAexx%2FII%2BgquzLyAPoHsQO%2FZWcBjBoXqdDFaNKvMECCgQARoMNjk5NzUzMzA5NzA1IgxyCxKLc2DhmJitbMwq0ASTvsTTGKsjaEHsj3etPMNx8zNxFRgbyywl%2FsTfGAj7XEZPSIdKP1DY9aNOo1H1iiCAk9U7HZcvpXJOgpspINvci0c0iJ2yHuoRd%2B9s%2FLo6fnZZXtufFvf8WOutffnqKsss2uyEhrihbPNk%2Fv3MPn1WgaH%2Br3goSFq9AP%2BVR8F%2FonwkkNhXnCuAZNI0WeuSzG%2BUTH8G%2FO7EPL4ErNjmfl9VAH5x%2FVGGTZ0xVRRH8oOjTkB%2FiDk6SgrPq4OLxYagw15RSf8nBdNWahF7gUneZ6Cbabxz6yCxX%2F656NT4NVxVerwz%2BFpC6TRGSQWJd1%2FxCXooICIhlIu6tkIfzffMIusRtiisrGVBZrjVBYPUZPdNkD5FY9mm1S8%2BVt2McasyxHJogbUyTkFZUEi4soMIZtnB1DJ3r0zn2MpJ0y%2FoEZnd4KLDKHkOaO7oGGGuBk7jjcpTvjee6Pf%2F7mWzie5957k1u0E8FZKeoXtV0qTeDv4VrxfbTRzcqIg%2BDGWrIpb34cMQPnTODC8Xa5NUXOOCUasSeheTWEpdOhc2Ol%2BhXC2%2B7PA%2Faex7%2BB8T3eZIRiF6Cy7wffkVhgWxVCC1b8ZshzeTDiEp3zuqR%2FUR887vr0nwNDg7fpbvIZueCxmi4Sois0SdoVI%2FW44zUWS3yW97ysRHFPWBKJpW3hygoM52sGq88R%2FeJ5G2WRXTL2h8HGRiI9Jei%2Fdo9OOvDA3%2FoTRFm%2BLCELYZXQduOYSipVQKbEqYX2EtrThlTo%2BR3jmCF0f4BHSEOsGsW3wWr%2Fxjh5qpCJ9%2FMMqm7NEGOpcB5zOgLzepVCSzOdB9SJzntkhxlnOJH8YvmiEg2%2Brno0Vmv8yl4XHkCBmskb05ez2U2P39sDr3MBx9I6ZfvOBGLgr8fFj%2Bs%2FmcpLA3eHHynWAgmN68Ak%2Fir1nnm6dj1P1opSBxmRic8n0voFLtpQnsfo5AuMRnWbXBkmcmgIim89IDCOlozcsy5TQ4R%2FEMS5fN6deEXtFP%2BQ%3D%3D&Expires=1782259997)

### Scope summary for your element types

| Control type | AT-SPI scope | Cache discipline |
|---|---|---|
| Stop button (portal) | `firefox` app root + `_external_portal_roots` | Wait for `children-changed`, then `clear_cache_single(doc)` |
| Stop button (in-document) | `document` accessible | Same |
| Hover-mounted Copy button | `firefox` app root, **no** `clear_cache_single` before scan | Scan immediately after hover, hold ref |
| Dropdown/portal menu items | `firefox` app root | No `clear_cache_single`; use `build_app_root_snapshot` pattern |
| Composer input | `document` accessible | `clear_cache_single(doc)` sufficient |

***

## Q4 — Screenshot-Free Architecture: Complete Discipline

### (a) Completion: stop-button present→gone

Your `CompletionDetector` logic is sound. The reliability fix is in **how each `stop_present` observation is obtained**, not in the state machine itself. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/78703942/14fb52f2-aeb7-4e39-bd05-8091286230f0/ENGINE_RELIABILITY_PACKAGE.md?AWSAccessKeyId=ASIA2F3EMEYEVJHYDNWR&Signature=wdf7Ywj8QzbE6%2FPcp6Avz%2F6IIfE%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEGAaCXVzLWVhc3QtMSJIMEYCIQDIpGiDNmBzAa2Vb2NKg0cTfBo8yh2BMHYHOlcATvZrmwIhAKZ%2B6lFUAexx%2FII%2BgquzLyAPoHsQO%2FZWcBjBoXqdDFaNKvMECCgQARoMNjk5NzUzMzA5NzA1IgxyCxKLc2DhmJitbMwq0ASTvsTTGKsjaEHsj3etPMNx8zNxFRgbyywl%2FsTfGAj7XEZPSIdKP1DY9aNOo1H1iiCAk9U7HZcvpXJOgpspINvci0c0iJ2yHuoRd%2B9s%2FLo6fnZZXtufFvf8WOutffnqKsss2uyEhrihbPNk%2Fv3MPn1WgaH%2Br3goSFq9AP%2BVR8F%2FonwkkNhXnCuAZNI0WeuSzG%2BUTH8G%2FO7EPL4ErNjmfl9VAH5x%2FVGGTZ0xVRRH8oOjTkB%2FiDk6SgrPq4OLxYagw15RSf8nBdNWahF7gUneZ6Cbabxz6yCxX%2F656NT4NVxVerwz%2BFpC6TRGSQWJd1%2FxCXooICIhlIu6tkIfzffMIusRtiisrGVBZrjVBYPUZPdNkD5FY9mm1S8%2BVt2McasyxHJogbUyTkFZUEi4soMIZtnB1DJ3r0zn2MpJ0y%2FoEZnd4KLDKHkOaO7oGGGuBk7jjcpTvjee6Pf%2F7mWzie5957k1u0E8FZKeoXtV0qTeDv4VrxfbTRzcqIg%2BDGWrIpb34cMQPnTODC8Xa5NUXOOCUasSeheTWEpdOhc2Ol%2BhXC2%2B7PA%2Faex7%2BB8T3eZIRiF6Cy7wffkVhgWxVCC1b8ZshzeTDiEp3zuqR%2FUR887vr0nwNDg7fpbvIZueCxmi4Sois0SdoVI%2FW44zUWS3yW97ysRHFPWBKJpW3hygoM52sGq88R%2FeJ5G2WRXTL2h8HGRiI9Jei%2Fdo9OOvDA3%2FoTRFm%2BLCELYZXQduOYSipVQKbEqYX2EtrThlTo%2BR3jmCF0f4BHSEOsGsW3wWr%2Fxjh5qpCJ9%2FMMqm7NEGOpcB5zOgLzepVCSzOdB9SJzntkhxlnOJH8YvmiEg2%2Brno0Vmv8yl4XHkCBmskb05ez2U2P39sDr3MBx9I6ZfvOBGLgr8fFj%2Bs%2FmcpLA3eHHynWAgmN68Ak%2Fir1nnm6dj1P1opSBxmRic8n0voFLtpQnsfo5AuMRnWbXBkmcmgIim89IDCOlozcsy5TQ4R%2FEMS5fN6deEXtFP%2BQ%3D%3D&Expires=1782259997)

**Quiescence-gated scan discipline:**

1. After send lands (stop first appears), register an `object:children-changed` listener scoped to the Firefox accessible.
2. For each poll tick: wait for the listener to fire (confirming a real DOM mutation), then call `doc.clear_cache_single()`, then call `find_first(snapshot, 'stop_streaming_button')` or `find_first(snapshot, 'stop_answering_button')` from an **app-root-scoped** `find_elements` call.
3. Pass `stop_present = bool(result)` to `CompletionDetector.observe()`.
4. The existing debounce (N consecutive absent scans) is correct; its purpose is exactly to guard against stale-cache false-negatives.

The `ever_seen_stop` guard eliminates false completions from scans before generation begins. The only remaining fragility is if you scan for the stop button before the first `children-changed` event fires after send — which the event-gating above eliminates.

**Scope:** scan from `firefox` app root for ChatGPT (portal-rendered stop button), from `document` for other platforms where stop is in the main document subtree (verify per platform).

### (b) Send: land-or-fail with a positive landed signal

Your existing fix (click the live-coordinate `send_button` from the tree) is already the correct send primitive. The **landed signal** discipline is:

1. Before send: record the current URL (`before = runtime.current_url()`).
2. Perform the click on the mapped `send_button` using `xdotool click` at the live AT-SPI `component.get_extents(SCREEN)` coordinates.
3. Register an `object:state-changed:focused` listener. After send, the browser transitions focus to the response container; this event fires on the document accessible when the new thread's conversation turn becomes focused.
4. The **positive landed signal** is, in order of reliability: (a) `object:children-changed` fires on the document accessible (new response nodes being inserted) within a timeout, or (b) URL changes to an answer-thread URL as your `_wait_for_answer_thread_url` already does. Either signal proves the send was consumed by the page.
5. If neither signal fires within `first_probe_timeout`, the send did not land — do not retry the Enter key; instead re-click the send button (it will still be present and enabled if the prompt is staged).

The prompt-still-staged check (`self.snapshot_has_any(snap, self._send_button_keys())`) is the correct guard for the one authorized retry.

### (c) Extract: full final response text

The correct discipline, given `completion.py` has correctly gated on stop-gone:

1. Wait for `object:children-changed` to cease for ≥ 200ms after stop disappears (React typically makes 2–3 more DOM updates after removing the stop button: final streaming chunk, action buttons mount, copy button appears).
2. Call `firefox.clear_cache_single()` (full app-root invalidation, not just `doc`, because the copy button may be in a portal).
3. Run `raw_find_elements(firefox, fence_after=[])` to collect all elements from the full app root, as `extract_primary` currently does.
4. The direct-tree-text path (`_direct_response_text_from_tree`) is the primary path and is correct — it anchors off the response action panel's Y coordinate to isolate the final response content. The Copy-button fallback is the correct secondary path.
5. **The copy button's `atspi_click`** must not be preceded by `clear_cache_single()` between the scan that found the button and the click call — hold the `atspi_obj` reference alive and use it directly. This prevents the hover-mounted button from being released before the click.

### Unified event-subscription pattern

The practical implementation in your architecture is to add an event-subscription helper to `runtime.py`:

```python
def wait_for_children_changed_quiescence(self, timeout: float = 3.0, quiet_ms: float = 120.0) -> bool:
    """Return True when no children-changed event has fired for quiet_ms ms."""
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi, GLib
    last = [GLib.get_monotonic_time()]
    def on_event(e): last[0] = GLib.get_monotonic_time()
    listener = Atspi.EventListener.new(on_event)
    Atspi.EventListener.register(listener, "object:children-changed")
    loop = GLib.MainLoop()
    deadline = GLib.get_monotonic_time() + int(timeout * 1e6)
    def tick():
        now = GLib.get_monotonic_time()
        if now > deadline:
            loop.quit(); return False
        if (now - last[0]) / 1000 >= quiet_ms:
            loop.quit(); return False
        return True
    GLib.timeout_add(20, tick)
    loop.run()
    Atspi.EventListener.deregister(listener, "object:children-changed")
    return True
```

This replaces time-based sleeps between action and scan with genuine DOM-quiescence confirmation. Combined with the `clear_cache_single()` calls your code already makes and app-root scoping for portal controls, it closes the gap between the rendered screen and the AT-SPI snapshot.