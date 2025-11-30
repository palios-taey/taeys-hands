Cool, Jesse – I’m going to treat “this” as “give me a concrete v2 implementation for the rebuild architecture you sketched in `REBUILD_REQUIREMENTS.md` (session + validation + selectors + MCP tools), reusing the working pieces from the current system.”

Below is a **drop‑in `src/v2` skeleton** that:

* Separates **core** vs **platforms** vs **workflow** vs **MCP** as in the spec 
* Reuses the **validation checkpoint system**, response detection, and finder navigation patterns you already have
* Centralizes selectors via a **registry** instead of hardcoding them in the interface classes
* Adds a **requirement enforcer** that makes skipping attachments mathematically impossible when the plan says “attach files”
* Implements the **session state model** and recovery flows from `SESSION_REQUIREMENTS.md`
* Leaves platform quirks (Grok JS click, Gemini overlays, disabled buttons, etc.) in the **platform classes**, not spread across tools

I’ll focus on **foundation code** (selectors, validation, sessions, workflows, tool handlers). Platform automation details (clicking buttons, `_navigateFinderDialog`, Fibonacci polling) live behind the `BasePlatform` interface so you can plug in the existing, battle‑tested patterns.

---

## 1. Selector Registry (centralized selectors)

`src/v2/core/selectors/selector-registry.ts`

This matches the JSON shape you described (`config/selectors/claude.json`, etc.).

```ts
// src/v2/core/selectors/selector-registry.ts
import * as fs from "fs/promises";
import * as path from "path";

export interface SelectorDefinition {
  primary: string;
  fallback?: string;
  description?: string;
}

export interface PlatformSelectorConfig {
  version: string;
  platform: string;
  url: string;
  selectors: Record<string, SelectorDefinition>;
}

/**
 * Centralized selector registry.
 *
 * Loads per-platform selector JSON files from config/selectors/*.json
 * and provides a simple getSelector(platform, key) API with
 * descriptive errors and fallback support.
 */
export class SelectorRegistry {
  private platformCache = new Map<string, PlatformSelectorConfig>();
  private readonly baseDir: string;

  constructor(baseDir = path.join(process.cwd(), "config", "selectors")) {
    this.baseDir = baseDir;
  }

  private async loadPlatform(platform: string): Promise<PlatformSelectorConfig> {
    const cached = this.platformCache.get(platform);
    if (cached) return cached;

    const filePath = path.join(this.baseDir, `${platform}.json`);
    const raw = await fs.readFile(filePath, "utf8");
    const parsed = JSON.parse(raw) as PlatformSelectorConfig;

    if (!parsed.selectors) {
      throw new Error(
        `Selector config for platform '${platform}' is missing 'selectors' map (${filePath}).`
      );
    }

    this.platformCache.set(platform, parsed);
    return parsed;
  }

  /**
   * Returns the best selector string for a given (platform, key).
   * Uses primary selector, falling back if necessary.
   */
  async getSelector(platform: string, key: string): Promise<string> {
    const cfg = await this.loadPlatform(platform);
    const def = cfg.selectors[key];

    if (!def) {
      const available = Object.keys(cfg.selectors).sort();
      throw new Error(
        `Selector key '${key}' not found for platform '${platform}'. ` +
          `Available keys: ${available.join(", ")}`
      );
    }

    if (def.primary) return def.primary;
    if (def.fallback) return def.fallback;

    throw new Error(
      `Selector '${key}' for platform '${platform}' has neither primary nor fallback defined.`
    );
  }

  /**
   * Returns the full selector definition (primary + fallback + description).
   */
  async getDefinition(
    platform: string,
    key: string
  ): Promise<SelectorDefinition> {
    const cfg = await this.loadPlatform(platform);
    const def = cfg.selectors[key];

    if (!def) {
      const available = Object.keys(cfg.selectors).sort();
      throw new Error(
        `Selector key '${key}' not found for platform '${platform}'. ` +
          `Available keys: ${available.join(", ")}`
      );
    }

    return def;
  }
}
```

---

## 2. Validation Core (checkpoint manager + requirement enforcer)

This wraps your existing `ValidationCheckpointStore` and implements the **proactive enforcement** you already worked out inside `taey_send_message`.

