// ─────────────────────────────────────────────
// ERROR HANDLING & LOGGING
// ─────────────────────────────────────────────

import Logger from './logger';

/**
 * Structured error logging system
 */

export class AppError extends Error {
  code: string;
  context: Record<string, unknown>;
  timestamp: string;

  constructor(message: string, code = 'APP_ERROR', context: Record<string, unknown> = {}) {
    super(message);
    this.name = 'AppError';
    this.code = code;
    this.context = context;
    this.timestamp = new Date().toISOString();
  }

  toJSON() {
    return {
      message: this.message,
      code: this.code,
      context: this.context,
      timestamp: this.timestamp,
      stack: this.stack,
    };
  }
}

// Re-export the canonical Logger for backward compatibility
export { Logger };

/**
 * Initialize error reporting (idempotent — safe to call multiple times).
 */
let _errorHandlingInitialized = false;
export function initializeErrorHandling() {
  if (_errorHandlingInitialized) return;
  _errorHandlingInitialized = true;

  globalThis.addEventListener('error', (event: ErrorEvent) => {
    Logger.error('Unhandled error', undefined, {
      message: event.message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      stack: event.error?.stack,
    });
  });

  globalThis.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    Logger.error('Unhandled promise rejection', undefined, {
      reason: event.reason?.message || event.reason,
      stack: event.reason?.stack,
    });
  });
}
