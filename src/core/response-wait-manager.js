/**
 * Background Response Wait Manager
 *
 * Manages multiple concurrent response waiting tasks.
 * Adapted from builder-taey BackgroundProcessManager pattern.
 *
 * Key Features:
 * - Silent by default (no automatic reminders)
 * - Incremental status checks (only new state since last check)
 * - Clean lifecycle management
 * - Multiple concurrent waits across different sessions
 */

import { ResponseDetectionEngine } from './response-detection.js';

/**
 * State for a single background wait task
 */
class WaitState {
  constructor(waitId, sessionId, maxWaitSeconds) {
    this.waitId = waitId;              // Unique wait ID
    this.sessionId = sessionId;        // Session being waited on
    this.status = 'waiting';           // "waiting" | "completed" | "timeout" | "error" | "cancelled"
    this.responseText = null;          // Detected response text
    this.detectionResult = null;       // Full detection result object
    this.error = null;                 // Error message if failed
    this.startedAt = new Date();       // When wait started
    this.completedAt = null;           // When wait finished
    this.maxWaitSeconds = maxWaitSeconds;
    this.read = false;                 // Has status been checked?
    this.loggedToNeo4j = false;        // Has response been logged?
    this.task = null;                  // Running async task reference
  }

  get runtime() {
    const end = this.completedAt || new Date();
    return Math.round((end - this.startedAt) / 1000);
  }

  toJSON() {
    return {
      waitId: this.waitId,
      sessionId: this.sessionId,
      status: this.status,
      responseText: this.responseText,
      responseLength: this.responseText ? this.responseText.length : 0,
      detectionMethod: this.detectionResult?.method || null,
      detectionConfidence: this.detectionResult?.confidence || null,
      error: this.error,
      runtimeSeconds: this.runtime,
      startedAt: this.startedAt.toISOString(),
      completedAt: this.completedAt?.toISOString() || null,
      isRead: this.read,
      loggedToNeo4j: this.loggedToNeo4j
    };
  }
}

export class ResponseWaitManager {
  constructor(sessionManager) {
    this.sessionManager = sessionManager;
    this.waits = new Map();  // waitId → WaitState
    this.nextId = 1;
  }

  /**
   * Generate unique wait ID
   */
  _generateId() {
    const waitId = `wait_${String(this.nextId).padStart(6, '0')}`;
    this.nextId++;
    return waitId;
  }

  /**
   * Start background response detection
   * Returns wait_id immediately, detection runs in background
   */
  async startWaiting(sessionId, maxWaitSeconds = 600) {
    // Validate session exists
    const session = this.sessionManager.getSession(sessionId);
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }

    // Create wait state
    const waitId = this._generateId();
    const state = new WaitState(waitId, sessionId, maxWaitSeconds);
    this.waits.set(waitId, state);

    // Start background detection task (fire and forget)
    state.task = this._runDetection(state).catch(err => {
      console.error(`[ResponseWaitManager] Detection task failed: ${err.message}`);
      // Error is already stored in state by _runDetection
    });

    console.error(`[ResponseWaitManager] Started waiting on ${sessionId} (wait_id: ${waitId}, max: ${maxWaitSeconds}s)`);