### 2.1 Checkpoint Manager

`src/v2/core/validation/checkpoint-manager.ts`

```ts
// src/v2/core/validation/checkpoint-manager.ts

export type StepName =
  | "plan"
  | "attach_files"
  | "type_message"
  | "click_send"
  | "wait_response"
  | "extract_response";

export interface ValidationCheckpoint {
  id: string;
  conversationId: string;
  step: StepName;
  validated: boolean;
  notes: string;
  screenshot: string | null;
  validator: string | null;
  timestamp: string;
  requiredAttachments: string[];
  actualAttachments: string[];
}

export interface AttachmentRequirements {
  required: boolean;
  files: string[];
  count: number;
}

export interface ValidationStore {
  initSchema(): Promise<void>;
  createCheckpoint(input: {
    conversationId: string;
    step: StepName;
    validated: boolean;
    notes: string;
    screenshot?: string | null;
    validator?: string | null;
    requiredAttachments?: string[];
    actualAttachments?: string[];
  }): Promise<ValidationCheckpoint>;
  getLastValidation(
    conversationId: string
  ): Promise<ValidationCheckpoint | null>;
  canProceedToStep(
    conversationId: string,
    nextStep: StepName
  ): Promise<{ canProceed: boolean; reason: string; lastValidated: string | null }>;
  requiresAttachments(conversationId: string): Promise<AttachmentRequirements>;
}

/**
 * Thin wrapper around ValidationCheckpointStore.
 *
 * In production you instantiate it with the existing
 * ValidationCheckpointStore instance from src/core/validation-checkpoints.js
 * which already implements the required methods. 
 */
export class CheckpointManager {
  constructor(private readonly store: ValidationStore) {}

  initSchema() {
    return this.store.initSchema();
  }

  createCheckpoint(input: {
    conversationId: string;
    step: StepName;
    validated: boolean;
    notes: string;
    screenshot?: string | null;
    validator?: string | null;
    requiredAttachments?: string[];
    actualAttachments?: string[];
  }) {
    return this.store.createCheckpoint(input);
  }

  getLastValidation(conversationId: string) {
    return this.store.getLastValidation(conversationId);
  }

  canProceedToStep(conversationId: string, nextStep: StepName) {
    return this.store.canProceedToStep(conversationId, nextStep);
  }

  requiresAttachments(conversationId: string) {
    return this.store.requiresAttachments(conversationId);
  }
}
```

### 2.2 Requirement Enforcer

`src/v2/core/validation/requirement-enforcer.ts`

This is essentially the generalized version of your `taey_send_message` validation block, pulled into a reusable component.

