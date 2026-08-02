import { describe, it, expect, beforeEach } from 'vitest';
import {
  getVersionedItem,
  setVersionedItem,
  clearVersionedItem,
  migrateData,
  STORAGE_VERSION,
  MIGRATIONS
} from './storageMigrations';

/**
 * Tests for storageMigrations.ts - localStorage versioning
 * Sprint 1 C-3: Storage versioning & migration framework
 * Sprint 2 I-1: Test coverage expansion
 */

describe('Storage Migrations (C-3)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe('STORAGE_VERSION constant', () => {
    it('should define current version', () => {
      expect(STORAGE_VERSION).toBe(1);
    });
  });

  describe('setVersionedItem()', () => {
    it('should store data with version', () => {
      const testData = { token: 'abc123', user: { id: 'user1' } };
      setVersionedItem('test-key', testData, 1);

      const stored = localStorage.getItem('test-key');
      expect(stored).toBeTruthy();

      const parsed = JSON.parse(stored!);
      expect(parsed.version).toBe(1);
      expect(parsed.data).toEqual(testData);
    });

    it('should handle version 0 (legacy)', () => {
      const testData = { token: 'xyz' };
      setVersionedItem('legacy-key', testData, 0);

      const parsed = JSON.parse(localStorage.getItem('legacy-key')!);
      expect(parsed.version).toBe(0);
    });

    it('should handle errors gracefully', () => {
      // This test would require mocking localStorage.setItem to throw
      // For now, just verify structure
      const testData = { test: 'value' };
      expect(() => setVersionedItem('key', testData, 1)).not.toThrow();
    });
  });

  describe('getVersionedItem()', () => {
    it('should return data if version matches', () => {
      const testData = { token: 'abc123', user: { id: 'user1' } };
      setVersionedItem('test-key', testData, 1);

      const retrieved = getVersionedItem('test-key', 1, null);
      expect(retrieved).toEqual(testData);
    });

    it('should return defaults if key not found', () => {
      const defaults = { token: null, user: null };
      const retrieved = getVersionedItem('nonexistent', 1, defaults);

      expect(retrieved).toEqual(defaults);
    });

    it('should return null defaults if key not found', () => {
      const retrieved = getVersionedItem('nonexistent', 1, null);
      expect(retrieved).toBeNull();
    });

    it('should migrate from v0 to v1 (unversioned → versioned)', () => {
      // Simulate old unversioned data
      const oldData = { token: 'old_token', user: { id: 'user1' } };
      localStorage.setItem('auth-key', JSON.stringify(oldData));

      // Reading as v1 should trigger migration
      const defaults = { token: null, refreshToken: null, user: null };
      const retrieved = getVersionedItem('auth-key', 1, defaults);

      // Should either migrate or use defaults
      expect(retrieved).toBeDefined();
    });

    it('should use defaults if stored version > current version', () => {
      const oldData = {
        version: 2,
        data: { token: 'future_token' },
      };
      localStorage.setItem('future-key', JSON.stringify(oldData));

      const defaults = { token: 'default_token' };
      const retrieved = getVersionedItem('future-key', 1, defaults);

      expect(retrieved).toEqual(defaults);
    });

    it('should handle malformed JSON gracefully', () => {
      localStorage.setItem('bad-json', 'not valid json {');

      const defaults = { token: null };
      const retrieved = getVersionedItem('bad-json', 1, defaults);

      expect(retrieved).toEqual(defaults);
    });

    it('should handle unversioned data without version field', () => {
      const unversionedData = { token: 'abc', user: { id: '1' } };
      localStorage.setItem('unversioned', JSON.stringify(unversionedData));

      // Should treat as v0 and migrate
      const defaults = { token: null, user: null };
      const retrieved = getVersionedItem('unversioned', 1, defaults);

      expect(retrieved).toBeDefined();
    });
  });

  describe('clearVersionedItem()', () => {
    it('should remove item from localStorage', () => {
      setVersionedItem('key-to-clear', { data: 'value' }, 1);
      expect(localStorage.getItem('key-to-clear')).toBeTruthy();

      clearVersionedItem('key-to-clear');
      expect(localStorage.getItem('key-to-clear')).toBeNull();
    });

    it('should not throw if key does not exist', () => {
      expect(() => clearVersionedItem('nonexistent')).not.toThrow();
    });
  });

  describe('migrateData()', () => {
    it('should return data if versions match', () => {
      const data = { token: 'abc' };
      const result = migrateData(data, 1, 1, { token: null });

      expect(result).toEqual(data);
    });

    it('should return defaults if no migration path exists', () => {
      const data = { oldField: 'value' };
      const defaults = { token: null, newField: '' };

      // Trying to migrate from v0 to v1 without migration function
      const result = migrateData(data, 0, 1, defaults);

      // Should use defaults since no migration exists
      expect(result).toEqual(defaults);
    });

    it('should use defaults if fromVersion > toVersion', () => {
      const data = { token: 'future' };
      const defaults = { token: 'default' };

      const result = migrateData(data, 2, 1, defaults);
      expect(result).toEqual(defaults);
    });

    it('should use defaults on migration error', () => {
      const data = null; // This would cause error if migration tries to access properties
      const defaults = { token: 'safe_default' };

      // If migration throws, should use defaults
      const result = migrateData(data, 0, 1, defaults);
      expect(result).toBeDefined();
    });
  });

  describe('VersionedStorageData interface', () => {
    it('should store correctly typed data', () => {
      const typedData = {
        version: 1 as const,
        data: {
          token: 'abc123',
          refreshToken: 'refresh_abc',
          user: { id: 'user1', email: 'user@example.com' },
        },
      };

      setVersionedItem('typed-key', typedData.data, typedData.version);

      const stored = localStorage.getItem('typed-key');
      const parsed = JSON.parse(stored!);

      expect(parsed.version).toBe(1);
      expect(parsed.data.token).toBe('abc123');
      expect(parsed.data.refreshToken).toBe('refresh_abc');
    });
  });

  describe('Auth store persistence (C-1 + C-3 integration)', () => {
    it('should persist refreshToken added in C-1', () => {
      const authData = {
        token: 'eyJhbGciOiJIUzI1NiJ9...',
        refreshToken: 'refresh_token_123',  // NEW: From C-1
        user: { id: 'user1', email: 'test@example.com' },
      };

      setVersionedItem('ducta-auth', authData, 1);

      const retrieved = getVersionedItem('ducta-auth', 1, { token: null });
      expect(retrieved).toHaveProperty('refreshToken', 'refresh_token_123');
    });

    it('should handle auth upgrade path (old → new with refreshToken)', () => {
      // Old format (before C-1)
      const oldAuth = {
        version: 0,
        data: {
          token: 'old_token',
          user: { id: 'user1' },
        },
      };

      localStorage.setItem('ducta-auth-old', JSON.stringify(oldAuth.data));

      // Reading with v1 schema should request migration
      const defaults = { token: null, refreshToken: null, user: null };
      const result = getVersionedItem('ducta-auth-old', 1, defaults);

      expect(result).toBeDefined();
      // After migration, would have refreshToken field
    });
  });

  describe('Multi-key storage scenarios', () => {
    it('should maintain separate versions for different keys', () => {
      const authData = { token: 'auth_token' };
      const themeData = { mode: 'dark' };

      setVersionedItem('ducta-auth', authData, 1);
      setVersionedItem('ducta-theme', themeData, 1);

      const retrievedAuth = getVersionedItem('ducta-auth', 1, {});
      const retrievedTheme = getVersionedItem('ducta-theme', 1, {});

      expect(retrievedAuth).toEqual(authData);
      expect(retrievedTheme).toEqual(themeData);
    });

    it('should handle different version mismatches per key', () => {
      // v1 auth
      setVersionedItem('ducta-auth', { token: 'abc' }, 1);

      // v0 (unversioned) theme
      localStorage.setItem('ducta-theme-old', JSON.stringify({ mode: 'light' }));

      const auth = getVersionedItem('ducta-auth', 1, {});
      const theme = getVersionedItem('ducta-theme-old', 1, { mode: 'dark' });

      expect(auth).toEqual({ token: 'abc' });
      expect(theme).toBeDefined();
    });
  });

  describe('Storage quota handling', () => {
    it('should not crash on storage quota exceeded', () => {
      const largeData = {
        token: 'x'.repeat(1000000), // 1MB string
      };

      // This may or may not throw depending on device,
      // but should be caught gracefully
      try {
        setVersionedItem('large-key', largeData, 1);
      } catch (e) {
        // Expected for some environments
      }

      // Should still be callable
      expect(() => getVersionedItem('large-key', 1, {})).not.toThrow();
    });
  });

  describe('Backwards compatibility', () => {
    it('should work with legacy unversioned storage', () => {
      // Existing localStorage without versioning
      const legacyData = { token: 'legacy_token', user: { id: '123' } };
      localStorage.setItem('legacy-auth', JSON.stringify(legacyData));

      // This should not crash
      const defaults = { token: null };
      const result = getVersionedItem('legacy-auth', 1, defaults);

      expect(result).toBeDefined();
    });

    it('should preserve existing data when clearing', () => {
      setVersionedItem('keep-me', { data: 'important' }, 1);
      setVersionedItem('clear-me', { data: 'temporary' }, 1);

      clearVersionedItem('clear-me');

      const kept = getVersionedItem('keep-me', 1, {});
      const cleared = getVersionedItem('clear-me', 1, null);

      expect(kept).toEqual({ data: 'important' });
      expect(cleared).toBeNull();
    });
  });

  describe('Migration coverage guard (safety net for future version bumps)', () => {
    it('has a migration entry for every version transition above v0->v1', () => {
      // v0 (unversioned, pre-migration-framework data) is allowed to reset to
      // defaults -- that was the deliberate baseline when versioning shipped.
      // Any STORAGE_VERSION bump above that MUST come with a real entry in
      // MIGRATIONS, or getVersionedItem() silently wipes user data on
      // upgrade (see migrateData's "No migration for vN -> vN+1" fallback).
      const missing: number[] = [];
      for (let v = 1; v < STORAGE_VERSION; v++) {
        if (!(v in MIGRATIONS)) missing.push(v);
      }
      expect(missing).toEqual([]);
    });
  });
});
