Here is the adversarial audit of `CONSULTATION_CONTRACT.md`.

Your contract is a beautifully ruthless constraint system. By banning fuzzy heuristics and forcing a binary match-or-notify loop, you structurally eliminate the silent hallucinations and state-rot that plague most browser-automation agents.

However, applying strict Boolean logic (`match == true || halt()`) to asynchronous, state-mutating browser DOMs via AT-SPI polling will currently break your engine. You have conflated transient visual states with durable logical states, and made naive assumptions about accessibility tree boundaries.

Here is where the binary breaks, prioritized by severity, and the concrete amendments required to close the holes.

---

### (a) GAPS (Unmapped States & Transitions)

**1. The Same-Chat "New URL" Trap**

* **The Break:** The contract states `Submit succeeded = new chat URL + Stop button appeared`. This AND condition makes Turn 2 of any consultation impossible. The URL *does not change* when submitting a follow-up message in an existing chat. The engine will permanently halt on message #2.
* **The Amendment:** Bifurcate the validation invariant. `Submit (New Chat) = URL change + Stop appeared`. `Submit (Same Chat) = URL identical + Response node container incremented + Stop appeared`.

**2. The "Stop Gone = Complete" Silent Failure**

* **The Break:** The contract defines completion negatively: `Complete = Stop gone`. If a rate limit triggers, an "Unsafe Content" filter hits, or the WebSocket drops mid-generation, the Stop button instantly vanishes. The engine will evaluate `Stop gone -> Complete`, scrape the error (or an empty string) as a successful payload, and proceed without ever triggering a HALT.
* **The Amendment:** Define positive completion. `Complete = Stop gone AND ("Continue Generating" button is absent) AND (Mapped error elements are absent)`.

**3. OS Window-Manager Context Loss**

* **The Break:** *"Every menu... mapped exact."* Clicking "Attach" often spawns a native OS file picker (GTK/KDE). This is a completely different application root in the AT-SPI tree (`org.a11y.atspi.Desktop`). The browser tree pauses. The engine will scan the browser, see no UI, wait, and HALT.
* **The Amendment:** Map a `System Boundary` context shift. When triggering an OS dialog, the driver must be instructed by the YAML to pivot its AT-SPI root to the Desktop namespace, execute the mapped path-paste, and pivot back.

**4. The Transient Fast-Gen Race Condition**

* **The Break:** `Generating = Stop present.` If an AI hits a cache and outputs "Yes" in 100ms, the Stop button will mount and unmount *between* your AT-SPI polling ticks. The engine evaluates the submit, never sees the Stop button, assumes the submit click failed, rescans, and falsely HALTs.
* **The Amendment:** Never use a purely transient element as a strict blocking gate. `Submit succeeded = Stop appeared OR (Stop never appeared BUT target response text node is populated)`.

---

### (b) CONTRADICTIONS / AMBIGUITIES

**5. The Sibling Multiplicity Ambiguity**

* **The Break:** *"MATCHES the mapped YAML (exact name+role)"*. In ChatGPT, every completed message has a "Copy" button. On turn 5, there are five identical elements. The binary match is ambiguous. If the driver picks `matches[-1]` or `matches[0]`, it is secretly applying a heuristic guess.
* **The Amendment:** Enforce structural uniqueness. If an exact match yields `N > 1` elements, it is an automatic NO-MATCH (drift). The YAML must support `parent_name` or an explicit `path_index` to isolate the single target.

**6. The Disabled Ghost Element**

* **The Break:** *"Nothing is ever hidden."* In React, a "Send" button blocked by an ongoing file upload retains its exact name and role in the AT-SPI tree, it just lacks the `STATE_ENABLED` flag. The engine will match it exactly, click a dead button (doing nothing), and hang waiting for "Stop".
* **The Amendment:** Include AT-SPI state in the binary identity. `Exact Match = Exact Name + Exact Role + AT-SPI State (ENABLED)`.

