#!/usr/bin/env node
/**
 * Taey-Hands MCP Server v2
 * Function-based tools with session management
 *
 * Architecture: Tool → SessionManager → Interface → Method
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema, } from "@modelcontextprotocol/sdk/types.js";
import { getSessionManager } from "./session-manager.js";
// @ts-ignore - conversation-store is JS, not TS
import { getConversationStore } from "../../src/core/conversation-store.js";
// @ts-ignore - response-detection is JS, not TS
import { ResponseDetectionEngine } from "../../src/core/response-detection.js";
// @ts-ignore - validation-checkpoints is JS, not TS
import { ValidationCheckpointStore } from "../../src/core/validation-checkpoints.js";
// Get singleton session manager
const sessionManager = getSessionManager();
// Get conversation store for Neo4j logging
const conversationStore = getConversationStore();
// Get validation checkpoint store
const validationStore = new ValidationCheckpointStore();
// Initialize schema on startup
conversationStore.initSchema().catch((err) => {
    console.error('[MCP] Failed to initialize ConversationStore schema:', err.message);
});
validationStore.initSchema().catch((err) => {
    console.error('[MCP] Failed to initialize ValidationCheckpointStore schema:', err.message);
});
/**
 * MCP Tools Definitions
 */
const TOOLS = [
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
        name: "taey_send_message",
        description: "Type and send a message in the current conversation. Uses human-like typing and clicks the send button. When waitForResponse is true, automatically waits for the AI response, extracts it, and saves to Neo4j.",
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
                },
                waitForResponse: {
                    type: "boolean",
                    description: "Whether to wait for AI response completion. If true, uses ResponseDetectionEngine to wait for response, extracts it, and saves to Neo4j automatically.",
                    default: false
                }
            },
            required: ["sessionId", "message"]
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
        description: "Download an artifact file from a chat response. Works with Claude (simple download), Gemini (multi-step export), and Perplexity (multi-step export). ChatGPT and Grok do not support artifact downloads.",
        inputSchema: {
            type: "object",
            properties: {
                sessionId: {
                    type: "string",
                    description: "Session ID returned from taey_connect"
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
                }
            },
            required: ["conversationId", "step", "validated", "notes"]
        }
    }
];
/**
 * Create MCP server
 */