```ts
// src/v2/core/validation/requirement-enforcer.ts
import {
  AttachmentRequirements,
  CheckpointManager,
  StepName,
  ValidationCheckpoint,
} from "./checkpoint-manager";

/**
 * Enforces validation + attachment requirements before allowing
 * workflow steps to execute.
 *
 * This is where we make it mathematically impossible to:
 * - send without validating required steps, or
 * - skip attachment when the plan says "attach files".
 */
export class RequirementEnforcer {
  constructor(private readonly checkpoints: CheckpointManager) {}

  /**
   * Guard for any step that has a simple prerequisite chain,
   * e.g. 'attach_files' must come after a validated 'plan'.
   */
  async ensureStepAllowed(
    conversationId: string,
    nextStep: StepName
  ): Promise<void> {
    const can = await this.checkpoints.canProceedToStep(
      conversationId,
      nextStep
    );

    if (!can.canProceed) {
      throw new Error(
        `Validation checkpoint failed for step '${nextStep}': ${can.reason}\n\n` +
          `You must validate the prerequisite step before proceeding.\n` +
          `Use taey_validate_step with the appropriate 'step' and 'validated=true' after reviewing the screenshot.`
      );
    }
  }

  /**
   * Guard specifically for sending a message.
   *
   * - If plan requires attachments → last validated step must be
   *   'attach_files', validated=true, and attachment count must match.
   * - If no attachments required → last validated step must be 'plan'
   *   or 'attach_files', and validated=true.
   */
  async ensureCanSendMessage(conversationId: string): Promise<void> {
    const requirement: AttachmentRequirements =
      await this.checkpoints.requiresAttachments(conversationId);

    const last: ValidationCheckpoint | null =
      await this.checkpoints.getLastValidation(conversationId);

    if (!last) {
      throw new Error(
        `Validation checkpoint failed: No validation checkpoints found for this conversation.\n` +
          `You must validate at least the 'plan' step before sending a message.\n\n` +
          `Typical sequence:\n` +
          `1. Plan message → capture screenshot\n` +
          `2. taey_validate_step(step='plan', validated=true, notes='Plan looks correct')\n` +
          `3. Proceed with attachments / typing / sending.`
      );
    }

    if (requirement.required) {
      await this.enforceAttachmentRequirements(conversationId, requirement, last);
    } else {
      await this.enforceNoAttachmentPath(last);
    }
  }

  private async enforceAttachmentRequirements(
    conversationId: string,
    requirement: AttachmentRequirements,
    last: ValidationCheckpoint
  ) {
    if (last.step !== "attach_files") {
      throw new Error(
        `Validation checkpoint failed: Draft plan requires ${requirement.count} attachment(s).\n` +
          `Last validated step was '${last.step}'.\n\n` +
          `You MUST:\n` +
          `1. Call taey_attach_files with files: ${JSON.stringify(
            requirement.files
          )}\n` +
          `2. Review the returned screenshot to confirm all files are visible in the input area\n` +
          `3. Call taey_validate_step with step='attach_files' and validated=true\n\n` +
          `You cannot skip attachment when the draft plan specifies files.`
      );
    }

    if (!last.validated) {
      throw new Error(
        `Validation checkpoint failed: Attachment step is pending validation (validated=false).\n` +
          `You must review the screenshot and call taey_validate_step with validated=true.\n` +
          `Notes from pending checkpoint: ${last.notes}`
      );
    }

    const actual = last.actualAttachments || [];
    if (actual.length !== requirement.count) {
      throw new Error(
        `Validation checkpoint failed: Plan required ${requirement.count} file(s), ` +
          `but ${actual.length} were attached.\n` +
          `Required files: ${JSON.stringify(requirement.files)}\n` +
          `Actual files: ${JSON.stringify(actual)}`
      );
    }

    // If we reach here, enforcement passes
    // (keep log messages in the MCP layer, not here).
  }

  private async enforceNoAttachmentPath(last: ValidationCheckpoint) {
    if (!last.validated) {
      throw new Error(
        `Validation checkpoint failed: Step '${last.step}' is pending validation (validated=false).\n` +
          `Call taey_validate_step with validated=true after reviewing the screenshot.\n` +
          `Notes from pending checkpoint: ${last.notes}`
      );
    }

    const validSteps: StepName[] = ["plan", "attach_files"];
    if (!validSteps.includes(last.step)) {
      throw new Error(
        `Validation checkpoint failed: Last validated step was '${last.step}'. ` +
          `You must validate one of: ${validSteps.join(
            ", "
          )} before sending a message.`
      );
    }
  }
}
```

---

## 3. Session Core (ManagedSession + SessionManager)

This implements the **single source of truth** session model + health checks + DB sync from `SESSION_REQUIREMENTS.md`.

We keep the browser automation behind a `PlatformSession` interface so you can reuse your existing `ChatInterface` subclasses or new platform classes.

### 3.1 Types & abstractions

