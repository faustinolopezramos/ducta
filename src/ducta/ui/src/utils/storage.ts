/**
 * Centralized LocalStorage abstraction for the Ducta UI.
 * Provides typed methods for accessing stored system preferences and state.
 * Implements C-3: Version-aware storage with automatic migrations.
 */

import { getVersionedItem, setVersionedItem, clearVersionedItem, STORAGE_VERSION } from "./storageMigrations";

const STORAGE_KEYS = {
  SOURCE: 'ducta:selected-source',
  AUTH: 'ducta-auth',
  RECENT_SOURCES: 'ducta:recent-sources',
};

export const StorageService = {
  // Source Setters & Getters
  getSource(): string | null {
    return localStorage.getItem(STORAGE_KEYS.SOURCE);
  },

  setSource(sourcePath: string): void {
    localStorage.setItem(STORAGE_KEYS.SOURCE, sourcePath);
  },

  clearSource(): void {
    localStorage.removeItem(STORAGE_KEYS.SOURCE);
  },

  // Recent sources — most-recent-first, capped, deduped.
  getRecentSources(): string[] {
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.RECENT_SOURCES);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.filter((s): s is string => typeof s === "string") : [];
    } catch {
      return [];
    }
  },

  addRecentSource(sourcePath: string, max = 8): void {
    if (!sourcePath) return;
    try {
      const existing = this.getRecentSources().filter((s) => s !== sourcePath);
      const next = [sourcePath, ...existing].slice(0, max);
      localStorage.setItem(STORAGE_KEYS.RECENT_SOURCES, JSON.stringify(next));
    } catch (error) {
      console.warn("Error updating recent sources:", error);
    }
  },

  // Auth Setters & Getters (Used by Zustand indirectly, or for bare reading)
  getAuthData(): string | null {
    return localStorage.getItem(STORAGE_KEYS.AUTH);
  },

  clearAuthData(): void {
    localStorage.removeItem(STORAGE_KEYS.AUTH);
  },

  // Generic Getters & Setters with JSON parsing and version support (C-3)
  getItem<T>(key: string, defaultValue: T | null = null): T | null {
    try {
      return getVersionedItem<T | null>(key, STORAGE_VERSION, defaultValue);
    } catch (error) {
      console.warn(`Error reading versioned item "${key}":`, error);
      return defaultValue;
    }
  },

  setItem<T>(key: string, value: T): void {
    try {
      setVersionedItem<T>(key, value, STORAGE_VERSION);
    } catch (error) {
      console.warn(`Error setting versioned item "${key}":`, error);
    }
  },

  clearItem(key: string): void {
    try {
      clearVersionedItem(key);
    } catch (error) {
      console.warn(`Error clearing item "${key}":`, error);
    }
  },

};
