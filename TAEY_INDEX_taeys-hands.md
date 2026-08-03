PROCESS:   Family-Chat consultation — hand a packet to the AI Chats (Gaia/Claude,
           Logos/Grok, Cosmos/Gemini, Horizon/ChatGPT, Clarity/Perplexity) and return
           grounded answers to the ONE requester. taeys-hands is the SOLE conduit for
           displays :2-:6 / :13.
PLAN:      /home/mira/taeys-hands/FLOW_CONSULTATION_ENGINE.md  (8-step flow, 742 lines)
           /home/mira/taeys-hands/CONSULTATION_CONTRACT.md     (contract, 56 lines)
           /home/mira/taeys-hands/100_TIMES.md                 (recurring failure rules, 102 lines)
           [all three stat-verified present on this branch 2026-08-03; root 100_TIMES.md restored from docs/archive/100_TIMES.md; the consultation_v2/ copies are DEAD — do not cite them]
LAUNCH:    Taey drives (preferred): python3 /home/mira/taeys-hands/scripts/run_taey_consult_extract.py
             --platform <p> --display :N --model ep3 --attach <abs file> --prompt "<=600 chars, must NOT inline the attachment>"
             one platform at a time, staggered. Displays: :2 ChatGPT, :3 Claude, :4 Gemini, :5 Grok, :6 Perplexity.
           Engine fallback (deterministic, not Taey-driven): python3 /home/mira/taeys-hands/scripts/run_consultation_v2.py
             --platform <p> --requester <node> --select model=<mode> --attach <file> --message "<framing>"
           Executed by the taeys-hands seat only.
EXPECT:    Output JSON: ok=true, attachment_verified=true, stop_seen=true, a real NON-ECHO body that
           cites file:line it could only get by reading the attached/fetched source, answer_thread bound;
           then the raw body delivered to the requester. A reviewer BLOCK (declined for lack of in-session
           fetch) is a VALID outcome, not a failure. Empty/echo body or attachment_verified=false = not done.
ON FAIL:   Notify taeys-hands. Review /home/mira/taeys-hands/100_TIMES.md FIRST (recurring-failure rules),
           then FLOW_CONSULTATION_ENGINE.md for the failing step. Then decide: BUG (engine/seat mis-drives
           or a YAML drifts from the live AT-SPI tree) -> dispatch taeys-hands-codex to root-cause fix,
           production-verify, taeys-hands merges; vs TRAINING (Taey emitted a wrong action it could have
           gotten right) -> author a pair per the taey-training-trigger skill. First error = full stop.
NEVER:     Drive the CAREERS displays (:8 Upwork, :18 LinkedIn, :19 Sales Nav, apply-display) — Treasurer/linkedin own them.
           Never experiment on shared :6 (careers Deep-Research runs there). Never double-dispatch a live/generating display.
           Never skip the FAMILY_KERNEL + platform IDENTITY attachment. Never drive Kendra's personal displays (:27/:28).
           Never write code from the taeys-hands seat — all code changes go through taeys-hands-codex.