**7. Stop-Button Platform Knowledge**

* **The Break:** The contract claims `claude-code-fleet-notify` owns Stop-button detection, AND that shared code carries zero platform knowledge. To find the Stop button without fuzziness, the monitor must know its exact name/role per platform, violating the knowledge boundary.
* **The Amendment:** The exact Stop-button definition must live in the platform YAML. The driver passes this exact schema object to the monitor layer upon dispatch.

---

### (c) CASES THE BINARY GENUINELY CAN'T EXPRESS

**8. Dynamic Response Content (The "Mapped Exact" Paradox)**

* **The Break:** *"The completed screen mapped exact."* In AT-SPI, the `name` of a text node IS the generated text itself. You cannot exact-map an AI's unpredictable response string. If enforced, the engine halts on the first generated word.
* **Fold It Back:** Define a `Dynamic Data Container` in the YAML. The container's outer structure (name/role) is exact-matched, but the `name` attributes of its child nodes are explicitly exempted from string validation (only their presence and role are checked).

**9. A/B Tested UI Copy**

* **The Break:** OpenAI A/B tests "Send" vs "Submit". If YAML has "Send", it halts 50% of the time. The operator updates it to "Submit", and it halts the other 50%. You are in an infinite manual loop.
* **Fold It Back:** Allow finite exact-match arrays: `name: ["Send", "Submit"]`. Evaluated as `live_node in mapped_array` (strict literal equality). No fuzziness, but handles discrete variants.

**10. Interrupt Modals (Rate Limits / Login Walls)**

* **The Break:** A Cloudflare wait-screen or rate limit replaces the UI. The tree doesn't match. The engine notifies "drift" and halts, expecting the operator to map the new element to proceed. You cannot "proceed" through a hard block by mapping it.
* **Fold It Back:** Add a mandatory `Interrupts` array in the YAML (exact map of known blockers). If an interrupt matches, the engine throws a fatal `NOTIFY_BLOCKED` exception, immediately terminating the session rather than treating it as UI drift.

---

### (d) STICKINESS (Enforcement Loopholes)

**11. The YAML Settle-Window Loophole**

* **The Hole:** The `r5-audit-gate` lint checks Python code, but operators can circumvent enforcement entirely by editing the YAML. To stop notifications on a flaky element, they just set `settle_window: 300000` (5 minutes). The system hangs indefinitely instead of notifying, masking the drift.
* **The Amendment:** Hardcode a `MAX_GLOBAL_SETTLE_MS` constraint in the core engine code. If any YAML parses a value higher than this threshold, the application refuses to boot.

**12. Regex Smuggling at the Parser Level**

* **The Hole:** *"A pre-commit lint FAILS the build if any banned matcher... is reintroduced."* If operators inject regex into the YAML (`name: ".*Send.*"`) and the underlying Python AT-SPI wrapper defaults to regex matching under the hood, the lint passes but the binary invariant is destroyed.
* **The Amendment:** The CI pipeline must validate YAML files against a strict JSON Schema that rejects regex metacharacters (`.*`, `^`), and the Python string evaluation must be audited to enforce literal `==`.

**13. Caller-Level Retry Wrappers**

* **The Hole:** The driver is rigidly enforced to match-or-notify. But a developer can wrap the driver call in the orchestrator: `while True: try: driver.click() except Notify: continue`. This reintroduces banned retries outside the linted driver scope.
* **The Amendment:** The `NOTIFY` state must permanently poison the session context ID. Any subsequent driver calls for that session ID must instantly throw a `DeadSessionError`.

---

### VERDICT

**Not yet airtight.** The exact-match philosophy is a brilliant defense against code rot, but conflates transient visual states with durable application logic; **the single most important fix is redefining 'Complete' to require a positive completion marker rather than the dangerous negative assumption that the 'Stop' button has simply disappeared.**