```ts
// src/v2/core/browser/types.ts

export type InterfaceType =
  | "claude"
  | "chatgpt"
  | "gemini"
  | "grok"
  | "perplexity";

export type SessionState =
  | "CREATING"
  | "CONNECTING"
  | "ACTIVE"
  | "STALE"
  | "ORPHANED"
  | "CLOSED"
  | "FAILED";

export interface PlatformSession {
  platform: InterfaceType;
  /**
   * Underlying page URL (e.g. https://claude.ai/chat/abc123)
   */
  getCurrentUrl(): Promise<string>;

  /**
   * Extract platform conversation id from current URL.
   * (Platform-specific logic lives in the platform class.)
   */
  getConversationIdFromUrl(url: string): string | null;

  /**
   * Take a labeled screenshot and return the file path.
   * Follows the same pattern as current ChatInterface.screenshot().
   */
  takeScreenshot(label: string): Promise<string>;

  /**
   * Attach files using the human-like, Finder-dialog-based pattern.
   * Returns screenshot path. The workflow will handle validation.
   */
  attachFiles(filePaths: string[]): Promise<string>;

  /**
   * Type a message into the chat input (human-like typing/paste).
   */
  typeMessage(text: string): Promise<void>;

  /**
   * Click the send button.
   */
  clickSend(): Promise<void>;

  /**
   * Wait for response completion using the response detection engine
   * (Fibonacci polling + stability), then return raw text. 
   */
  waitForResponse(): Promise<string>;

  /**
   * Gracefully close the underlying browser tab/context.
   */
  disconnect(): Promise<void>;
}

export interface ConversationStore {
  createConversation(input: {
    platform: InterfaceType;
    conversationId: string | null;
    status: string;
    sessionId: string;
  }): Promise<{ id: string }>;

  updateConversation(
    id: string,
    patch: Partial<{
      status: string;
      sessionId: string | null;
      conversationId: string | null;
      lastActivity: Date;
      closedAt: Date;
    }>
  ): Promise<void>;

  getConversationBySessionId(
    sessionId: string
  ): Promise<{ id: string; status: string; sessionId: string | null } | null>;

  getActiveSessions(): Promise<
    {
      id: string;
      platform: InterfaceType;
      status: string;
      sessionId: string | null;
    }[]
  >;
}
```

### 3.2 ManagedSession

```ts
// src/v2/core/browser/managed-session.ts
import { v4 as uuidv4 } from "uuid";
import {
  ConversationStore,
  InterfaceType,
  PlatformSession,
  SessionState,
} from "./types";

/**
 * ManagedSession mirrors the design in SESSION_REQUIREMENTS.md and
 * keeps browser + MCP + DB state in sync. 
 */
export class ManagedSession {
  readonly sessionId: string;
  readonly platform: InterfaceType;
  readonly createdAt: Date;
  state: SessionState = "CREATING";
  conversationId: string | null = null; // platform chat ID
  conversationUrl: string | null = null;
  lastActivity: Date | null = null;

  constructor(
    sessionId: string,
    platform: InterfaceType,
    public readonly platformSession: PlatformSession,
    private readonly dbStore: ConversationStore,
    private conversationNodeId: string | null = null
  ) {
    this.sessionId = sessionId;
    this.platform = platform;
    this.createdAt = new Date();
  }

  static async create(
    platform: InterfaceType,
    platformSession: PlatformSession,
    dbStore: ConversationStore
  ): Promise<ManagedSession> {
    const sessionId = uuidv4();
    const session = new ManagedSession(sessionId, platform, platformSession, dbStore);
    session.state = "CONNECTING";

    const url = await platformSession.getCurrentUrl();
    session.conversationUrl = url;
    session.conversationId = platformSession.getConversationIdFromUrl(url);

    const convo = await dbStore.createConversation({
      platform,
      conversationId: session.conversationId,
      status: "active",
      sessionId,
    });

    session.conversationNodeId = convo.id;
    session.state = "ACTIVE";
    session.lastActivity = new Date();
    await session.syncToDB();
    return session;
  }

  get conversationDbId(): string {
    if (!this.conversationNodeId) {
      throw new Error(
        `ManagedSession[${this.sessionId}] has no conversationNodeId set.`
      );
    }
    return this.conversationNodeId;
  }

  async syncToDB(): Promise<void> {
    await this.dbStore.updateConversation(this.conversationDbId, {
      conversationId: this.conversationId,
      sessionId: this.sessionId,
      status: this.stateToDbStatus(),
      lastActivity: new Date(),
    });
  }

  async syncFromBrowser(): Promise<void> {
    const url = await this.platformSession.getCurrentUrl();
    this.conversationUrl = url;
    this.conversationId = this.platformSession.getConversationIdFromUrl(url);
  }

  private stateToDbStatus(): string {
    switch (this.state) {
      case "ACTIVE":
      case "CONNECTING":
        return "active";
      case "STALE":
      case "ORPHANED":
        return "orphaned";
      case "CLOSED":
        return "closed";
      case "FAILED":
        return "failed";
      case "CREATING":
      default:
        return "creating";
    }
  }

  async healthCheck(): Promise<void> {
    try {
      await this.platformSession.getCurrentUrl();
      this.state = "ACTIVE";
    } catch {
      this.state = "STALE";
      await this.syncToDB();
      throw new Error(`Session ${this.sessionId} is stale (browser dead).`);
    }
  }

  /**
   * Wrapper for workflow steps. Ensures health, then syncs browser+DB.
   */
  async execute<T>(fn: (session: PlatformSession) => Promise<T>): Promise<T> {
    await this.healthCheck();
    const result = await fn(this.platformSession);
    await this.syncFromBrowser();
    await this.syncToDB();
    this.lastActivity = new Date();
    return result;
  }

  async close(status: "CLOSED" | "FAILED" = "CLOSED"): Promise<void> {
    this.state = status;
    await this.platformSession.disconnect();
    await this.dbStore.updateConversation(this.conversationDbId, {
      status: this.stateToDbStatus(),
      sessionId: null,
      closedAt: new Date(),
    });
  }
}
```

