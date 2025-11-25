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
// Get singleton session manager
const sessionManager = getSessionManager();
/**
 * MCP Tools Definitions
 */
const TOOLS = [
    {
        name: "taey_connect",
        description: "Connect to a chat interface (Claude, ChatGPT, Gemini, Grok, or Perplexity). Creates a new session and initializes browser automation. Optionally navigates to an existing conversation. Returns a session ID for use with other tools.",
        inputSchema: {
            type: "object",
            properties: {
                interface: {
                    type: "string",
                    enum: ["claude", "chatgpt", "gemini", "grok", "perplexity"],
                    description: "Which chat interface to connect to"
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
        description: "Type and send a message in the current conversation. Uses human-like typing and clicks the send button.",
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
                waitForResponse: {
                    type: "boolean",
                    description: "Whether to wait for a response (not implemented yet)",
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
        description: "Attach one or more files to the conversation. Uses human-like Finder navigation (Cmd+Shift+G) to locate and attach files.",
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
                const { interface: interfaceType, conversationId } = args;
                // Create new session
                const sessionId = await sessionManager.createSession(interfaceType);
                // If conversationId provided, navigate to that conversation
                let conversationUrl;
                if (conversationId) {
                    const chatInterface = sessionManager.getInterface(sessionId);
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
                const { sessionId, message, waitForResponse } = args;
                // Get interface from session
                const chatInterface = sessionManager.getInterface(sessionId);
                // Prepare input (focus)
                await chatInterface.prepareInput();
                // Type message with human-like typing
                await chatInterface.typeMessage(message);
                // Click send button
                await chatInterface.clickSend();
                return {
                    content: [
                        {
                            type: "text",
                            text: JSON.stringify({
                                success: true,
                                sessionId,
                                message: "Message sent",
                                sentText: message,
                                waitForResponse: waitForResponse || false,
                            }, null, 2),
                        },
                    ],
                };
            }
            case "taey_extract_response": {
                const { sessionId } = args;
                // Get interface from session
                const chatInterface = sessionManager.getInterface(sessionId);
                // Extract latest response
                const responseText = await chatInterface.getLatestResponse();
                return {
                    content: [
                        {
                            type: "text",
                            text: JSON.stringify({
                                success: true,
                                responseText,
                                timestamp: new Date().toISOString(),
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
                                success: true,
                                sessionId,
                                interfaceType: session.interfaceType,
                                modelName: result.modelName,
                                screenshot: result.screenshot,
                                message: `Selected model: ${result.modelName}`,
                            }, null, 2),
                        },
                    ],
                };
            }
            case "taey_attach_files": {
                const { sessionId, filePaths } = args;
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
                return {
                    content: [
                        {
                            type: "text",
                            text: JSON.stringify({
                                success: true,
                                filesAttached: attachmentResults.length,
                                attachments: attachmentResults,
                                screenshot: lastScreenshot,
                                message: `Attached ${attachmentResults.length} file(s)`,
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
                // Get target interface and send message
                const targetInterface = sessionManager.getInterface(targetSessionId);
                await targetInterface.prepareInput();
                await targetInterface.typeMessage(messageToSend);
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