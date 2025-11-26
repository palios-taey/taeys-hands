/**
 * Job Manager for MCP Server
 * Handles spawning detached worker processes and tracking job status
 */
import { spawn } from "child_process";
import { randomUUID } from "crypto";
import { readFile, writeFile, unlink } from "fs/promises";
import { existsSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { dirname } from "path";
// ES module equivalent of __dirname
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
export class JobManager {
    jobs;
    statusDir;
    resultDir;
    constructor() {
        this.jobs = new Map();
        this.statusDir = "/tmp";
        this.resultDir = "/tmp";
    }
    /**
     * Start a new research job
     * Spawns a detached worker process and returns job ID immediately
     */
    async startJob(config) {
        const jobId = randomUUID();
        const sessionId = Date.now();
        // Initialize job status
        const status = {
            jobId,
            status: "pending",
            startedAt: new Date().toISOString(),
        };
        this.jobs.set(jobId, status);
        // Write initial status file
        await this.writeStatusFile(jobId, status);
        // Path to worker script (relative to mcp_server directory)
        const workerPath = path.join(__dirname, "worker.js");
        // Spawn detached worker process
        const worker = spawn("node", [
            workerPath,
            jobId,
            sessionId.toString(),
            config.model,
            config.message,
            config.research.toString(),
            ...config.files,
        ], {
            detached: true,
            stdio: "ignore", // Don't pipe stdio to avoid blocking
        });
        // Unref so parent can exit independently
        worker.unref();
        // Update status to running
        status.status = "running";
        status.progress = {
            phase: "initializing",
            message: "Starting Claude research workflow",
        };
        this.jobs.set(jobId, status);
        await this.writeStatusFile(jobId, status);
        return jobId;
    }
    /**
     * Get current job status
     * Reads from status file if available
     */
    async getJobStatus(jobId) {
        // First check in-memory cache
        let status = this.jobs.get(jobId);
        // If not in memory, try reading from file
        if (!status) {
            status = await this.readStatusFile(jobId);
            if (status) {
                this.jobs.set(jobId, status);
            }
        }
        else {
            // Refresh from file to get latest updates from worker
            const fileStatus = await this.readStatusFile(jobId);
            if (fileStatus) {
                status = fileStatus;
                this.jobs.set(jobId, status);
            }
        }
        return status || null;
    }
    /**
     * Get job result (only for completed jobs)
     */
    async getJobResult(jobId) {
        const status = await this.getJobStatus(jobId);
        if (!status) {
            return null;
        }
        if (status.status !== "completed" && status.status !== "failed") {
            return null;
        }
        // Read result file
        const result = await this.readResultFile(jobId);
        return result;
    }
    /**
     * Clean up completed job files
     */
    async cleanupJob(jobId) {
        const statusPath = this.getStatusPath(jobId);
        const resultPath = this.getResultPath(jobId);
        try {
            if (existsSync(statusPath)) {
                await unlink(statusPath);
            }
            if (existsSync(resultPath)) {
                await unlink(resultPath);
            }
            this.jobs.delete(jobId);
        }
        catch (error) {
            console.error(`Failed to cleanup job ${jobId}:`, error);
        }
    }
    /**
     * Helper: Get status file path
     */
    getStatusPath(jobId) {
        return path.join(this.statusDir, `research-${jobId}-status.json`);
    }
    /**
     * Helper: Get result file path
     */
    getResultPath(jobId) {
        return path.join(this.resultDir, `research-${jobId}-result.json`);
    }
    /**
     * Helper: Write status to file
     */
    async writeStatusFile(jobId, status) {
        const statusPath = this.getStatusPath(jobId);
        await writeFile(statusPath, JSON.stringify(status, null, 2), "utf-8");
    }
    /**
     * Helper: Read status from file
     */
    async readStatusFile(jobId) {
        const statusPath = this.getStatusPath(jobId);
        if (!existsSync(statusPath)) {
            return null;
        }
        try {
            const data = await readFile(statusPath, "utf-8");
            return JSON.parse(data);
        }
        catch (error) {
            console.error(`Failed to read status file for job ${jobId}:`, error);
            return null;
        }
    }
    /**
     * Helper: Read result from file
     */
    async readResultFile(jobId) {
        const resultPath = this.getResultPath(jobId);
        if (!existsSync(resultPath)) {
            return null;
        }
        try {
            const data = await readFile(resultPath, "utf-8");
            return JSON.parse(data);
        }
        catch (error) {
            console.error(`Failed to read result file for job ${jobId}:`, error);
            return null;
        }
    }
}
//# sourceMappingURL=job-manager.js.map