# Five-lane `consult_chat` production receipt — 2026-08-25

Result: PASS for one concurrent deterministic five-platform campaign. This receipt does not claim statistical
reliability, two unattended cycles, or release from Codex receipt supervision.

## Frozen execution

- Campaign: `taey-hub-ramp-parallel9b-20260825`
- Hands execution SHA: `77456bb59e5ac43014e9ab2cc43fec5a4363328b`
- Presence execution SHA: `562758793b1389de9da3a87e86833df80d490fe9`
- Frozen specification SHA-256: `ab5bfce13fc06b83ade832c56929ed9d762c320a3067596d11e69d034b726ee7`
- Batch-summary SHA-256: `6b8906deab5d1b6481342251dad8ab10bdc3b926dc372e8e6121d01958f4662b`
- Launch spread: `1.058633 ms`

`scripts/run_consult_chat_parallel.py` launched five distinct
`scripts/run_consult_chat_worker.py` processes. Each worker made one `consult_chat` request with its own
platform, display, seat, event, correlation, and artifact root.

## Terminal results

| Platform | Display | Validated steps | Time to terminal | Response bytes | Response SHA-256 |
|---|---:|---:|---:|---:|---|
| ChatGPT | `:2` | 18 | 1,418.8 s | 29,976 | `c664f628bc4afd1f7e681e02ff2e255ac912dc34839fa5453f83f67692c1b21b` |
| Claude | `:3` | 22 | 1,263.8 s | 25,818 | `48725a2d34b523583668ef79c9a5dc3f659574fbb88a2b10b0315772b8f33529` |
| Gemini | `:4` | 20 | 886.2 s | 47,973 | `b6bb41ef0185ef2de83c4add7272a7790af02492ad0273f6eb835f77b57a667f` |
| Grok | `:5` | 14 | 387.6 s | 11,227 | `005e179a071cd4690dbb6b2ad5d2afbd702c904f3f370c49eb5da34a26778075` |
| Perplexity | `:6` | 18 | 397.6 s | 56,480 | `6113149a66989ffc33e0715053a981b2da92ab7c8c3f9203dac8d00ece756da3` |

The five consultation receipts contain 92 steps. Mechanical re-derivation found 92 `success=true`, zero
failed steps, and zero steps with absent or empty evidence. Every lane returned exit code zero,
`terminal_receipt.ok=true`, and non-empty extracted response text.

Terminal batch state was:

```json
{
  "active_turns": 0,
  "display_leases": [],
  "orphan_workers": []
}
```

`clean_release=true`. The response and batch hashes above were independently recomputed during Main Taey's
five-ruling reconciliation. Raw runtime artifacts are intentionally not published because they contain
account-local paths and live UI evidence; the content addresses above bind the production observation without
publishing that private state.

## Qualification boundary

This campaign proves concurrent fanout, YAML/driver-owned step validation, platform monitor ownership,
extraction, and cleanup on the pinned commits. It leaves reproducibility on a second campaign, unattended
Main-Taey ownership, quota behavior at sustained cadence, and exception containment without Codex as open
qualification questions.
