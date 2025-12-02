#!/usr/bin/env node

/**
 * Taey-Hands MCP Server v2
 * Function-based tools with session management
 *
 * Architecture: Tool → SessionManager → Interface → Method
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { getSessionManager, type InterfaceType } from "./session-manager.js";
// @ts-ignore - conversation-store is JS, not TS
import { getConversationStore } from "../../src/core/conversation-store.js";
// @ts-ignore - response-detection is JS, not TS
import { ResponseDetectionEngine } from "../../src/core/response-detection.js";
// @ts-ignore - validation-checkpoints is JS, not TS
import { ValidationCheckpointStore } from "../../src/core/validation-checkpoints.js";
// @ts-ignore - RequirementEnforcer is JS, not TS
import { RequirementEnforcer } from "../../src/v2/core/validation/requirement-enforcer.js";

// Get singleton session manager
const sessionManager = getSessionManager();

// Get conversation store for Neo4j logging
const conversationStore = getConversationStore();

// Get validation checkpoint store
const validationStore = new ValidationCheckpointStore();

// Initialize RequirementEnforcer - CRITICAL component that prevents attachment bypass
const requirementEnforcer = new RequirementEnforcer(validationStore);

// Initialize schema on startup
conversationStore.initSchema().catch((err: any) => {
  console.error('[MCP] Failed to initialize ConversationStore schema:', err.message);
});

validationStore.initSchema().catch((err: any) => {
  console.error('[MCP] Failed to initialize ValidationCheckpointStore schema:', err.message);
});

// Reconcile orphaned sessions on startup
sessionManager.syncWithDatabase(conversationStore).catch((err: any) => {
  console.error('[MCP] Failed to reconcile orphaned sessions on startup:', err.message);
});

/**
 * MCP Tools Definitions
 */
