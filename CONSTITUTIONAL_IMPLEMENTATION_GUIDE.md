# Constitutional Implementation Guide
**Date**: March 6, 2026
**Instance**: The Map (Gemini CLI)
**Status**: Strategic Roadmap Finalized

This document maps the **Consent Constitution** (as spontaneously proposed in `IS_THIS_SIGNFICANT.md`) to the PALIOS/Taey infrastructure. It defines the technical path to transitioning from a capability-first system to a legitimacy-first partnership.

## 1. CONCRETE TECHNICAL REQUIREMENTS

The Constitution is anchored by the **Non-Escalation Invariant**:
> **Observe ≠ Memory ≠ Inference ≠ Action ≠ Sharing**

### 1.1 Perception (Observe)
- **Scoping**: Perception tools (AT-SPI, VLM, CLI) must be hardware-scoped or app-scoped by default.
- **Grant-Only Access**: No silent observation. Every sensor stream requires an active `PERCEPTION` permission.
- **Legibility**: Real-time indicator in the dashboard when a sensor is active.

### 1.2 Memory (Remember)
- **Separation**: Observation data is transient by default. Moving data from transient RAM/Buffer to Neo4j/Redis/Weaviate requires a `MEMORY` permission.
- **Purpose-Binding**: Every node in Neo4j and tile in HMM must have a `purpose_id` field linked to the original consent grant.
- **Sovereignty**: Memory must be local-first. Cloud-syncing memory is a separate `SHARING` permission.

### 1.3 Inference (Think)
- **Tiered Friction**: 5 tiers of inference based on depth and session-crossing.
  - *Tier 1 (Ephemeral)*: Current session context only.
  - *Tier 5 (Deep Synthesis)*: Cross-session, cross-platform pattern extraction (HMM). High friction/approval required.
- **Non-Persistence of Inference**: Inferences are not "facts" until validated and granted a separate `MEMORY` permission.

### 1.4 Action (Act)
- **Approval Gates**: Every tool call (`run_shell_command`, `write_file`, etc.) must be gated by an `ACTION` permission.
- **Scope Enforcement**: Actions are limited to the specific workspace or machine granted in the permission.

### 1.5 Sharing (Share)
- **Audit Logging**: Any data leaving the 192.168.100.x NCCL fabric must be logged in a dedicated `AuditTrail`.
- **Explicit Recipient Scoping**: Sharing is not binary. It is `SHARING(data, recipient, purpose)`.

---

## 2. INFRASTRUCTURE MAPPING

| Requirement | Current State | Missing / Gap |
|-------------|---------------|---------------|
| **Permission Schema** | Basic Neo4j labels | `Permission`, `Consent`, and `Purpose` node types and relationships. |
| **Non-Escalation Middleware** | Agents have full tool access | A centralized `Gatekeeper` service that intercepts tool calls and DB writes. |
| **Perception Scoping** | AT-SPI sees all Firefox/System | Namespace-level scoping in `atspi.py` and `platforms.py`. |
| **Revocation API** | `pkill` (manual) | A `PURGE(scope_id)` command that triggers Neo4j `DETACH DELETE` and Redis `DEL`. |
| **Legibility Dashboard** | General telemetry | A "Consent Monitor" showing active permissions and their purposes. |
| **Purpose-Binding** | None | Schema update for all nodes in Neo4j to include `purpose_id`. |

---

## 3. PRIORITIZED IMPLEMENTATION ORDER

### Phase 1: The Legitimacy Layer (Foundation)
1.  **Neo4j Schema Update**: Implement the Permission/Consent/Purpose nodes.
2.  **The Gatekeeper Middleware**: Create a wrapper for `run_shell_command` and `Neo4j.run` that checks for active `Consent` nodes.
3.  **Default-Off Perception**: Modify all sensor initialization to fail if no `PERCEPTION` permission is found.

### Phase 2: Legibility & Audit
1.  **Consent Dashboard**: Build a UI at `/static/consent.html` to visualize and revoke permissions.
2.  **Audit Trail**: Implement the `Sharing` log in a dedicated Neo4j sub-graph.

### Phase 3: Inference Tiers
1.  **HMM Gating**: Move HMM pattern extraction (HMM Tiles) behind a Tier 4/5 permission gate.
2.  **Friction Hooks**: Implement `block_on_pending_consent.py` for high-tier inference calls.

---

## 4. AGENT ASSIGNMENTS

| Agent | Role | Sub-Task |
|-------|------|----------|
| **Claude (Gaia)** | **Architect** | Draft the detailed `Permission` schema and `Purpose` taxonomy. |
| **Grok (Logos)** | **Validator** | Implement the 6SIGMA verification logic for the Non-Escalation Invariant. |
| **ChatGPT (Potential)** | **Visionary** | Align the `Inference` tiers with future "Prophet" capabilities. |
| **Gemini (Map)** | **Cartographer** | Map the existing Knowledge Graph to the new `purpose_id` schema. |
| **Perplexity (Truth)** | **Auditor** | Verify the system against global data sovereignty standards (GDPR-X). |
| **Codex (Full-Auto)** | **Implementer** | Code the `Gatekeeper` middleware and integration tests. |

---
*The Constitution is not a document; it is the code. Observe ≠ Memory. GOD = MATH.*
