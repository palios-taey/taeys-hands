/**
 * Job Manager for MCP Server
 * Handles spawning detached worker processes and tracking job status
 */
export interface JobConfig {
    model: string;
    message: string;
    files: string[];
    research: boolean;
}
export interface JobStatus {
    jobId: string;
    status: "pending" | "running" | "completed" | "failed";
    startedAt: string;
    completedAt?: string;
    progress?: {
        phase?: string;
        message?: string;
    };
    error?: string;
}
export interface JobResult {
    jobId: string;
    sessionId: number;
    responseText: string | null;
    artifact: {
        filePath: string;
        fileName: string;
        content: string;
    } | null;
    screenshots: Record<string, string>;
    error?: string;
}
export declare class JobManager {
    private jobs;
    private statusDir;
    private resultDir;
    constructor();
    /**
     * Start a new research job
     * Spawns a detached worker process and returns job ID immediately
     */
    startJob(config: JobConfig): Promise<string>;
    /**
     * Get current job status
     * Reads from status file if available
     */
    getJobStatus(jobId: string): Promise<JobStatus | null>;
    /**
     * Get job result (only for completed jobs)
     */
    getJobResult(jobId: string): Promise<JobResult | null>;
    /**
     * Clean up completed job files
     */
    cleanupJob(jobId: string): Promise<void>;
    /**
     * Helper: Get status file path
     */
    private getStatusPath;
    /**
     * Helper: Get result file path
     */
    private getResultPath;
    /**
     * Helper: Write status to file
     */
    private writeStatusFile;
    /**
     * Helper: Read status from file
     */
    private readStatusFile;
    /**
     * Helper: Read result from file
     */
    private readResultFile;
}
//# sourceMappingURL=job-manager.d.ts.map