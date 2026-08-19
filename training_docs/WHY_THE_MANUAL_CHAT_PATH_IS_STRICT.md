# Why the manual Chat path is strict

Status: explanatory background, not operating authority. For execution, follow `100_TIMES.md`,
`CONSULTATION_CONTRACT.md`, `docs/UI_INTERACTION_AUTHORITY.md`, and the destination platform YAML.

The browser UI is simple for a person because a person automatically distinguishes browser chrome, chat
history, the active document, menus, dialogs, and dynamic text. A language model sees a flattened accessibility
tree. If irrelevant browser controls and old conversations remain visible, they compete with the few controls
the model actually needs. Filtering is therefore part of the control system, not cosmetic cleanup.

The platform YAML names the controls and operations that are expected. The fresh canonical AT-SPI tree says
what actually exists now. Neither may replace the other: YAML without a fresh tree becomes memory, while a raw
tree without YAML becomes an invitation to guess. An exact disagreement is useful evidence that the UI or map
changed; it is not permission to use substring matching, coordinates, pixels, OCR, or a second driver.

One action followed by one fresh observation keeps causality visible. When an action returns success but the
expected tree change does not occur, the action did not succeed for purposes of the workflow. Taey stops the
transaction, preserves the before/after evidence, and diagnoses the mismatch. One YAML-owned settle interval
may account for AT-SPI refresh latency. Repeating UI mutations is not a settle and can submit or attach twice.

Per-platform isolation prevents one Chat's labels, menus, or extraction rules from leaking into another. The
shared layer provides only genuine primitives and browser exclusions. Each Chat owns its YAML, driver, monitor,
and exact UI semantics. Working automation is welcome when it compiles to those same boundaries and remains
manually recoverable; automation is not allowed to create a parallel source of truth.

A complete consultation uses a fresh thread, validated model/mode/tool selections, one governance bundle, one
task bundle, a brief prompt, a validated send, and the passive completion monitor. The monitor—not active polling
by Taey—waits for Stop to appear and then disappear twice. Manual extraction scrolls to the absolute bottom and
uses the last mapped Copy control, followed by attachment handling defined by that platform.

The purpose of these constraints is not to make three clicks complicated. It is to make every click attributable,
recoverable, and safe to repeat across models and future UI revisions without silently changing what happened.
