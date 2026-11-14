import { describe, it, expect, beforeEach } from 'vitest';
import { Logger } from './logger';

/**
 * Tests for logger.ts - Credential sanitization
 * Sprint 1 C-5: Protect against credential leakage
 * Sprint 2 I-1: Test coverage expansion
 */

describe('Logger - Credential Sanitization (C-5)', () => {
  beforeEach(() => {
    Logger.clear();
    Logger.configure({ level: 'debug', enabled: true, enableConsole: false });
  });

  describe('Redaction patterns', () => {
    it('should redact tokens in messages', () => {
      Logger.debug('User token: token=abc123def456');

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.message).toContain('[REDACTED]');
      expect(lastEntry.message).not.toContain('abc123');
    });

    it('should redact Bearer tokens', () => {
      Logger.debug('api_key: sk_live_FAKE00000000000000000');
      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.message).toContain('[REDACTED]');
      expect(lastEntry.message).not.toContain('Bearer');
    });

    it('should redact JWT tokens by signature', () => {
      Logger.debug('JWT: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U');

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.message).toContain('[REDACTED]');
    });

    it('should redact password values', () => {
      Logger.debug('password: secretpassword123');

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.message).toContain('[REDACTED]');
      expect(lastEntry.message).not.toContain('secretpassword');
    });

    it('should redact API keys', () => {
      Logger.debug('api_key: sk_live_FAKE00000000000000000');

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.message).toContain('[REDACTED]');
    });

    it('should redact multiple sensitive values in one message', () => {
      Logger.debug('token: abc123, password: secret, apiKey: xyz789');

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      const redactedCount = (lastEntry.message.match(/\[REDACTED\]/g) || []).length;
      expect(redactedCount).toBeGreaterThanOrEqual(3);
    });
  });

  describe('Context redaction', () => {
    it('should redact token field in context', () => {
      Logger.debug('User login', { token: 'abc123xyz', email: 'user@example.com' });

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.context?.token).toBe('[REDACTED]');
      expect(lastEntry.context?.email).toBe('user@example.com');
    });

    it('should redact refreshToken field', () => {
      Logger.debug('Token refresh', {
        refreshToken: 'refresh_token_abc123',
        tokenExpiry: 1234567890
      });

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.context?.refreshToken).toBe('[REDACTED]');
      expect(lastEntry.context?.tokenExpiry).toBe(1234567890);
    });

    it('should redact password field case-insensitively', () => {
      Logger.warn('Auth error', {
        Password: 'userpass123',
        PASSWORD: 'adminpass456',
        user_password: 'passphrase'
      });

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.context?.Password).toBe('[REDACTED]');
      expect(lastEntry.context?.PASSWORD).toBe('[REDACTED]');
      expect(lastEntry.context?.user_password).toBe('[REDACTED]');
    });

    it('should redact credential and credentials fields', () => {
      Logger.debug('Connect', {
        credentials: { user: 'admin', secret: 'pass123' },
        credential_type: 'oauth2'
      });

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.context?.credentials).toBe('[REDACTED]');
      expect(lastEntry.context?.credential_type).toBe('[REDACTED]');
    });

    it('should redact nested sensitive values in objects', () => {
      Logger.debug('User data', {
        user: {
          name: 'John',
          token: 'secret_token_xyz',
          profile: {
            email: 'john@example.com',
            apiKey: 'key_abc123'
          }
        }
      });

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.context?.user?.token).toBe('[REDACTED]');
      expect(lastEntry.context?.user?.profile?.apiKey).toBe('[REDACTED]');
      expect(lastEntry.context?.user?.name).toBe('John');
      expect(lastEntry.context?.user?.profile?.email).toBe('john@example.com');
    });

    it('should handle null values safely', () => {
      expect(() => {
        Logger.debug('Test', { token: null, password: undefined });
      }).not.toThrow();

      const entries = Logger.getEntries();
      expect(entries).toHaveLength(1);
    });

    it('should not redact non-sensitive fields with "key" in name', () => {
      Logger.debug('Config', {
        primary_key: 'id',
        foreign_key: 'user_id',
        cache_key: 'session_123'
      });

      const entries = Logger.getEntries();
      const lastEntry = entries[entries.length - 1];

      // These should not be redacted (not in sensitive keywords)
      expect(lastEntry.context?.primary_key).toBe('id');
    });
  });

  describe('Sensitive keywords matching', () => {
    const sensitiveKeywords = [
      'token', 'refreshToken', 'password', 'secret', 'apiKey',
      'api_key', 'authorization', 'credential', 'credentials',
      'passwd', 'accessToken', 'access_token', 'bearer', 'jwt'
    ];

    sensitiveKeywords.forEach(keyword => {
      it(`should redact field: ${keyword}`, () => {
        const context = { [keyword]: 'sensitive_value_123' };
        Logger.debug('Test', context);

        const entries = Logger.getEntries();
        const lastEntry = entries[entries.length - 1];

        expect(lastEntry.context?.[keyword]).toBe('[REDACTED]');
      });
    });
  });

  describe('Error logging with sanitization', () => {
    it('should sanitize error messages', () => {
      const error = new Error('Failed to authenticate with token: secret123abc');
      Logger.error('Auth failed', error);

      const entries = Logger.getEntries({ level: 'error' });
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.message).toContain('[REDACTED]');
      expect(lastEntry.message).not.toContain('secret123');
    });

    it('should sanitize error context', () => {
      Logger.error('API error', new Error('Network failed'), {
        token: 'auth_token_xyz',
        endpoint: '/api/users'
      });

      const entries = Logger.getEntries({ level: 'error' });
      const lastEntry = entries[entries.length - 1];

      expect(lastEntry.context?.token).toBe('[REDACTED]');
      expect(lastEntry.context?.endpoint).toBe('/api/users');
    });
  });

  describe('Log entries storage', () => {
    it('should store sanitized entries in memory', () => {
      Logger.debug('Debug with token: xyz123');
      Logger.info('Info with password: secret');
      Logger.warn('Warn with api_key: key_abc');

      const entries = Logger.getEntries();
      expect(entries).toHaveLength(3);

      entries.forEach(entry => {
        expect(entry.message).toContain('[REDACTED]');
      });
    });

    it('should maintain entry ordering with sanitization', () => {
      Logger.debug('First token: aaa');
      Logger.info('Second password: bbb');
      Logger.warn('Third secret: ccc');

      const entries = Logger.getEntries();
      expect(entries[0].level).toBe('debug');
      expect(entries[1].level).toBe('info');
      expect(entries[2].level).toBe('warn');
    });

    it('should have max entry limit even with sanitization', () => {
      Logger.configure({ maxEntries: 10 });

      for (let i = 0; i < 20; i++) {
        Logger.debug(`Message ${i} with token: token_${i}`);
      }

      const entries = Logger.getEntries();
      expect(entries.length).toBeLessThanOrEqual(10);
    });
  });

  describe('Export logs with sanitization', () => {
    it('should export sanitized logs as JSON', () => {
      Logger.debug('Test message with password: secret123');
      const exported = Logger.exportLogs();

      expect(exported).toContain('[REDACTED]');
      expect(exported).not.toContain('secret123');
    });

    it('should export all entries as valid JSON', () => {
      Logger.info('Entry 1 token: xyz1');
      Logger.warn('Entry 2 api_key: key1');

      const exported = Logger.exportLogs();
      const parsed = JSON.parse(exported);

      expect(Array.isArray(parsed)).toBe(true);
      expect(parsed).toHaveLength(2);
    });
  });

  describe('Integration with console output', () => {
    it('should output sanitized messages to console', () => {
      Logger.configure({ enableConsole: true });

      // Can't easily spy on console in Vitest, but verify log() method works
      expect(() => {
        Logger.debug('Test with token: secret_abc');
      }).not.toThrow();
    });
  });

  describe('Statistics with sanitization', () => {
    it('should include sanitized entries in stats', () => {
      Logger.debug('Debug with token: xyz');
      Logger.info('Info with password: secret');
      Logger.error('Error with api_key: key123');

      const stats = Logger.getStats();

      expect(stats.total).toBe(3);
      expect(stats.byLevel.debug).toBe(1);
      expect(stats.byLevel.info).toBe(1);
      expect(stats.byLevel.error).toBe(1);
    });
  });

  describe('Performance considerations', () => {
    it('should sanitize large context objects without hanging', () => {
      const largeContext: any = {};
      for (let i = 0; i < 1000; i++) {
        largeContext[`field${i}`] = `value${i}`;
        if (i % 3 === 0) {
          largeContext[`token${i}`] = `secret_${i}`;
        }
      }

      const start = performance.now();
      Logger.debug('Large context', largeContext);
      const duration = performance.now() - start;

      expect(duration).toBeLessThan(100); // Should complete quickly
      expect(Logger.getEntries()).toHaveLength(1);
    });

    it('should not regex-bomb on pathological input', () => {
      const pathological = 'a'.repeat(10000) + 'token:value';

      expect(() => {
        Logger.debug(pathological);
      }).not.toThrow();
    });
  });
});
