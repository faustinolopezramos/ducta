// ─────────────────────────────────────────────
// STORAGE MIGRATIONS — Version management for localStorage
// Implements C-3: Schema versioning and migration framework
// ─────────────────────────────────────────────

export const STORAGE_VERSION = 1;

export interface VersionedStorageData<T> {
  version: number;
  data: T;
}

/**
 * Migration function type.
 * Transforms data from previousVersion to the next version.
 */
type MigrationFn = (data: any) => any;

/**
 * Migration map: takes data from version N and returns migrated data for version N+1.
 * If no migration exists for a version, data is replaced with defaults.
 */
export const MIGRATIONS: Record<number, MigrationFn> = {
  // Example: Version 0->1 migration
  // 0: (data) => ({
  //   ...data,
  //   newField: 'default_value'
  // }),
};

/**
 * Migrate data from one version to another.
 * Applies all intermediate migrations sequentially.
 * If fromVersion > toVersion or migration fails, returns defaultData.
 *
 * @param data The stored data
 * @param fromVersion Current version
 * @param toVersion Target version
 * @param defaultData Default data if migration fails
 * @returns Migrated data or defaults
 */
export function migrateData<T>(
  data: any,
  fromVersion: number,
  toVersion: number,
  defaultData: T
): T {
  if (fromVersion > toVersion) {
    console.warn(`[Storage] Cannot migrate from v${fromVersion} to v${toVersion}. Using defaults.`);
    return defaultData;
  }

  let current = data;

  for (let v = fromVersion; v < toVersion; v++) {
    const migration = MIGRATIONS[v];
    if (!migration) {
      console.warn(`[Storage] No migration for v${v} -> v${v + 1}. Using defaults.`);
      return defaultData;
    }

    try {
      current = migration(current);
    } catch (error) {
      console.error(`[Storage] Migration v${v} -> v${v + 1} failed:`, error);
      return defaultData;
    }
  }

  return current as T;
}

/**
 * Apply version-aware getItem with automatic migration.
 *
 * @param key Storage key
 * @param currentVersion Current expected version
 * @param defaultData Default data if key not found or migration needed
 * @returns Migrated data or defaults
 */
export function getVersionedItem<T>(
  key: string,
  currentVersion: number,
  defaultData: T
): T {
  try {
    const item = localStorage.getItem(key);
    if (!item) return defaultData;

    const parsed = JSON.parse(item) as VersionedStorageData<T>;

    // If version field doesn't exist, it's unversioned data (v0)
    if (typeof parsed.version !== "number") {
      console.warn(`[Storage] Key "${key}" is unversioned. Migrating as v0.`);
      return migrateData(parsed, 0, currentVersion, defaultData);
    }

    if (parsed.version === currentVersion) {
      return parsed.data;
    }

    if (parsed.version > currentVersion) {
      console.warn(`[Storage] Key "${key}" is v${parsed.version}, but app expects v${currentVersion}. Using defaults.`);
      return defaultData;
    }

    // Migrate from stored version to current version
    return migrateData(parsed.data, parsed.version, currentVersion, defaultData);
  } catch (error) {
    console.error(`[Storage] Error reading "${key}":`, error);
    return defaultData;
  }
}

/**
 * Apply version-aware setItem.
 *
 * @param key Storage key
 * @param data Data to store
 * @param version Version to store with data
 */
export function setVersionedItem<T>(key: string, data: T, version: number): void {
  try {
    const versioned: VersionedStorageData<T> = { version, data };
    localStorage.setItem(key, JSON.stringify(versioned));
  } catch (error) {
    console.warn(`[Storage] Error setting "${key}":`, error);
  }
}

/**
 * Clear a versioned item from storage.
 */
export function clearVersionedItem(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch (error) {
    console.error(`[Storage] Error clearing "${key}":`, error);
  }
}
