#!/usr/bin/env node
/**
 * MCP Server for Taey-Hands
 * Provides tools for Claude research workflow orchestration
 * Following official MCP SDK patterns
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema, } from "@modelcontextprotocol/sdk/types.js";
import { JobManager } from "./job-manager.js";
// Initialize job manager
const jobManager = new JobManager();
// Define the three MCP tools
const TOOLS = [
    {
        name: "start_claude_research",
        description: "Start a long-running Claude research request with optional file attachments. Returns immediately with a job ID.",
        inputSchema: {
            type: "object",
            properties: {
                model: {
                    type: "string",
                    description: "Claude model to use (e.g., 'Opus 4.5', 'Sonnet 4')",
                    default: "Opus 4.5"
                },
                message: {
                    type: "string",
                    description: "Message/prompt to send to Claude"
                },
                files: {
                    type: "array",
                    items: { type: "string" },
                    description: "Array of absolute file paths to attach",
                    default: []
                },
                research: {
                    type: "boolean",
                    description: "Enable Research mode",
                    default: true
                }
            },
            required: ["message"]
        }
    },
    {
        name: "get_research_status",
        description: "Check the status of a running research job. Returns current progress and state.",
        inputSchema: {
            type: "object",
            properties: {
                jobId: {
                    type: "string",
                    description: "Job ID returned from start_claude_research"
                }
            },
            required: ["jobId"]
        }
    },
    {
        name: "get_research_result",
        description: "Retrieve the final result of a completed research job, including response text, artifacts, and screenshots.",
        inputSchema: {
            type: "object",
            properties: {
                jobId: {
                    type: "string",
                    description: "Job ID returned from start_claude_research"
                }
            },
            required: ["jobId"]
        }
    }
];
// Create MCP server instance
const server = new Server({
    name: "taey-hands",
    version: "0.1.0",
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
 * Handler: Execute tool requests
 */
server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;
    try {
        switch (name) {
            case "start_claude_research": {
                const { model, message, files, research } = args;
                // Validate message
                if (!message || message.trim().length === 0) {
                    return {
                        content: [
                            {
                                type: "text",
                                text: JSON.stringify({
                                    error: "Message cannot be empty"
                                }, null, 2)
                            }
                        ],
                        isError: true
                    };
                }
                // Start the job (spawns detached process)
                const jobId = await jobManager.startJob({
                    model: model || "Opus 4.5",
                    message,
                    files: files || [],
                    research: research !== false
                });
                return {
                    content: [
                        {
                            type: "text",
                            text: JSON.stringify({
                                jobId,
                                status: "started",
                                message: "Research job started successfully"
                            }, null, 2)
                        }
                    ]
                };
            }
            case "get_research_status": {
                const { jobId } = args;
                if (!jobId) {
                    return {
                        content: [
                            {
                                type: "text",
                                text: JSON.stringify({
                                    error: "jobId is required"
                                }, null, 2)
                            }
                        ],
                        isError: true
                    };
                }
                const status = await jobManager.getJobStatus(jobId);
                if (!status) {
                    return {
                        content: [
                            {
                                type: "text",
                                text: JSON.stringify({
                                    error: `Job ${jobId} not found`
                                }, null, 2)
                            }
                        ],
                        isError: true
                    };
                }
                return {
                    content: [
                        {
                            type: "text",
                            text: JSON.stringify(status, null, 2)
                        }
                    ]
                };
            }
            case "get_research_result": {
                const { jobId } = args;
                if (!jobId) {
                    return {
                        content: [
                            {
                                type: "text",
                                text: JSON.stringify({
                                    error: "jobId is required"
                                }, null, 2)
                            }
                        ],
                        isError: true
                    };
                }
                const result = await jobManager.getJobResult(jobId);
                if (!result) {
                    return {
                        content: [
                            {
                                type: "text",
                                text: JSON.stringify({
                                    error: `Job ${jobId} not found or not completed`
                                }, null, 2)
                            }
                        ],
                        isError: true
                    };
                }
                return {
                    content: [
                        {
                            type: "text",
                            text: JSON.stringify(result, null, 2)
                        }
                    ]
                };
            }
            default:
                return {
                    content: [
                        {
                            type: "text",
                            text: JSON.stringify({
                                error: `Unknown tool: ${name}`
                            }, null, 2)
                        }
                    ],
                    isError: true
                };
        }
    }
    catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        return {
            content: [
                {
                    type: "text",
                    text: JSON.stringify({
                        error: errorMessage
                    }, null, 2)
                }
            ],
            isError: true
        };
    }
});
/**
 * Start the server
 */
async function main() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error("Taey-Hands MCP server running on stdio");
}
main().catch((error) => {
    console.error("Fatal error in main():", error);
    process.exit(1);
});
//# sourceMappingURL=server.js.map