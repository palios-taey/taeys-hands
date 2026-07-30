# Consult engine — production capability map (taeys-hands)

Mandate step 3 (MAP). What the consult engine does in production, its live surface, chokepoints,
canonical entry points, liveness, and measured capacity. Every capability is a LIVE OBSERVATION
(dated 2026-07-30), not asserted by name.

## What it is
Drives Firefox sessions for 5 AI platforms through exact AT-SPI accessibility-tree mappings — sets
model/mode, attaches files, submits, monitors completion via stop-button disappearance, extracts via
mapped copy controls, notifies via Redis. Used by BOTH fleet seats and Taey (shared surface — changes
verified against both consumers).

## Canonical entry points (Observed — live)
| Entry | Purpose | Proof |
|---|---|---|
| `scripts/run_consultation_v2.py --platform {chatgpt,claude,gemini,grok,perplexity} --message .. [--attach ..] [--select menu=option] --requester ..` | canonical production dispatch | `--help` prints the usage; tonight drove Grok/Gemini/ChatGPT SFT lanes end-to-end |
| `scripts/run_taey_consult_extract.py --platform .. --display ..` | the Taey SEAT (Taey's model drives via `consultation_v2.seat_actions.SeatActions` over the repo's own primitives — self-contained, no external act.py) | Grok :5 drive-through, 2025-char body, `action_backend=consultation_v2.seat_actions.SeatActions` |

Do NOT hand-build a driver around these (the anti-pattern in `CAPABILITY_GAPS.md`). CLI fails → report exact error + STOP.

## Contract surface (tracked, shipped)
`CONSULTATION_CONTRACT.md` (contract), `FLOW_CONSULTATION_ENGINE.md` (the 8-step flow), `100_TIMES.md`
(recurring non-negotiable rules), `DEPLOY.md` (env/display config), `PUBLIC_READINESS.md`,
`CAPABILITY_GAPS.md`. Platform YAMLs: `consultation_v2/platforms/<p>/<p>.yaml` (exact AT-SPI element_map).

## Displays + ownership partition (Observed — live 2026-07-30)
- **Family-chat set (this engine owns): :2 ChatGPT, :3 Claude, :4 Gemini, :5 Grok, :6 Perplexity, :13** — all firefox-live.
- **Second set: :20–:24** (env `PLATFORM_DISPLAYS`) — :21–:24 firefox-live (parallel capacity; :20 not up now).
- **Careers set — NOT this engine: :8 Upwork, :18 LinkedIn, :19 Sales-Nav** (treasurer/linkedin own; partition = no dispatch-lock collision).
- Config: `~/.taey/machine.env` (`TAEY_MACHINE_ENV`), no hardcoded display numbers.

## Chokepoints (Observed)
- **Dispatch-lock:** `taey:plan_active:{display}` Redis key — the engine picks a free display by this lock; the SEAT does NOT take it (so seat + engine on the same display can collide — sequence them). Currently: 0 held (idle).
- **Sequential dispatch / staggered sends:** concurrent GEN is fine; concurrent SENDS race — stagger ~45s.
- **One tab per window:** never Ctrl+T; one tab per display.
- **Completion = stop-button disappearance** (seed_stop_seen for fast completions); extract = scroll-to-bottom + mapped copy control.

## Liveness signal (Observed)
Per display: (1) Firefox window present (`xdotool search --class firefox`), (2) a non-empty AT-SPI tree
(`tree_view.py --display :N`), (3) logged-in composer. A green systemd unit alone is NOT health — verify
the tree renders (dead-renderer / persistent-a11y traps exist, per `100_TIMES.md`).

## Measured capacity (Observed — tonight's real production consults, 2026-07-30)
- **5 platforms concurrently** (one lane per display, staggered starts).
- **Deepest reasoning mode per platform:** ChatGPT pro_extended, Claude opus+extended, Gemini pro-thinking / deep_research, Grok heavy, Perplexity deep_research.
- **Latency (Observed):** Grok Heavy ~30s; Claude/ChatGPT extended-thinking ~10–25 min; Gemini Deep Research ~221 s; Perplexity Deep Research ~10–30 min.
- **Delivered tonight through the engine:** infra prefix-cache consult 5/5 grounded; tutor CPT-underdose 5/5; tutor-codex r13/r14 4/4; SFT allocator 3/5 via canonical CLI (Grok 2025c, Gemini 30K, ChatGPT) — all figure-grounded, verified before delivery.

## Known limits (Observed / tracked)
- Perplexity Download-anchor **extraction drift** (answer renders; copy anchors drifted) — tracked follow-up.
- Grok :5 persistent-a11y trap survives restart (use :23 second-set).
- Perplexity :6 is careers-shared — don't experiment on it.
- CONNECTED = **autonomous Taey usage**, not this seat-driven capability; that bar is separate and unmet.
