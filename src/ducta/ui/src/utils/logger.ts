/**
 * Centralized logging system for Ducta
 *
 * Features:
 * - Multiple log levels (debug, info, warn, error)
 * - Structured logging with context
 * - Performance monitoring
 * - Error tracking
 * - Dev tools integration
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

interface LogEntry {
  timestamp: number;
  level: LogLevel;
  message: string;
  context?: Record<string, any>;
  stack?: string;
  duration?: number;
}

interface LoggerConfig {
  level: LogLevel;
  enabled: boolean;
  maxEntries: number;
  enableDevTools: boolean;
  enableConsole: boolean;
}

class Logger {
  private static entries: LogEntry[] = [];
  private static config: LoggerConfig = {
    level: 'info',
    enabled: true,
    maxEntries: 500,
    enableDevTools: true,
    enableConsole: true,
  };

  private static readonly LEVEL_PRIORITY = {
    debug: 0,
    info: 1,
    warn: 2,
    error: 3,
  };

  /**
   * Configure logger
   */
  static configure(config: Partial<LoggerConfig>): void {
    this.config = { ...this.config, ...config };
  }

  /**
   * Log debug message
   */
  static debug(message: string, context?: Record<string, any>): void {
    this.log('debug', message, context);
  }

  /**
   * Log info message
   */
  static info(message: string, context?: Record<string, any>): void {
    this.log('info', message, context);
  }

  /**
   * Log warning
   */
  static warn(message: string, context?: Record<string, any>): void {
    this.log('warn', message, context);
  }

  /**
   * Log error with optional stack trace
   */
  static error(message: string, error?: Error | string, context?: Record<string, any>): void {
    const stack = error instanceof Error ? error.stack : undefined;
    const originalMessage =
      error instanceof Error
        ? error.message
        : typeof error === 'string'
        ? error
        : undefined;
    const messageWithError = originalMessage
      ? `${message}: ${originalMessage}`
      : message;
    this.log('error', messageWithError, { ...context, originalMessage, stack });
  }

  /**
   * Time an operation
   */
  static time<T>(label: string, fn: () => T): T {
    const start = performance.now();
    try {
      const result = fn();
      const duration = performance.now() - start;
      this.info(`⏱ ${label}: ${duration.toFixed(2)}ms`);
      return result;
    } catch (error) {
      const duration = performance.now() - start;
      this.error(`⏱ ${label} failed after ${duration.toFixed(2)}ms`, error instanceof Error ? error : String(error));
      throw error;
    }
  }

  /**
   * Time an async operation
   */
  static async timeAsync<T>(label: string, fn: () => Promise<T>): Promise<T> {
    const start = performance.now();
    try {
      const result = await fn();
      const duration = performance.now() - start;
      this.info(`⏱ ${label}: ${duration.toFixed(2)}ms`);
      return result;
    } catch (error) {
      const duration = performance.now() - start;
      this.error(`⏱ ${label} failed after ${duration.toFixed(2)}ms`, error instanceof Error ? error : String(error));
      throw error;
    }
  }

  /**
   * Redact sensitive values from log messages and context.
   * Matches tokens, passwords, secrets, keys, and authorization headers.
   * Implements C-5: Protection against credential leakage (P-UI-005).
   */
  private static readonly SENSITIVE_PATTERNS = [
    /(?:token|password|secret|api_?key|authorization|credential|passwd|access_?token|refresh_?token|bearer)\s*[:=]\s*\S+/gi,
    /Bearer\s+\S+/gi,  // Simplified: any Bearer token
    /eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_.+/=]*/g, // JWT tokens
    /"[^"]*(?:token|password|secret|key|credential)[^"]*":\s*"[^"]*"/gi, // JSON key-value pairs
  ];

  private static readonly SENSITIVE_KEYS = [
    'token',
    'refreshtoken',
    'password',
    'secret',
    'apikey',
    'api_key',
    'authorization',
    'credential',
    'credentials',
    'passwd',
    'accesstoken',
    'access_token',
    'refresh_token',
    'bearer',
    'authorization_header',
    'jwt',
  ];

  private static isSensitiveKey(key: string): boolean {
    const lk = key.toLowerCase();
    return this.SENSITIVE_KEYS.some((sensitiveKey) => {
      return (
        lk === sensitiveKey ||
        lk.startsWith(`${sensitiveKey}_`) ||
        lk.endsWith(`_${sensitiveKey}`)
      );
    });
  }

  private static redact(text: string): string {
    let result = text;
    for (const pattern of this.SENSITIVE_PATTERNS) {
      result = result.replace(pattern, "[REDACTED]");
    }
    return result;
  }

  private static redactContext(ctx: Record<string, any> | undefined): Record<string, any> | undefined {
    if (!ctx) return ctx;
    const redacted: Record<string, any> = {};
    for (const [key, value] of Object.entries(ctx)) {
      const isSensitive = this.isSensitiveKey(key);

      if (isSensitive) {
        redacted[key] = "[REDACTED]";
      } else if (typeof value === "string") {
        redacted[key] = this.redact(value);
      } else if (typeof value === "object" && value !== null) {
        // Recursively redact nested objects
        redacted[key] = this.redactContext(value);
      } else {
        redacted[key] = value;
      }
    }
    return redacted;
  }

  /**
   * Core logging function
   */
  private static log(
    level: LogLevel,
    message: string,
    context?: Record<string, any>
  ): void {
    if (!this.config.enabled || this.LEVEL_PRIORITY[level] < this.LEVEL_PRIORITY[this.config.level]) {
      return;
    }

    const entry: LogEntry = {
      timestamp: Date.now(),
      level,
      message: this.redact(message),
      context: this.redactContext(context),
    };

    // Store in memory
    this.entries.push(entry);
    if (this.entries.length > this.config.maxEntries) {
      this.entries.shift();
    }

    // Console output
    if (this.config.enableConsole) {
      this.outputToConsole(entry);
    }

    // Dev tools integration (skipped if not available)
    // if (this.config.enableDevTools && (globalThis as any).__DUCTA_LOGGER__) {
    //   (globalThis as any).__DUCTA_LOGGER__.addEntry(entry);
    // }

  }

  /**
   * Output to browser console
   */
  private static outputToConsole(entry: LogEntry): void {
    const prefix = `[${new Date(entry.timestamp).toISOString()}] [${entry.level.toUpperCase()}]`;
    const style = this.getConsoleStyle(entry.level);

    if (entry.context && Object.keys(entry.context).length > 0) {
      console.log(`%c${prefix} ${entry.message}`, style, entry.context);
    } else {
      console.log(`%c${prefix} ${entry.message}`, style);
    }
  }

  /**
   * Get console styling
   */
  private static getConsoleStyle(level: LogLevel): string {
    const styles: Record<LogLevel, string> = {
      debug: 'color: var(--text-dim); font-size: 12px;',
      info: 'color: var(--blue); font-weight: bold; font-size: 13px;',
      warn: 'color: var(--amber); font-weight: bold; font-size: 13px;',
      error: 'color: var(--red); font-weight: bold; font-size: 13px;',
    };
    return styles[level];
  }

  /**
   * Get all log entries
   */
  static getEntries(filter?: { level?: LogLevel; limit?: number }): LogEntry[] {
    let entries = this.entries;

    if (filter?.level) {
      entries = entries.filter(e => e.level === filter.level);
    }

    if (filter?.limit) {
      entries = entries.slice(-filter.limit);
    }

    return entries;
  }

  /**
   * Export logs as JSON
   */
  static exportLogs(): string {
    return JSON.stringify(this.entries, null, 2);
  }

  /**
   * Clear log history
   */
  static clear(): void {
    this.entries = [];
  }

  /**
   * Get statistics
   */
  static getStats(): {
    total: number;
    byLevel: Record<LogLevel, number>;
    oldest: number;
    newest: number;
  } {
    const byLevel = {
      debug: 0,
      info: 0,
      warn: 0,
      error: 0,
    };

    this.entries.forEach(e => {
      byLevel[e.level]++;
    });

    return {
      total: this.entries.length,
      byLevel,
      oldest: this.entries[0]?.timestamp ?? 0,
      newest: this.entries.at(-1)?.timestamp ?? 0,
    };
  }
}

// Make logger available globally
if (globalThis.window !== undefined) {
  (globalThis as any).__DUCTA_LOGGER__ ??= Logger;
}

export { Logger };
export default Logger;