    return {
      waitId,
      sessionId,
      status: 'waiting',
      startedAt: state.startedAt.toISOString(),
      maxWaitSeconds,
      message: `Background wait started. Use taey_check_wait_status("${waitId}") to check progress.`
    };
  }

  /**
   * Background task: Run response detection
   * PRIVATE - called by startWaiting()
   */
  async _runDetection(state) {
    try {
      // Get chat interface
      const chatInterface = this.sessionManager.getInterface(state.sessionId);
      const session = this.sessionManager.getSession(state.sessionId);

      // Create detection engine
      const detector = new ResponseDetectionEngine(
        chatInterface.page,
        session.interfaceType,
        { debug: true }
      );

      // Wait for response (this is the long blocking call that runs in background)
      const detectionResult = await detector.detectCompletion();

      // Update state - COMPLETED
      state.status = 'completed';
      state.responseText = detectionResult.content;
      state.detectionResult = detectionResult;
      state.completedAt = new Date();

      console.error(`[ResponseWaitManager] ✓ Wait ${state.waitId} completed (${state.runtime}s, ${detectionResult.method})`);

      // Mark response complete in session manager
      this.sessionManager.markResponseComplete(state.sessionId);

    } catch (err) {
      // Detection failed - timeout or error
      if (err.message.includes('timeout') || err.message.includes('Detection timeout')) {
        state.status = 'timeout';
        state.error = `Detection timeout after ${state.maxWaitSeconds}s`;
      } else {
        state.status = 'error';
        state.error = err.message;
      }
      state.completedAt = new Date();

      console.error(`[ResponseWaitManager] ✗ Wait ${state.waitId} ${state.status}: ${state.error}`);

      // Clear response pending even on error
      this.sessionManager.markResponseComplete(state.sessionId);
    }
  }

  /**
   * Check status of background wait
   * Returns current state (incremental)
   */
  async checkStatus(waitId) {
    const state = this.waits.get(waitId);
    if (!state) {
      throw new Error(`Wait not found: ${waitId}`);
    }

    // Mark as read
    const wasUnread = !state.read;
    state.read = true;

    // Return full state
    const result = state.toJSON();

    // Add notification if this is first read and wait is complete
    if (wasUnread && (state.status === 'completed' || state.status === 'timeout' || state.status === 'error')) {
      result.notification = `Wait ${waitId} ${state.status} after ${state.runtime}s`;
    }

    return result;
  }

  /**
   * Get wait state (internal use)
   */
  getWaitState(waitId) {
    return this.waits.get(waitId);
  }

  /**
   * Cancel background wait
   * Stops detection and cleans up
   */
  async cancelWait(waitId) {
    const state = this.waits.get(waitId);
    if (!state) {
      throw new Error(`Wait not found: ${waitId}`);
    }

    if (state.status !== 'waiting') {
      return {
        waitId,
        status: state.status,
        message: `Wait already ${state.status}, cannot cancel`
      };
    }

    // Update state
    state.status = 'cancelled';
    state.completedAt = new Date();
    state.error = 'Cancelled by user';

    // Clear response pending
    this.sessionManager.markResponseComplete(state.sessionId);

    console.error(`[ResponseWaitManager] Cancelled wait ${waitId}`);

    return {
      waitId,
      status: 'cancelled',
      runtimeSeconds: state.runtime,
      message: 'Wait cancelled successfully'
    };
  }

  /**
   * List all background waits
   * Optionally filter by status or sessionId
   */
  listWaits(options = {}) {
    const { status, sessionId } = options;

    let filteredWaits = Array.from(this.waits.values());

    if (status) {
      filteredWaits = filteredWaits.filter(w => w.status === status);
    }

    if (sessionId) {
      filteredWaits = filteredWaits.filter(w => w.sessionId === sessionId);
    }

    // Count by status
    const allWaits = Array.from(this.waits.values());
    const waiting = allWaits.filter(w => w.status === 'waiting').length;
    const completed = allWaits.filter(w => w.status === 'completed').length;
    const timeout = allWaits.filter(w => w.status === 'timeout').length;
    const error = allWaits.filter(w => w.status === 'error').length;
    const cancelled = allWaits.filter(w => w.status === 'cancelled').length;

    return {
      waits: filteredWaits.map(w => w.toJSON()),
      total: filteredWaits.length,
      counts: {
        waiting,
        completed,
        timeout,
        error,
        cancelled
      }
    };
  }

  /**
   * Clean up completed waits
   * Removes completed/timeout/error waits that have been read
   */
  cleanup() {
    let cleaned = 0;

    for (const [waitId, state] of this.waits.entries()) {
      if (state.read && state.status !== 'waiting') {
        this.waits.delete(waitId);
        cleaned++;
      }
    }

    console.error(`[ResponseWaitManager] Cleaned up ${cleaned} completed wait(s)`);
    return { cleaned };
  }

  /**
   * Get wait by session ID (latest)
   */
  getWaitBySession(sessionId) {
    const sessionWaits = Array.from(this.waits.values())
      .filter(w => w.sessionId === sessionId)
      .sort((a, b) => b.startedAt - a.startedAt); // Latest first

    return sessionWaits.length > 0 ? sessionWaits[0] : null;
  }
}