### 3.3 SessionManager

`src/v2/core/browser/session-manager.ts`

Implements startup reconciliation + orphan marking from the requirements doc.

```ts
// src/v2/core/browser/session-manager.ts
import {
  ConversationStore,
  InterfaceType,
  PlatformSession,
} from "./types";
import { ManagedSession } from "./managed-session";

export class SessionManager {
  private sessions = new Map<string, ManagedSession>();

  constructor(private readonly dbStore: ConversationStore) {}

  getSession(sessionId: string): ManagedSession {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session '${sessionId}' not found. Use taey_list_sessions or taey_connect.`);
    }
    return session;
  }

  listSessions(): ManagedSession[] {
    return Array.from(this.sessions.values());
  }

  async createSession(
    platform: InterfaceType,
    platformSession: PlatformSession
  ): Promise<ManagedSession> {
    const session = await ManagedSession.create(
      platform,
      platformSession,
      this.dbStore
    );
    this.sessions.set(session.sessionId, session);
    return session;
  }

  async destroySession(sessionId: string, status: "CLOSED" | "FAILED" = "CLOSED") {
    const session = this.sessions.get(sessionId);
    if (!session) return;
    await session.close(status);
    this.sessions.delete(sessionId);
  }

  async destroyAllSessions(status: "CLOSED" | "FAILED" = "CLOSED") {
    for (const [id] of this.sessions) {
      await this.destroySession(id, status);
    }
  }

  /**
   * Validates a specific session's browser health.
   */
  async validateSessionHealth(sessionId: string): Promise<void> {
    const session = this.getSession(sessionId);
    await session.healthCheck();
  }

  /**
   * Reconcile DB vs in-memory vs browser state on startup and periodically.
   * Based on the sync algorithm in SESSION_REQUIREMENTS.md. 
   */
  async syncWithDatabase(): Promise<void> {
    const dbSessions = await this.dbStore.getActiveSessions();

    for (const dbSession of dbSessions) {
      const sessionId = dbSession.sessionId || "";
      const mcpSession = sessionId && this.sessions.get(sessionId);

      if (!mcpSession) {
        // DB says "active" but no MCP session → mark orphaned
        await this.dbStore.updateConversation(dbSession.id, {
          status: "orphaned",
          sessionId: null,
        });
      } else {
        try {
          await mcpSession.healthCheck();
        } catch {
          // Browser dead → mark orphaned, drop MCP session
          await this.dbStore.updateConversation(dbSession.id, {
            status: "orphaned",
            sessionId: null,
          });
          this.sessions.delete(sessionId);
        }
      }
    }
  }
}
```

---

## 4. Attachment Workflow + StepValidator

This is the v2 version of your **attachment workflow** with **pending validation checkpoints** and explicit “next step” hints.

`src/v2/core/validation/step-validator.ts`

```ts
// src/v2/core/validation/step-validator.ts
import { CheckpointManager, StepName } from "./checkpoint-manager";

/**
 * StepValidator encapsulates "create checkpoint + instruct user to validate"
 * behavior, so tools don't need to know the checkpoint schema details. 
 */
export class StepValidator {
  constructor(private readonly checkpoints: CheckpointManager) {}