const server = new Server({
    name: "taey-hands",
    version: "0.2.0",
}, {
    capabilities: {
        tools: {},
    },
});
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
                const { interface: interfaceType, sessionId: providedSessionId, newSession, conversationId } = args;
                // VALIDATION: Require explicit session decision
                if (!providedSessionId && !newSession) {
                    throw new Error('Must specify either sessionId (to reuse) or newSession=true (to create). No defaults allowed.');
                }
                if (providedSessionId && newSession) {
                    throw new Error('Cannot specify both sessionId and newSession=true. Choose one.');
                }
                // Determine session ID
                let sessionId;
                if (newSession) {
                    // Create new session
                    sessionId = await sessionManager.createSession(interfaceType);
                    // Create conversation in Neo4j
                    try {
                        await conversationStore.createConversation({
                            id: sessionId,
                            title: conversationId ? `Resume: ${conversationId}` : `New ${interfaceType} session`,
                            purpose: 'AI Family collaboration via Taey Hands MCP',
                            initiator: 'mcp_server',
                            platforms: [interfaceType],
                            platform: interfaceType, // Add platform as top-level field for querying
                            sessionId: sessionId, // Add sessionId as top-level field
                            conversationId: conversationId || null, // Add conversationId as top-level field
                            metadata: {
                                conversationId: conversationId || null,
                                createdVia: 'taey_connect'
                            }
                        });
                    }
                    catch (err) {
                        console.error('[MCP] Failed to create conversation in Neo4j:', err.message);
                    }
                }
                else {
                    // Reuse existing session
                    sessionId = providedSessionId;
                }
                // Connect and get screenshot
                const chatInterface = sessionManager.getInterface(sessionId);
                const connectResult = await chatInterface.connect({ sessionId });
                // If conversationId provided, navigate to that conversation
                let conversationUrl;
                if (conversationId) {
                    conversationUrl = await chatInterface.goToConversation(conversationId);
                }
                return {
                    content: [
                        {
                            type: "text",
                            text: JSON.stringify({
                                success: true,
                                sessionId,
                                interface: interfaceType,
                                screenshot: connectResult.screenshot,
                                conversationUrl: conversationUrl || undefined,
                                message: conversationId
                                    ? `Connected to ${interfaceType} at conversation ${conversationId}`
                                    : `Connected to ${interfaceType}`,
                            }, null, 2),
                        },
                    ],
                };
            }
            case "taey_disconnect": {
                const { sessionId } = args;
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
                const { sessionId } = args;
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
            case "taey_send_message": {
                const { sessionId, message, attachments, waitForResponse } = args;
                // VALIDATION CHECKPOINT: Check last validation
                const lastValidation = await validationStore.getLastValidation(sessionId);
                if (!lastValidation) {
                    throw new Error(`Validation checkpoint failed: No validation checkpoints found. ` +
                        `You must validate the 'plan' step before sending a message.`);
                }
                // Check that the last checkpoint is validated=true (not pending)
                if (!lastValidation.validated) {
                    throw new Error(`Validation checkpoint failed: The most recent step '${lastValidation.step}' is pending validation (validated=false). ` +
                        `You must call taey_validate_step with validated=true after reviewing the screenshot. ` +
                        `Notes from pending checkpoint: ${lastValidation.notes}`);
                }
                // Check that last validated step is an acceptable prerequisite
                const validSteps = ['plan', 'attach_files'];
                if (!validSteps.includes(lastValidation.step)) {
                    throw new Error(`Validation checkpoint failed: Last validated step was '${lastValidation.step}'. ` +
                        `Must validate one of: ${validSteps.join(', ')} before sending.`);
                }
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
                }
                catch (err) {
                    console.error('[MCP] Failed to log message to Neo4j:', err.message);
                }
                // Prepare input (focus)
                await chatInterface.prepareInput();
                // Type message with human-like typing
                await chatInterface.typeMessage(message);
                // Click send button
                await chatInterface.clickSend();
                // If waitForResponse is true, use ResponseDetectionEngine
                if (waitForResponse) {
                    console.error(`[MCP] Waiting for response from ${interfaceName}...`);
                    try {
                        // Create detection engine for this platform
                        const detector = new ResponseDetectionEngine(chatInterface.page, session?.interfaceType || interfaceName, { debug: true });
                        // Wait for response completion
                        const detectionResult = await detector.detectCompletion();
                        const responseText = detectionResult.content;
                        const timestamp = new Date().toISOString();
                        console.error(`[MCP] Response detected (${detectionResult.method}, ${detectionResult.confidence * 100}% confidence) in ${detectionResult.detectionTime}ms`);
                        // Log response to Neo4j
                        try {
                            await conversationStore.addMessage(sessionId, {
                                role: 'assistant',
                                content: responseText,
                                platform: interfaceName,
                                timestamp,
                                metadata: {
                                    source: 'mcp_taey_send_message_auto_extract',
                                    detectionMethod: detectionResult.method,
                                    detectionConfidence: detectionResult.confidence,
                                    detectionTime: detectionResult.detectionTime,
                                    contentLength: responseText.length
                                }
                            });
                        }
                        catch (err) {
                            console.error('[MCP] Failed to log response to Neo4j:', err.message);
                        }
                        return {
                            content: [
                                {
                                    type: "text",
                                    text: JSON.stringify({
                                        success: true,
                                        sessionId,
                                        message: "Message sent and response received",
                                        sentText: message,
                                        waitForResponse: true,
                                        responseText,
                                        responseLength: responseText.length,
                                        detectionMethod: detectionResult.method,
                                        detectionConfidence: detectionResult.confidence,
                                        detectionTime: detectionResult.detectionTime,
                                        timestamp
                                    }, null, 2),
                                },
                            ],
                        };
                    }
                    catch (err) {
                        console.error('[MCP] Response detection failed:', err.message);
                        return {
                            content: [
                                {
                                    type: "text",
                                    text: JSON.stringify({
                                        success: false,
                                        sessionId,
                                        message: "Message sent but response detection failed",
                                        sentText: message,
                                        waitForResponse: true,
                                        error: err.message,
                                    }, null, 2),
                                },
                            ],
                            isError: true,
                        };
                    }
                }
                return {
                    content: [
                        {
                            type: "text",
                            text: JSON.stringify({
                                success: true,
                                sessionId,
                                message: "Message sent",
                                sentText: message,
                                waitForResponse: false,
                            }, null, 2),
                        },
                    ],
                };
            }
            case "taey_extract_response": {
                const { sessionId } = args;
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
                }
                catch (err) {
                    console.error('[MCP] Failed to log response to Neo4j:', err.message);
                }
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
                const { sessionId, modelName, isLegacy = false } = args;
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
                }
                else {
                    // Claude, Gemini, Grok: standard call
                    result = await chatInterface.selectModel(modelName, { sessionId });
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
                const { sessionId, filePaths } = args;
                // VALIDATION CHECKPOINT: Require 'plan' step validated
                const canProceed = await validationStore.canProceedToStep(sessionId, 'attach_files');
                if (!canProceed.canProceed) {
                    throw new Error(`Validation checkpoint failed: ${canProceed.reason}\n\n` +
                        `You must call taey_validate_step to validate the 'plan' step before attaching files.\n` +
                        `Review the screenshot from planning and confirm the session state is correct.`);
                }
                // Get interface from session
                const chatInterface = sessionManager.getInterface(sessionId);
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
                    screenshot: lastScreenshot
                });
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
                const { sourceSessionId, targetSessionId, prefix } = args;
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
                const { sessionId, enabled = true, modeName } = args;
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
                }
                else if (session.interfaceType === "chatgpt") {
                    // ChatGPT: use setMode() with Deep research
                    const mode = modeName || "Deep research";
                    result = await chatInterface.setMode(mode, { sessionId });
                    screenshot = result.screenshot || '';
                    result.mode = `${mode} enabled`;
                }
                else if (session.interfaceType === "gemini") {
                    // Gemini: use setMode() with Deep Research or Deep Think
                    const mode = modeName || "Deep Research";
                    result = await chatInterface.setMode(mode, { sessionId });
                    screenshot = result.screenshot || '';
                    result.mode = `${mode} enabled`;
                }
                else if (session.interfaceType === "perplexity") {
                    // Perplexity: use enableResearchMode() - always enables
                    result = await chatInterface.enableResearchMode({ sessionId });
                    screenshot = result.screenshot || '';
                    result.mode = "Pro Search enabled";
                }
                else {
                    // Other interfaces: try generic enableResearchMode if available
                    if (typeof chatInterface.enableResearchMode === 'function') {
                        result = await chatInterface.enableResearchMode({ sessionId });
                        screenshot = result.screenshot || '';
                        result.mode = "Research mode enabled";
                    }
                    else {
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
                const { sessionId, downloadPath = "/tmp", format = "markdown", timeout = 10000 } = args;
                // Get interface from session
                const session = sessionManager.getSession(sessionId);
                const chatInterface = sessionManager.getInterface(sessionId);
                // Check if interface supports downloadArtifact
                if (typeof chatInterface.downloadArtifact !== 'function') {
                    throw new Error(`Artifact download not supported for ${session?.interfaceType || 'this interface'}`);
                }
                // Call downloadArtifact method with interface-specific options
                const result = await chatInterface.downloadArtifact({
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
                const { conversationId, step, validated, notes, screenshot } = args;
                // Create validation checkpoint
                const checkpoint = await validationStore.createCheckpoint({
                    conversationId,
                    step,
                    validated,
                    notes,
                    screenshot: screenshot || null
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
    }
    catch (error) {
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
    await server.connect(transport);
    console.error("Taey-Hands MCP Server v2 running on stdio");
}
main().catch((error) => {
    console.error("Fatal error:", error);
    process.exit(1);
});
//# sourceMappingURL=server-v2.js.map