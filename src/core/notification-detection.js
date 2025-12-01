/**
 * Notification-Based Response Detection
 *
 * Replaces Fibonacci polling with instant event-driven detection.
 * Based on Perplexity research: Web Notifications API provides < 100ms detection
 * when platforms send "thinking complete" notifications.
 *
 * Strategy Chain:
 * 1. Web Notifications API (< 100ms) ⭐ Primary
 * 2. MutationObserver (< 500ms) - Fallback
 * 3. Network Request Detection (< 200ms) - Secondary
 * 4. Fibonacci Polling (1-55s) - Last resort
 */

export class NotificationDetectionEngine {
  constructor(page, platform, options = {}) {
    this.page = page;
    this.platform = platform;
    this.options = options;
    this.debug = options.debug || false;
  }

  /**
   * Initialize notification interception
   * Injects code to monkey-patch Notification.showNotification()
   */
  async initializeNotificationListener() {
    await this.page.evaluate(() => {
      // Create custom event for notification detection
      window.__notificationReceived = false;
      window.__notificationData = null;

      // Monkey-patch Notification constructor
      const OriginalNotification = window.Notification;

      window.Notification = function(...args) {
        const title = args[0];
        const options = args[1] || {};

        // Detect completion notifications
        const completionKeywords = [
          'finished thinking',
          'research complete',
          'deep research',
          'response ready',
          'completed',
          'done'
        ];

        const isCompletion = completionKeywords.some(keyword =>
          title.toLowerCase().includes(keyword) ||
          (options.body && options.body.toLowerCase().includes(keyword))
        );

        if (isCompletion) {
          window.__notificationReceived = true;
          window.__notificationData = { title, ...options };

          // Emit custom event that Playwright can detect
          window.dispatchEvent(new CustomEvent('ai-response-complete', {
            detail: { title, options }
          }));
        }

        // Call original constructor
        return new OriginalNotification(...args);
      };

      // Copy static properties
      Object.setPrototypeOf(window.Notification, OriginalNotification);
      Object.setPrototypeOf(window.Notification.prototype, OriginalNotification.prototype);
    });

    this.log('Notification listener initialized');
  }

  /**
   * Wait for notification-based completion detection
   * Returns immediately when notification fires
   */
  async waitForNotification(timeout = 30000) {
    return new Promise(async (resolve, reject) => {
      const startTime = Date.now();

      // Set up event listener for custom event
      await this.page.exposeFunction('__notifyCompletion', (data) => {
        this.log('Notification detected:', data);
        resolve({ method: 'notification', detected: true, data });
      });

      await this.page.evaluate(() => {
        window.addEventListener('ai-response-complete', (event) => {
          window.__notifyCompletion(event.detail);
        });
      });

      // Timeout fallback
      const timeoutId = setTimeout(() => {
        reject(new Error('Notification timeout - falling back to next strategy'));
      }, timeout);

      // Poll for notification flag (lightweight backup)
      const pollInterval = setInterval(async () => {
        const received = await this.page.evaluate(() => window.__notificationReceived);

        if (received) {
          clearInterval(pollInterval);
          clearTimeout(timeoutId);

          const data = await this.page.evaluate(() => window.__notificationData);
          resolve({ method: 'notification', detected: true, data });
        }
      }, 100); // Check every 100ms
    });
  }

  /**
   * MutationObserver fallback
   * Watches DOM for completion patterns
   */
  async waitForMutationDetection(containerSelector, timeout = 30000) {
    return new Promise(async (resolve, reject) => {
      const startTime = Date.now();

      await this.page.evaluate((selector, maxTime) => {
        return new Promise((resolveInner, rejectInner) => {
          const container = document.querySelector(selector);
          if (!container) {
            return rejectInner(new Error('Container not found'));
          }

          let lastContent = '';
          let stableCount = 0;
          const stabilityRequired = 2; // 2 checks with no changes

          const observer = new MutationObserver(() => {
            const currentContent = container.textContent;

            if (currentContent === lastContent) {
              stableCount++;
              if (stableCount >= stabilityRequired) {
                observer.disconnect();
                resolveInner({ content: currentContent });
              }
            } else {
              stableCount = 0;
              lastContent = currentContent;
            }
          });

          observer.observe(container, {
            childList: true,
            subtree: true,
            characterData: true
          });

          // Timeout
          setTimeout(() => {
            observer.disconnect();
            rejectInner(new Error('MutationObserver timeout'));
          }, maxTime);
        });
      }, containerSelector, timeout)
      .then(result => resolve({ method: 'mutation', ...result }))
      .catch(reject);
    });
  }

  /**
   * Combined detection with fallback chain
   */
  async detect(containerSelector) {
    // Initialize notification listener
    await this.initializeNotificationListener();

    // Try strategies in order
    try {
      // Strategy 1: Notification (fastest)
      this.log('Attempting notification detection...');
      return await this.waitForNotification(5000);
    } catch (e) {
      this.log('Notification detection failed, trying MutationObserver...');

      try {
        // Strategy 2: MutationObserver
        return await this.waitForMutationDetection(containerSelector, 10000);
      } catch (e2) {
        this.log('MutationObserver failed, falling back to polling');
        throw new Error('All instant detection methods failed - use Fibonacci fallback');
      }
    }
  }

  log(message, ...args) {
    if (this.debug) {
      console.log(`[NotificationDetection:${this.platform}]`, message, ...args);
    }
  }
}