  async createPendingCheckpoint(params: {
    conversationId: string;
    step: StepName;
    screenshot: string;
    notes: string;
    actualAttachments?: string[];
    requiredAttachments?: string[];
  }) {
    const checkpoint = await this.checkpoints.createCheckpoint({
      conversationId: params.conversationId,
      step: params.step,
      validated: false,
      notes: params.notes,
      screenshot: params.screenshot,
      actualAttachments: params.actualAttachments || [],
      requiredAttachments: params.requiredAttachments || [],
    });

    return {
      status: "pending" as const,
      validationId: checkpoint.id,
      message:
        `Review the screenshot to confirm the UI state is correct, then ` +
        `call taey_validate_step with step='${params.step}' and validated=true.`,
      screenshot: params.screenshot,
    };
  }
}
```

`src/v2/workflow/attachment-workflow.ts`

```ts
// src/v2/workflow/attachment-workflow.ts
import { SessionManager } from "../core/browser/session-manager";
import { CheckpointManager } from "../core/validation/checkpoint-manager";
import { RequirementEnforcer } from "../core/validation/requirement-enforcer";
import { StepValidator } from "../core/validation/step-validator";

/**
 * High-level attachment workflow:
 * - enforce that 'plan' has been validated
 * - run platform-specific attach automation
 * - create pending 'attach_files' checkpoint with actualAttachments
 * - return screenshot + validation instructions
 */
export class AttachmentWorkflow {
  constructor(
    private readonly sessions: SessionManager,
    private readonly checkpoints: CheckpointManager,
    private readonly enforcer: RequirementEnforcer,
    private readonly validator: StepValidator
  ) {}

  async attachFiles(input: {
    sessionId: string;
    conversationId: string;
    filePaths: string[];
  }) {
    // Ensure we are allowed to perform 'attach_files' at this point.
    await this.enforcer.ensureStepAllowed(
      input.conversationId,
      "attach_files"
    );

    const managed = this.sessions.getSession(input.sessionId);

    // Run the platform-specific automation (Finder dialog pattern).
    const screenshot = await managed.execute((platform) =>
      platform.attachFiles(input.filePaths)
    );

    // Create a pending checkpoint that records what we tried to attach.
    const pending = await this.validator.createPendingCheckpoint({
      conversationId: input.conversationId,
      step: "attach_files",
      screenshot,
      notes: `Attached ${input.filePaths.length} file(s). Awaiting manual validation.`,
      actualAttachments: input.filePaths,
    });

    return {
      automationCompleted: true,
      screenshot,
      validation: pending,
    };
  }
}
```

---

## 5. Session Workflow (for taey_connect / resume / disconnect)

`src/v2/workflow/session-workflow.ts`

This is the façade the MCP tools call: it hides SessionManager + ConversationStore + CheckpointManager wiring and implements the connect/resume semantics from the requirements docs.

```ts
// src/v2/workflow/session-workflow.ts
import { SessionManager } from "../core/browser/session-manager";
import {
  ConversationStore,
  InterfaceType,
  PlatformSession,
} from "../core/browser/types";
import { CheckpointManager } from "../core/validation/checkpoint-manager";

/**
 * Creates PlatformSession instances for a given platform.
 * This is where you plug in the new platform classes that contain
 * all the click / selector / overlay / AppleScript / xdotool logic. 
 */
export interface PlatformFactory {
  createPlatformSession(platform: InterfaceType, opts?: {
    conversationId?: string | null;
    newSession?: boolean;
  }): Promise<PlatformSession>;
}

export class SessionWorkflow {
  constructor(
    private readonly sessions: SessionManager,
    private readonly dbStore: ConversationStore,
    private readonly checkpoints: CheckpointManager,
    private readonly platformFactory: PlatformFactory
  ) {}

