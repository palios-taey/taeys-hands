# Public Operating Boundary

Status: public surrogate for operator-only governance. This file exists so `CLAUDE.md`
does not point a downloaded Taey at private repos as canonical dependencies.

## Observed

- This repository is public and contains the live shared AT-SPI primitives, per-platform YAML contracts,
  passive monitors, and extraction/ingestion components used by Taey's manual Family-chat path. The
  Layer-3 autonomous engine is retained as reference code and is not the production control path.
- Machine-specific values such as hosts, display numbers, and seat names are runtime
  configuration. The public repo can document the contract, but a portable setup must inject
  local values.
- Public references in always-loaded docs must resolve from public repos or from files in this
  repo. A private operator path can be useful for Mira operators, but it is not a dependency a
  downloaded Taey can satisfy.

## Public Mandate Summary

- Taey is the customer of this repo. The shared consultation substrate and manual path exist as Taey
  production infrastructure, not as a generic adoption surface.
- A released Taey plus public repos should be enough to understand the public contract. When
  private operator governance contains a rule needed here, the rule must be summarized in a
  public file or moved into a public repo.
- A pointer that resolves only inside a private repo or operator-local directory is a
  disconnection defect unless the surrounding text explicitly labels it as Mira-only operator
  detail.

## 6SIGMA Workflow Summary

- Select one target, measure the real failure, identify the root cause, improve the artifact,
  run the real production workload, then let the owner control the merge.
- Root-cause fixes correct the upstream shape so the broken path is no longer reached. A bypass
  branch or narrow exception is a patch and needs a clear reason.
- "Done" requires evidence: commit SHA, mechanical gate result, and a production observation.
  A passing test written with the fix is not enough.

## ISMA Prose Retrieval Summary

- Use public `palios-taey/isma-core:ISMA_PROSE_RETRIEVAL_SPEC.md` for the retrieval contract.
- Use prose retrieval for framing and prior decisions, not as a metric source.
- Cross-check numeric claims against public measurement receipts. If the only baseline is in a
  private operator store, a downloaded Taey must answer Unknown rather than cite it.

## Private-To-Public Summary

- A public repo must not require secrets, PII, private training data, or private operator paths
  to understand its public contract.
- Local topology belongs in configuration examples or dated production receipts, not as a
  portable setup requirement.
- Publication is human-approved and gate-backed. If a required rule is still private, publish a
  concise surrogate here before making it a dependency.