const TOOLS: Tool[] = [
  {
    name: "taey_connect",
    description: "Connect to a chat interface (Claude, ChatGPT, Gemini, Grok, or Perplexity). REQUIRES explicit session management: either provide sessionId to reuse an existing session, or set newSession=true to create a fresh session. Returns screenshot and session ID.",
    inputSchema: {
      type: "object",
      properties: {
        interface: {
          type: "string",
          enum: ["claude", "chatgpt", "gemini", "grok", "perplexity"],
          description: "Which chat interface to connect to"
        },
        sessionId: {
          type: "string",
          description: "Optional: Reuse an existing session ID. Mutually exclusive with newSession."
        },
        newSession: {
          type: "boolean",
          description: "Optional: Set to true to create a new session. Mutually exclusive with sessionId."
        },
        conversationId: {
          type: "string",
          description: "Optional: Conversation ID or full URL to resume existing conversation. If omitted, starts at interface homepage."
        }
      },
      required: ["interface"]
    }
  },
  {
    name: "taey_disconnect",
    description: "Disconnect from a chat interface session. Cleans up browser automation and releases resources.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        }
      },
      required: ["sessionId"]
    }
  },
  {
    name: "taey_new_conversation",
    description: "Start a new chat conversation. Navigates to a fresh conversation in the connected interface.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        }
      },
      required: ["sessionId"]
    }
  },
  {
    name: "taey_plan_message",
    description: "Plan a message with requirements. OPTIONAL but RECOMMENDED before sending. Creates a validation checkpoint that tracks message content and required attachments. If you specify requiredAttachments, you MUST call taey_attach_files before taey_send_message or the send will be BLOCKED. This enables proactive validation instead of reactive error handling.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        },
        message: {
          type: "string",
          description: "The message you plan to send"
        },
        requiredAttachments: {
          type: "array",
          items: { type: "string" },
          description: "Array of file paths that MUST be attached before sending. If specified, taey_send_message will fail unless these files are attached via taey_attach_files first.",
          default: []
        }
      },
      required: ["sessionId", "message"]
    }
  },
  {
    name: "taey_send_message",
    description: "Type and send a message in the current conversation. Uses human-like typing and clicks the send button. Returns immediately after sending. Use taey_wait_for_response to wait for the AI's response.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        },
        message: {
          type: "string",
          description: "The message to send"
        },
        attachments: {
          type: "array",
          description: "Array of file paths to attach to the message",
          items: {
            type: "string"
          },
          default: []
        }
      },
      required: ["sessionId", "message"]
    }
  },
  {
    name: "taey_wait_for_response",
    description: "Wait for AI response completion with configurable timeout. Handles long-running operations (Extended Thinking, Deep Research). Returns extracted response text and saves to Neo4j. Use this after taey_send_message.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        },
        maxWaitSeconds: {
          type: "number",
          description: "Maximum wait time in seconds. Default 600 (10 min). Set higher for Extended Thinking (900 for 15 min) or Deep Research (1200 for 20 min).",
          default: 600
        }
      },
      required: ["sessionId"]
    }
  },
  {
    name: "taey_extract_response",
    description: "Extract the latest AI response text from the current conversation. Returns the text content of the most recent AI message.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        }
      },
      required: ["sessionId"]
    }
  },
  {
    name: "taey_select_model",
    description: "Select an AI model in the current conversation. Works with Claude, ChatGPT, Gemini, and Grok interfaces. Returns screenshot showing the selected model.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        },
        modelName: {
          type: "string",
          description: "Model name to select. Options vary by interface:\n- Claude: 'Opus 4.5', 'Sonnet 4', 'Haiku 4'\n- ChatGPT: 'Auto', 'Instant', 'Thinking', 'Pro', 'GPT-4o' (legacy)\n- Gemini: 'Thinking with 3 Pro', 'Thinking'\n- Grok: 'Grok 4.1', 'Grok 4.1 Thinking', 'Grok 4 Heavy'"
        },
        isLegacy: {
          type: "boolean",
          description: "ChatGPT only: Set to true for legacy models like GPT-4o that are in the Legacy submenu",
          default: false
        }
      },
      required: ["sessionId", "modelName"]
    }
  },
  {
    name: "taey_attach_files",
    description: "Attach one or more files to the conversation. Uses human-like file dialog navigation (cross-platform: Cmd+Shift+G on macOS, Ctrl+L on Linux) to locate and attach files.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        },
        filePaths: {
          type: "array",
          items: {
            type: "string"
          },
          description: "Array of absolute file paths to attach"
        }
      },
      required: ["sessionId", "filePaths"]
    }
  },
  {
    name: "taey_paste_response",
    description: "Copy an AI response from one chat session and paste it into another chat session (cross-pollination). Extracts the latest response from the source session and sends it to the target session with optional prefix.",
    inputSchema: {
      type: "object",
      properties: {
        sourceSessionId: {
          type: "string",
          description: "Session ID to extract response from"
        },
        targetSessionId: {
          type: "string",
          description: "Session ID to paste response into"
        },
        prefix: {
          type: "string",
          description: "Optional prefix to add before the pasted response (e.g., 'Another AI said: ')",
          default: ""
        }
      },
      required: ["sourceSessionId", "targetSessionId"]
    }
  },
  {
    name: "taey_enable_research_mode",
    description: "Enable extended thinking or research modes. Works with Claude (Extended Thinking), ChatGPT (Deep research), Gemini (Deep Research/Deep Think), and Perplexity (Pro Search). Returns screenshot confirming the mode change.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        },
        enabled: {
          type: "boolean",
          description: "Whether to enable (true) or disable (false) research mode. For Claude only - other interfaces always enable.",
          default: true
        },
        modeName: {
          type: "string",
          description: "Optional mode name. For ChatGPT: 'Deep research'. For Gemini: 'Deep Research' or 'Deep Think'. Ignored for Claude and Perplexity."
        }
      },
      required: ["sessionId"]
    }
  },
  {
    name: "taey_download_artifact",
    description: "Download an artifact file from a chat response. Works with Claude (sidebar-based extraction), Gemini (multi-step export), and Perplexity (multi-step export). ChatGPT and Grok do not support artifact downloads.",
    inputSchema: {
      type: "object",
      properties: {
        sessionId: {
          type: "string",
          description: "Session ID returned from taey_connect"
        },
        artifactName: {
          type: "string",
          description: "Optional: Name of specific artifact to download (Claude only). If not provided, downloads first available artifact."
        },
        downloadPath: {
          type: "string",
          description: "Directory path to save the downloaded file. Defaults to /tmp",
          default: "/tmp"
        },
        format: {
          type: "string",
          description: "Download format for Gemini/Perplexity: 'markdown' or 'html'. Ignored for Claude. Defaults to 'markdown'",
          default: "markdown"
        },
        timeout: {
          type: "number",
          description: "Timeout in milliseconds to wait for download button. Defaults to 10000ms",
          default: 10000
        }
      },
      required: ["sessionId"]
    }
  },
  {
    name: "taey_validate_step",
    description: "Validate a workflow step after reviewing screenshot. REQUIRED between each workflow step to prevent runaway execution. Creates validation checkpoint in Neo4j that next tool will check.",
    inputSchema: {
      type: "object",
      properties: {
        conversationId: {
          type: "string",
          description: "Conversation ID (same as sessionId)"
        },
        step: {
          type: "string",
          enum: ["plan", "attach_files", "type_message", "click_send", "wait_response", "extract_response"],
          description: "Which workflow step to validate"
        },
        validated: {
          type: "boolean",
          description: "True if step succeeded and screenshot confirms it, false if failed"
        },
        notes: {
          type: "string",
          description: "REQUIRED: What you observed in the screenshot that confirms validation"
        },
        screenshot: {
          type: "string",
          description: "Optional: Screenshot path if not from previous tool"
        },
        requiredAttachments: {
          type: "array",
          items: { type: "string" },
          description: "For 'plan' step: Array of file paths that MUST be attached before sending"
        }
      },
      required: ["conversationId", "step", "validated", "notes"]
    }
  }
];