  /**
   * taey_connect equivalent.
   */
  async connect(input: {
    platform: InterfaceType;
    newSession?: boolean;
    conversationId?: string | null;
  }) {
    const { platform, newSession = false, conversationId = null } = input;

    // For resume flows, we'll navigate directly to the existing URL
    // inside the platform-specific implementation.
    const platformSession = await this.platformFactory.createPlatformSession(
      platform,
      { conversationId, newSession }
    );

    const managed = await this.sessions.createSession(platform, platformSession);

    // Auto-create a 'plan' checkpoint with validated=false so
    // tools know they must validate before doing dangerous things. 
    await this.checkpoints.createCheckpoint({
      conversationId: managed.conversationDbId,
      step: "plan",
      validated: false,
      notes:
        "Auto-created plan checkpoint on connect(). You must review the session state and validate the plan before sending messages or attaching files.",
      screenshot: await managed.platformSession.takeScreenshot("connect-initial"),
      requiredAttachments: [],
      actualAttachments: [],
    });

    return {
      sessionId: managed.sessionId,
      conversationDbId: managed.conversationDbId,
      platform,
      state: managed.state,
      screenshot: await managed.platformSession.takeScreenshot("connect-summary"),
    };
  }

  /**
   * Explicit disconnect tool.
   */
  async disconnect(sessionId: string) {
    await this.sessions.destroySession(sessionId, "CLOSED");
    return { sessionId, status: "closed" as const };
  }
}
```

---

## 6. MCP Tool Layer (connect / attach / validate / send)

These are framework‑agnostic handlers you can call from your actual Anthropic MCP server switch; they encapsulate all the new logic and give **explicit next‑step guidance** in responses.

### 6.1 Zod Schemas

`src/v2/mcp/validators/schemas.ts`

```ts
// src/v2/mcp/validators/schemas.ts
import { z } from "zod";
import { InterfaceType } from "../../core/browser/types";

export const connectSchema = z.object({
  platform: z.custom<InterfaceType>().describe(
    "AI chat platform (claude, chatgpt, gemini, grok, perplexity)"
  ),
  newSession: z.boolean().optional().default(false),
  conversationId: z.string().nullable().optional(),
});

export const attachFilesSchema = z.object({
  sessionId: z.string(),
  conversationId: z.string(),
  filePaths: z.array(z.string().min(1)).min(1),
});

export const validateStepSchema = z.object({
  conversationId: z.string(),
  step: z.enum([
    "plan",
    "attach_files",
    "type_message",
    "click_send",
    "wait_response",
    "extract_response",
  ]),
  validated: z.boolean(),
  notes: z.string().min(1),
  screenshot: z.string().optional(),
  requiredAttachments: z.array(z.string()).optional(),
});

export const sendMessageSchema = z.object({
  sessionId: z.string(),
  conversationId: z.string(),
  message: z.string().min(1),
  waitForResponse: z.boolean().optional().default(true),
});
```

### 6.2 connect

`src/v2/mcp/tools/connect.ts`

```ts
// src/v2/mcp/tools/connect.ts
import { SessionWorkflow } from "../../workflow/session-workflow";
import { connectSchema } from "../validators/schemas";

export async function handleConnectTool(
  rawArgs: unknown,
  deps: { sessionWorkflow: SessionWorkflow }
) {
  const args = connectSchema.parse(rawArgs);

  const result = await deps.sessionWorkflow.connect({
    platform: args.platform,
    newSession: args.newSession,
    conversationId: args.conversationId ?? null,
  });

  return {
    success: true,
    ...result,
    nextStep:
      "Review the screenshots, define your plan, then call taey_validate_step(step='plan', validated=true, notes='Plan looks correct').",
  };
}
```

### 6.3 attach_files

`src/v2/mcp/tools/attach-files.ts`

```ts
// src/v2/mcp/tools/attach-files.ts
import { AttachmentWorkflow } from "../../workflow/attachment-workflow";
import { attachFilesSchema } from "../validators/schemas";

export async function handleAttachFilesTool(
  rawArgs: unknown,
  deps: { attachmentWorkflow: AttachmentWorkflow }
) {
  const args = attachFilesSchema.parse(rawArgs);

  const result = await deps.attachmentWorkflow.attachFiles({
    sessionId: args.sessionId,
    conversationId: args.conversationId,
    filePaths: args.filePaths,
  });

  return {
    success: true,
    automationCompleted: result.automationCompleted,
    screenshot: result.screenshot,
    validation: result.validation,
    nextStep:
      "Open the screenshot, confirm all files are visible above the input, then call taey_validate_step(step='attach_files', validated=true, notes='Files visible as pills in input area').",
  };
}
```

### 6.4 validate_step

`src/v2/mcp/tools/validate-step.ts`

This is just a thin wrapper over `CheckpointManager.createCheckpoint`, matching your existing MCP integration.

```ts
// src/v2/mcp/tools/validate-step.ts
import { CheckpointManager } from "../../core/validation/checkpoint-manager";
import { validateStepSchema } from "../validators/schemas";

