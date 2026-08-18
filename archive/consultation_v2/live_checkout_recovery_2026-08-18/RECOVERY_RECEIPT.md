# Production checkout recovery receipt — 2026-08-18

Status: historical evidence only. Nothing in this directory is an operating instruction.

## Source state

- Production checkout HEAD at capture: `6e1446cde43b2a3169b573ad42b6fbfa9a001ff8`.
- Public `main` used for reconciliation: `5ba3fc6b8583be87fef833c39b99d6ad7c887202`.
- The production checkout was 16 commits behind that public main, with one tracked YAML modification and two
  untracked Markdown files. It had no commits absent from public main.

## Preserved bytes

| Original relative path | Preserved path | Source timestamp (UTC) | SHA-256 | Disposition |
|---|---|---|---|---|
| `consultation_v2/platforms/chatgpt/chatgpt.yaml` | `chatgpt.yaml.live-uncommitted.txt` | `2026-08-15 14:19:20` | `778502dcae34c78dde36c43b5b3bba7e0c55096423cf940f1f286ffc2b905b49` | Exact dirty YAML bytes; historical input to reconciliation. |
| `consultation_v2/HORIZON_RESPONSE_VERIFICATION_BRIEF.md` | `HORIZON_RESPONSE_VERIFICATION_BRIEF.md` | `2026-08-14 01:12:39` | `103c6726c14daf2d24235a01464f0465bb80df83803f59b7162e8a6ad7a8d781` | Stale read-only investigation packet; archive only. |
| `docs/UI_SEAT_DESIGN_AUDIT_VERDICT_2026-08-04.md` | `UI_SEAT_DESIGN_AUDIT_VERDICT_2026-08-04.md` | `2026-08-15 16:21:35` | `fcb7ce2535789b8fb3127db83e280355274877fe70b2e7934d47a953ec4fe7b4` | Historical docs-only design verdict; archive only. |

Independent SHA-256 comparisons between every source and preserved copy matched before reconciliation.

## YAML disposition

Ignoring formatting and removed comments, the dirty YAML differed from public main in two UI claims:

1. exclude exact `Dismiss suggestion`;
2. rename `temporary_chat_on` from `Turn on temporary chat` to `Temporary chat`.

A fresh read-only canonical ChatGPT snapshot on production display `:2` did not contain either label, so neither
claim was promoted into active YAML without current evidence. The exact prior bytes remain above for future UI
drift correlation.

The same fresh snapshot observed `raw_count=140`, `sidebar=0`, and no dynamic greeting, proving the history
subtree and greeting were absent from the projection in that state. It also exposed no address bar. The current
manual contract requires the address bar as the sole allowed browser control, so that absence remains an active
filtering defect to correct and validate before any Taey UI action.