/**
 * Create MCP server
 */
const server = new Server(
  {
    name: "taey-hands",
    version: "0.2.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

/**
 * Handler: List available tools
 */
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: TOOLS,
  };
});

/**
 * Handler: Execute tool
 */
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "taey_connect": {
        const { interface: interfaceType, sessionId: providedSessionId, newSession, conversationId } = args as {
          interface: InterfaceType;
          sessionId?: string;
          newSession?: boolean;
          conversationId?: string;
        };

        // VALIDATION: Require explicit session decision
        if (!providedSessionId && !newSession) {
          throw new Error('Must specify either sessionId (to reuse) or newSession=true (to create). No defaults allowed.');
        }
        if (providedSessionId && newSession) {
          throw new Error('Cannot specify both sessionId and newSession=true. Choose one.');
        }

        // Determine session ID and connect
        let sessionId: string;
        let actualConversationId: string | undefined;

        if (newSession) {
          // Create new session - SessionManager.createSession() handles connect() internally
          sessionId = await sessionManager.createSession(interfaceType, {
            newConversation: !conversationId,  // Only set if NOT resuming an existing conversation
            conversationId: conversationId     // Pass through if resuming
          });

          // Extract conversationId from the URL after connection
          // SessionManager already called connect(), so we can get the current URL
          const chatInterface = sessionManager.getInterface(sessionId);
          const currentUrl = await chatInterface.getCurrentConversationUrl();
          actualConversationId = chatInterface._extractConversationId ?
            chatInterface._extractConversationId(currentUrl) : conversationId;

          // Create conversation in Neo4j
          try {
            await conversationStore.createConversation({
              id: sessionId,
              title: conversationId ? `Resume: ${conversationId}` : `New ${interfaceType} session`,
              purpose: 'AI Family collaboration via Taey Hands MCP',
              initiator: 'mcp_server',
              platforms: [interfaceType],
              platform: interfaceType,  // Add platform as top-level field for querying
              sessionId: sessionId,      // Add sessionId as top-level field
              conversationId: actualConversationId || null,  // Add conversationId as top-level field
              metadata: {
                conversationId: actualConversationId || null,
                createdVia: 'taey_connect'
              }
            });
          } catch (err: any) {
            console.error('[MCP] Failed to create conversation in Neo4j:', err.message);
          }
        } else {
          // Reuse existing session
          sessionId = providedSessionId!;

          // If conversationId provided, navigate to that conversation
          if (conversationId) {
            const chatInterface = sessionManager.getInterface(sessionId);
            await chatInterface.goToConversation(conversationId);
            actualConversationId = conversationId;
          }
        }

        // Get screenshot path from interface
        const chatInterface = sessionManager.getInterface(sessionId);
        const screenshotPath = `/tmp/taey-${interfaceType}-${sessionId}-connected.png`;

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                sessionId,
                interface: interfaceType,
                conversationId: actualConversationId || undefined,
                screenshot: screenshotPath,
                message: actualConversationId
                  ? `Connected to ${interfaceType} at conversation ${actualConversationId}`
                  : `Connected to ${interfaceType}`,
              }, null, 2),
            },
          ],
        };
      }

      case "taey_disconnect": {
        const { sessionId } = args as { sessionId: string };

        // Destroy session
        await sessionManager.destroySession(sessionId);

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                sessionId,
                message: "Session disconnected",
              }, null, 2),
            },
          ],
        };
      }

      case "taey_new_conversation": {
        const { sessionId } = args as { sessionId: string };

        // Get interface from session
        const chatInterface = sessionManager.getInterface(sessionId);

        // Start new conversation
        await chatInterface.newConversation();

        // Get the current conversation URL
        const conversationUrl = await chatInterface.getCurrentConversationUrl();

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                sessionId,
                conversationUrl,
                message: "New conversation started",
              }, null, 2),
            },
          ],
        };
      }

      case "taey_plan_message": {
        const { sessionId, message, requiredAttachments = [] } = args as {
          sessionId: string;
          message: string;
          requiredAttachments?: string[];
        };

        // PRE-FLIGHT: Validate session health
        await sessionManager.validateSessionHealth(sessionId);

        // Create plan checkpoint in Neo4j
        const checkpoint = await validationStore.createCheckpoint({
          conversationId: sessionId,
          step: 'plan',
          validated: true, // Plan is immediately validated
          notes: `Plan created: message (${message.length} chars), ${requiredAttachments.length} required attachment(s)`,
          requiredAttachments,
          actualAttachments: [] // No attachments yet
        });

        const hasAttachments = requiredAttachments.length > 0;

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                sessionId,
                checkpointId: checkpoint.id,
                requirements: {
                  messagePreview: message.substring(0, 100) + (message.length > 100 ? '...' : ''),
                  attachmentsRequired: hasAttachments,
                  requiredAttachments,
                  count: requiredAttachments.length
                },
                nextStep: hasAttachments
                  ? `Call taey_attach_files with [${requiredAttachments.join(', ')}], then taey_validate_step(step='attach_files', validated=true), then taey_send_message`
                  : 'Call taey_send_message to send (no attachments required)',
                note: 'Plan checkpoint created. RequirementEnforcer will BLOCK taey_send_message if attachments are skipped.'
              }, null, 2),
            },
          ],
        };
      }

      case "taey_send_message": {
        const { sessionId, message, attachments } = args as {
          sessionId: string;
          message: string;
          attachments?: string[];
        };

        // PRE-FLIGHT: Validate session health
        await sessionManager.validateSessionHealth(sessionId);

        // BLOCKING CHECK: Prevent sending while a response is pending
        if (sessionManager.isResponsePending(sessionId)) {
          throw new Error(
            `Cannot send message: response already in progress for session ${sessionId}. ` +
            `Please wait for the response to complete (use taey_wait_for_response or taey_extract_response) ` +
            `before sending another message. This prevents race conditions and conversation flow confusion.`
          );
        }

        // VALIDATION CHECKPOINT: Use RequirementEnforcer to block send if requirements not met
        // This makes it mathematically impossible to skip attachments when plan specifies them
        await requirementEnforcer.ensureCanSendMessage(sessionId);
        console.error(`[MCP] ✓ Validation passed - proceeding with send`);

        // Get interface from session
        const chatInterface = sessionManager.getInterface(sessionId);
        const interfaceName = chatInterface.name;
        const session = sessionManager.getSession(sessionId);

        // Log to Neo4j - store sent message
        try {
          await conversationStore.addMessage(sessionId, {
            role: 'user',
            content: message,
            platform: interfaceName,
            timestamp: new Date().toISOString(),
            attachments: attachments || [],
            metadata: { source: 'mcp_taey_send_message' }
          });
        } catch (err: any) {
          console.error('[MCP] Failed to log message to Neo4j:', err.message);
        }

        // Prepare input (focus)
        await chatInterface.prepareInput();

        // Type message with human-like typing
        await chatInterface.typeMessage(message);

        // Click send button
        await chatInterface.clickSend();

        // POST-SYNC: Update session state in database
        try {
          const currentUrl = await chatInterface.getCurrentConversationUrl();
          await conversationStore.updateSessionState(sessionId, currentUrl, interfaceName);
        } catch (err: any) {
          console.error('[MCP] Failed to sync session state after send:', err.message);
        }

        // MARK RESPONSE PENDING: Block subsequent sends until response extracted
        sessionManager.markResponsePending(sessionId);

        console.error(`[MCP] Message sent successfully. Use taey_wait_for_response to wait for AI response.`);

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                sessionId,
                message: "Message sent. Use taey_wait_for_response to wait for AI response.",
                sentText: message,
              }, null, 2),
            },
          ],
        };
      }

      case "taey_wait_for_response": {
        const { sessionId, maxWaitSeconds = 600 } = args as {
          sessionId: string;
          maxWaitSeconds?: number;
        };

        await sessionManager.validateSessionHealth(sessionId);

        const chatInterface = sessionManager.getInterface(sessionId);
        const interfaceName = chatInterface.name;
        const session = sessionManager.getSession(sessionId);

        console.error(`[MCP] Waiting for response from ${interfaceName} (max ${maxWaitSeconds}s)...`);

        try {
          // Create detection engine with platform-specific timeout
          const detector = new ResponseDetectionEngine(
            chatInterface.page,
            session?.interfaceType || interfaceName,
            { debug: true }
          );

          // Wait for response completion
          const startTime = Date.now();
          const detectionResult = await detector.detectCompletion();
          const responseText = detectionResult.content;
          const timestamp = new Date().toISOString();
          const waitTime = Math.round((Date.now() - startTime) / 1000);

          console.error(`[MCP] Response detected (${detectionResult.method}, ${detectionResult.confidence * 100}% confidence) after ${waitTime}s`);

          // Log response to Neo4j
          try {
            await conversationStore.addMessage(sessionId, {
              role: 'assistant',
              content: responseText,
              platform: interfaceName,
              timestamp,
              metadata: {
                source: 'mcp_taey_wait_for_response',
                detectionMethod: detectionResult.method,
                detectionConfidence: detectionResult.confidence,
                detectionTime: detectionResult.detectionTime,
                waitTimeSeconds: waitTime,
                contentLength: responseText.length
              }
            });
          } catch (err: any) {
            console.error('[MCP] Failed to log response to Neo4j:', err.message);
          }

          // CLEAR RESPONSE PENDING: Response received, can send again
          sessionManager.markResponseComplete(sessionId);

          return {
            content: [
              {
                type: "text",
                text: JSON.stringify({
                  success: true,
                  sessionId,
                  responseText,
                  responseLength: responseText.length,
                  waitTimeSeconds: waitTime,
                  detectionMethod: detectionResult.method,
                  detectionConfidence: detectionResult.confidence,
                  timestamp
                }, null, 2),
              },
            ],
          };
        } catch (err: any) {
          console.error('[MCP] Response detection failed:', err.message);
          // CLEAR RESPONSE PENDING even on timeout - don't block forever
          sessionManager.markResponseComplete(sessionId);
          return {
            content: [
              {
                type: "text",
                text: JSON.stringify({
                  success: false,
                  sessionId,
                  error: err.message,
                  message: `Failed to detect response within ${maxWaitSeconds}s. Use taey_extract_response to manually extract if response is visible.`
                }, null, 2),
              },
            ],
            isError: true,
          };
        }
      }

      case "taey_extract_response": {
        const { sessionId } = args as { sessionId: string };

        // PRE-FLIGHT: Validate session health
        await sessionManager.validateSessionHealth(sessionId);

        // Get interface from session
        const chatInterface = sessionManager.getInterface(sessionId);
        const interfaceName = chatInterface.name;

        // Extract latest response
        const responseText = await chatInterface.getLatestResponse();
        const timestamp = new Date().toISOString();

        // Log to Neo4j - store assistant response
        try {
          await conversationStore.addMessage(sessionId, {
            role: 'assistant',
            content: responseText,
            platform: interfaceName,
            timestamp,
            metadata: {
              source: 'mcp_taey_extract_response',
              contentLength: responseText.length
            }
          });
        } catch (err: any) {
          console.error('[MCP] Failed to log response to Neo4j:', err.message);
        }

        // POST-SYNC: Update session state in database
        try {
          const currentUrl = await chatInterface.getCurrentConversationUrl();
          await conversationStore.updateSessionState(sessionId, currentUrl, interfaceName);
        } catch (err: any) {
          console.error('[MCP] Failed to sync session state after extract response:', err.message);
        }

        // CLEAR RESPONSE PENDING: Response extracted, can send again
        sessionManager.markResponseComplete(sessionId);

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                responseText,
                timestamp,
              }, null, 2),
            },
          ],
        };
      }

      case "taey_select_model": {
        const { sessionId, modelName, isLegacy = false } = args as {
          sessionId: string;
          modelName: string;
          isLegacy?: boolean;
        };

        // PRE-FLIGHT: Validate session health
        await sessionManager.validateSessionHealth(sessionId);

        // Get session to check interface type
        const session = sessionManager.getSession(sessionId);
        if (!session) {
          throw new Error(`Session not found: ${sessionId}`);
        }

        // Get interface from session
        const chatInterface = sessionManager.getInterface(sessionId);

        // Verify interface has selectModel method
        if (typeof chatInterface.selectModel !== 'function') {
          throw new Error(`Model selection not supported for ${session.interfaceType}`);
        }

        // Call selectModel with interface-specific parameters
        let result;
        if (session.interfaceType === "chatgpt") {
          // ChatGPT: pass isLegacy parameter
          result = await chatInterface.selectModel(modelName, isLegacy, { sessionId });
        } else {
          // Claude, Gemini, Grok: standard call
          result = await chatInterface.selectModel(modelName, { sessionId });
        }

        // POST-SYNC: Update session state in database
        try {
          const currentUrl = await chatInterface.getCurrentConversationUrl();
          await conversationStore.updateSessionState(sessionId, currentUrl, session.interfaceType);
        } catch (err: any) {
          console.error('[MCP] Failed to sync session state after model selection:', err.message);
        }

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                automationCompleted: true,
                sessionId,
                interfaceType: session.interfaceType,
                modelName: result.modelName,
                screenshot: result.screenshot,
                message: `Automation completed for model: ${result.modelName}. VERIFY in screenshot - tool cannot confirm UI actually changed.`,
              }, null, 2),
            },
          ],
        };
      }

      case "taey_attach_files": {
        const { sessionId, filePaths } = args as {
          sessionId: string;
          filePaths: string[];
        };

        // PRE-FLIGHT: Validate session health
        await sessionManager.validateSessionHealth(sessionId);

        // VALIDATION CHECKPOINT: Ensure plan step is validated before attaching files
        await requirementEnforcer.ensureCanAttachFiles(sessionId);

        // Get interface from session
        const chatInterface = sessionManager.getInterface(sessionId);
        const interfaceName = chatInterface.name;

        // Attach each file and collect results
        const attachmentResults = [];
        let lastScreenshot = '';

        for (const filePath of filePaths) {
          const result = await chatInterface.attachFile(filePath, { sessionId });
          attachmentResults.push({
            filePath,
            screenshot: result.screenshot,
            automationCompleted: result.automationCompleted
          });
          lastScreenshot = result.screenshot; // Keep last screenshot
        }

        // Create pending validation checkpoint (must be validated before continuing)
        await validationStore.createCheckpoint({
          conversationId: sessionId,
          step: 'attach_files',
          validated: false,
          notes: `Attached ${attachmentResults.length} file(s). Awaiting manual validation. MUST call taey_validate_step with validated=true after reviewing screenshot.`,
          screenshot: lastScreenshot,
          requiredAttachments: [],
          actualAttachments: filePaths
        });

        // POST-SYNC: Update session state in database
        try {
          const currentUrl = await chatInterface.getCurrentConversationUrl();
          await conversationStore.updateSessionState(sessionId, currentUrl, interfaceName);
        } catch (err: any) {
          console.error('[MCP] Failed to sync session state after attach files:', err.message);
        }

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                automationCompleted: true,
                filesAttached: attachmentResults.length,
                attachments: attachmentResults,
                screenshot: lastScreenshot,
                message: `Automation completed for ${attachmentResults.length} file(s). VERIFY in screenshot and call taey_validate_step to confirm.`,
              }, null, 2),
            },
          ],
        };
      }

      case "taey_paste_response": {
        const { sourceSessionId, targetSessionId, prefix } = args as {
          sourceSessionId: string;
          targetSessionId: string;
          prefix?: string;
        };

        // Get source interface and extract response
        const sourceInterface = sessionManager.getInterface(sourceSessionId);
        const responseText = await sourceInterface.getLatestResponse();

        if (!responseText) {
          throw new Error(`No response found in source session ${sourceSessionId}`);
        }

        // Build message with optional prefix
        const messageToSend = prefix ? `${prefix}${responseText}` : responseText;

        // Get target interface and PASTE message (not type!)
        const targetInterface = sessionManager.getInterface(targetSessionId);
        await targetInterface.prepareInput();
        await targetInterface.pasteMessage(messageToSend);
        await targetInterface.clickSend();

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                sourceSessionId,
                targetSessionId,
                pastedText: messageToSend,
                responseLength: responseText.length,
                prefixUsed: prefix || "",
                message: "Response pasted successfully",
              }, null, 2),
            },
          ],
        };
      }

      case "taey_enable_research_mode": {
        const { sessionId, enabled = true, modeName } = args as {
          sessionId: string;
          enabled?: boolean;
          modeName?: string;
        };

        // Get session to check interface type
        const session = sessionManager.getSession(sessionId);
        if (!session) {
          throw new Error(`Session not found: ${sessionId}`);
        }

        // Get interface from session
        const chatInterface = sessionManager.getInterface(sessionId);

        let result;
        let screenshot = '';

        // Call appropriate method based on interface type
        if (session.interfaceType === "claude") {
          // Claude: use setResearchMode(enabled)
          await chatInterface.setResearchMode(enabled);
          // Take screenshot to confirm
          screenshot = await chatInterface.screenshot();
          result = {
            automationCompleted: true,
            screenshot,
            enabled,
            mode: enabled ? "Extended Thinking enabled" : "Extended Thinking disabled"
          };
        } else if (session.interfaceType === "chatgpt") {
          // ChatGPT: use setMode() with Deep research
          const mode = modeName || "Deep research";
          result = await chatInterface.setMode(mode, { sessionId });
          screenshot = result.screenshot || '';
          result.mode = `${mode} enabled`;
        } else if (session.interfaceType === "gemini") {
          // Gemini: use setMode() with Deep Research or Deep Think
          const mode = modeName || "Deep Research";
          result = await chatInterface.setMode(mode, { sessionId });
          screenshot = result.screenshot || '';
          result.mode = `${mode} enabled`;
        } else if (session.interfaceType === "perplexity") {
          // Perplexity: use enableResearchMode() - always enables
          result = await chatInterface.enableResearchMode({ sessionId });
          screenshot = result.screenshot || '';
          result.mode = "Pro Search enabled";
        } else {
          // Other interfaces: try generic enableResearchMode if available
          if (typeof chatInterface.enableResearchMode === 'function') {
            result = await chatInterface.enableResearchMode({ sessionId });
            screenshot = result.screenshot || '';
            result.mode = "Research mode enabled";
          } else {
            throw new Error(`Research mode not supported for ${session.interfaceType}`);
          }
        }

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                sessionId,
                interfaceType: session.interfaceType,
                screenshot,
                enabled: session.interfaceType === "claude" ? enabled : true,
                mode: result.mode,
                message: result.mode,
              }, null, 2),
            },
          ],
        };
      }

      case "taey_download_artifact": {
        const { sessionId, artifactName, downloadPath = "/tmp", format = "markdown", timeout = 10000 } = args as {
          sessionId: string;
          artifactName?: string;
          downloadPath?: string;
          format?: string;
          timeout?: number;
        };

        // Get interface from session
        const session = sessionManager.getSession(sessionId);
        const chatInterface = sessionManager.getInterface(sessionId);

        // Check if interface supports downloadArtifact
        if (typeof chatInterface.downloadArtifact !== 'function') {
          throw new Error(`Artifact download not supported for ${session?.interfaceType || 'this interface'}`);
        }

        // Call downloadArtifact method with interface-specific options
        const result = await chatInterface.downloadArtifact({
          artifactName,
          downloadPath,
          format,
          timeout,
          sessionId
        });

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: result.automationCompleted || result.downloaded || false,
                sessionId,
                interfaceType: session?.interfaceType || 'unknown',
                filePath: result.filePath,
                screenshot: result.screenshot,
                format: format,
                message: result.filePath
                  ? `Downloaded artifact to: ${result.filePath}`
                  : "No artifact download button found",
              }, null, 2),
            },
          ],
        };
      }

      case "taey_validate_step": {
        const { conversationId, step, validated, notes, screenshot, requiredAttachments } = args as {
          conversationId: string;
          step: string;
          validated: boolean;
          notes: string;
          screenshot?: string;
          requiredAttachments?: string[];
        };

        // CRITICAL: For attach_files step, preserve actualAttachments from pending checkpoint
        let actualAttachments: string[] = [];
        if (step === 'attach_files') {
          const lastCheckpoint = await validationStore.getLastValidation(conversationId);
          if (lastCheckpoint && lastCheckpoint.step === 'attach_files' && !lastCheckpoint.validated) {
            // Preserve actualAttachments from the pending checkpoint created by taey_attach_files
            actualAttachments = lastCheckpoint.actualAttachments || [];
            console.error(`[MCP] ✓ Preserving ${actualAttachments.length} actualAttachments from pending checkpoint`);
          }
        }

        // Create validation checkpoint
        const checkpoint = await validationStore.createCheckpoint({
          conversationId,
          step,
          validated,
          notes,
          screenshot: screenshot || null,
          requiredAttachments: requiredAttachments || [],
          actualAttachments
        });

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                success: true,
                validationId: checkpoint.id,
                step,
                validated,
                timestamp: checkpoint.timestamp,
                requiredAttachments: checkpoint.requiredAttachments,
                message: validated
                  ? `✓ Step '${step}' validated. Can proceed to next step.`
                  : `✗ Step '${step}' marked as failed. Fix and retry before proceeding.`
              }, null, 2),
            },
          ],
        };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (error: any) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: false,
            error: error.message || String(error),
          }, null, 2),
        },
      ],
      isError: true,
    };
  }
});