export async function handleValidateStepTool(
  rawArgs: unknown,
  deps: { checkpoints: CheckpointManager }
) {
  const args = validateStepSchema.parse(rawArgs);

  const checkpoint = await deps.checkpoints.createCheckpoint({
    conversationId: args.conversationId,
    step: args.step,
    validated: args.validated,
    notes: args.notes,
    screenshot: args.screenshot ?? null,
    requiredAttachments: args.requiredAttachments ?? [],
    actualAttachments: [], // attach_files tool populates this
  });

  return {
    success: true,
    validationId: checkpoint.id,
    step: checkpoint.step,
    validated: checkpoint.validated,
    timestamp: checkpoint.timestamp,
    requiredAttachments: checkpoint.requiredAttachments,
    message: checkpoint.validated
      ? `✓ Step '${checkpoint.step}' validated. You may proceed to the next workflow step.`
      : `✗ Step '${checkpoint.step}' marked as failed. Fix the issue and retry before proceeding.`,
  };
}
```

### 6.5 send_message

`src/v2/mcp/tools/send-message.ts`

This uses `RequirementEnforcer` to block bad sequences and relies on `ManagedSession.execute` to keep state in sync.

```ts
// src/v2/mcp/tools/send-message.ts
import { SessionManager } from "../../core/browser/session-manager";
import { RequirementEnforcer } from "../../core/validation/requirement-enforcer";
import { sendMessageSchema } from "../validators/schemas";

/**
 * taey_send_message v2:
 * - Enforces attachment + validation requirements
 * - Logs user+assistant messages via ConversationStore (outside this handler)
 * - Uses platform's response detection engine (waitForResponse)
 */
export async function handleSendMessageTool(
  rawArgs: unknown,
  deps: {
    sessions: SessionManager;
    enforcer: RequirementEnforcer;
  }
) {
  const args = sendMessageSchema.parse(rawArgs);

  await deps.enforcer.ensureCanSendMessage(args.conversationId);

  const session = deps.sessions.getSession(args.sessionId);

  // Type + send
  await session.execute((platform) => platform.typeMessage(args.message));
  await session.execute((platform) => platform.clickSend());

  let responseText: string | null = null;
  if (args.waitForResponse) {
    responseText = await session.execute((platform) =>
      platform.waitForResponse()
    );
  }

  const screenshot = await session.execute((platform) =>
    platform.takeScreenshot("after-send")
  );

  return {
    success: true,
    screenshot,
    response: responseText,
    automationCompleted: true,
  };
}
```

---

## 7. How this ties back to your existing pieces

* **ValidationCheckpointStore**: Reused via the `ValidationStore` interface in `checkpoint-manager.ts`. No schema changes required beyond what you’ve already added (`requiredAttachments` / `actualAttachments` + `requiresAttachments()`).

* **Response detection engine**: Lives behind `PlatformSession.waitForResponse()`, so you can drop in the Fibonacci polling + stability detection you already know works.

* **Finder navigation / attachment patterns**: The same `_navigateFinderDialog` / Cmd+Shift+G logic from `chat-interface.js` now lives in each platform’s `attachFiles()` method, while `AttachmentWorkflow` + `StepValidator` handle validation + checkpoints.

* **Platform quirks** (Grok JS click, Gemini overlays / disabled Start Research button, etc.) stay in the platform classes you inject via `PlatformFactory.createPlatformSession()`, instead of being interleaved with session/validation/MCP logic.

* **Session recovery / orphan detection** is implemented via `SessionManager.syncWithDatabase()` and the health check pattern from `SESSION_REQUIREMENTS.md`.

---

If you’d like, next step I can sketch one fully‑wired **platform implementation** (say `ClaudePlatformSession`) that uses the selector registry + bridge patterns and shows exactly where you plug in your AppleScript/xdotool and existing `_navigateFinderDialog` / coordinate-click tricks.
