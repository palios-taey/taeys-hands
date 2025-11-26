#!/usr/bin/env node

/**
 * Worker process for Claude research jobs
 * Spawned as detached process by JobManager
 * Updates status and result files during execution
 */

import { claudeResearchRequest } from "../src/workflows/claude-research-request.js";
import { writeFile } from "fs/promises";
import path from "path";

// Parse command line arguments
const [jobId, sessionId, model, message, research, ...files] = process.argv.slice(2);

if (!jobId || !sessionId || !message) {
  console.error("Usage: worker.js <jobId> <sessionId> <model> <message> <research> [files...]");
  process.exit(1);
}

// Status and result file paths
const statusPath = `/tmp/research-${jobId}-status.json`;
const resultPath = `/tmp/research-${jobId}-result.json`;

/**
 * Update job status file
 */
async function updateStatus(status, phase = null, message = null, error = null) {
  const statusData = {
    jobId,
    status,
    startedAt: new Date().toISOString(),
    ...(phase && { progress: { phase, message } }),
    ...(error && { error }),
  };

  if (status === "completed" || status === "failed") {
    statusData.completedAt = new Date().toISOString();
  }

  try {
    await writeFile(statusPath, JSON.stringify(statusData, null, 2), "utf-8");
  } catch (err) {
    console.error("Failed to write status:", err);
  }
}

/**
 * Write final result file
 */
async function writeResult(result, error = null) {
  const resultData = {
    jobId,
    sessionId: parseInt(sessionId),
    responseText: result?.responseText || null,
    artifact: result?.artifact || null,
    screenshots: result?.screenshots || {},
    ...(error && { error }),
  };

  try {
    await writeFile(resultPath, JSON.stringify(resultData, null, 2), "utf-8");
  } catch (err) {
    console.error("Failed to write result:", err);
  }
}

/**
 * Main worker execution
 */
async function runJob() {
  try {
    // Update status: running
    await updateStatus("running", "connecting", "Connecting to Claude interface");

    // Build config for workflow
    const config = {
      model: model || "Opus 4.5",
      message,
      files: files || [],
      research: research === "true",
      downloadPath: "/tmp",
      sessionId: parseInt(sessionId),
    };

    console.log(`[Worker ${jobId}] Starting research job`);
    console.log(`  Model: ${config.model}`);
    console.log(`  Message: ${config.message.substring(0, 50)}...`);
    console.log(`  Files: ${config.files.length}`);
    console.log(`  Research mode: ${config.research}`);

    // Execute the workflow
    const result = await claudeResearchRequest(config);

    console.log(`[Worker ${jobId}] Job completed successfully`);

    // Update status: completed
    await updateStatus("completed", "finished", "Research completed successfully");

    // Write result
    await writeResult(result);

    process.exit(0);
  } catch (error) {
    console.error(`[Worker ${jobId}] Job failed:`, error);

    const errorMessage = error instanceof Error ? error.message : String(error);

    // Update status: failed
    await updateStatus("failed", "error", "Job failed", errorMessage);

    // Write result with error
    await writeResult(null, errorMessage);

    process.exit(1);
  }
}

// Run the job
runJob().catch((err) => {
  console.error("Fatal error in worker:", err);
  process.exit(1);
});