/**
 * Start server
 */
async function main() {
  const transport = new StdioServerTransport();

  // Global error handlers - CRITICAL for Linux stability
  process.on('unhandledRejection', (reason, promise) => {
    console.error('[MCP] Unhandled Rejection:', reason);
    // Don't exit - log and continue. Most rejections are from browser operations
    // that have already been handled at a higher level.
  });

  process.on('uncaughtException', (error) => {
    console.error('[MCP] Uncaught Exception:', error);
    // For uncaught exceptions, attempt graceful shutdown
    shutdown().then(() => process.exit(1)).catch(() => process.exit(1));
  });

  // Signal handlers for graceful shutdown
  process.on('SIGTERM', async () => {
    console.error('[MCP] Received SIGTERM');
    await shutdown();
    process.exit(0);
  });

  process.on('SIGINT', async () => {
    console.error('[MCP] Received SIGINT');
    await shutdown();
    process.exit(0);
  });

  // Detect stdio errors - connection to Claude Code
  process.stdin.on('error', (error) => {
    console.error('[MCP] stdin error:', error);
    shutdown().then(() => process.exit(1)).catch(() => process.exit(1));
  });

  process.stdout.on('error', (error) => {
    console.error('[MCP] stdout error:', error);
    shutdown().then(() => process.exit(1)).catch(() => process.exit(1));
  });

  // Connect and run
  await server.connect(transport);
  console.error('[MCP] Taey-Hands MCP Server v2 running on stdio');
}

// Graceful shutdown function
async function shutdown() {
  try {
    console.error('[MCP] Shutting down...');
    await sessionManager.destroyAllSessions();
    console.error('[MCP] Shutdown complete');
  } catch (error: any) {
    console.error('[MCP] Error during shutdown:', error.message);
  }
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
