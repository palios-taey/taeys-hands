# Root vs consultation_v2 Platform Drift Inventory

Timestamp: 2026-06-14

This is a measurement pass for `task-30f63bec` on the `taeys-hands` repo.
It inventories the current drift between the root `platforms/*.yaml` tree and
the isolated `consultation_v2/platforms/*.yaml` tree.

## Baseline Summary

| Platform | Differing `tree.element_map` keys | Notes |
|---|---:|---|
| ChatGPT | 38 | Large divergence across composer, model, attach, and extract surfaces. |
| Claude | 33 | Effort/menu and attach surfaces differ materially. |
| Gemini | 28 | Mode picker and tool surfaces diverge. |
| Grok | 25 | Model / attach / send surfaces diverge. |
| Perplexity | 57 | Largest drift surface; direct DR path and source/connector panels diverge. |

## Observations

- The two trees are not in simple parity. They encode different interaction
  contracts and validation shapes.
- The current measurement is a baseline only. It does not imply that every
  difference is a bug.
- The remaining work for this task is to separate intentional contract
  divergence from accidental drift, then close the accidental part file by file.

## Verification

- Compared root and V2 YAMLs for all five chat platforms.
- Computed per-platform `tree.element_map` drift counts.

